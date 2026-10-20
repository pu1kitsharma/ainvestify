"""Writes three SYNTHETIC XBRL-companyfacts-shaped fixtures. Not real companies or figures."""
import json
import sys
from pathlib import Path

COMPANIES = [
    # key, name, cik, sector, fye (month, day), start revenue, growth, gross margin, opex ratio, cash0, goods share
    ('synthetic-saas', 'SYNTHETIC SAAS CO (FIXTURE)', 9000001, 'software', (12, 31), 40_000_000, [0.60, 0.45, 0.38, 0.30], 0.72, 0.95, 30_000_000, 0.05),
    ('synthetic-hardware', 'SYNTHETIC HARDWARE CO (FIXTURE)', 9000002, 'hardware', (9, 30), 120_000_000, [0.12, 0.08, -0.03, 0.10], 0.34, 0.27, 20_000_000, 0.85),
    ('synthetic-retail', 'SYNTHETIC RETAIL CO (FIXTURE)', 9000003, 'consumer', (1, 31), 300_000_000, [0.06, 0.04, 0.09, 0.05], 0.30, 0.24, 25_000_000, 0.97),
]
YEARS = [2019, 2020, 2021, 2022, 2023]


def r(x):
    return int(round(x / 1000.0)) * 1000


def build(company):
    key, name, cik, sector, (fm, fd), rev0, growth, gm, opex_ratio, cash0, goods = company
    facts, rev, cash = {}, rev0, cash0
    rows = []
    for i, year in enumerate(YEARS):
        if i:
            rev = rev * (1 + growth[i - 1])
        revenue = r(rev)
        goods_rev = r(revenue * goods)
        revenue = goods_rev + r(revenue - goods_rev)
        cogs = r(revenue * (1 - gm))
        gp = revenue - cogs
        opex = r(revenue * opex_ratio)
        op = gp - opex
        interest = r(abs(op) * 0.02 + 500_000)
        tax = r(max(op - interest, 0) * 0.21)
        ni = op - interest - tax
        da = r(revenue * 0.03)
        ocf = r(ni + da - revenue * 0.01)
        capex = r(revenue * 0.04)
        icf = -capex
        ffin = r(5_000_000 if key == 'synthetic-saas' and i in (0, 2) else -2_000_000)
        cash = cash + ocf + icf + ffin
        rows.append(dict(year=year, revenue=revenue, goods=goods_rev, services=revenue - goods_rev, cogs=cogs, gp=gp, opex=opex, op=op,
                         interest=interest, tax=tax, ni=ni, da=da, ocf=ocf, capex=capex, icf=icf, ffin=ffin, cash=cash,
                         debt=r(revenue * 0.1), equity=r(revenue * 0.5 + cash), assets=r(revenue * 0.9 + cash), liabilities=0))
    for x in rows:
        x['liabilities'] = x['assets'] - x['equity']

    def end(year):
        # Fiscal year ends in month fm of calendar year `year`.
        return '%d-%02d-%02d' % (year, fm, fd)

    from datetime import date, timedelta
    def duration_start(year):
        return (date.fromisoformat(end(year)) - timedelta(days=364)).isoformat()

    spec = [('Revenues', 'revenue', 'flow'), ('SalesRevenueGoodsNet', 'goods', 'flow'), ('SalesRevenueServicesNet', 'services', 'flow'),
            ('CostOfRevenue', 'cogs', 'flow'), ('GrossProfit', 'gp', 'flow'), ('OperatingExpenses', 'opex', 'flow'),
            ('OperatingIncomeLoss', 'op', 'flow'), ('InterestExpense', 'interest', 'flow'), ('IncomeTaxExpenseBenefit', 'tax', 'flow'),
            ('NetIncomeLoss', 'ni', 'flow'), ('DepreciationDepletionAndAmortization', 'da', 'flow'),
            ('NetCashProvidedByUsedInOperatingActivities', 'ocf', 'flow'), ('PaymentsToAcquirePropertyPlantAndEquipment', 'capex', 'flow'),
            ('NetCashProvidedByUsedInInvestingActivities', 'icf', 'flow'), ('NetCashProvidedByUsedInFinancingActivities', 'ffin', 'flow'),
            ('CashAndCashEquivalentsAtCarryingValue', 'cash', 'instant'), ('LongTermDebt', 'debt', 'instant'),
            ('StockholdersEquity', 'equity', 'instant'), ('Assets', 'assets', 'instant'), ('Liabilities', 'liabilities', 'instant')]
    us = {}
    for tag, field, kind in spec:
        entries = []
        for idx, x in enumerate(rows):
            # Each value appears in its own 10-K and again as a comparative in the next year's 10-K.
            for filing_idx in (idx, idx + 1):
                if filing_idx >= len(rows):
                    continue
                fy = rows[filing_idx]['year']
                e = {'end': end(x['year']), 'val': x[field], 'accn': '%010d-%02d-%06d' % (cik, fy % 100, 1), 'fy': fy, 'fp': 'FY',
                     'form': '10-K', 'filed': '%d-%02d-%02d' % (fy + (0 if fm < 12 else 1), (fm % 12) + 2 if fm < 11 else 2, 15)}
                if kind == 'flow':
                    e['start'] = duration_start(x['year'])
                entries.append(e)
        if kind == 'flow':  # quarterly noise that annual selection must ignore
            x = rows[-1]
            entries.append({'start': duration_start(x['year']), 'end': '%d-%02d-%02d' % (x['year'] - 1, (fm % 12) + 3 if fm < 10 else 3, 28),
                            'val': x[field] // 4, 'accn': '%010d-%02d-%06d' % (cik, x['year'] % 100, 2), 'fy': x['year'], 'fp': 'Q1',
                            'form': '10-Q', 'filed': '%d-06-01' % x['year']})
        us[tag] = {'label': tag, 'description': 'synthetic fixture', 'units': {'USD': entries}}
    return {'cik': cik, 'entityName': name, 'facts': {'us-gaap': us}}, {'company_key': key, 'sector': sector, 'cik': cik, 'origin': 'synthetic_fixture'}


if __name__ == '__main__':
    out = Path(__file__).parent
    index = []
    for company in COMPANIES:
        data, meta = build(company)
        (out / (meta['company_key'] + '.companyfacts.json')).write_text(json.dumps(data, indent=1, sort_keys=True) + '\n')
        index.append(meta)
    (out / 'index.json').write_text(json.dumps(index, indent=1) + '\n')
