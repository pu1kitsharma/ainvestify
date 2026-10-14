"""Bundled source-only model projection, exact evidence binding and bounded replay."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_source_unit_author as author, rationale_evidence
from tests.research.test_memo_causal_review import sample
from tests.research.test_rationale_evidence import Model as Characterizer, PIN as REVIEW_PIN

PIN = {'name': 'local-author', 'digest': 'c' * 64}


def fixture():
    memo, sources = sample()
    rows = []
    result = rationale_evidence.characterize_sources(sources, REVIEW_PIN, rows,
        lambda: None, Characterizer(), PreparationBudget(60, max_calls=2, max_requests=2))
    return memo, sources, {'attempts': rows, 'result': result}


def answer(payload):
    return {'recommendation': 'defer_pending_evidence', 'recommendation_units': {
        source_id: {'supporting_evidence_id': next(iter(payload['sources'][source_id]['spans'])),
                    'reported_scope': 'current_description',
                    'standalone_text': 'The registry reports uncertain completion status and current cash availability; dated company records remain relevant to diligence.'}
        for source_id in payload['recommendation_source_ids']},
        'unknown_units': {key: {
            'question': 'What operating cash is currently available to the company?',
            'conditional_importance': 'If reviewed cash records were available, they would help assess operating runway.',
            'requested_records': 'Reviewed bank and account records showing current operating cash availability.',
            'requested_time_basis': 'current'} for key in payload['prior_inquiries']}}


class Model:
    name = PIN['name']
    thinking = False
    max_tokens = 1200
    context_tokens = 8192
    temperature = 0

    def __init__(self, bad=False):
        self.calls, self.bad = 0, bad

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == author.TASK
        assert instruction == (author.INSTRUCTION if self.calls == 0 else author.RETRY_INSTRUCTION)
        self.calls += 1
        result = answer(json.loads(evidence))
        if self.bad and self.calls == 1:
            result['unknown_units']['u0']['conditional_importance'] = (
                'If FY22 records were available, they would help assess operating runway.')
        self.last_response_text = json.dumps(result)
        self.last_route = {'model': self.name, **author.OPTIONS}
        return schema.model_validate(result)


def test_payload_omits_old_rationales_claims_and_no_source_text_duplication():
    memo, sources, proof = fixture()
    payload, _ = author.frozen_request(memo, sources, proof, PIN)
    serialized = json.dumps(payload)
    assert memo['recommendation_reason'] not in serialized
    assert 'recommendation_claims' not in payload
    assert 'why_it_matters' not in serialized
    assert all('source_context' not in row for row in payload['sources'].values())
    for source in sources:
        assert ''.join(payload['sources'][source['id']]['spans'].values()) == source['passage']
    assert all('UNTRUSTED' in inquiry['prior_topic_status'] for inquiry in payload['prior_inquiries'].values())


def test_real_projection_overwrites_all_units_and_preserves_other_sections():
    memo, sources, proof = fixture()
    rows, model = [], Model()
    record = author.run_author(memo, sources, proof, PIN, rows, lambda: None,
        model, PreparationBudget(60, max_calls=2, max_requests=2))
    assert record['state'] == 'accepted' and model.calls == 1
    revised = record['memo']
    assert revised['recommendation_reason'].endswith('[S1].')
    assert revised['recommendation_claims'][0]['quote'] == sources[0]['passage']
    assert revised['recommendation_claims'][0]['assertion'] == record['answer']['recommendation_units']['S1']['standalone_text']
    for index, unit in enumerate(record['answer']['unknown_units'].values()):
        assert revised['unknowns'][index] == {'question': unit['question'],
            'why_it_matters': unit['conditional_importance'], 'evidence_needed': unit['requested_records']}
    assert revised['investment_thesis'] == memo['investment_thesis']
    replay = author.run_author(memo, sources, proof, PIN, rows, lambda: None,
                              None, SimpleNamespace(calls=0, max_calls=0))
    assert replay == record


def test_raw_and_blind_source_proof_tampering_block():
    memo, sources, proof = fixture()
    rows = []
    author.run_author(memo, sources, proof, PIN, rows, lambda: None,
                     Model(), PreparationBudget(60, max_calls=2, max_requests=2))
    changed = copy.deepcopy(proof)
    changed['result']['source_cards']['S1']['reporting_basis'] = 'historical'
    with pytest.raises(ValueError, match='recorded replay'):
        author.frozen_request(memo, sources, changed, PIN)
    rows[0]['response_hash'] = '0' * 64
    with pytest.raises(ValueError, match='frozen contract'):
        author.run_author(memo, sources, proof, PIN, rows, lambda: None, None,
                          SimpleNamespace(calls=0, max_calls=0))


def test_recommendation_evidence_cannot_cross_sources_or_invent_numbers():
    memo, sources, proof = fixture()
    payload, schema = author.frozen_request(memo, sources, proof, PIN)
    obj = answer(payload)
    obj['recommendation_units']['S1']['supporting_evidence_id'] = 'S2.e001'
    with pytest.raises(ValueError):
        author._project(memo, sources, payload, schema, obj)
    obj = answer(payload)
    obj['recommendation_units']['S1']['standalone_text'] = (
        'The registry reports revenue of 987654321 dollars with uncertain completion status and current cash availability.')
    with pytest.raises(ValueError, match='numbers are absent'):
        author._project(memo, sources, payload, schema, obj)


def test_unknown_fiscal_year_is_rejected_and_one_correction_replays():
    memo, sources, proof = fixture()
    rows, model = [], Model(bad=True)
    first = author.run_author(memo, sources, proof, PIN, rows, lambda: None, model,
                             PreparationBudget(60, max_calls=2, max_requests=2))
    assert first['state'] == 'needs_resume'
    result = author.run_author(memo, sources, proof, PIN, rows, lambda: None, model,
                              PreparationBudget(60, max_calls=2, max_requests=2))
    assert result['state'] == 'accepted' and model.calls == 2
    assert rows[1]['input']['correction_number'] == 1
    assert 'previous_invalid_answer' not in rows[1]['input']
    assert author.run_author(memo, sources, proof, PIN, rows, lambda: None, None,
                            SimpleNamespace(calls=0, max_calls=0)) == result


def test_second_invalid_answer_is_terminal_without_a_third_model_call():
    class Invalid(Model):
        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            self.calls += 1
            obj = answer(json.loads(evidence))
            obj['unknown_units']['u0']['conditional_importance'] = (
                'If FY22 records were available, they would help assess operating runway.')
            self.last_response_text = json.dumps(obj)
            self.last_route = {'model': self.name, **author.OPTIONS}
            return schema.model_validate(obj)

    memo, sources, proof = fixture()
    rows, model = [], Invalid()
    assert author.run_author(memo, sources, proof, PIN, rows, lambda: None, model,
        PreparationBudget(60, max_calls=2, max_requests=2))['state'] == 'needs_resume'
    with pytest.raises(ValueError, match='correction exhausted'):
        author.run_author(memo, sources, proof, PIN, rows, lambda: None, model,
                          PreparationBudget(60, max_calls=2, max_requests=2))
    assert model.calls == len(rows) == 2
