"""Stable, JSON-serializable observations for local analyst tools."""
from __future__ import annotations

from typing import Any

TOOL_VERSION = "tools/v1"


def observation(tool: str, result: dict[str, Any] | None = None, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    errors = errors or []
    return {"version": TOOL_VERSION, "ok": not errors, "tool": tool, "result": result or {}, "errors": errors}


def json_safe(value):
    """Retain rejected nonfinite inputs as explicit tagged diagnostics in JSONL."""
    import math
    if isinstance(value, float) and not math.isfinite(value):
        return {'invalid_number': repr(value)}
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def bounded_package(content, *, max_bytes, max_cells=None):
    """Reject package expansion and cell allocation before Office parsing."""
    from io import BytesIO
    from zipfile import ZipFile
    from defusedxml.ElementTree import iterparse
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(entry.file_size for entry in entries) > max_bytes * 4:
            raise ValueError('Expanded package exceeds byte/entry budget')
        if max_cells is not None:
            count = 0
            for entry in entries:
                if entry.filename.startswith('xl/worksheets/') and entry.filename.endswith('.xml'):
                    with archive.open(entry) as stream:
                        for _, element in iterparse(stream, events=('end',)):
                            if element.tag.rsplit('}', 1)[-1] == 'c':
                                count += 1
                                if count > max_cells:
                                    raise ValueError('Source workbook exceeds cell budget')
                            element.clear()
