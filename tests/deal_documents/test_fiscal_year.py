import datetime
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch

try:
    from delivery.deal_documents import compliance, semantics
except ModuleNotFoundError as error:
    if error.name != 'delivery.deal_documents.facts':
        raise
    # This focused checkout omits facts.py; numeric helpers are mocked below.
    facts = types.ModuleType('delivery.deal_documents.facts')
    facts.number_present = Mock()
    facts.numbers_in = Mock()
    facts.parse_value = Mock()
    with patch.dict(sys.modules, {'delivery.deal_documents.facts': facts}):
        from delivery.deal_documents import compliance, semantics


def fact(fact_id, period, value='100', metric='Revenue', **extra):
    return {'id': fact_id, 'period': period, 'value': value, 'metric': metric,
            'unit': 'USD Mn', 'basis': 'historical', 'statement': 'Reported figure', **extra}


class FiscalYearTests(unittest.TestCase):
    def setUp(self):
        for name, helper in (
                ('parse_value', float),
                ('numbers_in', lambda text: [float(value) for value in re.findall(r'(?<![\w-])\d+(?:\.\d+)?', text)]),
                ('number_present', lambda value, allowed: value in allowed)):
            self.enterContext(patch.object(semantics, name, side_effect=helper))

    def test_fiscal_year_labels(self):
        for month in (3, 6, 12):
            for label in ('FY22', 'F22', 'FY2022', 'FY-22', "FY'22", 'FY2021-22', 'FY2021/2022', 'FY2021–22'):
                with self.subTest(month=month, label=label):
                    self.assertEqual(semantics.period_of(label, fiscal_year_end_month=month),
                                     ('year', 2022 * 12 + month, 12))

    def test_all_fiscal_quarters_in_both_label_orders(self):
        for month in (3, 6, 12):
            for quarter in range(1, 5):
                for label in (f'Q{quarter}-FY22', f'FY2022 Q{quarter}'):
                    with self.subTest(month=month, label=label):
                        self.assertEqual(semantics.period_of(label, fiscal_year_end_month=month),
                                         ('quarter', 2021 * 12 + month + 3 * quarter, 3))

    def test_run_rates(self):
        for month in (3, 6, 12):
            for label in ('FY22 run rate', 'FY22 run-rate', 'FY22 exit rate'):
                with self.subTest(month=month, label=label):
                    self.assertEqual(semantics.period_of(label, fiscal_year_end_month=month),
                                     ('run_rate', 2022 * 12 + month, 12))
            self.assertEqual(semantics.period_of('run rate', fiscal_year_end_month=month), ('run_rate', 0, 12))

    def test_calendar_labels_and_unknown_periods_are_unchanged(self):
        expected = {'2022': ('year', 2022 * 12 + 12, 12), 'CY2022': ('year', 2022 * 12 + 12, 12),
                    'JFM22': ('quarter', 2022 * 12 + 3, 3), 'AMJ22': ('quarter', 2022 * 12 + 6, 3),
                    'JAS22': ('quarter', 2022 * 12 + 9, 3), 'OND22': ('quarter', 2022 * 12 + 12, 3),
                    'June 2022': ('month', 2022 * 12 + 6, 1), '': None, 'Total': None, None: None}
        for month in (3, 6, 12):
            for label, parsed in expected.items():
                with self.subTest(month=month, label=label):
                    self.assertEqual(semantics.period_of(label, fiscal_year_end_month=month), parsed)

    def test_default_is_march_and_calls_are_independent(self):
        self.assertEqual(semantics.period_of('FY22'), ('year', 2022 * 12 + 3, 12))
        self.assertEqual(semantics.period_of('Q1-FY22'), ('quarter', 2021 * 12 + 6, 3))
        semantics.period_of('FY22', fiscal_year_end_month=12)
        self.assertEqual(semantics.period_of('FY22'), ('year', 2022 * 12 + 3, 12))

    def test_total_span_and_description(self):
        for month, end_label in ((3, 'Mar-22'), (6, 'Jun-22'), (12, 'Dec-22')):
            with self.subTest(month=month):
                index = {f'r1c{q}': fact(f'r1c{q}', f'Q{q}-FY22') for q in range(1, 5)}
                total = fact('r1c5', 'Total', table='t1')
                index[total['id']] = total
                parsed = semantics.fact_period(total, index, fiscal_year_end_month=month)
                self.assertEqual(parsed, ('span', 2022 * 12 + month, 12))
                self.assertEqual(semantics.describe_period(parsed), f'the 12 months to {end_label}')
                calc = {'id': 'c1', 'kind': 'figure', 'decimals': 0, 'parts': [total['id']]}
                self.assertEqual(semantics.compute(calc, index, fiscal_year_end_month=month)['sentence'],
                                 f'Revenue was USD 100 Mn in the 12 months to {end_label}.')
                problems = semantics._fiscal_label_problems('FY22 revenue was 100.', [total], index,
                                                           's', 'quote', fiscal_year_end_month=month)
                self.assertEqual(len(problems), 1)
                self.assertIn(f'the 12 months to {end_label}', problems[0])

    def test_comparable_excludes_equivalent_calendar_quarter(self):
        for month, calendar_quarter in ((3, 'AMJ21'), (6, 'JAS21'), (12, 'JFM22')):
            with self.subTest(month=month):
                current = fact('a', 'Q1-FY22')
                same = fact('b', calendar_quarter)
                index = {'a': current, 'b': same}
                self.assertEqual(semantics.comparable(current, index, fiscal_year_end_month=month), '')

    def test_growth_and_cagr_use_mixed_fiscal_and_calendar_periods(self):
        for month, prior in ((3, 'AMJ20'), (6, 'JAS20'), (12, 'JFM21')):
            for kind in ('growth', 'multiple', 'cagr'):
                with self.subTest(month=month, kind=kind):
                    index = {'a': fact('a', prior), 'b': fact('b', 'Q1-FY22', '200')}
                    calc = {'id': 'c1', 'kind': kind, 'decimals': 1, 'a': 'a', 'b': 'b'}
                    result = semantics.compute(calc, index, fiscal_year_end_month=month)
                    self.assertEqual(result['over_time'], {'length': 3, 'gap': 12})
                    self.assertEqual(result['value'], 2.0 if kind == 'multiple' else 100.0)

    def test_same_period_calculations(self):
        for month, calendar_quarter in ((3, 'AMJ21'), (6, 'JAS21'), (12, 'JFM22')):
            for kind in ('ratio', 'share', 'difference'):
                with self.subTest(month=month, kind=kind):
                    index = {'a': fact('a', 'Q1-FY22'), 'b': fact('b', calendar_quarter, '200')}
                    calc = {'id': 'c1', 'kind': kind, 'decimals': 1, 'a': 'a', 'b': 'b'}
                    result = semantics.compute(calc, index, fiscal_year_end_month=month)
                    self.assertIsNone(result['over_time'])
                    self.assertEqual(result['value'], {'ratio': 0.5, 'share': 50.0, 'difference': -100.0}[kind])

    def test_mixed_quarter_sum(self):
        for month, prior in ((3, 'JFM21'), (6, 'AMJ21'), (12, 'OND21')):
            with self.subTest(month=month):
                index = {'a': fact('a', prior), 'b': fact('b', 'Q1-FY22', '200')}
                calc = {'id': 'c1', 'kind': 'sum', 'decimals': 0, 'parts': ['b', 'a']}
                result = semantics.compute(calc, index, fiscal_year_end_month=month)
                self.assertEqual(result['over_time'], {'length': 6, 'gap': 0})
                self.assertEqual(result['sentence'], f'Revenue totalled USD 300 Mn across {prior} to Q1-FY22.')

    def test_figure_order_and_reverse_quarter_label(self):
        for month, prior, end_label in ((3, 'JFM21', 'Jun-21'), (6, 'AMJ21', 'Sep-21'), (12, 'OND21', 'Mar-22')):
            with self.subTest(month=month):
                index = {'a': fact('a', prior), 'b': fact('b', 'FY22 Q1', '200')}
                calc = {'id': 'c1', 'kind': 'figure', 'decimals': 0, 'parts': ['b', 'a']}
                sentence = semantics.compute(calc, index, fiscal_year_end_month=month)['sentence']
                self.assertLess(sentence.index('100'), sentence.index('200'))
                self.assertIn(f'USD 200 Mn in the quarter to {end_label}', sentence)
                calc['kind'] = 'rank'
                self.assertIn(f'in the quarter to {end_label}',
                              semantics.compute(calc, index, fiscal_year_end_month=month)['sentence'])

    def test_sentence_checks_match_fiscal_year_end(self):
        for month, label in ((3, 'Mar22'), (6, 'Jun22'), (12, 'Dec22')):
            with self.subTest(month=month):
                current = fact('a', label)
                text = 'FY22 revenue was 100.'
                self.assertEqual(semantics.sentence_problems(text, [current], {}, label='s',
                                                           fiscal_year_end_month=month), [])
                self.assertEqual(semantics.sentence_failures(text, [current], {}, [100],
                                                           fiscal_year_end_month=month), [])
                wrong = fact('b', label.replace('22', '21'))
                self.assertTrue(semantics.sentence_problems(text, [wrong], {}, label='s',
                                                          fiscal_year_end_month=month))

    def test_latest_period_uses_setting_and_ignores_projections(self):
        base = {'facts': [fact('a', 'FY22'), fact('b', 'Sep22'),
                          fact('c', 'FY25', basis='projection'), fact('d', 'FY24 run rate')]}
        for month, expected in ((3, ('Sep22', 2022 * 12 + 9)), (6, ('Sep22', 2022 * 12 + 9)),
                                (12, ('FY22', 2022 * 12 + 12))):
            with self.subTest(month=month):
                self.assertEqual(compliance.latest_reported_period(base, fiscal_year_end_month=month), expected)
        self.assertEqual(compliance.latest_reported_period(base), ('Sep22', 2022 * 12 + 9))
        for month in (3, 6, 12):
            self.assertEqual(compliance.latest_reported_period({'facts': []}, fiscal_year_end_month=month), (None, None))
            quarters = {'facts': [fact('a', 'Q1-FY22'), fact('b', 'Q2-FY22')]}
            self.assertEqual(compliance.latest_reported_period(quarters, fiscal_year_end_month=month),
                             ('Q2-FY22', 2021 * 12 + month + 6))

    def test_compliance_dates_and_information_age(self):
        base = {'facts': [fact('a', 'FY22')]}
        today = datetime.date(2023, 7, 1)
        for month, month_name, age, status in ((3, 'March', 16, 'counsel'), (6, 'June', 13, 'counsel'),
                                             (12, 'December', 7, 'pass')):
            with self.subTest(month=month):
                self.assertEqual(compliance.information_age(base, today, fiscal_year_end_month=month), ('FY22', age))
                notice = compliance.notices('Company', base, today, fiscal_year_end_month=month)[1][1]
                self.assertIn(f'ending {month_name} 2022', notice)
                self.assertIn(f'{age} months before this draft', notice)
                assessment = compliance.assess([], base, today=today, fiscal_year_end_month=month)
                check = next(check for check in assessment['checks'] if check['key'] == 'information_date')
                self.assertEqual(check['status'], status)
        self.assertEqual(compliance.information_age(base, today), ('FY22', 16))


if __name__ == '__main__':
    unittest.main()
