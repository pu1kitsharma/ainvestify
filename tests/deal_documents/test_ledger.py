"""Numerical review against synthetic evidence, including deliberately wrong figures."""
import copy
import json
import tempfile
import types
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from delivery.deal_documents import ledger


def fact(key='S.a', value='120', **extra):
    return {'id': key, 'metric': 'Output', 'value': value, 'unit': 'items', 'period': 'FY30',
            'basis': 'historical', 'segment': '', 'document': 'Synthetic accounts', 'location': 'page 4',
            'topic': 'historical_financials', 'statement': f'Output: {value} items in FY30', **extra}


def base(*facts):
    return {'facts': list(facts), 'workbook_cells': [], 'checks': []}


def page(value='120', metric='Output'):
    return {'key': 'financials', 'title': 'Reported results', 'brief': '', 'takeaways': [], 'topics': [],
            'cells': ['S.a'], 'exhibits': {'table': {'header': ['items', 'FY30'], 'rows': [[metric, value]]}}}


class LedgerTests(unittest.TestCase):
    def test_baseline_never_silently_selects_a_conflicting_source(self):
        facts = base(fact(), fact('S.b', '125'))
        row = ledger.baseline(facts)['rows'][0]
        self.assertTrue(row['conflict'])
        self.assertIsNone(row['value'])
        self.assertIsNone(row['source_id'])
        facts['ledger_review'] = {'selections': {row['id']: {'source_id': 'S.b', 'reason': 'Reviewed revised source accounts',
                                                           'observation_sha256': ledger.digest(facts['facts'][1])}}}
        resolved = ledger.baseline(facts)['rows'][0]
        self.assertEqual(resolved['value'], 125)
        self.assertTrue(resolved['conflict'])
        self.assertEqual(len(resolved['candidates']), 2)
        canonical = ledger.canonical(facts)
        self.assertTrue(all(f['value'] == '125' and f['baseline_source_id'] == 'S.b' for f in canonical['facts']))
        self.assertEqual(facts['facts'][0]['value'], '120')
        facts['facts'][1]['value'] = '126'
        self.assertIsNone(ledger.baseline(facts)['rows'][0]['source_id'])

    def test_period_basis_case_version_and_scale_are_not_combined(self):
        facts = base(fact(), fact('S.b', period='Q1-FY30'), fact('S.c', basis='projection'),
                     fact('S.d', case='downside'), fact('S.e', version='revised'), fact('S.f', unit='thousand items'))
        result = ledger.baseline(facts)
        self.assertEqual(len(result['rows']), 6)
        self.assertEqual([item['kind'] for item in result['exceptions']], ['version_selection'])

    def test_an_explicit_version_choice_excludes_the_other_version(self):
        facts = base(fact(version='original'), fact('S.b', '125', version='revised'))
        rows = ledger.baseline(facts)['rows']
        chosen = next(row for row in rows if row['meaning']['version'] == 'revised')
        facts['ledger_review'] = {'selections': {chosen['id']: {'source_id': 'S.b', 'reason': 'Reviewed revised forecast version',
                                                               'observation_sha256': ledger.digest(facts['facts'][1])}}}
        result = ledger.baseline(facts)
        self.assertFalse(result['exceptions'])
        self.assertEqual([fact['id'] for fact in ledger.canonical(facts)['facts']], ['S.b'])
        self.assertTrue(any(row['status'] == 'alternative_version' for row in result['rows']))

    def test_zero_is_an_observation_and_missing_is_not_zero(self):
        result = ledger.baseline(base(fact(value=0), fact('S.b', value='', metric='Missing measure', cell_error=True)))
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(sum(row['value'] == 0 for row in result['rows']), 1)
        self.assertTrue(result['exceptions'])

    def test_a_reviewed_mapping_can_supply_a_missing_unit_but_cannot_clear_ocr(self):
        facts = base(fact(unit=''))
        self.assertTrue(ledger.baseline(facts)['exceptions'])
        facts['ledger_review'] = {'mappings': {'S.a': {'unit': 'items'}}}
        self.assertFalse(ledger.baseline(facts)['exceptions'])
        facts['facts'][0]['ocr_only'] = True
        self.assertTrue(ledger.baseline(facts)['exceptions'])

    def test_repeated_figures_have_individual_locations_and_sources(self):
        facts = base(fact())
        pages = ledger.bind_pages([page(), page()], facts)
        report = ledger.tie_out({'memo': pages, 'pitch': [copy.deepcopy(pages[0])]}, facts)
        amounts = [row for row in report['occurrences'] if row['path'] == 'table.rows.0.1']
        self.assertEqual(len(amounts), 3)
        self.assertTrue(all(row['status'] == 'tied' and row['sources'][0]['id'] == 'S.a' for row in amounts))
        self.assertFalse(report['exceptions'])
        self.assertEqual(len(amounts[0]['sources'][0]['observation_sha256']), 64)

    def test_planted_wrong_figure_is_caught_even_when_that_digit_is_in_another_source(self):
        facts = base(fact(), fact('S.b', '999', metric='Unrelated measure'))
        built = ledger.bind_pages([page()], facts)
        built[0]['exhibits']['table']['rows'][0][1] = '999'
        report = ledger.tie_out({'memo': built}, facts)
        self.assertTrue(any('requires 120' in item['detail'] for item in report['exceptions']))
        self.assertTrue(ledger.gate_section(report)['problems'])

    def test_old_cached_pages_are_checked_without_rewriting_them(self):
        report = ledger.tie_out({'memo': [page('999')]}, base(fact()))
        self.assertTrue(any('requires 120' in item['detail'] for item in report['exceptions']))

    def test_planted_period_or_denominator_change_invalidates_binding(self):
        facts = base(fact())
        built = ledger.bind_pages([page()], facts)
        built[0]['exhibits']['table']['rows'][0][1] = '120 % of different base'
        report = ledger.tie_out({'memo': built}, facts)
        self.assertTrue(any('changed after binding' in item['detail'] for item in report['exceptions']))
        built = ledger.bind_pages([page()], facts)
        built[0]['exhibits']['table']['rows'][0][0] = 'Costs'
        self.assertTrue(ledger.tie_out({'memo': built}, facts)['exceptions'])

    def test_derived_values_are_recomputed_before_rounding(self):
        facts = base(fact(value='40'), fact('S.b', '120', metric='Base'))
        built = page('33.3%', 'Share')
        built['cells'].append('S.b')
        built['exhibits']['table']['figure_expressions'] = {'rows.0.1#0': ledger.calculation('ratio_percent', ledger.source(facts['facts'][0]), ledger.source(facts['facts'][1]))}
        ledger.bind_pages([built], facts)
        self.assertFalse(ledger.tie_out({'memo': [built]}, facts)['exceptions'])
        built['exhibits']['table']['rows'][0][1] = '33.8%'
        self.assertTrue(ledger.tie_out({'memo': [built]}, facts)['exceptions'])

    def test_same_metric_conflicts_across_documents_are_explicit(self):
        facts = base(fact(), fact('S.b', '125'))
        first, second = page(), page('125')
        for built, key in ((first, 'S.a'), (second, 'S.b')):
            occurrence = next(o for o in ledger.occurrences(built) if o['path'] == 'table.rows.0.1')
            built['figure_slots'] = {occurrence['slot']: {'expression': {'op': 'source', 'id': key}, 'context_sha256': occurrence['context_sha256']}}
        report = ledger.tie_out({'memo': [first], 'pitch': [second]}, facts)
        self.assertTrue(any(item['kind'] == 'cross_document' for item in report['exceptions']))

    def test_definitions_cannot_hide_different_values_behind_the_same_printed_label(self):
        facts = base(fact(definition='Before deductions'), fact('S.b', '100', definition='After deductions'))
        first, second = page(), page('100')
        second['cells'] = ['S.b']
        ledger.bind_pages([first, second], facts)
        report = ledger.tie_out({'memo': [first], 'pitch': [second]}, facts)
        self.assertTrue(any(item['kind'] == 'cross_document' for item in report['exceptions']))

    def test_unattributed_authored_numbers_and_missing_locators_block(self):
        built = page()
        built['takeaways'] = ['A total of 999 is expected']
        report = ledger.tie_out({'memo': [built]}, base(fact(location='')))
        self.assertTrue(report['exceptions'])
        self.assertTrue(any(item.get('slot', '').startswith('takeaways') for item in report['exceptions']))

    def test_failed_reconciliations_are_not_erased_by_source_choices(self):
        facts = base(fact())
        facts['checks'] = [{'status': 'inconsistent', 'question': 'Subtotal does not reconcile'}]
        self.assertTrue(any(item['kind'] == 'reconciliation' for item in ledger.baseline(facts)['exceptions']))

    def test_reviewed_accounting_roles_reconcile_and_missing_components_never_balance(self):
        for total, parts, amounts in (
            ('asset_total', ('liability_total', 'equity_total'), (100, 60, 40)),
            ('closing_cash', ('opening_cash', 'net_cash_change'), (25, 10, 15)),
            ('net_revenue', ('gross_revenue', 'revenue_deduction'), (80, 100, 20)),
            ('contribution', ('contribution_base', 'contribution_cost'), (30, 80, 50)),
        ):
            with self.subTest(role=total):
                facts = base(*(fact(f'S.{n}', str(amount), metric=f'Measure {n}', financial_role=role, cost_boundary=f'Boundary {n}')
                               for n, (role, amount) in enumerate(zip((total, *parts), amounts))))
                self.assertFalse(ledger.baseline(facts)['exceptions'])
                facts['facts'][0]['value'] = str(amounts[0] + 1)
                self.assertEqual(ledger.baseline(facts)['reconciliations'][0]['status'], 'fail')
                facts['facts'].pop()
                self.assertEqual(ledger.baseline(facts)['reconciliations'][0]['status'], 'unresolved')

    def test_overlapping_cost_boundaries_prevent_double_subtraction(self):
        facts = base(fact('S.a', '60', metric='Net', financial_role='net_revenue'),
                     fact('S.b', '100', metric='Gross', financial_role='gross_revenue'),
                     fact('S.c', '20', metric='Deduction A', financial_role='revenue_deduction', cost_boundary='same accounts'),
                     fact('S.d', '20', metric='Deduction B', financial_role='revenue_deduction', cost_boundary='same accounts'))
        self.assertTrue(ledger.baseline(facts)['exceptions'])

    def test_missing_or_unreadable_exports_fail_closed(self):
        facts = base(fact())
        built = ledger.bind_pages([page()], facts)
        report = ledger.tie_out({'memo': built}, facts)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            ledger.audit_exports(report, {'memo': built}, Path(folder), {})
        self.assertTrue(any(item['kind'] == 'export_review' for item in report['exceptions']))
        self.assertTrue(ledger.gate_section(report)['problems'])
        self.assertIn('memo', report['affected_approvals'])
        json.dumps(report)

    def test_saved_editable_bytes_are_checked_and_wrong_export_is_caught(self):
        # Exercise the real ZIP/XML reader; the PDF text extractor is a test double.
        facts = base(fact(source_sha256='a' * 64, source_hash_scope='extracted_source_unit'))
        built = ledger.bind_pages([page()], facts)
        for printed_value in ('120', '999'):
            with self.subTest(value=printed_value), tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
                output = BytesIO()
                texts = [['Cover'], ['Notice', '2'], ['Reported results', 'items', 'FY30', 'Output', printed_value, '3']]
                with ZipFile(output, 'w') as archive:
                    for n, paragraphs in enumerate(texts, 1):
                        xml = '<root xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' + ''.join(
                            f'<a:p><a:r><a:t>{text}</a:t></a:r></a:p>' for text in paragraphs) + '</root>'
                        archive.writestr(f'ppt/slides/slide{n}.xml', xml)
                path = Path(folder)
                (path / 'memo.pptx').write_bytes(output.getvalue())
                (path / 'memo.pdf').write_bytes(b'synthetic PDF parser fixture')
                pdf = types.ModuleType('pypdf')
                pdf.PdfReader = lambda stream: types.SimpleNamespace(pages=[types.SimpleNamespace(extract_text=lambda text=' '.join(p): text) for p in texts])
                report = ledger.tie_out({'memo': built}, facts)
                with patch.dict('sys.modules', {'pypdf': pdf}):
                    ledger.audit_exports(report, {'memo': built}, path, {})
                if printed_value == '120':
                    self.assertFalse(report['exceptions'])
                    self.assertEqual(len(report['exports'][0]['pptx_sha256']), 64)
                else:
                    self.assertTrue(any(item['kind'] == 'export_text' for item in report['exceptions']))


class LedgerFamilyTests(unittest.TestCase):
    def test_financial_tables_snapshot_growth_and_margin_share_the_baseline(self):
        from delivery.deal_documents import pages
        cells = []
        for r, (metric, values) in enumerate((('Output', (100, 120)), ('Inputs', (70, 80)), ('Surplus', (30, 40))), 1):
            for c, (period, value) in enumerate(zip(('FY29', 'FY30'), values), 1):
                cells.append(fact(f'S.t1.r{r}c{c}', str(value), metric=metric, period=period, segment='Total',
                                  table={'id': 'S.t1', 'title': 'Reported schedule'}))
        facts = base(*cells)
        built = pages.build(facts)
        report = ledger.tie_out({'memo': built}, facts)
        self.assertFalse(report['exceptions'])
        self.assertTrue({'snapshot', 'financials', 'margins', 'trend'} <= {page['key'] for page in built})
        financials = next(page for page in built if page['key'] == 'financials')
        financials['exhibits']['grid']['rows'][0][1] = '120'
        self.assertTrue(ledger.tie_out({'memo': built}, facts)['exceptions'])

    def test_analytical_families_trace_all_occurrences_and_catch_planted_errors(self):
        from delivery.deal_documents import pages
        from tests.deal_documents.test_page_families import FAMILIES, groups
        for name, factory, builder in FAMILIES:
            with self.subTest(family=name):
                facts = base(*factory())
                exhibits, cells = builder(groups(facts['facts']))
                built = [{'key': name, 'title': 'Synthetic schedule', 'brief': '', 'takeaways': [], 'cells': cells, 'exhibits': part}
                         for part in pages._family_schedules(exhibits)]
                ledger.bind_pages(built, facts)
                report = ledger.tie_out({'memo': built}, facts)
                self.assertFalse(report['exceptions'])
                row = next(row for row in report['occurrences'] if row.get('expression', {}).get('op') not in (None, 'field', 'navigation'))
                target = built[row['content_page'] - 1]['exhibits']
                parts = row['path'].split('.')
                for part in parts[:-1]:
                    target = target[int(part)] if isinstance(target, list) else target[part]
                field = int(parts[-1]) if isinstance(target, list) else parts[-1]
                target[field] = 999 if isinstance(target[field], (float, int)) else '999'
                self.assertTrue(ledger.tie_out({'memo': built}, facts)['exceptions'])


if __name__ == '__main__':
    unittest.main()
