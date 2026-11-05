"""Single-input parser entry point; invoked exclusively through run_private."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    # Resource limits supplement the parent's 45-second process-group timeout.
    # Do this before importing the document parsers or opening untrusted bytes.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    # -I suppresses cwd/user/PYTHONPATH startup imports. Add immutable application
    # code explicitly after startup, never a writable upload/job directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agents.core.ingestion_agent import ingest_document
    from delivery.ingestion import CONTRACT, _write_new
    from delivery.storage import read_source_bytes

    root = Path.cwd()
    raw_request = read_source_bytes(root / 'request.json')
    request = json.loads(raw_request)
    if request.get('contract') != CONTRACT:
        raise ValueError('Unsupported private upload ingestion contract')
    source = Path(request['source_path'])
    raw = read_source_bytes(source)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != request['source_sha256'] or len(raw) != request['source_size']:
        raise ValueError('Private upload source changed before parsing')
    document = ingest_document(str(source), request['tenant_id'], request['deal_id'])
    document.id = request['document_id']
    for index, block in enumerate(document.blocks, 1):
        block.document_id = document.id
        block.id = request['block_id_prefix'] + '_' + str(index)
    if hashlib.sha256(read_source_bytes(source)).hexdigest() != digest:
        raise ValueError('Private upload source changed during parsing')
    _write_new(root / 'result.json', {'contract': CONTRACT,
        'request_sha256': hashlib.sha256(raw_request).hexdigest(),
        'source_sha256': digest, 'document': document.model_dump(mode='json')})


if __name__ == '__main__':
    main()
