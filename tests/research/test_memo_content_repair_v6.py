"""Fresh source-only author payload excludes rejected prose and old conclusions."""
import json
from types import SimpleNamespace

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_content_repair as repair
from agents.research.investment_memo import Memo
from tests.research.test_memo_causal_review import sample
from tests.research.test_memo_content_repair_v4 import PIN


POISON = 'A prior disputed rationale that must never enter the fresh author request.'


def fixture():
    memo, sources = sample()
    memo['recommendation_reason'] = POISON + ' This disputed conclusion should be replaced using source evidence [S1].'
    memo['recommendation_claims'][0]['assertion'] = 'An old disputed claim assertion not supplied to the fresh author.'
    memo['unknowns'][0]['why_it_matters'] = 'An old unknown rationale not supplied to the fresh author.'
    memo_digest = digest(Memo.model_validate(memo).model_dump(mode='json'))
    result = {'state': 'blocked', 'contract': 'memo-content-review-v5',
        'memo_digest': memo_digest, 'source_characterization': {'source_cards': {'S1': {
            'reporting_basis': 'not_stated',
            'contains_explicit_incomplete_quantification_claim': False}}},
        'findings': [{'field_path': 'recommendation_reason', 'verdict': 'unsupported',
            'exact_sentence': POISON, 'reason': 'A reviewer critique that must not enter fresh prose.',
            'source_id': 'S1', 'sentence_findings': [],
            'response_id': 'review_1', 'response_hash': 'b' * 64}]}
    packet = {'contract': repair.CONTRACT_V6, 'field_path': 'recommendation_reason',
        'base_memo_digest': memo_digest, 'review_memo_digest': memo_digest,
        'model_name': PIN['name'], 'model_digest': PIN['digest'],
        'review_response_id': 'review_1', 'review_response_hash': 'b' * 64}
    return memo, sources, result, packet


def test_fresh_payload_contains_no_old_prose_claim_assertions_or_reviewer_critique():
    memo, sources, result, packet = fixture()
    _, _, payload, _ = repair.frozen_request(memo, sources, packet, result)
    text = json.dumps(payload)
    assert POISON not in text
    assert 'old disputed claim' not in text and 'old unknown rationale' not in text
    assert 'reviewer critique' not in text
    assert 'existing_text' not in payload
    assert payload['finding'] == {'verdict': 'unsupported'}
    assert set(payload['context']) == {'unknowns'}
    assert all(set(row) == {'question', 'evidence_needed'} for row in payload['context']['unknowns'])
    assert all('claim_assertion' not in choice for choice in payload['choices'].values())
    assert payload['max_sentence_characters'] == 180
    assert payload['max_sentences'] == 3 and payload['one_sentence_per_item']
    assert payload['review_response_hash'] == result['findings'][0]['response_hash']
    assert payload['base_memo_digest'] == result['memo_digest']


class Author:
    name = PIN['name']
    thinking = False
    max_tokens = 1000
    context_tokens = 8192
    temperature = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == repair.TASK_V6 and instruction == repair.INSTRUCTION_V6
        assert POISON not in evidence
        answer = {'recommendation': 'defer_pending_evidence',
            'replacement_sentences': [{'choice_id': 'c01', 'text':
            'The registry reports uncertain completion status; dated account records would help assess operating cash before any investment decision.'}]}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **repair.OPTIONS}
        return schema.model_validate(answer)


def test_recorded_fresh_author_projection_replays_identically():
    memo, sources, result, _ = fixture()
    kwargs = dict(review_result=result, repair_attempts=[], save_repairs=lambda: None,
                  author_pin={**PIN, 'repair_contract': repair.CONTRACT_V6})
    first, revised = repair.revise_memo_content(memo, sources, author=Author(),
        repair_budget=PreparationBudget(60, max_calls=2, max_requests=2), **kwargs)
    replay, same = repair.revise_memo_content(memo, sources, author=None,
        repair_budget=SimpleNamespace(calls=0, max_calls=0), **kwargs)
    assert replay == first and same == revised
    assert revised.recommendation == 'defer_pending_evidence'
    assert revised.recommendation_reason.endswith('[S1].')
    assert revised.unknowns == Memo.model_validate(memo).unknowns


def test_fresh_author_requires_one_sentence_per_item():
    memo, sources, result, packet = fixture()
    model, retained, payload, schema = repair.frozen_request(memo, sources, packet, result)
    answer = {'recommendation': 'defer_pending_evidence', 'replacement_sentences': [
        {'choice_id': 'c01', 'text': 'The source reports uncertain completion status. Account records would help clarify operating cash.'}]}
    with pytest.raises(ValueError, match='one sentence per item'):
        repair._project(model, retained, payload, schema.model_validate(answer).model_dump())
