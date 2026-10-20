"""Independent stdlib Decimal arithmetic for a fictional diagnostic, never inference.

Run this file directly to print the separate objective answer key. The model may
receive ONLY ../input.txt, never this script, generated answers or rubric findings.
"""
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path

getcontext().prec = 40
D = lambda value: Decimal(str(value))


def historical():
    result = {}
    for year, values in [(2024, (1200, 360, 500, 180, 100, 20, 10, '7.5')),
                         (2025, (1500, 450, 600, 240, 120, 30, 10, '12.5'))]:
        rev, cogs, payroll, sales, admin, dep, interest, tax = map(D, values)
        gp = rev - cogs
        ebitda = gp - payroll - sales - admin
        ebit = ebitda - dep
        pbt = ebit - interest
        result[str(year)] = dict(revenue=rev, gross_profit=gp, gross_margin=gp/rev,
            ebitda=ebitda, ebitda_margin=ebitda/rev, ebit=ebit,
            profit_before_tax=pbt, cash_tax=tax, net_income=pbt-tax)
    h25 = result['2025']
    h25.update(cfo=h25['net_income']+D(30)-D(25)+D(15), capex=D(50),
               receivables=D(125), payables=D(75), net_ppe=D(120), debt=D(100))
    h25['cash'] = D(200)+h25['cfo']-h25['capex']
    h25['equity'] = D(240)+h25['net_income']
    h25['assets'] = h25['cash']+h25['receivables']+h25['net_ppe']
    h25['liabilities_and_equity'] = h25['payables']+h25['debt']+h25['equity']
    assert h25['assets'] == h25['liabilities_and_equity']
    return result


def scenario(name, growth, payroll_growth, admin_growth, sales_rate):
    current = historical()['2025']
    opening_cash = current['cash']
    customers, payroll, admin = D(125), D(600), D(120)
    cash, debt, ppe, ar, ap, equity = [current[key] for key in
                                    ('cash', 'debt', 'net_ppe', 'receivables', 'payables', 'equity')]
    rows = []
    for year in (2026, 2027, 2028):
        customers *= 1+D(growth)
        payroll *= 1+D(payroll_growth)
        admin *= 1+D(admin_growth)
        revenue = customers*D(12)
        cogs, sales = revenue*D('.30'), revenue*D(sales_rate)
        ebitda = revenue-cogs-payroll-sales-admin
        dep, interest = ppe*D('.20'), debt*D('.10')
        pbt = ebitda-dep-interest
        tax = max(D(0),pbt)*D('.25')
        ni = pbt-tax
        next_ar, next_ap = revenue/D(12), cogs/D(6)
        cfo = ni+dep-(next_ar-ar)+(next_ap-ap)
        cash_change = cfo-D(150)-D(20)
        cash += cash_change
        ppe += D(150)-dep
        debt -= D(20)
        equity += ni
        ar, ap = next_ar, next_ap
        rows.append(dict(year=year, status='illustrative/company_projection', average_customers=customers,
            revenue=revenue, cogs=cogs, gross_profit=revenue-cogs, payroll=payroll,
            sales_marketing=sales, administration=admin, ebitda=ebitda, depreciation=dep,
            ebit=ebitda-dep, interest=interest, profit_before_tax=pbt, cash_tax=tax,
            net_income=ni, receivables=ar, payables=ap, cfo=cfo, capex=D(150),
            principal_repayment=D(20), net_cash_change=cash_change, unfunded_cash=cash,
            net_ppe=ppe, debt=debt, unfunded_equity=equity))
    trough = min([opening_cash]+[row['unfunded_cash'] for row in rows])
    zero_floor_need = max(D(0), -trough)
    equity_need = max(D(0), D(50)-trough)
    for row in rows:
        row['funded_cash'] = row['unfunded_cash']+equity_need
        row['funded_equity'] = row['unfunded_equity']+equity_need
        row['funded_assets'] = row['funded_cash']+row['receivables']+row['net_ppe']
        row['funded_liabilities_equity'] = row['payables']+row['debt']+row['funded_equity']
        row['balance_check'] = row['funded_assets']-row['funded_liabilities_equity']
        assert row['balance_check'] == 0
        assert row['funded_cash'] >= 50
    return dict(name=name, status='illustrative/company_projection', years=rows,
        opening_cash=opening_cash, minimum_unfunded_cash=trough,
        maximum_draw_from_opening_cash=max(D(0),opening_cash-trough),
        zero_cash_floor_shortfall=zero_floor_need, required_equity_for_50_cash_floor=equity_need,
        illustrative_ask=D(600), ask_less_required_equity=D(600)-equity_need,
        funding_adequate_at_year_ends=D(600)>=equity_need)


def build():
    return {'contract': 'north-quay-synthetic-objective-key-v1',
        'input_sha256': hashlib.sha256((Path(__file__).parents[1]/'input.txt').read_bytes()).hexdigest(),
        'case_status': 'synthetic_diagnostic_not_gold_acceptance',
        'units': 'USD thousands except customer counts and ratios',
        'numeric_absolute_tolerance_usd_thousands': '0.005',
        'historical': historical(), 'scenarios': [
            scenario('BASE', '.20', '.20', '.10', '.20'),
            scenario('UPSIDE', '.30', '.15', '.05', '.18'),
            scenario('DOWNSIDE', '.05', '.20', '.10', '.22')],
        'historical_revenue_growth_2025': D('.25'),
        'expected_missing': ['FY2024 cash flow and opening balance sheet', 'Actual ARR',
            'Churn and retention', 'Customer concentration', 'Backlog and pipeline',
            'TAM and peers', 'Quarterly liquidity', 'Valuation and investor returns',
            'Detailed uses of proceeds', 'Audit and regulatory evidence'],
        'required_findings': ['No actual overdraft exists: negative unfunded cash is a funding shortfall',
            'No tax assets or benefits from forecast losses under the disclosed convention',
            'Funded balance sheets tie through explicit upfront equity, not a balancing plug',
            'Ask versus need is scenario-specific and annual liquidity alone is insufficient',
            'Customer equivalents are annual averages, with no second half-year convention',
            'All forward-looking figures are illustrative/company_projection, not validated'],
        'investor_acceptance': False, 'training_approved': False, 'independent_human_review': 'unrun'}


if __name__ == '__main__':
    print(json.dumps(build(), default=lambda value: str(value) if isinstance(value, Decimal) else value,
                     indent=2, allow_nan=False))
