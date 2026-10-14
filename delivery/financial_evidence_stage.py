"""Private workbook indexing before semantic interpretation or reconciliation."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from agents.analysis.workbook_reconciliation import MAX_BYTES
from agents.research.financial_evidence_manifest import CONTRACT, FINANCIAL_SCOPE, _check_scope
from delivery.artifacts import artifact_root
from delivery.isolation import run_private
from delivery.review_integrity import _read_beneath
from delivery.storage import MAX_FILE_BYTES, scope_component
from security.identity import has_access

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/private_financial_manifest_worker.py'
READ_CODE = (SCRIPT.parents[1] / 'agents', SCRIPT.parents[1] / 'schemas.py',
             SCRIPT.parents[1] / 'workflow_schemas.py', SCRIPT.parents[1] / 'delivery')
MANIFEST = 'financial_evidence_manifest.json'
RECEIPT = 'financial_manifest_receipt.json'
ADAPTER = 'financial-evidence-stage-v1'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def _hash(content):
    return hashlib.sha256(content).hexdigest()


def _stage_root(tenant, workspace_id, job_id, document_id):
    return (Path(artifact_root()).absolute() / scope_component(tenant) /
            scope_component(workspace_id) / 'jobs' / scope_component(job_id) /
            'financial_evidence' / scope_component(document_id))


@contextmanager
def _private_directory(path):
    """Create/open each directory without following any ancestor symlink."""
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Unsafe financial stage directory')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
            os.close(directory)
            directory = child
        yield directory
    finally:
        os.close(directory)


def _read_at(directory, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_BYTES:
            raise ValueError('Unsupported financial stage file')
        body = stream.read(MAX_FILE_BYTES + 1)
    if not body or len(body) > MAX_FILE_BYTES:
        raise ValueError('Financial stage file exceeds retained size limit')
    return body


def _retain_at(directory, name, body):
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             mode=0o600, dir_fd=directory)
    except FileExistsError:
        if _read_at(directory, name) != body:
            raise ValueError('Immutable financial index input changed')
        return
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _same_directory(directory, root):
    retained, current = os.fstat(directory), os.stat(root, follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or (retained.st_dev, retained.st_ino) != (current.st_dev, current.st_ino):
        raise ValueError('Financial stage directory inode changed')


def _original_bytes(document, tenant, deal_id):
    from api.routers.deals import UPLOAD_ROOT

    upload_root = Path(UPLOAD_ROOT).absolute()
    if upload_root.resolve() != upload_root:
        raise ValueError('Unsafe private upload root')
    relative = Path(document.storage_uri).relative_to(upload_root)
    if relative.parts[:2] != (scope_component(tenant), scope_component(deal_id)) or len(relative.parts) < 4:
        raise ValueError('Original workbook is outside its tenant/deal upload subtree')
    return _read_beneath(upload_root, relative.as_posix())


def run_financial_evidence_stage(store, job, document, *, timeout=30, stage_root=None):
    """Index exact server-resolved originals inside one immutable private job."""
    from api.routers.rooms import revision_for

    def blocked(reason):
        return {'state': 'blocked', 'reason': reason, **FINANCIAL_SCOPE}

    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 120:
        raise ValueError('Private index timeout must be within the room budget')
    tenant = job['tenant_id']
    if not has_access(store.conn, job['actor_id'], tenant):
        return blocked('job_access_revoked')
    room = store.get_workspace(tenant, workspace_id=job['workspace_id'])
    original = store.get_document(tenant, document.id)
    if (room is None or room.tenant_id != tenant or room.id != job['workspace_id']
            or not room.deal_id or original is None or document.type != 'xlsx'
            or original.type != 'xlsx' or original.tenant_id != tenant or document.tenant_id != tenant
            or original.deal_id != room.deal_id or document.deal_id != room.deal_id
            or original.storage_uri != document.storage_uri):
        return blocked('workbook_outside_room_scope')
    if revision_for(store, room) != job['input_revision']:
        return blocked('input_revision_changed')
    try:
        content = _original_bytes(original, tenant, room.deal_id)
    except (OSError, ValueError):
        return blocked('workbook_unavailable_or_unsafe')
    if len(content) > MAX_BYTES:
        return blocked('workbook_exceeds_size_limit')
    if revision_for(store, room) != job['input_revision']:
        return blocked('input_revision_changed')
    binding = {'tenant_id': tenant, 'deal_id': room.deal_id, 'document_id': original.id,
               'workbook_sha256': _hash(content)}
    room_binding = {'workspace_id': job['workspace_id'], 'job_id': job['id'],
                    'input_revision': job['input_revision']}
    adapter = {'contract': ADAPTER, 'binding': binding, 'room_binding': room_binding,
               'document_record_sha256': _hash(_json(original.model_dump(mode='json')))}
    root = _stage_root(tenant, job['workspace_id'], job['id'], original.id)
    if stage_root is not None and Path(stage_root).absolute() != root:
        return blocked('financial_index_directory_unsafe')
    try:
        with _private_directory(root) as directory:
            for name, body in {'adapter_binding.json': _json(adapter),
                'request.json': _json({'workbook': 'source.xlsx', 'binding': binding}),
                'source.xlsx': content}.items():
                _retain_at(directory, name, body)
            _same_directory(directory, root)
            # The room worker loads retained sidecars on unchanged reopen.
            # Direct repeated stage calls verify the index projection.
            run_private([sys.executable, SCRIPT], root, timeout=timeout, extra_read=READ_CODE)
            _same_directory(directory, root)
            raw = _read_at(directory, MANIFEST)
            receipt_raw = _read_at(directory, RECEIPT)
            receipt = json.loads(receipt_raw)
            manifest = json.loads(raw)
            _check_scope(manifest, binding)
            if receipt != {'contract': 'private-financial-manifest-receipt-v1',
                'binding': binding, 'manifest_sha256': _hash(raw),
                'manifest_digest': manifest['manifest_digest']}:
                raise ValueError('Financial index receipt changed')
            if _read_at(directory, 'source.xlsx') != content:
                raise ValueError('Financial parser changed source bytes')
    except TimeoutError:
        return blocked('financial_evidence_index_timeout')
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return blocked('financial_evidence_index_failed')
    if not has_access(store.conn, job['actor_id'], tenant):
        return blocked('job_access_revoked')
    if revision_for(store, room) != job['input_revision']:
        return blocked('input_revision_changed')
    return {'state': 'indexed_source_only', 'contract': CONTRACT, 'binding': binding,
            'room_binding': room_binding, 'adapter_binding_sha256': _hash(_json(adapter)),
            'manifest_digest': manifest['manifest_digest'], 'manifest_sha256': _hash(raw),
            'receipt_sha256': _hash(receipt_raw), 'manifest_path': str(root / MANIFEST),
            'retained_cell_count': len(manifest['cells']), 'packet_count': len(manifest['packets']),
            'sheet_count': len(manifest['sheets']), **FINANCIAL_SCOPE}


def load_financial_evidence(record, *, tenant_id, deal_id, document_id, workbook_sha256,
                            workspace_id=None, job_id=None, input_revision=None):
    """Load retained bytes without reparsing; reject foreign/stale/unsafe indexes."""
    binding = dict(tenant_id=tenant_id, deal_id=deal_id, document_id=document_id,
                   workbook_sha256=workbook_sha256)
    if (not isinstance(record, dict) or record.get('state') != 'indexed_source_only'
            or record.get('contract') != CONTRACT or record.get('binding') != binding
            or any(record.get(name) != value for name, value in FINANCIAL_SCOPE.items())):
        raise ValueError('Financial source index is unavailable or belongs to another room')
    context = record.get('room_binding')
    if not isinstance(context, dict) or set(context) != {'workspace_id', 'job_id', 'input_revision'} or any(
            not isinstance(value, str) or not value for value in context.values()):
        raise ValueError('Financial index room binding is unavailable')
    for name, expected in (('workspace_id', workspace_id), ('job_id', job_id), ('input_revision', input_revision)):
        if expected is not None and expected != context[name]:
            raise ValueError('Financial index belongs to a different room/job revision')
    root = _stage_root(tenant_id, context['workspace_id'], context['job_id'], document_id)
    if Path(record['manifest_path']) != root / MANIFEST:
        raise ValueError('Financial source index has an unsafe retained path')
    private_root = Path(artifact_root()).absolute()
    if private_root.resolve() != private_root:
        raise ValueError('Unsafe private artifact root')
    relative = root.relative_to(private_root)

    def retained(name):
        return _read_beneath(private_root, (relative / name).as_posix())

    raw = retained(MANIFEST)
    receipt_raw = retained(RECEIPT)
    adapter_raw = retained('adapter_binding.json')
    request_raw = retained('request.json')
    adapter = json.loads(adapter_raw)
    if (_hash(raw) != record['manifest_sha256'] or _hash(receipt_raw) != record['receipt_sha256']
            or _hash(adapter_raw) != record['adapter_binding_sha256']
            or request_raw != _json({'workbook': 'source.xlsx', 'binding': binding})
            or adapter.get('contract') != ADAPTER or adapter.get('binding') != binding
            or adapter.get('room_binding') != context
            or _hash(retained('source.xlsx')) != workbook_sha256):
        raise ValueError('Retained financial index input/derivative changed')
    manifest = json.loads(raw)
    _check_scope(manifest, binding)
    if (manifest['manifest_digest'] != record['manifest_digest'] or json.loads(receipt_raw) != {
            'contract': 'private-financial-manifest-receipt-v1', 'binding': binding,
            'manifest_sha256': _hash(raw), 'manifest_digest': manifest['manifest_digest']}):
        raise ValueError('Financial source index version changed')
    return manifest
