"""Exact Unix socket capability injected only by the isolated Linux worker runner."""
import os
import platform

import httpx


def transport_kwargs(*, asynchronous=False):
    value = os.environ.get('PRIVATE_OLLAMA_SOCKET')
    if value is None:
        return {}
    from delivery.model_ipc import SANDBOX_SOCKET, validate_socket
    if platform.system() != 'Linux' or value != SANDBOX_SOCKET:
        raise ValueError('Invalid private model socket capability')
    validate_socket(value)
    transport = httpx.AsyncHTTPTransport if asynchronous else httpx.HTTPTransport
    return {'transport': transport(uds=value, retries=0), 'trust_env': False, 'follow_redirects': False}


def local_tags(*, timeout=5):
    """Metadata uses the worker socket; legacy caller behavior stays intact."""
    import json
    import urllib.request
    if os.environ.get('PRIVATE_OLLAMA_SOCKET') is None:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=timeout) as response:
            return json.load(response)
    try:
        with httpx.Client(timeout=timeout, **transport_kwargs()) as client:
            with client.stream('GET', 'http://127.0.0.1:11434/api/tags') as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError('Local model inventory exceeds its limit')
                return json.loads(body)
    except httpx.HTTPError as exc:
        raise OSError('Local model inventory unavailable') from exc
