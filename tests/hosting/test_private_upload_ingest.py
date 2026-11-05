"""Real upload parser capabilities and two-user persistence; synthetic bytes only."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys

import pytest
from openpyxl import Workbook

from delivery import ingestion, isolation
from delivery.storage import scope_component
from tests.api.test_authentication import secured, sign_in
from store import Store

native = pytest.mark.skipif(platform.system() != 'Linux', reason='Native Linux private upload boundary qualification')
pytestmark = pytest.mark.skipif(not hasattr(os, 'O_NOFOLLOW'), reason='Private storage requires native POSIX no-follow descriptors')


def workbook_bytes():
    workbook = Workbook()
    workbook.active.title = 'Synthetic'
    workbook.active.append(['Metric', 'Value'])
    workbook.active.append(['Historical fixture', 120])
    workbook.active['B3'] = '=B2+1'
    workbook.create_sheet('Hidden').sheet_state = 'hidden'
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def pdf_bytes():
    from reportlab.pdfgen.canvas import Canvas
    output = BytesIO(); canvas = Canvas(output)
    canvas.drawString(72, 720, 'Synthetic private source fixture only')
    canvas.save()
    return output.getvalue()


@pytest.fixture
def private_root(tmp_path, monkeypatch):
    root = tmp_path / 'artifacts'
    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT', str(root))
    return root


def fixture_result(job):
    request_bytes = (job / 'request.json').read_bytes()
    request = json.loads(request_bytes)
    document = {'id': request['document_id'], 'tenant_id': request['tenant_id'],
        'deal_id': request['deal_id'], 'filename': Path(request['source_path']).name,
        'storage_uri': request['source_path'], 'type': 'xlsx', 'blocks': [], 'workbook_inventory': {}}
    return {'contract': ingestion.CONTRACT, 'request_sha256': hashlib.sha256(request_bytes).hexdigest(),
            'source_sha256': request['source_sha256'], 'document': document}


@pytest.mark.parametrize('change', ['tenant', 'document_id', 'path', 'request_hash', 'source_hash', 'request_bytes', 'source_bytes', 'extra_field', 'block_id', 'extra_block_field'])
def test_changed_result_is_rejected_and_original_and_failure_evidence_retained(tmp_path, monkeypatch, private_root, change):
    source = tmp_path / 'fixture.xlsx'
    source.write_bytes(workbook_bytes())
    original = source.read_bytes()
    def changed_worker(command, job, **options):
        value = fixture_result(job)
        if change == 'tenant': value['document']['tenant_id'] = 'other-tenant'
        if change == 'document_id': value['document']['id'] = 'existing-document'
        if change == 'path': value['document']['storage_uri'] = '/other/private/file'
        if change == 'request_hash': value['request_sha256'] = '0' * 64
        if change == 'source_hash': value['source_sha256'] = '0' * 64
        if change == 'request_bytes': (job / 'request.json').write_text('{}')
        if change == 'source_bytes': source.write_bytes(b'synthetic changed source')
        if change == 'extra_field': value['document']['unexpected'] = 'reject'
        if change in {'block_id', 'extra_block_field'}:
            request = json.loads((job / 'request.json').read_bytes())
            block = {'id': request['block_id_prefix'] + '_1', 'document_id': request['document_id'],
                     'page': 1, 'block_type': 'text', 'coordinates': {}, 'content': 'synthetic'}
            if change == 'block_id': block['id'] = 'other-document-block'
            else: block['unexpected'] = 'reject'
            value['document']['blocks'] = [block]
        (job / 'result.json').write_text(json.dumps(value))
    monkeypatch.setattr(ingestion, 'run_private', changed_worker)
    with pytest.raises(ValueError): ingestion.ingest_upload(source, 'tenant', 'deal')
    assert source.read_bytes() == (b'synthetic changed source' if change == 'source_bytes' else original)
    receipt = json.loads(next(private_root.rglob('receipt.json')).read_text())
    assert receipt['state'] == 'failed' and receipt['error_type'] == 'ValueError'


def test_timeout_and_busy_parser_preserve_original_without_unsandboxed_fallback(tmp_path, monkeypatch, private_root):
    source = tmp_path / 'fixture.xlsx'; source.write_bytes(workbook_bytes())
    original = source.read_bytes()
    monkeypatch.setattr(ingestion, 'run_private', lambda *a, **k: (_ for _ in ()).throw(TimeoutError('synthetic timeout')))
    with pytest.raises(TimeoutError): ingestion.ingest_upload(source, 'tenant', 'deal')
    assert ingestion._PARSER_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match='busy'):
            ingestion.ingest_upload(source, 'tenant', 'deal')
    finally: ingestion._PARSER_SLOT.release()
    assert len(list(private_root.rglob('receipt.json'))) == 1
    assert source.read_bytes() == original


def test_capacity_bound_covers_parent_result_validation(tmp_path, monkeypatch, private_root):
    source = tmp_path / 'fixture.xlsx'; source.write_bytes(workbook_bytes())
    def worker(command, job, **options):
        (job / 'result.json').write_text(json.dumps(fixture_result(job)))
    monkeypatch.setattr(ingestion, 'run_private', worker)
    real_load = ingestion._load_result
    def checked(raw):
        assert not ingestion._PARSER_SLOT.acquire(blocking=False)
        return real_load(raw)
    monkeypatch.setattr(ingestion, '_load_result', checked)
    ingestion.ingest_upload(source, 'tenant', 'deal')
    assert ingestion._PARSER_SLOT.acquire(blocking=False)
    ingestion._PARSER_SLOT.release()


@pytest.mark.parametrize('properties,document', [('"contract":1,"contract":2', '{}'),
    ('"contract":1', '{"value":NaN}'), ('"contract":1', '{"value":1e999}'),
    ('"contract":1', '[' * 66 + '0' + ']' * 66)])
def test_result_parser_rejects_duplicate_nonfinite_and_overdeep_json(properties, document):
    raw = ('{' + properties + ',"request_sha256":"request","source_sha256":"source","document":' + document + '}').encode()
    with pytest.raises(ValueError): ingestion._load_result(raw)


@native
def test_hostile_parser_has_exact_readonly_input_no_sibling_network_secret_or_inherited_fd(tmp_path, monkeypatch, private_root):
    source = tmp_path / 'fixture.xlsx'; source.write_bytes(workbook_bytes())
    sibling = tmp_path / 'other-room.txt'; sibling.write_text('ungranted synthetic private canary')
    api_secret = tmp_path / 'api.env'; api_secret.write_text('synthetic API secret')
    monkeypatch.setenv('SYNTHETIC_API_SECRET', 'must-not-be-in-child')
    real_run = isolation.run_private
    with socket.socket() as listener, api_secret.open('rb') as inherited:
        listener.bind(('127.0.0.1', 0)); listener.listen(1)
        os.set_inheritable(inherited.fileno(), True)
        code = r'''
import os,sys,json,hashlib,socket
from pathlib import Path
job=Path.cwd();raw=(job/'request.json').read_bytes();r=json.loads(raw);source=Path(r['source_path'])
assert hashlib.sha256(source.read_bytes()).hexdigest()==r['source_sha256']
for path in map(Path,sys.argv[1:3]):
 try:path.read_bytes()
 except OSError:pass
 else:raise AssertionError('Unrelated private bytes readable')
try:source.write_bytes(b'forbidden')
except OSError:pass
else:raise AssertionError('Original upload writable')
assert 'SYNTHETIC_API_SECRET' not in os.environ
assert [name for _,name in socket.if_nameindex()]==['lo']
for fd in Path('/proc/self/fd').iterdir():
 try:link=os.readlink(fd)
 except OSError:continue
 assert sys.argv[2] not in link,'API file descriptor inherited'
s=socket.socket();s.settimeout(.2)
try:s.connect(('127.0.0.1',int(sys.argv[3])))
except OSError:pass
else:raise AssertionError('Host network reachable')
finally:s.close()
doc={'id':r['document_id'],'tenant_id':r['tenant_id'],'deal_id':r['deal_id'],'filename':source.name,'type':'xlsx','storage_uri':str(source),'blocks':[],'workbook_inventory':{}}
(job/'result.json').write_text(json.dumps({'contract':r['contract'],'request_sha256':hashlib.sha256(raw).hexdigest(),'source_sha256':r['source_sha256'],'document':doc}))
'''
        def hostile(command, job, **options):
            assert command[1:3] == ['-I', '-B']
            assert options['extra_read_literals'] == (source,)
            assert options['timeout'] == 45 and not options.get('local_model')
            assert sibling not in options['extra_read'] and source.parent not in options['extra_read']
            # Probe hostile code under the exact production capabilities.
            return real_run([sys.executable, '-I', '-B', '-c', code, sibling, api_secret,
                             str(listener.getsockname()[1])], job, **options)
        monkeypatch.setattr(ingestion, 'run_private', hostile)
        result = ingestion.ingest_upload(source, 'tenant', 'deal')
    assert result.tenant_id == 'tenant' and source.read_bytes() != b'forbidden'
    assert sibling.read_text() == 'ungranted synthetic private canary'


@native
@pytest.mark.parametrize('fmt', ['xlsx', 'pdf'])
def test_two_authenticated_users_upload_same_name_with_real_isolated_parser_and_cross_scope_denial(secured, tmp_path, monkeypatch, private_root, fmt):
    import api.routers.deals as deals_router
    client, database, users = secured
    monkeypatch.setattr(deals_router, 'UPLOAD_ROOT', tmp_path / 'uploads')
    original = workbook_bytes() if fmt == 'xlsx' else pdf_bytes(); records = []
    for user in users:
        sign_in(client, user)
        created = client.post('/api/rooms', json={'name': 'Synthetic private room',
            'website': 'https://synthetic.example', 'terms_summary': 'Synthetic test engagement'}).json()
        with Store(database) as store:
            deal_id = store.get_workspace(user[1], workspace_id=created['workspace_id']).deal_id
        response = client.post(f'/api/deals/{deal_id}/documents', files={'file': ('same-name.' + fmt, original)})
        assert response.status_code == 200, response.text
        documents = client.get(f'/api/deals/{deal_id}/source-documents').json()
        assert len(documents) == 1
        document = documents[0]; path = Path(document['storage_uri'])
        assert path.read_bytes() == original and scope_component(user[1]) in str(path)
        assert document['type'] == fmt and document['blocks']
        if fmt == 'xlsx':
            assert len(document['blocks']) == 2 and document['blocks'][1]['coordinates']['sheet'] == 'Synthetic'
            assert document['workbook_inventory']['formula_count'] == 1
            assert any(sheet['state'] == 'hidden' for sheet in document['workbook_inventory']['sheets'])
        else:
            assert document['blocks'][0]['page'] == 1
            assert 'Synthetic private source fixture only' in document['blocks'][0]['content']
        records.append((created['workspace_id'], deal_id, document))
    assert records[0][2]['storage_uri'] != records[1][2]['storage_uri']
    assert client.get(f'/api/deals/{records[0][1]}/source-documents').status_code == 404
    assert client.get(f'/api/rooms/{records[0][0]}').status_code == 404
    sign_in(client, users[0])
    assert client.get(f'/api/deals/{records[1][1]}/source-documents').status_code == 404
    assert client.get(f'/api/rooms/{records[1][0]}').status_code == 404
    assert len(list(private_root.rglob('receipt.json'))) == 2


@native
def test_revocation_during_parser_execution_prevents_document_persistence(secured, tmp_path, monkeypatch, private_root):
    import api.routers.deals as deals_router
    client, database, users = secured; sign_in(client, users[0])
    monkeypatch.setattr(deals_router, 'UPLOAD_ROOT', tmp_path / 'uploads')
    created = client.post('/api/rooms', json={'name': 'Synthetic revocation room',
        'website': 'https://synthetic.example', 'terms_summary': 'Synthetic test engagement'}).json()
    with Store(database) as store:
        deal_id = store.get_workspace(users[0][1], workspace_id=created['workspace_id']).deal_id
    real_run = ingestion.run_private
    def revoke(command, job, **options):
        (job / 'json.py').write_text('raise RuntimeError("job import shadowing")')
        (job / 'sitecustomize.py').write_text('raise RuntimeError("job startup shadowing")')
        result = real_run(command, job, **options)
        with Store(database) as store:
            store.conn.execute('UPDATE auth_memberships SET active=0 WHERE user_id=?', (users[0][0],))
            store.conn.commit()
        return result
    monkeypatch.setattr(ingestion, 'run_private', revoke)
    response = client.post(f'/api/deals/{deal_id}/documents', files={'file': ('retained.xlsx', workbook_bytes())})
    assert response.status_code == 422 and 'retained' in response.json()['detail']
    with Store(database) as store:
        assert store.get_documents_for_deal(users[0][1], deal_id) == []
    assert len(list((tmp_path / 'uploads').rglob('retained.xlsx'))) == 1
