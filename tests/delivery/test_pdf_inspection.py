from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject
from reportlab.pdfgen import canvas

from delivery.inspection import inspect_bytes


def _pdf(*, page_action=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=720, height=405)
    if page_action:
        page[NameObject("/AA")] = DictionaryObject()
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_records_exact_page_geometry_and_blank_page_coverage():
    report = inspect_bytes(_pdf(), "pdf")
    assert report["page_count"] == 1
    assert report["page_geometry"] == [
        {"page": 1, "width_points": 720.0, "height_points": 405.0, "rotation": 0}
    ]
    assert report["pages_without_text"] == [1]
    assert report["pages_without_content"] == [1]
    assert {finding["code"] for finding in report["findings"]} == {
        "pdf_pages_without_searchable_text", "pdf_pages_without_content_stream"
    }
    assert report["structural_status"] == "fail"
    assert report["visual_status"] == "not_run"


def test_pdf_page_actions_require_review_without_exposing_action_data():
    report = inspect_bytes(_pdf(page_action=True), "pdf")
    assert any(finding == {"code": "pdf_page_action_requires_review", "page": 1}
               for finding in report["findings"])
    assert report["structural_status"] == "fail"


def test_layout_diagnostic_flags_overflow_and_continuation_without_approving_visual_quality():
    def made_pdf(*, overflow=False):
        output = BytesIO()
        page = canvas.Canvas(output, pagesize=(500, 500))
        page.setFont("Helvetica", 12)
        page.drawString(72, 400, "Synthetic material heading")
        if overflow:
            page.drawString(480, 390, "A substantive sentence runs beyond the page boundary")
            page.drawString(72, 370, "Synthetic evidence (continued)")
        page.showPage()
        page.save()
        return output.getvalue()

    clean = inspect_bytes(made_pdf(), "pdf")
    diagnostic = clean["layout_diagnostic"]
    assert diagnostic["version"] == "pdf-layout-diagnostic-v1"
    assert diagnostic["status"] == "observed"
    assert diagnostic["review_required"] is True
    assert diagnostic["flags"] == []
    assert diagnostic["pages"][0]["text_area_ratio"] > 0
    assert clean["visual_status"] == "not_run"

    flawed = inspect_bytes(made_pdf(overflow=True), "pdf")
    diagnostic = flawed["layout_diagnostic"]
    assert {flag["code"] for flag in diagnostic["flags"]} == {
        "text_crosses_page_boundary", "continued_heading_present"
    }
    assert diagnostic["pages"][0]["outside_page_characters"] > 0
    assert "substantive sentence" not in str(diagnostic).lower()
    assert flawed["visual_status"] == "not_run"
