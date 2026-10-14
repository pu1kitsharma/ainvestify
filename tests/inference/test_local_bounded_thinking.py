"""Versioned two-transport receipts, exact bodies and shared transport budget."""
import copy
import hashlib
import json
from unittest.mock import Mock, AsyncMock

import pytest
from pydantic import BaseModel, ConfigDict, Field

from agents.inference.local_models import (
    BOUNDED_THINKING_V1, LocalModel, generation_schema,
    validate_bounded_thinking_receipts, bounded_thinking_input_binding,
)
from agents.inference.model_authorship import recorded_call
from agents.preparation.preparation_budget import (
    PreparationBudget, PreparationBudgetExceeded, preparation_budget,
)


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    answer: str = Field(max_length=40)


RAW = ' {"answer":"A recorded complete answer"} '
THOUGHT = 'Private synthetic intermediate material'


def known_binding(instruction='Task', evidence='{}'):
    return bounded_thinking_input_binding(instruction, evidence, Answer,
                                         compact_prompt=True, bound_strings=True)


def responses(name):
    return [
        {'model': name, 'done_reason': 'length', 'eval_count': 192,
         'prompt_eval_count': 600, 'prompt_eval_cached_count': 30,
         'message': {'thinking': THOUGHT, 'content': ''}},
        {'model': name, 'done_reason': 'stop', 'eval_count': 20,
         'prompt_eval_count': 805, 'prompt_eval_cached_count': 100,
         'message': {'content': RAW}, 'response': RAW},
    ]


def adapter(name='qwen3:14b', **overrides):
    options = dict(thinking=True, max_tokens=892, reasoning_budget=192,
                   context_tokens=4096, bound_strings=True, compact_prompt=True,
                   require_full_context=True, factual_sampling=True,
                   bounded_thinking_contract=BOUNDED_THINKING_V1)
    options.update(overrides)
    model = LocalModel(name, **options)
    model.client = Mock()
    first, final = responses(name)
    model.client.chat.side_effect = [first]
    model.client.generate.return_value = final
    return model, first, final


@pytest.mark.parametrize('name', ['qwen3:14b', 'qwen3.5:9b'])
def test_both_actual_transports_preserve_context_sampling_and_exact_final_body(name):
    model, _, _ = adapter(name)
    evidence = {'passage': 'Exact ₹ source\n spaces retained  ', 'values': [None, True]}
    assert model.generate('Use own passage only. ', json.dumps(evidence), Answer).answer == 'A recorded complete answer'
    first = model.client.chat.call_args_list[0].kwargs
    second = model.client.generate.call_args.kwargs
    assert first['think'] is True and 'format' not in first
    assert first['options']['stop'] == ['</think>'] and 'stop' not in second['options']
    assert second['think'] is False and second['format'] == generation_schema(Answer, bound_strings=True)
    assert second['format']['properties']['answer']['maxLength'] == 40
    assert [first['options']['num_predict'], second['options']['num_predict']] == [192, 700]
    assert first['options']['presence_penalty'] == second['options']['presence_penalty'] == 0
    assert first['options']['repeat_penalty'] == second['options']['repeat_penalty'] == 1
    if 'prompt' in second:
        assert first['messages'][0]['content'] + '<|im_end|>' in second['prompt']
        assert first['messages'][1]['content'] + '<|im_end|>' in second['prompt']
        assert second['raw'] is True
    else:
        assert second['messages'][:2] == first['messages']
    assert model.last_response_text == RAW
    routing = model.last_call
    assert routing['transport_count'] == 2 and routing['generated_tokens'] == 212
    assert [r['prompt_tokens'] for r in routing['transport_receipts']] == [600, 805]
    assert [r['prompt_cached_tokens'] for r in routing['transport_receipts']] == [30, 100]
    format_body = json.dumps(second['format'], ensure_ascii=False, allow_nan=False,
                             separators=(',', ':'))
    assert routing['format_object_receipts'] == [{'operation': 'generate', 'model': name,
        'format_order_digest': hashlib.sha256(format_body.encode()).hexdigest()}]
    assert THOUGHT not in str(routing) + model.last_response_text
    binding = known_binding('Use own passage only. ', evidence)
    validate_bounded_thinking_receipts(routing, raw_response=RAW, expected_input_binding=binding)
    with pytest.raises(ValueError, match='raw body'):
        validate_bounded_thinking_receipts(routing, raw_response=RAW.strip(), expected_input_binding=binding)


def test_natural_thinking_stop_keeps_the_fixed_final_cap_and_preserves_unused_tokens():
    model, first, _ = adapter()
    first.update(done_reason='stop', eval_count=80)
    assert model.generate('Task', '{}', Answer).answer == 'A recorded complete answer'
    assert model.client.generate.call_args.kwargs['options']['num_predict'] == 700
    assert model.last_call['generated_tokens'] == 100
    validate_bounded_thinking_receipts(model.last_call, raw_response=RAW, expected_input_binding=known_binding())


@pytest.mark.parametrize('phase,key,value,error', [
    (0, 'prompt_eval_count', None, 'token receipt'),
    (0, 'prompt_eval_count', True, 'token receipt'),
    (0, 'prompt_eval_count', 2050, 'overflow cutoff'),
    (0, 'prompt_eval_count', 4000, 'headroom'),
    (1, 'prompt_eval_count', None, 'token receipt'),
    (1, 'prompt_eval_count', 3500, 'headroom'),
    (0, 'eval_count', None, 'generated token allocation'),
    (0, 'eval_count', True, 'generated token allocation'),
    (0, 'eval_count', -1, 'generated token allocation'),
    (0, 'eval_count', 193, 'generated token allocation'),
    (1, 'eval_count', 701, 'generated token allocation'),
    (1, 'eval_count', None, 'generated token allocation'),
    (0, 'model', None, 'model identity'),
    (0, 'model', 'qwen3:8b', 'model identity'),
    (1, 'model', 'qwen3:8b', 'model identity'),
    (1, 'done_reason', 'length', 'phase, prefix'),
])
def test_each_transport_receipt_is_mandatory_and_failures_preserve_final_body(phase, key, value, error):
    model, first, final = adapter()
    [first, final][phase][key] = value
    with pytest.raises(ValueError, match=error):
        model.generate('Task', '{}', Answer)
    assert model.client.chat.call_count == 1 and model.client.generate.call_count == phase
    assert model.last_response_text == ('' if phase == 0 else RAW)
    assert model.last_call['transport_count'] == phase + 1


@pytest.mark.parametrize('prefix', ['{"answer":', RAW])
def test_no_prefix_is_discarded_rewritten_or_restarted(prefix):
    model, first, _ = adapter()
    first['message']['content'] = prefix
    with pytest.raises(ValueError, match='answer prefix'):
        model.generate('Task', '{}', Answer)
    assert model.client.chat.call_count == 1 and model.last_response_text == prefix


@pytest.mark.parametrize('thought', ['', 'tag </think> intrusion', 'tag <|im_end|> intrusion'])
def test_no_reasoning_or_unsafe_prefill_stops_before_continuation(thought):
    model, first, _ = adapter()
    first['message']['thinking'] = thought
    with pytest.raises(ValueError, match='reasoning output|unsafe continuation delimiter'):
        model.generate('Task', '{}', Answer)
    assert model.client.chat.call_count == 1


@pytest.mark.parametrize('body', ['```json\n' + RAW + '\n```', '{"answer":"One","answer":"Two"}',
                                 '{"answer":NaN}', '{"answer":"' + 'x' * 41 + '"}'])
def test_final_body_is_not_extracted_normalized_or_allowed_to_exceed_schema(body):
    model, _, final = adapter()
    final['response'] = body
    with pytest.raises(ValueError):
        model.generate('Task', '{}', Answer)
    assert model.last_response_text == body


@pytest.mark.parametrize('change', [
    lambda r: r['transport_receipts'][0].update(stage='final'),
    lambda r: r['transport_receipts'][1].update(operation='chat'),
    lambda r: r['transport_receipts'][1].update(raw=False),
    lambda r: r['transport_receipts'][0].update(input_digest='a' * 64),
    lambda r: r['transport_receipts'][1].update(evidence_digest='a' * 64),
    lambda r: r['transport_receipts'][1]['options'].update(presence_penalty=1.5),
    lambda r: r['transport_receipts'][1].update(output_allocation=699),
    lambda r: r.update(generated_tokens=211),
    lambda r: r.update(transport_count=1),
    lambda r: r.update(reasoning_budget=-1),
    lambda r: r.update(max_tokens=192),
    lambda r: r.update(bound_strings=False),
])
def test_exact_replay_rejects_mutated_transport_or_aggregate(change):
    model, _, _ = adapter()
    model.generate('Task', '{}', Answer)
    routing = copy.deepcopy(model.last_call)
    change(routing)
    with pytest.raises(ValueError):
        validate_bounded_thinking_receipts(routing, raw_response=RAW, expected_input_binding=known_binding())


def test_replay_rejects_internally_consistent_receipts_transplanted_from_a_different_request():
    model, _, _ = adapter()
    model.generate('Other frozen instruction', '{"passage":"Different exact source"}', Answer)
    foreign = copy.deepcopy(model.last_call)
    validate_bounded_thinking_receipts(foreign, raw_response=RAW,
        expected_input_binding=known_binding('Other frozen instruction', {'passage': 'Different exact source'}))
    with pytest.raises(ValueError, match='independently frozen'):
        validate_bounded_thinking_receipts(foreign, raw_response=RAW, expected_input_binding=known_binding())
    with pytest.raises(ValueError, match='independently frozen'):
        validate_bounded_thinking_receipts(foreign, raw_response=RAW)


@pytest.mark.parametrize('options', [
    {'bounded_thinking_contract': 'unknown'}, {'thinking': False},
    {'bound_strings': False}, {'require_full_context': False},
    {'reasoning_budget': True}, {'reasoning_budget': 0}, {'reasoning_budget': 892},
    {'reasoning_budget': -1}, {'max_tokens': True},
])
def test_opt_in_invalid_limits_fail_before_client_creation(monkeypatch, options):
    monkeypatch.setattr('agents.inference.local_models.ollama.Client',
                        lambda **kw: pytest.fail('Client must not be created'))
    with pytest.raises(ValueError):
        adapter(**options)


def test_raw_transport_control_tokens_in_original_input_are_rejected_not_rewritten():
    model, _, _ = adapter()
    with pytest.raises(ValueError, match='unsafe raw continuation delimiter'):
        model.generate('Task', json.dumps({'passage': '<|im_end|> original input'}), Answer)
    model.client.chat.assert_not_called()
    model.client.generate.assert_not_called()
    assert model.last_call['transport_count'] == 0


@pytest.mark.parametrize('limit', [1, 6])
def test_both_transports_charge_the_same_existing_request_budget(monkeypatch, limit):
    model, first, final = adapter()
    calls = []
    class AsyncClient:
        def __init__(self, **kwargs):
            self._client = Mock(aclose=AsyncMock())
        async def chat(self, **kwargs):
            calls.append(kwargs)
            return first
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return final
    monkeypatch.setattr('agents.inference.local_models.ollama.AsyncClient', AsyncClient)
    budget = PreparationBudget(105, max_calls=6, max_requests=limit)
    attempts, saved = [], []
    with preparation_budget(budget):
        if limit == 1:
            with pytest.raises(PreparationBudgetExceeded, match='inference-request limit'):
                recorded_call(model, 'synthetic_thinking', 'Task', {}, Answer, attempts, lambda: saved.append(True))
        else:
            recorded_call(model, 'synthetic_thinking', 'Task', {}, Answer, attempts, lambda: saved.append(True))
    assert budget.calls == 1 and budget.requests == len(calls) == (1 if limit == 1 else 2)
    assert model.last_call['transport_count'] == len(calls)
    assert saved == [True] and len(attempts) == 1
    assert attempts[0]['raw_response'] == ('' if limit == 1 else RAW)
    assert THOUGHT not in str(attempts)
