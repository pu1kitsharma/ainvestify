"""Isolated recorded author calls retain legacy replay and fixed phase budgets."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_source_unit_author as author
from tests.research.test_memo_source_unit_author import fixture, PIN


class Model:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0

    def __init__(self, bad_unit=None, always_bad=False, disagree=False):
        self.calls, self.bad_unit, self.always_bad, self.disagree = 0, bad_unit, always_bad, disagree

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == author.TASK_V2
        payload = json.loads(evidence)
        assert 'prior_inquiries' not in payload and 'prior_question' not in evidence
        assert 'prior_requested_records' not in evidence and 'why_it_matters' not in evidence
        assert set(payload['sources']) == set(payload['unit_source_ids'])
        self.calls += 1
        if payload['unit_id'].startswith('r_'):
            source = payload['sources'][payload['unit_source_ids'][0]]
            obj = {'recommendation': 'decline' if self.disagree and payload['unit_id'] == 'r_S4' else 'defer_pending_evidence',
                'supporting_evidence_id': next(iter(source['spans'])), 'reported_scope': 'current_description',
                'standalone_text': 'The registry reports uncertain completion status and current cash availability; dated company records remain relevant to diligence.'}
        else:
            obj = {'question': 'What operating cash is currently available to the company?',
                'conditional_importance': 'If reviewed cash records were available, they would help assess operating runway.',
                'requested_records': 'Reviewed bank and account records showing current operating cash availability.',
                'requested_time_basis': 'current'}
            if self.bad_unit == payload['unit_id'] and (self.always_bad or not payload.get('correction_number')):
                obj['conditional_importance'] = 'If FY22 records were available, they would help assess operating runway.'
        self.last_response_text = json.dumps(obj)
        self.last_route = {'model': self.name, **author.OPTIONS_V2}
        return schema.model_validate(obj)


def advance(memo, sources, proof, rows, model):
    return author.run_author(memo, sources, proof, PIN, rows, lambda: None, model,
        PreparationBudget(105, max_calls=6, max_requests=6), contract=author.CONTRACT_V2)


def test_unit_requests_have_no_old_prose_and_only_own_scoped_source_cards():
    memo, sources, proof = fixture()
    _, _, requests, scope = author.frozen_unit_requests(memo, sources, proof, PIN)
    assert [key for key, _, _ in requests] == ['r_S1', 'u0', 'u1']
    for key, payload, schema in requests:
        assert set(payload['sources']) == set(payload['source_cards']) == set(scope[key])
        assert memo['recommendation_reason'] not in json.dumps(payload)
        assert 'prior_inquiries' not in payload
        if key.startswith('u'):
            assert len(scope[key]) <= 2
            assert 'UNTRUSTED' in payload['inquiry_search_terms_status']
            assert all(' ' not in term for term in payload['inquiry_search_terms'])


def test_one_call_per_invocation_completes_and_replays_all_raw_unit_bindings():
    memo, sources, proof = fixture()
    rows, model = [], Model()
    result = advance(memo, sources, proof, rows, model)
    assert result['state'] == 'needs_resume' and model.calls == len(rows) == 1
    result = advance(memo, sources, proof, rows, model)
    assert result['state'] == 'needs_resume' and model.calls == len(rows) == 2
    result = advance(memo, sources, proof, rows, model)
    assert result['state'] == 'accepted' and model.calls == len(rows) == 3
    assert result['response_id'].startswith('bundle:')
    assert len(result['response_ids']) == len(result['response_hashes']) == 3
    assert set(result['unit_response_ids']) == {'r_S1', 'u0', 'u1'}
    assert result['unknown_source_ids'] == {k: v for k, v in result['unit_source_ids'].items() if k.startswith('u')}
    replay = author.run_author(memo, sources, proof, PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=author.CONTRACT_V2)
    assert replay == result
    assert result['memo']['investment_thesis'] == memo['investment_thesis']
    rows[1]['input']['unit_source_ids'] = ['S999']
    with pytest.raises(ValueError, match='frozen source-unit'):
        advance(memo, sources, proof, rows, None)


def test_validation_error_gets_only_one_own_unit_correction():
    memo, sources, proof = fixture()
    rows, model = [], Model(bad_unit='u0')
    for _ in range(4):
        result = advance(memo, sources, proof, rows, model)
    assert result['state'] == 'accepted' and model.calls == 4
    assert rows[2]['input']['unit_id'] == 'u0' and rows[2]['input']['correction_number'] == 1
    assert 'previous_invalid_answer' not in rows[2]['input']
    assert rows[2]['input']['sources'] == rows[1]['input']['sources']


def test_second_invalid_unknown_call_is_terminal_without_touching_next_unit():
    memo, sources, proof = fixture()
    rows, model = [], Model(bad_unit='u0', always_bad=True)
    advance(memo, sources, proof, rows, model)
    advance(memo, sources, proof, rows, model)
    with pytest.raises(ValueError, match='correction exhausted: u0'):
        advance(memo, sources, proof, rows, model)
    assert model.calls == len(rows) == 3
    assert all(row['input']['unit_id'] != 'u1' for row in rows)
