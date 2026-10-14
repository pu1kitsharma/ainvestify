"""Generic economic-field binding rejects unlabeled USD values as revenue."""
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_source_unit_author as author, rationale_evidence
from tests.research.test_memo_causal_review import sample
from tests.research.test_memo_source_unit_author import PIN
from tests.research.test_rationale_evidence import Model as Characterizer, PIN as REVIEW_PIN


TABLE = 'Partnership schedule\nGo live date | Potential USD Mn\nHistorical live status | 0.34\nFuture scheduled status | 0.93'


def fixture():
    memo, sources = sample()
    source = {**sources[0], 'id': 'S4', 'passage': TABLE}
    sources.append(source)
    memo['recommendation_claims'].append({'source_id': 'S4', 'quote': TABLE,
        'assertion': 'The source reports partnership schedules and monetary values without naming their economic measure.'})
    rows = []
    result = rationale_evidence.characterize_sources(sources, REVIEW_PIN, rows, lambda: None,
        Characterizer(), PreparationBudget(60, max_calls=2, max_requests=2))
    return memo, sources, {'attempts': rows, 'result': result}


class Model:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == author.TASK_V4
        payload = json.loads(evidence)
        if payload['unit_id'].startswith('r_'):
            sid = payload['unit_source_ids'][0]
            text = 'The registry source reports uncertain completion status and current cash availability; dated records would help inform further diligence.'
            if sid == 'S4':
                if not payload.get('correction_number'):
                    text = 'The company reports partnership revenue of USD 0.34 million and further potential growth in its future schedule.'
                else:
                    assert 'Economic metric "revenue"' in payload['validation_error']
                    text = 'The source reports potential partnership amounts and scheduled statuses without naming the economic measure represented by those amounts.'
            obj = {'recommendation': 'defer_pending_evidence',
                'supporting_evidence_id': next(iter(payload['sources'][sid]['spans'])),
                'reported_scope': 'mixed', 'standalone_text': text}
        else:
            obj = {'question': 'What operating cash is currently available to the company?',
                'conditional_importance': 'If reviewed cash records were available, they would help assess operating runway.',
                'requested_records': 'Reviewed bank and account records showing current operating cash availability.',
                'requested_time_basis': 'current'}
        self.last_response_text = json.dumps(obj)
        self.last_route = {'model': self.name, **author.OPTIONS_V2}
        return schema.model_validate(obj)


def test_metric_binding_runs_before_numeric_scale_error_and_preserves_raw_source():
    memo, sources, proof = fixture()
    rows, model = [], Model()
    for _ in range(5):
        record = author.run_author(memo, sources, proof, PIN, rows, lambda: None, model,
            PreparationBudget(105, max_calls=6, max_requests=6), contract=author.CONTRACT_V4)
    assert record['state'] == 'accepted'
    assert rows[1]['answer']['standalone_text'].find('revenue of USD 0.34 million') >= 0
    assert 'Economic metric "revenue"' in rows[2]['input']['validation_error']
    assert 'revenue' not in record['answer']['recommendation_units']['S4']['standalone_text']
    assert sources[-1]['passage'] == TABLE
    assert record['memo']['recommendation_claims'][-1]['quote'] == TABLE
    assert author.run_author(memo, sources, proof, PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=author.CONTRACT_V4) == record


def test_unlabeled_monetary_assertion_without_metric_word_is_also_blocked():
    with pytest.raises(ValueError, match='no explicit economic metric label'):
        author._metric_binding('The source reports USD 0.34 for partnerships.', TABLE)
    author._metric_binding('The source reports potential partnership amounts.', TABLE)
    author._metric_binding('The source reports EBITDA losses.', 'Reported EBITDA losses')
    with pytest.raises(ValueError, match='Economic metric "income"'):
        author._metric_binding('The company reports income.', 'reported Revenue')


def test_v3_requests_and_instruction_are_preserved():
    memo, sources, proof = fixture()
    _, _, v3, _ = author.frozen_unit_requests(memo, sources, proof, PIN, contract=author.CONTRACT_V3)
    assert all(payload['contract'] == author.CONTRACT_V3 for _, payload, _ in v3)
    assert 'EXACT FIELD BINDING' not in author.INSTRUCTION_V3
    assert 'EXACT FIELD BINDING' in author.INSTRUCTION_V4
