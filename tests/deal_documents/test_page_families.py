"""Synthetic evidence for the analytical page families and their refusal boundaries."""
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from delivery.deal_documents import pages


def cell(number, metric, value, period='', unit='currency units', segment='', **extra):
    return {'id': f'S.c{number}', 'source': 'S', 'document': 'Synthetic schedule', 'location': f'sheet Plan cell C{number}',
            'metric': metric, 'value': str(value), 'unit': unit, 'period': period, 'segment': segment,
            'basis': 'projection', 'topic': 'company_model', 'statement': f'{metric}: {value}', **extra}


def cash_cells():
    return [cell(1, 'Opening cash', 10), cell(2, 'Minimum cash buffer', 2),
            *[cell(3 + index, 'Cash flow before financing', value, period) for index, (period, value) in enumerate(zip(('Jan-30', 'Feb-30', 'Mar-30'), (-6, -8, 5)))],
            *[cell(6 + index, 'Financing inflow', value, period) for index, (period, value) in enumerate(zip(('Jan-30', 'Feb-30', 'Mar-30'), (0, 10, 0)))]]


def case_cells():
    return [cell(index, 'Output', value, f'{case} case | FY30', unit='items')
            for index, (case, value) in enumerate((('Base', 100), ('Downside', 60), ('Upside', 140)), 1)]


def unit_cells():
    return [cell(1, 'Units sold', 4, 'FY30', 'items'), cell(2, 'Contribution', 20, 'FY30'), cell(3, 'Invested capital', 60, 'FY30')]


def peer_cells():
    return [cell(index, 'Defined productivity', value, 'FY30', 'items / worker', segment=f'Peer {index}', topic='competition', basis='third_party')
            for index, value in enumerate((8, 12, 16), 1)]


def return_cells():
    return [cell(1, 'Entry post-money equity valuation', 100, case='base'), cell(2, 'Exit equity valuation', 200, case='base'),
            cell(3, 'Investor ownership', 25, unit='%', case='base'), cell(4, 'Holding period', 2, unit='years', case='base'),
            cell(5, 'Interim distributions', 0, case='base')]


def transaction_cells():
    return [cell(1, 'Source', 20, segment='New capital'), cell(2, 'Source', 30, segment='Rollover'),
            cell(3, 'Use', 45, segment='Acquisition'), cell(4, 'Use', 5, segment='Fees'),
            cell(5, 'Instrument', '', unit='', statement='Instrument: Ordinary equity', basis='company_claim')]


FAMILIES = [('funding_plan', cash_cells, pages.funding_plan), ('operating_cases', case_cells, pages.operating_cases),
            ('unit_economics', unit_cells, pages.unit_economics), ('peer_benchmarks', peer_cells, pages.peer_benchmarks),
            ('investor_returns', return_cells, pages.investor_returns), ('transaction_summary', transaction_cells, pages.transaction_summary)]


def groups(cells):
    return pages._family_groups({'facts': cells, 'workbook_cells': []})


class FamilyCalculationTests(unittest.TestCase):
    def test_every_family_accepts_cited_data_and_abstains_without_it(self):
        for name, factory, builder in FAMILIES:
            with self.subTest(family=name):
                source = factory()
                found = builder(groups(source))
                self.assertIsNotNone(found)
                self.assertTrue(set(found[1]) <= {item['id'] for item in source})
                self.assertIsNone(builder([]))

    def test_cash_trough_runway_and_raise_are_recomputed(self):
        exhibit, cited = pages.funding_plan(groups(cash_cells()))
        self.assertEqual(exhibit['chart']['series'][0]['values'], [4, -4, 1])
        self.assertEqual(exhibit['chart']['series'][1]['values'], [4, 6, 11])
        self.assertEqual(exhibit['kpis'][0]['value'], '6.00 currency units')
        self.assertEqual(exhibit['kpis'][1]['value'], '1 months')
        self.assertEqual(exhibit['grid']['rows'][1][-2:], ['(4.00)', '6.00'])
        self.assertEqual(set(cited), {item['id'] for item in cash_cells()})

    def test_cash_missing_is_never_zero_and_profit_is_not_cash(self):
        for missing in range(len(cash_cells())):
            source = cash_cells()
            del source[missing]
            with self.subTest(missing=missing):
                self.assertIsNone(pages.funding_plan(groups(source)))
        source = cash_cells()
        for item in source:
            if item['metric'] == 'Cash flow before financing':
                item['metric'] = 'Operating profit'
        self.assertIsNone(pages.funding_plan(groups(source)))

    def test_cash_period_gaps_duplicates_and_mixed_units_abstain(self):
        for field, value in (('period', 'Apr-30'), ('period', 'Jan-30'), ('unit', 'other units'), ('value', ''), ('basis', 'target')):
            source = cash_cells()
            source[3][field] = value
            with self.subTest(field=field, value=value):
                self.assertIsNone(pages.funding_plan(groups(source)))

    def test_cash_historical_opening_and_annual_horizon_are_supported(self):
        source = cash_cells()
        source[0]['basis'] = 'historical'
        for item in source[2:]:
            item['period'] = {'Jan-30': 'FY30', 'Feb-30': 'FY31', 'Mar-30': 'FY32'}[item['period']]
        exhibit, _ = pages.funding_plan(groups(source))
        self.assertEqual(exhibit['kpis'][1]['value'], '12 months')
        for item in source[2:5]:
            item['value'] = '1'
        exhibit, _ = pages.funding_plan(groups(source))
        self.assertEqual(exhibit['kpis'][1]['value'], '36 months')
        self.assertIn('At least', exhibit['kpis'][1]['sub'])

    def test_source_case_columns_compare_without_inventing_a_case(self):
        source = case_cells()
        exhibit, cited = pages.operating_cases(groups(source))
        rows = exhibit['grid']['rows']
        self.assertEqual([row[-2:] for row in rows], [['100.00', '0.00'], ['60.00', '(40.00)'], ['140.00', '40.00']])
        self.assertEqual(len(cited), 3)
        self.assertIsNone(pages.operating_cases(groups(source[:1])))
        for item in source:
            item['period'] = 'FY30'
        self.assertIsNone(pages.operating_cases(groups(source)))

    def test_workbook_case_headers_and_unit_labels_are_used(self):
        source = case_cells()
        for item in source:
            item['metric'], item['unit'] = 'Output (items)', ''
        parsed = pages._family_groups({'facts': [], 'workbook_cells': source})
        self.assertIsNotNone(pages.operating_cases(parsed))
        self.assertEqual(parsed[0][0]['unit'], 'items')
        self.assertEqual(parsed[0][0]['case'], 'base')
        for item in source:
            item['metric'] = 'Output'
        self.assertIsNone(pages.operating_cases(pages._family_groups({'facts': [], 'workbook_cells': source})))

    def test_cases_do_not_cross_dates_basis_units_versions_or_sources(self):
        for field, value in (('period', 'Downside case | FY31'), ('unit', 'other units'), ('basis', 'historical'), ('version', 'other'), ('source', 'other')):
            source = case_cells()[:2]
            source[1][field] = value
            with self.subTest(field=field):
                self.assertIsNone(pages.operating_cases(groups(source)))

    def test_duplicate_or_ambiguous_cases_are_not_silently_overwritten(self):
        source = case_cells()[:2]
        source.append({**source[0], 'id': 'duplicate', 'value': '900'})
        self.assertIsNone(pages.operating_cases(groups(source)))
        source = case_cells()[:2]
        source[1]['ambiguity'] = 'Case label unreadable'
        self.assertIsNone(pages.operating_cases(groups(source)))

    def test_units_and_capital_are_separate_from_payback(self):
        exhibit, _ = pages.unit_economics(groups(unit_cells()))
        self.assertEqual(exhibit['grid']['rows'][0][-2:], ['5.00 currency units / items', '15.00 currency units / items'])
        exhibit, _ = pages.unit_economics(groups(unit_cells()[:2]))
        self.assertEqual(exhibit['grid']['rows'][0][-1], 'Not supplied')
        self.assertNotIn('payback', str(exhibit).lower())
        source = unit_cells()
        source[1]['value'] = '-20'
        self.assertIn('(5.00)', str(pages.unit_economics(groups(source))))

    def test_unit_economics_refuses_zero_missing_or_unmatched_denominators(self):
        for index, field, value in ((0, 'value', '0'), (0, 'value', ''), (0, 'value', '-1'), (0, 'unit', ''),
                                    (1, 'period', 'FY31'), (1, 'segment', 'Other'), (1, 'unit', '%'), (1, 'unit', 'currency units / item')):
            source = unit_cells()
            source[index][field] = value
            with self.subTest(index=index, field=field, value=value):
                self.assertIsNone(pages.unit_economics(groups(source)))

    def test_peer_statistics_use_only_matched_cited_observations(self):
        exhibit, cited = pages.peer_benchmarks(groups(peer_cells()))
        self.assertEqual(exhibit['grid']['rows'][-2:], [['Mean of cited peers', '12.00'], ['Median of cited peers', '12.00']])
        self.assertEqual(len(cited), 3)
        self.assertIsNone(pages.peer_benchmarks(groups(peer_cells()[:1])))

    def test_customers_and_unmatched_peer_definitions_are_not_comparables(self):
        for field, value in (('topic', 'distribution'), ('period', 'FY31'), ('basis', 'projection'), ('unit', 'other units'), ('definition', 'different definition')):
            source = peer_cells()[:2]
            source[1][field] = value
            with self.subTest(field=field):
                self.assertIsNone(pages.peer_benchmarks(groups(source)))

    def test_returns_are_computed_from_entry_exit_and_supplied_stake(self):
        exhibit, cited = pages.investor_returns(groups(return_cells()))
        rows = exhibit['grid']['rows']
        self.assertEqual(rows[3][2], '25.00 currency units')
        self.assertEqual(rows[4][2], '50.00 currency units')
        self.assertEqual(rows[5][2], '2.00x')
        self.assertIn('41.42%', rows[6][2])
        self.assertEqual(len(cited), 5)

    def test_returns_require_the_entire_chain_and_never_invent_an_exit(self):
        for missing in range(3):
            source = return_cells()
            del source[missing]
            self.assertIsNone(pages.investor_returns(groups(source)))
        for index, field, value in ((0, 'value', '0'), (0, 'metric', 'Entry enterprise valuation'), (1, 'metric', 'Exit revenue run rate'),
                                    (1, 'unit', 'other units'), (2, 'value', '110'), (2, 'value', '0'), (1, 'case', 'downside')):
            source = return_cells()
            source[index][field] = value
            with self.subTest(index=index, field=field, value=value):
                self.assertIsNone(pages.investor_returns(groups(source)))

    def test_exit_multiple_requires_dated_earnings_debt_and_cash(self):
        source = [item for item in return_cells() if item['metric'] != 'Exit equity valuation']
        inputs = [cell(6, 'Exit EBITDA', 30, 'FY32', case='base'), cell(7, 'Exit EV / EBITDA multiple', 5, 'FY32', unit='x', case='base'),
                  cell(8, 'Exit debt', 20, 'FY32', case='base'), cell(9, 'Exit cash', 10, 'FY32', case='base')]
        exhibit, cited = pages.investor_returns(groups(source + inputs))
        rows = {row[1]: row[2] for row in exhibit['grid']['rows']}
        self.assertEqual(rows['Computed exit enterprise value'], '150.00 currency units')
        self.assertEqual(rows['Exit equity valuation'], '140.00 currency units')
        self.assertEqual(rows['Terminal value of supplied stake'], '35.00 currency units')
        self.assertEqual(rows['Terminal value / entry cost'], '1.40x')
        self.assertTrue({item['id'] for item in inputs} <= set(cited))
        for missing in range(len(inputs)):
            self.assertIsNone(pages.investor_returns(groups(source + inputs[:missing] + inputs[missing + 1:])))
        inputs[-1]['period'] = 'FY31'
        self.assertIsNone(pages.investor_returns(groups(source + inputs)))

    def test_explicit_exit_dilution_is_used(self):
        source = return_cells() + [cell(6, 'Exit ownership', 10, unit='%', case='base')]
        exhibit, cited = pages.investor_returns(groups(source))
        rows = {row[1]: row[2] for row in exhibit['grid']['rows']}
        self.assertEqual(rows['Terminal value of supplied stake'], '20.00 currency units')
        self.assertEqual(rows['Terminal value / entry cost'], '0.80x')
        self.assertIn('S.c6', cited)

    def test_dated_entry_ownership_does_not_establish_exit_ownership(self):
        source = return_cells()
        source[2]['period'] = 'FY30'
        self.assertIsNone(pages.investor_returns(groups(source)))
        source.append(cell(6, 'Exit ownership', 20, 'FY32', unit='%', case='base'))
        self.assertIsNotNone(pages.investor_returns(groups(source)))

    def test_conflicting_optional_return_inputs_do_not_fall_back_to_defaults(self):
        for metric, unit, values in (('Exit ownership', '%', (10, 20)), ('Entry investment', 'currency units', (25, 30)),
                                     ('Holding period', 'years', (2, 3))):
            source = [item for item in return_cells() if item['metric'] != metric]
            source += [cell(6, metric, values[0], unit=unit, case='base'), cell(7, metric, values[1], unit=unit, case='base')]
            self.assertIsNone(pages.investor_returns(groups(source)))

    def test_annualisation_requires_supplied_duration_and_zero_interim_distributions(self):
        for source in (return_cells()[:3], return_cells()[:4], [*return_cells()[:4], {**return_cells()[4], 'value': '5'}]):
            exhibit, _ = pages.investor_returns(groups(source))
            self.assertEqual(exhibit['grid']['rows'][6][2], 'Not supported')
        source = return_cells()
        source[1]['value'] = '0'
        exhibit, _ = pages.investor_returns(groups(source))
        self.assertIn('-100.00%', exhibit['grid']['rows'][6][2])
        source = return_cells() + [cell(6, 'Entry investment', 30, case='base')]
        self.assertIsNone(pages.investor_returns(groups(source)))

    def test_sources_and_uses_reconcile_with_all_terms_cited(self):
        exhibit, cited = pages.transaction_summary(groups(transaction_cells()))
        rows = exhibit['grid']['rows']
        self.assertIn(['Source', 'Total sources', '50.00', '100.0%'], rows)
        self.assertIn(['Use', 'Total uses', '50.00', '100.0%'], rows)
        self.assertIn(['Reconciliation', 'Sources less uses', '0.00', 'Balanced'], rows)
        self.assertIn(['Term', 'Instrument', 'Ordinary equity', ''], rows)
        self.assertEqual(set(cited), {item['id'] for item in transaction_cells()})
        terms = transaction_cells() + [cell(6, 'Draw conditions', '', unit='', basis='company_claim', statement='Draw conditions: Subject to supplied milestones')]
        exhibit, cited = pages.transaction_summary(groups(terms))
        self.assertIn(['Term', 'Draw conditions', 'Subject to supplied milestones', ''], exhibit['grid']['rows'])
        self.assertIn('S.c6', cited)
        source = transaction_cells()
        source[3]['value'] = '4'
        rows = pages.transaction_summary(groups(source))[0]['grid']['rows']
        self.assertIn(['Reconciliation', 'Sources less uses', '1.00', 'Unreconciled'], rows)

    def test_transaction_abstains_for_missing_sides_instrument_and_mixed_currencies(self):
        for source in (transaction_cells()[:2], transaction_cells()[2:], transaction_cells()[:4]):
            self.assertIsNone(pages.transaction_summary(groups(source)))
        source = transaction_cells()
        source[3]['unit'] = 'other units'
        self.assertIsNone(pages.transaction_summary(groups(source)))

    def test_reported_transaction_totals_are_reconciled_and_cited(self):
        source = transaction_cells() + [cell(6, 'Total sources', 55)]
        exhibit, cited = pages.transaction_summary(groups(source))
        self.assertIn(['Reported total', 'Total sources', '55.00', 'Computed less reported: (5.00)'], exhibit['grid']['rows'])
        self.assertIn('S.c6', cited)

    def test_sources_and_uses_can_be_separate_tables_on_the_same_source_page(self):
        source = transaction_cells()
        for index, item in enumerate(source):
            if index < 4:
                item['table'] = {'id': 'Sources' if index < 2 else 'Uses'}
        self.assertIsNotNone(pages.transaction_summary(groups(source)))
        for item in source[2:4]:
            item['source'] = 'Different source'
        self.assertIsNone(pages.transaction_summary(groups(source)))

    def test_dense_schedules_continue_without_losing_periods_or_rows(self):
        exhibit = {'grid': {'header': ['Metric', *[f'Period {index}' for index in range(14)]],
                            'rows': [[f'Measure {row}', *[f'{row}-{column}' for column in range(14)]] for row in range(23)]}}
        parts = pages._family_schedules(exhibit)
        self.assertEqual(len(parts), 9)
        rebuilt = {(row[0], heading, value) for part in parts for row in part['grid']['rows'] for heading, value in zip(part['grid']['header'][1:], row[1:])}
        expected = {(row[0], heading, value) for row in exhibit['grid']['rows'] for heading, value in zip(exhibit['grid']['header'][1:], row[1:])}
        self.assertEqual(rebuilt, expected)

    @patch.object(pages, 'REFERENCE_DIR', Path('reference/inventory'))
    def test_new_families_reach_build_baseline_and_decks(self):
        for family, factory, _ in FAMILIES:
            with self.subTest(family=family):
                source = factory()
                built = pages.build({'facts': source, 'workbook_cells': []})
                self.assertIn(family, pages.baseline(built)['families'])
                self.assertNotIn(family, pages.baseline(built)['missing'])
                relevant = [page for page in built if page.get('family') == ('transaction' if family == 'transaction_summary' else family)]
                self.assertTrue(relevant)
                self.assertTrue(all(set(page['cells']) <= {item['id'] for item in source} for page in relevant))
                if family != 'investor_returns':
                    keys = {page['key'] for page in pages.decks(built)['pitch_deck']}
                    self.assertTrue({page['key'] for page in relevant} <= keys)
        missing = pages.baseline(pages.build({'facts': [], 'workbook_cells': []}))['missing']
        self.assertTrue(all(name in missing and missing[name] for name, _, _ in FAMILIES))

    def test_workbook_only_cases_reach_the_page_builder(self):
        built = pages.build({'facts': [], 'workbook_cells': case_cells()})
        self.assertIn('operating_cases', [page['key'] for page in built])

    def test_full_financial_schedules_keep_all_periods_and_rows(self):
        table = {'columns': {index: f'Period {index}' for index in range(1, 15)}, 'rows': {
            row: {'label': 'A long explicitly defined measure ' + str(row), 'cells': {
                column: {'id': f'T.r{row}c{column}', 'value': str(row * column), 'unit': 'currency units'} for column in range(1, 15)}} for row in range(1, 14)}}
        full = pages.period_table(table, full=True)
        parts = pages._family_schedules({'grid': full}, max_columns=13)
        self.assertEqual(len(full['header']), 15)
        self.assertEqual(len(full['rows']), 13)
        self.assertEqual(len(parts), 4)
        self.assertEqual(sum((len(part['grid']['header']) - 1) * len(part['grid']['rows']) for part in parts), 14 * 13)
        self.assertEqual(full['rows'][0][0], table['rows'][1]['label'])

    def test_workbook_citations_compact_only_adjacent_cells(self):
        source = [cell(index, 'Value', index) for index in (1, 2, 3, 5)]
        text = pages.source_line({'cells': [item['id'] for item in source]}, {item['id']: item for item in source})
        self.assertEqual(text, 'Synthetic schedule, sheet Plan, cells C1:C3, C5')

    def test_all_family_calculations_leave_the_fact_base_unchanged(self):
        for _, factory, builder in FAMILIES:
            source = factory()
            before = deepcopy(source)
            builder(groups(source))
            self.assertEqual(source, before)


class FamilyRenderingTests(unittest.TestCase):
    def test_each_family_builds_editable_office_exhibits(self):
        from pptx import Presentation
        from delivery.deal_documents import deck_render
        for name, factory, builder in FAMILIES:
            with self.subTest(family=name):
                exhibits, _ = builder(groups(factory()))
                specs = [{'heading': 'Synthetic analytical schedule', 'source': 'Synthetic schedule, cells C1:C9', 'bullets': [], **part}
                         for part in pages._family_schedules(exhibits)]
                data = deck_render.build_pages({'company': 'Synthetic entity', 'heading': 'Review', 'bullets': [], 'when': 'Draft'}, [], specs, 'Synthetic review')
                deck = Presentation(BytesIO(data))
                self.assertEqual(len(deck.slides), len(specs) + 2)
                for slide, spec in zip(list(deck.slides)[2:], specs):
                    if spec.get('grid'):
                        shape = next(shape for shape in slide.shapes if shape.has_table)
                        table = shape.table
                        self.assertEqual([[cell.text for cell in row.cells] for row in table.rows], [spec['grid']['header'], *spec['grid']['rows']])
                        self.assertLessEqual(shape.top + shape.height, deck_render.Inches(deck_render.BODY_BOTTOM))
                        for column in spec['grid'].get('numeric', []):
                            self.assertEqual(table.cell(1, column).text_frame.paragraphs[0].alignment, deck_render.PP_ALIGN.RIGHT)
                    if spec.get('chart'):
                        native = next(shape.chart for shape in slide.shapes if shape.has_chart)
                        self.assertEqual(list(native.series[0].values), spec['chart']['series'][0]['values'])
                    self.assertTrue(all(shape.top + shape.height <= deck.slide_height for shape in slide.shapes))

    def test_chart_and_table_keep_the_takeaway_inside_the_body(self):
        from delivery.deal_documents import deck_render
        deck, blank = deck_render._new()
        slide = deck.slides.add_slide(blank)
        chart = pages.funding_plan(groups(cash_cells()))[0]['chart']
        deck_render.draw_page(slide, {'heading': 'Cash comparison', 'source': '', 'chart': chart,
                                      'table': {'header': ['Item', 'Value'], 'rows': [['Cash', '4.00']]},
                                      'bullets': [('analysis', 'Financing covers the stated shortfall.')]}, 1)
        self.assertTrue(any('Financing covers' in shape.text for shape in slide.shapes if shape.has_text_frame))
        table = next(shape for shape in slide.shapes if shape.has_table)
        self.assertLessEqual(table.top + table.height, deck_render.Inches(deck_render.BODY_BOTTOM - 1.1 - .16))

    def test_negative_cash_chart_keeps_zero_in_view(self):
        from delivery.deal_documents import deck_render
        deck, blank = deck_render._new()
        slide = deck.slides.add_slide(blank)
        chart = {'plot': 'line', 'categories': ['FY30', 'FY31'], 'decimals': 1, 'unit': 'currency units', 'caption': 'Cash', 'series': [{'name': 'Cash', 'values': [-8, -4]}]}
        deck_render.draw_page(slide, {'heading': 'Cash shortfall', 'source': '', 'chart': chart, 'bullets': []}, 1)
        shape = next(shape for shape in slide.shapes if shape.has_chart)
        self.assertGreaterEqual(shape.chart.value_axis.maximum_scale, 0)
        self.assertGreater(shape.width, deck_render.Inches(deck_render.CHART_WIDTH))

    def test_overfull_headers_kpis_and_grids_are_refused(self):
        from delivery.deal_documents import deck_render
        base = {'heading': 'Synthetic schedule', 'source': '', 'bullets': []}
        with self.assertRaises(ValueError):
            deck_render.trial_page({**base, 'table': {'header': ['Item', 'long heading ' * 40], 'rows': [['Cash', '1']]}})
        with self.assertRaises(ValueError):
            deck_render.trial_page({**base, 'kpis': [{'label': 'long label ' * 60, 'value': '1', 'sub': 'Scope'}]})
        with self.assertRaises(ValueError):
            deck_render.trial_page({**base, 'grid': {'header': ['Item', 'Value'], 'rows': [['too much text ' * 500, '1']]}})


if __name__ == '__main__':
    unittest.main()
