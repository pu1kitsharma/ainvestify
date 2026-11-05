"""Bounded offline parsing of fetched PDF bytes, without API or database access."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from delivery.isolation import private_temp_root, run_private
from delivery.storage import read_source_bytes

CONTRACT = 'fetched-public-pdf-v1'
MAX_BYTES = 3_000_000
MAX_RESULT = 256_000
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'public_pdf_worker.py'


class PublicPDFError(ValueError):
    pass


def parse_pdf_payload(body: bytes) -> dict:
    """Pure parser used only inside the worker or trusted synthetic fixtures."""
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(body)) as pdf:
            parts, size = [], 0
            truncated = len(pdf.pages) > 10
            for number, page in enumerate(pdf.pages[:10], 1):
                text = page.extract_text() or ''
                parts.append(f'[PDF page {number}] {text}')
                size += len(text)
                if size >= 24000:
                    truncated = True
                    break
            text = ' '.join(' '.join(parts).split())
            if size < 80:
                raise PublicPDFError('insufficient_text')
            title = str((pdf.metadata or {}).get('Title') or 'Public document')[:200]
            return {'title': title, 'text': text[:24000], 'truncated': truncated}
    except PublicPDFError:
        raise
    except Exception as exc:
        raise PublicPDFError('parse_failed') from exc


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PublicPDFError('invalid_result')
            result[key] = value
        return result
    def invalid(_):
        raise PublicPDFError('invalid_result')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def validate_request(request):
    if (not isinstance(request, dict) or set(request) != {'contract', 'sha256', 'size_bytes'} or
            request['contract'] != CONTRACT or not isinstance(request['sha256'], str) or
            len(request['sha256']) != 64 or any(c not in '0123456789abcdef' for c in request['sha256']) or
            type(request['size_bytes']) is not int or not 0 < request['size_bytes'] <= MAX_BYTES):
        raise PublicPDFError('invalid_request')
    return request


def validate_result(result, request):
    if (not isinstance(result, dict) or set(result) != {'contract', 'sha256', 'size_bytes', 'state', 'page'} or
            any(result[key] != request[key] for key in ('contract', 'sha256', 'size_bytes')) or
            type(result['size_bytes']) is not int or result['state'] not in ('ok', 'insufficient_text', 'parse_failed')):
        raise PublicPDFError('invalid_result')
    page = result['page']
    if result['state'] != 'ok':
        if page is not None:
            raise PublicPDFError('invalid_result')
        raise PublicPDFError(result['state'])
    if (not isinstance(page, dict) or set(page) != {'title', 'text', 'truncated'} or
            not isinstance(page['title'], str) or len(page['title']) > 200 or
            not isinstance(page['text'], str) or not 0 < len(page['text']) <= 24000 or
            type(page['truncated']) is not bool):
        raise PublicPDFError('invalid_result')
    return page


def confined_pdf_payload(body: bytes, *, timeout=20) -> dict:
    """Stage only downloaded bytes in a fresh job; never grant network/model IPC."""
    started = time.monotonic()
    if (type(body) is not bytes or not 0 < len(body) <= MAX_BYTES or
            type(timeout) not in (int, float) or not 0 < timeout <= 25):
        raise PublicPDFError('parse_failed')
    request = {'contract': CONTRACT, 'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body)}
    try:
        with tempfile.TemporaryDirectory(prefix='public-pdf-', dir=private_temp_root()) as directory:
            job = Path(directory)
            if job.resolve().is_relative_to(SCRIPT.parents[1].resolve()):
                raise PublicPDFError('parse_failed')
            for name, data in (('input.bin', body), ('request.json', json.dumps(request).encode())):
                fd = os.open(job / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise PublicPDFError('parse_failed')
            run_private([sys.executable, SCRIPT], job, timeout=remaining)
            raw = read_source_bytes(job / 'result.json')
            if len(raw) > MAX_RESULT or time.monotonic() - started >= timeout:
                raise PublicPDFError('parse_failed')
            return validate_result(decode(raw), request)
    except PublicPDFError:
        raise
    except Exception as exc:
        # No parser traceback, raw source text or environment details in API errors.
        raise PublicPDFError('parse_failed') from exc
