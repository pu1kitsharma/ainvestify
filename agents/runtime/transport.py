"""Single-attempt local HTTP transport; no proxies, redirects or hosted fallback.

Socket timeout bounds each blocking operation, not a hard process cancellation.
The runtime checks total elapsed time again before executing any model tools.
"""
import http.client
import json
import time
from urllib.parse import urlsplit
from .loop import validate_endpoint

class LocalHTTPTransport:
    def __init__(self, *, max_bytes=2_000_000, connection_factory=http.client.HTTPConnection, clock=time.monotonic):
        if not 0 < max_bytes <= 8_000_000: raise ValueError('invalid response size bound')
        self.max_bytes, self.connection_factory, self.clock = max_bytes, connection_factory, clock

    supports_receipts = True

    def __call__(self, *, endpoint, request, timeout, receipt=None):
        endpoint = validate_endpoint(endpoint)
        if not 0 < timeout <= 120: raise ValueError('invalid remaining timeout')
        url = urlsplit(endpoint)
        start = self.clock()
        connection = self.connection_factory(url.hostname, url.port, timeout=timeout)
        try:
            body = json.dumps(request, allow_nan=False).encode()
            if receipt: receipt('request', body, {'complete': True})
            connection.request('POST', url.path + '/chat/completions', body=body,
                               headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
            response = connection.getresponse()
            length = response.getheader('Content-Length')
            if length is not None and (int(length) < 0 or int(length) > self.max_bytes):
                if receipt: receipt('response', b'', {'complete': False, 'http_status': response.status, 'declared_length': length})
                raise ValueError('response exceeds byte budget')
            data = bytearray()
            while True:
                remaining = timeout - (self.clock() - start)
                if remaining <= 0: raise TimeoutError('local response deadline exhausted')
                if connection.sock is not None: connection.sock.settimeout(remaining)
                chunk = response.read(min(65536, self.max_bytes + 1 - len(data)))
                if not chunk: break
                data.extend(chunk)
                if len(data) > self.max_bytes:
                    if receipt: receipt('response', bytes(data), {'complete': False, 'http_status': response.status})
                    raise ValueError('response exceeds byte budget')
            if receipt: receipt('response', bytes(data), {'complete': True, 'http_status': response.status})
            if response.status != 200: raise ValueError(f'local transport HTTP {response.status}')
            if self.clock() - start >= timeout: raise TimeoutError('local response deadline exhausted')
            def reject_constant(value): raise ValueError('nonfinite JSON constant')
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise ValueError('duplicate JSON key')
                    result[key] = value
                return result
            envelope = json.loads(bytes(data).decode('utf-8'), parse_constant=reject_constant, object_pairs_hook=unique_pairs)
            if not isinstance(envelope, dict) or not isinstance(envelope.get('choices'), list) or len(envelope['choices']) != 1:
                raise ValueError('invalid completion envelope')
            if not isinstance(envelope['choices'][0], dict): raise ValueError('invalid completion choice')
            message = envelope['choices'][0].get('message')
            if not isinstance(message, dict) or message.get('role') != 'assistant':
                raise ValueError('invalid assistant message')
            if not isinstance(envelope.get('usage'), dict): raise ValueError('invalid usage envelope')
            calls = message.get('tool_calls', [])
            if not isinstance(calls, list) or len(calls) > 16: raise ValueError('invalid tool calls')
            identifiers = set()
            for call in calls:
                if (not isinstance(call, dict) or not isinstance(call.get('id'), str) or not call['id']
                        or call['id'] in identifiers or call.get('type') != 'function'
                        or not isinstance(call.get('function'), dict)
                        or not isinstance(call['function'].get('name'), str)
                        or not isinstance(call['function'].get('arguments'), str)):
                    raise ValueError('invalid tool call')
                identifiers.add(call['id'])
            usage = envelope.get('usage', {}).get('total_tokens')
            if type(usage) is not int or usage < 0: raise ValueError('invalid usage envelope')
            return envelope
        finally:
            connection.close()


def make_transport(route=None, *, allowed_hosts=(), guided_json=None, guided_mode='response_format', **kwargs):
    """Transport factory. ``None``/Ollama name -> LocalHTTPTransport (unchanged);
    a resolved ``SelfHostedRoute`` or a ``selfhosted:<model>`` spec -> SelfHostedTransport.

    Returns (transport, endpoint). Pass ``endpoint`` and the route's model name to AgentRuntime.
    Hosted/cloud routes are rejected by the route parsers.
    """
    if route is None:
        return LocalHTTPTransport(**kwargs), 'http://127.0.0.1:11434/v1'
    from agents.inference.endpoint_policy import SelfHostedRoute, resolve_selfhosted_route
    from agents.inference.selfhosted_client import SelfHostedClient, SelfHostedTransport
    if isinstance(route, str):
        if route.startswith('selfhosted:'):
            route = resolve_selfhosted_route(route, allowed_hosts=allowed_hosts)
        else:
            from agents.inference.model_routing import validate_local_model_name
            validate_local_model_name(route)
            return LocalHTTPTransport(**kwargs), 'http://127.0.0.1:11434/v1'
    if not isinstance(route, SelfHostedRoute):
        raise ValueError('unsupported route')
    client = SelfHostedClient(route, allowed_hosts=allowed_hosts, **kwargs)
    return SelfHostedTransport(client, guided_json=guided_json, guided_mode=guided_mode), client.endpoint
