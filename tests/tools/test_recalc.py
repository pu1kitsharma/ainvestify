import pytest

from agents.tools import formula_engine as fx, recalc
from tests.tools.synthetic_books import build

available, reason = recalc.availability()
needs_office = pytest.mark.skipif(not available, reason=f'isolated LibreOffice unavailable: {reason}')


def test_unavailable_isolation_is_mandatory_unrun_not_pass(monkeypatch):
    monkeypatch.setattr(recalc, 'availability', lambda: (False, 'private_process_isolation_unavailable'))
    report = recalc.compare_libreoffice_to_engine(build({'S': {'A1': 1, 'A2': '=A1+1'}}))
    assert report['status'] == 'UNRUN' and report['mandatory_unrun'] is True and report['passed'] is False
    assert 'compared_cells' not in report


def test_run_private_failure_is_unrun(monkeypatch):
    monkeypatch.setattr(recalc, 'availability', lambda: (True, 'available'))
    import delivery.isolation as isolation

    def refuse(*a, **k):
        raise RuntimeError('private_process_isolation_unavailable')
    monkeypatch.setattr(isolation, 'run_private', refuse)
    assert recalc.recalculate_with_libreoffice(build({'S': {'A1': 1}}))['status'] == 'UNRUN'


def test_timeout_and_oversize_fail_closed(monkeypatch):
    monkeypatch.setattr(recalc, 'availability', lambda: (True, 'available'))
    import delivery.isolation as isolation

    def slow(*a, **k):
        raise TimeoutError('private_worker_timeout')
    monkeypatch.setattr(isolation, 'run_private', slow)
    assert recalc.recalculate_with_libreoffice(build({'S': {'A1': 1}}))['reason'] == 'libreoffice_timeout'
    assert recalc.recalculate_with_libreoffice(build({'S': {'A1': 1}}), max_input_bytes=10)['reason'] == 'input_exceeds_byte_budget'


SYNTHETIC = {
    'Inputs': {'A1': 'Rate', 'B1': 0.08, 'A2': 'Flows', 'B2': -1000, 'C2': 300, 'D2': 400, 'E2': 500, 'F2': 300, 'A3': 'Start', 'B3': '=DATE(2024,1,31)'},
    'Calc': {'A1': '=NPV(Inputs!B1,Inputs!C2:F2)+Inputs!B2', 'A2': '=IRR(Inputs!B2:F2)', 'A3': '=EOMONTH(Inputs!B3,2)', 'A4': '=IF(A1>0,"pos","neg")',
             'A5': '=SUMPRODUCT(Inputs!B2:F2,Inputs!B2:F2)', 'A6': '=INDEX(Inputs!B2:F2,3)&MATCH(400,Inputs!B2:F2,0)', 'A7': '=1/0', 'A8': '=IFERROR(A7,-1)',
             'A9': '=ROUND(2.675,2)+ROUND(-1.5,0)', 'A10': '=VLOOKUP(400,Inputs!C2:D2,1,FALSE)', 'A11': '=TEXT(A3,"yyyy-mm-dd")', 'A12': '=B1+C1', 'A13': '=A12+1',
             'B1': '=C1', 'C1': 1},
}


@needs_office
def test_libreoffice_agrees_with_engine_on_synthetic_workbook():
    report = recalc.compare_libreoffice_to_engine(build(SYNTHETIC), timeout=120)
    assert report['status'] == 'compared', report
    assert report['mismatches'] == [] and report['passed'] and report['agreement'] == 1.0
    assert any(e['cell'] == 'Calc!A7' for e in report['libreoffice_error_cells'])


@needs_office
def test_engine_matches_libreoffice_written_caches():
    run = recalc.recalculate_with_libreoffice(build(SYNTHETIC), timeout=120)
    assert run['status'] == 'recalculated'
    ev = fx.evaluate_workbook_bytes(run['content'])
    stored = fx.compare_with_cache(ev)
    assert stored['with_cache'] == len(ev.values) and stored['mismatch_count'] == 0 and stored['numeric_match_rate'] == 1.0


@needs_office
def test_active_content_is_refused_before_launch(tmp_path):
    from openpyxl import Workbook
    from io import BytesIO
    book = Workbook()
    book.active['A1'] = '=WEBSERVICE("http://example.invalid")'
    out = BytesIO()
    book.save(out)
    report = recalc.recalculate_with_libreoffice(out.getvalue())
    assert report['status'] in ('failed',) or report.get('reason')
