"""Exact-byte private inspection boundary; no database, credentials or model IPC."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from delivery.isolation import private_temp_root, run_private
from delivery.storage import MAX_FILE_BYTES, read_source_bytes

CONTRACT = 'private-artifact-inspection-v1'
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'private_inspection_worker.py'
MAX_RESULT = 4 * 1024 * 1024
MAX_FILES = 16
MAX_TOTAL = 256 * 1024 * 1024
FORMATS = {'pdf', 'pptx', 'docx', 'xlsx'}
CORE_FIELDS = {'sha256', 'size_bytes', 'format', 'inspector_version', 'findings',
               'structural_status', 'calculation_status', 'visual_status', 'compatibility_status'}
OPTIONAL_FIELDS = {'calculation_settings', 'formula_count', 'sheet_count',
                   'dependency_edge_count', 'dependency_coverage', 'chart_parts',
                   'slide_parts', 'slide_count', 'page_count', 'page_geometry',
                   'pages_without_text', 'pages_without_content',
                   'pages_with_only_numeric_text', 'layout_diagnostic'}
FINDING_FIELDS = {'code', 'part', 'cell', 'name', 'error_type', 'page', 'pages',
                  'slide_count', 'pdf_page_count', 'fragment_sha256', 'text_sha256', 'count'}


def _require(condition):
    if not condition:
        raise ValueError('private_inspection_contract_invalid')


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('private_inspection_contract_invalid')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def _metadata(value, *, depth=0, count=None):
    count = [0] if count is None else count
    count[0] += 1
    _require(depth <= 12 and count[0] <= 100_000)
    if isinstance(value, dict):
        _require(len(value) <= 100)
        for key, item in value.items():
            _require(isinstance(key, str) and len(key) <= 100)
            _metadata(item, depth=depth + 1, count=count)
    elif isinstance(value, list):
        _require(len(value) <= 20_000)
        for item in value:
            _metadata(item, depth=depth + 1, count=count)
    elif isinstance(value, str):
        _require(len(value) <= 2000)
    else:
        _require(value is None or type(value) in (bool, int, float))
        if type(value) is float:
            _require(math.isfinite(value))


def _findings(items):
    _require(isinstance(items, list))
    for item in items:
        _require(isinstance(item, dict) and set(item) <= FINDING_FIELDS and
                 isinstance(item.get('code'), str) and
                 re.fullmatch('[a-z][a-z0-9_]{0,99}', item['code']) is not None)


def validate_request(request):
    _require(isinstance(request, dict) and set(request) == {'contract', 'files', 'pairs'}
             and request['contract'] == CONTRACT and isinstance(request['files'], list)
             and 0 < len(request['files']) <= MAX_FILES and isinstance(request['pairs'], list)
             and len(request['pairs']) <= MAX_FILES)
    seen = {}
    for index, row in enumerate(request['files']):
        _require(isinstance(row, dict) and set(row) == {'id', 'filename', 'format', 'sha256', 'size_bytes'})
        _require(isinstance(row['id'], str) and re.fullmatch('[A-Za-z0-9_-]{1,100}', row['id'])
                 and row['id'] not in seen and row['filename'] == f'input-{index:03d}.bin'
                 and row['format'] in FORMATS and type(row['size_bytes']) is int
                 and 0 < row['size_bytes'] <= MAX_FILE_BYTES and isinstance(row['sha256'], str)
                 and re.fullmatch('[a-f0-9]{64}', row['sha256']))
        seen[row['id']] = row
    _require(sum(row['size_bytes'] for row in seen.values()) <= MAX_TOTAL)
    pairs = set()
    for pair in request['pairs']:
        _require(isinstance(pair, dict) and set(pair) == {'editable', 'pdf'})
        key = (pair['editable'], pair['pdf'])
        _require(key not in pairs and all(value in seen for value in key) and
                 seen[key[0]]['format'] in {'pptx', 'docx'} and seen[key[1]]['format'] == 'pdf')
        pairs.add(key)
    return request


def validate_result(result, request):
    _require(isinstance(result, dict) and set(result) == {'contract', 'input_digest', 'files', 'pairs'}
             and result['contract'] == CONTRACT and result['input_digest'] == _digest(request)
             and isinstance(result['files'], dict) and isinstance(result['pairs'], list))
    _metadata(result)
    expected = {row['id']: row for row in request['files']}
    _require(set(result['files']) == set(expected) and len(result['pairs']) == len(request['pairs']))
    for key, report in result['files'].items():
        source = expected[key]
        _require(isinstance(report, dict) and CORE_FIELDS <= set(report) <= CORE_FIELDS | OPTIONAL_FIELDS)
        _require(type(report['size_bytes']) is int and
                 all(report[field] == source[field] for field in ('sha256', 'size_bytes', 'format'))
                 and report['inspector_version'] == 'ooxml-pdf-v2'
                 and report['structural_status'] in {'pass', 'fail'}
                 and all(report[field] == 'not_run' for field in
                         ('calculation_status', 'visual_status', 'compatibility_status')))
        _findings(report['findings'])
        _require((report['structural_status'] == 'fail') == bool(report['findings']))
    for pair, offered in zip(result['pairs'], request['pairs']):
        _require(isinstance(pair, dict) and set(pair) == {'editable', 'pdf', 'report'}
                 and pair['editable'] == offered['editable'] and pair['pdf'] == offered['pdf'])
        report = pair['report']
        _require(isinstance(report, dict) and set(report) == {'editable_sha256', 'pdf_sha256',
                 'pair_status', 'editable_text_status', 'content_layout_status', 'findings',
                 'alternate_extraction_verified_fragments'})
        _require(report['editable_sha256'] == expected[pair['editable']]['sha256']
                 and report['pdf_sha256'] == expected[pair['pdf']]['sha256']
                 and report['pair_status'] in {'pass', 'fail'}
                 and report['editable_text_status'] in {'pass', 'fail', 'not_run'}
                 and report['content_layout_status'] == 'not_run'
                 and type(report['alternate_extraction_verified_fragments']) is int
                 and 0 <= report['alternate_extraction_verified_fragments'] <= 20_000)
        _findings(report['findings'])
        _require((report['pair_status'] == 'fail') == bool(report['findings']))
        _require(report['pair_status'] != 'pass' or report['editable_text_status'] == 'pass')
    return result


def inspect_artifacts(contents, pairs=(), *, timeout=110):
    """Inspect exact supplied bytes in a fresh bounded networkless worker.

    contents maps opaque artifact IDs to (format, bytes). Only those files cross
    the boundary. No tenant IDs, source paths, DB, model capability or credentials
    are supplied. Formula/value payloads never return to the coordinator.
    """
    _require(type(timeout) in (int, float) and 0 < timeout <= 120)
    started = time.monotonic()
    if not contents:
        _require(not pairs)
        return {}, []
    files = [{'id': key, 'filename': f'input-{index:03d}.bin', 'format': fmt,
              'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content)}
             for index, (key, (fmt, content)) in enumerate(contents.items())]
    request = validate_request({'contract': CONTRACT, 'files': files,
                                'pairs': [{'editable': left, 'pdf': right} for left, right in pairs]})
    with tempfile.TemporaryDirectory(prefix='private-inspection-', dir=private_temp_root()) as directory:
        job = Path(directory)
        for row in files:
            fd = os.open(job / row['filename'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(contents[row['id']][1])
        (job / 'request.json').write_bytes(_encoded(request))
        os.chmod(job / 'request.json', 0o600)
        try:
            remaining = timeout - (time.monotonic() - started)
            _require(remaining > 0)
            run_private([sys.executable, SCRIPT], job, timeout=remaining)
        except (RuntimeError, TimeoutError, OSError) as exc:
            raise ValueError('private_artifact_inspection_unavailable') from exc
        try:
            raw = read_source_bytes(job / 'result.json')
            _require(len(raw) <= MAX_RESULT and time.monotonic() - started < timeout)
            result = validate_result(_decode(raw), request)
        except Exception as exc:
            raise ValueError('private_inspection_contract_invalid') from exc
        return result['files'], result['pairs']
