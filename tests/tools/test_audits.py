import pytest

from agents.tools import audits, formula_engine as fx
from tests.tools.synthetic_books import build


def ev_of(sheets, **kw):
    return fx.evaluate_workbook_bytes(build(sheets, **kw))


def monthly_quarterly(bug=True):
    months = {}
    for i, col in enumerate('DEFGHIJKLMNO'):
        months[f'{col}1'] = f'M{i + 1}'
        months[f'{col}2'] = 10 + i          # revenue
        months[f'{col}3'] = 1 + i * 0.1     # cost A
        months[f'{col}4'] = 2.0             # SG&A
    months['A2'], months['A3'], months['A4'] = 'Revenue', 'Staff Cost', 'SG&A Cost'
    quarterly = {'A1': 'Qtrly', 'A2': 'Revenue', 'A3': 'Staff Costs', 'A4': 'SG&A Costs'}
    spans = ['D:F', 'G:I', 'J:L', 'M:O']
    for q, (qcol, span) in enumerate(zip('DEFG', spans)):
        a, b = span.split(':')
        for row in (2, 3):
            quarterly[f'{qcol}{row}'] = f"=SUM(Monthly!{a}{row}:{b}{row})"
        quarterly[f'{qcol}4'] = f"=Monthly!{'DEFG'[q]}4" if bug else f"=SUM(Monthly!{a}4:{b}4)"
    quarterly['H2'], quarterly['H3'], quarterly['H4'] = '=SUM(D2:G2)', '=SUM(D3:G3)', '=SUM(D4:G4)'
    return {'Monthly': months, 'Qtrly': quarterly}


def test_range_width_flags_single_month_pull_with_cells():
    ev = ev_of(monthly_quarterly(bug=True))
    # three aggregate rows are needed for a modal pattern: add two more
    report = audits.range_width_audit(ev, min_modal_rows=2)
    high = [f for f in report['findings'] if f['severity'] == 'high']
    assert len(high) == 1
    assert high[0]['sheet'] == 'Qtrly' and high[0]['row'] == 4
    assert high[0]['cells'] == ['Qtrly!D4', 'Qtrly!E4', 'Qtrly!F4', 'Qtrly!G4']
    assert (high[0]['row_stride'], high[0]['row_width'], high[0]['modal_stride'], high[0]['modal_width']) == (1, 1, 3, 3)


def test_range_width_clean_when_consistent():
    ev = ev_of(monthly_quarterly(bug=False))
    assert audits.range_width_audit(ev, min_modal_rows=2)['finding_count'] == 0


def test_reconcile_totals_finds_monthly_vs_quarterly_gap():
    ev = ev_of(monthly_quarterly(bug=True))
    members = [{'sheet': 'Monthly', 'first_col': 'D', 'last_col': 'O'}, {'sheet': 'Qtrly', 'first_col': 'D', 'last_col': 'G', 'total_col': 'H'}]
    report = audits.reconcile_totals(ev, members)
    assert [m['label'] for m in report['mismatches']] == ['SG&A Cost (INR)'] or [m['label'] for m in report['mismatches']] == ['SG&A Cost']
    bad = report['mismatches'][0]
    assert bad['spread'] == pytest.approx(24 - 8)
    assert bad['cells'] == ['Monthly!D4:O4', 'Qtrly!D4:G4']
    clean = audits.reconcile_totals(ev_of(monthly_quarterly(bug=False)), members)
    assert clean['mismatch_count'] == 0 and clean['compared_rows'] == 3


def test_reconcile_explicit_rows_and_ambiguous_labels():
    sheets = {'A': {'A1': 'Total', 'B1': 1, 'C1': 2, 'A2': 'Total', 'B2': 5, 'C2': 5}, 'B': {'A1': 'Total', 'B1': 3, 'A2': 'Total', 'B2': 9}}
    ev = ev_of(sheets)
    members = [{'sheet': 'A', 'first_col': 'B', 'last_col': 'C'}, {'sheet': 'B', 'first_col': 'B', 'last_col': 'B'}]
    report = audits.reconcile_totals(ev, members, explicit_rows=[{'name': 'first', 'rows': [1, 1]}, {'name': 'second', 'rows': [2, 2]}])
    assert report['ambiguous_repeated_labels'] and report['compared_rows'] == 2
    assert [m['label'] for m in report['mismatches']] == ['second']


def test_hidden_inventory_and_visible_readers():
    sheets = {'Vis': {'A1': '=Hid!A1+Calc!A2', 'A2': 1, 'A3': '=SUM(Calc!A1:A3)'}, 'Hid': {'A1': 5}, 'Calc': {'A1': 1, 'A2': 2, 'A3': 3, 'B1': 9}}
    ev = ev_of(sheets, hidden=('Hid',), hidden_rows={'Calc': (2,)}, hidden_cols={'Calc': ('B',)})
    report = audits.hidden_inventory(ev)
    assert [s['sheet'] for s in report['hidden_sheets']] == ['Hid']
    assert report['hidden_rows'][0]['rows'] == [2] and report['hidden_columns'][0]['columns'] == ['B']
    reasons = {r['reason'] for r in report['visible_cells_reading_hidden']}
    assert 'hidden sheet Hid' in reasons and 'hidden rows/columns in Calc' in reasons
    assert report['span_hidden_total'] == 1


def test_unit_scale_audit_flags_missing_conversion_and_accepts_constant():
    sheets = {'Mn': {'A1': 'INR Mn', 'A2': 'Revenue', 'B2': '=Raw!B2', 'A3': 'Cost', 'B3': '=Raw!B3/1000000', 'A4': 'Staff (INR K)', 'B4': 5},
              'Raw': {'A1': 'INR', 'A2': 'Revenue', 'B2': 2500000, 'A3': 'Cost', 'B3': 1000000}}
    ev = ev_of(sheets)
    report = audits.unit_scale_audit(ev)
    assert [m['cell'] for m in report['cross_sheet_unit_mismatch_without_conversion']] == ['Mn!B2']
    assert report['conversion_count'] == 1 and report['scale_constant_cell_count'] == 1
    assert any(u['sheet'] == 'Mn' for u in report['units_mixed_within_sheet'])
    assert audits.parse_unit('INR Mn')['scale'] == 1e6 and audits.parse_unit('(USD thousand)')['scale'] == 1e3
    assert audits.parse_unit('Revenue growth') is None and audits.parse_unit('M&A') is None


def test_driver_growth_double_count_candidate():
    cells = {'A1': 'Growth', 'A2': 'Customers', 'A3': 'Revenue per customer', 'A4': 'Revenue', 'A5': 'Orders', 'B2': 100, 'B3': 50}
    for i, col in enumerate('BCDEFG'):
        cells[f'{col}1'] = 0.1
    for prev, col in zip('BCDEF', 'CDEFG'):
        cells[f'{col}2'] = f'={prev}2*(1+{col}1)'
        cells[f'{col}3'] = f'={prev}3*(1+{col}1)'
        cells[f'{col}5'] = f'={prev}5+1'
    for col in 'BCDEFG':
        cells[f'{col}4'] = f'={col}2*{col}3'
    cells['B5'] = 1
    report = audits.driver_growth_double_count(ev_of({'M': cells}))
    assert report['finding_count'] == 1
    f = report['findings'][0]
    assert {r['row'] for r in f['driver_rows']} == {2, 3} and f['label_hint'] == 'price_like_and_count_like'
    assert f['combined_by_multiplication_in'][0]['cell'] == 'M!B4' and f['combination_count'] == 6
    # Independent growth series -> nothing
    cells2 = dict(cells)
    for prev, col in zip('BCDEF', 'CDEFG'):
        cells2[f'{col}3'] = f'={prev}3*(1+{col}6)'
        cells2[f'{col}6'] = 0.05
    assert audits.driver_growth_double_count(ev_of({'M': cells2}))['finding_count'] == 0


def balance_book(plug=True):
    cells = {'A1': 'Balance sheet', 'A2': 'Cash', 'A3': 'Receivables', 'A4': 'Total assets', 'A5': 'Debt', 'A6': 'Equity', 'A7': 'Total liabilities and equity'}
    for col in 'BCD':
        cells[f'{col}3'] = 40
        cells[f'{col}5'] = 30
        cells[f'{col}4'] = f'=SUM({col}2:{col}3)'
        cells[f'{col}7'] = f'=SUM({col}5:{col}6)'
        cells[f'{col}2'] = f'={col}7-{col}3' if plug else 70
        cells[f'{col}6'] = 80
    if plug:
        cells['A2'] = 'Cash'
    return {'Balance Sheet': cells}


def test_balance_sheet_plug_and_check():
    report = audits.balance_sheet_audit(ev_of(balance_book(plug=True)))['sheets'][0]
    assert report['cash_defined_by_subtraction'] and report['cash_defined_by_subtraction'][0]['cell'] == "Balance Sheet!B2"
    assert all(t['balanced'] for t in report['assets_vs_liabilities_equity'])
    clean = audits.balance_sheet_audit(ev_of(balance_book(plug=False)))['sheets'][0]
    assert clean['cash_defined_by_subtraction'] == [] and not clean['plug_candidates']
    # genuinely unbalanced independent figures are reported as a difference, not hidden
    unbalanced = balance_book(plug=False)
    unbalanced['Balance Sheet']['B2'] = 65
    row = audits.balance_sheet_audit(ev_of(unbalanced))['sheets'][0]['assets_vs_liabilities_equity'][0]
    assert not row['balanced'] and row['difference'] == pytest.approx(-5)


def test_balance_sheet_structural_plug_with_negation_and_sign_flips():
    cells = {'A2': 'Equity', 'A3': 'Fixed assets', 'A4': 'Other', 'A6': 'Net', 'B3': 10, 'B4': 5, 'B2': '=-(B3+B4)', 'B6': '=SUM(B2:B4)',
             'C3': 10, 'C4': -5, 'C2': '=-(C3+C4)', 'C6': '=SUM(C2:C4)'}
    report = audits.balance_sheet_audit(ev_of({'BS': cells}), sheet='BS')['sheets'][0]
    assert [p['plug_cell'] for p in report['plug_candidates']] == ['BS!B2', 'BS!C2']
    assert report['plug_candidates'][0]['balancing_total_cell'] == 'BS!B6'
    assert {s['label'] for s in report['sign_observations']} == {'Other'} or any(s['kind'] == 'sign_flips_across_periods' for s in report['sign_observations'])
    assert report['zero_sum_rows'][0]['row'] == 6


def test_error_propagation_roots_and_counts():
    ev = ev_of({'S': {'A1': '=1/0', 'A2': '=A1+1', 'A3': '=A2*2', 'B1': '=#REF!+1', 'B2': '=B1', 'C1': 3, 'C2': '=C1+1'}})
    report = audits.error_propagation_map(ev)
    roots = {r['root_cell']: r for r in report['root_errors']}
    assert set(roots) == {'S!A1', 'S!B1'}
    assert roots['S!A1']['downstream_error_cells'] == 2 and roots['S!A1']['origin'] == 'evaluated_error'
    assert roots['S!B1']['origin'] == 'literal_error_in_formula' and report['error_cells'] == 5


def test_hardcode_audit_groups_patterns_and_flags_overwrites():
    cells = {'A1': 'Cost', 'A2': 'Revenue'}
    for col in 'BCDEFG':
        cells[f'{col}1'] = f'={col}2*0.37+{col}3'
        cells[f'{col}2'] = 10
        cells[f'{col}3'] = f'={col}2*12'
    cells['A4'] = 'Margin'
    for col in 'BCDEF':
        cells[f'{col}4'] = f'={col}2-{col}3'
    cells['D4'] = 12345                      # overwritten formula
    cells['A5'] = 'Opening'
    cells['B5'] = '=-503470'
    report = audits.hardcode_audit(ev_of({'M': cells}))
    pattern = next(p for p in report['formula_patterns_with_embedded_literals'])
    assert pattern['literals'] == [0.37] and pattern['cell_count'] == 6
    assert report['literal_among_formulas_in_row'][0]['literal_cells'] == ['M!D4']
    assert [c['cell'] for c in report['pure_constant_formulas']] == ['M!B5']
