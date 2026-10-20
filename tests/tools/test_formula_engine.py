import math

import pytest

from agents.tools import formula_engine as fx
from tests.tools.synthetic_books import build


def run(cells, **kw):
    return fx.evaluate_workbook_bytes(build({'S': cells}, **kw))


def v(ev, address, sheet='S'):
    out = ev.value(sheet, address)
    return out.code if isinstance(out, fx.XlErr) else out


def test_arithmetic_precedence_and_percent():
    ev = run({'A1': '=2+3*4', 'A2': '=-2^2', 'A3': '=2^3^2', 'A4': '=10/4', 'A5': '=50%*200', 'A6': '=(1+2)*3', 'A7': '="a"&"b"&1.5',
              'A8': '=1<2', 'A9': '=2^-1', 'A10': '=1E3+.5'})
    assert [v(ev, f'A{i}') for i in range(1, 11)] == [14, 4, 64, 2.5, 100, 9, 'ab1.5', True, 0.5, 1000.5]


def test_errors_and_iferror():
    ev = run({'A1': '=1/0', 'A2': '=IFERROR(A1,-1)', 'A3': '=A1+1', 'A4': '=#REF!+1', 'A5': '="x"+1', 'A6': '=NOPEFUNC(1)',
              'A7': '=IFERROR(1/0,"n")', 'A8': '=(-8)^0.5', 'A9': '=0^0', 'A10': '=MATCH(9,B1:B3,0)', 'B1': 1, 'B2': 2, 'B3': 3,
              'A11': '=IFNA(A10,"none")', 'A12': '=NA()'})
    assert [v(ev, f'A{i}') for i in range(1, 13)] == ['#DIV/0!', -1, '#DIV/0!', '#REF!', '#VALUE!', '#UNSUPPORTED!', 'n', '#NUM!',
                                                      '#NUM!', '#N/A', 'none', '#N/A']
    summary = fx.evaluation_summary(ev)
    assert 'NOPEFUNC' in summary['unsupported_functions']
    assert summary['workbook_error_count'] >= 7


def test_aggregates_ignore_text_and_blank_in_ranges():
    ev = run({'A1': 1, 'A2': 'x', 'A3': 3, 'A4': True, 'B1': '=SUM(A1:A5)', 'B2': '=AVERAGE(A1:A5)', 'B3': '=MIN(A1:A5)', 'B4': '=MAX(A1:A5)',
              'B5': '=COUNT(A1:A5)', 'B6': '=COUNTA(A1:A5)', 'B7': '=SUM(A1,A3,"2",TRUE)', 'B8': '=PRODUCT(A1,A3)', 'B9': '=MEDIAN(A1,A3,10)',
              'B10': '=AVERAGE(C1:C3)', 'B11': '=MIN(C1:C3)'})
    assert [v(ev, f'B{i}') for i in range(1, 12)] == [4, 2, 1, 3, 2, 4, 7, 3, 3, '#DIV/0!', 0]


def test_logic_lookup_and_text():
    ev = run({'A1': 5, 'A2': 'b', 'B1': 'a', 'B2': 'b', 'B3': 'c', 'C1': 10, 'C2': 20, 'C3': 30,
              'D1': '=IF(A1>3,"hi","lo")', 'D2': '=AND(A1>1,A1<9)', 'D3': '=OR(A1<1,A1>9)', 'D4': '=NOT(TRUE)',
              'D5': '=INDEX(C1:C3,2)', 'D6': '=MATCH("c",B1:B3,0)', 'D7': '=VLOOKUP(A2,B1:C3,2,FALSE)', 'D8': '=VLOOKUP(25,C1:C3,1)',
              'D9': '=INDEX(B1:C3,3,2)', 'D10': '=MATCH(25,C1:C3,1)', 'D11': '=SUMPRODUCT(C1:C3,C1:C3)',
              'D12': '=SUMPRODUCT((C1:C3>10)*(C1:C3))', 'D13': '=ROUND(2.5,0)+ROUND(-2.5,0)+ROUND(1.2345,2)', 'D14': '=ABS(-3)',
              'D15': '=SUMIF(B1:B3,"b",C1:C3)', 'D16': '=COUNTIF(C1:C3,">=20")', 'D17': '=CHOOSE(2,"x","y","z")',
              'D18': '=LEFT("hello",2)&RIGHT("hello",2)&MID("hello",2,3)&LEN("abc")', 'D19': '=SUMIFS(C1:C3,B1:B3,"<>a",C1:C3,"<30")',
              'D20': '=ISNUMBER(A1)+ISTEXT(A2)+ISERROR(1/0)+ISBLANK(Z9)', 'D21': '=IF(A1>9,1)', 'D22': '=ROUNDDOWN(-2.9,0)+ROUNDUP(2.1,0)'})
    got = [v(ev, f'D{i}') for i in range(1, 23)]
    assert got == ['hi', True, False, False, 20, 3, 20, 20, 30, 2, 1400, 50, 1.23, 3, 20, 2, 'y',
                   'heloell3', 20, 4, False, 1]


def test_dates_text_and_financial_functions():
    ev = run({'A1': '=DATE(2023,1,31)', 'A2': '=EOMONTH(A1,1)', 'A3': '=EDATE(A1,1)', 'A4': '=YEAR(A2)*100+MONTH(A2)',
              'A5': '=TEXT(A2,"mmm-yy")', 'A6': '=TEXT(1234.567,"#,##0.00")', 'A7': '=TEXT(0.256,"0.0%")', 'A8': '=DAY(A2)',
              'A9': '=EOMONTH(DATE(2024,1,15),1)-DATE(2024,2,1)', 'A10': '=DATE(2023,14,1)',
              'B1': -100, 'B2': 60, 'B3': 60, 'C1': '=NPV(0.1,B2:B3)+B1', 'C2': '=IRR(B1:B3)', 'C3': '=PMT(0.01,12,1000)',
              'D1': '=DATE(2023,1,1)', 'D2': '=DATE(2024,1,1)', 'E1': -1000, 'E2': 1100, 'C4': '=XIRR(E1:E2,D1:D2)'})
    assert v(ev, 'A1') == 44957 and v(ev, 'A2') == 44985 and v(ev, 'A3') == 44985
    assert v(ev, 'A4') == 202302 and v(ev, 'A5') == 'Feb-23' and v(ev, 'A6') == '1,234.57' and v(ev, 'A7') == '25.6%' and v(ev, 'A8') == 28
    assert v(ev, 'A9') == 28 and v(ev, 'A10') == v(ev, 'A10')
    assert math.isclose(v(ev, 'C1'), 60 / 1.1 + 60 / 1.21 - 100)
    assert math.isclose(v(ev, 'C2'), 0.13066238629180749, rel_tol=1e-9)
    assert math.isclose(v(ev, 'C3'), -88.84878867834166, rel_tol=1e-9)
    assert math.isclose(v(ev, 'C4'), 0.1, rel_tol=1e-3)           # 1100/1000 over 365 days


def test_cross_sheet_names_absolute_ranges_and_tables():
    book = build({'Inputs': {'A1': 'Rate', 'B1': 0.2, 'A2': 'Col', 'A3': 10, 'A4': 20, 'F1': 'Unit', 'G1': 'Mult', 'F2': 'Mn', 'G2': 1e6, 'F3': 'K', 'G3': 1e3},
                  'Calc': {'A1': "=Inputs!$B$1*100", 'A2': '=SUM(Inputs!A3:A4)*Rate', 'A3': '=SUM(Colz)', 'A4': "=VLOOKUP(\"K\",Conv[#All],2,0)",
                           'A5': '=SUM(A:A)-A5+0', 'A6': "='Inputs'!B1+Missing!A1", 'A7': '=SUM(Conv[Mult])'}},
                 names={'Rate': 'Inputs!$B$1', 'Colz': 'Inputs!$A$3:$A$4'}, tables={'Inputs': ('Conv', 'F1:G3')})
    ev = fx.evaluate_workbook_bytes(book)
    assert [v(ev, f'A{i}', 'Calc') for i in (1, 2, 3, 4, 7)] == [20, 6, 30, 1000, 1001000]
    assert v(ev, 'A6', 'Calc') == '#REF!'
    # A5 reads its own column including itself
    assert any('Calc!A5' in c['cells'] for c in ev.circular)


def test_circular_reference_detection_is_exact_and_downstream_flagged():
    ev = run({'A1': '=B1+1', 'B1': '=C1+1', 'C1': '=A1+1', 'D1': '=A1*2', 'E1': '=E1', 'F1': '=1+2', 'G1': '=IFERROR(F1,0)'})
    assert len(ev.circular) == 2
    cycle = next(c for c in ev.circular if c['size'] == 3)
    assert cycle['cells'] == ['S!A1', 'S!B1', 'S!C1'] and cycle['path'][0] == cycle['path'][-1]
    assert v(ev, 'D1') == '#CIRC!' and v(ev, 'F1') == 3 and v(ev, 'G1') == 3
    assert fx.evaluation_summary(ev)['circular_references']


def test_deep_dependency_chain_is_iterative():
    cells = {'A1': 1}
    for i in range(2, 4000):
        cells[f'A{i}'] = f'=A{i - 1}+1'
    ev = run(cells)
    assert v(ev, 'A3999') == 3999


def with_caches(book, mapping):
    """Inject stored formula results: mapping {'<f>text</f>': value} (synthetic cache fixture)."""
    import zipfile
    from io import BytesIO
    zin = zipfile.ZipFile(BytesIO(book))
    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == 'xl/worksheets/sheet1.xml':
                for formula, value in mapping.items():
                    data = data.replace(f'<f>{formula}</f><v></v>'.encode(), f'<f>{formula}</f><v>{value}</v>'.encode())
            zout.writestr(item, data)
    return out.getvalue()


def test_cache_comparison_reports_mismatch_and_blocked():
    book = with_caches(build({'S': {'A1': 2, 'A2': '=A1*3', 'A3': '=OFFSET(A1,0,0)', 'A4': '=A1+1'}}), {'A1*3': 99, 'A1+1': 3})
    ev = fx.evaluate_workbook_bytes(book)
    report = fx.compare_with_cache(ev)
    assert report['with_cache'] == 2 and report['numeric_matches'] == 1
    assert report['mismatch_count'] == 1 and report['mismatches'][0]['cell'] == 'S!A2'
    assert report['mismatches'][0]['evaluated'] == 6 and report['mismatches'][0]['cached'] == 99
    assert 'OFFSET' in ev.unsupported


def test_budget_rejections():
    with pytest.raises(ValueError):
        fx.load_model(build({'S': {'A1': 1}}), max_bytes=10)
    with pytest.raises(ValueError):
        fx.load_model(build({'S': {f'A{i}': i for i in range(1, 50)}}), max_cells=10)
