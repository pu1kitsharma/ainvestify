"""Private classifier snapshots, real namespace/UDS transport and strict replay."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys

import pytest

from delivery import classification as stage, model_ipc
from tests.api.test_authentication import secured, sign_in
from schemas import Deal, DealStatus
from store import Store

native = pytest.mark.skipif(platform.system() != 'Linux', reason='Native private classifier qualification requires Linux')


def response(content=None, **changes):
    value = {'model': stage.MODEL, 'done': True, 'done_reason': 'stop',
        'message': {'role': 'assistant', 'content': json.dumps(content or {
            'action': 'source_leads', 'reasoning': 'Synthetic intent only',
            'sector_keyword': 'synthetic', 'location_filter': None})},
        'prompt_eval_count': 400, 'eval_count': 30, 'total_duration': 123,
        'load_duration': 12, 'prompt_eval_duration': 34, 'eval_duration': 56}
    value.update(changes)
    return value


@pytest.fixture
def private_fixture(tmp_path, monkeypatch):
    root = tmp_path/'artifacts'; monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT', str(root))
    monkeypatch.setenv('PRIVATE_MODEL_IPC', model_ipc.CONTRACT)
    class Reply(BytesIO):
        status = 200
        def getheader(self, name): return 'application/json' if name == 'Content-Type' else None
    class Connection:
        requests = []
        payload = response()
        sock = None
        def __init__(self, host, port, *, timeout):
            assert (host, port) == ('127.0.0.1', 11434) and 0 < timeout <= 120
        def connect(self): pass
        def request(self, method, path, *, body, headers):
            assert method == 'POST' and path == '/api/chat'
            self.requests.append(json.loads(body))
        def getresponse(self): return Reply(json.dumps(self.payload).encode())
        def close(self): pass
    relay = model_ipc.model_relay
    monkeypatch.setattr(model_ipc, 'model_relay', lambda **kwargs: relay(**kwargs, _connection_factory=Connection))
    return root, Connection


@pytest.mark.parametrize('change', [dict(model='other-model'), dict(done=False),
    dict(done_reason='length'), dict(prompt_eval_count=4098), dict(prompt_eval_count=0),
    dict(eval_count=True), dict(eval_count=513)])
def test_strict_projection_rejects_identity_incomplete_overflow_and_invalid_usage(change):
    with pytest.raises(ValueError): stage._project('prompt', 'synthetic', None, response(**change))


@pytest.mark.parametrize('decision', [
    {'action': 'invented', 'reasoning': 'reject'},
    {'action': 'source_leads', 'reasoning': 'reject', 'extra': 'not allowed'},
    {'action': 'source_leads', 'reasoning': ''},
    {'action': 'source_leads', 'reasoning': 'reject', 'sector_keyword': 123},
])
def test_strict_decision_has_no_action_or_schema_fallback(decision):
    with pytest.raises(ValueError): stage._project('prompt', 'synthetic', None, response(decision))


def test_directive_strict_replay_rejects_invalid_action_and_target():
    deal = Deal(tenant_id='tenant', name='Synthetic', status=DealStatus.REVIEWED)
    for value in ({'action': 'invented', 'reasoning': 'reject'},
                  {'action': 'rerun_extraction', 'reasoning': 'reject', 'target_field': 'other_private_field'}):
        with pytest.raises(ValueError): stage._project('directive', 'synthetic', deal, response(value))


@native
def test_real_worker_retains_exact_raw_response_and_usage_without_dispatch(secured, private_fixture):
    client, database, users = secured; root, connection = private_fixture
    sign_in(client, users[0])
    result = client.post('/api/prompt/classify', json={'prompt': 'find synthetic companies'})
    assert result.status_code == 200, result.text
    assert result.json()['action'] == 'source_leads'
    request_path = next(root.rglob('request.json')); request = json.loads(request_path.read_bytes())
    assert connection.requests == [request['model_request']]
    assert request['tenant_id'] == users[0][1] and request['actor_id'] == users[0][0]
    raw = json.loads((request_path.parent/'raw-response.json').read_bytes())
    assert raw['message']['content'] == connection.payload['message']['content']
    usage = json.loads((request_path.parent/'usage.json').read_bytes())
    assert usage['calls'] == usage['requests'] == 1 and usage['max_seconds'] == 110
    assert json.loads((request_path.parent/'receipt.json').read_bytes())['state'] == 'validated'
    with Store(database) as store:
        assert store.list_deals(users[0][1]) == []


@native
@pytest.mark.parametrize('invalid', ['wrong-model', 'length', 'decision'])
def test_invalid_model_output_is_retained_but_never_becomes_a_classification(secured, private_fixture, invalid):
    client, _, users = secured; root, connection = private_fixture; sign_in(client, users[0])
    if invalid == 'wrong-model': connection.payload = response(model='other-model')
    elif invalid == 'length': connection.payload = response(done_reason='length')
    else: connection.payload = response({'action': 'invented', 'reasoning': 'reject'})
    result = client.post('/api/prompt/classify', json={'prompt': 'synthetic input'})
    assert result.status_code == 503
    raw = json.loads(next(root.rglob('raw-response.json')).read_bytes())
    assert raw['message']['content'] == connection.payload['message']['content']
    assert json.loads(next(root.rglob('receipt.json')).read_bytes())['state'] == 'failed'
    assert not list(root.rglob('decision.json'))


@native
def test_directive_preview_is_scoped_and_read_only(secured, private_fixture):
    client, database, users = secured; root, connection = private_fixture
    with Store(database) as store:
        deal = Deal(tenant_id=users[0][1], name='Synthetic', status=DealStatus.REVIEWED)
        store.save_deal(deal)
    sign_in(client, users[1])
    assert client.post(f'/api/deals/{deal.id}/directive/preview', json={'directive': 'prepare a synthetic teaser'}).status_code == 404
    assert connection.requests == []
    sign_in(client, users[0]); connection.payload = response({'action': 'compile_teaser', 'reasoning': 'Synthetic preview', 'target_field': None})
    result = client.post(f'/api/deals/{deal.id}/directive/preview', json={'directive': 'prepare a synthetic teaser'})
    assert result.status_code == 200 and result.json()['action'] == 'compile_teaser'
    with Store(database) as store:
        assert store.get_deal(users[0][1], deal.id).model_dump() == deal.model_dump()
    before = len(connection.requests)
    assert client.post(f'/api/deals/{deal.id}/directive/preview', json={'directive': 'continue'}).status_code == 200
    assert len(connection.requests) == before


@native
def test_revocation_of_exact_session_blocks_result_even_when_another_session_is_active(secured, private_fixture, monkeypatch):
    from security.identity import create_session, revoke_session
    client, database, users = secured; root, _ = private_fixture; sign_in(client, users[0])
    with Store(database) as store: create_session(store.conn, users[0][0], users[0][1])
    real_run = stage.run_private
    def revoke(*args, **kwargs):
        value = real_run(*args, **kwargs)
        with Store(database) as store: revoke_session(store.conn, users[0][2])
        return value
    monkeypatch.setattr(stage, 'run_private', revoke)
    assert client.post('/api/prompt/classify', json={'prompt': 'synthetic input'}).status_code == 503
    assert list(root.rglob('raw-response.json')) and not list(root.rglob('decision.json'))


@native
def test_classifier_cannot_read_other_files_secrets_host_network_or_shadow_startup(secured, private_fixture, tmp_path, monkeypatch):
    client, _, users = secured; _, _connection = private_fixture; sign_in(client, users[0])
    sibling = tmp_path/'other-room.txt'; sibling.write_text('synthetic unrelated private bytes')
    monkeypatch.setenv('SYNTHETIC_CLASSIFIER_SECRET', 'not-in-child')
    real_run = stage.run_private
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1)
        code = '''import os,socket,sys\nfrom pathlib import Path\nassert not os.environ.get('SYNTHETIC_CLASSIFIER_SECRET')\nassert [name for _,name in socket.if_nameindex()]==['lo']\ntry:Path(sys.argv[1]).read_bytes()\nexcept OSError:pass\nelse:raise AssertionError('unrelated private file readable')\ns=socket.socket();s.settimeout(.2)\ntry:s.connect(('127.0.0.1',int(sys.argv[2])))\nexcept OSError:pass\nelse:raise AssertionError('host network reachable')\nfinally:s.close()\n'''
        def probe(command, job, **options):
            assert options['local_model'] is True and command[1:3] == ['-I', '-B']
            (job/'json.py').write_text('raise RuntimeError("job shadow import")')
            (job/'sitecustomize.py').write_text('raise RuntimeError("job startup import")')
            real_run([sys.executable, '-I', '-B', '-c', code, sibling, str(listener.getsockname()[1])], job, **options)
            return real_run(command, job, **options)
        monkeypatch.setattr(stage, 'run_private', probe)
        result = client.post('/api/prompt/classify', json={'prompt': 'synthetic input'})
    assert result.status_code == 200, result.text


@native
@pytest.mark.parametrize('change', ['request', 'usage', 'deal-state'])
def test_changed_snapshot_or_usage_or_deal_state_is_rejected(secured, private_fixture, monkeypatch, change):
    client, database, users = secured; root, connection = private_fixture; sign_in(client, users[0])
    with Store(database) as store:
        deal = Deal(tenant_id=users[0][1], name='Synthetic', status=DealStatus.REVIEWED)
        store.save_deal(deal)
    connection.payload = response({'action': 'compile_teaser', 'reasoning': 'Synthetic preview'})
    real_run = stage.run_private
    def modify(command, job, **options):
        value = real_run(command, job, **options)
        if change == 'request':
            path = job/'request.json'; path.write_bytes(path.read_bytes()+b' ')
        elif change == 'usage':
            usage = json.loads((job/'usage.json').read_bytes()); usage['requests'] = True
            (job/'usage.json').write_text(json.dumps(usage))
            outcome = json.loads((job/'outcome.json').read_bytes())
            outcome['usage_sha256'] = hashlib.sha256((job/'usage.json').read_bytes()).hexdigest()
            (job/'outcome.json').write_text(json.dumps(outcome))
        else:
            with Store(database) as store:
                current = store.get_deal(users[0][1], deal.id); current.status = DealStatus.COMPILED
                store.save_deal(current)
        return value
    monkeypatch.setattr(stage, 'run_private', modify)
    result = client.post(f'/api/deals/{deal.id}/directive/preview', json={'directive': 'prepare a synthetic teaser'})
    assert result.status_code == 503 and not list(root.rglob('decision.json'))


@native
def test_anonymous_and_oversize_text_never_start_model_work(secured, private_fixture):
    client, _, users = secured; root, connection = private_fixture
    assert client.post('/api/prompt/classify', json={'prompt': 'synthetic'}).status_code == 401
    sign_in(client, users[0])
    assert client.post('/api/prompt/classify', json={'prompt': 'x'*4097}).status_code == 503
    assert connection.requests == [] and not list(root.rglob('request.json'))
