from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject

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
