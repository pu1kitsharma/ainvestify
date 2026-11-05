"""Parse one immutable upload behind the private OS boundary; retain failures."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from threading import BoundedSemaphore

from delivery.artifacts import artifact_root
from delivery.isolation import run_private
from delivery.storage import read_source_bytes, scoped_directory, scope_component
from schemas import DocBlock, Document, new_id

CONTRACT = 'private-upload-ingest-v1'
MAX_SECONDS = 45
PROJECT = Path(__file__).resolve().parents[1]
_PARSER_SLOT = BoundedSemaphore(1)  # Current deployment runs one API process.


def _write_new(path, value):
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(payload).hexdigest()


def _load_result(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate private ingestion result property')
            value[key] = item
        return value
    def finite(value):
        raise ValueError('Non-finite private ingestion result value')
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=finite)
    pending, count = [(result, 0)], 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 64 or count > 500000:
            raise ValueError('Private ingestion result exceeds its structure limit')
        if type(value) is float and not math.isfinite(value):
            raise ValueError('Non-finite private ingestion result value')
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
    if type(result) is not dict or set(result) != {'contract', 'request_sha256', 'source_sha256', 'document'}:
        raise ValueError('Unexpected private ingestion result shape')
    return result


def ingest_upload(source, tenant_id, deal_id):
    # Cover input reads, child parsing and parent JSON/schema validation with
    # one capacity bound. Concurrent uploads retain their original bytes and
    # fail closed without starting another memory-heavy parser.
    if not _PARSER_SLOT.acquire(blocking=False):
        raise RuntimeError('Private upload parser is busy; original bytes retained')
    try:
        return _ingest_upload(source, tenant_id, deal_id)
    finally:
        _PARSER_SLOT.release()


def _ingest_upload(source, tenant_id, deal_id):
    """Grant a checked file, immutable code and one writable private job only.

    No database, upload directory, other room, model socket, API environment
    or host network is passed to the parser. Originals and diagnostic output
    survive rejection. The caller remains responsible for trusted persistence.
    """
    source = Path(source).absolute()
    if source.is_symlink() or source.resolve() != source:
        raise ValueError('Upload input must be canonical and unlinked')
    if source.suffix.lower() not in {'.pdf', '.xlsx', '.xlsm'}:
        raise ValueError('Unsupported upload input format')
    original = read_source_bytes(source)
    source_hash = hashlib.sha256(original).hexdigest()
    root = artifact_root()
    identifier = new_id('ingest')
    with scoped_directory(root, tenant_id, deal_id, create=True) as descriptor:
        os.mkdir(identifier, mode=0o700, dir_fd=descriptor)
    job = root / scope_component(tenant_id) / scope_component(deal_id) / identifier
    request = {'contract': CONTRACT, 'source_path': str(source), 'source_sha256': source_hash,
               'source_size': len(original), 'tenant_id': tenant_id, 'deal_id': deal_id,
               'document_id': new_id('doc'), 'block_id_prefix': new_id('blk')}
    request_hash = _write_new(job / 'request.json', request)
    receipt = {'contract': CONTRACT, 'request_sha256': request_hash,
               'source_sha256': source_hash, 'state': 'started'}
    try:
        run_private([__import__('sys').executable, '-I', '-B', PROJECT / 'scripts/private_upload_ingest_worker.py'],
                    job, timeout=MAX_SECONDS, extra_read=(PROJECT / 'agents', PROJECT / 'schemas.py'),
                    extra_read_literals=(source,))
        raw = read_source_bytes(job / 'result.json')
        result = _load_result(raw)
        if (result.get('contract') != CONTRACT or result.get('request_sha256') != request_hash
                or result.get('source_sha256') != source_hash
                or hashlib.sha256(read_source_bytes(job / 'request.json')).hexdigest() != request_hash
                or hashlib.sha256(read_source_bytes(source)).hexdigest() != source_hash):
            raise ValueError('Private ingestion source or request binding changed')
        value = result['document']
        if (type(value) is not dict or set(value) != set(Document.model_fields)
                or any(type(value[key]) is not str for key in
                       ('id', 'tenant_id', 'deal_id', 'filename', 'type', 'storage_uri'))
                or type(value.get('workbook_inventory')) is not dict
                or type(value.get('blocks')) is not list or len(value['blocks']) > 50000
                or any(type(block) is not dict or set(block) != set(DocBlock.model_fields)
                       or type(block['page']) is not int or block['page'] <= 0
                       or type(block['coordinates']) is not dict for block in value['blocks'])):
            raise ValueError('Unexpected private ingestion document shape')
        document = Document.model_validate(value)
        expected_type = 'pdf' if source.suffix.lower() == '.pdf' else 'xlsx'
        if (document.id != request['document_id']
                or document.tenant_id != tenant_id or document.deal_id != deal_id
                or document.filename != source.name or document.type != expected_type
                or document.storage_uri != str(source)
                or any(block.document_id != document.id
                       or block.id != request['block_id_prefix'] + '_' + str(index)
                       for index, block in enumerate(document.blocks, 1))):
            raise ValueError('Private ingestion document identity changed')
        receipt.update(state='parsed', result_sha256=hashlib.sha256(raw).hexdigest(),
                       document_id=document.id, block_count=len(document.blocks))
        return document
    except Exception as exc:
        receipt.update(state='failed', error_type=type(exc).__name__)
        raise
    finally:
        _write_new(job / 'receipt.json', receipt)
