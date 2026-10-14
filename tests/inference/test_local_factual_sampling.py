"""Explicit factual sampling reaches the local transport and durable receipts."""
import json
import hashlib
from unittest.mock import Mock

import httpx
import pytest
from pydantic import BaseModel

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import recorded_call, response_answer


class Answer(BaseModel):
    answer: str


RAW = '{"answer":"Recorded model answer"}'


def adapter(name='qwen3.5:9b', **options):
    model = LocalModel(name, max_tokens=600, context_tokens=8192, **options)
    model.client = Mock()
    model.client.chat.return_value = {'model': name, 'done_reason': 'stop',
        'message': {'content': RAW}, 'prompt_eval_count': 1000, 'eval_count': 12}
    return model


@pytest.mark.parametrize('name', ['qwen3.5:9b', 'qwen3:14b', 'phi4-mini'])
def test_factual_policy_reaches_each_family_without_rewriting_input_or_output(name):
    model = adapter(name, factual_sampling=True)
    evidence = '{ "source": "Exact  repeated repeated source label" }'
    attempts, saved = [], []
    result, response_id = recorded_call(model, 'factual_test', 'Use own source only',
        json.loads(evidence), Answer, attempts, lambda: saved.append(True))
    request = model.client.chat.call_args.kwargs
    assert request['options']['presence_penalty'] == 0
    assert request['options']['repeat_penalty'] == 1
    assert request['options']['num_predict'] == 600
    assert request['options']['num_ctx'] == 8192
    assert json.loads(request['messages'][1]['content']) == json.loads(evidence)
    assert result.answer == 'Recorded model answer' and saved == [True]
    assert attempts[0]['raw_response'] == RAW
    assert response_answer(attempts, response_id) == {'answer': 'Recorded model answer'}
    routing = attempts[0]['routing']
    assert routing['factual_sampling'] is True
    assert routing['sampling'] == model.sampling
    assert all(request['options'][key] == value for key, value in routing['sampling'].items())


@pytest.mark.parametrize('name, expected', [
    ('qwen3.5:9b', {'top_p': .8, 'top_k': 20, 'min_p': 0,
                    'presence_penalty': 1.5, 'repeat_penalty': 1.0}),
    ('qwen3:14b', {'top_p': .8, 'top_k': 20, 'min_p': 0}),
    ('phi4-mini', {}),
])
def test_historical_default_sampler_and_transport_remain_unchanged(name, expected):
    model = adapter(name)
    evidence = '{ "old": "source" }'
    model.generate('Historical task', evidence, Answer)
    request = model.client.chat.call_args.kwargs
    assert model.sampling == expected
    assert request['options'] == {'temperature': model.temperature, 'num_ctx': 8192,
                                  'num_predict': 600, **expected}
    assert request['messages'][1]['content'] == evidence
    assert model.last_call['factual_sampling'] is False
    assert model.last_call['sampling'] == expected
    assert 'format_object_receipts' not in model.last_call


@pytest.mark.parametrize('value', [1, 0, 'true', None])
def test_policy_requires_a_boolean_before_client_creation(monkeypatch, value):
    monkeypatch.setattr('agents.inference.local_models.ollama.Client',
                        lambda **kwargs: pytest.fail('Invalid policy must not create a client'))
    with pytest.raises(TypeError, match='explicit boolean'):
        LocalModel('qwen3.5:9b', factual_sampling=value)


def test_failed_factual_transport_keeps_actual_sampling_in_saved_attempt():
    model = adapter(factual_sampling=True)
    model.last_response_text = 'Earlier unrelated response'
    model.client.chat.side_effect = httpx.ReadTimeout('Transport stalled')
    attempts, saved = [], []
    with pytest.raises(RuntimeError, match='inference timed out'):
        recorded_call(model, 'factual_test', 'Use sources', {'source': 'Synthetic'},
                      Answer, attempts, lambda: saved.append(True))
    row = attempts[0]
    assert saved == [True] and row['raw_response'] == '' and 'answer' not in row
    assert row['routing']['factual_sampling'] is True
    assert row['routing']['sampling']['presence_penalty'] == 0
    assert row['routing']['sampling']['repeat_penalty'] == 1
    request = model.client.chat.call_args.kwargs
    assert all(request['options'][key] == value for key, value in row['routing']['sampling'].items())
    assert 'generated_tokens' not in row['routing']


def test_prompt_failure_records_policy_before_any_model_request():
    model = adapter(factual_sampling=True, compact_prompt=True)
    with pytest.raises(json.JSONDecodeError):
        model.generate('Task', 'not JSON', Answer)
    model.client.chat.assert_not_called()
    assert model.last_call['factual_sampling'] is True
    assert model.last_call['sampling']['presence_penalty'] == 0
    assert model.last_call['sampling']['repeat_penalty'] == 1


def test_actual_sampling_snapshot_cannot_be_overridden_or_changed_after_request():
    model = adapter(factual_sampling=True)
    model.sampling.update(presence_penalty=2, repeat_penalty=1.2)

    def transport(**request):
        assert request['options']['presence_penalty'] == 0
        assert request['options']['repeat_penalty'] == 1
        model.sampling['presence_penalty'] = 3
        return {'message': {'content': RAW}, 'done_reason': 'stop'}

    model.client.chat.side_effect = transport
    model.generate('Task', '{}', Answer)
    assert model.last_call['sampling']['presence_penalty'] == 0
    assert model.last_call['sampling']['repeat_penalty'] == 1
    model.sampling['top_p'] = .2
    assert model.last_call['sampling']['top_p'] == .8


def test_factual_reasoning_continuation_preserves_sampler_and_existing_output_cap():
    model = LocalModel('qwen3.5:9b', thinking=True, max_tokens=1400,
                       reasoning_budget=512, factual_sampling=True)
    model.client = Mock()
    model.client.chat.return_value = {'message': {'thinking': 'Private intermediate', 'content': ''},
                                     'done_reason': 'length', 'eval_count': 512}
    model.client.generate.return_value = {'response': RAW, 'done_reason': 'stop', 'eval_count': 12}
    assert model.generate('Task', '{}', Answer).answer == 'Recorded model answer'
    requests = [model.client.chat.call_args.kwargs, model.client.generate.call_args.kwargs]
    assert [request['options']['num_predict'] for request in requests] == [512, 888]
    assert all(request['options']['presence_penalty'] == 0 and request['options']['repeat_penalty'] == 1
               for request in requests)
    assert model.last_call['factual_sampling'] is True
    assert model.last_response_text == RAW and model.last_call['generated_tokens'] == 524


def test_ordered_format_receipt_survives_success_and_binds_client_argument():
    model = adapter(factual_sampling=True, bound_strings=True, require_full_context=True)
    attempts = []
    recorded_call(model, 'format_binding', 'Use own evidence', {'source': 'Synthetic'},
                  Answer, attempts, lambda: None)
    request = model.client.chat.call_args.kwargs
    body = json.dumps(request['format'], ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'))
    receipt = {'operation': 'chat', 'model': model.name,
               'format_order_digest': hashlib.sha256(body.encode()).hexdigest()}
    assert attempts[0]['routing']['format_object_receipts'] == [receipt]
    reordered = dict(reversed(list(request['format'].items())))
    assert json.loads(body) == reordered
    assert hashlib.sha256(json.dumps(reordered, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest() != receipt['format_order_digest']
    assert set(receipt) == {'operation', 'model', 'format_order_digest'}


def test_request_limit_does_not_record_unsent_format_argument():
    from agents.preparation.preparation_budget import (
        PreparationBudget, PreparationBudgetExceeded, preparation_budget)
    model = adapter(factual_sampling=True, bound_strings=True, require_full_context=True)
    budget = PreparationBudget(105, max_calls=6, max_requests=1)
    budget.start_request()
    with preparation_budget(budget):
        with pytest.raises(PreparationBudgetExceeded):
            model.generate('Task', '{}', Answer)
    model.client.chat.assert_not_called()
    assert 'format_object_receipts' not in model.last_call
