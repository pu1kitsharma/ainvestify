"""The Office worker must keep its IPC socket inside the isolated job."""

from pathlib import Path
import json

import pytest

from delivery import libreoffice
from delivery.rendering import render_deck_pdf, render_intro


def test_private_conversion_uses_job_local_osl_socket(monkeypatch, tmp_path):
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
    monkeypatch.setattr(libreoffice, "private_temp_root", lambda: tmp_path)
    monkeypatch.setattr(libreoffice, "sandbox_binary", lambda binary: binary)
    monkeypatch.setattr(libreoffice, "office_read_roots", lambda binary: (
        Path("/Applications/LibreOffice.app"),))

    assert libreoffice.convert(editable, "pptx", "pdf") == expected_pdf
    assert observed["job"].parent == tmp_path.resolve()
    assert f"-env:OSL_SOCKET_PATH={observed['job']}" in observed["args"]
    assert observed["options"]["local_ipc"] is True
    assert observed["options"]["extra_read"] == (
        Path("/Applications/LibreOffice.app"),)
    arguments = observed["args"]
    assert arguments[arguments.index("--convert-to") + 1] == libreoffice.pdf_export_argument("pptx")


@pytest.mark.parametrize("source_format,filter_name", [
    ("pptx", "impress_pdf_Export"), ("docx", "writer_pdf_Export"),
    ("xlsx", "calc_pdf_Export"),
])
def test_static_pdf_export_has_explicit_viewer_and_embedding_policy(source_format, filter_name):
    kind, selected, raw_options = libreoffice.pdf_export_argument(source_format).split(":", 2)
    assert (kind, selected) == ("pdf", filter_name)
    assert json.loads(raw_options) == {
        "InitialPage": {"type": "long", "value": "0"},
        "Magnification": {"type": "long", "value": "0"},
        "UseTaggedPDF": {"type": "boolean", "value": "true"},
        "ExportFormFields": {"type": "boolean", "value": "false"},
        "IsAddStream": {"type": "boolean", "value": "false"},
    }
