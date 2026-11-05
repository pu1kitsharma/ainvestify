"""Downloaded PDFs are parsed offline with exact-byte and resource bounds."""
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import socket
import sys

import pytest
from reportlab.pdfgen import canvas

from agents.discovery.web_sources import PublicWebFetcher, SourceError, parse_pdf
from delivery import public_pdf
from delivery.isolation import isolation_available, run_private
from scripts import public_pdf_worker


def _pdf(pages=1):
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    for number in range(pages):
        pdf.drawString(40, 700, f'Synthetic public source page {number + 1} reports an offering and customer scope for independent verification.')
        pdf.showPage()
    pdf.save()
    return stream.getvalue()


def _runner(command, job, **kwargs):
    assert command == [sys.executable, public_pdf.SCRIPT]
    assert set(kwargs) == {'timeout'} and 0 < kwargs['timeout'] <= 25
    assert not job.resolve().is_relative_to(public_pdf.SCRIPT.parents[1].resolve())
    assert set(path.name for path in job.iterdir()) == {'request.json', 'input.bin'}
    request = json.loads((job / 'request.json').read_text())
    assert set(request) == {'contract', 'sha256', 'size_bytes'}
    before = Path.cwd()
    try:
        os.chdir(job)
        public_pdf_worker.main()
    finally:
        os.chdir(before)


def _fetcher(monkeypatch, body):
    fetcher = PublicWebFetcher()
    monkeypatch.setattr(fetcher, '_allowed', lambda *_: None)
    monkeypatch.setattr(fetcher, '_request', lambda *_a, **_k:
                        (200, {'Content-Type': 'application/pdf'}, body))
    return fetcher


def test_product_fetch_uses_confined_bytes_only_and_preserves_parser_semantics(monkeypatch):
    body = _pdf(12)
    expected = parse_pdf('https://synthetic.example/source.pdf', body)
    jobs = []
    def confined(command, job, **kwargs):
        jobs.append(job)
        _runner(command, job, **kwargs)
    monkeypatch.setattr(public_pdf, 'run_private', confined)
    monkeypatch.setattr('agents.discovery.web_sources.parse_pdf',
                        lambda *_: pytest.fail('Product fetch cannot use the in-process parser'))
    actual = _fetcher(monkeypatch, body).fetch(expected.url)
    assert actual == expected
    assert actual.truncated is True and '[PDF page 10]' in actual.text
    assert '[PDF page 11]' not in actual.text
    assert all(not job.exists() for job in jobs)


@pytest.mark.parametrize('tamper', ['hash', 'extra_field', 'wrong_type', 'oversized_text', 'duplicate_key'])
def test_worker_response_requires_exact_hash_and_bounded_schema(monkeypatch, tamper):
    def malicious(command, job, **kwargs):
        _runner(command, job, **kwargs)
        path = job / 'result.json'
        result = json.loads(path.read_text())
        if tamper == 'hash':
            result['sha256'] = '0' * 64
        elif tamper == 'extra_field':
            result['private_room'] = 'must-not-cross'
        elif tamper == 'wrong_type':
            result['page']['truncated'] = 0
        elif tamper == 'oversized_text':
            result['page']['text'] = 'x' * 24001
        if tamper == 'duplicate_key':
            path.write_text('{"contract":"ignored",' + path.read_text()[1:])
        else:
            path.write_text(json.dumps(result))
    monkeypatch.setattr(public_pdf, 'run_private', malicious)
    with pytest.raises(SourceError, match='could not be parsed') as error:
        _fetcher(monkeypatch, _pdf()).fetch('https://synthetic.example/source.pdf')
    assert error.value.status == 'partial'


def test_parser_absence_timeout_and_changed_bytes_fail_closed(monkeypatch):
    def denied(*_, **__):
        raise RuntimeError('private_process_isolation_unavailable')
    monkeypatch.setattr(public_pdf, 'run_private', denied)
    with pytest.raises(SourceError, match='could not be parsed'):
        _fetcher(monkeypatch, _pdf()).fetch('https://synthetic.example/source.pdf')
    def timeout(*_, **__):
        raise TimeoutError('worker timeout')
    monkeypatch.setattr(public_pdf, 'run_private', timeout)
    with pytest.raises(public_pdf.PublicPDFError, match='parse_failed'):
        public_pdf.confined_pdf_payload(_pdf())
    def modified(command, job, **kwargs):
        (job / 'input.bin').write_bytes(b'changed after download hash')
        _runner(command, job, **kwargs)
    monkeypatch.setattr(public_pdf, 'run_private', modified)
    with pytest.raises(public_pdf.PublicPDFError):
        public_pdf.confined_pdf_payload(_pdf())


def test_empty_pdf_stays_explicit_gap_and_budget_is_shared(monkeypatch):
    from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
    monkeypatch.setattr(public_pdf, 'run_private', _runner)
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.showPage()
    pdf.save()
    with pytest.raises(SourceError, match='insufficient selectable text'):
        _fetcher(monkeypatch, stream.getvalue()).fetch('https://synthetic.example/source.pdf')
    timeouts = []
    def bounded(command, job, **kwargs):
        timeouts.append(kwargs['timeout'])
        _runner(command, job, **kwargs)
    monkeypatch.setattr(public_pdf, 'run_private', bounded)
    with preparation_budget(PreparationBudget(max_seconds=3)):
        _fetcher(monkeypatch, _pdf()).fetch('https://synthetic.example/source.pdf')
    assert 0 < timeouts[0] <= 3


@pytest.mark.live_integration
def test_native_pdf_worker_and_no_network_database_or_credential_capability(tmp_path, monkeypatch):
    if platform.system() != 'Linux' or not isolation_available()[0]:
        pytest.skip('Requires native Linux private isolation')
    outside, job = tmp_path / 'synthetic-api-db.txt', tmp_path / 'job'
    outside.write_text('synthetic-database-secret')
    job.mkdir(mode=0o700)
    monkeypatch.setenv('SYNTHETIC_API_SECRET', 'synthetic-secret')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        code = ('import json,os,socket;from pathlib import Path\nresult={}\n'
                f'try:Path({str(outside)!r}).read_bytes();result["database"]=True\n'
                'except OSError:result["database"]=False\n'
                f'try:socket.create_connection(("127.0.0.1",{listener.getsockname()[1]}),timeout=1).close();result["network"]=True\n'
                'except OSError:result["network"]=False\n'
                'result["credential"]="SYNTHETIC_API_SECRET" in os.environ\n'
                'result["model"]="PRIVATE_OLLAMA_SOCKET" in os.environ\n'
                'Path("result.json").write_text(json.dumps(result))\n')
        run_private([sys.executable, '-c', code], job, timeout=10)
    assert json.loads((job / 'result.json').read_text()) == {
        'database': False, 'network': False, 'credential': False, 'model': False}
    actual = _fetcher(monkeypatch, _pdf()).fetch('https://synthetic.example/source.pdf')
    assert '[PDF page 1]' in actual.text
