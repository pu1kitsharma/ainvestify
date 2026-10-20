"""Private-reference checks. Auto-skipped when the confidential workbook is absent.

Assertions use only structure (cell addresses, counts, rates). No value, label text or
formula from the private file is stored in the repository.
"""
import os
from pathlib import Path

import pytest

from agents.tools import audits, formula_engine as fx, recalc

PATH = Path(os.environ.get('TOFFEE_PRIVATE_XLSX', '/Users/divyangmishra/Downloads/Toffee Projections Oct-22 to Sep-23 (INR Mn).xlsx'))
pytestmark = pytest.mark.skipif(not PATH.is_file(), reason='private reference workbook not present')


@pytest.fixture(scope='module')
def ev():
    return fx.evaluate_workbook_bytes(PATH.read_bytes())


def test_engine_reproduces_stored_numeric_caches(ev):
    report = fx.compare_with_cache(ev)
    assert report['numeric_comparable'] > 1000
    assert report['numeric_match_rate'] >= 0.99, report['mismatches'][:5]
    assert report['blocked_by_unsupported'] == 0 and not ev.unsupported


def test_range_width_audit_finds_quarterly_single_month_pull(ev):
    report = audits.range_width_audit(ev)
    high = [f for f in report['findings'] if f['severity'] == 'high']
    cells = {c for f in high for c in f['cells']}
    assert {f"Qtrly P&L WS!{c}{54}" for c in 'DEFG'} <= cells


def test_monthly_to_quarterly_total_gap_is_detected(ev):
    members = [{'sheet': 'SG&A WS', 'first_col': 'D', 'last_col': 'O'},
               {'sheet': 'Qtrly P&L WS', 'first_col': 'D', 'last_col': 'G', 'total_col': 'H'}]
    report = audits.reconcile_totals(ev, members)
    assert report['mismatch_count'] == 1 and report['mismatches'][0]['spread'] > 0
    assert report['mismatches'][0]['cells'] == ['SG&A WS!D33:O33', 'Qtrly P&L WS!D54:G54']


def test_structural_audits_observe_known_features(ev):
    hidden = audits.hidden_inventory(ev)
    assert {s['sheet'] for s in hidden['hidden_sheets']} >= {'BalanceSheet', 'CFS'}
    bs = audits.balance_sheet_audit(ev)['sheets'][0]
    assert bs['sheet'] == 'BalanceSheet' and bs['plug_candidate_count'] >= 1
    errors = audits.error_propagation_map(ev)
    assert errors['root_count'] >= 1 and errors['root_errors'][0]['in_hidden_sheet']
    units = audits.unit_scale_audit(ev)
    assert units['mismatch_count'] >= 1 and units['scale_constant_cell_count'] >= 1
    assert audits.hardcode_audit(ev)['pure_constant_formula_count'] >= 1


def test_libreoffice_parity_on_private_reference():
    available, reason = recalc.availability()
    if not available:
        pytest.skip(reason)
    report = recalc.compare_libreoffice_to_engine(PATH.read_bytes(), timeout=180, allow_finding_codes=('unsupported_or_unknown_reference',))
    assert report['status'] == 'compared'
    assert report['agreement'] >= 0.99
