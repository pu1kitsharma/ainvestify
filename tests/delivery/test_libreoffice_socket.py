"""The Office worker must keep its IPC socket inside the isolated job."""

from pathlib import Path

from delivery import libreoffice
from delivery.rendering import render_deck_pdf, render_intro


def test_private_conversion_uses_job_local_osl_socket(monkeypatch):
    sections = [("Synthetic claim", "A synthetic statement [S1].", "[S1] Synthetic record.")]
    editable = render_intro("Synthetic fixture", sections)
    expected_pdf = render_deck_pdf("Synthetic fixture", sections)
    observed = {}

    def fake_run_private(args, job, **options):
        observed.update(args=args, job=job, options=options)
        (job / "output" / "input.pdf").write_bytes(expected_pdf)

    monkeypatch.setattr(libreoffice, "office_binary", lambda: Path(
        "/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    monkeypatch.setattr(libreoffice, "run_private", fake_run_private)

    assert libreoffice.convert(editable, "pptx", "pdf") == expected_pdf
    assert observed["job"].parent == Path("/private/tmp")
    assert f"-env:OSL_SOCKET_PATH={observed['job']}" in observed["args"]
    assert observed["options"]["local_ipc"] is True
    assert observed["options"]["extra_read"] == (
        Path("/Applications/LibreOffice.app"),)
