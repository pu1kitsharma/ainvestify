import json
import pytest

from agents.inference.endpoint_policy import resolve_selfhosted_route
from agents.inference.selfhosted_client import SelfHostedClient, SelfHostedTransport
from agents.runtime import AgentRuntime
from agents.runtime.loop import InfraFault, ModelFault
from agents.runtime.transport import LocalHTTPTransport, make_transport
from tests.selfhosted.fake_openai import TOKEN, FakeServer, completion

ALLOW = ('localhost',)


@pytest.fixture
def server():
    with FakeServer() as s:
        yield s


def build(server, model='banker-base', **kw):
    route = resolve_selfhosted_route('selfhosted:' + model, base_url=server.base_url, token=TOKEN, allowed_hosts=ALLOW)
    client = SelfHostedClient(route, allowed_hosts=ALLOW)
    return client, SelfHostedTransport(client, **kw)


def request(model='banker-base', **kw):
    return {'model': model, 'messages': [{'role': 'user', 'content': 'hi'}], 'tools': [], 'max_tokens': 64, **kw}


def call(transport, req=None, receipt=None, timeout=5):
    return transport(endpoint=transport.client.endpoint, request=req or request(), timeout=timeout, receipt=receipt)


def test_happy_path_sends_bearer_and_records_receipts(server):
    server.reply(completion())
    _, t = build(server)
    receipts = []
    out = call(t, receipt=lambda phase, data, meta: receipts.append((phase, data, meta)))
    assert out['choices'][0]['finish_reason'] == 'stop' and out['usage']['total_tokens'] == 12 and out['model'] == 'banker-base'
    sent = server.requests[0]
    assert sent['path'] == '/v1/chat/completions' and sent['headers']['Authorization'] == 'Bearer ' + TOKEN
    body = json.loads(sent['body'])
    assert body['stream'] is False and body['temperature'] == 0 and 'tools' not in body  # empty tools dropped
    assert [r[0] for r in receipts] == ['request', 'response']
    assert receipts[0][1] == sent['body']                       # exact raw bytes sent
    assert json.loads(receipts[1][1])['model'] == 'banker-base' and receipts[1][2]['http_status'] == 200 and receipts[1][2]['complete']
    assert all(TOKEN.encode() not in r[1] and TOKEN not in json.dumps(r[2]) for r in receipts)
    assert out['adapter']['response_sha256']


def test_tool_calls_normalised(server):
    server.reply(completion(content=None, calls=[
        {'id': 'a', 'type': 'function', 'function': {'name': 'wb.read', 'arguments': {'x': 1}}},
        {'type': 'function', 'function': {'name': 'wb.trace', 'arguments': '{}'}}]))
    _, t = build(server)
    out = call(t, request(tools=[{'type': 'function', 'function': {'name': 'wb.read'}}]))
    calls = out['choices'][0]['message']['tool_calls']
    assert out['choices'][0]['finish_reason'] == 'tool_calls'
    assert calls[0]['function']['arguments'] == '{"x": 1}' and calls[1]['id'].startswith('selfhosted-')
    assert json.loads(server.requests[0]['body'])['tool_choice'] == 'auto'


def test_duplicate_tool_ids_rejected(server):
    fn = {'name': 'a', 'arguments': '{}'}
    server.reply(completion(calls=[{'id': 'd', 'type': 'function', 'function': fn}, {'id': 'd', 'type': 'function', 'function': fn}]))
    with pytest.raises(ValueError):
        call(build(server)[1])


@pytest.mark.parametrize('body', [b'', b'   ', b'not json', b'[]', b'\xff\xfe', json.dumps({'choices': []}).encode(),
                                  json.dumps({'model': 'banker-base'}).encode()])
def test_empty_or_malformed_frames_are_infra_faults(server, body):
    server.reply(body)
    with pytest.raises(InfraFault):
        call(build(server)[1])


@pytest.mark.parametrize('status', [500, 502, 503, 429])
def test_server_errors_are_infra_faults(server, status):
    server.reply(b'{"error":"busy"}', status=status)
    with pytest.raises(InfraFault):
        call(build(server)[1])


def test_connection_refused_is_infra_fault_without_token_leak():
    route = resolve_selfhosted_route('selfhosted:m', base_url='http://localhost:9', token=TOKEN, allowed_hosts=ALLOW)
    t = SelfHostedTransport(SelfHostedClient(route, allowed_hosts=ALLOW))
    with pytest.raises(InfraFault) as err:
        call(t, request('m'))
    assert TOKEN not in str(err.value)


def test_error_text_masks_token(server):
    class Boom:
        def __init__(self, *a, **k): pass
        def request(self, *a, **k): raise OSError('proxy said ' + TOKEN)
        def close(self): pass
    route = resolve_selfhosted_route('selfhosted:m', base_url=server.base_url, token=TOKEN, allowed_hosts=ALLOW)
    t = SelfHostedTransport(SelfHostedClient(route, allowed_hosts=ALLOW, connection_factory=Boom))
    with pytest.raises(InfraFault) as err:
        call(t, request('m'))
    assert TOKEN not in str(err.value) and '<redacted>' in str(err.value)


def test_auth_rejection_is_not_an_infra_retry(server):
    server.reply(b'{"error":"nope"}', status=401)
    with pytest.raises(ValueError, match='bearer token') as err:
        call(build(server)[1])
    assert not isinstance(err.value, InfraFault)


def test_finish_reason_length_is_model_fault(server):
    server.reply(completion(finish='length', content='cut off'))
    with pytest.raises(ModelFault):
        call(build(server)[1])


def test_length_accepted_only_for_batch_generators(server):
    server.reply(completion(finish='length', content='partial'))
    client, _ = build(server)
    assert client.chat([{'role': 'user', 'content': 'x'}], max_tokens=8, allow_length=True) == 'partial'
    with pytest.raises(ModelFault):
        client.chat([{'role': 'user', 'content': 'x'}], max_tokens=8)


def test_model_identity_mismatch_rejected(server):
    server.reply(completion(model='something-else'))
    with pytest.raises(ValueError, match='model'):
        call(build(server)[1])


def test_request_model_must_match_route(server):
    server.reply(completion())
    with pytest.raises(ValueError, match='route'):
        call(build(server)[1], request('other-model'))
    assert server.requests == []


@pytest.mark.parametrize('mutate', [lambda c: c.pop('usage'), lambda c: c['usage'].pop('prompt_tokens'),
                                    lambda c: c['usage'].update(completion_tokens=-1),
                                    lambda c: c['choices'][0].update(finish_reason='content_filter'),
                                    lambda c: c['choices'][0].update(finish_reason='tool_calls')])
def test_incomplete_or_nonterminal_envelopes_fail_closed(server, mutate):
    c = completion()
    mutate(c)
    server.reply(c)
    with pytest.raises(ValueError):
        call(build(server)[1])


def test_duplicate_json_keys_and_nonfinite_rejected(server):
    for raw in (b'{"choices":[],"choices":[]}', b'{"usage":{"total_tokens":NaN}}'):
        server.reply(raw)
        with pytest.raises(ValueError):
            call(build(server)[1])


def test_oversized_response_bounded_and_receipted(server):
    server.reply(b'x' * 5000)
    route = resolve_selfhosted_route('selfhosted:banker-base', base_url=server.base_url, token=TOKEN, allowed_hosts=ALLOW)
    t = SelfHostedTransport(SelfHostedClient(route, allowed_hosts=ALLOW, max_bytes=1000))
    receipts = []
    with pytest.raises(ValueError, match='byte budget'):
        call(t, receipt=lambda p, d, m: receipts.append((p, m)))
    assert receipts[-1][0] == 'response' and receipts[-1][1]['complete'] is False


def test_guided_decoding_modes_and_tool_conflict(server):
    schema = {'type': 'object', 'properties': {'a': {'type': 'integer'}}}
    server.reply(completion(content='{"a":1}'))
    call(build(server, guided_json=schema)[1])
    assert json.loads(server.requests[-1]['body'])['response_format']['json_schema']['schema'] == schema
    call(build(server, guided_json=schema, guided_mode='guided_json')[1])
    assert json.loads(server.requests[-1]['body'])['guided_json'] == schema
    with pytest.raises(ValueError, match='tool'):
        call(build(server, guided_json=schema)[1], request(tools=[{'type': 'function'}]))


def test_unknown_request_fields_rejected(server):
    with pytest.raises(ValueError, match='unsupported'):
        call(build(server)[1], request(extra_body={'x': 1}))
    assert server.requests == []


def test_runtime_endpoint_must_match_validated_route(server):
    _, t = build(server)
    with pytest.raises(ValueError):
        t(endpoint='http://127.0.0.1:11434/v1', request=request(), timeout=5)


# ---- policy: private hosts only --------------------------------------------------------------
def test_public_and_unlisted_hosts_rejected_before_any_connection(monkeypatch):
    def forbidden(*a, **k): raise AssertionError('network attempted')
    monkeypatch.setenv('SELFHOSTED_TOKEN', TOKEN)
    for url in ('http://8.8.8.8:8000', 'https://api.anthropic.com', 'http://gpu.internal:8000', 'http://169.254.169.254', 'http://127.0.0.1:8000'):
        monkeypatch.setenv('SELFHOSTED_BASE_URL', url)
        with pytest.raises(ValueError):
            make_transport('selfhosted:banker-base', allowed_hosts=())
    monkeypatch.setenv('SELFHOSTED_BASE_URL', 'http://10.20.0.5:8000')
    t, endpoint = make_transport('selfhosted:banker-base', connection_factory=forbidden)
    assert endpoint == 'http://10.20.0.5:8000/v1' and t.supports_receipts


def test_client_rejects_non_route_and_revalidates(server):
    with pytest.raises(ValueError):
        SelfHostedClient('http://10.0.0.5:8000')
    route = resolve_selfhosted_route('selfhosted:m', base_url=server.base_url, token=TOKEN, allowed_hosts=ALLOW)
    with pytest.raises(ValueError):
        SelfHostedClient(route)       # 'localhost' is not on the allow-list unless passed


def test_make_transport_keeps_ollama_default_and_rejects_hosted():
    t, endpoint = make_transport()
    assert isinstance(t, LocalHTTPTransport) and endpoint == 'http://127.0.0.1:11434/v1'
    t, endpoint = make_transport('qwen3:8b')
    assert isinstance(t, LocalHTTPTransport)
    for bad in ('anthropic-api:claude', 'deepseek-api:x', 'gpt-cloud:1', 'selfhosted:model-cloud'):
        with pytest.raises(ValueError):
            make_transport(bad)


# ---- runtime integration ---------------------------------------------------------------------
def runtime(tmp_path, server, model='banker-base'):
    route = resolve_selfhosted_route('selfhosted:' + model, base_url=server.base_url, token=TOKEN, allowed_hosts=ALLOW)
    transport, endpoint = make_transport(route, allowed_hosts=ALLOW)
    return AgentRuntime(endpoint=endpoint, model=model, transport=transport, tools={}, directory=tmp_path), endpoint


def test_agent_runtime_runs_with_receipts_and_checkpoint_has_no_token(tmp_path, server):
    server.reply(completion(content='final draft'))
    rt, endpoint = runtime(tmp_path, server)
    assert endpoint == server.base_url + '/v1'
    state = rt.run('im_writer', 'synthetic mandate')
    assert state['status'] == 'human_review_required' and state['tokens'] == 12
    assert [r['phase'] for r in state['receipts']] == ['request', 'response']
    rt._verify_receipts()
    for f in tmp_path.rglob('*'):
        if f.is_file():
            assert TOKEN.encode() not in f.read_bytes()
    reopened = AgentRuntime.open(directory=tmp_path, endpoint=endpoint, model='banker-base', transport=rt.transport, tools={})
    assert reopened.endpoint == endpoint


def test_agent_runtime_fault_classes(tmp_path, server):
    server.reply(b'')
    state = runtime(tmp_path / 'a', server)[0].run('im_writer', 'm')
    assert state['status'] == 'failed' and state['fault_class'] == 'infra_fault'
    server.reply(completion(finish='length'))
    state = runtime(tmp_path / 'b', server)[0].run('im_writer', 'm')
    assert state['fault_class'] == 'model_error'
    server.reply(completion(model='drift'))
    state = runtime(tmp_path / 'c', server)[0].run('im_writer', 'm')
    assert state['status'] == 'failed' and state['fault_class'] != 'infra_fault'


def test_runtime_still_rejects_private_endpoint_with_plain_transport(tmp_path):
    with pytest.raises(ValueError):
        AgentRuntime(endpoint='http://10.0.0.5:8000/v1', model='m', transport=lambda **k: None, tools={}, directory=tmp_path)
