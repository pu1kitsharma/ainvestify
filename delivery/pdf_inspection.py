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
    return {"page_count": len(reader.pages), "page_geometry": sizes,
            "pages_without_text": pages_without_text,
            "pages_without_content": pages_without_content,
            "pages_with_only_numeric_text": pages_with_only_numeric_text,
            "findings": findings}
