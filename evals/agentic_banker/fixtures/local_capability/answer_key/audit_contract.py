"""Evaluation-only adapter: independent synthetic Decimal key -> objective audit.

Never supply expectations or this module to inference. A separate names-only
list may be supplied in a future explicitly versioned experiment, not retrofitted
onto earlier recorded requests. No aliases or workbook/prose repairs are inferred.
Uses stdlib only and never launches a model, training job or artifact renderer.
"""
from decimal import Decimal
import json
from pathlib import Path

YEAR_METRICS = (
    'revenue', 'gross_profit', 'ebitda', 'ebit', 'profit_before_tax',
    'cash_tax', 'net_income', 'cfo', 'receivables', 'payables',
    'net_ppe', 'debt', 'funded_cash', 'funded_equity',
)
FUNDING_METRICS = (
    'minimum_unfunded_cash', 'zero_cash_floor_shortfall',
    'required_equity_for_50_cash_floor', 'ask_less_required_equity',
)
REPORTED_HISTORY = {
    '2024': {'revenue', 'cash_tax'},
    '2025': {'revenue', 'cash_tax', 'capex', 'receivables', 'payables', 'debt'},
}


def build_contract(key):
    if key.get('contract') != 'north-quay-synthetic-objective-key-v1':
        raise ValueError('Unrecognized independent answer-key contract')
    expected = []
    checks = []
    def add(identifier, value, *, status, formula, ratio=False):
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError('Nonfinite independent expectation')
        expected.append({'id': identifier, 'value': float(number),
            'unit': 'ratio' if ratio else 'USD_thousands',
            'tolerance': 0.000005 if ratio else 0.005,
            'require_formula': formula, 'status': status})
    def check(identifier, kind, inputs, output):
        checks.append({'id': identifier, 'kind': kind, 'inputs': inputs,
                       'output': output, 'tolerance': 0.005})
    for year, values in key['historical'].items():
        prefix = f'historical.{year}.'
        for name, value in values.items():
            add(prefix+name, value, status='historical',
                formula=name not in REPORTED_HISTORY[year], ratio=name.endswith('margin'))
        check(prefix+'profit_after_tax', 'difference',
              [prefix+'profit_before_tax', prefix+'cash_tax'], prefix+'net_income')
    prefix = 'historical.2025.'
    check(prefix+'asset_sum', 'sum',
          [prefix+'cash', prefix+'receivables', prefix+'net_ppe'], prefix+'assets')
    check(prefix+'liabilities_equity_sum', 'sum',
          [prefix+'payables', prefix+'debt', prefix+'equity'], prefix+'liabilities_and_equity')
    for scenario in key['scenarios']:
        scenario_prefix = f"scenarios.{scenario['name']}."
        for row in scenario['years']:
            prefix = scenario_prefix+str(row['year'])+'.'
            for name in YEAR_METRICS:
                add(prefix+name, row[name], status='company_projection', formula=True)
            check(prefix+'profit_after_tax', 'difference',
                  [prefix+'profit_before_tax', prefix+'cash_tax'], prefix+'net_income')
        for name in FUNDING_METRICS:
            add(scenario_prefix+name, scenario[name], status='company_projection', formula=True)
    if len(expected) != 166 or len({item['id'] for item in expected}) != len(expected):
        raise ValueError('Independent 166-metric contract coverage changed')
    required_memo = ['historical.2025.revenue', 'historical.2025.ebitda',
        'historical.2025.cfo', 'historical.2025.cash']
    for scenario in key['scenarios']:
        prefix = f"scenarios.{scenario['name']}."
        required_memo += [prefix+'2028.revenue', prefix+'2028.ebitda',
                         prefix+'required_equity_for_50_cash_floor',
                         prefix+'ask_less_required_equity']
    return {'expected_outputs': expected, 'required_memo_metrics': required_memo, 'checks': checks}


def requested_metric_ids(contract):
    """Pure machine names, with no expected figures, formulas or cell addresses."""
    return [row['id'] for row in contract['expected_outputs']]


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--names-only', action='store_true',
                        help='Emit only requested metric IDs for a future staged experiment')
    args = parser.parse_args()
    independent_key = json.loads((Path(__file__).with_name('expected.json')).read_text())
    contract = build_contract(independent_key)
    print(json.dumps(requested_metric_ids(contract) if args.names_only else contract,
                     indent=2, allow_nan=False))
