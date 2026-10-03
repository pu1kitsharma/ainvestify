"""Qualify synthetic editable/PDF exports through the private Office worker.

The operator must attest that the supplied files are public or synthetic. This
diagnostic never changes release status; visual review remains a separate gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from delivery.inspection import inspect_export_pair
from delivery.libreoffice import convert, office_binary


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _pages(content: bytes) -> int:
    from io import BytesIO

    return len(PdfReader(BytesIO(content), strict=True).pages)


def qualify_pair(source: Path, name: str, output: Path) -> dict:
    fmt = "docx" if name == "memo" else "pptx"
    editable = (source / f"{name}.{fmt}").read_bytes()
    native = (source / f"{name}.pdf").read_bytes()
    converted = convert(editable, fmt, "pdf", timeout=90)
    (output / f"{name}.libreoffice.pdf").write_bytes(converted)
    native_pair = inspect_export_pair(editable, fmt, native)
    office_pair = inspect_export_pair(editable, fmt, converted)
    native_pages, office_pages = _pages(native), _pages(converted)
    return {
        "editable_sha256": _sha(editable),
        "native_pdf_sha256": _sha(native),
        "libreoffice_pdf_sha256": _sha(converted),
        "editable_format": fmt,
        "native_pages": native_pages,
        "libreoffice_pages": office_pages,
        "page_count_parity": native_pages == office_pages,
        "native_pair": native_pair,
        "libreoffice_pair": office_pair,
        "visual_status": "manual_review_pending",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--names", nargs="+", choices=("intro", "pitch", "memo"),
                        default=("intro", "pitch", "memo"))
    parser.add_argument("--operator-attested-public-or-synthetic", action="store_true")
    args = parser.parse_args()
    if not args.operator_attested_public_or_synthetic:
        parser.error("public/synthetic input attestation is required")
    source, output = args.source.resolve(), args.output.resolve()
    if source == output or source in output.parents or output in source.parents:
        parser.error("source and diagnostic output must be separate directories")
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "scope": "operator_attested_public_or_synthetic_diagnostic",
        "production_qualified": False,
        "investor_material_accepted": False,
        "libreoffice_binary": str(office_binary()),
        "pairs": {},
    }
    for name in args.names:
        try:
            report["pairs"][name] = qualify_pair(source, name, output)
        except Exception as exc:
            report["pairs"][name] = {"conversion_status": "fail",
                                     "error_type": type(exc).__name__, "reason": str(exc)}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(any(pair.get("libreoffice_pair", {}).get("pair_status") != "pass" or
                   not pair.get("page_count_parity", False)
                   for pair in report["pairs"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
