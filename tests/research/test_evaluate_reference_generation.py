"""Private CLI provenance/isolation risks using synthetic files and no inference."""
from copy import deepcopy
import hashlib
import math
from io import BytesIO, StringIO
import json
from contextlib import redirect_stdout

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from agents.research.document_evidence_manifest import build_document_manifest, attach_document_ocr
from delivery import document_generation_stage as stage
from delivery import document_ocr
from scripts import evaluate_reference_generation as cli
from scripts import private_reference_generation_worker as worker
from tests.research.test_document_generation import PIN


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_source(directory):
    """Generate source bytes in Python; no native Office, OCR or compiler runs."""
    directory.mkdir(mode=0o700)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(30, 700, 'The source reports a limited pilot in 2024.')
    pdf.showPage(); pdf.save()
    content = buffer.getvalue()
    (directory / 'source.pdf').write_bytes(content)
    manifest = build_document_manifest(content, 'pdf', tenant_id='tenant', deal_id='deal', document_id='synthetic')
    path = directory / 'document_evidence_manifest.json'
    stage._write_new(path, manifest)
    stage._write_new(directory / 'document_manifest_receipt.json', {
        'binding': manifest['binding'], 'manifest_sha256': _sha(path),
        'manifest_digest': manifest['manifest_digest']})
    return path, manifest


def synthetic_ocr(private_root, native_path, native, monkeypatch):
    """A self-consistent mock OCR archive; these observations are never gold labels."""
    root = private_root / 'synthetic-ocr'
    root.mkdir(mode=0o700)
    (root / 'source.pdf').write_bytes((native_path.parent / 'source.pdf').read_bytes())
    image = root / 'page_0001.png'
    page = PdfReader(BytesIO((root / 'source.pdf').read_bytes())).pages[0]
    width_points, height_points = float(page.cropbox.width), float(page.cropbox.height)
    width = 600
    Image.new('RGB', (width, math.ceil(height_points * width / width_points)), 'white').save(image)
    binary = root / 'private-vision-ocr'
    binary.write_bytes(b'mock generic executable bytes; never executed')
    source_sha = native['binding']['source_sha256']
    stage._write_new(root / 'request.json', {'contract': document_ocr.CONTRACT, 'source_sha256': source_sha,
        'width': width, 'max_pages': 120, 'languages': ['en-US']})
    raster = {'id': 'page_0001', 'path': str(image), 'page': 1,
              'width_points': width_points, 'height_points': height_points}
    stage._write_new(root / 'page_images.json', {'contract': document_ocr.CONTRACT,
        'source_sha256': source_sha, 'images': [raster], 'elapsed_seconds': 0})
    request = {'contract': document_ocr.CONTRACT, 'images': [{'id': raster['id'],
        'path': str(image), 'sha256': _sha(image)}], 'languages': ['en-US'],
        'worker_source_sha256': _sha(document_ocr.SOURCE), 'worker_binary_sha256': _sha(binary)}
    build_root = private_root / 'mock-generic-build'
    monkeypatch.setattr(document_ocr, 'BUILD_ROOT', build_root)
    build = build_root / (request['worker_source_sha256'] + '-explicit-sdk-v1')
    build.mkdir(mode=0o700, parents=True)
    (build / 'private-vision-ocr').write_bytes(binary.read_bytes())
    stage._write_new(build / 'build_receipt.json', {'contract': 'private-vision-ocr-build-v1',
        'source_sha256': request['worker_source_sha256'], 'binary_sha256': request['worker_binary_sha256'],
        'private_inputs': False, 'sdk': str(document_ocr.SDK), 'compiler': str(document_ocr.SWIFTC)})
    stage._write_new(root / 'ocr_request.json', request)
    result = {'contract': document_ocr.CONTRACT, 'engine': 'AppleVision-VNRecognizeTextRequest',
        'coordinate_system': 'normalized-bottom-left', 'language_correction': False,
        'images': [{'id': raster['id'], 'image_sha256': _sha(image), 'observations': [
            {'text': 'Unverified OCR observation', 'confidence': .8, 'bbox': [.1, .1, .7, .1]}]}]}
    stage._write_new(root / 'ocr_result.json', result)
    stage._write_new(root / 'ocr_receipt.json', {'contract': document_ocr.CONTRACT,
        'request_sha256': _sha(root / 'ocr_request.json'), 'output_sha256': _sha(root / 'ocr_result.json'),
        'worker_source_sha256': request['worker_source_sha256'],
        'worker_binary_sha256': request['worker_binary_sha256'], 'elapsed_seconds': 0, 'image_count': 1,
        'recognition_status': 'source_transcription_unreviewed', 'financial_validation': 'not_established',
        'network_access': 'denied'})
    page = {**result['images'][0], 'page': 1, 'source_sha256': source_sha,
        'engine': result['engine'], 'coordinate_system': result['coordinate_system'],
        'language_correction': False, 'width_points': raster['width_points'],
        'height_points': raster['height_points']}
    stage._write_new(root / 'page_observations.json', {'contract': document_ocr.CONTRACT,
        'source_sha256': source_sha, 'pages': [page],
        'source_transcription_status': 'local_ocr_proposed_unreviewed', 'financial_validation': 'not_established'})
    keys = ('page', 'source_sha256', 'image_sha256', 'engine', 'coordinate_system', 'language_correction', 'observations')
    manifest = attach_document_ocr(native, [{k: page[k] for k in keys}], expected_binding=native['binding'])
    target = native_path.parent / 'document_evidence_manifest_ocr.json'
    stage._write_new(target, manifest)
    stage._write_new(native_path.parent / 'document_manifest_ocr_receipt.json', {
        'binding': manifest['binding'], 'manifest_sha256': _sha(target), 'manifest_digest': manifest['manifest_digest'],
        'native_manifest_sha256': _sha(native_path), 'ocr_receipt_sha256': _sha(root / 'ocr_receipt.json'),
        'ocr_root': str(root)})
    return target, root


def _never(*args, **kwargs):
    pytest.fail('Changed private provenance must not reach isolation or inference')


def test_changed_original_fails_before_model_inventory_or_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'PRIVATE_ROOT', tmp_path)
    source, _ = synthetic_source(tmp_path / 'source')
    monkeypatch.setattr(cli, 'installed_digest', lambda name: PIN['digest'])
    output = tmp_path / 'run'
    assert cli.run(output, 'prepare', manifests=[source])['state'] == 'prepared'
    original = source.parent / 'source.pdf'
    original.write_bytes(original.read_bytes() + b'changed after freeze')
    monkeypatch.setattr(cli, 'installed_digest', _never)
    monkeypatch.setattr(cli, 'run_private', _never)
    with pytest.raises(ValueError, match='bytes changed'):
        cli.run(output, 'advance')
    assert not list(output.glob('call_*.started.json'))


@pytest.mark.parametrize('changed_file', ['ocr_result.json', 'ocr_request.json', 'page_observations.json'])
def test_changed_ocr_provenance_blocks_before_private_worker(tmp_path, monkeypatch, changed_file):
    monkeypatch.setattr(cli, 'PRIVATE_ROOT', tmp_path)
    source, native = synthetic_source(tmp_path / 'source')
    target, ocr_root = synthetic_ocr(tmp_path, source, native, monkeypatch)
    assert cli._checked_manifest(target)[0]['binding'] == native['binding']
    monkeypatch.setattr(cli, 'installed_digest', lambda name: PIN['digest'])
    output = tmp_path / 'run'
    assert cli.run(output, 'prepare', manifests=[target])['state'] == 'prepared'
    changed = stage._read(ocr_root / changed_file)
    if changed_file == 'page_observations.json':
        changed['pages'][0]['observations'][0]['text'] = 'Modified unreviewed observation'
    else:
        changed['unexpected_change'] = True
    (ocr_root / changed_file).write_text(json.dumps(changed))
    monkeypatch.setattr(cli, 'installed_digest', _never)
    monkeypatch.setattr(cli, 'run_private', _never)
    with pytest.raises(ValueError, match='OCR|observation projection'):
        cli.run(output, 'advance')
    assert not list(output.glob('response_*.json'))


def test_rehashed_derived_ocr_manifest_cannot_override_recorded_raw_recognition(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'PRIVATE_ROOT', tmp_path)
    source, native = synthetic_source(tmp_path / 'source')
    target, ocr_root = synthetic_ocr(tmp_path, source, native, monkeypatch)
    assert cli._checked_manifest(target)[0]['binding'] == native['binding']
    raw_before = (ocr_root / 'ocr_result.json').read_bytes()
    projected = stage._read(ocr_root / 'page_observations.json')
    projected['pages'][0]['observations'][0]['text'] = 'Tampered projection with internally consistent derived hashes'
    (ocr_root / 'page_observations.json').write_text(json.dumps(projected))
    keys = ('page', 'source_sha256', 'image_sha256', 'engine', 'coordinate_system', 'language_correction', 'observations')
    modified = attach_document_ocr(native, [{k: projected['pages'][0][k] for k in keys}],
                                   expected_binding=native['binding'])
    target.write_text(json.dumps(modified))
    receipt_path = source.parent / 'document_manifest_ocr_receipt.json'
    receipt = stage._read(receipt_path)
    receipt.update(manifest_sha256=_sha(target), manifest_digest=modified['manifest_digest'])
    receipt_path.write_text(json.dumps(receipt))
    monkeypatch.setattr(cli, 'installed_digest', _never)
    monkeypatch.setattr(cli, 'run_private', _never)
    output = tmp_path / 'should-not-prepare'
    with pytest.raises(ValueError, match='projection differs from recorded raw recognition'):
        cli.run(output, 'prepare', manifests=[target])
    assert not output.exists()
    assert (ocr_root / 'ocr_result.json').read_bytes() == raw_before


def test_unchanged_verify_worker_replays_without_model_or_model_network_access(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'PRIVATE_ROOT', tmp_path)
    source, _ = synthetic_source(tmp_path / 'source')
    monkeypatch.setattr(cli, 'installed_digest', lambda name: PIN['digest'])
    output = tmp_path / 'run'
    cli.run(output, 'prepare', manifests=[source])
    before = {p.name: _sha(p) for p in output.iterdir() if p.is_file()}
    monkeypatch.setattr(cli, 'installed_digest', _never)
    monkeypatch.setattr(worker, 'installed_digest', _never)
    monkeypatch.setattr(stage, 'advance_document_generation', _never)
    boundary = []
    def isolated_verify(command, root, *, timeout, extra_read, local_model):
        assert command[-1] == 'verify' and local_model is False and timeout == 118
        boundary.append(root)
        output = StringIO()
        with redirect_stdout(output):
            worker.main(root, 'verify')
        return output.getvalue()
    monkeypatch.setattr(cli, 'run_private', isolated_verify)
    result = cli.run(output, 'verify')
    assert result['state'] == 'needs_call' and result['phase'] == 'document_plan'
    assert boundary == [output]
    assert before == {p.name: _sha(p) for p in output.iterdir() if p.is_file()}


def test_complete_context_freezes_separate_installed_source_reviewer_without_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'PRIVATE_ROOT', tmp_path)
    source, _ = synthetic_source(tmp_path / 'source')
    source_pin = {'name': 'qwen3.5:14b', 'digest': 'b' * 64}
    monkeypatch.setattr(cli, 'installed_digest', lambda name:
        source_pin['digest'] if name == source_pin['name'] else PIN['digest'])
    monkeypatch.setattr(cli, 'run_private', _never)
    output = tmp_path / 'context-run'
    result = cli.run(output, 'prepare', manifests=[source], catalog_encoding='complete-source-maps-v1',
        source_map_profile='unit-ids-bound-v3', qualification_context_profile='complete-page-context-v1',
        source_coverage_reviewer=source_pin['name'])
    assert result['state'] == 'prepared'
    body, request, rows = stage._load_run(output)
    assert not rows and not list(output.glob('call_*.started.json'))
    assert body['source_coverage_reviewer_pin'] == source_pin
    assert body['reviewer_pin']['name'] == 'qwen3.5:9b'
    assert body['maximum_lifetime_model_calls'] == 2 * body['source_map_count'] + 81
    assert request[0] == 'document_source_map_v3'
    assert 'source_coverage_reviewer_pin' not in request[2]  # Reader requests remain independently reusable.


def test_separate_source_reviewer_without_explicit_profile_fails_before_model_lookup_or_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'PRIVATE_ROOT', tmp_path)
    source, _ = synthetic_source(tmp_path / 'source')
    monkeypatch.setattr(cli, 'installed_digest', _never)
    monkeypatch.setattr(cli, 'run_private', _never)
    output = tmp_path / 'should-not-prepare'
    with pytest.raises(ValueError, match='separate source reviewer requires'):
        cli.run(output, 'prepare', manifests=[source], catalog_encoding='complete-source-maps-v1',
            source_coverage_reviewer='qwen3.5:14b')
    assert not output.exists()
