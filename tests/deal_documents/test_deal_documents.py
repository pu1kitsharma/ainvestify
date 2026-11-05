"""Offline checks for the code-owned guarantees of the deal-documents workflow (synthetic data only)."""
import json
from pathlib import Path

import pytest

from delivery.deal_documents import facts as F
from delivery.deal_documents.memo import SECTIONS, banned_in, compute, validate_section
from delivery.deal_documents.sources import Unit
from delivery.deal_documents.tables import detect_tables

PAGE = """                              6
   USD Mn | Q1-FY22 | Q2-FY22 | FY22
                 USD Mn | OND | 22 | JFM 23
   Revenue | 0.06 | 0.27 | 1.46
                 Revenue | 2.33 | 2.98
   Product A | 0.05 | 0.16 | 0.69
                 Product A | 0.43 | 0.50
   EBITDA | (0.53) | (0.71) | (2.94)
                 EBITDA | (0.38) | (0.25)
1 USD = 75 INR"""


def test_side_by_side_tables_are_separated_by_indentation():
    tables, other = detect_tables(PAGE, 'X-p6')
    assert [len(t.rows) for t in tables] == [3, 3]
    assert tables[0].rows[0].values == ['0.06', '0.27', '1.46'] and tables[1].rows[0].values == ['2.33', '2.98']
    assert tables[0].rows[2].values[0] == '(0.53)'
    assert '1 USD = 75 INR' in other and all('Revenue' not in line for line in other)


def test_two_tables_sharing_one_line_are_split_into_rows():
    text = '\n'.join(['   Alpha | Tractor | Dec-21 Live | 0.34 | 0.93 | Beta | Cycle | 2018 Live | 0.07 | 0.27',
                      '   Gamma | Bus | Feb-22 Live | 2.67 | 6.67 | Delta | Pet | Oct-21 Live | 0.03 | 0.07'])
    tables, _ = detect_tables(text, 'X-p4')
    assert [[r.label for r in t.rows] for t in tables] == [['Alpha Tractor Dec-21 Live', 'Gamma Bus Feb-22 Live'],
                                                           ['Beta Cycle 2018 Live', 'Delta Pet Oct-21 Live']]


def _unit():
    return Unit('X-p1', 'deck.pdf', 'page 1', {'text': 'Equity Raised | 580.47 | 8.29\n10k plus channel partners at POS'})


def test_fact_values_must_appear_in_cited_block():
    unit = _unit()
    good = F._fact('X-p1.1', unit, 'cap_table_funding', 'historical', 'Equity raised', '', '', '580.47', 'INR Mn', 'text', '')
    bad = F._fact('X-p1.2', unit, 'cap_table_funding', 'historical', 'Equity raised', '', '', '580.5', 'INR Mn', 'text', '')
    assert F._check_fact(good, unit, '') is None
    assert F._check_fact(bad, unit, '') == 'value does not appear in the cited block'


def test_values_written_out_from_printed_suffixes_are_accepted():
    unit = Unit('X-p3', 'intro.pdf', 'page 3', {'text': '500k Policies | INR 1 Bn TAM | USD 3.5k ARPU'})
    for value in ('500000', '1000', '3500'):
        fact = F._fact('X-p3.1', unit, 'product', 'historical', 'm', '', '', value, '', 'text', '')
        assert F._check_fact(fact, unit, '') is None, value
    wrong = F._fact('X-p3.2', unit, 'product', 'historical', 'm', '', '', '600000', '', 'text', '')
    assert F._check_fact(wrong, unit, '') == 'value does not appear in the cited block'


def test_wrong_block_citation_is_corrected_and_ranges_need_both_ends():
    unit = Unit('X-p4', 'deck.pdf', 'page 4', {'text': 'Purpose Built for POS', 'ocr': 'Dengue Insurance 682 per year; dealers sell 250-300 cycles'},
                {'ocr'})
    fact = F._fact('X-p4.1', unit, 'unit_economics', 'company_claim', 'Premium', 'Dengue', '', '682', 'INR', 'text', '')
    assert F._check_fact(fact, unit, '') is None and fact['block'] == 'ocr' and fact['ocr_only']
    ranged = F._fact('X-p4.2', unit, 'business_model', 'company_claim', 'Cycles', '', '', '250-300', '', 'ocr', '')
    assert F._check_fact(ranged, unit, '') is None
    wrong = F._fact('X-p4.3', unit, 'business_model', 'company_claim', 'Cycles', '', '', '250-400', '', 'ocr', '')
    assert F._check_fact(wrong, unit, '') == 'value does not appear in the cited block'


def test_non_numeric_facts_must_be_grounded_and_numbers_in_detail_on_page():
    unit = _unit()
    grounded = F._fact('X-p1.3', unit, 'distribution', 'company_claim', 'Partners', '', '', '', '', 'text', '')
    assert F._check_fact(grounded, unit, 'more than 10k channel partners at POS') is None
    assert F._check_fact(grounded, unit, 'channel partners award 2023') == '2023 in period/detail is not on this page'
    assert F._check_fact(grounded, unit, 'award winning insurtech platform') == 'detail is not grounded in the cited block'


def _check(**fields):
    base = {'type': '', 'question': 'q', 'a': '', 'b': '', 'rate': '', 'direction': '', 'total': '', 'components': [],
            'minus': [], 'why_it_matters': ''}
    return {**base, **fields}


def test_typed_checks_are_computed_by_code_with_rounding_tolerance():
    index = {'inr': {'value': '580.47'}, 'usd': {'value': '8.29'}, 'fx': {'value': '75'},
             'a': {'value': '0.10'}, 'b': {'value': '0.12'}, 'c': {'value': '0.38'}, 'total': {'value': '0.61'},
             'rev': {'value': '0.73'}, 'gwp': {'value': '0.20'}}
    conversion = F._evaluate(_check(type='conversion', a='inr', b='usd', rate='fx', direction='divide'), index)
    assert conversion['status'] == 'inconsistent' and conversion['left_value'] == pytest.approx(7.7396, abs=1e-3)
    rounding = F._evaluate(_check(type='components_sum', total='total', components=['a', 'b', 'c']), index)
    assert rounding['status'] == 'consistent'  # 0.60 vs 0.61 is within printed rounding
    ratio = F._evaluate(_check(type='ratio_view', a='rev', b='gwp'), index)
    assert ratio['status'] == 'reported' and ratio['ratio'] == 3.65
    assert F._evaluate(_check(type='conversion', a='inr', b='usd'), index)['status'] == 'not_computable'


def test_conversion_uses_the_single_stated_exchange_rate_when_the_model_omits_it():
    index = {'usd': {'value': '45.45'}, 'inr': {'value': '3408.38'},
             'fx': {'value': '75', 'basis': 'definition', 'metric': 'Exchange rate', 'unit': 'INR/USD', 'statement': '1 USD = 75 INR'}}
    result = F._evaluate(_check(type='conversion', a='inr', b='usd'), index)
    assert result['status'] == 'consistent' and result['rate_inferred_by_code'] == 'fx'
    index['fx2'] = {'value': '70', 'basis': 'definition', 'metric': 'Exchange rate', 'statement': 'rate'}
    assert F._evaluate(_check(type='conversion', a='inr', b='usd'), index)['status'] == 'not_computable'


def test_same_value_in_two_currencies_is_retried_at_the_stated_rate():
    index = {'usd': {'value': '(0.73)'}, 'inr': {'value': '-54.40'},
             'fx': {'value': '75', 'basis': 'definition', 'metric': 'Exchange rate', 'statement': '1 USD = 75 INR'}}
    result = F._evaluate(_check(type='same_value', a='inr', b='usd'), index)
    assert result['status'] == 'consistent' and result['rate_inferred_by_code'] == 'fx'


def test_shareholding_percentages_are_checked_to_sum_to_one_hundred():
    holders = [('a', '18.23'), ('b', '18.23'), ('c', '63.54')]
    facts = [{'id': f'X-p8.{i}', 'source': 'X-p8', 'metric': 'Shareholding', 'segment': name, 'unit': '%', 'value': value}
             for i, (name, value) in enumerate(holders, 1)]
    checks = F.table_checks(facts)
    assert len(checks) == 1 and checks[0]['status'] == 'consistent'


def test_table_segments_are_checked_against_totals_without_the_model():
    def cell(row, segment, value):
        return {'id': f'X-p6.T1.r{row}c1', 'metric': 'Revenue', 'segment': segment, 'period': 'Q1', 'value': value,
                'table': {'id': 'X-p6.T1'}}
    checks = F.table_checks([cell(1, 'Total', '1.00'), cell(2, 'A', '0.40'), cell(3, 'B', '0.40')])
    assert len(checks) == 1 and checks[0]['status'] == 'inconsistent'


def _fact(fact_id, metric, period, value, basis='historical', unit='USD Mn', segment='', document='deck'):
    statement = f'{metric}' + (f' — {segment}' if segment else '') + (f' — {period}' if period else '') + f': {value} {unit}'
    return {'id': fact_id, 'metric': metric, 'segment': segment, 'period': period, 'value': value, 'unit': unit,
            'basis': basis, 'statement': statement, 'document': document}


REVENUE = {'f1': _fact('f1', 'Revenue', 'Q2-FY22', '0.27'), 'f2': _fact('f2', 'Revenue', 'Q4-FY22', '0.73'),
           'fy': _fact('fy', 'Revenue', 'FY22', '1.46'), 'prem': _fact('prem', 'Gross premium', 'Q4-FY22', '0.50'),
           'p23': _fact('p23', 'Revenue', 'FY23', '9.80', basis='projection'),
           'rr': _fact('rr', 'ARR - Revenue', 'FY23 Exit Run Rate', '13.18', basis='projection'),
           'tam': _fact('tam', 'TAM', '', '2.7', basis='third_party', unit='USD Bn')}


def _calc(calc_id, kind, a='', b='', parts=(), rate='', decimals=1):
    return {'id': calc_id, 'kind': kind, 'a': a, 'b': b, 'parts': list(parts), 'rate': rate, 'decimals': decimals}


def _para(text, cites):
    return {'kind': 'evidence', 'text': text, 'cites': [{'id': c, 'says': REVENUE[c]['value']} for c in cites]}


def test_memo_numbers_must_come_from_cited_facts_or_declared_calculations():
    from delivery.deal_documents.memo import finish_section
    section = {'key': 'historical', 'title': 'Historical', 'words': 34}
    assert compute(_calc('c1', 'multiple', 'f1', 'f2'), REVENUE)['text'] == '2.7x'
    ok = {'calculations': [_calc('c1', 'multiple', 'f1', 'f2'), _calc('c2', 'figure', parts=['f1', 'f2'])],
          'paragraphs': [_para('{c2} {c1} Growth must continue.', ['f1', 'f2'])]}
    problems, results = validate_section(section, ok, REVENUE)
    assert problems == []
    assert finish_section(section, ok, results, [])['paragraphs'][0]['text'] == (
        'Revenue was USD 0.27 Mn in Q2-FY22 and USD 0.73 Mn in Q4-FY22. Revenue of USD 0.73 Mn in Q4-FY22 was 2.7 times '
        'its level of USD 0.27 Mn in Q2-FY22, over 6 months. Growth must continue.')
    # The model types neither period figures nor a placeholder inside its own words.
    typed = {'calculations': [_calc('c1', 'multiple', 'f1', 'f2')], 'paragraphs': [_para(
        'Revenue rose from USD 0.27 Mn in Q2-FY22 to USD 0.73 Mn in Q4-FY22, {c1}.', ['f1', 'f2'])]}
    assert any('placeholder inside its own words' in p for p in validate_section(section, typed, REVENUE)[0])
    plain = {'calculations': [], 'paragraphs': [_para('Revenue rose to USD 0.73 Mn.', ['f2'])]}
    assert any('the figure for Q4-FY22' in p for p in validate_section(section, plain, REVENUE)[0])
    invented = {'calculations': [], 'paragraphs': [_para('Revenue grew 170% to USD 0.73 Mn, a strong result.', ['f1', 'f2'])]}
    problems = validate_section(section, invented, REVENUE)[0]
    assert any('170' in p for p in problems) and any('strong' in p for p in problems)


def test_periods_are_parsed_with_indian_fiscal_quarters():
    from delivery.deal_documents.semantics import period_of
    assert period_of('Q4-FY22') == period_of('JFM 22') == ('quarter', 2022 * 12 + 3, 3)
    assert period_of('Q1-FY23') == period_of('AMJ 22') and period_of('OND 22')[1] == 2022 * 12 + 12
    assert period_of('FY 23') == ('year', 2023 * 12 + 3, 12) and period_of('FY23 Exit Run Rate')[0] == 'run_rate'
    assert period_of('Mar 23') == ('month', 2023 * 12 + 3, 1) and period_of('Total') is None and period_of('B') is None


def test_comparisons_across_period_lengths_metrics_or_order_are_rejected():
    from delivery.deal_documents.semantics import CalculationError
    for calc in (_calc('c1', 'growth', 'f2', 'fy'),      # quarter vs full year
                 _calc('c1', 'growth', 'prem', 'f2'),    # premium vs revenue
                 _calc('c1', 'growth', 'f2', 'f1'),      # later before earlier
                 _calc('c1', 'cagr', 'f1', 'f2'),        # six months is not a compound annual rate
                 _calc('c1', 'share', 'f2', 'fy'),       # share across different periods
                 _calc('c1', 'share', 'tam', 'f2')):     # share across units
        with pytest.raises(CalculationError):
            compute(calc, REVENUE)
    quarters = {f'q{n}': _fact(f'q{n}', 'Revenue', f'Q{n}-FY22', str(value)) for n, value in ((1, 0.06), (2, 0.27), (3, 0.40), (4, 0.73))}
    assert compute(_calc('c1', 'sum', parts=list(quarters), decimals=2), quarters)['text'] == 'USD 1.46 Mn'
    share = compute(_calc('c1', 'share', 'f2', 'prem'), REVENUE)
    assert share['text'] == '146.0%' and share['over_time'] is None
    segments = {'ev': _fact('ev', 'Revenue', 'FY22', '0.54', segment='EV'), 'tot': _fact('tot', 'Revenue', 'FY22', '1.46', segment='Total'),
                'evp': _fact('evp', 'Payout', 'FY22', '0.31', segment='EV'), 'smep': _fact('smep', 'Premium', 'FY22', '0.38', segment='SME')}
    assert compute(_calc('c1', 'share', 'ev', 'tot'), segments)['text'] == '37.0%'  # a segment's share of its total
    assert compute(_calc('c1', 'ratio', 'evp', 'ev', decimals=2), segments)['text'] == '0.57x'  # one segment
    with pytest.raises(CalculationError):
        compute(_calc('c1', 'ratio', 'smep', 'tot'), segments)  # SME premium against total revenue


def test_a_single_period_ratio_cannot_be_called_growth_and_a_quarterly_change_is_not_annual():
    results = {'c1': compute(_calc('c1', 'ratio', 'f2', 'prem', decimals=2), REVENUE),
               'c2': compute(_calc('c2', 'growth', 'f1', 'f2'), REVENUE)}
    from delivery.deal_documents.semantics import sentence_problems
    cited = [REVENUE['f1'], REVENUE['f2'], REVENUE['prem']]
    assert any('not a change over time' in p for p in
               sentence_problems('Revenue growth was {c1} against premium in Q4-FY22.', cited, results, label='p1'))
    assert any('calls c2 annual' in p for p in
               sentence_problems('Revenue grew {c2} year-on-year.', cited, results, label='p1'))
    assert sentence_problems('Revenue was {c1} gross premium in Q4-FY22.', cited, results, label='p1') == []
    assert sentence_problems('Revenue rose {c2} over two quarters from Q2-FY22 to Q4-FY22.', cited, results, label='p1') == []


def test_literal_quarter_to_year_comparison_is_flagged():
    from delivery.deal_documents.semantics import sentence_problems
    problems = sentence_problems('Revenue grew from USD 0.73 Mn to USD 1.46 Mn.', [REVENUE['f2'], REVENUE['fy']], {}, label='p1')
    assert any('same length' in p for p in problems)


def test_projections_run_rates_and_third_party_figures_must_be_labelled_in_the_sentence():
    from delivery.deal_documents.semantics import sentence_problems
    def check(text, *ids):
        return sentence_problems(text, [REVENUE[i] for i in ids], {}, label='p1')
    assert any('company projection' in p for p in check('Revenue reaches USD 9.80 Mn in FY23.', 'p23'))
    assert check('The company projects revenue of USD 9.80 Mn in FY23.', 'p23') == []
    assert check('The company projects an exit run rate of USD 13.18 Mn.', 'rr') == []
    assert any('source' in p for p in check('The home-insurance market is USD 2.7 Bn.', 'tam'))
    assert check('According to Swiss Re, the market is USD 2.7 Bn.', 'tam') == []
    assert any('measures premium' in p for p in check('Revenue was USD 0.50 Mn in Q4-FY22.', 'prem'))


def test_placeholders_are_filled_by_code_and_unknown_ones_are_rejected():
    section = {'words': 18}
    draft = {'calculations': [_calc('c1', 'multiple', 'f1', 'f2')],
             'paragraphs': [_para('Revenue rose {c1} from Q2-FY22 to Q4-FY22; see also {c9}.', ['f1', 'f2'])]}
    problems, results = validate_section(section, draft, REVENUE)
    assert any('{c9}' in p for p in problems)
    from delivery.deal_documents.memo import finish_section
    final = finish_section({'key': 'historical', 'title': 'Historical'}, draft, results, [])
    assert final['paragraphs'][0]['text'].startswith('Revenue rose 2.7x') and final['paragraphs'][0]['calculations_used'] == ['c1', 'c9']


def test_sentences_that_still_fail_are_removed_and_recorded():
    from delivery.deal_documents.memo import prune
    index = {**REVENUE, 'q1': _fact('q1', 'Revenue', 'Q1-FY22', '0.06'), 'q3': _fact('q3', 'Revenue', 'Q3-FY22', '0.50')}
    draft = {'calculations': [_calc('c1', 'growth', 'fy', 'f2'), _calc('c2', 'multiple', 'f1', 'f2')], 'paragraphs': [
        _para('{c1}. {c2}. The ramp depends on new partners.', ['f2', 'fy', 'f1'])]}
    problems, results = validate_section({'words': 30}, draft, index)
    assert any('Q3-FY22' in p and 'compare' in p for p in problems)  # the fix names comparable quarters
    removed = prune(draft, index, results)
    assert [r['sentence'] for r in removed] == ['{c1}.']
    assert draft['paragraphs'][0]['text'] == '{c2}. The ramp depends on new partners.'
    assert [c['id'] for c in draft['calculations']] == ['c2'] and validate_section({'words': 30}, draft, index)[0] == []


def test_a_unit_typed_after_a_placeholder_is_not_doubled():
    from delivery.deal_documents.semantics import fill_placeholders
    results = {'c1': {'text': '+19.9%'}, 'c2': {'text': '2.7x'}, 'c3': {'text': 'USD 13.33 Mn'}}
    assert fill_placeholders('up {c1}% and {c2}x larger, then {c1}.', results) == 'up +19.9% and 2.7x larger, then +19.9%.'
    assert fill_placeholders('converts to {c3} USD, or {c3} Mn.', results) == 'converts to USD 13.33 Mn, or USD 13.33 Mn.'


def test_a_ratio_cannot_be_written_as_a_money_amount():
    from delivery.deal_documents.semantics import fill_placeholders, sentence_problems
    results = {'c1': compute(_calc('c1', 'ratio', 'prem', 'f2', decimals=2), REVENUE)}
    cited = [REVENUE['f2'], REVENUE['prem']]
    assert any('money amount' in p for p in sentence_problems('Revenue of USD 0.73 Mn on USD {c1} Mn premium.', cited, results, label='p'))
    assert sentence_problems('Premium was {c1} revenue in Q4-FY22.', cited, results, label='p') == []
    assert results['c1']['label'] == 'Gross premium relative to Revenue, Q4-FY22'
    amount = {'c5': {'text': 'USD 13.33 Mn', 'kind': 'convert'}}
    assert fill_placeholders('about USD {c5} Mn at 75', amount) == 'about USD 13.33 Mn at 75'
    assert fill_placeholders('INR 1,000 Mn ({c5} USD Mn) rather', amount) == 'INR 1,000 Mn (USD 13.33 Mn) rather'


def test_cached_sections_are_rechecked_under_current_rules():
    from delivery.deal_documents.memo import finish_section, revalidate, validate_section
    draft = {'calculations': [_calc('c1', 'ratio', 'prem', 'f2', decimals=2), _calc('c2', 'figure', parts=['f2'])],
             'paragraphs': [_para('{c2}. Premium was USD {c1} Mn.', ['f2', 'prem'])]}
    problems, results = validate_section({'words': 18}, draft, REVENUE)
    record = finish_section({'key': 'historical', 'title': 'Historical'}, draft, results, [])  # saved as if valid
    again = revalidate({'key': 'historical', 'title': 'Historical', 'words': 8}, record, REVENUE)
    assert [item['sentence'] for item in again['removed_sentences']] == ['Premium was USD {c1} Mn.']
    assert again['paragraphs'][0]['text'] == 'Revenue was USD 0.73 Mn in Q4-FY22.' and again['state'] == 'valid'


def test_citation_markup_in_prose_is_removed_and_thin_sections_are_flagged():
    from delivery.deal_documents.memo import length_problems, strip_ids
    assert strip_ids('Toffee runs a B2B2C model {cites: [') == 'Toffee runs a B2B2C model'
    assert strip_ids('Premium rose (cites: ["TII-p6.T1.r1c6"]) in Q1-FY23.') == 'Premium rose in Q1-FY23.'
    assert strip_ids('USD 7.70 Mn (OND 22) {TII-p6.T2.r1c1}.') == 'USD 7.70 Mn (OND 22).'
    assert strip_ids('thirteen named entities (TID-p14.2–TID-p14.5) and a rate (c1) of {c1}.') == \
        'thirteen named entities and a rate of {c1}.'
    assert strip_ids('as stated on TID-p7.1 and TII-p6.T1.r5c5 pages') == 'as stated on and pages'
    assert 'develop the analysis' in length_problems({'words': 260}, 110)[0] and length_problems({'words': 260}, 250) == []


def test_one_line_paragraphs_are_flagged_and_sentence_endings_restored():
    from delivery.deal_documents.memo import finish_section
    lines = {'calculations': [], 'paragraphs': [_para('Revenue reached USD 0.73 Mn in Q4-FY22', ['f2']) for _ in range(3)]}
    problems, results = validate_section({'words': 18}, lines, REVENUE)
    assert any('single sentence' in p for p in problems)
    final = finish_section({'key': 'historical', 'title': 'Historical'}, lines, results, problems)
    assert final['paragraphs'][0]['text'].endswith('Q4-FY22.')


def test_meta_references_and_doubled_results_are_flagged_for_revision():
    draft = {'calculations': [_calc('c1', 'growth', 'f1', 'f2')], 'paragraphs': [_para(
        'The reviewer notes revenue rose 170.4% {c1} from Q2-FY22 to Q4-FY22.', ['f1', 'f2'])]}
    problems, results = validate_section({'words': 12}, draft, REVENUE)
    assert any('how the memo was prepared' in p for p in problems)
    from delivery.deal_documents.memo import finish_section
    final = finish_section({'key': 'historical', 'title': 'Historical'}, draft, results, problems)
    assert final['paragraphs'][0]['text'] == 'The reviewer notes revenue rose 170.4% from Q2-FY22 to Q4-FY22.'
    rate = {'calculations': [_calc('c1', 'ratio', 'f2', 'prem', decimals=2)], 'paragraphs': [_para(
        'The take rate was {c1} of gross premium in Q4-FY22.', ['f2', 'prem'])]}
    assert any('declare it as a share' in p for p in validate_section({'words': 10}, rate, REVENUE)[0])


def test_phrases_the_reviewer_barred_are_flagged():
    from delivery.deal_documents.memo import avoided_phrases
    avoid = avoided_phrases({'human_notes': 'FOS means feet on street. avoid: "field operating system"'})
    draft = {'calculations': [], 'paragraphs': [_para('Revenue reached USD 0.73 Mn in Q4-FY22 with no Field Operating System.', ['f2'])]}
    assert any('barred' in p for p in validate_section({'words': 14}, draft, REVENUE, (), avoid)[0])


def test_implied_exchange_rates_and_self_comparisons():
    from delivery.deal_documents.semantics import CalculationError, sentence_problems
    cap = {'inr': _fact('inr', 'Equity Raised', 'Current', '580.47', unit='INR Million', segment='Total'),
           'usd': _fact('usd', 'Equity Raised', 'Current', '8.29', unit='USD Million', segment='Total'),
           'hold': _fact('hold', 'Shareholding', 'Current', '62.98', unit='%')}
    assert compute(_calc('c1', 'implied_rate', 'inr', 'usd', decimals=2), cap)['text'] == '70.02 INR/USD'
    with pytest.raises(CalculationError):
        compute(_calc('c1', 'ratio', 'usd', 'inr', decimals=2), cap)  # one figure against itself
    percent_sum = {'c7': {'kind': 'sum', 'text': '62.98 %', 'over_time': None, 'projection': False, 'label': 'holdings', 'value': 62.98}}
    assert any('money amount' in p for p in sentence_problems('Total capital raised is INR {c7} Mn.', [], percent_sum, label='p'))


def _projection_table():
    """A projection row with four quarter columns and a "Total" column, plus actuals of the same series."""
    table = {'id': 'T2'}
    row = {f'T2.r5c{n}': {**_fact(f'T2.r5c{n}', 'Indirect Spends', period, value, basis='projection', segment='Total'), 'table': table}
           for n, (period, value) in enumerate([('OND 22', '1.10'), ('JFM 23', '1.20'), ('AMJ 23', '1.30'), ('JAS 23', '1.48'),
                                                ('Total', '5.08')], 1)}
    return {**row, 'q1': _fact('q1', 'Indirect Spends', 'Q1-FY23', '1.73', segment='Total'),
            'fy': _fact('fy', 'Indirect Spends', 'FY22', '3.10', segment='Total')}


def test_a_total_column_covers_its_quarters_and_is_not_a_fiscal_year():
    from delivery.deal_documents.semantics import fact_period, period_of, sentence_problems
    index = _projection_table()
    assert fact_period(index['T2.r5c5'], index) == ('span', 2023 * 12 + 9, 12) and period_of('FY 2022-23') == period_of('FY23')
    problems = sentence_problems('The company projects indirect spends of USD 5.08 Mn, exceeding Q1-FY23 actuals of USD 1.73 Mn.',
                                 [index['T2.r5c5'], index['q1']], {}, label='p', index=index)
    assert any('12 months to Sep-23' in p and 'same length' in p for p in problems)
    # The earlier figure is uncited: it is found in the index by its series.
    assert any('same length' in p for p in sentence_problems(
        'Indirect spends were USD 1.73 Mn in Q1-FY23, up from USD 3.10 Mn in FY22.', [index['q1']], {}, label='p', index=index))
    assert any('names FY23' in p for p in sentence_problems(
        'The company projects FY23 indirect spends of USD 5.08 Mn.', [index['T2.r5c5']], {}, label='p', index=index))
    assert sentence_problems('The company projects indirect spends of USD 5.08 Mn for the twelve months to Sep-23.',
                             [index['T2.r5c5']], {}, label='p', index=index) == []
    assert sentence_problems('Indirect spends were USD 1.73 Mn in Q1-FY23.', [index['q1']], {}, label='p', index=index) == []


def test_a_calculation_keeps_the_name_of_its_measure_and_direction_claims_need_the_comparison():
    from delivery.deal_documents.semantics import sentence_problems
    figures = {'m': _fact('m', 'Margin', 'Q1-FY23', '0.44', segment='Total'), 'r': _fact('r', 'Revenue', 'Q1-FY23', '1.16', segment='Total'),
               'e': _fact('e', 'EBITDA', 'Q1-FY23', '-1.29', segment='Total')}
    results = {'c1': compute(_calc('c1', 'share', 'm', 'r', decimals=2), figures),
               'c2': compute(_calc('c2', 'share', 'e', 'r', decimals=2), figures)}
    cited = list(figures.values())
    assert any('calls c1 EBITDA' in p for p in sentence_problems('Payouts were high, with EBITDA margin at {c1}.', cited, results, label='p'))
    assert any('calls c1 gross margin' in p for p in sentence_problems('The gross margin in Q1-FY23 was {c1}.', cited, results, label='p'))
    assert sentence_problems('Margin was {c1} of revenue and EBITDA {c2} of revenue in Q1-FY23.', cited, results, label='p') == []
    assert any('overstated' in p for p in sentence_problems('The USD valuation is overstated.', cited, results, label='p'))


def test_drafting_instructions_notices_and_repeats_are_removed():
    from delivery.deal_documents.memo import banned_in, prune, strip_ids
    draft = {'calculations': [], 'paragraphs': [_para(
        'According to the report the market is USD 2.7 Bn. The IM should clarify the date of the materials. '
        'Flag FEMA reporting for counsel. The advisors have no conflict of interest in this memorandum. '
        'According to the report the market is USD 2.7 Bn in size.', ['tam'])]}
    problems = validate_section({'words': 30}, draft, REVENUE)[0]
    assert sum('drafting instruction' in p for p in problems) == 2 and any('notices are added by code' in p for p in problems)
    removed = prune(draft, REVENUE, {})
    assert len(removed) == 4 and 'repeats' in removed[-1]['reasons'][0]
    assert draft['paragraphs'][0]['text'] == 'According to the report the market is USD 2.7 Bn.'
    assert strip_ids("It claims 'no direct competitors' (TID-p14.1 says 'No direct competitors'), yet lists "
                     "Acko (TID-p14.2 says 'Acko, Phonepe'; TID-p14.3 says 'Oneassist').") == \
        "It claims 'no direct competitors', yet lists Acko."
    assert banned_in("The company says 'No FOS, Leverage existing POS infrastructure' across unique policies.") == []


def test_an_exchange_rate_unit_after_a_placeholder_is_not_doubled():
    from delivery.deal_documents.semantics import fill_placeholders
    assert fill_placeholders('equity converts at {c3} INR/USD.', {'c3': {'text': '70.02 INR/USD'}}) == 'equity converts at 70.02 INR/USD.'


def test_a_typed_out_result_is_checked_like_its_placeholder_and_a_sum_is_not_a_remainder():
    from delivery.deal_documents.semantics import sentence_problems
    ratio = {'c2': {'kind': 'ratio', 'label': 'Margin (Total) relative to Revenue (Total)', 'text': '0.30x',
                    'over_time': None, 'projection': False}}
    assert any('calls c2 net margin' in p for p in sentence_problems('The company has a net margin of 0.30x on revenue.',
                                                                       [], ratio, label='p'))
    assert sentence_problems('Margin is 0.30x revenue.', [], ratio, label='p') == []
    total = {'c2': {'kind': 'sum', 'label': 'total of Shareholding A, Shareholding B', 'text': '29.35%',
                    'over_time': None, 'projection': False}}
    assert any('remainder' in p for p in sentence_problems('The remaining {c2} is held by investors.', [], total, label='p'))
    assert sentence_problems('Two investors hold {c2} between them.', [], total, label='p') == []


def test_evidence_sentences_are_written_by_code_with_their_direction_names_and_periods():
    from delivery.deal_documents.memo import strip_ids
    index = {**REVENUE, 'fall': _fact('fall', 'Revenue', 'Q1-FY23', '0.50'),
             'inr': _fact('inr', 'Valuation', 'Current', '1255.47', unit='INR Million'),
             'usd': _fact('usd', 'Valuation', 'Current', '17.94', unit='USD Million'),
             'fx': _fact('fx', 'Exchange rate', '', '75', unit='INR/USD', basis='company_claim')}
    sentence = lambda **calc: compute({'id': 'c1', 'a': '', 'b': '', 'rate': '', 'parts': [], 'decimals': 2, **calc}, index)['sentence']
    assert sentence(kind='growth', a='f2', b='fall') == 'Revenue fell 31.51% from USD 0.73 Mn in Q4-FY22 to USD 0.50 Mn in Q1-FY23.'
    assert sentence(kind='share', a='prem', b='f2') == 'Gross premium (USD 0.50 Mn) was 68.49% of revenue (USD 0.73 Mn) in Q4-FY22.'
    assert sentence(kind='figure', parts=['p23', 'fy']) == 'Revenue was USD 1.46 Mn in FY22 and is projected at USD 9.80 Mn in FY23.'
    assert sentence(kind='convert', a='inr', rate='fx', b='usd') == (
        'Valuation of INR 1,255.47 Mn converts to USD 16.74 Mn at 75 INR/USD, while the materials state USD 17.94 Mn, '
        'USD 1.20 Mn more than the conversion.')
    assert strip_ids('{c1} {c2} The point is margin. Premium of {c3} USD rose.') == \
        '{c1}. {c2}. The point is margin. Premium of {c3} USD rose.'


def test_independent_steps_run_concurrently_and_every_step_is_recorded(tmp_path, monkeypatch):
    import sqlite3
    import threading
    import time
    from delivery.deal_documents import pipeline, runs
    conn = sqlite3.connect(tmp_path / 'app.db', isolation_level=None, check_same_thread=False)
    run = runs.create(conn, 't1', 'w1', 'd1', 'Synthetic Co', tmp_path / 'run', 'local-model')
    runs.update(conn, run['id'], lambda data: data['phases']['memo'].update(state='queued'))
    run, phase, token = runs.claim(conn)
    tracker = runs.Tracker(conn, run, phase, token, 'test')
    tracker.plan([(f's{i}', f'Step {i}', 'write') for i in range(6)])
    monkeypatch.setattr(pipeline, 'PARALLEL', 3)
    active, peak, lock = [0], [0], threading.Lock()

    def work(i):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return i
    assert pipeline.parallel([lambda i=i: tracker.step(f's{i}', [i], lambda i=i: work(i)) for i in range(6)]) == list(range(6))
    assert peak[0] == 3
    steps = runs.get_by_id(conn, run['id'])['data']['phases']['memo']['steps']
    assert [s['state'] for s in steps] == ['done'] * 6 and all(s['seconds'] is not None for s in steps)


def test_a_revision_returns_only_changed_paragraphs_and_the_rest_is_kept_verbatim():
    from delivery.deal_documents.memo import _patch_schema, apply_patch
    draft = {'calculations': [_calc('c1', 'figure', parts=['f2'])], 'paragraphs': [
        _para('{c1}. Keep this point.', ['f2']), _para('Old wording.', ['f2']), _para('Cut this.', ['f2']),
        {'kind': 'question', 'text': 'What is the policy count?', 'cites': [{'id': 'f2', 'says': '0.73'}]}]}
    patch = {'calculations': [_calc('c2', 'figure', parts=['fy'])], 'edits': [
        {'paragraph': 2, 'kind': 'analysis', 'text': 'New wording.', 'cites': [{'id': 'f2', 'says': '0.73'}]},
        {'paragraph': 3, 'kind': 'analysis', 'text': '', 'cites': []},
        {'paragraph': 0, 'kind': 'analysis', 'text': '{c2}. Added point.', 'cites': [{'id': 'fy', 'says': '1.46'}]}]}
    merged = apply_patch(draft, patch)
    assert [p['text'] for p in merged['paragraphs']] == ['{c1}. Keep this point.', 'New wording.', '{c2}. Added point.',
                                                         'What is the policy count?']
    assert [c['id'] for c in merged['calculations']] == ['c1', 'c2']
    assert _patch_schema(['f2'], 4)['properties']['edits']['items']['properties']['paragraph']['maximum'] == 4


def test_the_writer_sees_short_ids_and_every_answer_is_mapped_back_to_real_ids():
    from delivery.deal_documents.memo import Aliases, strip_ids
    aliases = Aliases(['TII-p6.T1.r5', 'TII-p6.T1.r5c6', 'TII-p6.T1.r5c5', 'TID-p4.4'])
    assert aliases.apply('TII-p6.T1.r5 [historical]: c5 FY22=1.46 · c6 Q1-FY23=1.16; see TID-p4.4.') == \
        '#1 [historical]: c5 FY22=1.46 · c6 Q1-FY23=1.16; see #2.'
    assert aliases.to['TII-p6.T1.r5c6'] == '#1c6'
    answer = aliases.restore({'calculations': [{'a': '#1c5', 'b': '#1c6', 'rate': '', 'parts': ['#1c6']}],
                              'edits': [{'cites': [{'id': '#2', 'says': 'customers'}]}]})
    assert answer['calculations'][0]['a'] == 'TII-p6.T1.r5c5' and answer['calculations'][0]['parts'] == ['TII-p6.T1.r5c6']
    assert answer['edits'][0]['cites'][0]['id'] == 'TID-p4.4'
    assert strip_ids('Revenue rose (#1c6, #2) as stated #12.') == 'Revenue rose as stated.'


def test_rankings_are_stated_by_code_and_the_model_does_not_rank_figures_itself():
    from delivery.deal_documents.memo import evidence_form_problems
    index = {s: _fact(s, 'Gross margin', '', v, basis='projection', unit='%', segment=name)
             for s, v, name in (('h', '45', 'Home & Content'), ('e', '20', 'EV & Motor'), ('g', '15', 'SME & Gig'))}
    ranked = compute({'id': 'c1', 'kind': 'rank', 'a': '', 'b': '', 'rate': '', 'parts': ['e', 'g', 'h'], 'decimals': 0}, index)
    assert ranked['sentence'] == ('Gross margin is projected highest for Home & Content (45%), then for EV & Motor (20%), '
                                  'and lowest for SME & Gig (15%).')
    cited = [REVENUE['f2']]
    assert evidence_form_problems('EV & Motor has the lowest gross margin.', cited, REVENUE)
    assert evidence_form_problems('Revenue is higher than the prior year.', cited, REVENUE)
    assert evidence_form_problems('The company states more than ten thousand partners.', cited, REVENUE) == []
    assert evidence_form_problems('Regulatory risk is higher for bundled products.', cited, REVENUE) == []


def test_a_rerun_moves_old_outputs_aside_and_shows_sections_as_they_are_drafted(tmp_path):
    from delivery.deal_documents.pipeline import MEMO_OUTPUTS, _supersede, progress_markdown
    (tmp_path / 'memo.md').write_text('old memo')
    (tmp_path / 'facts.md').write_text('facts stay')
    _supersede(tmp_path, MEMO_OUTPUTS)
    moved = list((tmp_path / 'superseded').glob('*/memo.md'))
    assert not (tmp_path / 'memo.md').exists() and moved and moved[0].read_text() == 'old memo'
    assert (tmp_path / 'facts.md').read_text() == 'facts stay'
    text = progress_markdown([{'title': 'Company overview', 'state': 'valid', 'problems': [],
                               'paragraphs': [{'text': 'Revenue was USD 0.73 Mn in Q4-FY22.'}]}], 12)
    assert 'IN PROGRESS' in text and '1 of 12 sections' in text and 'Revenue was USD 0.73 Mn in Q4-FY22.' in text


def test_growth_across_a_skipped_quarter_must_state_its_span():
    from delivery.deal_documents.semantics import sentence_problems
    results = {'c1': compute({'id': 'c1', 'kind': 'growth', 'a': 'f1', 'b': 'f2', 'decimals': 2}, REVENUE)}
    assert any('skips the periods' in p for p in sentence_problems('Revenue grew {c1} to Q4-FY22.', [], results, label='p'))
    assert sentence_problems('Revenue grew {c1} over two quarters to Q4-FY22.', [], results, label='p') == []


def test_unsourced_quotes_reviewer_attribution_and_orphaned_references_are_removed():
    from delivery.deal_documents.memo import prune, strip_ids
    draft = {'calculations': [], 'paragraphs': [_para(
        "According to the report the market is USD 2.7 Bn. The deck shows logos but notes 'no confirmation from the auditor'. "
        "The sum of these logos is unclear. Reviewer findings note that revenue exceeds premium. "
        "It is unclear how revenue is recognised.", ['tam'])]}
    removed = prune(draft, REVENUE, {})
    assert [r['reasons'][0][:14] for r in removed] == ['it quotes "no ', 'it refers back', 'it describes h']
    assert draft['paragraphs'][0]['text'] == 'According to the report the market is USD 2.7 Bn. It is unclear how revenue is recognised.'
    assert prune({'calculations': [], 'paragraphs': [_para("Revenue was 'Revenue — Q4-FY22' in the deck.", ['f2'])]},
                 REVENUE, {}) == []
    assert strip_ids('higher channel payouts {cites:,,-notes.5,-notes.10}.') == 'higher channel payouts.'


def test_improvement_between_a_quarter_and_a_year_is_flagged_and_dangling_sentences_go():
    from delivery.deal_documents.memo import prune
    from delivery.deal_documents.semantics import sentence_problems
    loss = {'q': _fact('q', 'EBITDA', 'Q1-FY23', '-1.29'), 'y': _fact('y', 'EBITDA', 'FY22', '-2.94')}
    assert any('same length' in p for p in sentence_problems(
        'EBITDA was negative USD 1.29 Mn in Q1-FY23, an improvement from USD 2.94 Mn in FY22.', list(loss.values()), {}, label='p'))
    draft = {'calculations': [], 'paragraphs': [_para('Revenue grew from USD 1.46 Mn in FY22 to USD 0.73 Mn in Q4-FY22. '
                                                      'This shows momentum. According to the report the market is USD 2.7 Bn.',
                                                      ['fy', 'f2', 'tam'])]}
    removed = prune(draft, REVENUE, {})
    assert [r['sentence'] for r in removed][1] == 'This shows momentum.'
    assert draft['paragraphs'][0]['text'] == 'According to the report the market is USD 2.7 Bn.'


def test_reviewer_changes_with_invented_figures_are_not_passed_to_the_writer():
    from delivery.deal_documents.review import known_numbers, notes_for, proposes_unknown_number
    sections = [{'results': {'c1': {'value': 13.33, 'text': 'USD 13.33 Mn'}}}]
    known = known_numbers(REVENUE, sections)
    wrong = {'section': 'market', 'quote_verified': True, 'reviewer': 'fact_checker', 'quote': 'USD 13.33 Mn',
             'problem': 'conversion', 'fix': 'It should be USD 133.3 Mn.'}
    right = {**wrong, 'fix': 'Say USD 13.33 Mn is a conversion at the stated rate.'}
    assert proposes_unknown_number(wrong, known) and not proposes_unknown_number(right, known)
    notes = notes_for('market', {'issues': [wrong, right]}, known)
    assert '133.3' not in notes and 'conversion at the stated rate' in notes


def test_compliance_gate_flags_assurances_stale_data_and_missing_disclosures():
    import datetime
    from delivery.deal_documents import compliance
    base = {'facts': [REVENUE['f2'], REVENUE['p23']]}
    sections = [{'section': 'risks', 'problems': [], 'paragraphs': [
        {'text': 'Investors are guaranteed a 3x return. The company projects it will reach USD 9.80 Mn.'}]}]
    result = compliance.assess(sections, base, today=datetime.date(2026, 10, 28))
    status = {check['key']: check['status'] for check in result['checks']}
    assert status['assurance_language'] == 'fail' and status['information_date'] == 'counsel'
    assert status['disclosure_risk_factors'] == 'pass' and status['disclosure_use_of_proceeds'] == 'fail'
    assert 'counsel_private_placement' in result['counsel_questions']
    hits = next(c for c in result['checks'] if c['key'] == 'assurance_language')['evidence']
    assert len(hits) == 1  # the attributed projection is not an assurance
    notice = dict(compliance.notices('Acme', base, today=datetime.date(2026, 10, 28)))
    assert '55 months' in notice['Basis of preparation and date of information']


def test_run_state_survives_restarts_and_approvals_bind_the_output(tmp_path):
    import sqlite3
    from delivery.deal_documents import runs
    conn = sqlite3.connect(tmp_path / 'app.db', isolation_level=None)
    run = runs.create(conn, 't1', 'w1', 'd1', 'Acme', tmp_path, 'm')
    with pytest.raises(ValueError):
        runs.queue(conn, run, 'memo', 'owner')  # facts not approved
    runs.queue(conn, run, 'facts', 'owner')
    claimed, phase, token = runs.claim(conn)
    tracker = runs.Tracker(conn, claimed, phase, token, 'v1')
    tracker.plan([('a', 'Step A', 'extract'), ('b', 'Step B', 'write')])
    calls = []
    assert tracker.step('a', ['x'], lambda: calls.append(1) or {'n': 1}) == {'n': 1}
    # The worker dies: the lease expires and the phase is re-queued, keeping step A.
    conn.execute('UPDATE deal_document_runs SET lease_until=0')
    claimed, phase, token = runs.claim(conn)
    tracker = runs.Tracker(conn, claimed, phase, token, 'v1')
    assert tracker.step('a', ['x'], lambda: calls.append(2) or {'n': 2}) == {'n': 1} and calls == [1]
    tracker.step('b', ['y'], lambda: True)
    (tmp_path / 'facts.json').write_text('{}')
    tracker.finish('needs_approval')
    view = runs.public(runs.get(conn, 't1', 'w1'))['phases']['facts']
    assert view['state'] == 'needs_approval' and view['interruptions'] == 1 and view['steps_done'] == 2
    runs.approve(conn, runs.get(conn, 't1', 'w1'), 'facts', 'operator', {'by': 'owner', 'notes': ''})
    assert runs.phase_ready(runs.get(conn, 't1', 'w1'), 'memo') is None
    (tmp_path / 'facts.json').write_text('{"changed": true}')
    assert 'changed after approval' in runs.phase_ready(runs.get(conn, 't1', 'w1'), 'memo')


def _claimed_tracker(tmp_path):
    import sqlite3
    from delivery.deal_documents import runs
    conn = sqlite3.connect(tmp_path / 'app.db', isolation_level=None)
    run = runs.create(conn, 't1', 'w1', 'd1', 'Acme', tmp_path, 'm')
    runs.queue(conn, run, 'facts', 'owner')
    claimed, phase, token = runs.claim(conn)
    return conn, runs.Tracker(conn, claimed, phase, token, 'v1')


def test_a_step_that_returns_a_model_failure_is_retried_rather_than_saved(tmp_path):
    _, tracker = _claimed_tracker(tmp_path)
    tracker.plan([('a', 'A', 'write'), ('b', 'B', 'check')])
    assert tracker.step('a', ['x'], lambda: {'state': 'failed', 'paragraphs': []})['state'] == 'failed'
    assert tracker.step('a', ['x'], lambda: {'state': 'valid'})['state'] == 'valid'
    assert tracker.step('b', ['x'], lambda: {'issues': [], 'failure': 'server down'})['failure'] == 'server down'
    assert tracker.step('b', ['x'], lambda: {'issues': []}) == {'issues': []}
    assert tracker.step('a', ['x'], lambda: {'state': 'changed'}) == {'state': 'valid'}


def test_an_answer_given_during_a_run_is_visible_to_later_steps(tmp_path):
    from delivery.deal_documents import runs
    conn, tracker = _claimed_tracker(tmp_path)
    tracker.set_questions([{'id': 'q1', 'text': 'Which rate?', 'why': 'w', 'severity': 'blocker', 'sections': [], 'confidence': 95,
                            'basis': 'b', 'sources': []}])
    runs.answer_question(conn, runs.get(conn, 't1', 'w1'), 'q1', 'Seventy.', 'owner')
    assert tracker.live_questions()[0]['answer']['text'] == 'Seventy.'


def test_questions_are_asked_before_any_section_is_written():
    source = Path(__file__).resolve().parents[2].joinpath('delivery/deal_documents/pipeline.py').read_text(encoding='utf-8')
    body = source[source.index('def memo_phase'):source.index('MEMO_OUTPUTS =')]
    assert body.index("tracker.step('questions'") < body.index("tracker.step(f'write:")
    from delivery.deal_documents import climb
    assert climb.PASSES == 2


def test_prompts_and_rules_carry_no_one_sector_or_company():
    import re
    from delivery.deal_documents import decks, facts, memo, questions, review
    texts = [memo.WRITE_SYSTEM, json.dumps(memo.SECTIONS), facts.CHECK_SYSTEM if hasattr(facts, 'CHECK_SYSTEM') else '', decks.DECK_SYSTEM,
             questions.ASK_SYSTEM, review.FACT_CHECK_SYSTEM, review.COMPLIANCE_SYSTEM, review.GENERAL_NOTES]
    assert not re.search(r'premium|polic(y|ies)\b|insur|irdai|\bMGA\b|EV & Motor|Sep-23', ' '.join(texts), re.IGNORECASE)


def test_sector_notes_join_only_when_the_company_calls_for_them():
    from delivery.deal_documents.review import reference_notes
    assert 'IRDAI' not in reference_notes('A company selling accounting software to retailers.')
    assert 'IRDAI' in reference_notes('A distributor of motor insurance.')


def test_old_information_is_asked_about_but_blocks_nothing():
    from delivery.deal_documents import compliance, questions
    fact_base = {'facts': [{'id': 'A-p1.1', 'statement': 'Revenue: 1 USD Mn', 'metric': 'Revenue', 'period': 'Q1-FY20', 'basis': 'historical',
                            'value': '1', 'unit': 'USD Mn', 'segment': '', 'topic': 'historical_financials'}], 'workbook_cells': [], 'checks': []}
    found = questions.candidates(fact_base)
    assert next(item for item in found if item['basis'] == 'information_age')['severity'] == 'high'
    assert 'information_date' not in compliance.assess([], fact_base)['blockers']


def _money(fact_id, period, value):
    return {'id': fact_id, 'statement': f'EBITDA: {value} USD Mn', 'metric': 'EBITDA', 'segment': 'Total', 'period': period, 'basis': 'historical',
            'value': value, 'unit': 'USD Mn', 'topic': 'historical_financials'}


def test_direction_words_must_match_the_change_including_for_losses():
    from delivery.deal_documents import semantics
    index = {'a': _money('a', 'FY21', '(2.94)'), 'b': _money('b', 'FY22', '(0.73)')}
    change = semantics.compute({'id': 'c1', 'kind': 'difference', 'a': 'b', 'b': 'a', 'rate': '', 'parts': [], 'decimals': 2}, index)
    results = {'c1': change}
    assert change['value'] > 0
    assert semantics.sentence_problems('EBITDA losses narrowed by {c1}.', [], results, label='p', index=index) == []
    assert any('direction' in problem for problem in semantics.sentence_problems('EBITDA losses widened by {c1}.', [], results, label='p', index=index))


def test_readings_compare_only_like_periods_and_are_built_for_any_table():
    from delivery.deal_documents import readings
    from delivery.deal_documents.decks import tables_from_facts
    cell = lambda column, period, value: {'id': f'X-p1.T1.r1c{column}', 'statement': f'Units — Total — {period}: {value} count', 'metric': 'Units',
                                          'segment': 'Total', 'period': period, 'basis': 'historical', 'value': value, 'unit': 'count',
                                          'topic': 'operations', 'table': {'id': 'X-p1.T1', 'title': 'Units'}}
    facts = [cell(1, 'Q4-FY22', '10'), cell(2, 'FY22', '30'), cell(3, 'Q4-FY23', '20')]
    results = readings.build(tables_from_facts(facts), {fact['id']: fact for fact in facts})
    growth = [result for result in results.values() if result['kind'] == 'growth']
    assert len(growth) == 1 and growth[0]['facts'] == ['X-p1.T1.r1c1', 'X-p1.T1.r1c3'] and growth[0]['text'] == '+100.0%'


def _im_facts():
    def cell(row, column, metric, period, value):
        return {'id': f'X-p1.T1.r{row}c{column}', 'statement': f'{metric} — Total — {period}: {value} USD Mn', 'metric': metric, 'segment': 'Total',
                'period': period, 'basis': 'historical', 'value': value, 'unit': 'USD Mn', 'topic': 'historical_financials', 'document': 'Deck',
                'location': 'page 1', 'table': {'id': 'X-p1.T1', 'title': 'Results'}}
    facts = [cell(1, 1, 'Revenue', 'FY21', '1.00'), cell(1, 2, 'Revenue', 'FY22', '3.00'), cell(2, 1, 'EBITDA', 'FY21', '(2.00)'), cell(2, 2, 'EBITDA', 'FY22', '(1.00)'),
             {'id': 'X-p2.1', 'statement': 'The company sells software to retailers.', 'metric': '', 'segment': '', 'period': '', 'basis': 'company_claim',
              'value': '', 'unit': '', 'topic': 'historical_financials', 'document': 'Deck', 'location': 'page 2'}]
    return {'facts': facts, 'workbook_cells': [], 'checks': [], 'observations': [], 'human_notes': ''}


class _FakeIMModel:
    """Scripted answers: the first of each list is what a writer proposes, then what it says after repair."""
    def __init__(self, sections, thesis, verdicts):
        self.sections, self.thesis, self.verdicts, self.calls = list(sections), list(thesis), list(verdicts), []

    def json(self, name, profile, system, user, schema, *args, **kwargs):
        self.calls.append((name, profile, user))
        source = self.verdicts if name == 'thesis-claims' else self.thesis if name.startswith('thesis') else self.sections
        return source.pop(0) if len(source) > 1 else source[0]


def _readings(fact_base):
    from delivery.deal_documents import readings
    from delivery.deal_documents.decks import tables_from_facts
    index = {fact['id']: fact for fact in fact_base['facts']}
    tables = tables_from_facts(fact_base['facts'])
    return tables, readings.build(tables, index), index


def _key(results, kind, *words):
    return next(key for key, result in results.items() if result['kind'] == kind and all(word in result['label'] for word in words))


def test_a_section_that_recites_or_invents_is_repaired_without_a_person(tmp_path):
    from delivery.deal_documents import im
    from delivery.deal_documents.memo import SECTIONS
    fact_base = _im_facts()
    tables, results, index = _readings(fact_base)
    growth = _key(results, 'growth', 'Revenue')
    spec = next(section for section in SECTIONS if section['key'] == 'historical')
    invented = {'headline': 'Revenue rose to 9.99 in FY22.', 'exhibits': ['X-p1.T1'], 'paragraphs': [
        {'text': 'The materials do not explain the costs.', 'cites': []}, {'text': 'Revenue rose 9.99 percent.', 'cites': []}]}
    fixed = {'headline': 'Revenue tripled while losses narrowed.', 'exhibits': ['X-p1.T1'], 'paragraphs': [
        {'text': f'Revenue changed by {{{growth}}} between the two years, which shows the retail offer finding demand.', 'cites': []},
        {'text': 'The company sells software to retailers, so each new customer adds recurring work.', 'cites': ['X-p2.1']}]}
    model = _FakeIMModel([invented, fixed], [], [])
    thesis = {'positioning': 'Software for retailers.', 'merits': [], 'tension': 'Losses.'}
    record = im.write_section(model, spec, thesis, fact_base, tables, results, index)
    assert [call[0] for call in model.calls] == ['im-historical', 'im-historical-repair1']
    assert record['state'] == 'valid' and record['problems'] == [] and '+200.0%' in record['paragraphs'][0]['text']
    assert record['exhibits'][0]['rows'][0][0] == 'Revenue' and 'X-p1.T1.r1c2' in record['paragraphs'][0]['cites']


def test_a_paragraph_with_no_evidence_goes_back_to_the_writer():
    from delivery.deal_documents import im
    from delivery.deal_documents.memo import SECTIONS
    fact_base = _im_facts()
    tables, results, index = _readings(fact_base)
    spec = next(section for section in SECTIONS if section['key'] == 'historical')
    bare = {'headline': 'Retailers buy the software.', 'exhibits': [], 'paragraphs': [{'text': 'Retailers like the software.', 'cites': []},
                                                                                      {'text': 'The company sells software.', 'cites': ['X-p2.1']}]}
    cited = {**bare, 'paragraphs': [{'text': 'The company sells software.', 'cites': ['X-p2.1']}, {'text': 'Retailers buy it.', 'cites': ['X-p2.1']}]}
    model = _FakeIMModel([bare, cited], [], [])
    record = im.write_section(model, spec, {'positioning': 'p', 'merits': [], 'tension': 't'}, fact_base, tables, results, index)
    assert len(model.calls) == 2 and record['state'] == 'valid'


def test_a_sentence_that_never_passes_is_removed_and_recorded(tmp_path):
    from delivery.deal_documents import im
    from delivery.deal_documents.memo import SECTIONS
    fact_base = _im_facts()
    tables, results, index = _readings(fact_base)
    spec = next(section for section in SECTIONS if section['key'] == 'historical')
    stubborn = {'headline': 'Revenue grew.', 'exhibits': [], 'paragraphs': [
        {'text': 'Revenue reached 9.99 this year. The company sells software to retailers.', 'cites': ['X-p2.1']}, {'text': 'The company sells software.', 'cites': ['X-p2.1']}]}
    model = _FakeIMModel([stubborn], [], [])
    record = im.write_section(model, spec, {'positioning': 'p', 'merits': [], 'tension': 't'}, fact_base, tables, results, index)
    assert len(model.calls) == 3 and '9.99' not in json.dumps(record['paragraphs'])
    assert record['removed_sentences'][0]['sentence'].startswith('Revenue reached')


def test_a_merit_its_own_evidence_contradicts_is_rewritten_then_dropped_by_the_local_reviewer():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    merit = lambda claim: {'claim': claim, 'proof': 'The company sells software to retailers.', 'against': 'The company sells software to retailers.'}
    draft = {'positioning': 'Software for retailers.', 'tension': 'Losses continue.', 'merits': [merit('Every sale is profitable.'), merit('Retailers buy the software.'), merit('Retailers renew the software.')]}
    verdicts = [{'verdicts': [{'merit': 1, 'verdict': 'contradicted', 'reason': 'EBITDA is negative'}, {'merit': 2, 'verdict': 'supported', 'reason': 'ok'}, {'merit': 3, 'verdict': 'supported', 'reason': 'ok'}]}]
    model = _FakeIMModel([], [draft], verdicts)
    thesis = im.write_thesis(model, fact_base, results, index)
    assert [merit['claim'] for merit in thesis['merits']] == ['Retailers buy the software.', 'Retailers renew the software.']
    assert thesis['dropped'] == [{'claim': 'Every sale is profitable.', 'reason': 'EBITDA is negative'}]
    assert [call[1] for call in model.calls if call[0] == 'thesis-claims'] == ['check'] * 3


def test_a_rewrite_after_review_is_checked_by_code_again_and_refused_claims_leave():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    growth = _key(results, 'growth', 'Revenue')
    merit = lambda claim, proof=f'Revenue grew {{{growth}}}.': {'claim': claim, 'proof': proof, 'against': 'The company sells software to retailers.'}
    first = {'positioning': 'Software for retailers.', 'tension': 'Losses continue.', 'merits': [merit('Retailers buy the software.'), merit('Retailers stay.'), merit('Partners struggle.')]}
    typed = {**first, 'merits': [merit('Retailers buy the software.'), merit('Retailers stay.'), merit('Revenue reached 9.99 this year.', 'Revenue reached 9.99.')]}
    fixed = {**first, 'merits': [merit('Retailers buy the software.'), merit('Retailers stay.'), merit('Retailers renew the software.')]}
    ok = lambda number: {'merit': number, 'verdict': 'supported', 'reason': 'ok'}
    weak = {'verdicts': [ok(1), ok(2), {'merit': 3, 'verdict': 'not_a_merit', 'reason': 'a weakness'}]}
    good = {'verdicts': [ok(1), ok(2), ok(3)]}
    model = _FakeIMModel([], [first, typed, fixed], [weak, good])
    thesis = im.write_thesis(model, fact_base, results, index)
    assert [call[0] for call in model.calls] == ['thesis', 'thesis-claims', 'thesis-reviewed1', 'thesis-reviewed1-repair1', 'thesis-claims']
    assert thesis['problems'] == [] and thesis['dropped'] == [] and thesis['merits'][2]['claim'] == 'Retailers renew the software.'


def test_a_change_may_state_its_two_figures_beside_the_comparison():
    from delivery.deal_documents import semantics
    fact = lambda fact_id, period, value: {'id': fact_id, 'metric': 'Units', 'segment': 'Total', 'period': period, 'value': value, 'unit': 'USD Mn', 'basis': 'historical', 'statement': 'Units'}
    index = {'a': fact('a', 'FY21', '1.00'), 'b': fact('b', 'FY22', '3.00')}
    calc = lambda name, **fields: semantics.compute({'id': name, 'rate': '', 'a': '', 'b': '', 'parts': [], 'decimals': 1, **fields}, index)
    results = {'c1': calc('c1', kind='figure', parts=['a']), 'c2': calc('c2', kind='figure', parts=['b']), 'c3': calc('c3', kind='growth', a='a', b='b')}
    assert semantics.sentence_problems('Units grew from {c1} to {c2}, a {c3} increase.', [], results, label='p', index=index) == []
    assert semantics.sentence_problems('Units grew to {c2}.', [], results, label='p', index=index)


def test_a_period_name_is_not_an_unsupported_figure_but_a_typed_figure_is():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    fact_base['facts'][1]['period'] = 'Q4-FY22'
    tables, results, index = _readings(fact_base)
    narrative = [fact for fact in fact_base['facts'] if not fact.get('table')]
    allowed = im._allowed(narrative, fact_base['facts'])
    assert im.text_problems('Retailers kept buying through Q4-FY22.', 'thesis', [], results, index, allowed) == []
    assert im.text_problems('Revenue reached 3.00 in Q4-FY22.', 'thesis', [], results, index, allowed)


def test_too_few_merits_sends_the_writer_back_to_other_subjects():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    growth = _key(results, 'growth', 'Revenue')
    merit = lambda claim: {'claim': claim, 'proof': f'Revenue grew {{{growth}}}.', 'against': 'The company sells software to retailers.'}
    thin = {'positioning': 'Software for retailers.', 'tension': 'Losses continue.', 'merits': [merit('Retailers buy the software.')]}
    full = {**thin, 'merits': [merit('Retailers buy the software.'), merit('Retailers stay.'), merit('Retailers refer others.')]}
    ok = lambda number: {'merit': number, 'verdict': 'supported', 'reason': 'ok'}
    model = _FakeIMModel([], [thin, full], [{'verdicts': [ok(1)]}, {'verdicts': [ok(1), ok(2), ok(3)]}])
    thesis = im.write_thesis(model, fact_base, results, index)
    assert len(thesis['merits']) == 3 and thesis['problems'] == []
    assert 'Add more' in next(call[2] for call in model.calls if call[0] == 'thesis-reviewed1')


def test_every_section_and_the_thesis_are_told_the_reconciliation_findings():
    from delivery.deal_documents import im
    from delivery.deal_documents.memo import SECTIONS
    fact_base = {**_im_facts(), 'human_notes': 'Revenue above its gross volume needs explaining.'}
    tables, results, index = _readings(fact_base)
    spec = next(section for section in SECTIONS if section['key'] == 'historical')
    section = {'headline': 'Retailers buy the software.', 'exhibits': [], 'paragraphs': [{'text': 'The company sells software.', 'cites': ['X-p2.1']}, {'text': 'Retailers buy it.', 'cites': ['X-p2.1']}]}
    merit = {'claim': 'Retailers buy it.', 'proof': 'The company sells software.', 'against': 'The company sells software.'}
    model = _FakeIMModel([section], [{'positioning': 'p.', 'tension': 't.', 'merits': [merit] * 3}], [{'verdicts': [{'merit': n, 'verdict': 'supported', 'reason': 'ok'} for n in (1, 2, 3)]}])
    im.write_section(model, spec, {'positioning': 'p', 'merits': [], 'tension': 't'}, fact_base, tables, results, index)
    im.write_thesis(model, fact_base, results, index)
    assert all('Revenue above its gross volume' in call[2] for call in model.calls if call[0] != 'thesis-claims')


def test_a_memorandum_does_not_talk_about_its_own_documents():
    from delivery.deal_documents import im
    _, results, index = _readings(_im_facts())
    for text in ('The memorandum presents a contradiction.', 'The provided materials are silent.', 'The estimate is not corroborated by anyone.'):
        assert im.text_problems(text, 'market', [], results, index, [])
    assert im.text_problems('The estimate is not corroborated by anyone.', 'risks', [], results, index, []) == []


def test_a_failing_tension_or_positioning_never_reaches_the_writers():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    merit = lambda claim: {'claim': claim, 'proof': 'The company sells software to retailers.', 'against': 'The company sells software to retailers.'}
    answer = {'positioning': 'Software for retailers.', 'tension': 'Customers total 660,000 on our own sum.', 'merits': [merit('A works.'), merit('B works.'), merit('C works.')]}
    ok = {'verdicts': [{'merit': number, 'verdict': 'supported', 'reason': 'ok'} for number in (1, 2, 3)]}
    thesis = im.write_thesis(_FakeIMModel([], [answer], [ok]), fact_base, results, index)
    assert thesis['tension'] == '' and 'tension removed' in thesis['problems'][0]
    assert '660' not in im.thesis_text(thesis, results)


def test_the_claim_reviewer_judges_a_merit_on_its_own_subject():
    from delivery.deal_documents import im
    assert 'Judge each merit on its own subject' in im.CLAIM_SYSTEM and 'Losses do not disprove' in im.CLAIM_SYSTEM


def test_a_fiscal_year_name_must_be_the_period_of_the_figure_beside_it():
    from delivery.deal_documents import semantics
    fact = lambda fact_id, period: {'id': fact_id, 'metric': 'Revenue', 'segment': 'Total', 'period': period, 'value': '5.00', 'unit': 'USD Mn', 'basis': 'historical', 'statement': 'Revenue'}
    index = {'a': fact('a', 'Q1-FY23'), 'b': fact('b', 'FY22'), 'c': fact('c', 'JAS 23')}
    results = {f'c{n}': semantics.compute({'id': f'c{n}', 'kind': 'figure', 'a': '', 'b': '', 'rate': '', 'parts': [item], 'decimals': 1}, index) for n, item in enumerate('abc', 1)}
    assert not semantics.sentence_problems('Revenue in FY22 was {c2}.', [], results, label='p', index=index)
    assert any('says FY22' in problem for problem in semantics.sentence_problems('Revenue in FY22 was {c3}.', [], results, label='p', index=index))


def test_a_change_after_by_prints_its_size_and_the_verb_gives_the_direction():
    from delivery.deal_documents import semantics
    assert semantics.fill_placeholders('Losses widened by {c1}.', {'c1': {'text': 'USD -0.76 Mn', 'kind': 'difference'}}) == 'Losses widened by USD 0.76 Mn.'


def test_a_sentence_pointing_back_at_a_removed_sentence_goes_too():
    from delivery.deal_documents import im
    from delivery.deal_documents.memo import SECTIONS
    fact_base = _im_facts()
    tables, results, index = _readings(fact_base)
    spec = next(section for section in SECTIONS if section['key'] == 'historical')
    paragraph = {'text': 'Revenue reached 9.99 this year. This gap suggests a change. The company sells software to retailers.', 'cites': ['X-p2.1']}
    kept, removed = im._keep_sentences(spec, paragraph, fact_base['facts'], results, index, im._allowed(fact_base['facts'][-1:], fact_base['facts']), [])
    assert kept == 'The company sells software to retailers.' and len(removed) == 2


def test_a_memorandum_does_not_instruct_its_reader():
    from delivery.deal_documents import im
    _, results, index = _readings(_im_facts())
    assert im.text_problems('Principal risks require resolution before committing capital.', 'summary', [], results, index, [])
    assert im.text_problems('The number of licences is not specified.', 'company', [], results, index, [])


def _growth_results():
    from delivery.deal_documents import semantics
    fact = lambda fact_id, period, value: {'id': fact_id, 'metric': 'Volume', 'segment': 'Total', 'period': period, 'value': value, 'unit': 'USD Mn', 'basis': 'historical', 'statement': 'Volume'}
    index = {'a': fact('a', 'Q1-FY22', '1.00'), 'b': fact('b', 'Q4-FY22', '4.00')}
    calc = lambda name, kind, **fields: semantics.compute({'id': name, 'kind': kind, 'a': '', 'b': '', 'rate': '', 'parts': [], 'decimals': 1, **fields}, index)
    return {'c1': calc('c1', 'figure', parts=['a']), 'c2': calc('c2', 'figure', parts=['b']), 'c3': calc('c3', 'growth', a='a', b='b'), 'c4': calc('c4', 'difference', a='b', b='a')}, index


def test_growth_across_a_span_is_sound_when_both_ends_are_printed():
    from delivery.deal_documents import semantics
    results, index = _growth_results()
    assert not [p for p in semantics.sentence_problems('Volume rose from {c1} in Q1-FY22 to {c2} in Q4-FY22, up {c3}.', [], results, label='p', index=index) if 'skips' in p]
    assert [p for p in semantics.sentence_problems('Volume rose {c3} to Q4-FY22.', [], results, label='p', index=index) if 'skips' in p]


def test_a_change_is_never_printed_as_a_level():
    from delivery.deal_documents import semantics
    results, index = _growth_results()
    assert any('as a level' in p for p in semantics.sentence_problems('Volume moved to {c4} over the year.', [], results, label='p', index=index))
    assert not any('as a level' in p for p in semantics.sentence_problems('Volume moved by {c4} over the year.', [], results, label='p', index=index))


def test_the_memorandum_never_narrates_a_difference_between_figures_in_any_section():
    from delivery.deal_documents import im
    _, results, index = _readings(_im_facts())
    for text in ('The FX discrepancy requires reconciliation.', 'Segment labels are inconsistent between documents.', 'Counsel to confirm the licence.',
                 'This requires management clarification before proceeding.', 'The list undermines the claim.'):
        assert im.text_problems(text, 'risks', [], results, index, [])


def test_a_regulated_assurance_word_is_repaired_before_the_gate_sees_it():
    from delivery.deal_documents import im
    _, results, index = _readings(_im_facts())
    assert any('assurance' in p for p in im.text_problems('Revenue rests on a Guaranteed Margin Model.', 'business_model', [], results, index, []))


def test_an_overstated_merit_keeps_the_reviewers_fair_wording():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    merit = lambda claim: {'claim': claim, 'proof': 'The company sells software to retailers.', 'against': 'The company sells software to retailers.'}
    answer = {'positioning': 'Software for retailers.', 'tension': 'Whether retailers keep buying.', 'merits': [merit('A works.'), merit('B dominates.'), merit('C works.')]}
    verdicts = {'verdicts': [{'merit': 1, 'verdict': 'supported', 'reason': 'ok', 'fair_claim': ''}, {'merit': 2, 'verdict': 'overstated', 'reason': 'too far', 'fair_claim': 'B has customers.'},
                             {'merit': 3, 'verdict': 'supported', 'reason': 'ok', 'fair_claim': ''}]}
    thesis = im.write_thesis(_FakeIMModel([], [answer], [verdicts]), fact_base, results, index)
    assert [merit['claim'] for merit in thesis['merits']] == ['A works.', 'B has customers.', 'C works.'] and not thesis['dropped']


def test_a_point_made_twice_stays_only_where_it_first_appears():
    from delivery.deal_documents import im
    repeated = 'Risk sits with the carriers and never on the balance sheet'
    section = lambda key, *texts: {'section': key, 'results': {}, 'paragraphs': [{'text': text, 'source_text': text} for text in texts], 'removed_sentences': []}
    records = [section('company', f'{repeated}.'), section('team', f'{repeated}, meaning the team is experienced. This matters. Retailers buy it.'), section('summary', f'{repeated}.')]
    final = {record['section']: record for record in im.drop_repeats(records)}
    assert final['company']['paragraphs'][0]['text'] == f'{repeated}.'
    assert final['team']['paragraphs'][0]['text'] == 'Retailers buy it.' and len(final['team']['removed_sentences']) == 2
    assert final['summary']['paragraphs'][0]['text'] == f'{repeated}.'


def test_a_dangling_reference_goes_even_with_a_sentence_between_it_and_the_removal():
    from delivery.deal_documents import im
    from delivery.deal_documents.memo import SECTIONS
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    spec = next(section for section in SECTIONS if section['key'] == 'historical')
    paragraph = {'text': 'Revenue reached 9.99 this year. The company sells software to retailers. This trajectory shows demand.', 'cites': ['X-p2.1']}
    kept, _ = im._keep_sentences(spec, paragraph, fact_base['facts'], results, index, im._allowed(fact_base['facts'][-1:], fact_base['facts']), [])
    assert kept == 'The company sells software to retailers.'


def test_the_largest_move_in_each_measure_comes_first():
    from delivery.deal_documents import readings
    _, results, index = _readings(_im_facts())
    assert list(readings.standouts(results, index).values())[0]['label'].startswith('growth in Revenue')


def test_high_questions_hold_release_and_the_summary_prints_first():
    from delivery.deal_documents import compliance, im_render
    section = {'section': 'company', 'paragraphs': [{'text': 'The company sells software.'}]}
    open_question = {'text': 'Which rate applies?', 'severity': 'high'}
    fact_base = {'facts': [], 'workbook_cells': [], 'checks': [], 'observations': [], 'human_notes': ''}
    assert 'figures_under_confirmation' in compliance.assess([section], fact_base, open_questions=[open_question])['blockers']
    assert 'figures_under_confirmation' not in compliance.assess([section], fact_base, open_questions=[{**open_question, 'answer': {'text': '75'}}])['blockers']
    order = lambda sections: sorted(sections, key=lambda item: item['section'] != 'summary')
    assert order([{'section': 'company'}, {'section': 'summary'}])[0]['section'] == 'summary' and "section.get('merits'" in Path(im_render.__file__).read_text()


def _two_rates():
    from delivery.deal_documents import semantics
    fact = lambda fact_id, metric, period, value: {'id': fact_id, 'metric': metric, 'segment': 'Total', 'period': period, 'value': value, 'unit': 'USD Mn', 'basis': 'historical', 'statement': metric}
    index = {'a': fact('a', 'Premium', 'FY21', '1.00'), 'b': fact('b', 'Premium', 'FY22', '5.00'), 'c': fact('c', 'Margin', 'FY21', '1.00'), 'd': fact('d', 'Margin', 'FY22', '3.00')}
    calc = lambda name, a, b: semantics.compute({'id': name, 'kind': 'growth', 'a': a, 'b': b, 'rate': '', 'parts': [], 'decimals': 1}, index)
    return {'c1': calc('c1', 'a', 'b'), 'c2': calc('c2', 'c', 'd')}, index


def test_a_claim_that_one_rate_beat_another_needs_both_and_the_right_order():
    from delivery.deal_documents import semantics
    results, index = _two_rates()
    check = lambda text: semantics.sentence_problems(text, [], results, label='p', index=index)
    assert any('without both rates' in p for p in check('Margin outpaced premium growth.'))
    assert any('shows the opposite' in p for p in check('Margin growth of {c2} outpaced premium growth of {c1}.'))
    assert not any('outpaced' in p for p in check('Premium growth of {c1} outpaced margin growth of {c2}.'))
    assert not any('slower' in p for p in check('Margin grew {c2}, slower than premium at {c1}.'))


def test_a_change_must_name_its_own_measure():
    from delivery.deal_documents import semantics
    results, index = _two_rates()
    assert any('without naming' in p for p in semantics.sentence_problems('This is a step-up from the prior year, which grew {c1}.', [], results, label='p', index=index))
    assert not any('without naming' in p for p in semantics.sentence_problems('Premiums grew {c1} in the year.', [], results, label='p', index=index))


def test_margin_and_quarter_claims_need_a_figure():
    from delivery.deal_documents import semantics
    check = lambda text: semantics.sentence_problems(text, [], {}, label='p', index={})
    assert any('without a reading' in p for p in check('The company scales with improving unit economics.'))
    assert any('without a figure' in p for p in check('The company projects breakeven by the final quarter of FY23.'))


def test_a_large_rise_prints_as_a_multiple_for_any_company():
    from delivery.deal_documents import readings
    fact_base = _im_facts()
    fact_base['facts'][1]['value'] = '5.00'
    tables, results, index = _readings(fact_base)
    assert any(result['kind'] == 'growth' and result['text'] == '5.0x' for result in results.values())
    assert all('(Total)' not in line for line in readings.lines(results))


def test_a_memorandum_does_not_assume_gender():
    from delivery.deal_documents import im
    _, results, index = _readings(_im_facts())
    assert any('gender' in p for p in im.text_problems('Their chief of sales brings his experience.', 'team', [], results, index, []))


def test_period_and_unit_wording_alone_is_not_a_repeat():
    from delivery.deal_documents import im
    section = lambda key, text: {'section': key, 'results': {}, 'paragraphs': [{'text': text, 'source_text': text}], 'removed_sentences': []}
    first = 'Revenue grew from USD 0.10 Mn in Q1-FY22 to USD 4.20 Mn in Q1-FY23, a change of 42.0x.'
    second = 'Channel payout grew from USD 0.04 Mn in Q1-FY22 to USD 0.73 Mn in Q1-FY23, a change of 18.2x.'
    final = im.drop_repeats([section('business_model', first), section('distribution', second)])
    assert final[1]['paragraphs'] and not final[1]['removed_sentences']


def test_a_thesis_with_no_reported_growth_goes_back_for_a_traction_merit():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    merit = lambda claim: {'claim': claim, 'proof': 'The company sells software to retailers.', 'against': 'The company sells software to retailers.'}
    answer = {'positioning': 'Software for retailers.', 'tension': 'Whether retailers keep buying.', 'merits': [merit('A works.'), merit('B works.'), merit('C works.')]}
    ok = {'verdicts': [{'merit': number, 'verdict': 'supported', 'reason': 'ok', 'fair_claim': ''} for number in (1, 2, 3)]}
    model = _FakeIMModel([], [answer], [ok])
    thesis = im.write_thesis(model, fact_base, results, index)
    assert 'No merit rests on reported growth' in next(call[2] for call in model.calls if call[0] == 'thesis-reviewed1')
    assert 'no merit rests on reported growth' in thesis['problems']


def test_a_merit_lost_to_review_is_asked_for_again_on_the_missing_subject():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    growth = _key(results, 'growth', 'Revenue')
    plain = lambda claim: {'claim': claim, 'proof': 'The company sells software to retailers.', 'against': 'The company sells software to retailers.'}
    first = {'positioning': 'Software for retailers.', 'tension': 'Whether retailers keep buying.', 'merits': [plain('Retailers buy it.'), plain('The product is sold.')]}
    traction = {'positioning': 'Software for retailers.', 'tension': 'Whether retailers keep buying.',
                'merits': [{'claim': 'Revenue has grown.', 'proof': f'Revenue grew {{{growth}}}.', 'against': 'The company sells software to retailers.'}]}
    answers = [first, first, first, traction]

    class Model(_FakeIMModel):
        def json(self, name, profile, system, user, schema, *args, **kwargs):
            self.calls.append((name, profile, user))
            if name == 'thesis-claims':
                merits = user.count('MERIT ')
                return {'verdicts': [{'merit': number, 'verdict': 'supported', 'reason': 'ok', 'fair_claim': ''} for number in range(1, merits + 1)]}
            return answers.pop(0) if len(answers) > 1 else answers[0]
    model = Model([], [], [])
    thesis = im.write_thesis(model, fact_base, results, index)
    assert [merit['claim'] for merit in thesis['merits']] == ['Retailers buy it.', 'The product is sold.', 'Revenue has grown.']
    assert thesis['problems'] == []
    assert any(call[0] == 'thesis-fill1' and 'A merit on traction' in call[2] for call in model.calls)


def test_a_fault_in_the_case_against_does_not_cost_the_merit():
    from delivery.deal_documents import im
    fact_base = _im_facts()
    _, results, index = _readings(fact_base)
    growth = _key(results, 'growth', 'Revenue')
    merit = lambda claim: {'claim': claim, 'proof': f'Revenue grew {{{growth}}}.', 'against': 'The materials do not say.'}
    answer = {'positioning': 'Software for retailers.', 'tension': 'Whether retailers keep buying.', 'merits': [merit('A works.'), merit('B works.'), merit('C works.')]}
    ok = {'verdicts': [{'merit': number, 'verdict': 'supported', 'reason': 'ok', 'fair_claim': ''} for number in (1, 2, 3)]}
    thesis = im.write_thesis(_FakeIMModel([], [answer], [ok]), fact_base, results, index)
    assert len(thesis['merits']) == 3 and all(merit['against'] == '' for merit in thesis['merits'])
    assert 'Against' not in im.thesis_text(thesis, results)


def test_results_do_not_confirm_things_and_named_things_are_not_counted_by_hand():
    from delivery.deal_documents import im
    assert any('let the reader conclude' in problem for problem in im.text_problems('This confirms the model works.', 'summary', [], {}, {}, []))
    assert any('let the reader conclude' in problem for problem in im.text_problems('Revenue is validating the channel.', 'summary', [], {}, {}, []))
    assert any('by hand' in problem for problem in im.text_problems('The company lists thirteen named firms.', 'competition', [], {}, {}, []))
    assert not im.text_problems('The company sells to four categories of buyer.', 'competition', [], {}, {}, [])


def test_a_figure_keeps_its_name_and_a_past_valuation_is_not_a_live_round():
    from delivery.deal_documents import im
    from delivery.deal_documents.semantics import compute
    fact = {'id': 'V1', 'statement': 'Pre Series A Valuation — Total — Current: 784.99 INR Million', 'metric': 'Pre Series A Valuation', 'segment': 'Total', 'period': 'Current',
            'basis': 'historical', 'value': '784.99', 'unit': 'INR Million', 'topic': 'cap_table_funding'}
    index = {'V1': fact}
    results = {'c1': compute({'id': 'c1', 'kind': 'figure', 'a': '', 'b': '', 'rate': '', 'parts': ['V1'], 'decimals': 2}, index)}
    assert any('something other than its name' in problem for problem in im.text_problems('The pre-money valuation stands at {c1}.', 'capital', [fact], results, index, []))
    assert not any('something other than its name' in problem for problem in im.text_problems('The Pre Series A valuation was {c1}.', 'capital', [fact], results, index, []))
    assert any('speaks of a round' in problem for problem in im.text_problems('The current round values the company at {c1}.', 'capital', [fact], results, index, []))


def test_a_market_size_with_no_currency_stays_out():
    from delivery.deal_documents import im
    fact = {'id': 'M1', 'statement': 'Market Value — Embedded Finance — 2030: 7.2 Trillion', 'metric': 'Market Value', 'value': '7.2', 'unit': 'Trillion', 'topic': 'market', 'segment': '', 'period': '2030', 'basis': 'third_party'}
    assert any('no currency' in problem for problem in im.text_problems('Research shows the market reaching 7.2 Trillion by 2030.', 'market', [fact], {}, {}, [7.2]))


def test_a_deterioration_prints_no_second_minus_but_a_level_keeps_its_sign():
    from delivery.deal_documents.semantics import fill_placeholders
    assert fill_placeholders('a deterioration of USD -0.76 Mn', {}) == 'a deterioration of USD 0.76 Mn'
    assert fill_placeholders('EBITDA of USD -1.29 Mn', {}) == 'EBITDA of USD -1.29 Mn'


def test_the_team_section_gives_each_person_a_title():
    from delivery.deal_documents import im
    from delivery.deal_documents.memo import SECTIONS
    spec = next(section for section in SECTIONS if section['key'] == 'team')
    fact = {'id': 'T1', 'statement': 'Name & Role — Asha Rao: CEO & Co-Founder, 20 years in retail', 'topic': 'team'}
    answer = lambda text: {'headline': 'The team knows retail.', 'exhibits': [], 'paragraphs': [{'text': text, 'cites': ['T1']}]}
    assert any('without their title' in problem for problem in im._section_problems(spec, answer('Asha Rao has 20 years in retail.'), [fact], {}, {}, [20], ()))
    assert not any('without their title' in problem for problem in im._section_problems(spec, answer('Asha Rao, CEO, has 20 years in retail.'), [fact], {}, {}, [20], ()))


def _audit_record():
    paragraph = lambda text: {'kind': 'analysis', 'text': text, 'source_text': text, 'cites': ['X-p2.1'], 'own_cites': ['X-p2.1'], 'calculations_used': []}
    return {'section': 'business_model', 'title': 'Business', 'state': 'valid', 'headline': 'Retailers buy the software.', 'results': {}, 'problems': [], 'removed_sentences': [],
            'paragraphs': [paragraph('The company sells software. It sells to retailers. This keeps costs low. Sales run through partners.')]}


class _Audit:
    """`passes` is one {profile: refused sentence numbers} for each read of the section."""
    def __init__(self, *passes):
        self.passes, self.calls = passes, []

    def json(self, name, profile, system, user, schema, *args, **kwargs):
        self.calls.append((name, user))
        refused = self.passes[1 if 'again' in name else 0].get(profile, ())
        return {'sentences': [{'n': number, 'kind': 'fact', 'verdict': 'refuse' if number in refused else 'pass', 'why': 'no fact says so.'}
                              for number in range(schema['properties']['sentences']['minItems'])]}


def _both(*numbers):
    return {'check': numbers, 'analyse': numbers}


def test_the_audit_sends_a_refused_sentence_back_once_then_takes_it_out():
    from delivery.deal_documents import im
    facts = _im_facts()['facts'][-1:]
    model, asked = _Audit(_both(3), _both(3)), []
    record = im.audit_section(model, _audit_record(), facts, lambda notes: asked.append(notes) or _audit_record())
    assert 'This keeps costs low.' in asked[0]
    assert record['paragraphs'][0]['text'] == 'The company sells software. It sells to retailers. Sales run through partners.'
    assert record['removed_sentences'][0]['reasons'] == ['claim audit: no fact says so.'] and record['state'] == 'valid'
    assert 'The company sells software to retailers.' in model.calls[0][1]


def test_one_agents_refusal_asks_the_writer_but_removes_nothing():
    from delivery.deal_documents import im
    asked = []
    record = im.audit_section(_Audit({'check': (3,)}), _audit_record(), _im_facts()['facts'][-1:], lambda notes: asked.append(notes) or _audit_record())
    assert not asked and not record['removed_sentences'] and 'This keeps costs low.' in record['paragraphs'][0]['text']
    assert record['audit'] == [] and record['audit_noted'][0]['sentence'] == 'This keeps costs low.'


def test_the_audit_keeps_a_rewrite_that_it_no_longer_refuses():
    from delivery.deal_documents import im
    better = {**_audit_record(), 'headline': 'Retailers buy it.'}
    record = im.audit_section(_Audit(_both(3), {}), _audit_record(), _im_facts()['facts'][-1:], lambda notes: better)
    assert record['headline'] == 'Retailers buy it.' and not record['removed_sentences']


def test_a_rewrite_that_says_much_less_is_not_taken():
    from delivery.deal_documents import im
    short = _audit_record()
    short['paragraphs'] = [{**short['paragraphs'][0], 'text': 'Sales run.', 'source_text': 'Sales run.'}]
    record = im.audit_section(_Audit(_both(3), {}), _audit_record(), _im_facts()['facts'][-1:], lambda notes: short)
    assert 'Sales run through partners.' in record['paragraphs'][0]['text'] and 'This keeps costs low.' not in record['paragraphs'][0]['text']


def test_the_audit_cannot_gut_a_section():
    from delivery.deal_documents import im
    record = im.audit_section(_Audit(_both(1, 2, 3, 4), _both(1, 2, 3, 4)), _audit_record(), _im_facts()['facts'][-1:], lambda notes: _audit_record())
    assert record['paragraphs'] and record['state'] == 'needs_review'
    assert any(problem.startswith('claim audit') for problem in record['problems'])


def test_a_refused_headline_comes_off_and_says_why():
    from delivery.deal_documents import im
    record = im.audit_section(_Audit(_both(0), _both(0)), _audit_record(), _im_facts()['facts'][-1:], lambda notes: _audit_record())
    assert record['headline'] == '' and record['state'] == 'needs_review'


def test_relations_say_which_measure_became_a_smaller_share():
    from delivery.deal_documents import readings
    moves = {'c1': {'kind': 'growth', 'over_time': {'gap': 12}, 'value': 4100, 'text': '42.0x', 'label': 'Premium from Q1 to Q2'},
             'c2': {'kind': 'growth', 'over_time': {'gap': 12}, 'value': 2100, 'text': '22.0x', 'label': 'Margin from Q1 to Q2'}}
    assert readings.relations(moves) == ['Premium (42.0x) grew faster than Margin (22.0x), so Margin fell as a share of Premium.']


def test_a_slide_keeps_the_companys_name_and_prints_numbers_as_people_do():
    from delivery.deal_documents import decks
    assert decks._misspelt('Tooffee Insurance grew.', 'Toffee Insurance') == ['Tooffee']
    assert decks._misspelt('Toffee Insurance grew.', 'Toffee Insurance') == []
    assert decks.RAW_NUMBER.search('has 10000 count channel partners').group(0) == '10000 count'
    assert not decks.RAW_NUMBER.search('as of 2016 it had 10,000 partners')


def test_a_headline_that_describes_the_slide_is_refused():
    from delivery.deal_documents import decks
    assert decks.LABEL_HEADLINE.search('The cap table shows IVM and other holders')
    assert not decks.LABEL_HEADLINE.search('Insurers and venture funds back the company')


def test_the_highlights_are_the_merits_review_kept():
    from delivery.deal_documents import decks
    slide = {'section': 'highlights', 'state': 'needs_review', 'problems': ['the slide has 2 bullets; it needs at least 3 to make its point'], 'visual': {'type': 'chart'},
             'paragraphs': [{'kind': 'headline', 'text': 'The case in one line.'}, {'kind': 'evidence', 'text': 'A weaker restatement.'}]}
    merits = [{'claim': f'Claim {number}.', 'proof': f'Proof {number}.'} for number in (1, 2, 3)]
    final = decks.merit_slide(slide, merits)
    assert [paragraph['text'] for paragraph in final['paragraphs']] == ['The case in one line.', 'Claim 1. Proof 1.', 'Claim 2. Proof 2.', 'Claim 3. Proof 3.']
    assert final['state'] == 'valid' and final['visual'] == {'type': 'none'}


def test_whole_company_rows_in_a_chart_are_named_by_their_measure():
    from delivery.deal_documents import decks
    row = {'label': 'Gross Premium — Total', 'cells': {1: {'segment': 'Total'}}}
    assert decks._item_name(row) == 'Gross Premium'
    assert decks._item_name({'label': 'Premium — Motor', 'cells': {1: {'segment': 'Motor'}}}) == 'Motor'


def test_large_rises_and_small_ratios_read_as_people_say_them():
    from delivery.deal_documents.semantics import compute
    fact = lambda item, metric, period, value: {'id': item, 'statement': f'{metric} {period}: {value}', 'metric': metric, 'segment': 'Total', 'period': period, 'basis': 'historical', 'value': value, 'unit': 'USD Mn'}
    index = {'a': fact('a', 'Revenue', 'FY21', '1.00'), 'b': fact('b', 'Revenue', 'FY22', '5.00'), 'c': fact('c', 'Debt', 'FY22', '0.50')}
    calc = lambda kind, a, b: {'id': 'c1', 'kind': kind, 'a': a, 'b': b, 'rate': '', 'parts': [], 'decimals': 1}
    assert 'rose 5.0x from' in compute(calc('growth', 'a', 'b'), index)['sentence']
    assert '10.0% of' in compute(calc('ratio', 'c', 'b'), index)['sentence']


def _page_tables():
    from delivery.deal_documents.decks import tables_from_facts
    def cell(row, column, metric, segment, period, value, basis='historical'):
        return {'id': f'R-p1.T1.r{row}c{column}', 'statement': f'{metric} — {segment} — {period}: {value} USD Mn', 'metric': metric, 'segment': segment, 'period': period, 'basis': basis,
                'value': value, 'unit': 'USD Mn', 'topic': 'historical_financials', 'document': 'Deck', 'location': 'page 1', 'table': {'id': 'R-p1.T1', 'title': 'Results'}}
    lines = [('Volume', 'Total', ['10.00', '12.00', '30.00']), ('Sales', 'Total', ['4.00', '5.00', '8.00']), ('Sales', 'Alpha', ['3.00', '4.00', '6.00']), ('Sales', 'Beta', ['1.00', '1.00', '2.00']),
             ('Fees', 'Total', ['3.00', '3.00', '5.00']), ('Profit', 'Total', ['1.00', '2.00', '3.00']), ('Overheads', 'Total', ['9.00', '9.00', '9.00']), ('EBITDA', 'Total', ['(8.00)', '(7.00)', '(6.00)'])]
    facts = [cell(number, column, metric, segment, period, value) for number, (metric, segment, values) in enumerate(lines, 1)
             for column, (period, value) in enumerate(zip(('Q1-FY22', 'Q4-FY22', 'Q1-FY23'), values), 1)]
    return facts, tables_from_facts(facts)


def test_the_base_of_a_margin_table_comes_from_the_accounts_own_arithmetic_not_a_name():
    from delivery.deal_documents import pages
    _, tables = _page_tables()
    table = tables['R-p1.T1']
    whole, *_ = pages.identity(table)
    assert whole['label'] == 'Sales — Total'
    size = pages.common_size(table)
    assert size['header'][0] == '% of Sales' and size['rows'][1] == ['Fees', '75.0%', '60.0%', '62.5%']


def test_the_snapshot_leads_with_the_top_line_the_margin_and_the_last_line():
    from delivery.deal_documents import pages
    _, tables = _page_tables()
    kpis = pages.snapshot(tables['R-p1.T1'])
    assert [kpi['label'] for kpi in kpis] == ['Volume', 'Sales', 'Profit', 'EBITDA']
    assert kpis[0]['value'] == '30.00 USD Mn' and kpis[0]['sub'] == '+200% on Q1-FY22'


def test_a_page_is_built_only_from_data_that_exists():
    from delivery.deal_documents import pages
    facts, _ = _page_tables()
    keys = [page['key'] for page in pages.build({'facts': facts, 'workbook_cells': []})]
    assert 'snapshot' in keys and 'margins' in keys and 'mix' in keys and 'team' not in keys and 'forecast' not in keys and 'competition' not in keys
    empty = [page['key'] for page in pages.build({'facts': [], 'workbook_cells': []})]
    assert empty[:2] == ['transaction', 'risks'] and all(key.startswith('regulatory_checklist') for key in empty[2:])  # what is outstanding is still listed


def test_a_category_listing_is_not_mistaken_for_a_person():
    from delivery.deal_documents import pages
    base = {'topic': 'competition', 'metric': 'Rival type', 'value': '', 'unit': '', 'period': ''}
    rivals = [{**base, 'id': f'C{number}', 'segment': name, 'statement': f'Rival type — {name}: Red Co, Blue Co'} for number, name in enumerate(('Lending Fintechs', 'Web Stores', 'Old Banks'))]
    team = [{'id': f'T{number}', 'topic': 'team', 'metric': 'Name & Role', 'segment': name, 'value': '', 'unit': '', 'period': '', 'statement': f'Name & Role — {name}: CEO, 20 years in retail'}
            for number, name in enumerate(('Asha Rao', 'Ben Lee'))]
    assert pages.people(rivals + team)[0]['rows'][0][:2] == ['Asha Rao', 'CEO']
    assert len(pages.people(rivals + team)[0]['rows']) == 2
    assert pages.categories(rivals + team)[0]['rows'][0] == ['Lending Fintechs', 'Red Co, Blue Co']


def test_page_words_may_use_only_numbers_printed_on_the_page():
    from delivery.deal_documents import pages
    good = {'title': 'Sales tripled as two partners went live today', 'takeaways': ['Sales reached 8.00.']}
    assert pages.copy_problems(good, [8.0]) == []
    bad = {'title': 'Sales tripled as two partners went live today', 'takeaways': ['Sales reached 9.50.']}
    assert any('not printed on this page' in problem for problem in pages.copy_problems(bad, [8.0]))
    assert any('words' in problem for problem in pages.copy_problems({'title': 'Sales overview', 'takeaways': []}, []))


def test_a_refused_takeaway_goes_back_once_then_comes_off_the_page():
    from delivery.deal_documents import pages

    class Model:
        def __init__(self):
            self.calls = []

        def json(self, name, profile, system, user, schema, *args, **kwargs):
            self.calls.append(name)
            return {'sentences': [{'n': number, 'kind': 'fact', 'verdict': 'refuse' if number == 1 else 'pass', 'why': 'no.'} for number in range(schema['properties']['sentences']['minItems'])]}
    page = {'key': 'k', 'kind': 'table', 'exhibits': {}, 'topics': [], 'cells': [], 'title': 'Sales tripled as partners went live', 'takeaways': ['Wrong line.', 'Right line.']}
    asked = []
    final = pages.audit_copy(Model(), page, [], lambda notes: asked.append(notes) or page)
    assert 'Wrong line.' in asked[0] and final['takeaways'] == ['Right line.'] and final['audit'][0]['line'] == 'Wrong line.'


def test_a_bridge_steps_reach_the_printed_end_and_show_what_segments_do_not_explain():
    from delivery.deal_documents import pages
    _, tables = _page_tables()
    table = tables['R-p1.T1']
    chart = pages.bridge(table)
    assert chart['plot'] == 'waterfall' and chart['categories'][0] == 'Q1-FY22' and chart['categories'][-1] == 'Q1-FY23'
    values = chart['series'][0]['values']
    assert values[0] + sum(values[1:-1]) == values[-1] == 8.0 and chart['kinds'][0] == 'total'
    short = [cell for cell in _page_tables()[0] if not (cell['segment'] == 'Beta' and cell['period'] == 'Q1-FY23')]
    short.append({**next(cell for cell in _page_tables()[0] if cell['segment'] == 'Beta' and cell['period'] == 'Q1-FY23'), 'value': '1.00', 'statement': 'Sales — Beta — Q1-FY23: 1.00 USD Mn'})
    from delivery.deal_documents.decks import tables_from_facts
    gapped = pages.bridge(tables_from_facts(short)['R-p1.T1'])
    assert 'Not allocated' in gapped['categories'] and gapped['series'][0]['values'][gapped['categories'].index('Not allocated')] == 1.0


def test_the_margin_panel_shares_the_results_periods():
    from delivery.deal_documents import pages
    _, tables = _page_tables()
    table = tables['R-p1.T1']
    panels = pages.dashboard(table, pages.trend_rows(table), 'line')
    assert panels['chart']['categories'] == panels['chart2']['categories']
    assert panels['chart2']['series'][0]['values'] == [25.0, 40.0, 37.5] and 'as % of Sales' in panels['chart2']['caption']


def test_trend_rows_keep_one_unit_when_a_ratio_sits_among_the_amounts():
    from delivery.deal_documents import pages
    from delivery.deal_documents.decks import tables_from_facts
    facts, _ = _page_tables()
    ratio = [{**cell, 'id': cell['id'].replace('.r1c', '.r9c'), 'metric': 'Growth', 'unit': '%', 'statement': cell['statement'].replace('Volume', 'Growth').replace('USD Mn', '%')}
             for cell in facts if cell['metric'] == 'Volume']
    table = tables_from_facts(facts + ratio)['R-p1.T1']
    rows = pages.trend_rows(table)
    assert rows and len({table['rows'][number]['cells'][column]['unit'] for number in rows for column in pages.period_columns(table)}) == 1
    pages.dashboard(table, rows, 'line')


def test_a_bridge_and_panels_draw_on_a_page():
    from delivery.deal_documents import deck_render, pages
    _, tables = _page_tables()
    table = tables['R-p1.T1']
    panels = pages.dashboard(table, pages.trend_rows(table), 'line')
    base = {'heading': 'Sales tripled', 'source': 'Deck, p. 1', 'note': '', 'bullets': [('analysis', 'A short point.')]}
    deck_render.trial_page({**base, **panels})
    deck_render.trial_page({**base, 'chart': pages.bridge(table)})


def test_a_demonstration_teaches_form_and_its_names_cannot_reach_the_page():
    from delivery.deal_documents import pages
    shots = [{'purposes': ['trend'], 'title': 'Northwind sales tripled', 'takeaways': [], 'evidence': ['Sales 8.00'], 'wrong': {'title': 'x', 'why': 'y'}, 'lesson': 'z'},
             {'purposes': ['thin_evidence'], 'title': 'Sales by quarter', 'takeaways': [], 'evidence': ['Sales 2.00'], 'wrong': {'title': 'x', 'why': 'y'}, 'lesson': 'z'}]
    assert [shot['title'] for shot in pages.matched({'key': 'bridge'}, shots)] == ['Northwind sales tripled', 'Sales by quarter']
    assert pages.borrowed('Volume beat Northwind on sales', shots, 'Volume 30.00') == ['Northwind']
    assert pages.borrowed('Volume beat Northwind on sales', shots, 'Northwind 30.00') == []
    foreign = lambda text: pages.borrowed(text, shots, 'Volume')
    assert any('demonstration' in problem for problem in pages.copy_problems({'title': 'Volume beat Northwind this year', 'takeaways': []}, [], foreign=foreign))


def test_the_baseline_is_measured_from_the_references_and_names_what_is_missing(tmp_path, monkeypatch):
    import json
    from delivery.deal_documents import pages
    monkeypatch.setattr(pages, 'REFERENCE_DIR', tmp_path)
    entries = [{'archetype': 'cover', 'approximate_words': 500, 'exhibit_count': 0, 'title_type': 'topic'}, *({'archetype': 'financial table', 'approximate_words': words, 'exhibit_count': 1, 'title_type': 'conclusion'} for words in (40, 60, 80))]
    (tmp_path / 'one.json').write_text(json.dumps(entries))
    (tmp_path / 'demonstrations.json').write_text(json.dumps([{'purposes': []}]))
    facts, _ = _page_tables()
    report = pages.baseline(pages.build({'facts': facts, 'workbook_cells': []}))
    assert report['references'] == {'one': {'pages': 3, 'words_low': 50.0, 'words_median': 60.0, 'words_high': 70.0, 'with_exhibit': 1.0, 'conclusion_titles': 1.0}}
    assert 'financial_table' in report['families'] and 'peer_benchmarks' in report['missing'] and 'transaction_summary' in report['missing']


def test_the_compliance_gate_reads_the_words_on_the_pages():
    from delivery.deal_documents import compliance, pages
    written = {'key': 'trend', 'schedule': False, 'title': 'Returns are guaranteed for every investor', 'takeaways': ['Sales tripled.'], 'exhibits': {}, 'problems': ['a dropped line failed']}
    risks = {'key': 'risks', 'schedule': False, 'title': 'The plan depends on partners', 'takeaways': [], 'exhibits': {'grid': {'rows': [['Partner loss', 'Few partners', '']]}}}
    table = {'key': 'financials', 'schedule': True, 'title': 'Reported financial summary', 'takeaways': [], 'exhibits': {}}
    untitled = {'key': 'mix', 'schedule': False, 'title': '', 'brief': 'Mix.', 'takeaways': [], 'exhibits': {}, 'problems': ['title failed']}
    sections = pages.as_sections([written, risks, table, untitled])
    assert [section['section'] for section in sections] == ['historical', 'risks', 'historical', 'mix']
    assert sections[0]['problems'] == [] and sections[3]['problems'] == ['title failed']
    assert 'Partner loss Few partners ' in [item['text'] for item in sections[1]['paragraphs']]
    result = compliance.assess(sections, {'facts': [], 'workbook_cells': []})
    assert 'assurance_language' in result['blockers']


def test_earlier_generations_stay_readable_while_a_phase_reruns(tmp_path):
    from api.routers.deal_documents import earlier_versions
    for version, names in (('20260101T000000Z', ['memo.md', 'investment_memorandum.pdf']), ('20260102T000000Z', ['pitch_deck.pdf', 'scratch.json']),
                           ('20260103T000000Z', ['memo.md']), ('not-a-version', ['investment_memorandum.pdf'])):
        (tmp_path / 'superseded' / version).mkdir(parents=True)
        for name in names:
            (tmp_path / 'superseded' / version / name).write_text('x')
    versions = earlier_versions(tmp_path)
    assert [item['version'] for item in versions] == ['20260102T000000Z', '20260101T000000Z']  # newest first, an interrupted rerun left out
    assert [item['name'] for item in versions[0]['files']] == ['pitch_deck.pdf'] and versions[1]['files'][0]['phase'] == 'memo'
    assert earlier_versions(tmp_path / 'nothing') == []


def test_a_wide_table_wraps_its_headings_and_widens_its_labels_before_it_is_refused():
    from pptx import Presentation
    from delivery.deal_documents import deck_render
    deck = Presentation()
    deck.slide_width, deck.slide_height = deck_render.Inches(deck_render.WIDTH), deck_render.Inches(7.5)
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    wide = {'header': ['Quarter', 'Gross Premium', 'Revenue', 'Channel Payout', 'Margin', 'Share of Gross Premium'],
            'rows': [['A rather long business line', '3.33', '0.85', '0.54', '0.31', '79.3%'], ['Short', '0.22', '0.08', '0.01', '0.07', '5.2%']]}
    used = deck_render._table(slide, wide, 0.5, 1.5, 8.1, 3.0)
    assert used <= 3.0
    native = next(shape for shape in slide.shapes if shape.has_table).table
    assert native.rows[0].height == 2 * native.rows[1].height  # the heading took a second line
    assert all(native.cell(0, column).text for column in range(6))
    impossible = {'header': ['A', 'B'], 'rows': [['x', 'y' * 200]]}
    with pytest.raises(ValueError, match='label does not fit'):
        deck_render._table(slide, impossible, 0.5, 1.5, 8.1, 3.0)


def test_a_stated_range_must_cover_every_value_the_page_shows():
    from delivery.deal_documents import pages
    series = [[30.9, 29.9, 29.9, 30.1]]
    assert pages.range_problems('Margin stays between 29.9 and 30.1.', series)
    assert pages.range_problems('Margin stays between 29.9 and 30.9.', series) == []
    assert pages.range_problems('Margin stays between 29.9% and 30.1%.', [[1.0, 2.0]]) == []  # another series on the page
    assert pages.copy_problems({'title': 'Margin holds through the projection', 'takeaways': ['Stays between 29.9 and 30.1.']}, [29.9, 30.1], series=series)


def test_a_ratio_page_gives_writer_and_auditor_the_amounts_behind_it():
    from delivery.deal_documents import pages
    seen = []

    class Model:
        def json(self, name, profile, system, user, schema, **kwargs):
            seen.append(user)
            return {'title': 'Spend falls as a share of revenue', 'takeaways': []} if 'sentences' not in schema['properties'] else {'sentences': [{'n': 0, 'kind': 'fact', 'verdict': 'pass', 'why': ''}]}
    page = {'key': 'margins', 'kind': 'table', 'brief': 'Where money goes.', 'exhibits': {'table': {'header': ['% of Revenue', 'Y1'], 'rows': [['EBITDA', '-10.0%']]}},
            'cells': [], 'topics': [], 'title': '', 'schedule': False, 'takeaways': [], 'behind': 'EBITDA | (7.77)'}
    written = pages.write_copy(Model(), page, [])
    assert 'AMOUNTS BEHIND THE PAGE' in seen[0] and '(7.77)' in seen[0]
    pages.audit_copy(Model(), written, [], lambda notes: written)
    assert '(7.77)' in seen[1]


def test_a_risk_table_with_no_mitigants_has_no_empty_column():
    from delivery.deal_documents import pages

    class Model:
        def json(self, *args, **kwargs):
            return {'title': 'The plan depends on partners going live', 'rows': [{'risk': 'Partner loss', 'why': 'Few partners', 'mitigant': ''}, {'risk': 'Delay', 'why': 'Slow launch', 'mitigant': ' '}, {'risk': 'Rules', 'why': 'New rules', 'mitigant': ''}]}
    page = {'key': 'risks', 'kind': 'risks', 'brief': 'Risks.', 'exhibits': {}, 'cells': [], 'topics': [], 'title': '', 'schedule': False, 'takeaways': []}
    grid = pages.write_copy(Model(), page, [])['exhibits']['grid']
    assert grid['header'] == ['Risk', 'What creates it'] and all(len(row) == 2 for row in grid['rows'])


def test_key_points_show_each_statement_once_and_abstain_when_thin():
    from delivery.deal_documents import pages
    fact = lambda number, text, topic='product': {'id': f'f{number}', 'statement': text, 'topic': topic, 'table': None}
    facts = [fact(1, 'Model: Sells through partners at the point of sale'), fact(2, 'Distribution model: Sells through partners at point of sale'), fact(3, 'Pricing: Fixed monthly fee per seat'),
             fact(4, 'Reach: Live with nine named resellers'), fact(5, 'A sentence with no label'), fact(6, 'Team: Six people', 'team'), fact(7, 'Product 1: Combines Feature A1 and Feature B1'), fact(8, 'Staff: 20+ count')]
    grid, used = pages.key_points(facts, ('product',))
    assert [row[0] for row in grid['rows']] == ['Model', 'Pricing', 'Reach', 'Staff'] and used == ['f1', 'f3', 'f4', 'f8']
    assert grid['rows'][3][1] == '20+'
    assert pages.key_points(facts, ('team',)) is None


def test_the_writer_chooses_exhibit_rows_but_cannot_change_them():
    from delivery.deal_documents import pages

    class Model:
        def __init__(self, points):
            self.points = points

        def json(self, name, profile, system, user, schema, **kwargs):
            assert '3. Filler | Feature A1' in user and schema['properties']['points']['items']['maximum'] == 3
            return {'title': 'Partners carry the distribution model', 'takeaways': [], 'points': self.points}
    rows = [['Model', 'Partners'], ['Price', 'Fixed fee'], ['Reach', 'Nine resellers'], ['Filler', 'Feature A1']]
    page = {'key': 'business_model', 'kind': 'copy', 'brief': 'How it earns.', 'exhibits': {'grid': {'header': ['Point', 'Company statement'], 'rows': rows, 'weights': [3, 9]}},
            'cells': [], 'topics': [], 'title': '', 'schedule': False, 'takeaways': [], 'pick': True}
    assert pages.write_copy(Model([2, 0, 1, 1, 9]), page, [])['exhibits']['grid']['rows'] == [rows[2], rows[0], rows[1]]
    assert pages.write_copy(Model([0]), page, [])['exhibits']['grid']['rows'] == rows  # too few to stand as an exhibit


def test_more_than_four_notices_stay_on_the_page():
    from pptx import Presentation
    from delivery.deal_documents import deck_render
    deck = Presentation()
    deck.slide_width, deck.slide_height = deck_render.Inches(deck_render.WIDTH), deck_render.Inches(deck_render.HEIGHT)
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    deck_render._notices(slide, [(f'Heading {number}', 'A short notice.') for number in range(5)], 2)
    assert all(shape.top + shape.height <= deck.slide_height for shape in slide.shapes)


def test_a_lone_sentence_joins_its_neighbour_and_a_close_repeat_in_a_paragraph_goes():
    from delivery.deal_documents import im
    def section(*texts):
        return {'section': 'risks', 'results': {}, 'removed_sentences': [],
                'paragraphs': [{'text': text, 'source_text': text, 'cites': [str(number)], 'own_cites': [], 'calculations_used': []} for number, text in enumerate(texts)]}
    final = im.drop_repeats([section('One sentence stands alone here.', 'A second sentence follows here. A third sentence closes here.')])[0]
    assert len(final['paragraphs']) == 1 and final['paragraphs'][0]['text'].startswith('One sentence') and final['paragraphs'][0]['cites'] == ['0', '1']
    text = 'Risk stays with fronting insurer reinsurance brokers today. This structure uses fronting insurer reinsurance brokers again. Claims stay low.'
    final = im.drop_repeats([section(text)])[0]
    assert 'This structure' not in final['paragraphs'][0]['text']


def test_a_comparison_must_match_the_values_and_negatives_do_not_double():
    from delivery.deal_documents import semantics
    fact = lambda fact_id, metric, a: {'id': fact_id, 'metric': metric, 'segment': 'Total', 'period': a[0], 'value': a[1], 'unit': 'USD Mn', 'basis': 'historical', 'statement': metric}
    index = {'a': fact('a', 'Costs', ('FY21', '1.00')), 'b': fact('b', 'Costs', ('FY22', '3.00')), 'c': fact('c', 'Margin', ('FY21', '1.00')), 'd': fact('d', 'Margin', ('FY22', '22.00'))}
    calc = lambda name, a, b: semantics.compute({'id': name, 'kind': 'growth', 'a': a, 'b': b, 'rate': '', 'parts': [], 'decimals': 1}, index)
    results = {'c1': calc('c1', 'a', 'b'), 'c2': calc('c2', 'c', 'd')}
    bad = semantics.sentence_problems('Costs grew {c1}, outpacing the {c2} growth in margin.', [], results, label='p', index=index)
    good = semantics.sentence_problems('Margin grew {c2}, outpacing the {c1} growth in costs.', [], results, label='p', index=index)
    assert any('shows the opposite' in problem for problem in bad) and not any('shows the opposite' in problem for problem in good)
    results = {'c3': {'text': 'negative USD 1.29 Mn', 'kind': 'figure'}}
    assert semantics.fill_placeholders('EBITDA was negative {c3}.', results) == 'EBITDA was negative USD 1.29 Mn.'


def test_a_total_row_is_found_wherever_it_sits_in_the_table():
    from delivery.deal_documents.decks import tables_from_facts
    row = lambda number, segment, value: {'id': f'Y-p1.T1.r{number}c1', 'metric': 'Pipeline', 'segment': segment, 'period': 'FY24', 'value': value, 'unit': 'USD Mn',
                                          'statement': 's', 'table': {'id': 'Y-p1.T1', 'title': 'Pipeline'}}
    table = tables_from_facts([row(1, 'Alpha', '2.00'), row(2, 'Gamma', '9.00'), row(3, 'Beta', '3.00'), row(4, 'Delta', '4.00')])['Y-p1.T1']
    assert table['rows'][2]['label'] == 'Pipeline — Total' and table['rows'][2]['cells'][1]['segment'] == 'Total'


def test_a_run_rate_is_never_called_actual():
    from delivery.deal_documents import semantics
    index = {'a': {'id': 'a', 'metric': 'Run rate - revenue', 'segment': 'Total', 'period': 'Q4-FY22', 'value': '4.11', 'unit': 'USD Mn', 'basis': 'projection', 'statement': 'Run rate'}}
    results = {'c1': semantics.compute({'id': 'c1', 'kind': 'figure', 'a': '', 'b': '', 'rate': '', 'parts': ['a'], 'decimals': 1}, index)}
    assert any('projection or run rate' in problem for problem in semantics.sentence_problems('The projected run rate has actual revenue at {c1}.', [], results, label='p', index=index))


def test_a_section_without_a_chosen_exhibit_still_shows_its_table():
    from delivery.deal_documents import im
    from delivery.deal_documents.memo import SECTIONS
    fact_base = _im_facts()
    tables, results, index = _readings(fact_base)
    spec = next(section for section in SECTIONS if section['key'] == 'historical')
    answer = {'headline': 'Retailers buy the software.', 'exhibits': [], 'paragraphs': [{'text': 'The company sells software.', 'cites': ['X-p2.1']}, {'text': 'Retailers buy it.', 'cites': ['X-p2.1']}]}
    record = im.write_section(_FakeIMModel([answer], [], []), spec, {'positioning': 'p', 'merits': [], 'tension': 't'}, fact_base, tables, results, index)
    assert record['exhibits'][0]['table'] == 'X-p1.T1'


def test_a_last_row_that_sums_the_rows_above_is_named_as_their_total_for_any_table():
    from delivery.deal_documents.decks import tables_from_facts
    row = lambda number, segment, value: {'id': f'Y-p1.T1.r{number}c1', 'metric': 'Pipeline', 'segment': segment, 'period': 'FY24', 'value': value, 'unit': 'USD Mn',
                                          'statement': 's', 'table': {'id': 'Y-p1.T1', 'title': 'Pipeline'}}
    table = tables_from_facts([row(1, 'Alpha', '2.00'), row(2, 'Beta', '3.00'), row(3, 'Gamma', '5.00')])['Y-p1.T1']
    assert table['rows'][3]['label'] == 'Pipeline — Total'
    table = tables_from_facts([row(1, 'Alpha', '2.00'), row(2, 'Beta', '3.00'), row(3, 'Gamma', '4.00')])['Y-p1.T1']
    assert table['rows'][3]['label'] == 'Pipeline — Gamma'


def test_the_memorandum_renders_a_finding_exhibit_and_prose():
    from docx import Document
    from delivery.deal_documents import im_render
    section = {'title': 'Results', 'headline': 'Revenue tripled.', 'state': 'valid', 'paragraphs': [{'text': 'It tripled.'}],
               'exhibits': [{'title': 'Results', 'header': ['USD Mn', 'FY21', 'FY22'], 'rows': [['Revenue', '1.00', '3.00']], 'note': 'Source: deck.'}]}
    document = Document(__import__('io').BytesIO(im_render.build_docx('Synthetic Co', [('Notice', 'Text')], [section])))
    text = [paragraph.text for paragraph in document.paragraphs]
    assert 'Revenue tripled.' in text and 'Exhibit 1: Results' in text and document.tables[0].cell(1, 2).text == '3.00'


def _filled(schema):
    """The smallest answer a schema allows, so a run can be exercised without a model."""
    if 'enum' in schema:
        return schema['enum'][0]
    if schema['type'] == 'object':
        return {key: _filled(schema['properties'][key]) for key in schema.get('required', [])}
    if schema['type'] == 'array':
        return [_filled(schema['items']) for _ in range(schema.get('minItems', 0))]
    return schema.get('minimum', 0) if schema['type'] == 'integer' else ''


class _WholeRunModel:
    def __init__(self):
        self.names = []

    def json(self, name, profile, system, user, schema, *args, **kwargs):
        self.names.append(name)
        if name.startswith('thesis') and name != 'thesis-claims':
            merit = {'claim': 'Retailers buy the software.', 'proof': 'The company sells software to retailers.', 'against': 'The company sells software to retailers.'}
            return {'positioning': 'Software for retailers.', 'tension': 'Losses continue.', 'merits': [merit, merit]}
        if name.startswith('im-'):
            cite = schema['properties']['paragraphs']['items']['properties']['cites']['items'].get('enum', ['X-p2.1'])[0]
            return {'headline': 'Retailers buy the software.', 'exhibits': schema['properties']['exhibits'].get('items', {}).get('enum', [])[:1], 'paragraphs': [
                {'text': 'The company sells software to retailers.', 'cites': [cite]}, {'text': 'Retailers are its customers.', 'cites': [cite]}]}
        return _filled(schema)


def test_a_whole_memorandum_phase_runs_and_writes_every_output(tmp_path):
    import sqlite3
    from delivery.deal_documents import pipeline, runs
    from delivery.deal_documents import facts as fact_module
    conn = sqlite3.connect(tmp_path / 'app.db', isolation_level=None)
    out = tmp_path / 'run'
    out.mkdir()
    fact_base = _im_facts()
    fact_module_path = out / 'facts.json'
    fact_module_path.write_text(json.dumps(fact_base))
    run = runs.create(conn, 't1', 'w1', 'd1', 'Synthetic Co', out, 'local-model')
    runs.queue(conn, run, 'facts', 'owner')
    claimed, phase, token = runs.claim(conn)
    runs.Tracker(conn, claimed, phase, token, 'test').finish('needs_approval')
    runs.approve(conn, runs.get(conn, 't1', 'w1'), 'facts', 'operator', {'by': 'owner', 'notes': ''})
    runs.queue(conn, runs.get(conn, 't1', 'w1'), 'memo', 'owner')
    claimed, phase, token = runs.claim(conn)
    model = _WholeRunModel()
    claimed['data']['generation_path'] = 'prose'  # Exercise the optional full prose path.
    pipeline.memo_phase(runs.Tracker(conn, claimed, phase, token, 'test'), model, claimed, None)
    assert model.names.index('questions') < model.names.index('thesis') < next(i for i, name in enumerate(model.names) if name.startswith('im-'))
    for name in ('thesis.json', 'memo.json', 'memo.md', 'open_items.md', 'compliance.json', 'investment_memorandum.pptx', 'investment_memorandum.pdf'):
        assert (out / name).stat().st_size > 0, name
    memo = json.loads((out / 'memo.json').read_text())
    assert len(memo) == 12 and all(section['paragraphs'] for section in memo)


def test_a_failed_model_call_recovers_by_itself_and_lightens_the_gpu(tmp_path, monkeypatch):
    from delivery.deal_documents import llm
    monkeypatch.setattr(llm, 'NUM_GPU', '14')
    monkeypatch.setattr(llm, 'RETRY_WAIT', 0)
    attempts = []

    class Flaky:
        def chat(self, **kwargs):
            attempts.append(kwargs['options'].get('num_gpu'))
            if len(attempts) == 1:
                raise RuntimeError('CUDA error: unspecified launch failure')
            return iter([{'message': {'content': '{"ok": true}'}, 'done': True, 'done_reason': 'stop'}])
    model = llm.RecordedModel(tmp_path)
    model.clients = {host: Flaky() for host in model.clients}
    assert model.json('call', 'write', 's', 'u', {'type': 'object'}) == {'ok': True}
    assert attempts == [14, 7]
    assert len(list((tmp_path / 'calls').glob('*.json'))) == 2


def test_a_server_that_stays_down_ends_the_call_with_an_error(tmp_path, monkeypatch):
    from delivery.deal_documents import llm
    monkeypatch.setattr(llm, 'RETRY_WAIT', 0)

    class Down:
        def chat(self, **kwargs):
            raise ConnectionError('refused')
    model = llm.RecordedModel(tmp_path)
    model.clients = {host: Down() for host in model.clients}
    with pytest.raises(llm.ModelResponseError):
        model.json('call', 'write', 's', 'u', {'type': 'object'})
    assert len(list((tmp_path / 'calls').glob('*.json'))) == llm.CALL_RETRIES + 1


def test_estimate_uses_measured_step_times():
    from delivery.deal_documents.runs import estimate
    state = {'state': 'running', 'started_at': 1000, 'steps': [
        {'kind': 'write', 'state': 'done', 'seconds': 100}, {'kind': 'write', 'state': 'pending'},
        {'kind': 'check', 'state': 'pending'}]}
    view = estimate(state, now=1200)
    # The unmeasured check scales with this run's measured write speed (100 s against a 420 s default).
    assert view['elapsed_seconds'] == 100 and view['remaining_seconds'] == round(100 + 205 * 100 / 420) and view['steps_done'] == 1
    slow = {**state, 'steps': [{'kind': 'write', 'state': 'done', 'seconds': 840}, {'kind': 'review', 'state': 'pending'}]}
    assert estimate(slow, now=1200)['remaining_seconds'] == 1500 * 2  # a model twice as slow as the defaults


def test_citations_must_quote_the_cited_fact():
    from delivery.deal_documents.memo import citation_problems
    index = {'f1': {'value': '0.27', 'statement': 'Revenue — Total — Q2-FY22: 0.27 USD Mn', 'segment': 'Total', 'period': 'Q2-FY22'},
             'f9': {'value': '', 'statement': 'Contact — Email: rohan@example.com', 'segment': '', 'period': ''}}
    good = {'cites': [{'id': 'f1', 'says': 'Revenue — Total'}]}
    blind = {'cites': [{'id': 'f9', 'says': 'ARR is premium based'}]}
    assert citation_problems(1, good, index) == []
    assert 'not in that fact' in citation_problems(1, blind, index)[0]


def test_section_findings_are_filtered_to_the_section_facts():
    from delivery.deal_documents.memo import findings_summary
    base = {'checks': [{'status': 'inconsistent', 'question': 'fx', 'left_value': 1, 'right_value': 2, 'difference_pct': 50,
                        'left_expression': 'a', 'right_expression': 'b', 'a': 'cap1', 'b': 'cap2', 'rate': '', 'total': '',
                        'components': [], 'minus': []}],
            'observations': [{'severity': 'high', 'issue': 'competitors', 'facts': ['comp1']}], 'human_notes': 'date caveat'}
    scoped = findings_summary(base, {'comp1'})
    assert 'competitors' in scoped and 'fx' not in scoped and 'date caveat' in scoped
    assert 'fx' in findings_summary(base)


def test_banned_filler_matches_whole_words_only():
    assert banned_in('A robust, very large market') == ['robust', 'very']
    assert banned_in('Stronghold Ltd distributes') == []


def test_company_overview_covers_every_section_and_hides_working_notes(tmp_path):
    from api.routers.deal_documents import TOPICS, draft_sections
    assert sorted(title for _, titles in TOPICS for title in titles) == sorted(section['title'] for section in SECTIONS)
    (tmp_path / 'memo.md').write_text('# Investment memorandum — IN PROGRESS\n\n**Not reviewed.**\n\n'
                                      '## Company overview (first draft; needs review)\n\nA paragraph.\n\n- open problem: too long\n\n'
                                      '## Market opportunity (revised after review; valid)\n\nAnother.\n')
    assert draft_sections(tmp_path) == [{'title': 'Company overview', 'paragraphs': ['A paragraph.']},
                                        {'title': 'Market opportunity', 'paragraphs': ['Another.']}]
    (tmp_path / 'memo.json').write_text(json.dumps([{'title': 'Company overview', 'paragraphs': [
        {'kind': 'body', 'text': 'Final.'}, {'kind': 'question', 'text': 'Please confirm?'}]}]))
    assert draft_sections(tmp_path) == [{'title': 'Company overview', 'paragraphs': ['Final.']}]


def test_memo_structure_ends_with_summary_written_last():
    keys = [section['key'] for section in SECTIONS]
    assert keys[-1] == 'summary' and 'risks' in keys and len(keys) == len(set(keys))


def test_deck_tables_are_built_from_source_cells(tmp_path):
    from delivery.deal_documents.decks import slide_table, tables_from_facts
    facts = []
    for row, (metric, values) in enumerate([('Revenue', ['0.06', '0.27']), ('EBITDA', ['(0.53)', '(0.71)'])], 1):
        for column, value in enumerate(values, 1):
            facts.append({'id': f'X-p6.T1.r{row}c{column}', 'metric': metric, 'segment': '', 'period': ['Q1', 'Q2'][column - 1],
                          'value': value, 'unit': 'USD Mn', 'basis': 'historical', 'table': {'id': 'X-p6.T1', 'title': 'P&L'}})
    table = slide_table(tables_from_facts(facts)['X-p6.T1'], [2, 1])
    assert table['rows'] == [['EBITDA', '(0.53)', '(0.71)'], ['Revenue', '0.06', '0.27']]


def test_repetition_loop_is_detected_and_complete_items_salvaged():
    from delivery.deal_documents.llm import repeating, salvage_array
    item = '{"t": "mkt", "b": "C", "m": "Market position", "s": "", "p": "", "v": "TOP 24", "u": "", "k": "ocr", "d": ""}, '
    looped = '{"facts": [{"t": "co", "b": "H", "m": "Name", "s": "", "p": "", "v": "", "u": "", "k": "text", "d": "Acme"}, ' + item * 12 + '{"t": "mk'
    assert repeating(looped) and not repeating(looped[:300])
    schema = {'properties': {'facts': {'type': 'array'}}}
    salvaged = json.loads(salvage_array(looped, schema))
    assert salvaged['facts'][0]['d'] == 'Acme' and len(salvaged['facts']) == 13
    assert salvage_array('{"facts": [{"t": "co"', schema) is None  # nothing complete to keep


def test_phase_gate_rejects_changed_output(tmp_path):
    import scripts.deal_documents as cli
    (tmp_path / 'facts.json').write_text('{"facts": []}')
    cli.main(['approve', '--out', str(tmp_path), '--phase', 'facts', '--by', 'reviewer'])
    assert cli.require_approval(tmp_path, 'facts')['approved_by'] == 'reviewer'
    (tmp_path / 'facts.json').write_text('{"facts": [1]}')
    with pytest.raises(SystemExit):
        cli.require_approval(tmp_path, 'facts')
    assert json.loads((tmp_path / 'approvals.json').read_text())['facts']['sha256']


def test_reviewer_label_corrections_are_recorded_and_break_the_approval(tmp_path):
    import scripts.deal_documents as cli
    fact = {**_fact('x', 'ARR run rate', 'Mar 22', '27', basis='projection'), 'ocr_only': False, 'cell_error': False}
    base = {'facts': [fact], 'workbook_summary_sheets': [], 'workbook_cells': [], 'rejected': [], 'checks': [], 'observations': []}
    (tmp_path / 'facts.json').write_text(json.dumps(base))
    cli.main(['approve', '--out', str(tmp_path), '--phase', 'facts', '--by', 'reviewer'])
    (tmp_path / 'fix.json').write_text(json.dumps([{'id': 'x', 'basis': 'historical', 'reason': 'achieved milestone'}]))
    cli.main(['correct', '--out', str(tmp_path), '--file', str(tmp_path / 'fix.json'), '--by', 'reviewer'])
    saved = json.loads((tmp_path / 'facts.json').read_text())
    assert saved['facts'][0]['basis'] == 'historical' and saved['corrections'][0]['before'] == 'projection'
    assert 'achieved milestone' in (tmp_path / 'facts.md').read_text()
    with pytest.raises(SystemExit):
        cli.require_approval(tmp_path, 'facts')


def test_fact_ids_written_into_prose_are_stripped():
    from delivery.deal_documents.memo import strip_ids
    text = 'Toffee runs a B2B2C model (TID-p7.1, TID-p15.2) with partners [TII-p6.T1.r5c5].'
    assert strip_ids(text) == 'Toffee runs a B2B2C model with partners.'
    assert strip_ids('Revenue was USD 0.73 Mn (Q4-FY22).') == 'Revenue was USD 0.73 Mn (Q4-FY22).'


def test_truncated_nested_json_is_closed_after_the_last_complete_object():
    from delivery.deal_documents.llm import salvage_array
    content = ('{"calculations": [], "paragraphs": [{"kind": "evidence", "text": "A", "cites": [{"id": "x", "says": "y"}], '
               '"calculations_used": []}, {"kind": "analysis", "text": "B", "cites": [{"id": "x", "says": "y"}, {"id": "x", "sa')
    salvaged = json.loads(salvage_array(content, {}))
    assert [p['text'] for p in salvaged['paragraphs']] == ['A', 'B']


def test_wrong_citation_id_is_resolved_from_a_unique_quote():
    from delivery.deal_documents.memo import citation_problems, resolve_citations
    index = {'dist': {'value': '', 'statement': 'Distribution model: POS without FOS model', 'segment': '', 'period': ''},
             'tam': {'value': '2.7', 'statement': 'TAM — Home & Content: 2.7 USD Bn', 'segment': 'Home & Content', 'period': ''},
             'p1': {'value': '0.10', 'statement': 'Premium — Q1: 0.10 USD Mn', 'segment': '', 'period': 'Q1'},
             'p2': {'value': '0.10', 'statement': 'Revenue — Q3: 0.10 USD Mn', 'segment': '', 'period': 'Q3'}}
    paragraph = {'cites': [{'id': 'dist', 'says': '2.7 USD Bn'}, {'id': 'dist', 'says': '0.10 USD Mn'}]}
    assert resolve_citations(paragraph, index) == [('dist', 'tam')]
    assert paragraph['cites'][0]['id'] == 'tam'
    assert len(citation_problems(1, paragraph, index)) == 1  # the ambiguous 0.10 quote stays flagged


def test_cites_prefix_references_are_stripped():
    from delivery.deal_documents.memo import strip_ids
    assert strip_ids('Margin rose (cites: TID-p7.1, TII-p3.1) and fell (calc: calc_ratio).') == 'Margin rose and fell.'


def test_ordinary_parentheticals_are_not_stripped():
    from delivery.deal_documents.memo import strip_ids
    for text in ('Revenue (INR-denominated) rose.', 'Targets (FY-23) were met.', 'Premium (Q4-FY22) was 0.20.'):
        assert strip_ids(text) == text


def test_a_bare_value_with_unit_is_a_valid_quote():
    from delivery.deal_documents.memo import citation_problems
    index = {'nm': {'value': '8', 'statement': 'Net Margin — EV & TW (Motor): 8 %', 'segment': 'EV & TW (Motor)', 'period': ''}}
    assert citation_problems(1, {'cites': [{'id': 'nm', 'says': '8 %'}]}, index) == []
    assert citation_problems(1, {'cites': [{'id': 'nm', 'says': '9 %'}]}, index) != []


def test_routes_send_profiles_to_their_servers_and_refuse_non_loopback(tmp_path, monkeypatch):
    from delivery.deal_documents import llm
    with pytest.raises(ValueError):
        llm.parse_routes('write=http://10.0.0.5:11434')
    with pytest.raises(ValueError):
        llm.parse_routes('nonsense=http://127.0.0.1:11435')
    monkeypatch.setattr(llm, 'ROUTES', 'write=http://127.0.0.1:11435|http://127.0.0.1:11436,review=http://127.0.0.1:11436')
    model = llm.RecordedModel(tmp_path, 'qwen3:32b')

    class Client:
        def __init__(self, host):
            self.host, self.calls = host, 0

        def chat(self, **kwargs):
            self.calls += 1
            return iter([{'message': {'content': '{"ok": true}'}, 'done': True, 'done_reason': 'stop'}])
    model.clients = {host: Client(host) for host in model.clients}
    model.json('a', 'review', 's', 'u', {'type': 'object'})
    assert model.clients['http://127.0.0.1:11436'].calls == 1
    model.json('b', 'check', 's', 'u', {'type': 'object'})
    assert model.clients[llm.OLLAMA_HOST.rstrip('/')].calls == 1
    # A busy writer server sends the next writing call to the other one; idle, the thread keeps its server.
    model.busy['http://127.0.0.1:11436'] = 1
    model.json('c', 'write', 's', 'u', {'type': 'object'})
    assert model.clients['http://127.0.0.1:11435'].calls == 1
    model.busy['http://127.0.0.1:11436'] = 0
    model.json('d', 'write', 's', 'u', {'type': 'object'})
    assert model.clients['http://127.0.0.1:11435'].calls == 2
    assert set(model.busy.values()) == {0}
    assert json.loads(next(tmp_path.glob('calls/*-d.json')).read_text())['host'] == 'http://127.0.0.1:11435'



def _cell(table, row, column, metric, period, value, basis='historical', unit='USD Mn', segment='Total'):
    fact = _fact(f'{table}.r{row}c{column}', metric, period, value, basis=basis, unit=unit, segment=segment)
    return {**fact, 'table': {'id': table, 'title': 'Financial Snapshot'}, 'location': 'p6', 'topic': 'historical_financials',
            'cell_error': False}


def _deck_facts():
    periods = ['Q1-FY22', 'Q2-FY22', 'Q3-FY22', 'Q4-FY22', 'FY22']
    facts = [_cell('X-p6.T1', 1, c, 'Revenue', p, v) for c, (p, v) in enumerate(zip(periods, ['0.06', '0.27', '0.40', '0.73', '1.46']), 1)]
    facts += [_cell('X-p6.T1', 2, c, 'EBITDA', p, v) for c, (p, v) in enumerate(zip(periods, ['(0.53)', '(0.71)', '(0.70)', '(1.00)', '(2.94)']), 1)]
    facts += [_cell('X-p6.T2', 1, c, 'Revenue', p, v, basis='projection')
              for c, (p, v) in enumerate(zip(['OND 22', 'JFM 23', 'Total'], ['2.33', '2.98', '5.31']), 1)]
    facts += [_cell('X-p8.T1', 1, 1, 'Equity Raised', 'Current', '580.47', unit='INR Million'),
              _cell('X-p8.T1', 1, 2, 'Equity Raised', 'Current', '8.29', unit='USD Mn')]
    return facts


def test_a_chart_is_drawn_from_source_cells_and_never_mixes_totals_into_a_trend():
    from delivery.deal_documents.decks import fact_chart, tables_from_facts
    tables = tables_from_facts(_deck_facts())
    chart = fact_chart(tables['X-p6.T1'], [1, 2], 'column')
    assert chart['categories'] == ['Q1-FY22', 'Q2-FY22', 'Q3-FY22', 'Q4-FY22']  # FY22 is a different length
    assert [s['name'] for s in chart['series']] == ['Revenue', 'EBITDA']
    assert chart['series'][1]['values'] == [-0.53, -0.71, -0.7, -1.0] and chart['decimals'] == 2
    assert 'not independently verified' in chart['note']
    projected = fact_chart(tables['X-p6.T2'], [1], 'line')
    assert projected['categories'] == ['OND 22 (P)', 'JFM 23 (P)'] and 'company projection' in projected['note']
    with pytest.raises(ValueError):
        fact_chart(tables['X-p6.T1'], [9], 'column')
    with pytest.raises(ValueError):  # one figure in two currencies has no period axis
        fact_chart(tables['X-p8.T1'], [1], 'column')


def test_a_slide_table_prints_source_values_with_no_ids_and_labels_each_currency():
    from delivery.deal_documents.decks import slide_table, tables_from_facts
    table = slide_table(tables_from_facts(_deck_facts())['X-p8.T1'], [1])
    assert table['header'] == ['Item', 'Current (INR Million)', 'Current (USD Mn)']
    assert table['rows'] == [['Equity Raised', '580.47', '8.29']]


def _slide_draft(headline, bullets, visual=None, calculations=()):
    cite = {'id': 'X-p6.T1.r1c4', 'says': '0.73'}
    return {'calculations': list(calculations), 'visual': visual or {'type': 'none', 'table': '', 'rows': [], 'plot': 'column'},
            'paragraphs': [{'kind': 'headline', 'text': headline, 'cites': [dict(cite)]}] +
                          [{'kind': 'evidence', 'text': text, 'cites': [dict(cite)]} for text in bullets]}


def test_slides_pass_the_memo_rules_and_their_own_shape_checks():
    from delivery.deal_documents.decks import BY_KEY, tables_from_facts, validate_slide
    facts = _deck_facts()
    index, tables = {fact['id']: fact for fact in facts}, tables_from_facts(facts)
    spec = BY_KEY['historical']
    growth = [_calc('c1', 'growth', a='X-p6.T1.r1c2', b='X-p6.T1.r1c4')]
    chart = {'type': 'chart', 'table': 'X-p6.T1', 'rows': [1, 2], 'plot': 'column'}
    message = 'Quarterly revenue is rising while EBITDA losses continue'

    def problems(headline, bullets, visual=chart):
        return ' | '.join(validate_slide(spec, _slide_draft(headline, bullets, visual, growth), index, tables)[0])
    assert problems(message, ['{c1}. The cost base has not yet scaled down.']) == ''
    assert '0.73' in problems('Revenue reached USD 0.73 Mn in Q4-FY22', ['{c1}.'])
    assert 'ranks or compares' in problems('Quarterly revenue is the highest in Q4-FY22', ['{c1}.'])
    assert 'topic label' in problems('Financial performance', ['{c1}.'])
    assert 'needs a chart' in problems(message, ['{c1}.'], None)
    assert 'beside a visual' in problems(message, ['{c1}.', 'Costs persist.', 'Hiring continues.'])


class _FakeDeckModel:
    def __init__(self):
        self.calls = []

    def json(self, name, profile, system, user, schema, images=(), settings=None, meta=None):
        from delivery.deal_documents.review import AREAS
        self.calls.append(name)
        return {'areas': [{'area': area, 'status': 'adequate', 'reason': 'Fine.'} for area in AREAS], 'findings': []}


def test_the_decks_are_the_reviewed_pages_in_the_fundraising_order(tmp_path):
    import sqlite3
    from pptx import Presentation
    from delivery.deal_documents import pipeline, runs
    from delivery.deal_documents.decks import tables_from_facts
    from delivery.deal_documents import pages
    conn = sqlite3.connect(tmp_path / 'app.db', isolation_level=None, check_same_thread=False)
    out = tmp_path / 'run'
    out.mkdir()
    run = runs.create(conn, 't1', 'w1', 'd1', 'Synthetic Co', out, 'local-model')
    facts, _ = _page_tables()
    base = {'facts': facts, 'workbook_cells': [], 'checks': [], 'observations': []}
    (out / 'facts.json').write_text(json.dumps(base))
    built = pages.build(base)
    for page in built:
        page.update(title=page['title'] or 'Sales tripled as partners went live', takeaways=['One.', 'Two.', 'Three.'] if page['key'] == 'trend' else [])
    (out / 'pages.json').write_text(json.dumps(built))

    def approved(data):
        data['phases']['facts'].update(state='approved', approvals={'operator': {'notes': '', 'sha256': 'f' * 64}})
        data['phases']['memo'].update(state='approved', approvals={'operator': {'sha256': 'e' * 64}})
        data['phases']['decks'].update(state='queued')
    runs.update(conn, run['id'], approved)
    run, phase, token = runs.claim(conn)
    assert phase == 'decks'
    model = _FakeDeckModel()
    pipeline.decks_phase(runs.Tracker(conn, run, phase, token, 'test'), model, run, None)
    assert model.calls == ['deck-compliance']
    decks = json.loads((out / 'decks.json').read_text())
    keys = [page['key'] for page in decks['pitch_deck']]
    assert keys.index('snapshot') < keys.index('trend') < keys.index('risks') < keys.index('transaction') == len(keys) - 1
    assert 'financials' not in keys and len(decks['intro_deck']) < len(keys)
    assert len(next(page for page in decks['pitch_deck'] if page['key'] == 'trend')['takeaways']) == 2
    pitch = Presentation(out / 'pitch_deck.pptx')
    assert len(pitch.slides) == len(keys) + 2  # the cover and the notice
    introduction = Presentation(out / 'intro_deck.pptx')
    assert len(introduction.slides) == len(decks['intro_deck']) + 2
    shown = ' '.join(shape.text_frame.text for slide in pitch.slides for shape in slide.shapes if shape.has_text_frame)
    assert 'Pitch deck' in shown and 'Important notice' in shown and 'Synthetic Co' in shown and 'Investment memorandum' not in shown
    assert 'Contents' not in shown and 'Executive summary' not in shown
    assert (out / 'pitch_deck.pdf').read_bytes()[:4] == b'%PDF' and (out / 'intro_deck.pdf').read_bytes()[:4] == b'%PDF'
    assert 'Sales tripled' in (out / 'decks.md').read_text() and (out / 'deck_compliance.md').exists()


def test_a_revision_is_held_to_the_memorandum_voice_and_gaps_go_to_the_company():
    from delivery.deal_documents.memo import investor_paragraphs, open_items_markdown, voice_problems
    def draft(text, kind='analysis'):
        return {'paragraphs': [{'kind': kind, 'text': text, 'cites': []}]}
    historical, risks = {'key': 'historical'}, {'key': 'risks'}
    assert voice_problems(historical, draft('The materials do not define revenue.'))
    assert voice_problems(historical, draft('An investor cannot assess unit economics.'))
    assert voice_problems(historical, draft('Counsel should confirm the licence.'))
    assert voice_problems(historical, draft('The company does not explain the ARR calculation.'))
    assert voice_problems(risks, draft('The company does not explain the ARR calculation.')) == []  # risks exist to state limits
    assert voice_problems(risks, draft('The materials are dated.'))
    assert voice_problems(historical, draft('What does ARR include in the materials?', 'question')) == []
    assert voice_problems(historical, draft('ARR is stated on premium, not revenue.')) == []
    section = {'section': 'historical', 'title': 'Historical', 'paragraphs': [
        {'kind': 'evidence', 'text': 'Revenue rose.', 'cites': []}, {'kind': 'question', 'text': 'How is ARR calculated?', 'cites': []}]}
    assert [p['kind'] for p in investor_paragraphs(section)] == ['evidence']
    listed = open_items_markdown([section], 'Synthetic Co')
    assert 'How is ARR calculated?' in listed and 'Revenue rose.' not in listed


def test_a_run_rate_period_is_not_called_a_run_rate_twice():
    result = compute({'id': 'c1', 'kind': 'figure', 'a': '', 'b': '', 'rate': '', 'parts': ['rr'], 'decimals': 2}, REVENUE)
    assert 'FY23 Exit Run Rate' in result['sentence'] and 'run rate run rate' not in result['sentence'].lower()


def test_the_information_age_counts_months_from_the_latest_reported_period():
    import datetime
    from delivery.deal_documents.compliance import information_age
    fact_base = {'facts': [_fact('q', 'Revenue', 'Q1-FY23', '1.16')]}
    label, age = information_age(fact_base, datetime.date(2026, 10, 30))
    assert label == 'Q1-FY23' and age == 52


def test_a_restart_keeps_measured_times_and_the_estimate_ignores_stopped_time():
    from delivery.deal_documents import runs
    now = 1_000_000.0
    done = [{'kind': 'write', 'state': 'done', 'seconds': 1000, 'cached': True}, {'kind': 'write', 'state': 'done', 'seconds': 1400, 'cached': True},
            {'kind': 'write', 'state': 'done', 'seconds': 1200}]
    phase = {'state': 'running', 'started_at': now - 172800, 'steps': done + [
        {'kind': 'write', 'state': 'running', 'started': now - 100}, {'kind': 'write', 'state': 'pending'}, {'kind': 'revise', 'state': 'pending'}]}
    estimate = runs.estimate(phase, now)
    assert estimate['elapsed_seconds'] == 3700  # worked time, not the two days since the phase first started
    assert estimate['remaining_seconds'] == round(1100 + 1200 + 1200)
    assert estimate['remaining_low'] < estimate['remaining_seconds'] < estimate['remaining_high']
    assert estimate['measured_steps'] == 3
    overdue = runs.estimate({'state': 'running', 'steps': done + [{'kind': 'write', 'state': 'running', 'started': now - 9000}]}, now)
    assert overdue['remaining_seconds'] == 180  # past its expected time it is still running, so not nearly finished


def test_a_saved_step_keeps_its_seconds_for_the_estimate(tmp_path):
    import sqlite3
    from delivery.deal_documents import runs
    conn = sqlite3.connect(tmp_path / 'app.db', isolation_level=None)
    run = runs.create(conn, 't1', 'w1', 'd1', 'Synthetic Co', tmp_path, 'local-model')
    runs.update(conn, run['id'], lambda data: data['phases']['memo'].update(state='queued'))
    run, phase, token = runs.claim(conn)
    tracker = runs.Tracker(conn, run, phase, token, 'test')
    tracker.plan([('s', 'Step', 'write')])
    import time
    tracker.step('s', [1], lambda: time.sleep(.2) or 'done')
    runs.update(conn, run['id'], lambda data: data['phases']['memo']['steps'][0].update(seconds=None))  # as after a restart
    tracker.step('s', [1], lambda: 'not run again')
    saved = runs.get_by_id(conn, run['id'])['data']['phases']['memo']['steps'][0]
    assert saved['cached'] and saved['seconds'] is not None


def _sample_facts():
    return {'facts': [_fact('q', 'Revenue', 'Q1-FY23', '1.16')], 'workbook_cells': [],
            'checks': [{'status': 'inconsistent', 'question': 'Check conversion', 'left_value': 7.74, 'right_value': 8.29, 'difference_pct': 6.6,
                        'left_expression': 'INR at 75', 'right_expression': 'stated USD'}],
            'observations': [{'severity': 'high', 'issue': 'ARR cannot be tied to premium', 'facts': ['q']},
                             {'severity': 'low', 'issue': 'Minor wording', 'facts': []}]}


def test_the_system_finds_what_to_ask_and_confidence_comes_from_the_evidence():
    import datetime
    from delivery.deal_documents.questions import candidates, fallback
    found = candidates(_sample_facts(), [{'section': 'historical', 'paragraphs': [
        {'kind': 'question', 'text': 'How is ARR calculated?', 'cites': ['q']}]}], datetime.date(2026, 10, 30))
    by_basis = {item['basis'] for item in found}
    assert by_basis == {'information_age', 'calculation', 'missing_disclosure', 'analyst', 'writer_gap'}
    assert not any('Minor wording' in item['text'] for item in found)
    assert any('52 months' in item['text'] and item['severity'] == 'high' for item in found)
    asked = fallback(found)
    assert asked[0]['severity'] == 'blocker' and asked[0]['confidence'] == 90
    assert next(q for q in asked if 'ARR cannot' in q['text'])['confidence'] == 70


def test_the_asking_agent_cannot_invent_or_drop_what_code_proved():
    import datetime
    from delivery.deal_documents.questions import ask, candidates

    class Agent:
        def json(self, name, profile, system, user, schema, **kwargs):
            assert 'rests on:' in user
            return {'questions': [{'text': 'Which rate is right, 75 or the implied rate? Send the board-approved cap table.',
                                   'why': 'Valuation depends on it.', 'severity': 'high', 'sections': ['capital'], 'sources': ['F2', 'F6'], 'facts': []},
                                  {'text': 'Why does revenue exceed gross premium?', 'why': 'Take rate.', 'severity': 'high', 'sections': [],
                                   'sources': [], 'facts': ['q', 'invented-id']},
                                  {'text': 'Something with no evidence?', 'why': 'None.', 'severity': 'high', 'sections': [], 'sources': [], 'facts': ['invented-id']}]}
    facts = _sample_facts()
    found = candidates(facts, (), datetime.date(2026, 10, 30))
    assert [item['id'] for item in found][:2] == ['F1', 'F2'] and found[1]['basis'] == 'calculation'
    analyst = next(item['id'] for item in found if item['basis'] == 'analyst')
    assert analyst == 'F6'
    asked = ask(Agent(), facts, ['capital'], found)
    assert asked[0]['confidence'] == 98  # proven by calculation, and a different kind of evidence agrees
    assert any('52 months' in q['text'] for q in asked)  # the agent left it out; code still asks
    assert sum('Related-party' in q['text'] for q in asked) == 1
    assert next(q for q in asked if 'exceed gross premium' in q['text'])['confidence'] == 55
    assert not any('no evidence' in q['text'] for q in asked)


def test_answers_become_citable_company_statements():
    from delivery.deal_documents.questions import answer_facts, answer_notes
    questions = [{'text': 'Which rate?', 'sections': ['capital'], 'answer': {'text': 'USD 8.29 Mn used 70 INR/USD.'}},
                 {'text': 'Unanswered?', 'sections': [], 'answer': None}]
    fact = answer_facts(questions)[0]
    assert fact['id'] == 'ANS-p1.1' and fact['basis'] == 'company_claim' and 'Company response' in fact['statement']
    assert 'ANS-p1.1' in answer_notes(questions, 'capital') and answer_notes(questions, 'team') == ''


def test_readiness_is_calculated_and_capped_by_what_only_people_can_settle():
    from delivery.deal_documents.questions import readiness
    units = [{'paragraphs': [{}], 'problems': []}, {'paragraphs': [{}], 'problems': ['x']}]
    assessed = {'a': {'issues': 1, 'score': {'overall': 80}}, 'b': {'issues': 0, 'score': {'overall': 90}}}
    blocked = readiness(units, assessed, [{'severity': 'blocker', 'answer': None}])
    assert blocked['cap'] == 69 and blocked['score'] <= 69 and 'blocking' in blocked['cap_reason']
    answered = readiness(units, assessed, [{'severity': 'blocker', 'answer': {'text': 'x'}}])
    assert answered['cap'] == 89 and 'compliance' in answered['cap_reason'] and answered['score'] > blocked['score']
    assert readiness(units, assessed, [], signed_off=True)['cap'] == 100
    assert {part['key'] for part in blocked['parts']} == {'evidence', 'review', 'quality', 'questions'}


def _reading(problems=0, issues=0, points=70, failures=()):
    return {'problems': problems, 'issues': issues, 'found': [], 'score': {'overall': points, 'criteria': {'voice': 3}, 'weakest': 'x', 'change': 'y'},
            'failures': list(failures)}


def test_a_candidate_must_beat_the_best_and_accuracy_outranks_polish():
    from delivery.deal_documents.climb import better, finished
    best = _reading(points=70)
    assert better(_reading(points=73), best)
    assert not better(_reading(points=72), best)  # within the scorer's noise
    assert not better(_reading(issues=1, points=99), best)  # polish cannot buy a wrong sentence
    assert better(_reading(issues=0, points=10), _reading(issues=2, points=90))
    assert not better(_reading(points=90, failures=['scorer: timeout']), best)
    assert finished(_reading(points=85)) and not finished(_reading(points=84)) and not finished(_reading(issues=1, points=99))


def test_the_climb_keeps_only_improvements_and_stops_when_a_round_gains_nothing():
    from delivery.deal_documents.climb import climb
    parts = {'a': {'title': 'A', 'state': 'valid', 'paragraphs': [{}], 'version': 0}, 'b': {'title': 'B', 'state': 'valid', 'paragraphs': [{}], 'version': 0}}
    rounds = []

    def assess(items, number):
        return [_reading(points={('a', 0): 60, ('b', 0): 90, ('a', 1): 80, ('a', 2): 79}[key, part['version']]) for key, part in items]

    def rewrite(items, number):
        rounds.append([key for key, _, _ in items])
        return [{**part, 'version': number} for _, part, _ in items]
    best, assessed, history = climb(parts, assess, rewrite, lambda number, todo: None, passes=5)
    assert rounds == [['a'], ['a']]  # b was at target; round 2 gained nothing, so the climb stopped before the budget
    assert best['a']['version'] == 1 and assessed['a']['score']['overall'] == 80  # the worse second version was discarded
    assert best['b']['version'] == 0
    assert [entry['kept'] for entry in history[1:]] == [['a'], []]


def test_routes_review_agents_to_their_own_model(tmp_path, monkeypatch):
    from delivery.deal_documents import llm
    monkeypatch.setattr(llm, 'REVIEW_MODEL', 'qwen3:14b')
    model = llm.RecordedModel(tmp_path, 'qwen3:32b')
    used = []

    class Client:
        def chat(self, **kwargs):
            used.append(kwargs['model'])
            return iter([{'message': {'content': '{"ok": true}'}, 'done': True, 'done_reason': 'stop'}])
    model.clients = {host: Client() for host in model.clients}
    for profile in ('write', 'check', 'score'):
        model.json(profile, profile, 's', 'u', {'type': 'object'})
    assert used == ['qwen3:32b', 'qwen3:14b', 'qwen3:14b']
