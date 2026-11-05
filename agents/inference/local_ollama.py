"""Loopback-only Ollama transport for legacy deal and CLI product routes."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import httpx
import ollama

from agents.inference.model_routing import validate_local_model_name
from agents.inference.local_transport import transport_kwargs
from agents.inference.runtime_options import hardware_runtime_options, validate_runtime_options
from agents.preparation.preparation_budget import ACTIVE_BUDGET, PreparationBudgetExceeded

LOOPBACK_OLLAMA = 'http://127.0.0.1:11434'


def effective_chat_options(model, options=None):
    """Freeze actual placement for callers retaining a private request receipt.

    A named profile requires an explicit context; no implicit context, model,
    output limit or CLI sampling default is changed. Explicit hardware options
    remain authoritative and the operation is idempotent.
    """
    validate_local_model_name(model)
    if options is None:
        return None
    if isinstance(options, ollama.Options):
        options = options.model_dump(exclude_none=True)
    if not isinstance(options, dict):
        raise TypeError('Local chat options require a dictionary or Ollama Options.')
    actual = deepcopy(options)
    validate_runtime_options({key: actual[key] for key in ('num_gpu', 'num_batch') if key in actual})
    placement = hardware_runtime_options(model, actual['num_ctx']) if 'num_ctx' in actual else {}
    return {**placement, **actual}


def _request(operation, model, *, timeout_seconds=240, response_recorder=None, **kwargs):
    validate_local_model_name(model)
    if response_recorder is not None and not callable(response_recorder):
        raise TypeError('Local response recorder must be callable.')
    if operation == 'chat' and 'options' in kwargs:
        kwargs['options'] = effective_chat_options(model, kwargs['options'])
    budget = ACTIVE_BUDGET.get()
    def record(response):
        if response_recorder is not None:
            # Recorder failures fail the operation; an invalid terminal/model
            # still reaches this private evidence sink before validation.
            response_recorder(deepcopy(response))
        return response
    try:
        if budget is None:
            client = ollama.Client(host=LOOPBACK_OLLAMA, timeout=timeout_seconds, **transport_kwargs())
            try:
                response = record(getattr(client, operation)(model=model, **kwargs))
            finally:
                close = getattr(getattr(client, '_client', None), 'close', None)
                if callable(close):
                    close()
        else:
            budget.start_request()
            async def bounded():
                remaining = budget.remaining()
                timeout = remaining if timeout_seconds is None else min(timeout_seconds, remaining)
                client = ollama.AsyncClient(host=LOOPBACK_OLLAMA, timeout=timeout,
                                           **transport_kwargs(asynchronous=True))
                try:
                    return record(await asyncio.wait_for(
                        getattr(client, operation)(model=model, **kwargs), timeout=timeout))
                except (asyncio.TimeoutError, httpx.ReadTimeout) as exc:
                    raise PreparationBudgetExceeded('Private local inference reached its time limit; the request was cancelled and saved evidence is retained.') from exc
                finally:
                    await client._client.aclose()
            response = asyncio.run(bounded())
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise RuntimeError('Local Ollama inference is unavailable at 127.0.0.1:11434; no hosted fallback was used.') from exc
    except httpx.ReadTimeout as exc:
        raise RuntimeError('Local Ollama inference timed out; no hosted fallback was used.') from exc
    except ollama.ResponseError as exc:
        if exc.status_code == 404:
            raise RuntimeError(f'Installed local Ollama model {model!r} was not found; no download or hosted fallback was used.') from exc
        raise RuntimeError(f'Local Ollama inference failed (HTTP {exc.status_code}); no hosted fallback was used.') from exc
    returned = response.get('model') if isinstance(response, dict) else getattr(response, 'model', None)
    expected = {model} if ':' in model else {model, model + ':latest'}
    if returned not in expected and (returned is not None or budget is not None):
        raise ValueError('Local runtime returned a different model than requested; the result was not accepted.')
    if operation == 'chat' and (response.get('done_reason') not in (None, 'stop')
            or budget is not None and (response.get('done') is not True or response.get('done_reason') != 'stop')):
        raise ValueError('Local model response did not finish normally; the result was not accepted.')
    return response


def local_chat(*, model, messages, **kwargs):
    return _request('chat', model, messages=messages, **kwargs)


def local_embed(*, model, input, **kwargs):
    return _request('embed', model, input=input, **kwargs)
