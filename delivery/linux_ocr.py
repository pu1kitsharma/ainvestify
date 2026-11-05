"""Confined, replayable Linux OCR batches. Transcription is never financial review."""
from __future__ import annotations

import csv
import hashlib
from io import StringIO
import json
import math
import os
from pathlib import Path
import platform
import struct
import sys
import time
import zlib

from delivery.isolation import run_private
from delivery.storage import read_source_bytes

CONTRACT = 'private-tesseract-document-ocr-v1'
ENGINE = 'Tesseract5-eng-no-dictionary-correction'
PROJECT = Path(__file__).resolve().parents[1]
WORKER = PROJECT / 'scripts/private_tesseract_worker.py'
BINARY = Path('/usr/bin/tesseract')
LANGUAGE = Path('/usr/share/tesseract-ocr/5/tessdata/eng.traineddata')
MAX_BATCH_PAGES = 8
MAX_PAGES = 120
MAX_PIXELS = 12_000_000
MAX_SOURCE_BYTES = 32 * 1024 * 1024


def sha(body):
    return hashlib.sha256(body).hexdigest()


def _canonical(path, *, directory=False):
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path or (not path.is_dir() if directory else not path.is_file()):
        raise ValueError('OCR path must be canonical and unlinked')
    return path


def _write(path, value):
    body = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(body)


def _load(path):
    raw = read_source_bytes(_canonical(path))
    if len(raw) > 32_000_000:
        raise ValueError('OCR JSON exceeds supported bound')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate OCR JSON property')
            result[key] = value
        return result
    def finite(value):
        raise ValueError('Nonfinite OCR JSON value')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=finite)
    if not isinstance(value, dict):
        raise ValueError('OCR object required')
    return raw, value


def runtime_pins():
    if platform.system() != 'Linux':
        raise RuntimeError('Linux OCR runtime required')
    import importlib.metadata
    import PIL._imaging
    import pypdfium2_raw
    paths = {'worker': WORKER, 'projection':Path(__file__).resolve(), 'binary': BINARY,
             'english_language': LANGUAGE, 'limit_wrapper':Path('/usr/bin/prlimit'),
             'pdfium':Path(pypdfium2_raw.__file__).parent/'libpdfium.so',
             'pillow_native':Path(PIL._imaging.__file__), 'python':Path(sys.executable).resolve()}
    result = {name: {'path': str(_canonical(path)), 'sha256': sha(read_source_bytes(path))}
              for name, path in paths.items()}
    result['package_versions'] = {name:importlib.metadata.version(name) for name in ('pypdfium2','Pillow')}
    return result


def png_dimensions(body):
    """Bounded IHDR validation without running an image codec in the parent."""
    if (len(body)<33 or body[:8]!=b'\x89PNG\r\n\x1a\n' or body[8:16]!=b'\x00\x00\x00\rIHDR'
            or zlib.crc32(body[12:29])!=struct.unpack('>I',body[29:33])[0]):
        raise ValueError('Invalid OCR PNG header')
    width,height,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',body[16:29])
    if (not 1<=width or not 1<=height or width*height>MAX_PIXELS or depth not in {1,2,4,8,16}
            or color not in {0,2,3,4,6} or compression!=0 or filtering!=0 or interlace not in {0,1}):
        raise ValueError('Unsupported OCR PNG geometry')
    return width,height


def parse_tsv(raw, width, height):
    """Project literal word observations into ordered lines without correcting words."""
    if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0
            or width * height > MAX_PIXELS or len(raw) > 8_000_000):
        raise ValueError('OCR raster/TSV bounds exceeded')
    reader = csv.DictReader(StringIO(raw.decode('utf-8')), delimiter='\t', quoting=csv.QUOTE_NONE)
    expected = ['level','page_num','block_num','par_num','line_num','word_num',
                'left','top','width','height','conf','text']
    if reader.fieldnames != expected:
        raise ValueError('Unsupported OCR TSV header')
    lines, words_seen, page_seen = {}, set(), False
    for index, row in enumerate(reader):
        if index >= 50000 or None in row or any(value is None for value in row.values()):
            raise ValueError('OCR TSV structure exceeds bounds')
        level = int(row['level'])
        hierarchy = tuple(int(row[name]) for name in ('page_num','block_num','par_num','line_num','word_num'))
        if (not 1<=level<=5 or hierarchy[0]!=1 or any(value<0 for value in hierarchy)
                or any(hierarchy[position]<=0 for position in range(1,level))
                or any(hierarchy[position]!=0 for position in range(level,5))):
            raise ValueError('Invalid OCR TSV page/hierarchy')
        x, y, w, h = (int(row[name]) for name in ('left','top','width','height'))
        if min(x,y) < 0 or min(w,h) <= 0 or x+w > width or y+h > height:
            raise ValueError('OCR coordinates escape raster')
        if level==1:
            if page_seen or (x,y,w,h)!=(0,0,width,height):
                raise ValueError('OCR TSV page geometry changed')
            page_seen=True
        if level!=5:
            continue
        if hierarchy in words_seen or not page_seen:
            raise ValueError('Duplicate/unscoped OCR TSV word')
        words_seen.add(hierarchy)
        if not row['text'].strip():
            continue
        confidence = float(row['conf'])
        if not math.isfinite(confidence) or not 0 <= confidence <= 100:
            raise ValueError('Invalid OCR confidence')
        key = hierarchy[:4]
        lines.setdefault(key, []).append((row['text'], confidence / 100, x,y,w,h))
    if not page_seen or len(lines) > 5000:
        raise ValueError('OCR observation count exceeds bound')
    observations = []
    for words in lines.values():
        text = ' '.join(word[0] for word in words)
        if len(text) > 8000:
            raise ValueError('OCR line exceeds bound')
        x0, y0 = min(word[2] for word in words), min(word[3] for word in words)
        x1, y1 = max(word[2]+word[4] for word in words), max(word[3]+word[5] for word in words)
        observations.append({'text': text, 'confidence': min(word[1] for word in words),
                             'bbox':[x0/width, 1-y1/height, (x1-x0)/width, (y1-y0)/height]})
    return observations


def checked_request(request):
    expected = {'contract','source_path','source_sha256','page_numbers','width','runtime_pins'}
    if set(request) != expected or request['contract'] != CONTRACT:
        raise ValueError('Unsupported Linux OCR request')
    pages, width = request['page_numbers'], request['width']
    if (not isinstance(pages, list) or not 1 <= len(pages) <= MAX_BATCH_PAGES
            or any(type(page) is not int or not 1 <= page <= MAX_PAGES for page in pages)
            or sorted(set(pages)) != pages or type(width) is not int or not 600 <= width <= 2400):
        raise ValueError('Explicit OCR page batch bounds invalid')
    if request['runtime_pins'] != runtime_pins():
        raise ValueError('OCR runtime provenance changed')
    source = _canonical(request['source_path'])
    body = read_source_bytes(source)
    if len(body) > MAX_SOURCE_BYTES or sha(body) != request['source_sha256']:
        raise ValueError('OCR original source bytes changed')
    return body


def replay_pdf_batch(job_directory, *, _deadline=None):
    """Read-only replay of exact raw TSV; never invokes OCR, rendering or a model."""
    job = _canonical(job_directory, directory=True)
    if job.stat().st_mode & 0o077:
        raise ValueError('Private OCR job permissions required')
    request_raw, request = _load(job / 'request.json')
    checked_request(request)
    result_raw, result = _load(job / 'result.json')
    _, receipt = _load(job / 'receipt.json')
    if (receipt.get('state') != 'transcribed_unreviewed'
            or receipt.get('network_access') != 'denied'
            or receipt.get('financial_validation') != 'not_established'
            or receipt.get('request_sha256') != sha(request_raw)
            or receipt.get('result_sha256') != sha(result_raw)
            or result.get('contract') != CONTRACT
            or result.get('request_sha256') != sha(request_raw)
            or result.get('source_sha256') != request['source_sha256']
            or type(result.get('total_pages')) is not int
            or not 1 <= result['total_pages'] <= MAX_PAGES
            or max(request['page_numbers']) > result['total_pages']
            or not isinstance(result.get('pages'), list)
            or [page.get('page') for page in result['pages']] != request['page_numbers']):
        raise ValueError('OCR raw receipt or complete batch inventory changed')
    projected = []
    for row in result['pages']:
        if _deadline is not None and time.monotonic()>=_deadline:
            raise TimeoutError('OCR cumulative parent budget exhausted')
        number = row['page']
        required = {'page','width_pixels','height_pixels','width_points','height_points','image_sha256','tsv_sha256'}
        if set(row) != required:
            raise ValueError('Unexpected OCR page shape')
        image = read_source_bytes(_canonical(job / ('page_%04d.png' % number)))
        raw = read_source_bytes(_canonical(job / ('page_%04d.tsv' % number)))
        if sha(image) != row['image_sha256'] or sha(raw) != row['tsv_sha256']:
            raise ValueError('OCR original raster/TSV binding changed')
        dimensions=png_dimensions(image)
        if (type(row['width_pixels']) is not int or type(row['height_pixels']) is not int
                or dimensions!=(row['width_pixels'],row['height_pixels'])
                or abs(row['width_pixels']-request['width']) > 1
                or any(type(row[key]) not in (float,int) or not math.isfinite(row[key]) or row[key] <= 0
                       for key in ('width_points','height_points'))):
            raise ValueError('OCR raster geometry invalid')
        if abs(row['height_pixels']-math.ceil(row['height_points']*request['width']/row['width_points']))>1:
            raise ValueError('OCR raster aspect ratio changed')
        observations = parse_tsv(raw, row['width_pixels'], row['height_pixels'])
        projected.append({**row, 'source_sha256':request['source_sha256'], 'engine':ENGINE,
            'language_correction':False, 'coordinate_system':'normalized-bottom-left',
            'observations':observations})
    return {'contract':CONTRACT, 'source_sha256':request['source_sha256'],
            'total_pages':result['total_pages'], 'pages':projected,
            'source_transcription_status':'local_ocr_proposed_unreviewed',
            'financial_validation':'not_established', 'network_access':'denied'}


def run_pdf_batch(source, job_directory, page_numbers, *, width=1800, timeout=110):
    """One explicit <=8-page batch, fresh isolated process, <=110 seconds total."""
    deadline=time.monotonic()+timeout
    source = _canonical(source)
    job = _canonical(job_directory, directory=True)
    if job.stat().st_mode & 0o077 or not 0 < timeout <= 110:
        raise ValueError('Private OCR job/budget required')
    request = {'contract':CONTRACT, 'source_path':str(source),
               'source_sha256':sha(read_source_bytes(source)), 'page_numbers':list(page_numbers),
               'width':width, 'runtime_pins':runtime_pins()}
    checked_request(request)
    frozen = job / 'request.json'
    if frozen.exists():
        _, previous = _load(frozen)
        if previous != request:
            raise ValueError('Frozen OCR input changed')
        return replay_pdf_batch(job,_deadline=deadline)
    if list(job.iterdir()):
        raise ValueError('Fresh private OCR batch directory required')
    request_hash = _write(frozen, request)
    receipt = {'contract':CONTRACT, 'request_sha256':request_hash, 'network_access':'denied',
               'financial_validation':'not_established', 'state':'started'}
    try:
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise TimeoutError('OCR preparation exhausted cumulative budget')
        run_private([sys.executable, '-I', '-B', WORKER], job, timeout=remaining,
                    extra_read_literals=(source,))
        receipt.update(state='transcribed_unreviewed', result_sha256=sha(read_source_bytes(job / 'result.json')))
    except Exception as error:
        receipt.update(state='failed', error_type=type(error).__name__)
        raise
    finally:
        _write(job / 'receipt.json', receipt)
    return replay_pdf_batch(job,_deadline=deadline)


def combine_pdf_batches(job_directories):
    """A complete source requires every page, exact bindings and no duplicate batches."""
    batches = [replay_pdf_batch(path) for path in job_directories]
    if not batches:
        raise ValueError('OCR batches required')
    first = batches[0]
    pages = []
    for batch in batches:
        if (batch['source_sha256'], batch['total_pages']) != (first['source_sha256'], first['total_pages']):
            raise ValueError('Cannot combine OCR for different originals')
        pages.extend(batch['pages'])
    pages.sort(key=lambda page: page['page'])
    if [page['page'] for page in pages] != list(range(1, first['total_pages']+1)):
        raise ValueError('Complete OCR page coverage required; duplicate/missing pages')
    return {**first, 'pages':pages, 'page_coverage_status':'complete',
            'batch_count':len(batches), 'financial_validation':'not_established'}
