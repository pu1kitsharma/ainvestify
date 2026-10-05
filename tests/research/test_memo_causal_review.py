"""Frozen synthetic memo consequence review and exact raw replay."""
import copy
import json

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_causal_review as causal


def sample():
    fixture = json.load(open('tests/fixtures/public_memo/sparse_conflict.synthetic.json'))
    sources = fixture['sources']
    claim = {'source_id': 'S1',
             'quote': 'The transaction completion status is unknown, and the entry does not state current cash availability.',
             'assertion': 'The registry entry leaves the reported financing status and current cash availability unknown.'}
    analysis = ('The synthetic registry lists a reported financing round, while its completion '
                'status and current cash availability remain unknown [S1]. The diligence team '
                'should request dated transaction and account records before treating the '
                'listed round as available operating capital [S1].')
    memo = {'recommendation': 'defer_pending_evidence',
            'recommendation_reason': analysis,
            'recommendation_claims': [claim],
            'investment_thesis': {'heading': 'Investment thesis', 'analysis': analysis,
                                  'claims': [claim]},
            'business_and_market': {'heading': 'Business and market', 'analysis': analysis,
                                    'claims': [claim]},
            'differentiation_and_execution': {'heading': 'Differentiation and execution',
                                              'analysis': analysis, 'claims': [claim]},
            'risks_and_countercase': {'heading': 'Risks and countercase',
                                      'analysis': analysis, 'claims': [claim]},
            'diligence_plan': {'heading': 'Diligence plan',
                               'analysis': analysis, 'claims': [claim]},
            'unknowns': [
                {'question': 'Did the reported financing actually close?',
                 'why_it_matters': 'A registry listing alone does not establish cash available to operations.',
                 'evidence_needed': 'Dated closing and account records from the company.'},
                {'question': 'What operating cash is available today?',
                 'why_it_matters': 'The source gives no verified cash position for diligence.',
                 'evidence_needed': 'Current reviewed bank and management records.'}]}
    return memo, sources


CONTRACT = {'version': causal.CONTRACT, 'model_name': 'qwen3.5:9b',
            'model_digest': 'sha256:synthetic'}


class Reviewer:
    name = 'qwen3.5:9b'
    thinking = False
    max_tokens = 1400
    context_tokens = 8192
    temperature = 0

    def __init__(self, *, malformed=False):
        self.calls = 0
        self.malformed = malformed
        self.last_response_text = ''
        self.last_route = {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == causal.TASK and instruction == causal.INSTRUCTION
        self.calls += 1
        payload = json.loads(evidence)
        answer = {}
        for row in payload['rows']:
            defect = 'forces immediate fundraising or asset liquidation' in row['sentence']
            answer[row['row_id']] = {
                'relation': causal.UNSUPPORTED if defect else
                            causal.CONDITIONAL if 'should request' in row['sentence'] else
                            causal.SOURCE_SUPPORTED,
                'challenged_clause': 'forces immediate fundraising or asset liquidation'
                                      if defect else None,
                'premise_source_ids': row['premise_ids'],
                'reason': ('The cited registry does not establish this compulsory business outcome.'
                           if defect else 'This statement preserves source limits or proposes a check.')}
        if self.malformed:
            answer.pop(payload['rows'][0]['row_id'])
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **causal.OPTIONS}
        return schema.model_validate_json(self.last_response_text)


def run(memo, sources, model, attempts, contract=CONTRACT):
    result = None
    for _ in causal.frozen_calls(memo, sources, contract):
        result = causal.review_memo_causal_claims(memo, sources, attempts,
            lambda: None, model, PreparationBudget(60, max_calls=1, max_requests=1),
            contract=contract)
        if result['state'] != 'needs_resume':
            break
    return result


def test_exact_source_scoped_rows_and_consequence_block_with_replay():
    memo, sources = sample()
    memo['diligence_plan']['analysis'] += (' An adverse result forces immediate fundraising '
                                            'or asset liquidation.')
    calls = causal.frozen_calls(memo, sources, CONTRACT)
    assert sum(len(call[1]) for call in calls) == 13
    assert len(calls) == 5 and all(len(call[1]) <= 3 for call in calls)
    target = next(row for call in calls for row in call[1]
                  if 'forces immediate fundraising' in row['sentence'])
    assert target['sentence_id'] == 'diligence_plan.sentence_3'
    assert target['premise_ids'] == ['S1'] and target['source_evidence'][0]['exact_quotes'] == [
        memo['diligence_plan']['claims'][0]['quote']]
    assert sources[0]['passage'] in calls[-1][2]['source_table']['S1']['full_passage']
    attempts, model = [], Reviewer()
    result = run(memo, sources, model, attempts)
    assert result['state'] == 'blocked' and result['reason'] == 'memo_causal_review_blocked'
    finding, = result['review']['findings']
    assert finding['sentence_id'] == target['sentence_id']
    assert finding['challenged_clause'] in finding['sentence']
    assert finding['premise_source_ids'] == ['S1'] and model.calls == 5
    assert all(row['response_hash'] for row in attempts)
    before = json.dumps(attempts)
    assert run(memo, sources, Reviewer(), attempts) == result
    assert json.dumps(attempts) == before


def test_conditional_and_attributed_control_accepts_but_missing_row_blocks():
    memo, sources = sample()
    attempts, model = [], Reviewer()
    result = run(memo, sources, model, attempts)
    assert result['state'] == 'accepted' and result['review']['findings'] == []
    assert model.calls == 4
    bad_attempts, bad_model = [], Reviewer(malformed=True)
    blocked = run(memo, sources, bad_model, bad_attempts)
    assert blocked['state'] == 'blocked'
    assert blocked['reason'] == 'memo_causal_malformed_answer'
    assert bad_model.calls == 1


def test_changed_quote_or_raw_response_cannot_replay():
    memo, sources = sample()
    changed = copy.deepcopy(memo)
    changed['diligence_plan']['claims'][0]['quote'] = 'An invented source excerpt is not present.'
    with pytest.raises(ValueError, match='not exact source text'):
        causal.frozen_calls(changed, sources, CONTRACT)
    attempts = []
    run(memo, sources, Reviewer(), attempts)
    attempts[0]['raw_response'] += ' '
    with pytest.raises(ValueError, match='raw response changed'):
        causal.evaluate_attempts(memo, sources, attempts, CONTRACT)


V2_CONTRACT = {**CONTRACT, 'version': causal.CONTRACT_V2}


class BinaryReviewer(Reviewer):
    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == causal.TASK_V2 and instruction == causal.INSTRUCTION_V2
        self.calls += 1
        payload = json.loads(evidence)
        answer = {}
        for row in payload['rows']:
            defect = 'forces immediate fundraising or asset liquidation' in row['sentence']
            answer[row['row_id']] = {
                'relation': causal.UNSUPPORTED if defect else 'no_unsupported_consequence',
                'focus_clause_id': 'c00', 'premise_source_ids': row['premise_ids'],
                'reason': ('The source does not establish a forced business outcome.' if defect
                           else 'The statement reports uncertainty or proposes conditional work.')}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **causal.OPTIONS}
        return schema.model_validate_json(self.last_response_text)


def test_v2_binary_task_binds_enumerated_clause_and_preserves_v1_replay():
    control, sources = sample()
    defect = copy.deepcopy(control)
    defect['diligence_plan']['analysis'] += (' An adverse result forces immediate fundraising '
                                             'or asset liquidation.')
    calls = causal.frozen_calls(defect, sources, V2_CONTRACT)
    assert all('clauses' in row for call in calls for row in call[2]['rows'])
    target = next(row for call in calls for row in call[2]['rows']
                  if 'asset liquidation' in row['sentence'])
    assert target['clauses']['c00'] == target['sentence']
    control_attempts, defect_attempts = [], []
    passed = run(control, sources, BinaryReviewer(), control_attempts, V2_CONTRACT)
    blocked = run(defect, sources, BinaryReviewer(), defect_attempts, V2_CONTRACT)
    assert passed['state'] == 'accepted' and passed['review']['findings'] == []
    assert blocked['state'] == 'blocked' and len(blocked['review']['findings']) == 1
    finding = blocked['review']['findings'][0]
    assert finding['sentence_id'] == 'diligence_plan.sentence_3'
    assert finding['challenged_clause'] == target['sentence']
    assert run(defect, sources, BinaryReviewer(), defect_attempts, V2_CONTRACT) == blocked
