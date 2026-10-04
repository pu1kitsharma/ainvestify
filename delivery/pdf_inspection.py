"""Non-executing structural checks for private exported PDFs.

The result is an inventory, not visual, financial, or engine qualification.
Only page numbers and geometry leave this helper; source text and link targets do
not enter routine validation reports.
"""
from __future__ import annotations

from io import BytesIO
import re

MAX_PDF_BYTES = 128 * 1024 * 1024
MAX_PAGES = 500
MAX_LAYOUT_CHARS = 250_000
LAYOUT_DIAGNOSTIC_VERSION = "pdf-layout-diagnostic-v1"


def _layout_diagnostic(content: bytes) -> dict:
    """Bounded geometry observations, never a visual-quality approval.

    The report contains no reader-facing source text. A page may have an
    intentional continuation or sparse composition, so those observations
    require a human reviewer rather than becoming automatic PASS/FAIL votes.
    """
    import pdfplumber

    pages = []
    flags = []
    total_chars = 0
    with pdfplumber.open(BytesIO(content)) as document:
        for number, page in enumerate(document.pages, 1):
            chars = page.chars
            total_chars += len(chars)
            if total_chars > MAX_LAYOUT_CHARS or len(chars) > 50_000:
                return {"version": LAYOUT_DIAGNOSTIC_VERSION, "status": "incomplete",
                        "reason": "layout_character_scope_exceeded", "review_required": True,
                        "pages": pages, "flags": flags}
            width, height = float(page.width), float(page.height)
            if not chars or width <= 0 or height <= 0:
                pages.append({"page": number, "character_count": len(chars),
                              "text_area_ratio": 0.0, "small_text_characters": 0,
                              "outside_page_characters": 0})
                continue
            outside = sum(1 for char in chars if char["x0"] < -1 or char["top"] < -1
                          or char["x1"] > width + 1 or char["bottom"] > height + 1)
            small = sum(1 for char in chars if float(char.get("size", 0)) < 7)
            area = sum(max(0.0, min(width, char["x1"]) - max(0.0, char["x0"]))
                       * max(0.0, min(height, char["bottom"]) - max(0.0, char["top"]))
                       for char in chars)
            pages.append({"page": number, "character_count": len(chars),
                          "text_area_ratio": round(min(1.0, area / (width * height)), 4),
                          "small_text_characters": small,
                          "outside_page_characters": outside})
            if outside:
                flags.append({"code": "text_crosses_page_boundary", "page": number,
                              "character_count": outside})
            if small >= 50:
                flags.append({"code": "substantial_text_below_7pt", "page": number,
                              "character_count": small})
            # A heading explicitly marked continued is a useful page-split
            # signal; its presence alone does not prove a layout defect.
            first_lines = (page.extract_text() or "").splitlines()[:12]
            if any(re.search(r"\(continued\)\s*$", line, re.IGNORECASE)
                   for line in first_lines):
                flags.append({"code": "continued_heading_present", "page": number})
    return {"version": LAYOUT_DIAGNOSTIC_VERSION, "status": "observed",
            "review_required": True, "pages": pages, "flags": flags}


def inspect_pdf(content: bytes) -> dict:
    from pypdf import PdfReader

    if len(content) > MAX_PDF_BYTES:
        raise ValueError("pdf_size_limit")
    reader = PdfReader(BytesIO(content), strict=True)
    if reader.is_encrypted or not reader.pages:
        raise ValueError("encrypted_or_empty_pdf")
    if len(reader.pages) > MAX_PAGES:
        raise ValueError("page_limit")

    findings = []
    root = reader.trailer["/Root"]
    if any(key in root for key in ("/OpenAction", "/AA", "/Names", "/AcroForm")):
        findings.append({"code": "pdf_active_or_embedded_content_requires_review"})

    sizes = []
    pages_without_text = []
    pages_without_content = []
    pages_with_only_numeric_text = []
    for index, page in enumerate(reader.pages, 1):
        box = page.mediabox
        width, height = float(box.width), float(box.height)
        sizes.append({"page": index, "width_points": width, "height_points": height,
                      "rotation": int(page.get("/Rotate", 0)) % 360})
        if not (50 <= width <= 20_000 and 50 <= height <= 20_000):
            findings.append({"code": "pdf_invalid_page_geometry", "page": index})
        extracted = (page.extract_text() or "").strip()
        if not extracted:
            pages_without_text.append(index)
        elif not re.sub(r"[\d\s]+", "", extracted):
            pages_with_only_numeric_text.append(index)
        if page.get_contents() is None:
            pages_without_content.append(index)
        if "/AA" in page:
            findings.append({"code": "pdf_page_action_requires_review", "page": index})
        for annotation_ref in page.get("/Annots", []):
            annotation = annotation_ref.get_object()
            if any(key in annotation for key in ("/A", "/AA", "/FS")) or annotation.get("/Subtype") in {
                "/FileAttachment", "/RichMedia", "/3D"
            }:
                findings.append({"code": "pdf_annotation_action_or_attachment_requires_review", "page": index})

    if pages_without_text:
        findings.append({"code": "pdf_pages_without_searchable_text", "pages": pages_without_text})
    if pages_without_content:
        findings.append({"code": "pdf_pages_without_content_stream", "pages": pages_without_content})
    if pages_with_only_numeric_text:
        findings.append({"code": "pdf_pages_with_only_numeric_text", "pages": pages_with_only_numeric_text})
    try:
        layout = _layout_diagnostic(content)
    except Exception as exc:
        layout = {"version": LAYOUT_DIAGNOSTIC_VERSION, "status": "unavailable",
                  "reason": type(exc).__name__, "review_required": True,
                  "pages": [], "flags": []}
    return {"page_count": len(reader.pages), "page_geometry": sizes,
            "pages_without_text": pages_without_text,
            "pages_without_content": pages_without_content,
            "pages_with_only_numeric_text": pages_with_only_numeric_text,
            "layout_diagnostic": layout,
            "findings": findings}
