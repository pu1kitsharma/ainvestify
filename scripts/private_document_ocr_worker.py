"""Network-denied source transcription; run only inside a private job directory."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from delivery.document_ocr import CONTRACT, rasterize_pdf


def main(root):
    root = Path(root).resolve()
    request = json.loads((root / 'request.json').read_text())
    source = root / 'source.pdf'
    if (request.get('contract') != CONTRACT or source.is_symlink()
            or not source.is_file() or source.stat().st_size > 40_000_000):
        raise ValueError('Unsupported private OCR source')
    content = source.read_bytes()
    source_sha = hashlib.sha256(content).hexdigest()
    if source_sha != request.get('source_sha256'):
        raise ValueError('Private OCR source bytes changed')
    if (root / 'page_images.json').exists():
        raise ValueError('Private raster result already exists; replay immutable receipt')
    started = time.monotonic()
    images = rasterize_pdf(content, root, width=request.get('width', 2400),
                           max_pages=request.get('max_pages', 120))
    payload = {'contract': CONTRACT, 'source_sha256': source_sha, 'images': images,
               'elapsed_seconds': round(time.monotonic() - started, 3)}
    descriptor = os.open(root / 'page_images.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as output:json.dump(payload, output, ensure_ascii=False)
    print(json.dumps({'page_count': len(images), 'elapsed_seconds': payload['elapsed_seconds']}))


if __name__ == '__main__':
    main(sys.argv[1])
