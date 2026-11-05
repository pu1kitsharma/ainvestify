"""Hardware placement is explicit and remains bound to exact transport receipts."""
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest
from pydantic import BaseModel

from agents.inference.local_models import LocalModel, validate_bounded_thinking_receipts, validate_stream_observation_receipt
from agents.inference.runtime_options import (
    HARDWARE_PROFILE_ENV, RTX2060_QWEN35_V1, hardware_runtime_options, validate_runtime_options,
)
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from tests.inference.test_local_bounded_thinking import adapter, known_binding, RAW, Answer as BoundedAnswer
from tests.inference.test_local_stream_observation import model, streaming_client, terminal, Output


@pytest.mark.parametrize('options', [True, [], {'num_ctx': 2048}, {'num_predict': 9999},
    {'temperature': 0}, {'num_gpu': True}, {'num_gpu': 1.0}, {'num_gpu': 257},
    {'num_gpu': -2}, {'num_batch': 0}, {'num_batch': 513}, {'num_batch': '128'}])
def test_invalid_hardware_options_fail_before_client_creation(monkeypatch, options):
    monkeypatch.setattr('agents.inference.local_models.ollama.Client',
                        lambda **kwargs: pytest.fail('Invalid placement created a client'))
    with pytest.raises(ValueError, match='Runtime option'):
        LocalModel('qwen3.5:9b', runtime_options=options)


def test_profile_requires_explicit_opt_in_and_preserves_context_and_model(monkeypatch):
    monkeypatch.delenv(HARDWARE_PROFILE_ENV, raising=False)
    assert hardware_runtime_options('qwen3.5:9b', 16384) == {}
    monkeypatch.setenv(HARDWARE_PROFILE_ENV, RTX2060_QWEN35_V1)
    assert hardware_runtime_options('qwen3.5:9b', 2048) == {'num_gpu': 33, 'num_batch': 128}
    assert hardware_runtime_options('qwen3.5:9b', 16384) == {'num_gpu': 31, 'num_batch': 128}
    assert hardware_runtime_options('qwen3:8b', 16384) == {}
    with pytest.raises(ValueError, match='measured context'):
        LocalModel('qwen3.5:9b', context_tokens=32768)
    # An explicit empty dictionary is a deliberate opt-out for a diagnostic.
    assert LocalModel('qwen3.5:9b', runtime_options={}).runtime_options == {}
    monkeypatch.setenv(HARDWARE_PROFILE_ENV, 'unknown')
    with pytest.raises(ValueError, match='Unknown'):
        LocalModel('qwen3.5:9b')


class Answer(BaseModel):
    answer: str


def test_sync_options_are_frozen_separately_from_sampling_and_preserved_on_failure():
    selected = {'num_gpu': 31, 'num_batch': 128}
    role = LocalModel('qwen3.5:9b', max_tokens=600, context_tokens=16384, runtime_options=selected)
    selected['num_gpu'] = 0
    role.client = Mock()
    role.client.chat.return_value = {'model': role.name, 'done_reason': 'stop',
        'message': {'content': '{"answer":"synthetic"}'}, 'prompt_eval_count': 500, 'eval_count': 10}
    assert role.generate('Task', '{}', Answer).answer == 'synthetic'
    actual = role.client.chat.call_args.kwargs['options']
    assert actual['num_gpu'] == 31 and actual['num_batch'] == 128
    assert actual['num_ctx'] == 16384 and actual['num_predict'] == 600
    assert role.last_call['runtime_options'] == {'num_gpu': 31, 'num_batch': 128}
    assert 'num_gpu' not in role.last_call['sampling']
    role.runtime_options['num_gpu'] = 0
    assert role.last_call['runtime_options']['num_gpu'] == 31
    role.client.chat.side_effect = httpx.ReadTimeout('synthetic timeout')
    with pytest.raises(RuntimeError, match='timed out'):
        role.generate('Task', '{}', Answer)
    assert role.last_call['runtime_options']['num_gpu'] == 0
    assert role.last_response_text == ''


def test_both_thinking_transports_bind_hardware_options_and_reject_tampering():
    role, _, _ = adapter('qwen3.5:9b', runtime_options={'num_gpu': 31, 'num_batch': 128})
    role.generate('Task', '{}', BoundedAnswer)
    for call in (role.client.chat.call_args.kwargs, role.client.generate.call_args.kwargs):
        assert call['options']['num_gpu'] == 31 and call['options']['num_batch'] == 128
    validate_bounded_thinking_receipts(role.last_call, raw_response=RAW, expected_input_binding=known_binding())
    changed = deepcopy(role.last_call)
    changed['runtime_options']['num_gpu'] = 30
    with pytest.raises(ValueError, match='sampling policy'):
        validate_bounded_thinking_receipts(changed, raw_response=RAW, expected_input_binding=known_binding())


def test_async_stream_options_match_receipt_with_original_budget(monkeypatch):
    calls, clients = streaming_client(monkeypatch, [terminal('{"text":"synthetic"}')])
    role = model()
    role.runtime_options = validate_runtime_options({'num_gpu': 31, 'num_batch': 128})
    budget = PreparationBudget(2, max_calls=1, max_requests=6)
    with preparation_budget(budget):
        assert role.generate('Task', '{}', Output).text == 'synthetic'
    assert len(calls) == budget.requests == 1 and clients[0].closed
    assert calls[0]['options']['num_gpu'] == 31 and calls[0]['options']['num_batch'] == 128
    validate_stream_observation_receipt(role.last_call, raw_response=role.last_response_text)
    changed = deepcopy(role.last_call)
    changed['runtime_options']['num_batch'] = 256
    with pytest.raises(ValueError, match='changed actual options'):
        validate_stream_observation_receipt(changed, raw_response=role.last_response_text)


def test_private_worker_passes_only_the_named_hardware_profile(monkeypatch, tmp_path):
    from delivery.isolation import build_bwrap_command
    monkeypatch.setenv(HARDWARE_PROFILE_ENV, RTX2060_QWEN35_V1)
    monkeypatch.setenv('UNRELATED_RUNTIME_SETTING', 'excluded')
    monkeypatch.setattr('delivery.model_ipc.validate_socket', lambda path: path)
    _, env = build_bwrap_command(['python', 'worker.py'], tmp_path, bwrap='bwrap',
        project=tmp_path, prefixes=[], local_model=True, model_socket=tmp_path/'ollama.sock')
    assert env[HARDWARE_PROFILE_ENV] == RTX2060_QWEN35_V1
    assert 'UNRELATED_RUNTIME_SETTING' not in env
    _, env = build_bwrap_command(['python', 'worker.py'], tmp_path, bwrap='bwrap',
        project=tmp_path, prefixes=[])
    assert HARDWARE_PROFILE_ENV not in env
