from delivery.inspection import inspect_bytes
from delivery.rendering import render_research_pdf
from pypdf import PdfReader
from io import BytesIO


def test_draft_pdf_contains_recorded_section_and_source():
    content = render_research_pdf("Example Company", [
        ("Reason to investigate", "The reported round warrants further research, while revenue is unknown.",
         "[S1] https://startupdb.com/api/v1/startups/example")])
    report = inspect_bytes(content, "pdf")
    assert report["structural_status"] == "pass"
    assert report["page_count"] == 1
    assert report["visual_status"] == "not_run"


def test_pdf_separates_model_analysis_exact_excerpt_and_source_version():
    body = ("The reported pilot calls for buyer validation [S1].\n\n"
            "Source claims and exact excerpts:\n"
            "[S1] Example describes a clinic pilot. Exact excerpt: "
            "Example describes a scheduling pilot with one clinic.")
    content = render_research_pdf("Example Company", [
        ("Diligence recommendation", body,
         "[S1] https://example.org/pilot | Example source | version version123")])
    report = inspect_bytes(content, "pdf")
    assert report["structural_status"] == "pass"
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    for value in ("Diligence recommendation", "SOURCE CLAIMS AND EXACT EXCERPTS",
                  "scheduling pilot with one clinic", "SOURCE VERSIONS", "version123"):
        assert value in text
