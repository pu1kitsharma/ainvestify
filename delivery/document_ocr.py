"""Bounded local raster transcription, independently of local LLM authorship.

Original figures remain observations. OCR confidence does not establish financial
accuracy, table cell semantics, review, or investor approval.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from delivery.isolation import run_private
from delivery.storage import read_source_bytes


CONTRACT = 'private-vision-ocr-v1'
PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / 'scripts/private_vision_ocr.swift'
SWIFTC = Path('/Library/Developer/CommandLineTools/usr/bin/swiftc')
SDK = Path('/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk')
MAX_IMAGES = 120
MAX_PIXELS = 12_000_000
BUILD_ROOT = PROJECT / 'runtime_qualification/local_tools/private_vision_ocr'


def _write_new(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True)


def build_local_ocr_worker(*, timeout=80):
    """Compile immutable generic code before any private input enters a worker.

    This compiler receives no documents, text, paths or images from private
    rooms. Recognition itself always runs behind the network-denied boundary.
    """
    if platform.system() != 'Darwin' or not SWIFTC.is_file():
        raise RuntimeError('Private local OCR runtime unavailable')
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    root = BUILD_ROOT / (source_sha + '-explicit-sdk-v1')
    binary, receipt_path = root / 'private-vision-ocr', root / 'build_receipt.json'
    if receipt_path.is_file():
        return checked_local_ocr_worker()
    if root.exists():
        raise ValueError('Interrupted OCR compiler build requires review')
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'TMPDIR': str(root),
           'LANG': 'en_US.UTF-8'}
    result = subprocess.run([str(SWIFTC), '-sdk', str(SDK), '-module-cache-path', str(root / 'module-cache'),
        str(SOURCE), '-o', str(binary)], env=env, cwd=root, capture_output=True, timeout=timeout)
    _write_new(root / 'compiler_result.json', {'returncode': result.returncode,
        'stdout': result.stdout.decode('utf-8', errors='replace'),
        'stderr': result.stderr.decode('utf-8', errors='replace'), 'private_inputs': False})
    if result.returncode or not binary.is_file():
        raise RuntimeError('Generic local OCR compiler failed')
    os.chmod(binary, 0o700)
    _write_new(receipt_path, {'contract': 'private-vision-ocr-build-v1',
        'source_sha256': source_sha, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'compiler': str(SWIFTC), 'sdk': str(SDK), 'private_inputs': False})
    return checked_local_ocr_worker()


def checked_local_ocr_worker():
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    root = BUILD_ROOT / (source_sha + '-explicit-sdk-v1')
    binary, receipt_path = root / 'private-vision-ocr', root / 'build_receipt.json'
    if binary.is_symlink() or receipt_path.is_symlink() or not binary.is_file() or not receipt_path.is_file():
        raise RuntimeError('Build the generic local OCR worker before private processing')
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get('contract') != 'private-vision-ocr-build-v1'
            or receipt.get('source_sha256') != source_sha
            or receipt.get('private_inputs') is not False or receipt.get('sdk') != str(SDK)
            or receipt.get('binary_sha256') != hashlib.sha256(binary.read_bytes()).hexdigest()):
        raise ValueError('Local OCR executable provenance changed')
    return binary


def checked_ocr_result(request, result):
    """Validate exact image inventory, normalised geometry and unchanged bytes."""
    if (request.get('contract') != CONTRACT or result.get('contract') != CONTRACT
            or result.get('language_correction') is not False
            or result.get('coordinate_system') != 'normalized-bottom-left'
            or result.get('engine') != 'AppleVision-VNRecognizeTextRequest'):
        raise ValueError('Unsupported local OCR receipt')
    inputs, outputs = request.get('images', []), result.get('images', [])
    if not inputs or len(inputs) > MAX_IMAGES or len(inputs) != len(outputs):
        raise ValueError('Local OCR image inventory is incomplete')
    if len({row['id'] for row in inputs}) != len(inputs):
        raise ValueError('Local OCR image IDs are ambiguous')
    for source, output in zip(inputs, outputs):
        path = Path(source['path'])
        if (path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']
                or output.get('id') != source['id']
                or output.get('image_sha256') != source['sha256']):
            raise ValueError('Local OCR image binding changed')
        observations = output.get('observations')
        if not isinstance(observations, list) or len(observations) > 5000:
            raise ValueError('Local OCR observation inventory unsupported')
        for row in observations:
            if not isinstance(row.get('text'), str) or len(row['text']) > 8000:
                raise ValueError('Local OCR text exceeds supported bound')
            confidence, bbox = row.get('confidence'), row.get('bbox')
            if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                    or not math.isfinite(confidence) or not 0 <= confidence <= 1
                    or not isinstance(bbox, list) or len(bbox) != 4
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) or not 0 <= v <= 1 for v in bbox)
                    or bbox[0] + bbox[2] > 1.000001 or bbox[1] + bbox[3] > 1.000001):
                raise ValueError('Local OCR confidence/geometry is invalid')
    return result


def recognize_images(images, job_directory, *, timeout=110, languages=('en-US',)):
    """Compile/run Apple Vision behind a network-denied, job-only write boundary.

    Inputs are private raster paths. Reopening replays exact recorded OCR rather
    than silently recognising changed images. No source words are sent to an API.
    """
    job = Path(job_directory).absolute()
    if (platform.system() != 'Darwin' or not SWIFTC.is_file()
            or not job.is_dir() or job.is_symlink() or job.resolve() != job
            or job.stat().st_mode & 0o077):
        raise RuntimeError('Private local OCR runtime unavailable')
    if not languages or len(languages) > 4 or any(not isinstance(v, str) for v in languages):
        raise ValueError('Local OCR languages unsupported')
    request = {'contract': CONTRACT, 'images': [], 'languages': list(languages),
               'worker_source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest()}
    for item in images:
        path = Path(item['path'])
        if (path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(job)):
            raise ValueError('OCR images must belong to the private job')
        request['images'].append({'id': item['id'], 'path': str(path.resolve()),
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if not request['images'] or len(request['images']) > MAX_IMAGES:
        raise ValueError('Local OCR image count unsupported')
    binary = checked_local_ocr_worker()
    binary_bytes = read_source_bytes(binary)
    binary_sha = hashlib.sha256(binary_bytes).hexdigest()
    build_receipt = json.loads(read_source_bytes(binary.parent / 'build_receipt.json'))
    if build_receipt.get('binary_sha256') != binary_sha:
        raise ValueError('Checked local OCR executable changed before copying')
    request['worker_binary_sha256'] = binary_sha
    frozen, output = job / 'ocr_request.json', job / 'ocr_result.json'
    executable = job / 'private-vision-ocr'
    if frozen.exists():
        if json.loads(frozen.read_text()) != request:
            raise ValueError('Frozen local OCR request changed')
        if (executable.is_symlink() or not executable.is_file()
                or hashlib.sha256(read_source_bytes(executable)).hexdigest() != binary_sha):
            raise ValueError('Private OCR executable copy changed')
        if output.is_symlink() or not output.is_file():
            raise ValueError('Interrupted local OCR request requires review')
        result = checked_ocr_result(request, json.loads(output.read_text()))
        receipt_path = job / 'ocr_receipt.json'
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError('Local OCR receipt missing')
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get('request_sha256') != hashlib.sha256(frozen.read_bytes()).hexdigest()
                or receipt.get('output_sha256') != hashlib.sha256(output.read_bytes()).hexdigest()
                or receipt.get('worker_source_sha256') != request['worker_source_sha256']
                or receipt.get('worker_binary_sha256') != binary_sha):
            raise ValueError('Local OCR receipt changed')
        return result
    if output.exists() or output.is_symlink() or (job / 'ocr_receipt.json').exists():
        raise ValueError('Unbound local OCR output requires review')
    # Vision reads its executable bundle directory during model initialisation.
    # Keep the checked generic executable inside the already-readable job rather
    # than opening its parent compiler/cache directory to private processing.
    descriptor = os.open(executable, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o700)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(binary_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    if hashlib.sha256(executable.read_bytes()).hexdigest() != hashlib.sha256(binary_bytes).hexdigest():
        raise ValueError('Private OCR executable copy changed')
    _write_new(frozen, request)
    started = time.monotonic()
    run_private([executable, frozen, output], job, timeout=timeout)
    os.chmod(output, 0o600)
    result = checked_ocr_result(request, json.loads(output.read_text()))
    _write_new(job / 'ocr_receipt.json', {
        'contract': CONTRACT, 'request_sha256': hashlib.sha256(frozen.read_bytes()).hexdigest(),
        'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'worker_source_sha256': request['worker_source_sha256'],
        'worker_binary_sha256': binary_sha,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'image_count': len(result['images']), 'recognition_status': 'source_transcription_unreviewed',
        'financial_validation': 'not_established', 'network_access': 'denied'})
    return result


def rasterize_pdf(content, job_directory, *, width=2400, max_pages=MAX_IMAGES):
    """Render complete private pages for OCR; never crop a selected passage."""
    import pypdfium2
    job = Path(job_directory).resolve()
    if not job.is_dir() or not 600 <= width <= 3000 or not 1 <= max_pages <= MAX_IMAGES:
        raise ValueError('Private page rendering bounds unsupported')
    images = []
    with pypdfium2.PdfDocument(content) as document:
        if not 1 <= len(document) <= max_pages:
            raise ValueError('Private PDF page count unsupported; split explicitly')
        for number in range(len(document)):
            page = document[number]
            scale = width / page.get_width()
            if math.ceil(page.get_width() * scale) * math.ceil(page.get_height() * scale) > MAX_PIXELS:
                page.close()
                raise ValueError('Private PDF page raster exceeds supported pixel bound')
            path = job / ('page_%04d.png' % (number + 1))
            if path.exists() or path.is_symlink():
                page.close()
                raise ValueError('Private page raster already exists')
            bitmap = page.render(scale=scale)
            try:
                bitmap.to_pil().save(path)
                os.chmod(path, 0o600)
                images.append({'id': 'page_%04d' % (number + 1), 'path': str(path),
                               'page': number + 1, 'width_points': page.get_width(),
                               'height_points': page.get_height()})
            finally:
                bitmap.close()
                page.close()
    return images


def run_document_ocr(job_directory, *, timeout=110):
    """Sequential isolated raster/OCR passes under one cumulative time bound.

    Seatbelt does not allow nested sandbox_apply. Each private subprocess gets
    its own network-denied boundary; neither executes outside isolation.
    """
    job = Path(job_directory).absolute()
    if job.is_symlink() or job.resolve() != job or not job.is_dir() or job.stat().st_mode & 0o077:
        raise ValueError('Canonical private OCR directory required')
    frozen = job / 'request.json'
    source = job / 'source.pdf'
    if frozen.is_symlink() or source.is_symlink():
        raise ValueError('Private OCR originals may not be linked')
    request = json.loads(frozen.read_text())
    if (request.get('contract') != CONTRACT or source.stat().st_size > 40_000_000
            or hashlib.sha256(source.read_bytes()).hexdigest() != request.get('source_sha256')):
        raise ValueError('Private OCR source request changed')
    result_path = job / 'page_observations.json'
    started = time.monotonic()
    image_path = job / 'page_images.json'
    if not image_path.exists():
        if list(job.glob('page_*.png')) or (job / 'worker-error.txt').exists():
            raise ValueError('Incomplete rasterization must be retained for review')
        run_private([sys.executable, PROJECT / 'scripts/private_document_ocr_worker.py', job],
                    job, timeout=timeout)
    if image_path.is_symlink():
        raise ValueError('Private raster inventory may not be linked')
    raster = json.loads(image_path.read_text())
    if raster.get('contract') != CONTRACT or raster.get('source_sha256') != request['source_sha256']:
        raise ValueError('Private raster source binding changed')
    remaining = timeout - (time.monotonic() - started)
    if remaining <= 0:
        raise TimeoutError('Private rasterization exhausted cumulative OCR budget')
    result = recognize_images(raster['images'], job, timeout=remaining,
                              languages=tuple(request.get('languages', ['en-US'])))
    pages = [{**row, 'page': image['page'], 'source_sha256': request['source_sha256'],
              'engine': result['engine'], 'language_correction': result['language_correction'],
              'coordinate_system': result['coordinate_system'],
              'width_points': image['width_points'], 'height_points': image['height_points']}
             for image, row in zip(raster['images'], result['images'])]
    payload = {'contract': CONTRACT, 'source_sha256': request['source_sha256'], 'pages': pages,
               'source_transcription_status': 'local_ocr_proposed_unreviewed',
               'financial_validation': 'not_established'}
    if result_path.exists():
        if result_path.is_symlink() or json.loads(result_path.read_text()) != payload:
            raise ValueError('Frozen private page observations changed')
    else:
        _write_new(result_path, payload)
    return payload


def replay_document_ocr(job_directory):
    """Independently replay immutable OCR evidence without running recognition.

    Source bytes, complete ordered raster inventory, generic worker provenance,
    raw recognition and its receipt are authorities. The saved page projection
    is compared with a reconstruction; its own digest is never a proof of text.
    This function is read-only and cannot compile, rasterise or invoke a model.
    """
    from io import BytesIO
    from PIL import Image
    from pypdf import PdfReader

    job = Path(job_directory).absolute()
    if (job.is_symlink() or not job.is_dir() or job.resolve() != job
            or job.stat().st_mode & 0o077):
        raise ValueError('Canonical private OCR replay directory required')

    def checked_file(path, *, within_job=True):
        path = Path(path).absolute()
        if (path.is_symlink() or not path.is_file() or path.resolve() != path
                or (within_job and not path.is_relative_to(job))):
            raise ValueError('Private OCR replay file is linked or outside scope')
        try:
            return read_source_bytes(path)
        except (OSError, ValueError) as error:
            raise ValueError('Private OCR replay file is unavailable or unsupported') from error

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate private OCR JSON key')
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError('Nonfinite private OCR JSON value')

    def load(path, *, within_job=True):
        raw = checked_file(path, within_job=within_job)
        try:
            value = json.loads(raw, object_pairs_hook=object_pairs, parse_constant=reject_constant)
        except (TypeError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError('Invalid private OCR JSON record') from error
        if not isinstance(value, dict):
            raise ValueError('Private OCR JSON object required')
        return raw, value

    def sha(raw):
        return hashlib.sha256(raw).hexdigest()

    def valid_sha(value):
        return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)

    original = checked_file(job / 'source.pdf')
    _, source_request = load(job / 'request.json')
    if (set(source_request) - {'contract','source_sha256','width','max_pages','languages'}
            or source_request.get('contract') != CONTRACT
            or source_request.get('source_sha256') != sha(original)):
        raise ValueError('Private OCR original source/request binding changed')
    width = source_request.get('width', 2400)
    max_pages = source_request.get('max_pages', MAX_IMAGES)
    languages = source_request.get('languages', ['en-US'])
    if (isinstance(width, bool) or not isinstance(width, int) or not 600 <= width <= 3000
            or isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= MAX_IMAGES
            or not isinstance(languages, list) or not 1 <= len(languages) <= 4
            or any(not isinstance(value, str) or not value for value in languages)):
        raise ValueError('Private OCR original rendering bounds unsupported')
    reader = PdfReader(BytesIO(original), strict=True)
    if not 1 <= len(reader.pages) <= max_pages:
        raise ValueError('Private OCR original page inventory exceeds bounds')
    _, raster = load(job / 'page_images.json')
    if (raster.get('contract') != CONTRACT or raster.get('source_sha256') != sha(original)
            or not isinstance(raster.get('images'), list) or len(raster['images']) != len(reader.pages)):
        raise ValueError('Private OCR raster inventory is not complete for the original')
    expected_images = []
    for number, (page, image) in enumerate(zip(reader.pages, raster['images']), 1):
        identifier = 'page_%04d' % number
        image_path = job / (identifier + '.png')
        if (not isinstance(image, dict) or set(image) !=
                {'id','path','page','width_points','height_points'} or
                image.get('id') != identifier or image.get('page') != number
                or image.get('path') != str(image_path)):
            raise ValueError('Private OCR raster order/location changed')
        image_bytes = checked_file(image_path)
        # Compare metadata with the original PDF geometry, not the projection.
        box, media = page.cropbox, page.mediabox
        page_width = min(float(box.right), float(media.right)) - max(float(box.left), float(media.left))
        page_height = min(float(box.top), float(media.top)) - max(float(box.bottom), float(media.bottom))
        rotation = int(page.get('/Rotate', 0)) % 360
        if rotation not in {0, 90, 180, 270} or float(page.get('/UserUnit', 1)) != 1:
            raise ValueError('Private OCR original page coordinate system unsupported')
        if rotation in {90, 270}:
            page_width, page_height = page_height, page_width
        for recorded, expected in [(image['width_points'],page_width), (image['height_points'],page_height)]:
            if (isinstance(recorded, bool) or not isinstance(recorded, (int, float))
                    or not math.isfinite(recorded) or recorded <= 0 or
                    not math.isfinite(expected) or expected <= 0 or not math.isclose(recorded,expected,abs_tol=0.01)):
                raise ValueError('Private OCR raster geometry differs from the original page')
        with Image.open(BytesIO(image_bytes)) as pixels:
            actual_width, actual_height = pixels.size
            if (pixels.format != 'PNG' or actual_width * actual_height > MAX_PIXELS
                    or abs(actual_width - width) > 1 or
                    abs(actual_height - math.ceil(page_height * width / page_width)) > 1):
                raise ValueError('Private OCR raster pixel geometry changed')
            pixels.verify()
        expected_images.append({'id':identifier,'path':str(image_path),'sha256':sha(image_bytes)})

    request_bytes, request = load(job / 'ocr_request.json')
    result_bytes, result = load(job / 'ocr_result.json')
    _, receipt = load(job / 'ocr_receipt.json')
    source_pin, binary_pin = request.get('worker_source_sha256'), request.get('worker_binary_sha256')
    if not valid_sha(source_pin) or not valid_sha(binary_pin):
        raise ValueError('Private OCR worker source/binary pins are missing')
    if request != {'contract':CONTRACT,'images':expected_images,'languages':languages,
                   'worker_source_sha256':source_pin,'worker_binary_sha256':binary_pin}:
        raise ValueError('Private OCR raw request does not bind the complete raster inventory')
    if (receipt.get('contract') != CONTRACT or receipt.get('network_access') != 'denied'
            or receipt.get('financial_validation') != 'not_established'
            or receipt.get('recognition_status') != 'source_transcription_unreviewed'
            or receipt.get('image_count') != len(expected_images)
            or receipt.get('request_sha256') != sha(request_bytes)
            or receipt.get('output_sha256') != sha(result_bytes)
            or receipt.get('worker_source_sha256') != source_pin
            or receipt.get('worker_binary_sha256') != binary_pin):
        raise ValueError('Private OCR raw receipt/hash/worker binding changed')
    copied_binary = checked_file(job / 'private-vision-ocr')
    if sha(copied_binary) != binary_pin:
        raise ValueError('Private OCR copied worker binary changed')
    build = BUILD_ROOT / (source_pin + '-explicit-sdk-v1')
    _, build_receipt = load(build / 'build_receipt.json', within_job=False)
    built_binary = checked_file(build / 'private-vision-ocr', within_job=False)
    if (sha(read_source_bytes(SOURCE)) != source_pin
            or build_receipt.get('contract') != 'private-vision-ocr-build-v1'
            or build_receipt.get('source_sha256') != source_pin
            or build_receipt.get('binary_sha256') != binary_pin
            or build_receipt.get('private_inputs') is not False
            or build_receipt.get('sdk') != str(SDK)
            or build_receipt.get('compiler') != str(SWIFTC)
            or sha(built_binary) != binary_pin):
        raise ValueError('Private OCR generic worker build provenance changed')
    checked_ocr_result(request, result)
    pages = [{**row, 'page':image['page'], 'source_sha256':sha(original),
              'engine':result['engine'], 'language_correction':result['language_correction'],
              'coordinate_system':result['coordinate_system'],
              'width_points':image['width_points'], 'height_points':image['height_points']}
             for image,row in zip(raster['images'],result['images'])]
    reconstructed = {'contract':CONTRACT,'source_sha256':sha(original),'pages':pages,
                     'source_transcription_status':'local_ocr_proposed_unreviewed',
                     'financial_validation':'not_established'}
    _, saved_projection = load(job / 'page_observations.json')
    if saved_projection != reconstructed:
        raise ValueError('Private OCR page projection differs from recorded raw recognition')
    return reconstructed
