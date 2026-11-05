"""Source units: one per PDF page or workbook sheet, with addressable blocks.

PDF pages use the original file's position-preserving text, so table rows and
side-by-side panels keep their structure. Local OCR of the rendered page is
attached as a separate block marked as an unverified transcription.
Workbook cells are kept as structured rows (row label, column header, value)
so figures can be transcribed by code rather than retyped by a model.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


@dataclass
class Unit:
    id: str
    document: str
    location: str
    blocks: dict[str, str] = field(default_factory=dict)
    ocr_blocks: set[str] = field(default_factory=set)
    image: Path | None = None
    provenance: dict = field(default_factory=dict)

    def text(self) -> str:
        lines = [f'SOURCE {self.id}: {self.document}, {self.location}']
        if self.provenance:
            lines.append('PUBLIC SOURCE (metadata, not document content): ' + self.provenance['url'])
        for block_id, text in self.blocks.items():
            label = ' (OCR transcription, unverified)' if block_id in self.ocr_blocks else ''
            lines.append(f'[block {block_id}]{label}\n{text}')
        return '\n'.join(lines)


@dataclass
class Sheet:
    id: str
    document: str
    name: str
    visibility: str
    rows: list[tuple[int, dict]]
    headers: dict[str, str]
    provenance: dict = field(default_factory=dict)

    def label(self, cells: dict) -> str:
        for key, value in cells.items():
            if isinstance(value, str) and value.strip() and not _numeric_text(value):
                return ' '.join(value.split())
        return ''

    def preview(self, limit=12) -> str:
        lines = [f'{self.id}: sheet "{self.name}" ({self.visibility}), {len(self.rows)} rows; columns: '
                 + ', '.join(f'{k}={v}' for k, v in list(self.headers.items())[:14])]
        for row, cells in self.rows[:limit]:
            lines.append(f'  r{row}: {self.label(cells)[:60]}')
        return '\n'.join(lines)


def _numeric_text(text):
    return bool(re.fullmatch(r'[\s\d.,%()\-]+', text))


def _literal(value):
    return value if isinstance(value, (dict, list)) else ast.literal_eval(value)


def short_name(name: str) -> str:
    stem = name.rsplit('.', 1)[0].strip()
    words = [word for word in re.split(r'[\s\-_()]+', stem) if word and word[0].isalpha()]
    return ''.join(word[0] for word in words).upper()[:5] or 'DOC'


def load_sources(db_path: str, tenant_id: str, deal_id: str, ocr_root: Path | None = None):
    connection = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        rows = connection.execute('SELECT data FROM documents WHERE tenant_id=? AND deal_id=?', (tenant_id, deal_id)).fetchall()
    finally:
        connection.close()
    units, sheets = [], []
    public_prefixes = set()
    for (data,) in sorted(rows, key=lambda row: json.loads(row[0])['filename']):
        document = json.loads(data)
        prefix = short_name(document['filename'])
        provenance = document.get('workbook_inventory', {}).get('public_source', {})
        if provenance:
            from delivery.storage import read_source_bytes
            raw = read_source_bytes(document['storage_uri'])
            if (provenance.get('origin') != 'public_document'
                    or hashlib.sha256(raw).hexdigest() != provenance.get('sha256')
                    or len(raw) != provenance.get('size_bytes')):
                raise ValueError('Public source bytes no longer match their provenance')
            prefix = 'P' + provenance['sha256'][:5].translate(str.maketrans('0123456789abcdef', 'ABCDEFGHIJKLMNOP'))
            if prefix in public_prefixes:
                raise ValueError('Public source identifiers collide; reconcile the documents')
            public_prefixes.add(prefix)
        if document['type'] == 'pdf':
            loaded = _pdf_units(document, prefix, ocr_root)
            units += loaded
        else:
            loaded = _sheets(document, prefix)
            sheets += loaded
        for source in loaded:
            source.provenance = dict(provenance)
    return units, sheets


def _layout_text(page) -> str:
    raw = page.extract_text(layout=True, x_density=7.25, y_density=13) or ''
    lines = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        body = re.sub(r' {3,}', ' | ', line.strip())
        body = re.sub(r'(?<=\S) {2}(?=\S)', ' ', body).replace('​', '')
        lines.append(' ' * (indent // 8) + body)
    return '\n'.join(lines)


def _page_file(ocr_root, filename, page_number, suffix):
    """Rendered page artefacts from the local OCR step (pdftoppm pads numbers only for long documents)."""
    if not ocr_root:
        return None
    folder = ocr_root / filename.rsplit('.', 1)[0].strip()
    for name in (f'page-{page_number}{suffix}', f'page-{page_number:02d}{suffix}', f'page-{page_number:03d}{suffix}'):
        if (folder / name).is_file():
            return folder / name
    return None


def _ocr_text(ocr_root, filename, page_number):
    path = _page_file(ocr_root, filename, page_number, '.txt')
    return ' '.join(path.read_text(errors='replace').split()) if path else ''


def _pdf_units(document, prefix, ocr_root):
    units = []
    with pdfplumber.open(document['storage_uri']) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            unit = Unit(f'{prefix}-p{number}', document['filename'], f'page {number}',
                        image=_page_file(ocr_root, document['filename'], number, '.png'))
            native = _layout_text(page)
            if native:
                unit.blocks['text'] = native
            # OCR is always attached when available: slides often carry figures only in images.
            # It stays a separate, flagged block so OCR-only support is visible downstream.
            ocr = _ocr_text(ocr_root, document['filename'], number)
            if len(ocr) > 20:
                unit.blocks['ocr'] = ocr
                unit.ocr_blocks.add('ocr')
            if unit.blocks:
                units.append(unit)
    return units


def _sheets(document, prefix):
    grouped = defaultdict(list)
    for block in document['blocks']:
        coordinates = _literal(block['coordinates'])
        grouped[(coordinates.get('sheet'), coordinates.get('visibility'))].append((coordinates.get('row'), _literal(block['content'])))
    sheets = []
    for index, ((name, visibility), rows) in enumerate(grouped.items(), 1):
        headers = {}
        for _, cells in rows:
            labels = {key.rstrip('0123456789'): ' '.join(str(value).split()) for key, value in cells.items()
                      if isinstance(value, str) and value.strip()}
            if len(labels) >= 3:
                headers = labels
                break
        sheets.append(Sheet(f'{prefix}-s{index}', document['filename'], str(name), str(visibility), rows, headers))
    return sheets


def format_number(value) -> str:
    if value == int(value) and abs(value) >= 1:
        return f'{int(value)}'
    return f'{value:.4f}'.rstrip('0').rstrip('.') if abs(value) < 1 else f'{value:.2f}'


def sheet_facts(sheet: Sheet) -> list[dict]:
    """Code transcription of numeric cells; no model involvement."""
    facts = []
    for row, cells in sheet.rows:
        label = sheet.label(cells)
        for key, value in cells.items():
            column = key.rstrip('0123456789')
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                if isinstance(value, str) and value.startswith('#'):
                    facts.append(_cell_fact(sheet, key, label, sheet.headers.get(column, column), value, error=True))
                continue
            facts.append(_cell_fact(sheet, key, label, sheet.headers.get(column, column), format_number(value)))
    return facts


def _cell_fact(sheet, key, label, header, value, error=False):
    return {'id': f'{sheet.id}.{key}', 'source': sheet.id, 'document': sheet.document,
            'location': f'sheet {sheet.name} ({sheet.visibility}) cell {key}',
            'statement': f'{label or "(unlabelled row)"} — {header}: {value}', 'topic': 'company_model',
            'metric': label, 'segment': '', 'period': header, 'value': '' if error else value,
            'unit': '', 'basis': 'company_model', 'block': key,
            'ambiguity': f'cell holds Excel error {value}' if error else '', 'ocr_only': False, 'cell_error': error,
            **({'provenance': dict(sheet.provenance)} if sheet.provenance else {})}


def sheet_text_cells(sheet: Sheet, minimum_length=40) -> Unit | None:
    """Narrative cells (assumption notes) for model extraction."""
    unit = Unit(f'{sheet.id}-notes', sheet.document, f'sheet {sheet.name} ({sheet.visibility}) notes',
                provenance=dict(sheet.provenance))
    for row, cells in sheet.rows:
        for key, value in cells.items():
            if isinstance(value, str) and len(value.strip()) >= minimum_length:
                label = sheet.label(cells)
                prefix = f'{label}: ' if label and label != value.strip() else ''
                unit.blocks[key] = prefix + ' '.join(value.split())
    return unit if unit.blocks else None
