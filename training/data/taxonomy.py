"""Canonical line-item taxonomy: us-gaap tags and common Indian GAAP / Ind AS labels.

Mappings are a starting convention, not an accounting opinion. Unmapped items
resolve to None and must be reported, never guessed.
"""
import re
from datetime import date

# name -> statement, kind (flow = duration, instant = point in time), tags (priority order), labels
CANONICAL = {
    'revenue': dict(statement='income', kind='flow', us_gaap=['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet'],
                    labels=['revenue from operations', 'total revenue', 'net sales', 'total income from operations', 'sales']),
    'revenue_goods': dict(statement='income', kind='flow', us_gaap=['SalesRevenueGoodsNet'], labels=['sale of products', 'sale of goods']),
    'revenue_services': dict(statement='income', kind='flow', us_gaap=['SalesRevenueServicesNet'], labels=['sale of services', 'service revenue']),
    'gmv': dict(statement='kpi', kind='flow', us_gaap=[], labels=['gmv', 'gross merchandise value', 'gross merchandise volume']),
    'net_revenue': dict(statement='income', kind='flow', us_gaap=[], labels=['net revenue', 'revenue net of discounts', 'take rate revenue']),
    'cogs': dict(statement='income', kind='flow', us_gaap=['CostOfRevenue', 'CostOfGoodsAndServicesSold'],
                 labels=['cost of materials consumed', 'cost of goods sold', 'cost of revenue', 'purchases of stock-in-trade']),
    'gross_profit': dict(statement='income', kind='flow', us_gaap=['GrossProfit'], labels=['gross profit', 'gross margin']),
    'contribution_margin': dict(statement='kpi', kind='flow', us_gaap=[], labels=['contribution margin']),
    'opex': dict(statement='income', kind='flow', us_gaap=['OperatingExpenses', 'CostsAndExpenses'], labels=['total expenses', 'total operating expenses']),
    'opex_sga': dict(statement='income', kind='flow', us_gaap=['SellingGeneralAndAdministrativeExpense'], labels=['other expenses', 'selling and administrative expenses']),
    'opex_rnd': dict(statement='income', kind='flow', us_gaap=['ResearchAndDevelopmentExpense'], labels=['research and development expenses']),
    'opex_marketing': dict(statement='income', kind='flow', us_gaap=['SellingAndMarketingExpense', 'MarketingAndAdvertisingExpense'], labels=['advertisement and sales promotion', 'marketing expenses']),
    'opex_employee': dict(statement='income', kind='flow', us_gaap=['LaborAndRelatedExpense'], labels=['employee benefits expense']),
    'operating_income': dict(statement='income', kind='flow', us_gaap=['OperatingIncomeLoss'], labels=['operating profit', 'profit from operations', 'ebit']),
    'ebitda': dict(statement='derived', kind='flow', us_gaap=[], labels=['ebitda', 'operating profit before depreciation']),
    'da': dict(statement='income', kind='flow', us_gaap=['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization'], labels=['depreciation and amortisation expense', 'depreciation and amortization']),
    'interest_expense': dict(statement='income', kind='flow', us_gaap=['InterestExpense'], labels=['finance costs', 'interest expense']),
    'tax': dict(statement='income', kind='flow', us_gaap=['IncomeTaxExpenseBenefit'], labels=['total tax expense', 'tax expense', 'provision for tax']),
    'net_income': dict(statement='income', kind='flow', us_gaap=['NetIncomeLoss', 'ProfitLoss'], labels=['profit for the year', 'profit after tax', 'pat', 'net profit']),
    'receivables': dict(statement='balance', kind='instant', us_gaap=['AccountsReceivableNetCurrent'], labels=['trade receivables']),
    'inventory': dict(statement='balance', kind='instant', us_gaap=['InventoryNet'], labels=['inventories']),
    'payables': dict(statement='balance', kind='instant', us_gaap=['AccountsPayableCurrent'], labels=['trade payables']),
    'cash': dict(statement='balance', kind='instant', us_gaap=['CashAndCashEquivalentsAtCarryingValue', 'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'], labels=['cash and cash equivalents']),
    'debt': dict(statement='balance', kind='instant', us_gaap=['LongTermDebt', 'DebtInstrumentCarryingAmount'], labels=['borrowings', 'long-term borrowings']),
    'equity': dict(statement='balance', kind='instant', us_gaap=['StockholdersEquity'], labels=['total equity', "shareholders' funds"]),
    'assets': dict(statement='balance', kind='instant', us_gaap=['Assets'], labels=['total assets']),
    'liabilities': dict(statement='balance', kind='instant', us_gaap=['Liabilities'], labels=['total liabilities']),
    'ocf': dict(statement='cashflow', kind='flow', us_gaap=['NetCashProvidedByUsedInOperatingActivities'], labels=['net cash from operating activities']),
    'capex': dict(statement='cashflow', kind='flow', us_gaap=['PaymentsToAcquirePropertyPlantAndEquipment'], labels=['purchase of property, plant and equipment']),
    'icf': dict(statement='cashflow', kind='flow', us_gaap=['NetCashProvidedByUsedInInvestingActivities'], labels=['net cash used in investing activities']),
    'fcf_financing': dict(statement='cashflow', kind='flow', us_gaap=['NetCashProvidedByUsedInFinancingActivities'], labels=['net cash from financing activities']),
}

UNIT_SCALES = {'lakh': 1e5, 'lakhs': 1e5, 'lac': 1e5, 'lacs': 1e5, 'crore': 1e7, 'crores': 1e7, 'cr': 1e7,
               'k': 1e3, 'thousand': 1e3, 'thousands': 1e3, 'mn': 1e6, 'million': 1e6, 'millions': 1e6,
               'bn': 1e9, 'billion': 1e9, 'billions': 1e9}

_TAG = {t: n for n, d in CANONICAL.items() for t in d['us_gaap']}
_LABEL = {l: n for n, d in CANONICAL.items() for l in d['labels']}


def resolve_tag(tag):
    return _TAG.get(tag)


def tag_priority(name):
    return list(CANONICAL[name]['us_gaap'])


def _norm(label):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\' ,]+', ' ', label.casefold())).strip()


def resolve_label(label):
    return _LABEL.get(_norm(label))


def parse_amount(text):
    """'Rs. 1,234.5 crore' -> (12345000000.0 .. , scale). Raises ValueError on ambiguity."""
    m = re.fullmatch(r'\s*(?:rs\.?|inr|usd|us\$|₹|\$)?\s*\(?(-?[\d,]+(?:\.\d+)?)\)?\s*([a-z]*)\s*', text.casefold())
    if not m:
        raise ValueError('Unparseable amount')
    number = float(m.group(1).replace(',', ''))
    if text.strip().startswith('(') and number > 0:
        number = -number
    unit = m.group(2)
    if unit and unit not in UNIT_SCALES:
        raise ValueError('Unknown unit word: ' + unit)
    scale = UNIT_SCALES.get(unit, 1.0)
    return number * scale, scale


def fiscal_year_label(end, fye_month=None):
    """FY labelled by the calendar year in which the fiscal year ends (Indian FY24 = Apr 2023-Mar 2024)."""
    if isinstance(end, str):
        end = date.fromisoformat(end)
    return 'FY%d' % end.year


def is_calendar_aligned(fye_month):
    return fye_month == 12
