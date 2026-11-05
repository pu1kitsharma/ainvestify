"""Synthetic response replay, authenticated persistence and real private UDS worker."""
from contextlib import contextmanager
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys

import pytest

from delivery import extraction, isolation, model_ipc
from schemas import AuditEvent, BlockType, Deal, DealStatus, DocBlock, Document, ExtractionResult
from store import Store
from tests.api.test_authentication import secured, sign_in

pytestmark = pytest.mark.skipif(not hasattr(os, 'O_NOFOLLOW'), reason='Native POSIX private file boundary required')
native = pytest.mark.skipif(platform.system() != 'Linux', reason='Native Linux UDS/bubblewrap qualification')


def source(tenant='tenant', deal='deal', identifier='document'):
    return Document(id=identifier, tenant_id=tenant, deal_id=deal, filename='synthetic.txt.pdf',
        type='pdf', storage_uri='/ungranted/original.pdf', blocks=[
            DocBlock(id=identifier+'_main', document_id=identifier, page=1, block_type=BlockType.TEXT,
                     coordinates={}, content='Synthetic USD ARR 120, prior ARR 100, MRR 10, burn 5, cash 30, runway 6, headcount 4; funding 20.'),
            DocBlock(id=identifier+'_table', document_id=identifier, page=2, block_type=BlockType.TABLE,
                     coordinates={}, content=[['Holder', 'Percent'], ['Synthetic founders', '80'], ['Synthetic others', '20']])])


def response(document, model='phi4-mini'):
    main, table = document.blocks
    value = lambda number: {'value': number, 'source_block_id': main.id, 'source_page': 1}
    content = {key: value(number) for key, number in {
        'arr': 120, 'arr_prior_year': 100, 'mrr': 10, 'growth_rate_yoy': 20,
        'burn_monthly': 5, 'cash_on_hand': 30, 'runway_months': 6, 'headcount': 4}.items()}
    content.update(cap_table=[{'holder': 'Synthetic founders', 'pct': 80}],
        cap_table_source_block_id=table.id,
        funding_history=[{'round_name': 'Synthetic round', 'amount': 20, 'source_block_id': main.id, 'source_page': 1}])
    return {'model': model, 'done': True, 'done_reason': 'stop', 'prompt_eval_count': 120,
            'eval_count': 200, 'message': {'role': 'assistant', 'content': json.dumps(content)}}


@pytest.fixture
def private_root(tmp_path, monkeypatch):
    root = tmp_path / 'private-artifacts'
    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT', str(root))
    return root


def fake_worker(command, job, **options):
    assert command[1:3] == ['-I', '-B']
    assert options['local_model'] is True and 0 < options['timeout'] <= 120
    assert options['extra_read'] == (extraction.PROJECT / 'agents', extraction.PROJECT / 'schemas.py')
    assert not options.get('extra_read_literals')
    raw = (job / 'request.json').read_bytes(); request = json.loads(raw)
    document = Document.model_validate(request['document'])
    call = json.loads((job / 'model-request.json').read_bytes())
    answer = response(document, request['model'])
    response_hash = extraction.write_json(job / 'raw-response.json', answer)
    usage_hash = extraction.write_json(job / 'usage.json',
        {'max_seconds': request['max_seconds'], 'max_calls': 6, 'max_requests': 6,
         'calls': 1, 'requests': 1, 'elapsed_seconds': .01})
    projected = extraction.validate_response(answer, request['model'], document, request['extracted_at'], call)
    extraction.write_json(job / 'result.json', {'contract': extraction.CONTRACT,
        'request_sha256': hashlib.sha256(raw).hexdigest(), 'document_sha256': request['document_sha256'],
        'model_request_sha256': request['model_request_sha256'], 'response_sha256': response_hash,
        'usage_sha256': usage_hash, 'result': projected.model_dump(mode='json')})


@pytest.mark.parametrize('change', ['tenant', 'document', 'value', 'approved', 'reviewer', 'response_hash',
                                  'usage_hash', 'request_bytes', 'model_request_bytes'])
def test_tampered_result_cannot_replace_replayed_model_response(private_root, monkeypatch, change):
    def changed(command, job, **options):
        fake_worker(command, job, **options)
        path = job / 'result.json'; value = json.loads(path.read_text())
        if change == 'tenant': value['result']['tenant_id'] = 'other-room'
        if change == 'document': value['result']['document_id'] = 'other-document'
        if change == 'value': value['result']['arr']['value'] = 999999
        if change == 'approved': value['result']['arr']['status'] = 'approved'
        if change == 'reviewer': value['result']['arr']['reviewer'] = 'appointed-by-model'
        if change in {'response_hash', 'usage_hash'}: value[change.replace('_hash', '_sha256')] = '0' * 64
        if change == 'request_bytes': (job / 'request.json').write_text('{}')
        if change == 'model_request_bytes': (job / 'model-request.json').write_text('{}')
        path.write_text(json.dumps(value))
    monkeypatch.setattr(extraction, 'run_private', changed)
    with pytest.raises(ValueError): extraction.extract_private(source(), 'phi4-mini')
    receipt = json.loads(next(private_root.rglob('receipt.json')).read_text())
    assert receipt['state'] == 'failed'
    assert next(private_root.rglob('raw-response.json')).is_file()


@pytest.mark.parametrize('change', ['page', 'missing_usage', 'truncated_context', 'ambiguous_cutoff',
                                  'zero_prompt', 'zero_output', 'output_limit', 'nonfinite', 'duplicate'])
def test_response_page_schema_and_token_receipts_fail_closed(change):
    document = source(); answer = response(document); call = extraction.model_request(document, 'phi4-mini', None)
    content = json.loads(answer['message']['content'])
    if change == 'page': content['arr']['source_page'] = 2
    if change == 'missing_usage': answer.pop('eval_count')
    if change == 'truncated_context': answer['prompt_eval_count'] = call['options']['num_ctx']
    if change == 'ambiguous_cutoff': answer['prompt_eval_count'] = call['options']['num_ctx'] // 2 + 2
    if change == 'zero_prompt': answer['prompt_eval_count'] = 0
    if change == 'zero_output': answer['eval_count'] = 0
    if change == 'output_limit': answer['eval_count'] = 1025
    answer['message']['content'] = json.dumps(content)
    if change == 'nonfinite': answer['message']['content'] = answer['message']['content'].replace('120,', 'NaN,', 1)
    if change == 'duplicate': answer['message']['content'] = answer['message']['content'].replace('"value": 120', '"value": 120, "value": 999', 1)
    with pytest.raises(ValueError): extraction.validate_response(answer, 'phi4-mini', document, 'synthetic-time', call)


def test_capacity_limit_covers_parent_replay_and_timeout_has_no_direct_fallback(private_root, monkeypatch):
    monkeypatch.setattr(extraction, 'run_private', fake_worker)
    original = extraction.validate_response
    def checked(*args):
        assert not extraction._EXTRACTION_SLOT.acquire(blocking=False)
        return original(*args)
    monkeypatch.setattr(extraction, 'validate_response', checked)
    result = extraction.extract_private(source(), 'phi4-mini')
    assert result.arr.value == 120 and result.arr.status.value == 'proposed'
    monkeypatch.setattr(extraction, 'run_private', lambda *a, **k: (_ for _ in ()).throw(TimeoutError('private synthetic error')))
    with pytest.raises(TimeoutError): extraction.extract_private(source(), 'phi4-mini')
    assert extraction._EXTRACTION_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match='busy'): extraction.extract_private(source(), 'phi4-mini')
    finally: extraction._EXTRACTION_SLOT.release()
    assert len(list(private_root.rglob('receipt.json'))) == 2


@pytest.mark.parametrize('field,value', [('max_seconds', 121), ('max_calls', True), ('max_requests', True)])
def test_usage_budget_must_match_frozen_parent_request(private_root, monkeypatch, field, value):
    def forged(command, job, **options):
        fake_worker(command, job, **options)
        usage = json.loads((job / 'usage.json').read_text()); usage[field] = value
        raw = extraction.encoded(usage); (job / 'usage.json').write_bytes(raw)
        result = json.loads((job / 'result.json').read_text())
        result['usage_sha256'] = hashlib.sha256(raw).hexdigest()
        (job / 'result.json').write_text(json.dumps(result))
    monkeypatch.setattr(extraction, 'run_private', forged)
    with pytest.raises(ValueError, match='budget'): extraction.extract_private(source(), 'phi4-mini')


def seed(database, user):
    with Store(database) as store:
        deal = Deal(id='deal_'+user[0], tenant_id=user[1], name='Synthetic source only')
        document = source(user[1], deal.id, 'doc_'+user[0]); deal.document_ids = [document.id]
        store.save_deal(deal); store.save_document(document)
    return deal, document


def test_source_session_result_status_and_human_audit_commit_atomically(secured):
    _, database, users = secured; user = users[0]
    deal, document = seed(database, user)
    result = extraction.validate_response(response(document), 'phi4-mini', document, 'synthetic-time',
                                          extraction.model_request(document, 'phi4-mini', None))
    from security.identity import resolve_session
    with Store(database) as store:
        store.authenticated_identity = resolve_session(store.conn, user[2])
        event = AuditEvent(tenant_id=user[1], deal_id=deal.id, actor='forged-reviewer',
                           action='reject', target_id='arr')
        with pytest.raises(ValueError, match='audit identity'):
            extraction.persist_private_result(store, result, document, None,
                                               status=DealStatus.EXTRACTED, audit_events=[event])
        assert store.get_extraction_result(user[1], deal.id) is None
        assert store.get_deal(user[1], deal.id).status == DealStatus.NEW
        assert store.get_audit_log(user[1], deal.id) == []
        event.actor = user[0]
        extraction.persist_private_result(store, result, document, None,
                                           status=DealStatus.EXTRACTED, audit_events=[event])
        assert store.get_extraction_result(user[1], deal.id).arr.value == 120
        assert store.get_deal(user[1], deal.id).status == DealStatus.EXTRACTED
        assert store.get_audit_log(user[1], deal.id)[0].actor == user[0]


def test_authenticated_extract_and_all_three_review_retries_are_private_and_cross_scope_denied(secured, monkeypatch, private_root):
    client, database, users = secured
    monkeypatch.setattr(extraction, 'run_private', fake_worker)
    deals = [seed(database, user)[0] for user in users]
    for index, user in enumerate(users):
        sign_in(client, user)
        assert client.post(f'/api/deals/{deals[1-index].id}/extract', json={}).status_code == 404
        result = client.post(f'/api/deals/{deals[index].id}/extract', json={})
        assert result.status_code == 200, result.text
        assert result.json()['tenant_id'] == user[1] and result.json()['arr']['status'] == 'proposed'
        for path, key in [('fields/arr', 'arr'), ('cap-table', 'cap_table'), ('funding-history', 'funding_history')]:
            result = client.post(f'/api/deals/{deals[index].id}/review/{path}',
                                 json={'decision': 'reject', 'note': 'Synthetic reviewed correction request'})
            assert result.status_code == 200, result.text
            count = result.json()['extraction_result'][key]['retry_count'] if key == 'arr' else result.json()['extraction_result'][key+'_retry_count']
            assert count == 1
    assert len(list(private_root.rglob('receipt.json'))) == 8


@pytest.mark.parametrize('change', ['session', 'membership', 'disabled_user', 'source', 'concurrent_result'])
def test_revocation_and_stale_source_cannot_persist_worker_output(secured, monkeypatch, private_root, change):
    client, database, users = secured; user = users[0]; sign_in(client, user)
    deal, document = seed(database, user)
    def revoked(command, job, **options):
        fake_worker(command, job, **options)
        with Store(database) as store:
            if change == 'session': store.conn.execute('UPDATE auth_sessions SET revoked=1 WHERE user_id=?', (user[0],))
            if change == 'membership': store.conn.execute('UPDATE auth_memberships SET active=0 WHERE user_id=?', (user[0],))
            if change == 'disabled_user': store.conn.execute('UPDATE auth_users SET disabled=1 WHERE id=?', (user[0],))
            if change == 'source':
                document.blocks[0].content = 'Changed synthetic source'
                store.save_document(document)
            if change == 'concurrent_result':
                store.save_extraction_result(ExtractionResult(tenant_id=user[1], deal_id=deal.id, document_id=document.id))
            store.conn.commit()
    monkeypatch.setattr(extraction, 'run_private', revoked)
    result = client.post(f'/api/deals/{deal.id}/extract', json={})
    assert result.status_code == (403 if change in {'session', 'membership', 'disabled_user'} else 409), result.text
    with Store(database) as store:
        saved = store.get_extraction_result(user[1], deal.id)
        assert saved is None if change != 'concurrent_result' else saved.arr.value is None


@pytest.mark.parametrize('retry', [False, True])
def test_api_worker_errors_never_echo_private_response_text(secured, monkeypatch, private_root, retry):
    client, database, users = secured; user = users[0]; sign_in(client, user)
    deal, document = seed(database, user)
    if retry:
        prior = extraction.validate_response(response(document), 'phi4-mini', document, 'synthetic-time',
                                             extraction.model_request(document, 'phi4-mini', None))
        with Store(database) as store: store.save_extraction_result(prior)
    def failing(*args, **kwargs):
        raise ValueError('private-response-canary-that-must-not-reach-http')
    monkeypatch.setattr(extraction, 'run_private', failing)
    path = f'/api/deals/{deal.id}/review/fields/arr' if retry else f'/api/deals/{deal.id}/extract'
    result = client.post(path, json={'decision': 'reject'} if retry else {})
    assert result.status_code == 422
    assert 'private-response-canary' not in result.text
    assert json.loads(next(private_root.rglob('receipt.json')).read_text())['state'] == 'failed'


class Reply(BytesIO):
    status = 200
    def getheader(self, name):
        return 'application/json' if name == 'Content-Type' else None


@pytest.fixture
def fake_relay(monkeypatch):
    calls = []; terminal = {'done_reason': 'stop'}
    class Connection:
        sock = None
        def __init__(self, host, port, *, timeout):
            assert (host, port) == ('127.0.0.1', 11434)
        def connect(self): pass
        def request(self, method, path, *, body, headers):
            assert (method, path) == ('POST', '/api/chat')
            calls.append(json.loads(body))
        def getresponse(self):
            # IDs come from the immutable synthetic request, not an API override.
            call = calls[-1]; prompt = call['messages'][0]['content']
            import re
            identifiers = re.findall(r'\[BLOCK ([^ ]+) \| page', prompt)
            document = source(identifier=identifiers[0].removesuffix('_main'))
            value = response(document, call['model']); value.update(terminal)
            return Reply(json.dumps(value).encode())
        def close(self): pass
    original = model_ipc.model_relay
    @contextmanager
    def relay(*, timeout):
        with original(timeout=timeout, _connection_factory=Connection) as path:
            yield path
    monkeypatch.setattr(model_ipc, 'model_relay', relay)
    monkeypatch.setenv('PRIVATE_MODEL_IPC', 'unix-ollama-v1')
    return calls, terminal


@native
def test_real_bwrap_worker_uses_one_fake_uds_call_and_retains_replayable_usage(private_root, fake_relay):
    calls, _ = fake_relay
    result = extraction.extract_private(source(), 'phi4-mini', 'Synthetic correction only')
    assert result.arr.value == 120 and result.arr.extraction_method == 'llm:phi4-mini'
    assert len(calls) == 1 and calls[0]['stream'] is False
    frozen = json.loads(next(private_root.rglob('model-request.json')).read_text())
    assert calls[0] == frozen
    usage = json.loads(next(private_root.rglob('usage.json')).read_text())
    assert usage['calls'] == usage['requests'] == 1 and usage['max_calls'] == usage['max_requests'] == 6


@native
def test_invalid_terminal_raw_response_survives_real_worker_rejection(private_root, fake_relay):
    calls, terminal = fake_relay; terminal['done_reason'] = 'length'
    with pytest.raises(RuntimeError, match='private_worker_failed'):
        extraction.extract_private(source(), 'phi4-mini')
    assert len(calls) == 1
    assert json.loads(next(private_root.rglob('raw-response.json')).read_text())['done_reason'] == 'length'
    assert json.loads(next(private_root.rglob('usage.json')).read_text())['requests'] == 1
    assert json.loads(next(private_root.rglob('receipt.json')).read_text())['state'] == 'failed'


@native
def test_worker_cannot_read_sources_siblings_secrets_fd_or_host_network(tmp_path, monkeypatch, private_root, fake_relay):
    document = source()
    original = tmp_path / 'original.pdf'; original.write_bytes(b'synthetic immutable original')
    document.storage_uri = str(original)
    sibling = tmp_path / 'other-tenant.txt'; sibling.write_bytes(b'ungranted tenant fixture')
    secret = tmp_path / 'api.env'; secret.write_bytes(b'synthetic-api-secret')
    monkeypatch.setenv('SYNTHETIC_API_SECRET', 'not-in-worker')
    real_run = isolation.run_private
    with socket.socket() as listener, secret.open('rb') as inherited:
        listener.bind(('127.0.0.1', 0)); listener.listen(1)
        os.set_inheritable(inherited.fileno(), True)
        code = r'''
import os,sys,socket,runpy
from pathlib import Path
job=Path.cwd()
for path in map(Path,sys.argv[2:5]):
 try:path.read_bytes()
 except OSError:pass
 else:raise AssertionError('Unrelated private source readable')
try:Path(sys.argv[2]).write_bytes(b'forbidden')
except OSError:pass
# /tmp is a private tmpfs. A same-path shadow can be created there; the
# parent independently verifies the actual host original is unchanged.
assert 'SYNTHETIC_API_SECRET' not in os.environ
assert [name for _,name in socket.if_nameindex()]==['lo']
for descriptor in Path('/proc/self/fd').iterdir():
 try:target=os.readlink(descriptor)
 except OSError:continue
 assert sys.argv[4] not in target,'API descriptor inherited'
peer=socket.socket();peer.settimeout(.1)
try:peer.connect(('127.0.0.1',int(sys.argv[5])))
except OSError:pass
else:raise AssertionError('Host TCP network reachable')
finally:peer.close()
runpy.run_path(sys.argv[1],run_name='__main__')
'''
        def hostile(command, job, **options):
            (job / 'json.py').write_text('raise RuntimeError("job import shadow")')
            (job / 'sitecustomize.py').write_text('raise RuntimeError("job startup shadow")')
            return real_run([sys.executable, '-I', '-B', '-c', code, command[-1], original,
                             sibling, secret, str(listener.getsockname()[1])], job, **options)
        monkeypatch.setattr(extraction, 'run_private', hostile)
        result = extraction.extract_private(document, 'phi4-mini')
    assert result.arr.value == 120
    assert original.read_bytes() == b'synthetic immutable original'
    assert sibling.read_bytes() == b'ungranted tenant fixture'
