"""Retain a complete workbook index in an isolated private job directory."""
import hashlib
import json
import os
from pathlib import Path

from agents.research.financial_evidence_manifest import build_financial_manifest
from delivery.storage import MAX_FILE_BYTES, read_source_bytes


def _retain(path, body):
    if len(body) > MAX_FILE_BYTES:
        raise ValueError('Financial manifest exceeds retained size limit')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if read_source_bytes(path) != body:
            raise ValueError('Immutable financial index changed')
        return
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def run(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Private financial job directory is unsafe')
    request = json.loads(read_source_bytes(root / 'request.json'))
    if not isinstance(request, dict) or set(request) != {'workbook', 'binding'} or request['workbook'] != 'source.xlsx':
        raise ValueError('Exact private workbook request required')
    content = read_source_bytes(root / request['workbook'])
    binding = request['binding']
    if not isinstance(binding, dict) or set(binding) != {'tenant_id', 'deal_id', 'document_id', 'workbook_sha256'}:
        raise ValueError('Exact private workbook binding required')
    if hashlib.sha256(content).hexdigest() != binding['workbook_sha256']:
        raise ValueError('Original workbook changed')
    manifest = build_financial_manifest(content, **{key: binding[key]
        for key in ('tenant_id', 'deal_id', 'document_id')})
    if manifest['binding'] != binding:
        raise ValueError('Private workbook binding changed')
    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    _retain(root / 'financial_evidence_manifest.json', body)
    receipt = {'contract': 'private-financial-manifest-receipt-v1', 'binding': binding,
               'manifest_sha256': hashlib.sha256(body).hexdigest(),
               'manifest_digest': manifest['manifest_digest']}
    _retain(root / 'financial_manifest_receipt.json', json.dumps(receipt, ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    if read_source_bytes(root / request['workbook']) != content:
        raise ValueError('Financial parser changed original bytes')


if __name__ == '__main__':
    run(Path.cwd())
