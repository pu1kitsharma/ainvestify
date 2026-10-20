"""Read-only, bounded private document observations. No network, OCR or inference."""
from __future__ import annotations

from functools import wraps
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries, get_column_letter

from agents.research.document_evidence_manifest import build_document_manifest, document_unit_observation
from .contracts import observation, json_safe, bounded_package


def document_tool(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        try:
            result = method(self, *args, **kwargs)
            if len(json.dumps(result, default=str, allow_nan=False)) > self.max_output_chars:
                raise ValueError('Output exceeds observation budget; request a narrower scope')
            response = observation('doc.' + method.__name__, result)
        except Exception as exc:
            response = observation('doc.' + method.__name__, errors=[{'code': type(exc).__name__, 'message': str(exc)}])
        try:
            log = self._path('documents.trajectory.jsonl')
            with log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(json_safe({'call': {'tool': 'doc.' + method.__name__, 'args': args, 'kwargs': kwargs}, 'observation': response}), default=str, allow_nan=False) + '\n')
        except Exception as exc:
            response['ok'] = False
            response['errors'].append({'code': 'TrajectoryWriteFailed', 'message': str(exc)})
        return response
    return call


class DocumentTools:
    """Caller must provision the sandbox and authorize tenant/deal ownership.

    First access pins exact source bytes for the session; subsequent changes fail.
    Supply expected_sha256 on calls when resuming a previously pinned session.
    """
    def __init__(self, sandbox_root, *, tenant_id, deal_id, max_bytes=20_000_000,
                 max_output_chars=100_000, max_cells=10000, max_pages=100):
        self.root = Path(sandbox_root).resolve(strict=True)
        self.tenant_id, self.deal_id = tenant_id, deal_id
        self.max_bytes, self.max_output_chars = max_bytes, max_output_chars
        self.max_cells, self.max_pages = max_cells, max_pages
        self.pins = {}

    def _path(self, source):
        result = (self.root / source).resolve()
        if not result.is_relative_to(self.root):
            raise ValueError('Source escapes private document sandbox')
        return result

    def _source(self, source, expected_sha256=None):
        path = self._path(source)
        if path.stat().st_size > self.max_bytes:
            raise ValueError('Source exceeds byte budget')
        with path.open('rb') as stream:
            content = stream.read(self.max_bytes + 1)
        if not content or len(content) > self.max_bytes:
            raise ValueError('Source empty or exceeds byte budget')
        digest = sha256(content).hexdigest()
        expected = self.pins.get(str(path))
        if (expected_sha256 is not None and expected_sha256 != digest) or (expected is not None and expected != digest):
            raise ValueError('Source hash changed or expected bytes mismatch')
        self.pins[str(path)] = digest
        fmt = path.suffix.lower().lstrip('.')
        if fmt in ('pptx', 'xlsx'):
            bounded_package(content, max_bytes=self.max_bytes, max_cells=self.max_cells if fmt == 'xlsx' else None)
        return content, {'source_sha256': digest, 'source_bytes': len(content), 'format': fmt}

    def _manifest(self, source, expected_sha256=None):
        content, binding = self._source(source, expected_sha256)
        if binding['format'] == 'pdf':
            import pdfplumber
            with pdfplumber.open(BytesIO(content)) as pdf:
                if len(pdf.pages) > self.max_pages:
                    raise ValueError('Document exceeds page budget')
        elif binding['format'] == 'pptx':
            with ZipFile(BytesIO(content)) as archive:
                count = sum(name.startswith('ppt/slides/slide') and name.endswith('.xml') and '/_rels/' not in name for name in archive.namelist())
                if count > self.max_pages:
                    raise ValueError('Presentation exceeds page budget')
        manifest = build_document_manifest(content, binding['format'], tenant_id=self.tenant_id,
                                           deal_id=self.deal_id, document_id=binding['source_sha256'])
        return manifest, binding

    @staticmethod
    def _page(manifest, page):
        count = len(manifest['pages']) or len(manifest['slides'])
        if type(page) is not int or not 1 <= page <= count:
            raise ValueError('Page/slide is outside document')
        return 'page' if manifest['pages'] else 'slide'

    @document_tool
    def pages(self, source, *, expected_sha256=None):
        manifest, binding = self._manifest(source, expected_sha256)
        return {**binding, 'count': len(manifest['pages']) or len(manifest['slides']),
                'unit': 'page' if manifest['pages'] else 'slide', 'unsupported': manifest['unsupported'],
                'status': 'native_observation_unverified_no_ocr'}

    @document_tool
    def text(self, source, page, *, expected_sha256=None):
        manifest, binding = self._manifest(source, expected_sha256)
        key = self._page(manifest, page)
        units = [document_unit_observation(u) for u in manifest['units']
                 if u['source_locator'].get(key) == page and u['kind'] in ('text', 'table_cell', 'notes')]
        return {**binding, 'page': page, 'units': units, 'status': 'native_observation_unverified_no_ocr'}

    @document_tool
    def tables(self, source, page, *, expected_sha256=None):
        manifest, binding = self._manifest(source, expected_sha256)
        key = self._page(manifest, page)
        tables = [t for t in manifest['tables'] if t['source_locator'].get(key) == page]
        if sum(len(t['cells']) for t in tables) > self.max_cells:
            raise ValueError('Table cells exceed budget')
        return {**binding, 'page': page, 'tables': tables, 'status': 'native_observation_unverified'}

    @document_tool
    def chart_series(self, source, slide, *, expected_sha256=None):
        manifest, binding = self._manifest(source, expected_sha256)
        if binding['format'] != 'pptx':
            raise ValueError('Native chart series requires PPTX; PDF chart inference unsupported')
        self._page(manifest, slide)
        units = [document_unit_observation(u) for u in manifest['units']
                 if u['source_locator'].get('slide') == slide and u['kind'] in ('chart', 'chart_literal')]
        return {**binding, 'slide': slide, 'units': units, 'status': 'stored_chart_caches_unverified_not_recalculated',
                'external_relationships_fetched': False}

    @document_tool
    def xlsx_read(self, source, sheet, address, *, expected_sha256=None):
        content, binding = self._source(source, expected_sha256)
        if binding['format'] != 'xlsx':
            raise ValueError('xlsx_read requires macro-free .xlsx')
        a,b,c,d = range_boundaries(address.replace('$', ''))
        if None in (a,b,c,d) or not (1 <= a <= c <= 16384 and 1 <= b <= d <= 1048576) or (c-a+1)*(d-b+1) > self.max_cells:
            raise ValueError('Invalid or over-budget range')
        book = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
        cached = load_workbook(BytesIO(content), read_only=True, data_only=True, keep_links=False)
        try:
            ws, cache = book[sheet], cached[sheet]
            values = []
            for row_number, (row, cache_row) in enumerate(zip(ws.iter_rows(min_row=b,max_row=d,min_col=a,max_col=c),cache.iter_rows(min_row=b,max_row=d,min_col=a,max_col=c)), b):
                values.append([{'cell': f'{sheet}!{get_column_letter(column)}{row_number}', 'value': cell.value, 'type': cell.data_type,
                                'cached_value': cc.value, 'cache_status': 'stored_unverified_not_recalculated',
                                'source_sha256': binding['source_sha256'],
                                'content_sha256': sha256(json.dumps(cell.value, default=str, ensure_ascii=False).encode()).hexdigest()} for column,(cell,cc) in enumerate(zip(row,cache_row),a)])
            return {**binding, 'sheet': sheet, 'hidden': ws.sheet_state != 'visible', 'range': address, 'cells': values}
        finally:
            book.close()
            cached.close()

    @document_tool
    def page_image(self, source, page, *, expected_sha256=None):
        _, binding = self._source(source, expected_sha256)
        raise ValueError('Local page rendering backend is not qualified in tools/v1; no image or OCR was fabricated')
