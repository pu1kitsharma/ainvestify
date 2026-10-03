"""Workbook reconciliation and model-authored findings. Synthetic workbooks only."""
import json
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from agents.analysis import workbook_reconciliation as module
from agents.analysis.workbook_reconciliation import (INSTRUCTION, SCOPE, TASK, analyze_workbook,
                                                     period_status, reconcile_workbook,
                                                     validate_findings, workbook_block)

AS_OF = '2026-10-03'


def evidence_packet(reconciled, as_of_date=AS_OF):
    return module.evidence_packet(reconciled, as_of_date)
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def workbook(sheets, cached, hidden=(), hidden_rows=(), calc=None):
    """A synthetic .xlsx. `cached` gives the stored result of each formula cell, as
    a spreadsheet application would have saved it; openpyxl itself stores none."""
    book = Workbook()
    book.remove(book.active)
    for name, cells in sheets.items():
        sheet = book.create_sheet(name)
        for address, value in cells.items():
            sheet[address] = value
            if isinstance(value, str) and value.startswith('=') and address in ('C9',):
                sheet[address].number_format = '0.0%'
        if name in hidden:
            sheet.sheet_state = 'hidden'
    for name, row in hidden_rows:
        book[name].row_dimensions[row].hidden = True
    buffer = BytesIO()
    book.save(buffer)
    names = list(sheets)
    source, output = ZipFile(BytesIO(buffer.getvalue())), BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.startswith('xl/worksheets/sheet'):
                sheet_name = names[int(info.filename.split('sheet')[-1].split('.')[0]) - 1]
                ET.register_namespace('', NS)
                tree = ET.fromstring(data)
                for cell in tree.iter(f'{{{NS}}}c'):
                    key = (sheet_name, cell.attrib['r'])
                    formula = cell.find(f'{{{NS}}}f')
                    if formula is None:
                        continue
                    for old in cell.findall(f'{{{NS}}}v'):
                        cell.remove(old)
                    if key in cached and cached[key] is not None:
                        ET.SubElement(cell, f'{{{NS}}}v').text = str(cached[key])
                    cell.attrib.pop('t', None)
                    if isinstance(cached.get(key), str):
                        # a stored error such as #DIV/0!, or a stored text result
                        cell.attrib['t'] = 'e' if cached[key].startswith('#') else 'str'
                data = ET.tostring(tree, xml_declaration=True, encoding='UTF-8')
            if info.filename == 'xl/workbook.xml' and calc:
                ET.register_namespace('', NS)
                tree = ET.fromstring(data)
                for old in tree.findall(f'{{{NS}}}calcPr'):
                    tree.remove(old)
                ET.SubElement(tree, f'{{{NS}}}calcPr', calc)
                data = ET.tostring(tree, xml_declaration=True, encoding='UTF-8')
            target.writestr(info, data)
    return output.getvalue()


MODEL = {
    'Summary': {'A1': 'Metric', 'B1': 'FY2025',
                'A2': 'Revenue', 'B2': '=Inputs!B2*Inputs!B3',
                'A3': 'Costs', 'B3': '=SUM(Inputs!B4:B5)',
                'A4': 'Operating result', 'B4': '=B2-B3',
                'A5': 'Margin', 'B5': '=ROUND(B4/B2,4)'},
    'Inputs': {'A1': 'Assumption', 'B1': 'FY2025',
               'A2': 'Units sold', 'B2': 1200, 'A3': 'Price per unit', 'B3': 50,
               'A4': 'Staff cost', 'B4': 30000, 'A5': 'Other cost', 'B5': 12000}}
CACHE = {('Summary', 'B2'): 60000, ('Summary', 'B3'): 42000, ('Summary', 'B4'): 18000,
         ('Summary', 'B5'): 0.3}


def statuses(content):
    result = reconcile_workbook(content)
    return {f'{sheet}!{cell}': state for (sheet, cell), state in result['status'].items()
            if result['cells'][(sheet, cell)]['is_formula']}


def test_formulas_that_recompute_to_their_stored_values_are_reconciled_with_lineage():
    content = workbook(MODEL, CACHE, hidden=['Inputs'])
    assert set(statuses(content).values()) == {'reconciled'}
    packet = evidence_packet(reconcile_workbook(content))
    by_cell = {f"{item['sheet']}!{item['cell']}": item for item in packet['evidence']}
    result = by_cell['Summary!B4']
    assert (result['value'], result['kind'], result['formula']) == ('18000', 'formula_result', '=B2-B3')
    assert (result['row_label'], result['column_label']) == ('Operating result', 'FY2025')
    assert result['reconciliation'] == 'recomputed_from_inputs_equals_stored_value'
    assert result['direct_precedents'] == ['Summary!B2', 'Summary!B3']
    # Its lineage reaches every input it rests on, and those inputs are on a hidden sheet.
    rests_on = {packet['evidence'][int(name[1:]) - 1]['cell'] + '@' +
                packet['evidence'][int(name[1:]) - 1]['sheet'] for name in result['precedent_evidence_ids']}
    assert rests_on == {'B2@Summary', 'B3@Summary', 'B2@Inputs', 'B3@Inputs', 'B4@Inputs', 'B5@Inputs'}
    assert result['rests_on_hidden_cells'] and not result['on_hidden_sheet_row_or_column']
    assert by_cell['Inputs!B2']['on_hidden_sheet_row_or_column']
    assert by_cell['Inputs!B2']['reconciliation'] == 'entered_value_not_a_formula'
    assert by_cell['Summary!B5']['value'] == '0.3'
    assert packet['coverage'] == {'formula_cells': 4, 'formulas_reconciled': 4,
        'formulas_excluded': 0, 'numeric_inputs': 4, 'admitted_but_not_in_packet': 0,
        'complete': True}
    assert packet['excluded_cells'] == {} and len(packet['workbook_sha256']) == 64
    # The packet itself says what it is: partial evidence, not a recalculation.
    assert {key: packet[key] for key in SCOPE} == SCOPE
    assert SCOPE['workbook_recalculation'] == 'not_performed'
    assert SCOPE['financial_validation'] == 'not_established'
    assert 'blocked' in SCOPE['production_financial_checkpoint']
    assert result['period_status'] == 'period_before_as_of_date'


@pytest.mark.parametrize('change, expected', [
    # A stale cache: the stored result no longer follows from the inputs.
    ({('Summary', 'B2'): 61000}, {'Summary!B2': 'cache_mismatch', 'Summary!B3': 'reconciled',
                                  'Summary!B4': 'unreconciled_precedent',
                                  'Summary!B5': 'unreconciled_precedent'}),
    ({('Summary', 'B3'): None}, {'Summary!B2': 'reconciled', 'Summary!B3': 'missing_cache',
                                 'Summary!B4': 'unreconciled_precedent',
                                 'Summary!B5': 'unreconciled_precedent'}),
    # Only the last cell is wrong: everything it rests on is still admitted.
    ({('Summary', 'B5'): 0.31}, {'Summary!B2': 'reconciled', 'Summary!B3': 'reconciled',
                                 'Summary!B4': 'reconciled', 'Summary!B5': 'cache_mismatch'}),
])
def test_unreconciled_numbers_and_everything_built_on_them_fail_closed(change, expected):
    content = workbook(MODEL, {**CACHE, **change})
    assert statuses(content) == expected
    packet = evidence_packet(reconcile_workbook(content))
    admitted = {f"{item['sheet']}!{item['cell']}" for item in packet['evidence']}
    excluded = {cell for cell, state in expected.items() if state != 'reconciled'}
    assert not admitted & excluded and packet['coverage']['complete'] is False
    assert {cell for cells in packet['excluded_cells'].values() for cell in cells} == excluded
    # The withheld numbers appear nowhere in what the model would be given.
    for (sheet, cell), value in change.items():
        if value is not None:
            assert str(value) not in json.dumps(packet['evidence'])
    # And the workbook as a whole is refused: one stale or missing cache means the
    # file was saved without recalculating, so no stored result is analysed.
    result, model, attempts = analyse(content, [])
    assert result['state'] == 'blocked' and result['reason'] == 'stale_or_missing_formula_cache'
    assert result['cells'] == sorted(cell for cell, state in expected.items()
                                     if state in ('cache_mismatch', 'missing_cache'))
    assert model.calls == 0 and attempts == [] and 'findings' not in result
    assert {key: result[key] for key in SCOPE} == SCOPE


@pytest.mark.parametrize('formula, cached, state', [
    ('=IF(B2>0,B2,0)', 5, 'unsupported_formula_syntax'),
    ('=IF(B2,B2,0)', 5, 'unsupported_function_or_name'),
    ('=VLOOKUP(B2,A1:B3,2,FALSE)', 5, 'unsupported_function_or_name'),
    ('=INDIRECT("B2")', 5, 'unsupported_formula_syntax'),
    ('=B2/B3', 5, 'division_by_zero'),
    ('=B2&"x"', 5, 'unsupported_formula_syntax'),
    ('=B2+A2', 5, 'non_numeric_operand'),
    ('=B2:B3', 5, 'range_used_as_single_value'),
    # A sheet that does not exist is #REF! in a spreadsheet, never an empty cell.
    ('=Missing!B2+1', 1, 'unknown_sheet_reference'),
    ("='No Such Sheet'!B1*B2", 35, 'unknown_sheet_reference'),
    ('=SUM(Missing!B2:B3)', 0, 'unknown_sheet_reference'),
    ('=B2+#REF!', 5, 'invalid_reference'),
    ('=XFE1+B2', 5, 'invalid_reference'),          # beyond the last column
    ('=B2+B1048577', 5, 'invalid_reference'),      # beyond the last row
    ('=B2+D4', 5, 'reconciled'),                   # an empty cell on a real sheet is zero
    ('=B2*2', 'ten', 'non_numeric_cache'),
    ('=SUM(B2:B3)+B2%', 5.05, 'reconciled'),
    ('=-(B2^2)+MAX(B2:B3,7)-MIN(B2,9)+ABS(-3)+AVERAGE(B2:B3)', -17.5, 'reconciled'),
    ('=-(B2^2)+MAX(B2:B3,7)-MIN(B2,9)+ABS(-3)+AVERAGE(B2:B3)', -15, 'cache_mismatch'),
    ('=ROUND(B2/3,2)', 1.67, 'reconciled'),
    ("='Other Sheet'!B1*B2", 35, 'reconciled'),
])
def test_only_a_closed_arithmetic_subset_is_recomputed(formula, cached, state):
    content = workbook({'Sheet': {'A2': 'Label', 'B2': 5, 'B3': 0, 'C9': formula},
                        'Other Sheet': {'B1': 7}}, {('Sheet', 'C9'): cached})
    assert statuses(content)['Sheet!C9'] == state


def test_circular_and_hidden_row_cases_are_explicit():
    content = workbook({'Sheet': {'A1': 1, 'B1': '=C1+A1', 'C1': '=B1+1', 'D1': '=A1*2'}},
                       {('Sheet', 'B1'): 3, ('Sheet', 'C1'): 4, ('Sheet', 'D1'): 2},
                       hidden_rows=[('Sheet', 1)])
    found = statuses(content)
    assert found['Sheet!D1'] == 'reconciled'
    assert {found['Sheet!B1'], found['Sheet!C1']} <= {'circular_reference', 'unreconciled_precedent'}
    assert 'circular_reference' in {found['Sheet!B1'], found['Sheet!C1']}
    packet = evidence_packet(reconcile_workbook(content))
    assert all(item['on_hidden_sheet_row_or_column'] for item in packet['evidence'])
    result, model, _ = analyse(content, [])
    assert result['state'] == 'blocked' and result['reason'] == 'source_workbook_formula_errors'
    assert model.calls == 0


def test_percent_format_and_float_noise_are_rendered_stably():
    content = workbook({'Sheet': {'A8': 'Growth', 'B8': 0.1, 'B9': 0.2, 'C9': '=B8+B9'}},
                       {('Sheet', 'C9'): 0.30000000000000004})
    item = next(item for item in evidence_packet(reconcile_workbook(content))['evidence']
                if item['cell'] == 'C9')
    assert item['value'] == '0.3' and item['display_percent'] == '30%'


# ---- model-authored findings -------------------------------------------------------------

class Scripted:
    name = 'offline-test-model'

    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), 0
        self.last_response_text, self.last_call = '', {'host': 'test-double'}

    def generate(self, instruction, evidence, schema):
        self.calls += 1
        self.seen = json.loads(evidence)
        self.last_response_text = json.dumps(self.outputs.pop(0))
        return schema.model_validate_json(self.last_response_text)


def analyse(content, outputs, attempts=None, budget=None):
    attempts = [] if attempts is None else attempts
    model = Scripted(outputs)
    budget = budget or PreparationBudget(105, max_calls=5, max_requests=7)
    with preparation_budget(budget):
        result = analyze_workbook(content, as_of_date=AS_OF, model=model, attempts=attempts,
                                  save=lambda: None, budget=budget)
    return result, model, attempts


def ids(content):
    packet = evidence_packet(reconcile_workbook(content))
    return {f"{item['sheet']}!{item['cell']}": item['id'] for item in packet['evidence']}


def answer(*findings):
    return {'findings': list(findings),
            'unknowns': ['Whether the entered inputs match accounting records.']}


def finding(statement, *evidence_ids, kind='reported_value'):
    return {'kind': kind, 'statement': statement, 'evidence_ids': list(evidence_ids)}


def test_model_findings_are_bound_to_cited_cells_and_recorded():
    content = workbook(MODEL, CACHE, hidden=['Inputs'])
    cell = ids(content)
    good = answer(
        finding('The Operating result for FY2025 is 18000, a formula result that rests on hidden '
                'input cells.', cell['Summary!B4']),
        finding('Revenue of 60000 recomputes from Units sold 1200 and Price per unit 50, which '
                'are entered on a hidden sheet.', cell['Summary!B2'], cell['Inputs!B2'],
                cell['Inputs!B3'], kind='calculation_check'))
    result, model, attempts = analyse(content, [good])
    assert result['state'] == 'analysed' and result['independent_review'] == 'pending'
    assert result['acceptance_scope'] == 'local_model_checks_only'
    assert [item['cells'] for item in result['findings']] == [
        ['Summary!B4'], ['Summary!B2', 'Inputs!B2', 'Inputs!B3']]
    assert all(item['rests_on_hidden_cells'] for item in result['findings'])
    # The statements are the model's own words, recorded with their raw response.
    assert result['findings'][0]['statement'] == good['findings'][0]['statement']
    row = attempts[0]
    assert (row['task'], row['instruction']) == (TASK, INSTRUCTION) and row['raw_response']
    assert row['input']['evidence_digest'] == result['evidence_digest']
    assert model.seen['workbook_sha256'] == result['workbook_sha256']
    # A later pass replays the saved response without a call.
    again, replay, _ = analyse(content, [], attempts=attempts)
    assert again == result and replay.calls == 0
    tampered = json.loads(json.dumps(attempts))
    tampered[0]['raw_response'] = json.dumps(answer(finding('x' * 40, cell['Summary!B4'])))
    with pytest.raises(ValueError, match='modified'):
        analyse(content, [], attempts=tampered)


@pytest.mark.parametrize('statement, cited, reason', [
    ('The Operating result for FY2025 is roughly 18500 on hidden inputs.', ['Summary!B4'],
     "numbers ['18500']"),
    # A real workbook number, but not from a cell this finding cites.
    ('The Operating result is 18000 against Revenue of 60000 on hidden inputs.', ['Summary!B4'],
     "numbers ['60000']"),
    ('The Operating result for FY2025 is 18000 and has been audited, on hidden inputs.',
     ['Summary!B4'], 'not an audited or verified figure'),
    ('The Operating result for FY2025 is 18000 according to the summary sheet.', ['Summary!B4'],
     'must say so'),
])
def test_untraceable_or_overclaimed_findings_are_rejected_with_feedback(statement, cited, reason):
    content = workbook(MODEL, CACHE, hidden=['Inputs'])
    cell = ids(content)
    bad = answer(finding(statement, *[cell[name] for name in cited]))
    good = answer(finding('The Operating result for FY2025 is 18000, resting on hidden input '
                          'cells.', cell['Summary!B4']))
    result, model, attempts = analyse(content, [bad, good])
    assert result['state'] == 'analysed' and result['response_id'] == attempts[1]['id']
    assert reason in attempts[0]['semantic_validation_error']
    assert attempts[1]['input']['previous_response_id'] == attempts[0]['id']
    assert reason in attempts[1]['input']['validation_issue']
    # Three rejected answers stop the analysis; software writes no finding of its own.
    result, model, attempts = analyse(content, [bad, bad, bad, good])
    assert result['state'] == 'blocked' and result['reason'] == 'findings_not_bound_to_evidence'
    assert model.calls == 3 and 'findings' not in result and len(result['response_ids']) == 3


def test_findings_cannot_cite_excluded_cells_or_unknown_ids():
    # Revenue uses a function outside the subset: it and what rests on it are excluded.
    partial = {**MODEL, 'Summary': {**MODEL['Summary'],
                                    'B2': '=IF(Inputs!B2,Inputs!B2*Inputs!B3,0)'}}
    content = workbook(partial, CACHE, hidden=['Inputs'])
    cell = ids(content)
    assert 'Summary!B2' not in cell and 'Summary!B4' not in cell
    made_up = answer(finding('Revenue for FY2025 is 60000 according to the summary sheet.', 'E99'))
    grounded = answer(finding('Costs for FY2025 are 42000, summed from entries on a hidden sheet; '
                              'Revenue could not be reconciled.', cell['Summary!B3'],
                              kind='risk'))
    result, model, attempts = analyse(content, [made_up, grounded])
    assert attempts[0]['failure_kind'] == 'schema_validation'      # E99 is not an offered id
    assert result['state'] == 'analysed'
    assert result['excluded_cells']['unsupported_function_or_name'] == ['Summary!B2']
    assert result['coverage']['complete'] is False
    assert model.seen['excluded_cells']['unreconciled_precedent'] == ['Summary!B4', 'Summary!B5']
    assert '60000' not in json.dumps(model.seen['evidence'])
    # Even a completed analysis is labelled partial evidence with review pending.
    assert {key: result[key] for key in SCOPE} == SCOPE
    assert result['independent_review'] == 'pending'
    assert model.seen['evidence_scope'] == 'partial_cell_level_arithmetic_subset'


def test_nothing_is_analysed_without_reconciled_formula_evidence_or_a_safe_workbook():
    inputs_only = workbook({'Sheet': {'A1': 'Cash', 'B1': 5}}, {})
    result, model, attempts = analyse(inputs_only, [])
    assert result['state'] == 'blocked' and result['reason'] == 'no_reconciled_formula_evidence'
    assert model.calls == 0 and attempts == []
    result = analyse(b'not a workbook', [])[0]
    assert (result['state'], result['reason']) == ('blocked', 'invalid_or_unsafe_workbook_package')
    assert result['independent_review'] == 'pending'


@pytest.mark.parametrize('formula, stale_cache, code', [
    ('=Missing!B2+1', 1, 'unknown_sheet_reference'),
    ('=A1+#REF!', 4, 'invalid_reference'),
    ('=A1/B1', 4, 'division_by_zero'),
    ('=XFE1+A1', 4, 'invalid_reference'),
])
def test_stale_number_cached_in_an_erroring_formula_never_yields_a_finding(formula, stale_cache, code):
    """The formula would be an error in a spreadsheet; its stored number is a stale cache."""
    content = workbook({**MODEL, 'Scratch': {'A1': 4, 'B1': 0, 'C1': formula}},
                       {**CACHE, ('Scratch', 'C1'): stale_cache})
    assert statuses(content)['Scratch!C1'] == code
    # The summary block reconciles on its own, and is still refused with the rest.
    assert statuses(content)['Summary!B4'] == 'reconciled'
    cell = 'E1'
    tempting = answer(finding('The Operating result for FY2025 is 18000 in the summary sheet.', cell))
    result, model, attempts = analyse(content, [tempting])
    assert result['state'] == 'blocked' and result['reason'] == 'source_workbook_formula_errors'
    assert code in result['codes'] and result['cells'] == ['Scratch!C1']
    assert model.calls == 0 and attempts == [] and 'findings' not in result


def test_formula_error_anywhere_blocks_the_whole_workbook():
    """A good summary block does not rescue a workbook with an error cell elsewhere."""
    content = workbook({**MODEL, 'Scratch': {'A1': 4, 'B1': 0, 'C1': '=A1/B1'}},
                       {**CACHE, ('Scratch', 'C1'): '#DIV/0!'})
    result, model, attempts = analyse(content, [])
    assert result['state'] == 'blocked' and result['reason'] == 'source_workbook_formula_errors'
    assert result['codes'] == ['division_by_zero', 'stored_cell_error'] and model.calls == 0
    assert result['cells'] == ['Scratch!C1']
    broken = workbook({**MODEL, 'Scratch': {'A1': 4, 'C1': '=A1+#REF!'}},
                      {**CACHE, ('Scratch', 'C1'): '#REF!'})
    assert analyse(broken, [])[0]['reason'] == 'source_workbook_formula_errors'


@pytest.mark.parametrize('calc, codes', [
    ({'iterate': '1'}, ['iterative_calculation']),
    ({'fullPrecision': '0'}, ['precision_as_displayed']),
    ({'iterate': 'true', 'fullPrecision': 'false'}, ['iterative_calculation', 'precision_as_displayed']),
])
def test_calculation_settings_outside_the_subset_block_the_workbook(calc, codes):
    content = workbook(MODEL, CACHE, calc=calc)
    result, model, _ = analyse(content, [])
    assert result['state'] == 'blocked' and result['reason'] == 'unsupported_calculation_semantics'
    assert result['codes'] == codes and model.calls == 0
    # Manual calculation mode alone is recorded, not refused: the caches still reconcile.
    manual = workbook(MODEL, CACHE, calc={'calcMode': 'manual'})
    reconciled = reconcile_workbook(manual)
    assert workbook_block(reconciled) is None
    assert evidence_packet(reconciled)['calculation_settings'] == {'calcMode': 'manual'}


def test_external_or_active_content_blocks_the_workbook():
    reconciled = reconcile_workbook(workbook(MODEL, CACHE))
    for code in ('external_dependency', 'unsupported_active_or_external_part'):
        flagged = {**reconciled, 'package_findings': [code]}
        assert workbook_block(flagged) == {'reason': 'external_or_active_workbook_content',
                                           'codes': [code]}


@pytest.mark.parametrize('labels, status', [
    (['Revenue', 'FY2025'], 'period_before_as_of_date'),
    (['Revenue', 'FY2026'], 'period_not_complete_at_as_of_date'),
    (['Revenue', 'FY2027'], 'period_after_as_of_date'),
    (['Revenue', '2027E'], 'labelled_projection'),
    (['Forecast revenue', 'FY2024'], 'labelled_projection'),
    (['Budget', None], 'labelled_projection'),
    (['Revenue', None], 'no_period_in_labels'),
    (['Units sold 1200', None], 'no_period_in_labels'),
])
def test_period_status_is_read_from_labels_against_the_as_of_date(labels, status):
    assert period_status(labels, AS_OF) == status


def test_future_or_incomplete_period_cannot_be_described_as_an_actual():
    future = {'Summary': {'A1': 'Metric', 'B1': 'FY2027', 'A2': 'Revenue',
                          'B2': '=Inputs!B2*Inputs!B3'},
              'Inputs': {'A2': 'Units sold', 'B2': 1200, 'A3': 'Price per unit', 'B3': 50}}
    content = workbook(future, {('Summary', 'B2'): 60000})
    cell = ids(content)
    as_actual = answer(finding('Revenue for FY2027 is 60000 according to the summary sheet.',
                               cell['Summary!B2']))
    claims_actual = answer(finding('Projected revenue for FY2027 of 60000 matches the actual '
                                   'results of the business.', cell['Summary!B2']))
    projected = answer(finding('Revenue for FY2027 is projected at 60000, which is not an actual '
                               'result at the as-of date.', cell['Summary!B2']))
    result, model, attempts = analyse(content, [as_actual, claims_actual, projected])
    assert result['state'] == 'analysed' and result['response_id'] == attempts[2]['id']
    assert 'never as an actual result' in attempts[0]['semantic_validation_error']
    assert 'no cited value has a reviewed actual origin' in attempts[1]['semantic_validation_error']
    assert result['findings'][0]['cites_projection_or_incomplete_period'] is True
    assert model.seen['evidence'][0]['period_status'] == 'period_after_as_of_date'
    assert model.seen['as_of_date'] == AS_OF
    # The same statement about a completed period needs no projection wording.
    past = {**future, 'Summary': {**future['Summary'], 'B1': 'FY2025'}}
    past_content = workbook(past, {('Summary', 'B2'): 60000})
    past_cell = ids(past_content)
    ok = answer(finding('Revenue for FY2025 is 60000 according to the summary sheet.',
                        past_cell['Summary!B2']))
    assert analyse(past_content, [ok])[0]['findings'][0]['cites_projection_or_incomplete_period'] is False


def test_bounded_pass_yields_and_resumes_without_repeating_work():
    content = workbook(MODEL, CACHE)
    cell = ids(content)
    good = answer(finding('The Operating result for FY2025 is 18000 in the summary sheet model.',
                          cell['Summary!B4']))
    spent = PreparationBudget(105, max_calls=1, max_requests=3)
    spent.calls = 1
    result, model, attempts = analyse(content, [good], budget=spent)
    assert result['state'] == 'needs_resume' and model.calls == 0 and attempts == []
    late = PreparationBudget(105, max_calls=5, max_requests=7)
    late.started -= 95
    assert analyse(content, [good], budget=late)[0]['state'] == 'needs_resume'
    result, model, attempts = analyse(content, [good])
    assert result['state'] == 'analysed' and model.calls == 1


@pytest.mark.parametrize('statement, accepted', [
    ('Actual revenue for FY2023 was 60000 according to the summary sheet.', False),
    ('The company achieved revenue of 60000 in FY2023 per the summary sheet.', False),
    ('Historical revenue for FY2023 is 60000 in the summary sheet model.', False),
    ('Revenue of 60000 was earned in FY2023 according to the summary sheet.', False),
    # Safe wording for a past period: what the workbook shows, or a projection.
    ('The workbook shows FY2023 revenue of 60000 in the summary sheet.', True),
    ('Revenue for FY2023 was projected at 60000 in the summary sheet.', True),
    ('The workbook lists FY2023 revenue of 60000; it is not established as an actual result.', True),
    ('It cannot be concluded whether the FY2023 figure of 60000 represents actual results or projections.', True),
    ('It is unclear if the FY2023 figure of 60000 is an actual result.', True),
    ('It is unclear if the FY2023 figure of 60000 is a projection. Actual revenue was 60000.', False),
])
def test_past_period_is_not_an_actual_without_a_reviewed_actual_origin(statement, accepted):
    """A FY2023 sheet may be a projection made years ago. Its date proves nothing."""
    past = {'Summary': {'A1': 'Metric', 'B1': 'FY2023', 'A2': 'Revenue',
                        'B2': '=Inputs!B2*Inputs!B3'},
            'Inputs': {'A2': 'Units sold', 'B2': 1200, 'A3': 'Price per unit', 'B3': 50}}
    content = workbook(past, {('Summary', 'B2'): 60000})
    packet = evidence_packet(reconcile_workbook(content))
    target = next(item for item in packet['evidence'] if item['cell'] == 'B2'
                  and item['sheet'] == 'Summary')
    assert target['period_status'] == 'period_before_as_of_date'
    assert target['actual_origin'] == 'not_established'
    assert packet['actual_results_origin'] == 'not_established'
    candidate = answer(finding(statement, target['id']))
    if accepted:
        assert validate_findings(candidate, packet)[0]['statement'] == statement
    else:
        with pytest.raises(ValueError, match='no cited value has a reviewed actual origin'):
            validate_findings(candidate, packet)


def test_cancelled_call_is_not_a_rejected_answer_and_a_retry_needs_enough_time():
    from agents.preparation.preparation_budget import PreparationBudgetExceeded
    content = workbook(MODEL, CACHE)
    cell = ids(content)
    good = answer(finding('The Operating result for FY2025 is 18000 in the summary sheet model.',
                          cell['Summary!B4']))

    class Cancelled(Scripted):
        def generate(self, instruction, evidence, schema):
            self.calls += 1
            raise PreparationBudgetExceeded('Preparation reached its time limit during inference.')

    attempts = []
    for expected in ('needs_resume', 'needs_resume'):
        budget = PreparationBudget(105, max_calls=5, max_requests=7)
        with preparation_budget(budget):
            result = analyze_workbook(content, as_of_date=AS_OF, model=Cancelled([]),
                                      attempts=attempts, save=lambda: None, budget=budget)
        assert result['state'] == expected
    # Two cancelled calls stop the analysis; neither counted as a model answer.
    result = analyse(content, [good], attempts=attempts)[0]
    assert result['state'] == 'blocked' and result['reason'] == 'findings_call_timed_out_twice'
    assert len(attempts) == 2 and not any(row['raw_response'] for row in attempts)

    # A retry is not started with less time left than the previous answer took.
    bad = answer(finding('The Operating result for FY2025 is roughly 18500 in the model.',
                         cell['Summary!B4']))
    result, model, attempts = analyse(content, [bad, good])
    assert result['state'] == 'analysed'
    attempts[0]['elapsed_seconds'] = 74.0
    del attempts[1]
    short = PreparationBudget(105, max_calls=5, max_requests=7)
    short.started -= 70                 # thirty-five seconds left, the answer took seventy-four
    result, model, _ = analyse(content, [good], attempts=attempts, budget=short)
    assert result['state'] == 'needs_resume' and model.calls == 0 and len(attempts) == 1
    assert analyse(content, [good], attempts=attempts)[0]['state'] == 'analysed'


def test_hidden_dependence_must_be_stated_once_and_open_questions_may_ask_about_audit():
    content = workbook(MODEL, CACHE, hidden=['Inputs'])
    cell = ids(content)
    packet = evidence_packet(reconcile_workbook(content))
    stated_once = answer(
        finding('Revenue for FY2025 is 60000, a formula result in the summary sheet.',
                cell['Summary!B2']),
        finding('The summary results rest on entries kept on a hidden sheet of the workbook.',
                cell['Summary!B4'], kind='risk'),
        finding('It is not established whether the FY2025 figures were ever audited.',
                cell['Summary!B4'], kind='open_question'))
    bound = validate_findings(stated_once, packet)
    assert all(item['rests_on_hidden_cells'] for item in bound)
    silent = answer(finding('Revenue for FY2025 is 60000, a formula result in the summary sheet.',
                            cell['Summary!B2']))
    with pytest.raises(ValueError, match='at least one finding that cites it must say so'):
        validate_findings(silent, packet)
    with pytest.raises(ValueError, match='not an audited or verified figure'):
        validate_findings(answer(finding('Revenue for FY2025 is 60000 and is fully recalculated, '
                                         'resting on hidden inputs.', cell['Summary!B2'])), packet)


def test_validate_findings_allows_label_numbers_and_percent_display():
    content = workbook({'Sheet': {'A8': 'Growth 2025', 'B8': 0.1, 'B9': 0.2, 'C9': '=B8+B9'}},
                       {('Sheet', 'C9'): 0.3})
    packet = evidence_packet(reconcile_workbook(content))
    target = next(item for item in packet['evidence'] if item['cell'] == 'C9')
    base = next(item for item in packet['evidence'] if item['cell'] == 'B8')
    ok = answer(finding('The formula result is 30% which is 0.3 as a fraction of the base.',
                        target['id']),
                finding('Growth 2025 is entered as 0.1 in the workbook inputs for the period.',
                        base['id']))
    assert base['period_status'] == 'period_before_as_of_date'
    assert len(validate_findings(ok, packet)) == 2
    with pytest.raises(ValueError, match=r"numbers \['2026'\]"):
        validate_findings(answer(finding('Growth 2026 is entered as 0.1 in the workbook inputs.',
                                         base['id'])), packet)
