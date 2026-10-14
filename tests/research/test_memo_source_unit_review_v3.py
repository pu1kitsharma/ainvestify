"""Grouped replay, source boundaries and strict semantic blocking."""
import copy
import json
from types import SimpleNamespace
import pytest
from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_source_unit_review as base
from agents.research import memo_source_unit_review_v3 as review

PIN = {'name': 'local-reviewer', 'digest': 'a' * 64}


def fixture(monkeypatch):
    spans = {f'S{n}.e{e:03d}': {'source_id': f'S{n}', 'start': e * 10,
              'end': e * 10 + 10, 'exact_text': 'A synthetic source context or displayed claim.'}
             for n in (1, 2, 3) for e in (1, 2)}
    cards = {f'S{n}': {'reporting_basis': 'historical',
        'contains_explicit_incomplete_quantification_claim': False} for n in (1, 2, 3)}
    units = {f'r_S{n}': {'exact_text': 'The company reports a dated historical claim.',
        'required_function': 'investment_rationale', 'requested_time_basis': 'historical',
        'eligible_evidence_ids': [f'S{n}.e001']} for n in (1, 2)}
    for n in (0, 1):
        for field, function in [('question', 'inquiry'), ('conditional_importance', 'conditional_importance'),
                                ('requested_records', 'record_request')]:
            units[f'u{n}_{field}'] = {'exact_text': 'Which dated records would test this reported claim?',
                'required_function': function, 'requested_time_basis': 'historical',
                'eligible_evidence_ids': [f'S{n + 1}.e001', f'S{n + 1}.e002']}
    payload = {'contract': 'old', 'units': units, 'evidence_spans': spans, 'source_cards': cards,
               'source_versions': {f'S{n}': f'v{n}' for n in (1, 2, 3)},
               'base_memo_digest': 'b' * 64, 'revised_memo_digest': 'c' * 64,
               'author_response_hash': 'd' * 64, 'source_proof_hash': 'e' * 64}
    views = {key: {'text': unit['exact_text'], 'required_function': unit['required_function'],
        'requested_time_basis': unit['requested_time_basis'],
        'evidence_spans': {eid: {k: spans[eid][k] for k in ('source_id', 'exact_text')}
                           for eid in unit['eligible_evidence_ids']}, 'source_cards': cards}
        for key, unit in units.items()}
    monkeypatch.setattr(base, 'frozen_request', lambda *args: (copy.deepcopy(payload), None, copy.deepcopy(views)))
    return {'memo': {'synthetic': 'record'}, 'state': 'accepted'}


class Model:
    name = PIN['name']
    def __init__(self, flag=None, malformed=False):
        self.__dict__.update(review.OPTIONS)
        self.calls, self.flag, self.malformed = 0, flag, malformed
    def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
        self.calls += 1
        self.last_route = {'model': self.name, **review.OPTIONS}
        payload = json.loads(evidence)
        judgments = {}
        for key, unit in payload['units'].items():
            factual = unit['required_function'] == 'investment_rationale'
            eid = unit['eligible_evidence_ids'][0] if factual else None
            judgments[key] = {'function': unit['required_function'], 'evidence_id': eid,
                'source_time_basis': 'historical' if factual else 'not_applicable',
                'asserted_time_basis': 'historical' if factual else 'not_applicable',
                'quantification_scope': 'source_stated' if factual else 'not_applicable',
                'requires_explicit_quantification_claim': False, 'has_unsupported_premise': False,
                'preserves_time_scope': True, 'preserves_source_attribution': True,
                'has_unsupported_metric_interpretation': False,
                'reason': 'The wording preserves the reported source scope.',
                'relation': 'supported_fact' if factual else 'conditional_question'}
        if self.flag:
            key = next(iter(judgments))
            judgments[key][self.flag] = self.flag != 'preserves_source_attribution'
        if self.malformed and self.calls == 1:
            next(iter(judgments.values())).pop('preserves_source_attribution')
        answer = {'judgments': judgments}
        self.last_response_text = json.dumps(answer)
        return schema.model_validate(answer)


def invoke(authored, rows, model=None, budget=None):
    return review.run_review({}, [], {}, authored, PIN, PIN, rows, lambda: None,
                             model, budget or PreparationBudget(105, max_calls=6, max_requests=6))


def test_groups_filter_evidence_and_keep_context_without_quote_rescue(monkeypatch):
    authored = fixture(monkeypatch)
    groups = review.frozen_requests({}, [], {}, authored, PIN, PIN)
    assert [group[0] for group in groups] == ['recommendation', 'u0', 'u1']
    rec = groups[0][1]
    assert set(rec['evidence_spans']) == {'S1.e001', 'S2.e001'}
    assert set(rec['source_context_spans']) == {'S1.e001', 'S1.e002', 'S2.e001', 'S2.e002'}
    assert set(rec['source_cards']) == set(rec['source_versions']) == {'S1', 'S2'}
    assert rec['units']['r_S1']['eligible_evidence_ids'] == ['S1.e001']
    assert set(groups[1][1]['units']) == {'u0_question', 'u0_conditional_importance', 'u0_requested_records'}
    assert set(groups[1][1]['source_cards']) == {'S1'}


def test_three_calls_merge_only_exact_recorded_judgments_and_replay(monkeypatch):
    authored, rows, model = fixture(monkeypatch), [], Model()
    for _ in range(3):
        result = invoke(authored, rows, model)
    assert result['state'] == 'accepted' and model.calls == 3
    assert len(result['answer']['judgments']) == 8
    assert len(result['response_ids']) == len(result['response_hashes']) == 3
    assert all(value == 'unresolved' for value in result['unknown_status'].values())
    assert invoke(authored, rows) == result
    assert result['response_hash'] == digest([{'id': row['id'], 'hash': row['response_hash']} for row in rows])
    changed = copy.deepcopy(rows)
    changed[1]['input']['source_versions']['S1'] = 'different-version'
    with pytest.raises(ValueError, match='frozen contract'):
        invoke(authored, changed)


@pytest.mark.parametrize('flag', ['preserves_source_attribution', 'has_unsupported_metric_interpretation'])
def test_semantic_defects_block_without_correction_or_later_groups(monkeypatch, flag):
    authored, rows, model = fixture(monkeypatch), [], Model(flag=flag)
    result = invoke(authored, rows, model)
    assert result['state'] == 'blocked' and result['findings']
    assert model.calls == 1
    assert invoke(authored, rows, model)['state'] == 'blocked' and model.calls == 1


def test_one_shape_correction_then_next_group_and_low_time_no_call(monkeypatch):
    authored, rows, model = fixture(monkeypatch), [], Model(malformed=True)
    for _ in range(4):
        result = invoke(authored, rows, model)
    assert result['state'] == 'accepted' and model.calls == 4
    assert len(result['response_ids']) == len(result['response_hashes']) == 4
    assert result['response_hash'] == digest([{'id': row['id'], 'hash': row['response_hash']} for row in rows])
    assert rows[1]['instruction'] == review.RETRY
    assert 'validation_error' in rows[1]['input']
    other = Model()
    result = invoke(authored, [], other, SimpleNamespace(calls=0, max_calls=6, remaining=lambda: 24))
    assert result['state'] == 'needs_resume' and other.calls == 0


def test_v4_review_excludes_free_form_source_summary_and_binds_new_contract(monkeypatch):
    authored = fixture(monkeypatch)
    previous = base.frozen_request
    def with_summary(*args):
        payload, schema, views = previous(*args)
        for card in payload['source_cards'].values():
            card['reason'] = 'Untrusted model summary introducing an unsupported revenue label.'
        return payload, schema, views
    monkeypatch.setattr(base, 'frozen_request', with_summary)
    authored['contract'] = 'memo-source-unit-author-v6'
    groups = review.frozen_requests({}, [], {}, authored, PIN, PIN)
    assert all(payload['contract'] == review.CONTRACT_V4 for _, payload, _, _ in groups)
    assert all(set(card) == {'reporting_basis', 'contains_explicit_incomplete_quantification_claim'}
               for _, payload, _, _ in groups for card in payload['source_cards'].values())
    rows, model = [], Model()
    for _ in range(3): result = invoke(authored, rows, model)
    assert result['state'] == 'accepted' and result['contract'] == review.CONTRACT_V4
    assert all(row['task'] == review.TASK_V4 and row['instruction'] == review.INSTRUCTION_V4 for row in rows)
    assert invoke(authored, rows) == result
    with pytest.raises(ValueError, match='finite call plan'):
        invoke({**authored, 'contract': 'memo-source-unit-author-v5'}, rows)


def test_qualitative_review_recomputes_exact_author_excerpt_lineage():
    from agents.research import memo_source_unit_author as author
    from tests.research.test_memo_source_unit_author_v6 import date_fixture, Model as AuthorModel, PIN as AUTHOR_PIN
    memo, sources, proof = date_fixture()
    rows = []
    for _ in range(4):
        authored = author.run_author(memo, sources, proof, AUTHOR_PIN, rows, lambda: None,
            AuthorModel(), PreparationBudget(105, max_calls=6, max_requests=6), contract=author.CONTRACT_V6)
    payload, _, _ = base.frozen_request(memo, sources, proof, authored, AUTHOR_PIN, PIN)
    chosen = authored['answer']['recommendation_units']['S4']['supporting_evidence_id']
    assert payload['units']['r_S4']['eligible_evidence_ids'] == [chosen]
    assert 'Nov-21' in payload['evidence_spans'][chosen]['exact_text']
    tampered = copy.deepcopy(authored)
    tampered['offered_evidence_spans'][chosen]['start'] += 1
    with pytest.raises(ValueError, match='exact source retrieval'):
        base.frozen_request(memo, sources, proof, tampered, AUTHOR_PIN, PIN)
