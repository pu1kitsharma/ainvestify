"""Exact input binding and fail-closed private document inspection."""
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import sys

import pytest

from delivery import private_inspection as boundary
from delivery.isolation import isolation_available, run_private
from delivery.rendering import render_intro, render_deck_pdf
from scripts import private_inspection_worker


def _runner(command, job, **kwargs):
    assert command == [sys.executable, boundary.SCRIPT]
    assert set(kwargs) == {'timeout'} and 0 < kwargs['timeout'] <= 120
    assert set(path.name for path in job.iterdir()) <= {'request.json', 'input-000.bin', 'input-001.bin'}
    previous = Path.cwd()
    try:
        os.chdir(job)
        private_inspection_worker.main()
    finally:
        os.chdir(previous)


def _files():
    sections = [('Synthetic evidence', 'Source-reported synthetic statement.', 'Synthetic fixture')]
    return {'editable': ('pptx', render_intro('Synthetic fixture', sections)),
            'pdf': ('pdf', render_deck_pdf('Synthetic fixture', sections))}


def test_exact_pair_metadata_uses_fresh_confined_job_only(monkeypatch):
    jobs = []
    def isolated(command, job, **kwargs):
        jobs.append(job)
        _runner(command, job, **kwargs)
    monkeypatch.setattr(boundary, 'run_private', isolated)
    contents = _files()
    files, pairs = boundary.inspect_artifacts(contents, [('editable', 'pdf')])
    assert files['editable']['sha256'] == hashlib.sha256(contents['editable'][1]).hexdigest()
    assert pairs[0]['report']['pair_status'] == 'pass'
    assert pairs[0]['report']['content_layout_status'] == 'not_run'
    assert files['pdf']['visual_status'] == 'not_run'
    assert not jobs[0].exists()


@pytest.mark.parametrize('tamper', ['hash', 'input_digest', 'extra', 'duplicate_json', 'false_pass', 'pair_hash'])
def test_unbound_or_unexpected_worker_metadata_is_rejected(monkeypatch, tamper):
    def malicious(command, job, **kwargs):
        _runner(command, job, **kwargs)
        path = job / 'result.json'
        result = json.loads(path.read_text())
        if tamper == 'hash':
            result['files']['pdf']['sha256'] = '0' * 64
        elif tamper == 'input_digest':
            result['input_digest'] = '0' * 64
        elif tamper == 'extra':
            result['files']['pdf']['formula_cells'] = [{'private_text': 'must-not-return'}]
        elif tamper == 'false_pass':
            result['files']['pdf']['findings'] = [{'code': 'invalid_or_unsupported_file'}]
        elif tamper == 'pair_hash':
            result['pairs'][0]['report']['pdf_sha256'] = '0' * 64
        if tamper == 'duplicate_json':
            path.write_text('{"contract":"ignored",' + path.read_text()[1:])
        else:
            path.write_text(json.dumps(result))
    monkeypatch.setattr(boundary, 'run_private', malicious)
    with pytest.raises(ValueError):
        boundary.inspect_artifacts(_files(), [('editable', 'pdf')])


def test_worker_absence_never_falls_back_to_api_parser(monkeypatch):
    def denied(*_, **__):
        raise RuntimeError('private_process_isolation_unavailable')
    monkeypatch.setattr(boundary, 'run_private', denied)
    with pytest.raises(ValueError, match='private_artifact_inspection_unavailable'):
        boundary.inspect_artifacts({'artifact': ('pdf', b'%PDF-synthetic-invalid')})
    with pytest.raises(ValueError):
        boundary.inspect_artifacts({'artifact': ('pdf', b'x')}, timeout=121)


def test_worker_rechecks_input_bytes_before_parsing(monkeypatch):
    def changed(command, job, **kwargs):
        (job / 'input-000.bin').write_bytes(b'changed after exact request freeze')
        _runner(command, job, **kwargs)
    monkeypatch.setattr(boundary, 'run_private', changed)
    with pytest.raises(ValueError, match='contract_invalid'):
        boundary.inspect_artifacts({'artifact': ('pdf', b'%PDF-synthetic-invalid')})


def test_hidden_workbook_checks_remain_and_cell_values_stay_inside_worker(monkeypatch):
    from io import BytesIO
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active['A1'] = 'synthetic-private-cell-text'
    hidden = workbook.create_sheet('Hidden fixture')
    hidden.sheet_state = 'hidden'
    hidden['A1'] = '=SUM(1,2)'
    hidden['A2'] = '#REF!'
    hidden['A2'].data_type = 'e'
    content = BytesIO()
    workbook.save(content)
    monkeypatch.setattr(boundary, 'run_private', _runner)
    files, _ = boundary.inspect_artifacts({'workbook': ('xlsx', content.getvalue())})
    report = files['workbook']
    assert report['formula_count'] == 1 and report['sheet_count'] == 2
    assert {'stored_cell_error', 'missing_formula_cache'} <= {
        finding['code'] for finding in report['findings']}
    assert report['structural_status'] == 'fail'
    assert report['calculation_status'] == 'not_run'
    assert not {'formula_cells', 'sheets', 'defined_names', 'dependency_graph'} & set(report)
    assert 'synthetic-private-cell-text' not in json.dumps(report)


@pytest.mark.live_integration
def test_native_boundary_denies_other_files_network_and_credentials(tmp_path, monkeypatch):
    if platform.system() != 'Linux' or not isolation_available()[0]:
        pytest.skip('Requires qualified native Linux private isolation')
    outside, job = tmp_path / 'other-tenant.txt', tmp_path / 'job'
    outside.write_text('synthetic-other-tenant-secret')
    job.mkdir(mode=0o700)
    monkeypatch.setenv('PRIVATE_INSPECTION_TEST_SECRET', 'synthetic-env-secret')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        code = (
            'import json,os,socket;from pathlib import Path\n'
            'result={}\n'
            f'try: Path({str(outside)!r}).read_bytes(); result["other_file"]=True\n'
            'except OSError: result["other_file"]=False\n'
            f'try: socket.create_connection(("127.0.0.1",{listener.getsockname()[1]}),timeout=1).close(); result["network"]=True\n'
            'except OSError: result["network"]=False\n'
            'result["credentials"]="PRIVATE_INSPECTION_TEST_SECRET" in os.environ\n'
            'result["model_capability"]="PRIVATE_OLLAMA_SOCKET" in os.environ\n'
            'Path("result.json").write_text(json.dumps(result))\n')
        run_private([sys.executable, '-c', code], job, timeout=10)
    assert json.loads((job / 'result.json').read_text()) == {
        'other_file': False, 'network': False, 'credentials': False, 'model_capability': False}
    # Run the actual inspector as well; this is synthetic parsing, no model call.
    files, pairs = boundary.inspect_artifacts(_files(), [('editable', 'pdf')])
    assert files['pdf']['structural_status'] == 'pass'
    assert pairs[0]['report']['pair_status'] == 'pass'
    # A hostile OOXML entity is parsed only inside the same private boundary.
    from io import BytesIO
    from zipfile import ZipFile
    stream = BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('xl/workbook.xml',
            f'<!DOCTYPE workbook [<!ENTITY steal SYSTEM "{outside.as_uri()}">]>'
            '<workbook>&steal;</workbook>')
    files, _ = boundary.inspect_artifacts({'hostile': ('xlsx', stream.getvalue())})
    assert files['hostile']['structural_status'] == 'fail'
    assert files['hostile']['findings'][0]['code'] == 'invalid_or_unsupported_file'
    assert 'synthetic-other-tenant-secret' not in json.dumps(files)
