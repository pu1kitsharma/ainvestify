"""Synthetic scope-bound repair and frozen contract replay; no live model claims."""
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_content_repair as repair
from agents.research.investment_memo import Memo
from tests.research.test_memo_causal_review import sample

PIN = {'name': 'local-synthetic', 'digest': 'a' * 64,
       'repair_contract': repair.CONTRACT_V4}


def blocked(memo, path='unknowns[1].why_it_matters'):
    text = (memo['recommendation_reason'] if path == 'recommendation_reason'
            else memo['unknowns'][1]['why_it_matters'])
    return {'state': 'blocked', 'contract': 'memo-content-review-v4',
            'memo_digest': digest(Memo.model_validate(memo).model_dump(mode='json')),
            'findings': [{'field_path': path, 'verdict': 'unsupported',
                          'exact_sentence': text, 'reason': 'The scope exceeds the selected record.',
                          'source_id': 'S1', 'sentence_findings': [],
                          'response_id': 'review_1', 'response_hash': 'b' * 64}]}


def frozen(contract=repair.CONTRACT_V4, path='unknowns[1].why_it_matters'):
    memo, sources = sample()
    result = blocked(memo, path)
    packet = {'contract': contract, 'field_path': path,
              'base_memo_digest': result['memo_digest'],
              'review_memo_digest': result['memo_digest'],
              'model_name': PIN['name'], 'model_digest': PIN['digest'],
              'review_response_id': 'review_1', 'review_response_hash': 'b' * 64}
    return repair.frozen_request(memo, sources, packet, result)


def test_v4_unknown_relevance_uses_one_short_sentence_without_numbers():
    memo, sources, payload, schema = frozen()
    assert payload['max_sentences'] == 1
    assert payload['max_sentence_characters'] == payload['max_total_characters'] == 220
    assert all(choice['allowed_numbers'] == [] for choice in payload['choices'].values())
    assert all(choice['source_context'] for choice in payload['choices'].values())
    answer = {'replacement_sentences': [{'choice_id': 'c01', 'text':
              'Current bank records would help assess operating cash available for diligence.'}]}
    revised = repair._project(memo, sources, payload, schema.model_validate(answer).model_dump())
    assert revised.unknowns[1].why_it_matters == answer['replacement_sentences'][0]['text']
    assert revised.recommendation_reason == memo.recommendation_reason
    with pytest.raises(ValidationError):
        schema.model_validate({'replacement_sentences': answer['replacement_sentences'] * 2})
    answer['replacement_sentences'][0]['text'] = 'Current bank records would help assess cash for the next 12 months.'
    with pytest.raises(ValueError, match='does not allow'):
        repair._project(memo, sources, payload, answer)


def test_v4_preserves_full_source_context_for_period_and_scenario_interpretation():
    memo, sources, payload, _ = frozen(path='recommendation_reason')
    assert payload['max_sentences'] == 3
    assert payload['choices']['c01']['source_context'] == sources[0].passage
    assert payload['choices']['c01']['exact_text'] == memo.recommendation_claims[0].quote
    assert set(payload['source_scope_requirements']) == {
        'period_and_scenario', 'absence_and_quantification', 'unknown_relevance'}
    assert 'forecast or target is never achieved growth' in repair.INSTRUCTION_V4


def test_v3_payload_limits_and_instruction_remain_historical():
    _, _, payload, _ = frozen(repair.CONTRACT_V3)
    assert payload['max_sentences'] == 2 and payload['max_total_characters'] == 450
    assert 'source_scope_requirements' not in payload
    assert all('source_context' not in choice for choice in payload['choices'].values())
    assert 'max_total_characters (citations included)' in repair.INSTRUCTION


class Author:
    name = PIN['name']
    thinking = False
    max_tokens = 1000
    context_tokens = 8192
    temperature = 0

    def __init__(self):
        self.calls = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == repair.TASK_V4 and instruction == repair.INSTRUCTION_V4
        assert json.loads(evidence)['max_sentences'] == 1
        self.calls += 1
        answer = {'replacement_sentences': [{'choice_id': 'c01', 'text':
                  'Current bank records would help assess operating cash available for diligence.'}]}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **repair.OPTIONS}
        return schema.model_validate(answer)


def test_pin_opts_into_v4_and_raw_replay_rejects_contract_downgrade():
    memo, sources = sample()
    review_result, rows, author = blocked(memo), [], Author()
    kwargs = dict(review_result=review_result, repair_attempts=rows,
                  save_repairs=lambda: None, author_pin=PIN)
    outcome, revised = repair.revise_memo_content(memo, sources, author=author,
        repair_budget=PreparationBudget(60, max_calls=4, max_requests=4), **kwargs)
    assert outcome['state'] == 'revised_pending_rereview' and author.calls == 1
    assert rows[0]['task'] == repair.TASK_V4
    replay, same = repair.revise_memo_content(memo, sources, author=None,
        repair_budget=SimpleNamespace(calls=0, max_calls=0), **kwargs)
    assert same == revised and replay == outcome
    rows[0]['input']['contract'] = repair.CONTRACT_V3
    with pytest.raises(ValueError, match='frozen contract'):
        repair.revise_memo_content(memo, sources, author=None,
            repair_budget=SimpleNamespace(calls=0, max_calls=0), **kwargs)


def test_unknown_repair_pin_is_not_silently_ignored():
    memo, sources = sample()
    with pytest.raises(ValueError, match='Unknown pinned'):
        repair.revise_memo_content(memo, sources, review_result=blocked(memo),
            repair_attempts=[], save_repairs=lambda: None, author=None,
            author_pin={**PIN, 'repair_contract': 'invented-contract'},
            repair_budget=SimpleNamespace(calls=0, max_calls=0))


def test_invalid_v5_reviewer_answer_offers_exact_field_error_and_blind_cards_to_author():
    memo, sources = sample()
    result = blocked(memo)
    result['contract'] = 'memo-content-review-v5'
    result['source_characterization'] = {'source_cards': {'S1': {
        'contains_explicit_incomplete_quantification_claim': False}}}
    result['findings'][0] = {'field_path': 'unknowns[1].why_it_matters',
        'verdict': 'invalid_answer', 'validation_error': 'No explicit source statement.',
        'response_id': 'review_1', 'response_hash': 'b' * 64}
    packet = {'contract': repair.CONTRACT_V4,
        'field_path': 'unknowns[1].why_it_matters',
        'base_memo_digest': result['memo_digest'], 'review_memo_digest': result['memo_digest'],
        'model_name': PIN['name'], 'model_digest': PIN['digest'],
        'review_response_id': 'review_1', 'review_response_hash': 'b' * 64}
    _, _, payload, _ = repair.frozen_request(memo, sources, packet, result)
    assert payload['finding']['validation_error'] == 'No explicit source statement.'
    assert payload['existing_text'] == memo['unknowns'][1]['why_it_matters']
    assert payload['source_characterization'] == result['source_characterization']
    assert 'invalid reviewer response is not evidence' in repair.INSTRUCTION_V4_BLIND
    assert 'invalid reviewer response is not evidence' not in repair.INSTRUCTION_V4
