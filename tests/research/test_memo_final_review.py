"""Synthetic exact replay for bounded field-level final review."""
import json

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_final_review as field_review
from tests.research.test_memo_causal_review import sample


class Reviewer:
    name = 'qwen3:14b'
    thinking = False
    max_tokens = 1200
    context_tokens = 8192
    temperature = 0

    def __init__(self):
        self.calls = 0
        self.last_response_text = ''
        self.last_route = {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == field_review.TASK
        self.calls += 1
        self.last_response_text = json.dumps({
            'blocking': [], 'advisory': [],
            'review_note': 'The named field preserves the limits of its cited evidence.'})
        self.last_route = {'model': self.name, **field_review.OPTIONS}
        return schema.model_validate_json(self.last_response_text)


def test_six_field_calls_and_exact_replay():
    memo, sources = sample()
    contract = {'version': field_review.CONTRACT, 'model_name': 'qwen3:14b',
                'model_digest': 'a' * 64}
    attempts, model = [], Reviewer()
    for _ in field_review.FIELDS:
        result = field_review.review_memo_fields(
            memo, sources, 'b' * 64, attempts, lambda: None, model,
            PreparationBudget(30, max_calls=1, max_requests=1),
            contract=contract, company='Example Labs', as_of_date='2026-10-05')
    assert result['state'] == 'accepted' and model.calls == 6
    assert len(attempts) == 6
    replay, pending = field_review.evaluate_attempts(
        memo, sources, 'b' * 64, attempts, contract, 'Example Labs', '2026-10-05')
    assert pending is None and replay == result
    attempts[0]['input']['company'] = 'Changed'
    with pytest.raises(ValueError, match='exact contract'):
        field_review.evaluate_attempts(
            memo, sources, 'b' * 64, attempts, contract, 'Example Labs', '2026-10-05')


def test_small_typed_field_v2_replay_and_block():
    memo, sources = sample()
    contract = {'version': field_review.CONTRACT_V2, 'model_name': 'qwen3:14b',
                'model_digest': 'a' * 64}
    calls = field_review.frozen_calls_v2(
        memo, sources, 'b' * 64, 'qwen3:14b', 'a' * 64,
        'Example Labs', '2026-10-05')
    assert len(calls) == 6
    assert all(len(json.dumps(payload)) < 3000 for _, payload, _ in calls)

    class TypedReviewer(Reviewer):
        max_tokens = 450

        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            assert task == field_review.TASK_V2
            self.calls += 1
            payload = json.loads(evidence)
            self.last_response_text = json.dumps({
                'verdict': 'supported_or_conditional',
                'focus_sentence_id': next(iter(payload['sentences'])),
                'source_id': payload['claim_quotes'][0]['source_id'],
                'reason': 'The cited statement remains qualified as a report or a diligence proposal.'})
            self.last_route = {'model': self.name, **field_review.OPTIONS_V2}
            return schema.model_validate_json(self.last_response_text)

    attempts, model = [], TypedReviewer()
    for _ in calls:
        result = field_review.review_memo_fields(
            memo, sources, 'b' * 64, attempts, lambda: None, model,
            PreparationBudget(30, max_calls=1, max_requests=1),
            contract=contract, company='Example Labs', as_of_date='2026-10-05')
    assert result['state'] == 'accepted' and model.calls == 6
    replay, pending = field_review.evaluate_attempts(
        memo, sources, 'b' * 64, attempts, contract, 'Example Labs', '2026-10-05')
    assert replay == result and pending is None


def test_field_v3_bridges_only_exact_v2_reason_length_failure():
    from agents.inference.model_authorship import digest

    memo, sources = sample()
    old = field_review.frozen_calls_v2(
        memo, sources, 'b' * 64, 'qwen3:14b', 'a' * 64,
        'Example Labs', '2026-10-05')[0]
    reason = 'The attributed report remains uncertain. ' * 7
    answer = {'verdict': 'supported_or_conditional',
              'focus_sentence_id': next(iter(old[1]['sentences'])),
              'source_id': old[1]['claim_quotes'][0]['source_id'],
              'reason': reason}
    assert 120 < len(reason) < 450
    raw = json.dumps(answer)
    row = {'id': 'response_1', 'task': field_review.TASK_V2,
           'input': old[1], 'schema': old[2].model_json_schema(),
           'instruction': field_review.INSTRUCTION_V2, 'model': 'qwen3:14b',
           'routing': {'model': 'qwen3:14b', **field_review.OPTIONS_V2},
           'raw_response': raw, 'response_hash': digest(raw), 'answer': answer,
           'error': 'reason string_too_long', 'failure_kind': 'schema_validation'}
    contract = {'version': field_review.CONTRACT_V3, 'model_name': 'qwen3:14b',
                'model_digest': 'a' * 64}
    result, next_call = field_review.evaluate_attempts(
        memo, sources, 'b' * 64, [row], contract,
        'Example Labs', '2026-10-05')
    assert result is None and next_call[0] == 'investment_thesis'
    row['response_hash'] = '0' * 64
    with pytest.raises(ValueError, match='bridge differs'):
        field_review.evaluate_attempts(
            memo, sources, 'b' * 64, [row], contract,
            'Example Labs', '2026-10-05')


def test_field_v4_bridges_two_prior_length_envelopes():
    from agents.inference.model_authorship import digest

    memo, sources = sample()
    rows = []
    for index, (version, task, reason, failed) in enumerate((
            (field_review.CONTRACT_V2, field_review.TASK_V2,
             'An attributed and appropriately uncertain source report. ' * 5, True),
            (field_review.CONTRACT_V3, field_review.TASK_V3,
             'The reviewed premise remains explicitly attributed to the source.', False),
            (field_review.CONTRACT_V3, field_review.TASK_V3,
             'The model preserves the reported source claim and its uncertainty. ' * 9, True))):
        call = field_review.frozen_calls_v2(
            memo, sources, 'b' * 64, 'qwen3:14b', 'a' * 64,
            'Example Labs', '2026-10-05', version=version)[index]
        answer = {'verdict': 'supported_or_conditional',
                  'focus_sentence_id': next(iter(call[1]['sentences'])),
                  'source_id': call[1]['claim_quotes'][0]['source_id'],
                  'reason': reason}
        raw = json.dumps(answer)
        row = {'id': f'response_{index + 1}', 'task': task,
               'input': call[1], 'schema': call[2].model_json_schema(),
               'instruction': field_review.INSTRUCTION_V2, 'model': 'qwen3:14b',
               'routing': {'model': 'qwen3:14b', **field_review.OPTIONS_V2},
               'raw_response': raw, 'response_hash': digest(raw), 'answer': answer}
        if failed:
            row.update(error='reason string_too_long', failure_kind='schema_validation')
        rows.append(row)
    assert len(rows[2]['answer']['reason']) > 450
    contract = {'version': field_review.CONTRACT_V4, 'model_name': 'qwen3:14b',
                'model_digest': 'a' * 64}
    result, next_call = field_review.evaluate_attempts(
        memo, sources, 'b' * 64, rows, contract,
        'Example Labs', '2026-10-05')
    assert result is None and next_call[0] == 'differentiation_and_execution'
