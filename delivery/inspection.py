"""Bounded, non-executing inspection of exported files and workbook evidence.

Stored formula results are observations, never proof of recalculation. This
module reports unsupported coverage explicitly instead of inventing a PASS.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile, BadZipFile
from difflib import SequenceMatcher
import hashlib
import posixpath
import re
import unicodedata

from defusedxml import ElementTree as ET

MAX_EXPANDED = 128 * 1024 * 1024
MAX_PARTS = 10000
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _parts(content):
    archive = ZipFile(BytesIO(content))
    infos = archive.infolist()
    names = [i.filename for i in infos]
    if len(infos) > MAX_PARTS or len(names) != len(set(names)) or sum(i.file_size for i in infos) > MAX_EXPANDED:
        raise ValueError("archive_limits_or_duplicate_parts")
    for info in infos:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename or info.flag_bits & 1:
            raise ValueError("unsafe_or_encrypted_archive")
        if info.file_size > 1024*1024 and info.file_size / max(1, info.compress_size) > 500:
            raise ValueError("archive_expansion_limit")
    return archive


def inspect_bytes(content: bytes, fmt: str):
    report = {"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
        "format": fmt, "inspector_version": "ooxml-pdf-v2", "findings": [],
        "structural_status": "pass", "calculation_status": "not_run", "visual_status": "not_run",
        "compatibility_status": "not_run"}
    findings = report["findings"]
    try:
        if fmt == "pdf":
            from delivery.pdf_inspection import inspect_pdf
            pdf_report = inspect_pdf(content)
            findings.extend(pdf_report.pop("findings"))
            report.update(pdf_report)
        elif fmt in {"xlsx", "pptx", "docx"}:
            with _parts(content) as archive:
                names = archive.namelist()
                required = {"xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml", "docx": "word/document.xml"}[fmt]
                if required not in names or "[Content_Types].xml" not in names:
                    raise ValueError("wrong_document_type")
                trees = {}
                for name in names:
                    if name.endswith((".xml", ".rels")):
                        trees[name] = ET.fromstring(archive.read(name))
                    if any(term in name.lower() for term in ("vbaproject", "externallinks/", "connections.xml", "activex/", "customxml/")):
                        findings.append({"code": "unsupported_active_or_external_part", "part": name})
                    if "/embeddings/" in name:
                        findings.append({"code": "embedded_payload_requires_audience_review", "part": name})
                for name, tree in trees.items():
                    if name.endswith(".rels"):
                        for rel in tree:
                            if rel.attrib.get("TargetMode") == "External" and not rel.attrib.get("Type", "").endswith("/hyperlink"):
                                findings.append({"code": "external_dependency", "part": name})
                if fmt == "xlsx":
                    from delivery.formula_lineage import analyze
                    workbook = trees["xl/workbook.xml"]
                    report["sheets"] = [dict(sheet.attrib) for sheet in workbook.findall("s:sheets/s:sheet", NS)]
                    relationship_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                    rels = trees.get("xl/_rels/workbook.xml.rels")
                    targets = {}
                    if rels is not None:
                        for rel in rels:
                            target = rel.attrib.get("Target", "")
                            if rel.attrib.get("TargetMode") != "External":
                                part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
                                targets[rel.attrib.get("Id")] = part
                    part_to_sheet = {targets.get(s.get("{" + relationship_ns + "}id")): s["name"]
                        for s in report["sheets"] if targets.get(s.get("{" + relationship_ns + "}id")) in trees}
                    report["defined_names"] = [{"name": n.attrib.get("name"), "formula": n.text,
                        "localSheetId": n.attrib.get("localSheetId")}
                        for n in workbook.findall("s:definedNames/s:definedName", NS)]
                    report["calculation_settings"] = (workbook.find("s:calcPr", NS).attrib
                        if workbook.find("s:calcPr", NS) is not None else {})
                    report["formula_cells"] = []
                    for part, tree in trees.items():
                        if not part.startswith("xl/worksheets/") or not part.endswith(".xml"):
                            continue
                        for cell in tree.findall(".//s:sheetData/s:row/s:c", NS):
                            formula, cached = cell.find("s:f", NS), cell.find("s:v", NS)
                            where = {"part": part, "cell": cell.attrib.get("r")}
                            if cell.attrib.get("t") == "e":
                                findings.append(dict(where, code="stored_cell_error"))
                            if formula is not None:
                                report["formula_cells"].append(dict(where, formula=formula.text,
                                    formula_attributes=formula.attrib, cached_value=cached.text if cached is not None else None))
                                if cached is None or cached.text is None:
                                    findings.append(dict(where, code="missing_formula_cache"))
                                if formula.attrib.get("t") in {"array", "dataTable"}:
                                    findings.append(dict(where, code="unsupported_formula_type"))
                                if "#REF!" in (formula.text or ""):
                                    findings.append(dict(where, code="broken_formula_reference"))
                    for name in report["defined_names"]:
                        if "#REF!" in (name["formula"] or ""):
                            findings.append({"code": "broken_defined_name", "name": name["name"]})
                    report["formula_count"] = len(report["formula_cells"])
                    report["sheet_count"] = len(report["sheets"])
                    lineage = analyze(report["formula_cells"], part_to_sheet,
                        report["defined_names"], [s["name"] for s in report["sheets"]])
                    report["dependency_graph"] = lineage["graph"]
                    report["dependency_edge_count"] = lineage["edge_count"]
                    report["dependency_coverage"] = lineage["coverage"]
                    findings.extend(lineage["issues"])
                else:
                    report["chart_parts"] = sum("/charts/chart" in n and n.endswith(".xml") for n in names)
                    if fmt == "pptx":
                        presentation = trees["ppt/presentation.xml"]
                        rels = trees.get("ppt/_rels/presentation.xml.rels")
                        relationship_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                        slide_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
                        linked = {}
                        if rels is not None:
                            for rel in rels:
                                if rel.attrib.get("TargetMode") != "External":
                                    target = rel.attrib.get("Target", "")
                                    linked[rel.attrib.get("Id")] = (target.lstrip("/") if target.startswith("/")
                                        else posixpath.normpath(posixpath.join("ppt", target)))
                        slides = []
                        for element in presentation.findall(f".//{{{slide_ns}}}sldIdLst/{{{slide_ns}}}sldId"):
                            part = linked.get(element.attrib.get("{" + relationship_ns + "}id"))
                            if not part or part not in trees or not re.fullmatch(r"ppt/slides/slide\d+\.xml", part):
                                findings.append({"code": "missing_or_invalid_slide_relationship"})
                            else:
                                slides.append(part)
                        report["slide_parts"] = slides
                        report["slide_count"] = len(slides)
                        orphan = sorted({name for name in names if re.fullmatch(
                            r"ppt/slides/slide\d+\.xml", name)} - set(slides))
                        if orphan:
                            findings.append({"code": "orphan_slide_parts", "count": len(orphan)})
                        if not slides:
                            findings.append({"code": "empty_presentation"})
        else:
            raise ValueError("unsupported_file_format")
    except Exception as exc:
        # No raw parser errors: malformed source text must not enter routine logs.
        findings.append({"code": "invalid_or_unsupported_file", "error_type": type(exc).__name__})
    if findings:
        report["structural_status"] = "fail"
    return report


def summarize_report(report):
    """Do not expose private formula/value dumps in status endpoints."""
    return {k: v for k, v in report.items() if k not in {"formula_cells", "defined_names", "sheets", "dependency_graph"}}


def inspect_export_pair(editable: bytes, editable_format: str, pdf: bytes):
    """Check a concrete editable/PDF pair before deeper visual/content review.

    PPTX exports must have one PDF page per slide. Text in the editable file
    must appear on its corresponding PDF page (or anywhere in a DOCX export).
    For slides, also reject a substantial uninterrupted PDF-only text run.
    This does not validate chart data, visual layout or all PDF-only content.
    """
    if editable_format not in {"pptx", "docx"}:
        raise ValueError("unsupported_editable_pdf_pair")
    source = inspect_bytes(editable, editable_format)
    distribution = inspect_bytes(pdf, "pdf")
    findings = []
    if source["structural_status"] != "pass" or distribution["structural_status"] != "pass":
        findings.append({"code": "export_pair_input_invalid"})
    if editable_format == "pptx" and source.get("slide_count") != distribution.get("page_count"):
        findings.append({"code": "export_slide_page_count_mismatch",
                         "slide_count": source.get("slide_count"),
                         "pdf_page_count": distribution.get("page_count")})
    text_status = "not_run"
    if not findings:
        try:
            from pypdf import PdfReader

            def normalized(value):
                return " ".join(re.findall(r"[\w₹$€£%]+", unicodedata.normalize(
                    "NFKC", value).casefold()))

            with _parts(editable) as archive:
                names = archive.namelist()
                if editable_format == "pptx":
                    parts = source["slide_parts"]
                else:
                    parts = [name for name in names if name == "word/document.xml" or
                             re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)]
                fragments = []
                for part in parts:
                    tree = ET.fromstring(archive.read(part))
                    values = [node.text.strip() for node in tree.iter()
                              if node.tag.endswith("}t") and node.text and node.text.strip()]
                    fragments.append((part, values))
                if sum(len(values) for _, values in fragments) > 20000 or sum(
                        len(value) for _, values in fragments for value in values) > 1_000_000:
                    raise ValueError("export_text_scope_exceeded")
            reader = PdfReader(BytesIO(pdf), strict=True)
            page_text = [normalized(page.extract_text() or "") for page in reader.pages]
            alternate_page_text = None
            alternate_verified = 0
            for index, (part, values) in enumerate(fragments):
                target = page_text[index] if editable_format == "pptx" else " ".join(page_text)
                for value in values:
                    tokenized = normalized(value)
                    if tokenized and tokenized not in target:
                        # PDF text extractors can disagree about glyph ordering and
                        # kerning. Independently re-extract only a failed fragment;
                        # never discard a true mismatch by removing spaces.
                        if alternate_page_text is None:
                            import pdfplumber
                            with pdfplumber.open(BytesIO(pdf)) as alternate:
                                alternate_page_text = [normalized(page.extract_text() or "")
                                                       for page in alternate.pages]
                        alternate_target = (alternate_page_text[index] if editable_format == "pptx"
                                            else " ".join(alternate_page_text))
                        if tokenized in alternate_target:
                            alternate_verified += 1
                            continue
                        findings.append({"code": "export_editable_text_missing_from_pdf",
                                         "part": part, "fragment_sha256": hashlib.sha256(
                                             value.encode()).hexdigest()})
                        if len(findings) >= 20:
                            break
                if len(findings) >= 20:
                    break
                if editable_format == "pptx":
                    # Text-preserving export must not add a substantive claim
                    # absent from its editable slide. Short inserted tokens
                    # (page numbers, glyph extraction differences) are left
                    # for independent content review. Report a hash only.
                    editable_tokens = re.findall(r"\w+", normalized(" ".join(values)))
                    pdf_tokens = re.findall(r"\w+", target)
                    if len(pdf_tokens) > 2_000 or len(editable_tokens) > 2_000:
                        raise ValueError("export_pdf_text_scope_exceeded")
                    for operation, _, _, start, stop in SequenceMatcher(
                            None, editable_tokens, pdf_tokens, autojunk=False).get_opcodes():
                        added = pdf_tokens[start:stop]
                        if operation in {"insert", "replace"} and len(added) >= 6 and len(" ".join(added)) >= 30:
                            findings.append({"code": "export_pdf_only_substantive_text",
                                             "page": index + 1,
                                             "text_sha256": hashlib.sha256(" ".join(added).encode()).hexdigest()})
                            break
            text_status = "fail" if findings else "pass"
        except Exception as exc:
            findings.append({"code": "export_text_comparison_unavailable",
                             "error_type": type(exc).__name__})
            text_status = "not_run"
    pair_status = "fail" if findings else "pass"
    return {"editable_sha256": source["sha256"], "pdf_sha256": distribution["sha256"],
            "pair_status": pair_status, "editable_text_status": text_status,
            "content_layout_status": "not_run", "findings": findings,
            "alternate_extraction_verified_fragments": alternate_verified if text_status != "not_run" else 0}
