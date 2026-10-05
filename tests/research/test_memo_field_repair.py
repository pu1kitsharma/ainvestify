"""Synthetic source-local whole-field rewrite and exact raw replay."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget
from agents.research.memo_field_repair import (CONTRACT, INSTRUCTION, OPTIONS, TASK,
                                                CONTRACT_V2, TASK_V2, INSTRUCTION_V2,
                                                repair_memo_field)
from tests.research.test_memo_causal_review import sample


class Author:
    name = 'qwen3:14b'
    thinking = False
    max_tokens = 1400
    context_tokens = 8192
    temperature = 0

    def __init__(self):
        self.calls = 0
        self.last_response_text = ''
        self.last_route = {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == TASK and instruction == INSTRUCTION
        self.calls += 1
        payload = json.loads(evidence)
        assert payload['field'] == 'business_and_market'
        assert payload['quote_choices']['q01']['source_id'] == 'S1'
        answer = {'replacement_sentences': [
            {'quote_id': 'q01', 'text': ('The cited registry reports a financing round but does not '
                                         'establish that its transaction closed.')},
            {'quote_id': 'q01', 'text': ('Current cash availability remains unknown from this '
                                         'registry entry, so the round is not treated as operating cash.')} ]}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **OPTIONS}
        return schema.model_validate(answer)


def test_model_authored_field_rewrite_preserves_claims_and_replays():
    memo, sources = sample()
    packet = {'contract': CONTRACT, 'field': 'business_and_market',
              'base_memo_digest': digest(memo),
              'model_name': 'qwen3:14b', 'model_digest': 'a' * 64,
              'review_response_id': 'response_99',
              'review_response_hash': 'b' * 64}
    attempts, model = [], Author()
    budget = PreparationBudget(30, max_calls=1, max_requests=1)
    revised, response_id = repair_memo_field(
        memo, sources, packet, attempts, lambda: None, model, budget)
    assert model.calls == 1 and response_id == attempts[0]['id']
    assert revised.business_and_market.claims == revised.investment_thesis.claims
    assert revised.business_and_market.analysis.count('[S1]') == 2
    replay, replay_id = repair_memo_field(
        memo, sources, packet, attempts, lambda: None, None,
        PreparationBudget(30, max_calls=1, max_requests=1))
    assert replay == revised and replay_id == response_id
    attempts[0]['response_hash'] = '0' * 64
    with pytest.raises(ValueError, match='frozen contract'):
        repair_memo_field(memo, sources, packet, attempts, lambda: None,
                          None, PreparationBudget(30, max_calls=1, max_requests=1))


def test_second_field_repair_binds_prior_author_raw_and_new_field():
    memo, sources = sample()
    first_packet = {'contract': CONTRACT, 'field': 'business_and_market',
                    'base_memo_digest': digest(memo),
                    'model_name': 'qwen3:14b', 'model_digest': 'a' * 64,
                    'review_response_id': 'response_99',
                    'review_response_hash': 'b' * 64}
    attempts = []
    first, first_id = repair_memo_field(
        memo, sources, first_packet, attempts, lambda: None, Author(),
        PreparationBudget(30, max_calls=1, max_requests=1))

    class RisksAuthor(Author):
        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            assert task == TASK_V2 and instruction == INSTRUCTION_V2
            self.calls += 1
            payload = json.loads(evidence)
            assert payload['field'] == 'risks_and_countercase'
            assert payload['prior_field_repair_response_id'] == first_id
            answer = {'replacement_sentences': [
                {'quote_id': 'q01', 'text': ('The registry entry leaves completion of the '
                                            'reported financing unverified and does not confirm that the transaction closed.')},
                {'quote_id': 'q01', 'text': ('Current cash availability is not established '
                                            'by this record and remains a diligence question.')}]}
            self.last_response_text = json.dumps(answer)
            self.last_route = {'model': self.name, **OPTIONS}
            return schema.model_validate(answer)

    second_packet = {'contract': CONTRACT_V2, 'field': 'risks_and_countercase',
                     'base_memo_digest': digest(first.model_dump(mode='json')),
                     'model_name': 'qwen3:14b', 'model_digest': 'a' * 64,
                     'review_response_id': 'response_98',
                     'review_response_hash': 'c' * 64,
                     'prior_field_repair_response_id': first_id,
                     'prior_field_repair_response_hash': attempts[0]['response_hash']}
    second, second_id = repair_memo_field(
        first, sources, second_packet, attempts, lambda: None, RisksAuthor(),
        PreparationBudget(30, max_calls=1, max_requests=1))
    assert second_id == attempts[-1]['id'] and attempts[-1]['task'] == TASK_V2
    replay, replay_id = repair_memo_field(
        first, sources, second_packet, attempts, lambda: None, None,
        PreparationBudget(30, max_calls=1, max_requests=1))
    assert replay == second and replay_id == second_id
