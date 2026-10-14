"""Isolated read-only parser for local private acceptance attachments.

The worker never opens an API/deal store or emits extracted content to stdout.
Its source inventory stays under the mode-0700 ignored diagnostic directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from datetime import date, datetime
from urllib.parse import quote

from agents.core.ingestion_agent import ingest_document
from delivery.storage import read_source_bytes

INGEST_V1 = 'private-acceptance-ingest-v1'
INGEST_V2 = 'private-acceptance-ingest-v2'


def _json_scalar(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError('Unsupported retained cell type: ' + type(value).__name__)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_scalar)


def _financial_sources(content: bytes, file_hash: str):
    """Retain every nonempty cell without calculation or business interpretation.

    This is a separate per-sheet corpus, not an arbitrary first-N subset added
    to the small memo context. Oversized cells stay retained and explicitly
    prevent a claim of complete bounded-source compatibility.
    """
    from agents.analysis.workbook_reconciliation import read_cells
    inventory = read_cells(content)
    cells_by_sheet = {sheet['name']: [] for sheet in inventory['sheets']}
    for item in inventory['cells'].values():
        cells_by_sheet[item['sheet']].append(item)
    sources = []
    for sheet in inventory['sheets']:
        cells = cells_by_sheet[sheet['name']]
        chunks, chunk = [], []
        for cell in cells:
            if chunk and len(_canonical({'sheet': sheet, 'cells': chunk + [cell]})) > 3400:
                chunks.append(chunk)
                chunk = []
            chunk.append(cell)
        if chunk:
            chunks.append(chunk)
        for number, chunk in enumerate(chunks, 1):
            passage = _canonical({'sheet': sheet, 'cells': chunk,
                'actual_results_origin': 'not_established',
                'currency_unit_period_semantics': 'unassessed',
                'workbook_recalculation': 'not_performed',
                'financial_validation': 'not_established'})
            sources.append({'id': f'S{len(sources) + 1}',
                'url': f'private://{file_hash}/sheets/{quote(sheet["name"], safe="")}/{number}',
                'title': f'Private workbook sheet {sheet["name"]}, packet {number}',
                'passage': passage, 'version': file_hash,
                'attribution': 'Private workbook cells and stored caches; origin unreviewed'})
    inventory['cells'] = list(inventory['cells'].values())
    return {'contract': 'private-workbook-source-inventory-v1',
        'workbook_sha256': file_hash, 'inventory': inventory, 'sources': sources,
        'source_sha256': hashlib.sha256(_canonical(sources).encode()).hexdigest(),
        'inventory_sha256': hashlib.sha256(_canonical(inventory).encode()).hexdigest(),
        'retained_cell_count': sum(len(rows) for rows in cells_by_sheet.values()),
        'source_count': len(sources),
        'bounded_source_compatible': all(30 <= len(row['passage']) <= 4000 for row in sources),
        'semantic_coverage': 'unassessed', 'financial_validation': 'not_established',
        'workbook_recalculation': 'not_performed', 'actual_results_origin': 'not_established'}


def _pdf_visual_inventory(path):
    """Object counts are unread-content warnings, never chart interpretations."""
    import pdfplumber
    pages = {}
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            pages[number] = {'embedded_images': len(page.images),
                            'vector_curves': len(page.curves),
                            'vector_rectangles': len(page.rects),
                            'visual_content_status': 'unassessed'}
    return pages


def _write_private(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, default=_json_scalar)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def main() -> None:
    root = Path.cwd()
    request = json.loads((root / 'request.json').read_text())
    contract = request.get('contract', INGEST_V1)
    if contract not in {INGEST_V1, INGEST_V2}:
        raise ValueError('Unknown private ingestion contract')
    structured = contract == INGEST_V2
    paths = request['files']
    if (not isinstance(paths, list) or len(paths) != 3 or
            sorted(Path(path).suffix.lower() for path in paths) != ['.pdf', '.pdf', '.xlsx']):
        raise ValueError('Exactly two PDFs and one XLSX are required')
    inventory = []
    reports = []
    structures, financial_corpora = [], []
    for path_text in paths:
        path = Path(path_text)
        if path.is_symlink() or not path.is_file():
            raise ValueError('Private acceptance input is unavailable or linked')
        raw = read_source_bytes(path)
        file_hash = hashlib.sha256(raw).hexdigest()
        document = ingest_document(str(path), tenant_id='', deal_id='')
        if structured:
            structures.append({'format': document.type, 'file_sha256': file_hash,
                'blocks': [{'block_type': block.block_type.value,
                            'page': block.page, 'coordinates': block.coordinates,
                            'content': block.content} for block in document.blocks],
                'visual_inventory': _pdf_visual_inventory(path) if document.type == 'pdf' else {},
                'workbook_inventory': document.workbook_inventory if document.type == 'xlsx' else None})
            if document.type == 'xlsx':
                financial_corpora.append(_financial_sources(raw, file_hash))
        report = {'format': document.type, 'sha256': file_hash,
                  'byte_count': len(raw), 'block_count': len(document.blocks),
                  'page_count': len({block.page for block in document.blocks})
                  if document.type == 'pdf' else None}
        if document.type == 'xlsx':
            inspection = document.workbook_inventory or {}
            report['finding_codes'] = {
                code: sum(row.get('code') == code for row in inspection.get('findings', []))
                for code in sorted({row.get('code') for row in inspection.get('findings', [])
                                    if row.get('code')})}
            report['sheet_count'] = len(inspection.get('sheets', []))
        else:
            by_page = {}
            for block in document.blocks:
                content = (block.content if isinstance(block.content, str)
                           else json.dumps(block.content, ensure_ascii=False))
                if content.strip():
                    by_page.setdefault(block.page, []).append(content.strip())
            for page, pieces in sorted(by_page.items()):
                passage = '\n'.join(pieces)
                if not passage:
                    continue
                # Every page remains in the inventory. An oversized page blocks
                # the current memo context instead of silently losing evidence.
                inventory.append({'file_sha256': file_hash, 'page': page,
                                  'passage': passage, 'sha256': hashlib.sha256(
                                      passage.encode()).hexdigest()})
        reports.append(report)
    full_digest = hashlib.sha256(json.dumps(inventory, sort_keys=True,
        ensure_ascii=False).encode()).hexdigest()
    grouped = []
    for row in inventory:
        if (grouped and grouped[-1]['file_sha256'] == row['file_sha256'] and
                (len(row['passage']) < 30 or len(grouped[-1]['passage']) < 30) and
                len(grouped[-1]['passage']) + len(row['passage']) + 1 <= 4000):
            grouped[-1]['passage'] += '\n' + row['passage']
            grouped[-1]['pages'].append(row['page'])
        else:
            grouped.append({'file_sha256': row['file_sha256'],
                            'pages': [row['page']], 'passage': row['passage']})
    sources = []
    for index, row in enumerate(grouped, 1):
        pages = row['pages']
        source_hash = row['file_sha256']
        sources.append({'id': f'S{index}',
                        'url': f'private://{source_hash}/pages/{pages[0]}-{pages[-1]}',
                        'title': f'Private PDF pages {pages[0]}-{pages[-1]}',
                        'passage': row['passage'], 'version': source_hash,
                        'attribution': 'Private acceptance input; source-reported and unverified'})
    source_digest = hashlib.sha256(json.dumps(sources, sort_keys=True,
        ensure_ascii=False).encode()).hexdigest()
    _write_private(root / 'source_inventory.json',
        {'contract': contract, 'passages': inventory,
         'inventory_sha256': full_digest})
    _write_private(root / 'memo_sources.json',
        {'contract': 'private-acceptance-memo-sources-v2' if structured else 'private-acceptance-memo-sources-v1', 'sources': sources,
         'source_sha256': source_digest,
         'complete': (len(sources) <= 30 and
                      sum(len(row['passage']) for row in sources) <= 24000 and
                      all(30 <= len(row['passage']) <= 4000 for row in sources))})
    if structured:
        structure_by_file = {row['file_sha256']: row for row in structures}
        source_structures = {}
        for source, group in zip(sources, grouped):
            document = structure_by_file[group['file_sha256']]
            pages = group['pages']
            blocks = [block for block in document['blocks'] if block['page'] in pages]
            source_structures[source['id']] = {
                'file_sha256': group['file_sha256'], 'pages': pages,
                'block_topology_digest': hashlib.sha256(_canonical(blocks).encode()).hexdigest(),
                'table_block_count': sum(block['block_type'] == 'table' for block in blocks),
                'visual_inventory': {str(page): document['visual_inventory'].get(page, {})
                                     for page in pages},
                'visual_content_status': 'unassessed'}
        _write_private(root / 'structured_source_inventory.json', {
            'contract': INGEST_V2, 'documents': structures, 'source_structures': source_structures,
            'structure_sha256': hashlib.sha256(_canonical(structures).encode()).hexdigest(),
            'semantic_coverage': 'unassessed', 'visual_coverage': 'unassessed'})
        _write_private(root / 'financial_sources.json', {
            'contract': 'private-acceptance-financial-sources-v1', 'workbooks': financial_corpora,
            'semantic_coverage': 'unassessed', 'financial_validation': 'not_established',
            'workbook_recalculation': 'not_performed'})
    _write_private(root / 'ingest_result.json',
        {'state': 'parsed', 'document_count': len(reports),
         'documents': reports, 'pdf_passage_count': len(inventory),
         'pdf_passage_characters': sum(len(row['passage']) for row in inventory),
         'oversized_pdf_passages': sum(len(row['passage']) > 4000 for row in inventory),
         'inventory_sha256': full_digest,
         'memo_source_count': len(sources), 'memo_source_sha256': source_digest,
         'memo_source_complete': (len(sources) <= 30 and
                                  sum(len(row['passage']) for row in sources) <= 24000 and
                                  all(30 <= len(row['passage']) <= 4000 for row in sources)),
         'release_status': 'diagnostic_only_no_release'})


if __name__ == '__main__':
    main()
