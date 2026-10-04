"""Isolated read-only parser for local private acceptance attachments.

The worker never opens an API/deal store or emits extracted content to stdout.
Its source inventory stays under the mode-0700 ignored diagnostic directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from agents.core.ingestion_agent import ingest_document
from delivery.storage import read_source_bytes


def _write_private(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def main() -> None:
    root = Path.cwd()
    request = json.loads((root / 'request.json').read_text())
    paths = request['files']
    if (not isinstance(paths, list) or len(paths) != 3 or
            sorted(Path(path).suffix.lower() for path in paths) != ['.pdf', '.pdf', '.xlsx']):
        raise ValueError('Exactly two PDFs and one XLSX are required')
    inventory = []
    reports = []
    for path_text in paths:
        path = Path(path_text)
        if path.is_symlink() or not path.is_file():
            raise ValueError('Private acceptance input is unavailable or linked')
        raw = read_source_bytes(path)
        file_hash = hashlib.sha256(raw).hexdigest()
        document = ingest_document(str(path), tenant_id='', deal_id='')
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
        {'contract': 'private-acceptance-ingest-v1', 'passages': inventory,
         'inventory_sha256': full_digest})
    _write_private(root / 'memo_sources.json',
        {'contract': 'private-acceptance-memo-sources-v1', 'sources': sources,
         'source_sha256': source_digest,
         'complete': (len(sources) <= 30 and
                      sum(len(row['passage']) for row in sources) <= 24000 and
                      all(30 <= len(row['passage']) <= 4000 for row in sources))})
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
