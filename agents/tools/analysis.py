"""Analyst audit tools exposed through tools/v1: evaluate, audit and bind. Observation only.

Every method reads a bounded, hash-pinned XLSX/PPTX/DOCX inside the caller-provisioned
sandbox and returns observations. None writes into a workbook, repairs a formula, or
chooses company content; a clean result means the checks saw nothing, not that the
model is right. Office recalculation is reported UNRUN, never passed, when the private
process boundary is unavailable.
"""
from __future__ import annotations

from functools import wraps
from hashlib import sha256
import json
from pathlib import Path

from openpyxl.utils.cell import range_boundaries

from . import audits, claim_binder, formula_engine as fx, recalc
from .contracts import observation, json_safe


def analysis_tool(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        errors = []
        try:
            result = method(self, *args, **kwargs)
            errors = result.pop('_errors', []) if isinstance(result, dict) else []
            text = json.dumps(json_safe(result), default=str, allow_nan=False)
            if len(text) > self.max_output_chars:
                raise ValueError('Output exceeds observation budget; request a narrower scope')
            response = observation('analysis.' + method.__name__, json.loads(text), errors)
        except Exception as exc:
            response = observation('analysis.' + method.__name__, errors=[{'code': type(exc).__name__, 'message': str(exc)}])
        try:
            log = self._path('analysis.trajectory.jsonl')
            with log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(json_safe({'call': {'tool': 'analysis.' + method.__name__, 'args': args, 'kwargs': kwargs},
                                                   'observation': response}), default=str, allow_nan=False) + '\n')
        except Exception as exc:
            response['ok'] = False
            response['errors'].append({'code': 'TrajectoryWriteFailed', 'message': str(exc)})
        return response
    return call


class AnalysisTools:
    def __init__(self, sandbox_root, *, max_bytes=20_000_000, max_output_chars=200_000, max_cells=200_000):
        self.root = Path(sandbox_root).resolve(strict=True)
        self.max_bytes, self.max_output_chars, self.max_cells = max_bytes, max_output_chars, max_cells
        self.pins, self._cache = {}, {}

    def _path(self, source):
        result = (self.root / source).resolve()
        if not result.is_relative_to(self.root):
            raise ValueError('Source escapes private analysis sandbox')
        return result

    def _bytes(self, source, expected_sha256=None):
        path = self._path(source)
        if path.stat().st_size > self.max_bytes:
            raise ValueError('Source exceeds byte budget')
        with path.open('rb') as stream:
            content = stream.read(self.max_bytes + 1)
        if not content or len(content) > self.max_bytes:
            raise ValueError('Source empty or exceeds byte budget')
        digest = sha256(content).hexdigest()
        pinned = self.pins.get(str(path))
        if (expected_sha256 is not None and expected_sha256 != digest) or (pinned is not None and pinned != digest):
            raise ValueError('Source hash changed or expected bytes mismatch')
        self.pins[str(path)] = digest
        return content, digest

    def _evaluation(self, source, expected_sha256=None):
        content, digest = self._bytes(source, expected_sha256)
        if Path(source).suffix.lower() != '.xlsx':
            raise ValueError('Only macro-free .xlsx workbooks are supported')
        if digest not in self._cache:
            self._cache[digest] = fx.evaluate_workbook_bytes(content, max_bytes=self.max_bytes, max_cells=self.max_cells)
        return self._cache[digest], digest, content

    # ---------------------------------------------------------------- engine
    @analysis_tool
    def evaluate(self, source, *, cells=None, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        result = {'source_sha256': digest, **fx.evaluation_summary(ev), 'values': []}
        for item in cells or []:
            r1, c1, r2, c2 = _bounds(item['address'])
            sd = ev.model.sheet(item['sheet'])
            if sd is None:
                raise ValueError(f"Unknown sheet {item['sheet']}")
            if (r2 - r1 + 1) * (c2 - c1 + 1) > 400:
                raise ValueError('Request at most 400 cells per evaluate call')
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    v = ev.cell_value(sd.name, r, c)
                    result['values'].append({'cell': f'{sd.name}!{fx.a1(r, c)}', 'value': v.code if isinstance(v, fx.XlErr) else v,
                                             'formula': sd.formulas.get((r, c))})
        return result

    @analysis_tool
    def compare_cache(self, source, *, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **fx.compare_with_cache(ev),
                'note': 'stored caches are unverified observations; a match shows the evaluator reproduces the saved numbers'}

    @analysis_tool
    def libreoffice_recalc(self, source, *, timeout_seconds=90, expected_sha256=None):
        content, digest = self._bytes(source, expected_sha256)
        report = recalc.compare_libreoffice_to_engine(content, timeout=min(max(int(timeout_seconds), 10), 300),
                                                      max_input_bytes=self.max_bytes, max_cells=self.max_cells)
        errors = []
        if report.get('status') == 'UNRUN':
            errors.append({'code': 'UNRUN', 'message': 'Mandatory Office recalculation did not run: ' + report['reason']})
        elif report.get('status') != 'compared':
            errors.append({'code': 'RecalcFailed', 'message': str(report.get('reason'))})
        elif not report['passed']:
            errors.append({'code': 'EngineMismatch', 'message': f"{report['mismatch_count']} cell(s) differ between the evaluator and LibreOffice"})
        return {'source_sha256': digest, **report, '_errors': errors}

    # ---------------------------------------------------------------- audits
    @analysis_tool
    def audit_hidden(self, source, *, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **audits.hidden_inventory(ev)}

    @analysis_tool
    def audit_range_width(self, source, *, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **audits.range_width_audit(ev)}

    @analysis_tool
    def audit_units(self, source, *, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **audits.unit_scale_audit(ev)}

    @analysis_tool
    def audit_driver_growth(self, source, *, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **audits.driver_growth_double_count(ev)}

    @analysis_tool
    def audit_balance_sheet(self, source, *, sheet=None, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **audits.balance_sheet_audit(ev, sheet=sheet)}

    @analysis_tool
    def audit_errors(self, source, *, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **audits.error_propagation_map(ev)}

    @analysis_tool
    def audit_hardcodes(self, source, *, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **audits.hardcode_audit(ev)}

    @analysis_tool
    def audit_reconcile_totals(self, source, members, *, explicit_rows=None, expected_sha256=None):
        ev, digest, _ = self._evaluation(source, expected_sha256)
        return {'source_sha256': digest, **audits.reconcile_totals(ev, members, explicit_rows=explicit_rows)}

    # ---------------------------------------------------------------- claims
    def _cells_table(self, cells, workbook, ranges, expected_workbook_sha256):
        table = [dict(c) for c in (cells or [])]
        if workbook:
            ev, digest, _ = self._evaluation(workbook, expected_workbook_sha256)
            sheet_units = {}
            for item in ranges or []:
                sd = ev.model.sheet(item['sheet'])
                if sd is None:
                    raise ValueError(f"Unknown sheet {item['sheet']}")
                if sd.name not in sheet_units:
                    sheet_units[sd.name] = audits._sheet_unit(ev, sd)[0]
                r1, c1, r2, c2 = _bounds(item['address'])
                if (r2 - r1 + 1) * (c2 - c1 + 1) > 2000:
                    raise ValueError('Request at most 2000 cells per range')
                for r in range(r1, r2 + 1):
                    unit, _where = audits._row_unit(ev, sd, r, sheet_units[sd.name])
                    label = audits.row_label(ev, sd, r)
                    for c in range(c1, c2 + 1):
                        v = ev.cell_value(sd.name, r, c)
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            entry = {'ref': f'{sd.name}!{fx.a1(r, c)}', 'value': float(v), 'label': label,
                                     'unit': item.get('unit') or (unit['token'] if unit else None), 'workbook_sha256': digest}
                            if item.get('kind'):
                                entry['kind'] = item['kind']
                            table.append(entry)
        if not table:
            raise ValueError('A cells table or workbook ranges are required')
        return table

    @analysis_tool
    def claims_bind(self, text, *, cells=None, workbook=None, ranges=None, ignore_numbers=None, expected_workbook_sha256=None):
        table = self._cells_table(cells, workbook, ranges, expected_workbook_sha256)
        report = claim_binder.bind_claims(text, table, ignore_numbers=ignore_numbers or ())
        report['claims'] = report['claims'][:300]
        return {**report, 'cells_supplied': len(table)}

    @analysis_tool
    def claims_bind_document(self, source, *, cells=None, workbook=None, ranges=None, ignore_numbers=None,
                             expected_sha256=None, expected_workbook_sha256=None):
        content, digest = self._bytes(source, expected_sha256)
        table = self._cells_table(cells, workbook, ranges, expected_workbook_sha256)
        report = claim_binder.bind_document(content, Path(source).suffix, table, ignore_numbers=ignore_numbers or ())
        return {'source_sha256': digest, **report, 'cells_supplied': len(table)}

    @analysis_tool
    def chart_agreement(self, source, workbook, *, bindings=None, display_decimals=None, expected_sha256=None,
                        expected_workbook_sha256=None):
        content, digest = self._bytes(source, expected_sha256)
        if Path(source).suffix.lower() != '.pptx':
            raise ValueError('Native chart agreement requires a PPTX')
        ev, wdigest, _ = self._evaluation(workbook, expected_workbook_sha256)
        report = claim_binder.chart_workbook_agreement(content, ev, bindings=bindings, display_decimals=display_decimals)
        return {'source_sha256': digest, 'workbook_sha256': wdigest, **report}


def _bounds(address):
    bounds = range_boundaries(address.replace('$', ''))
    if None in bounds:
        raise ValueError('Invalid A1 address')
    c1, r1, c2, r2 = bounds
    return r1, c1, r2, c2
