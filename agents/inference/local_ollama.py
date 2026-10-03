"""Loopback-only Ollama transport for legacy deal and CLI product routes."""
from __future__ import annotations

import httpx
import ollama

from agents.inference.model_routing import validate_local_model_name

LOOPBACK_OLLAMA = 'http://127.0.0.1:11434'


def _request(operation, model, *, timeout_seconds=240, **kwargs):
    validate_local_model_name(model)
    try:
        client = ollama.Client(host=LOOPBACK_OLLAMA, timeout=timeout_seconds)
        response = getattr(client, operation)(model=model, **kwargs)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise RuntimeError('Local Ollama inference is unavailable at 127.0.0.1:11434; no hosted fallback was used.') from exc
    except ollama.ResponseError as exc:
        if exc.status_code == 404:
            raise RuntimeError(f'Installed local Ollama model {model!r} was not found; no download or hosted fallback was used.') from exc
        raise RuntimeError(f'Local Ollama inference failed (HTTP {exc.status_code}); no hosted fallback was used.') from exc
    returned = response.get('model') if isinstance(response, dict) else getattr(response, 'model', None)
    expected = {model} if ':' in model else {model, model + ':latest'}
    if returned and returned not in expected:
        raise ValueError('Local runtime returned a different model than requested; the result was not accepted.')
    if operation == 'chat' and response.get('done_reason') not in (None, 'stop'):
        raise ValueError('Local model response did not finish normally; the result was not accepted.')
    return response


def local_chat(*, model, messages, **kwargs):
    return _request('chat', model, messages=messages, **kwargs)


def local_embed(*, model, input, **kwargs):
    return _request('embed', model, input=input, **kwargs)
