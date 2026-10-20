"""OpenAI-compatible client and runtime transport for a private self-hosted server (vLLM).

Scope and guarantees (all enforced here, none claimed beyond offline tests):
  * Only routes resolved by ``endpoint_policy.resolve_selfhosted_route`` are accepted;
    the base URL is re-validated (RFC1918 literal or explicit internal allow-list) on
    construction and on every call. No redirects, proxies, retries or fallback endpoints.
  * The bearer token lives only in the route object and the Authorization header. It is
    never written to receipts, errors or ``repr``; any echo of it in a server body is masked
    in exception text.
  * ``SelfHostedTransport`` matches the ``NativeOllamaTransport`` contract used by
    ``agents.runtime.loop.AgentRuntime``: ``supports_receipts``, raw request/response body
    receipts, fail-closed envelope validation, InfraFault for server/frame faults and
    ModelFault for output-cap truncation.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import time
from urllib.parse import urlsplit

from agents.inference.endpoint_policy import SelfHostedRoute, validate_selfhosted_endpoint
from agents.runtime.loop import InfraFault, ModelFault

ADAPTER = 'openai-compat-selfhosted/v1'
_ALLOWED_REQUEST_KEYS = {'model', 'messages', 'tools', 'tool_choice', 'max_tokens', 'temperature', 'top_p', 'seed', 'stop'}
_MAX_BYTES = 8_000_000


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('nonfinite JSON constant')


class SelfHostedClient:
    """Single-attempt JSON POST/GET with byte bounds, deadlines and optional raw receipts."""

    def __init__(self, route, *, allowed_hosts=(), connection_factory=None, clock=time.monotonic, max_bytes=_MAX_BYTES):
        if not isinstance(route, SelfHostedRoute):
            raise ValueError('A resolved self-hosted route is required')
        if not 0 < max_bytes <= _MAX_BYTES:
            raise ValueError('invalid response size bound')
        self.route, self.allowed_hosts = route, tuple(allowed_hosts)
        self.base_url = validate_selfhosted_endpoint(route.base_url, allowed_hosts=self.allowed_hosts)
        parts = urlsplit(self.base_url)
        self._https = parts.scheme == 'https'
        self._host, self._port = parts.hostname, parts.port
        self._prefix = '/v1'
        self.connection_factory = connection_factory
        self.clock, self.max_bytes = clock, max_bytes

    @property
    def endpoint(self):
        """Canonical runtime endpoint (…/v1), valid for AgentRuntime via the transport's validator."""
        return self.base_url.rstrip('/').removesuffix('/v1') + '/v1'

    def _mask(self, text):
        token = getattr(self.route, '_token', '')
        return text.replace(token, '<redacted>') if token else text

    def _connect(self, timeout):
        validate_selfhosted_endpoint(self.base_url, allowed_hosts=self.allowed_hosts)  # re-check every call
        factory = self.connection_factory or (http.client.HTTPSConnection if self._https else http.client.HTTPConnection)
        return factory(self._host, self._port, timeout=timeout)

    def request(self, method, path, payload=None, *, timeout, receipt=None):
        """Return (status, raw_bytes). Receipts get request/response bytes; headers never."""
        if not 0 < timeout <= 3600:
            raise ValueError('invalid remaining timeout')
        body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        headers = {'Accept': 'application/json', **self.route.headers()}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        start = self.clock()
        connection = self._connect(timeout)
        try:
            if receipt and body is not None:
                receipt('request', body, {'complete': True, 'adapter': ADAPTER, 'path': self._prefix + path})
            try:
                connection.request(method, self._prefix + path, body=body, headers=headers)
                response = connection.getresponse()
            except (OSError, http.client.HTTPException) as exc:
                raise InfraFault(self._mask(f'{type(exc).__name__}: {exc}')) from None
            meta = {'adapter': ADAPTER, 'http_status': response.status}
            declared = response.getheader('Content-Length')
            if declared is not None and not 0 <= int(declared) <= self.max_bytes:
                if receipt:
                    receipt('response', b'', {**meta, 'complete': False, 'declared_length': declared})
                raise ValueError('response exceeds byte budget')
            data = bytearray()
            while True:
                remaining = timeout - (self.clock() - start)
                if remaining <= 0:
                    raise TimeoutError('self-hosted response deadline exhausted')
                if getattr(connection, 'sock', None) is not None:
                    connection.sock.settimeout(remaining)
                try:
                    chunk = response.read(min(65536, self.max_bytes + 1 - len(data)))
                except (OSError, http.client.HTTPException) as exc:
                    raise InfraFault(self._mask(f'{type(exc).__name__}: {exc}')) from None
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > self.max_bytes:
                    if receipt:
                        receipt('response', bytes(data), {**meta, 'complete': False})
                    raise ValueError('response exceeds byte budget')
            if receipt:
                receipt('response', bytes(data), {**meta, 'complete': True})
            if self.clock() - start >= timeout:
                raise TimeoutError('self-hosted response deadline exhausted')
            return response.status, bytes(data)
        finally:
            connection.close()

    def parse(self, status, data):
        """Fail-closed status/JSON handling shared by chat and listing calls."""
        if status >= 500 or status == 429:
            raise InfraFault(f'self-hosted HTTP {status}')
        if status in (401, 403):
            raise ValueError('self-hosted server rejected the bearer token')
        if status != 200:
            raise ValueError(f'self-hosted HTTP {status}')
        if not data.strip():
            raise InfraFault('empty self-hosted response frame')
        try:
            raw = json.loads(data.decode('utf-8'), parse_constant=_reject_constant, object_pairs_hook=_unique_pairs)
        except UnicodeDecodeError:
            raise InfraFault('malformed self-hosted response frame (not UTF-8)') from None
        except json.JSONDecodeError:
            raise InfraFault('malformed self-hosted response frame (not JSON)') from None
        if not isinstance(raw, dict):
            raise InfraFault('malformed self-hosted response frame (not an object)')
        return raw

    def with_model(self, model):
        """Same endpoint and token, different served model / LoRA adapter name."""
        route = SelfHostedRoute(model, self.route.base_url, self.route._token)
        return SelfHostedClient(route, allowed_hosts=self.allowed_hosts, connection_factory=self.connection_factory,
                                clock=self.clock, max_bytes=self.max_bytes)

    def raw_completion(self, prompt, *, max_tokens, temperature=0, timeout=120, receipt=None):
        """Raw-text completion (/v1/completions) -> text; truncation by max_tokens is expected."""
        if not isinstance(prompt, str) or type(max_tokens) is not int or max_tokens <= 0:
            raise ValueError('prompt text and positive max_tokens required')
        payload = {'model': self.route.model, 'prompt': prompt, 'max_tokens': max_tokens, 'temperature': temperature, 'stream': False}
        raw = self.parse(*self.request('POST', '/completions', payload, timeout=timeout, receipt=receipt))
        choices = raw.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise InfraFault('malformed completion frame')
        if raw.get('model') != self.route.model:
            raise ValueError('returned model does not match request')
        text = choices[0].get('text')
        if not isinstance(text, str):
            raise InfraFault('malformed completion frame (no text)')
        return text

    def load_lora_adapter(self, name, path, *, timeout=300):
        """vLLM runtime LoRA loading (needs VLLM_ALLOW_RUNTIME_LORA_UPDATING=True). Path is on the SERVER's disk."""
        status, data = self.request('POST', '/load_lora_adapter', {'lora_name': name, 'lora_path': str(path)}, timeout=timeout)
        if status != 200:
            self.parse(status, data)
            raise ValueError(f'adapter load failed HTTP {status}')
        return True

    def list_models(self, *, timeout=10, receipt=None):
        status, data = self.request('GET', '/models', timeout=timeout, receipt=receipt)
        raw = self.parse(status, data)
        items = raw.get('data')
        if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get('id'), str) for i in items):
            raise InfraFault('malformed model listing')
        return [i['id'] for i in items]

    def chat(self, messages, *, max_tokens, temperature=0, guided_json=None, timeout=120, receipt=None, extra=None, allow_length=False):
        """Plain chat completion -> assistant text. Used by batch generators (no tools)."""
        request = {'model': self.route.model, 'messages': messages, 'max_tokens': max_tokens, 'temperature': temperature, **(extra or {})}
        message = SelfHostedTransport(self, guided_json=guided_json, allow_length=allow_length).complete(request, timeout=timeout, receipt=receipt)
        return message['choices'][0]['message'].get('content') or ''


class SelfHostedTransport:
    """Drop-in for the runtime transport slot; same fail-closed behaviour as the Ollama native adapter."""
    supports_receipts = True

    def __init__(self, client, *, guided_json=None, guided_mode='response_format', max_timeout=600, allow_length=False):
        if not isinstance(client, SelfHostedClient):
            raise ValueError('SelfHostedClient required')
        if guided_mode not in {'response_format', 'guided_json'}:
            raise ValueError('unsupported guided decoding mode')
        if guided_json is not None and not isinstance(guided_json, dict):
            raise ValueError('guided_json must be a JSON-schema object')
        self.client, self.guided_json, self.guided_mode, self.max_timeout = client, guided_json, guided_mode, max_timeout
        self.allow_length = allow_length   # batch generators accept truncation; the agent runtime never does
        self.sequence = 0

    # AgentRuntime consults this instead of its loopback-only validator.
    def validate_endpoint(self, endpoint):
        if not isinstance(endpoint, str) or endpoint.rstrip('/') != self.client.endpoint:
            raise ValueError('endpoint does not match the validated self-hosted route')
        return endpoint.rstrip('/')

    def __call__(self, *, endpoint, request, timeout, receipt=None):
        self.validate_endpoint(endpoint)
        if not 0 < timeout <= self.max_timeout:
            raise ValueError('invalid remaining timeout')
        return self.complete(request, timeout=timeout, receipt=receipt)

    def _payload(self, request):
        unknown = set(request) - _ALLOWED_REQUEST_KEYS
        if unknown:
            raise ValueError(f'unsupported request fields: {sorted(unknown)}')
        if request.get('model') != self.client.route.model:
            raise ValueError('request model does not match the resolved self-hosted route')
        limit = request.get('max_tokens')
        if type(limit) is not int or limit <= 0:
            raise ValueError('explicit positive max_tokens required')
        payload = {k: v for k, v in request.items() if k != 'tools' or v}
        payload.setdefault('temperature', 0)
        payload['stream'] = False
        if payload.get('tools'):
            payload.setdefault('tool_choice', 'auto')
        if self.guided_json is not None:
            if payload.get('tools'):
                raise ValueError('guided decoding cannot be combined with tool calling')
            if self.guided_mode == 'response_format':
                payload['response_format'] = {'type': 'json_schema',
                                              'json_schema': {'name': 'output', 'schema': self.guided_json, 'strict': True}}
            else:
                payload['guided_json'] = self.guided_json
        return payload

    def complete(self, request, *, timeout, receipt=None):
        payload = self._payload(request)
        self.sequence += 1
        status, data = self.client.request('POST', '/chat/completions', payload, timeout=timeout, receipt=receipt)
        raw = self.client.parse(status, data)
        choices = raw.get('choices')
        if not isinstance(choices, list) or not choices:
            raise InfraFault('malformed completion frame (no choices)')
        if len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError('invalid completion choice')
        if raw.get('model') != payload['model']:
            raise ValueError('returned model does not match request')
        choice = choices[0]
        message = choice.get('message')
        if not isinstance(message, dict) or message.get('role') != 'assistant':
            raise InfraFault('malformed completion frame (no assistant message)')
        finish = choice.get('finish_reason')
        if finish == 'length' and not self.allow_length:
            raise ModelFault('generation hit the output-token cap before a complete answer or tool call (finish_reason length)')
        usage = raw.get('usage')
        if not isinstance(usage, dict):
            raise ValueError('invalid usage envelope')
        prompt, completion = usage.get('prompt_tokens'), usage.get('completion_tokens')
        if any(type(v) is not int or v < 0 for v in (prompt, completion)):
            raise ValueError('usage counters required')
        total = usage.get('total_tokens', prompt + completion)
        if type(total) is not int or total < 0:
            raise ValueError('invalid usage envelope')
        calls = message.get('tool_calls') or []
        if not isinstance(calls, list) or len(calls) > 16:
            raise ValueError('invalid tool calls')
        if finish not in (('stop', 'tool_calls', 'length') if self.allow_length else ('stop', 'tool_calls')) or (finish == 'tool_calls' and not calls):
            raise ValueError('missing or nonterminal finish reason')
        normalized, seen = [], set()
        for index, call in enumerate(calls):
            if not isinstance(call, dict) or call.get('type') not in (None, 'function') or not isinstance(call.get('function'), dict):
                raise ValueError('invalid tool call')
            function = call['function']
            arguments = function.get('arguments')
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, allow_nan=False)
            if not isinstance(function.get('name'), str) or not function['name'] or not isinstance(arguments, str):
                raise ValueError('invalid tool call')
            identifier = call.get('id') or f'selfhosted-{self.sequence}-{index}'
            if not isinstance(identifier, str) or identifier in seen:
                raise ValueError('invalid tool call')
            seen.add(identifier)
            normalized.append({'id': identifier, 'type': 'function', 'function': {'name': function['name'], 'arguments': arguments}})
        content = message.get('content')
        if content is not None and not isinstance(content, str):
            raise ValueError('invalid assistant content')
        return {'model': raw['model'],
                'choices': [{'finish_reason': 'tool_calls' if normalized else 'stop',
                             'message': {'role': 'assistant', 'content': content, 'tool_calls': normalized}}],
                'usage': {'total_tokens': total, 'prompt_tokens': prompt, 'completion_tokens': completion},
                'adapter': {'contract': ADAPTER, 'raw_finish_reason': finish,
                            'response_sha256': hashlib.sha256(data).hexdigest()}}
