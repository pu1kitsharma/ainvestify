"""Numeric table detection in position-preserving page text.

Code finds rows (a label followed by two or more numeric cells) and groups them
by indentation, which separates side-by-side tables. The model later supplies
the meaning of columns and rows; code transcribes every value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NUMERIC = re.compile(r'^\(?-?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?\)?%?$')


def is_numeric(cell: str) -> bool:
    cell = cell.strip()
    return bool(cell) and any(ch.isdigit() for ch in cell) and bool(NUMERIC.match(cell))


@dataclass
class TableRow:
    line: int
    label: str
    values: list[str]


@dataclass
class Table:
    id: str
    indent: int
    header: str = ''
    rows: list[TableRow] = field(default_factory=list)
    key: tuple[int, int] = (0, 0)

    def width(self) -> int:
        counts = [len(row.values) for row in self.rows]
        return max(set(counts), key=counts.count) if counts else 0

    def describe(self) -> str:
        lines = [f'TABLE {self.id} (header line: "{self.header or "none found"}"; {self.width()} value columns in most rows)']
        for number, row in enumerate(self.rows, 1):
            lines.append(f'  row {number}: {row.label or "(no label)"} — {len(row.values)} values: {" ".join(row.values)}')
        return '\n'.join(lines)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().split(' | ') if cell.strip()]


def _segments(cells: list[str]) -> list[tuple[str, list[str]]]:
    """Split a line into (label, numeric run) pairs; side-by-side tables share a line."""
    segments, label, values = [], [], []
    for cell in cells:
        if is_numeric(cell):
            values.append(cell)
        else:
            if values:
                segments.append((' '.join(label), values))
                label, values = [], []
            label.append(cell)
    if values:
        segments.append((' '.join(label), values))
    elif label and segments:
        return []  # trailing text after numbers: not a clean table row
    return segments


def detect_tables(text: str, unit_id: str) -> tuple[list[Table], list[str]]:
    """Return tables and the page lines that are not table rows."""
    tables: list[Table] = []
    pending_headers: dict[int, str] = {}
    lines = text.splitlines()
    for number, raw in enumerate(lines):
        indent = len(raw) - len(raw.lstrip(' '))
        cells = _cells(raw)
        segments = [segment for segment in _segments(cells)]
        if segments and all(len(values) >= 2 for _, values in segments):
            for position, (label, values) in enumerate(segments):
                key = (indent, position)
                table = next((t for t in reversed(tables) if t.key[1] == position and abs(t.key[0] - indent) <= 1), None)
                if table is None or (table.rows and number - table.rows[-1].line > 4):
                    table = Table(f'{unit_id}.T{len(tables) + 1}', indent, pending_headers.get(indent, ''))
                    table.key = key
                    tables.append(table)
                table.rows.append(TableRow(number, label, values))
        elif len(cells) >= 3:
            for near in (indent - 1, indent, indent + 1):
                pending_headers[near] = ' '.join(cells)
    tables = [table for table in tables if len(table.rows) >= 2]
    kept = {row.line for table in tables for row in table.rows}
    other = [line for number, line in enumerate(lines) if number not in kept]
    return tables, other
