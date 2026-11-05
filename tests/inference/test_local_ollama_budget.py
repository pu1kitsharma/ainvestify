"""Private legacy transports cancel, retain invalid raw output and freeze placement."""
import asyncio
from copy import deepcopy

import pytest

from agents.inference import local_ollama as transport
from agents.inference.runtime_options import HARDWARE_PROFILE_ENV, RTX2060_QWEN35_V1
from agents.preparation.preparation_budget import PreparationBudget, PreparationBudgetExceeded, preparation_budget


def terminal(**changes):
    response = {'model': 'qwen3.5:9b', 'done': True, 'done_reason': 'stop',
                'message': {'content': ' {"answer":"synthetic"} '},
                'prompt_eval_count': 50, 'eval_count': 7, 'total_duration': 123}
    response.update(changes)
    return response


def async_client(monkeypatch, response=None, *, stall=False):
    calls, instances = [], []
    class Client:
        def __init__(self, **kwargs):
            self._client = self; self.settings = kwargs
            self.closed = self.cancelled = False
            instances.append(self)
        async def chat(self, **kwargs):
            calls.append(deepcopy(kwargs))
            try:
                if stall: await asyncio.sleep(30)
                return deepcopy(response)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        async def aclose(self): self.closed = True
    monkeypatch.setattr(transport.ollama, 'AsyncClient', Client)
    return calls, instances


def test_explicit_profile_reaches_actual_request_without_altering_context_or_output(monkeypatch):
    monkeypatch.setenv(HARDWARE_PROFILE_ENV, RTX2060_QWEN35_V1)
    options = {'temperature': 0, 'num_ctx': 16384, 'num_predict': 1024}
    effective = transport.effective_chat_options('qwen3.5:9b', options)
    assert effective == {**options, 'num_gpu': 31, 'num_batch': 128}
    assert 'num_gpu' not in options
    assert transport.effective_chat_options('qwen3.5:9b', effective) == effective
    assert transport.effective_chat_options('qwen3.5:9b', {'temperature': 0}) == {'temperature': 0}
    assert transport.effective_chat_options('phi4-mini', options) == options
    assert transport.effective_chat_options('qwen3.5:9b', {**options, 'num_gpu': 0})['num_gpu'] == 0
    calls, clients = async_client(monkeypatch, terminal())
    with preparation_budget(PreparationBudget(2, max_calls=1, max_requests=6)):
        transport.local_chat(model='qwen3.5:9b', messages=[], options=options)
    assert calls[0]['options'] == effective and clients[0].closed


def test_deadline_cancels_the_actual_async_operation_and_closes_transport(monkeypatch):
    calls, clients = async_client(monkeypatch, stall=True)
    captured = []
    budget = PreparationBudget(.03, max_calls=1, max_requests=6)
    with preparation_budget(budget), pytest.raises(PreparationBudgetExceeded, match='cancelled'):
        transport.local_chat(model='qwen3.5:9b', messages=[], response_recorder=captured.append)
    assert len(calls) == budget.requests == 1 and captured == []
    assert clients[0].cancelled and clients[0].closed
    assert clients[0].settings['host'] == 'http://127.0.0.1:11434'
    assert 0 < clients[0].settings['timeout'] <= .03


@pytest.mark.parametrize('response', [terminal(model='other-model'), terminal(model=None),
    terminal(done_reason='length'), terminal(done=False), terminal(done_reason=None)])
def test_raw_invalid_response_is_recorded_before_rejection_and_recorder_is_not_sent_to_sdk(monkeypatch, response):
    calls, clients = async_client(monkeypatch, response)
    captured = []
    with preparation_budget(PreparationBudget(2)), pytest.raises(ValueError):
        transport.local_chat(model='qwen3.5:9b', messages=[], response_recorder=captured.append)
    assert captured == [response] and clients[0].closed
    assert 'response_recorder' not in calls[0]


def test_capture_cannot_mutate_the_response_used_for_identity_validation(monkeypatch):
    calls, clients = async_client(monkeypatch, terminal(model='other-model'))
    def mutate(value): value['model'] = 'qwen3.5:9b'
    with preparation_budget(PreparationBudget(2)), pytest.raises(ValueError, match='different model'):
        transport.local_chat(model='qwen3.5:9b', messages=[], response_recorder=mutate)
    assert len(calls) == 1 and clients[0].closed


def test_capture_storage_failure_closes_transport_and_does_not_retry(monkeypatch):
    calls, clients = async_client(monkeypatch, terminal())
    def full(value): raise OSError('synthetic evidence storage failure')
    with preparation_budget(PreparationBudget(2)), pytest.raises(OSError, match='storage failure'):
        transport.local_chat(model='qwen3.5:9b', messages=[], response_recorder=full)
    assert len(calls) == 1 and clients[0].closed


def test_transport_count_is_enforced_before_starting_another_client(monkeypatch):
    calls, clients = async_client(monkeypatch, terminal())
    budget = PreparationBudget(2, max_calls=1, max_requests=1)
    with preparation_budget(budget):
        transport.local_chat(model='qwen3.5:9b', messages=[])
        with pytest.raises(PreparationBudgetExceeded, match='request limit'):
            transport.local_chat(model='qwen3.5:9b', messages=[])
    assert len(calls) == len(clients) == budget.requests == 1


def test_cli_default_remains_sync_240_seconds_and_retains_raw_before_rejection(monkeypatch):
    settings, captured = [], []
    class Client:
        def __init__(self, **kwargs): self._client = self; self.closed = False; settings.append(kwargs)
        def chat(self, **kwargs):
            assert 'response_recorder' not in kwargs
            return terminal(done_reason='length')
        def close(self): self.closed = True
    monkeypatch.setattr(transport.ollama, 'Client', Client)
    with pytest.raises(ValueError, match='did not finish normally'):
        transport.local_chat(model='qwen3.5:9b', messages=[], response_recorder=captured.append)
    assert settings[0]['timeout'] == 240 and captured[0]['done_reason'] == 'length'
