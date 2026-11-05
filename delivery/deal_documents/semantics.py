"""Meaning checks that code, not the model, owns: periods, comparisons and the basis of each figure.

The model chooses which comparison to make; code decides whether that comparison
is meaningful (same metric, unit and period length), computes it, writes its
label and then checks that the sentence using it describes it correctly. A
quarter-to-quarter multiple cannot be called annual growth, a single-period
ratio cannot be called growth, and a projection cannot be written as a fact.
"""
from __future__ import annotations

import re

from delivery.deal_documents.facts import number_present, numbers_in, parse_value

MONTHS = {name: number for number, name in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
NAMED_QUARTERS = {'jfm': 3, 'amj': 6, 'jas': 9, 'ond': 12}


def _year(text):
    year = int(text)
    return year + 2000 if year < 100 else year


def period_of(period: str, fiscal_year_end_month=3):
    """(kind, end_month, length_months) for a printed period label, or None when it is not a period.

    Fiscal years are named for their ending year; fiscal_year_end_month defaults to 3 (March).
    With that default, FY22 runs April 2021 to March 2022 and Q1-FY22 is April to June 2021.
    """
    text = ' '.join(str(period or '').lower().replace("'", ' ').split())
    if not text:
        return None
    if 'run rate' in text or 'run-rate' in text or 'exit' in text:
        match = re.search(r'fy\s*-?\s*(\d{2,4})', text)
        return ('run_rate', _year(match.group(1)) * 12 + fiscal_year_end_month if match else 0, 12)
    match = re.fullmatch(r'q([1-4])\s*[- ]?\s*fy\s*-?\s*(\d{2,4})', text) or re.fullmatch(r'fy\s*-?\s*(\d{2,4})\s*[- ]?\s*q([1-4])', text)
    if match:
        quarter, year = (match.group(1), match.group(2)) if text.startswith('q') else (match.group(2), match.group(1))
        return ('quarter', (_year(year) - 1) * 12 + fiscal_year_end_month + 3 * int(quarter), 3)
    match = re.fullmatch(r'(jfm|amj|jas|ond)\s*-?\s*(\d{2,4})', text)
    if match:
        return ('quarter', _year(match.group(2)) * 12 + NAMED_QUARTERS[match.group(1)], 3)
    match = re.fullmatch(r'(?:fy|f)\s*-?\s*(\d{2,4})', text)
    if match:
        return ('year', _year(match.group(1)) * 12 + fiscal_year_end_month, 12)
    match = re.fullmatch(r'fy\s*((?:19|20)\d{2})\s*[-–/]\s*(\d{2}|(?:19|20)\d{2})', text)
    if match:
        return ('year', (int(match.group(1)) + 1) * 12 + fiscal_year_end_month, 12)
    match = re.fullmatch(r'(?:cy\s*)?((?:19|20)\d{2})', text)
    if match:
        return ('year', int(match.group(1)) * 12 + 12, 12)
    match = re.fullmatch(r'([a-z]{3})[a-z]*\s*-?\s*(\d{2,4})', text)
    if match and match.group(1) in MONTHS:
        return ('month', _year(match.group(2)) * 12 + MONTHS[match.group(1)], 1)
    return None


def month_label(month_index) -> str:
    year, month = divmod(month_index - 1, 12)
    return f'{list(MONTHS)[month].title()}-{year % 100:02d}'


def describe_period(parsed) -> str:
    if parsed is None:
        return 'an unrecognised period'
    if parsed[0] == 'span':
        return f'the {parsed[2]} months to {month_label(parsed[1])}'
    return {'quarter': 'a quarter', 'year': 'a full year', 'month': 'a month-end point', 'run_rate': 'an annualised run rate'}[parsed[0]]


TOTAL_COLUMNS = ('total', 'full year', 'full-year', 'year total', '12 months')


def fact_period(fact, index=None, fiscal_year_end_month=3):
    """period_of() for a fact; a table's "Total" column over consecutive quarter columns is the span they cover."""
    parsed = period_of(fact.get('period'), fiscal_year_end_month)
    if parsed or not index or not fact.get('table') or ' '.join(str(fact.get('period', '')).lower().split()) not in TOTAL_COLUMNS:
        return parsed
    row = re.sub(r'c\d+$', '', fact['id'])
    quarters = sorted(p[1] for key, other in index.items()
                      if key != fact['id'] and re.fullmatch(re.escape(row) + r'c\d+', key)
                      and (p := period_of(other.get('period'), fiscal_year_end_month)) and p[0] == 'quarter')
    if len(quarters) >= 2 and quarters == list(range(quarters[0], quarters[0] + 3 * len(quarters), 3)):
        return ('span', quarters[-1], 3 * len(quarters))
    return None


def _length_key(parsed):
    """A 12-month span compares like a year; otherwise the kind and length must match."""
    return ('year' if parsed[0] == 'span' and parsed[2] == 12 else parsed[0], parsed[2])


def _unit(fact):
    unit = ' '.join(str(fact.get('unit', '')).lower().replace('million', 'mn').replace('billion', 'bn').split())
    return unit


def _metric(fact):
    return re.sub(r'[^a-z0-9]+', ' ', str(fact.get('metric', '')).lower()).strip()


def _is_projection(fact, fiscal_year_end_month=3):
    return fact.get('basis') in ('projection', 'target') or (period_of(fact.get('period'), fiscal_year_end_month) or ('',))[0] == 'run_rate'


KINDS = ['figure', 'rank', 'growth', 'multiple', 'cagr', 'share', 'ratio', 'sum', 'difference', 'convert', 'implied_rate']
CURRENCIES = ('USD', 'INR', 'EUR', 'GBP')


def _currency(fact):
    token = (str(fact.get('unit') or '').split() or [''])[0].upper()
    return token if token in CURRENCIES else ''


def _same_item(a, b):
    """The same metric, segment and period: one figure, possibly stated in two currencies."""
    return (_metric(a) == _metric(b) and str(a.get('segment', '')).lower() == str(b.get('segment', '')).lower()
            and ' '.join(str(a.get('period', '')).lower().split()) == ' '.join(str(b.get('period', '')).lower().split()))


class CalculationError(ValueError):
    pass


def _value(fact):
    value = parse_value(fact.get('value', ''))
    if value is None:
        raise CalculationError(f'{fact["id"]} has no numeric value')
    return value


def _same_unit(a, b):
    if _unit(a) == _unit(b) and (_unit(a) or a.get('document') == b.get('document')):
        return
    raise CalculationError(f'{a["id"]} ({_unit(a) or "no unit"}) and {b["id"]} ({_unit(b) or "no unit"}) are not in the same unit')


def comparable(fact, index, limit=6, fiscal_year_end_month=3):
    """Periods of the same series and period length as `fact`, for an actionable rejection message."""
    parsed = period_of(fact.get('period'), fiscal_year_end_month)
    if parsed is None or not index:
        return ''
    found = sorted({(p[1], other.get('period')) for other in index.values()
                    if other is not fact and _metric(other) == _metric(fact)
                    and str(other.get('segment', '')).lower() == str(fact.get('segment', '')).lower()
                    and _unit(other) == _unit(fact) and other.get('basis') == fact.get('basis')
                    and (p := period_of(other.get('period'), fiscal_year_end_month))
                    and (p[0], p[2]) == (parsed[0], parsed[2]) and p[1] != parsed[1]})
    if not found:
        return ''
    earlier = [label for month, label in found if month < parsed[1]][-3:]
    later = [label for month, label in found if month > parsed[1]][:3]
    periods = ', '.join(earlier + later)
    return f'; the same series has {describe_period(parsed)} figures for {periods} — compare {fact.get("period")} with one of those'


def _over_time(a, b, *, need_year_gap=False, index=None, fiscal_year_end_month=3):
    """a and b must measure the same thing over periods of the same length, b later than a."""
    if _metric(a) != _metric(b) or str(a.get('segment', '')).lower() != str(b.get('segment', '')).lower():
        raise CalculationError(f'{a["id"]} ("{a.get("metric")}" {a.get("segment", "")}) and {b["id"]} ("{b.get("metric")}" '
                               f'{b.get("segment", "")}) are different metrics or segments; a change over time needs the same series')
    _same_unit(a, b)
    pa, pb = period_of(a.get('period'), fiscal_year_end_month), period_of(b.get('period'), fiscal_year_end_month)
    if pa is None or pb is None:
        raise CalculationError(f'period "{a.get("period")}" or "{b.get("period")}" is not a recognised period')
    if (pa[0], pa[2]) != (pb[0], pb[2]):
        raise CalculationError(f'{a.get("period")} is {describe_period(pa)} and {b.get("period")} is {describe_period(pb)}; '
                               'a change over time needs periods of the same kind and length'
                               + comparable(b, index, fiscal_year_end_month=fiscal_year_end_month))
    if pb[1] <= pa[1]:
        raise CalculationError(f'{b.get("period")} is not later than {a.get("period")}')
    if need_year_gap and pb[1] - pa[1] < 12:
        raise CalculationError('a compound annual rate needs at least a year between the periods')
    return pa, pb


def _same_period(a, b, fiscal_year_end_month=3):
    pa, pb = period_of(a.get('period'), fiscal_year_end_month), period_of(b.get('period'), fiscal_year_end_month)
    same = (pa is not None and pa == pb) or ' '.join(str(a.get('period', '')).lower().split()) == ' '.join(str(b.get('period', '')).lower().split())
    if not same:
        raise CalculationError(f'{a["id"]} ({a.get("period") or "no period"}) and {b["id"]} ({b.get("period") or "no period"}) '
                               'are for different periods; a ratio, share or difference needs one period')


def _number(value, decimals):
    return f'{value:,.{decimals}f}'


def _amount(unit, value, decimals):
    """'USD Mn' and 14.47 -> 'USD 14.47 Mn': currency first, then the number, then its scale."""
    tokens = str(unit or '').split()
    if tokens and tokens[0].upper() in ('USD', 'INR', 'EUR', 'GBP'):
        return ' '.join([tokens[0], _number(value, decimals)] + tokens[1:])
    return f'{_number(value, decimals)} {unit}'.strip()


def _series(fact):
    return f'{fact.get("metric")}' + (f' ({fact["segment"]})' if fact.get('segment') else '')


AMOUNT_KINDS = ('sum', 'difference', 'convert')
CURRENCY = r'(?:USD|INR|EUR|GBP|Rs\.?|₹|\$)'
SCALE_WORD = r'(?:Mn|Bn|mn|bn|million|billion|crore|lakh|thousand|k)\b'


def compute(calc, index, fiscal_year_end_month=3):
    """Validate and compute one typed calculation. Returns a result dict or raises CalculationError.

    The result carries `sentence`: the evidence sentence code writes for the memorandum, so the
    figures, periods, metric names, basis and direction of a comparison are never model-written.
    """
    kind, decimals = calc['kind'], calc['decimals']
    def fact(key):
        fact_id = calc.get(key) or ''
        if fact_id not in index:
            raise CalculationError(f'{kind} needs `{key}`')
        return index[fact_id]
    if kind == 'figure':
        parts = [index[fact_id] for fact_id in calc.get('parts', []) if fact_id in index]
        if not parts or len(parts) != len(calc.get('parts', [])):
            raise CalculationError('figure needs one or more known facts in `parts`')
        values = [_value(part) for part in parts]
        text = '; '.join(_fact_amount(part) for part in parts)
        label = 'figures: ' + ', '.join(f'{_series(p)} {p.get("period", "")}'.strip() for p in parts)
        result = {'id': calc['id'], 'kind': kind, 'value': values[0], 'text': text, 'label': label,
                  'facts': [p['id'] for p in parts], 'projection': any(_is_projection(p, fiscal_year_end_month) for p in parts), 'over_time': None}
        result['sentence'] = _figure_sentence(parts, index, fiscal_year_end_month)
        return result
    if kind == 'rank':
        parts = [index[fact_id] for fact_id in calc.get('parts', []) if fact_id in index]
        if len(parts) < 2 or len(parts) != len(calc.get('parts', [])):
            raise CalculationError('rank needs at least two known facts in `parts`')
        if len({_metric(p) for p in parts}) != 1:
            raise CalculationError('rank orders one metric across segments, entities or periods; these facts measure different metrics')
        for other in parts[1:]:
            _same_unit(parts[0], other)
        ordered = sorted(parts, key=_value, reverse=True)
        result = {'id': calc['id'], 'kind': kind, 'value': _value(ordered[0]), 'text': ' > '.join(_fact_amount(p) for p in ordered),
                  'label': f'{_series(parts[0]).split(" (")[0]} ranked', 'facts': [p['id'] for p in parts],
                  'projection': any(_is_projection(p, fiscal_year_end_month) for p in parts), 'over_time': None}
        result['sentence'] = _rank_sentence(ordered, index, fiscal_year_end_month)
        return result
    if kind in ('growth', 'multiple', 'cagr'):
        a, b = fact('a'), fact('b')
        pa, pb = _over_time(a, b, need_year_gap=kind == 'cagr', index=index, fiscal_year_end_month=fiscal_year_end_month)
        va, vb = _value(a), _value(b)
        if va <= 0 or (kind == 'cagr' and vb <= 0):
            raise CalculationError(f'{kind} needs a positive starting value')
        if kind == 'growth':
            value, text = (vb / va - 1) * 100, None
            text = f'{"+" if value >= 0 else ""}{_number(value, decimals)}%'
        elif kind == 'multiple':
            value = vb / va
            text = f'{_number(value, decimals)}x'
        else:
            years = (pb[1] - pa[1]) / 12
            value = ((vb / va) ** (1 / years) - 1) * 100
            text = f'{_number(value, decimals)}% a year'
        label = (f'{kind} in {a.get("metric")}' + (f' ({a["segment"]})' if a.get('segment') else '') +
                 f' from {a.get("period")} to {b.get("period")}')
        inputs, gap = [a, b], pb[1] - pa[1]
        over_time = {'length': pa[2], 'gap': gap}
    elif kind == 'implied_rate':
        a, b = fact('a'), fact('b')
        if not (_same_item(a, b) and _currency(a) and _currency(b) and _currency(a) != _currency(b)):
            raise CalculationError(f'an implied exchange rate needs one figure stated in two currencies; {_series(a)} '
                                   f'({a.get("unit")}) and {_series(b)} ({b.get("unit")}) are not that')
        vb = _value(b)
        if vb == 0:
            raise CalculationError('division by zero')
        value = _value(a) / vb
        text = f'{_number(value, decimals)} {_currency(a)}/{_currency(b)}'
        label = f'exchange rate implied by {_series(a)} {a.get("period", "")} in {_currency(a)} and {_currency(b)}'
        inputs, over_time = [a, b], None
    elif kind in ('share', 'ratio'):
        a, b = fact('a'), fact('b')
        if _same_item(a, b):
            raise CalculationError(f'{_series(a)} is compared with itself; if it is stated in two currencies, '
                                   'declare an implied_rate instead')
        _same_period(a, b, fiscal_year_end_month)
        segment_a, segment_b = (str(x.get('segment', '')).strip().lower() for x in (a, b))
        part_of_total = kind == 'share' and _metric(a) == _metric(b) and segment_b in ('', 'total', 'overall', 'all')
        if segment_a != segment_b and not part_of_total:
            raise CalculationError(f'{_series(a)} and {_series(b)} are different segments; compare one segment with itself, '
                                   'or a segment as a share of the same metric\'s total')
        if kind == 'share':
            _same_unit(a, b)
        vb = _value(b)
        if vb == 0:
            raise CalculationError('division by zero')
        value = _value(a) / vb * (100 if kind == 'share' else 1)
        text = f'{_number(value, decimals)}%' if kind == 'share' else f'{_number(value, decimals)}x'
        label = (f'{_series(a)} {"as a share of" if kind == "share" else "relative to"} {_series(b)}, '
                 f'{a.get("period") or "same period"}')
        inputs, over_time = [a, b], None
    elif kind == 'sum':
        parts = [index[fact_id] for fact_id in calc.get('parts', []) if fact_id in index]
        if len(parts) < 2 or len(parts) != len(calc.get('parts', [])):
            raise CalculationError('sum needs at least two known facts in `parts`')
        for other in parts[1:]:
            _same_unit(parts[0], other)
        periods = [period_of(p.get('period'), fiscal_year_end_month) for p in parts]
        one_period = len({' '.join(str(p.get('period', '')).lower().split()) for p in parts}) == 1
        consecutive_quarters = (all(p and p[0] == 'quarter' for p in periods) and len({_metric(p) for p in parts}) == 1 and
                                sorted(p[1] for p in periods) == list(range(min(p[1] for p in periods), min(p[1] for p in periods) + 3 * len(parts), 3)))
        if not (one_period or consecutive_quarters):
            raise CalculationError('sum needs facts for one period, or consecutive quarters of one metric')
        value = sum(_value(p) for p in parts)
        text = _amount(parts[0].get('unit', ''), value, decimals)
        names = [' '.join(str(p.get(key, '')) for key in ('metric', 'segment', 'period')).strip() for p in parts]
        label = 'total of ' + (', '.join(names) if len(parts) <= 4 else
                               f'{len(parts)} figures ({names[0]}, {names[1]} … {names[-1]})')
        inputs, over_time = parts, ({'length': 3 * len(parts), 'gap': 0} if consecutive_quarters and not one_period else None)
    elif kind == 'difference':
        a, b = fact('a'), fact('b')
        _same_unit(a, b)
        try:
            _same_period(a, b, fiscal_year_end_month)
            over_time = None
        except CalculationError:
            pa, pb = _over_time(b, a, index=index, fiscal_year_end_month=fiscal_year_end_month)
            over_time = {'length': pa[2], 'gap': pb[1] - pa[1]}
        value = _value(a) - _value(b)
        text = _amount(a.get('unit', ''), value, decimals)
        label = f'{_series(a)} {a.get("period", "")} minus {_series(b)} {b.get("period", "")}'
        inputs = [a, b]
    elif kind == 'convert':
        a, rate = fact('a'), fact('rate')
        rate_unit = _unit(rate)
        if '/' not in rate_unit:
            raise CalculationError(f'{rate["id"]} is not an exchange rate (unit "{rate.get("unit")}")')
        quote, base = [part.strip() for part in rate_unit.split('/', 1)]
        source = _unit(a).split()[0] if _unit(a) else ''
        scale = ' '.join(_unit(a).split()[1:])
        if source == quote:
            value, target = _value(a) / _value(rate), base
        elif source == base:
            value, target = _value(a) * _value(rate), quote
        else:
            raise CalculationError(f'{a["id"]} is in "{a.get("unit")}", which the rate {rate_unit} does not convert')
        text = f'{target.upper()} {_number(value, decimals)} {scale.title()}'.strip()
        label = f'{a.get("metric")} converted at {rate.get("value")} {rate.get("unit")}'
        inputs, over_time = [a, rate], None
    else:
        raise CalculationError(f'unknown calculation kind {kind}')
    result = {'id': calc['id'], 'kind': kind, 'value': round(value, decimals), 'text': text, 'label': label,
              'facts': [item['id'] for item in inputs], 'projection': any(_is_projection(item, fiscal_year_end_month) for item in inputs),
              'over_time': over_time}
    stated = index.get(calc.get('b') or '') if kind == 'convert' else None
    result['sentence'] = _calculation_sentence(kind, result, inputs, index, decimals, stated, fiscal_year_end_month)
    return result


# ---------------------------------------------------------------- evidence sentences

NO_SEGMENT = ('', 'total', 'overall', 'all')
UNIT_WORDS = {'USD', 'INR', 'EUR', 'GBP', 'MN', 'BN', 'MILLION', 'BILLION'}
VERBS = {'historical': 'was', 'projection': 'is projected at', 'target': 'is targeted at', 'company_model': 'is modelled at',
         'company_claim': 'is stated by the company as', 'third_party': 'is cited by the company from a third-party source as',
         'definition': 'is defined as'}


def _display_metric(fact):
    """'Gross Premium' -> 'gross premium'; names and acronyms keep their capitals ('Pre Series A Valuation' -> 'pre Series A valuation')."""
    words = [word for word in str(fact.get('metric', '')).split() if word.upper() not in UNIT_WORDS]
    return ' '.join(word.lower() if word.lower() in COMMON_WORDS else word for word in words) or 'figure'


COMMON_WORDS = {'gross', 'net', 'premium', 'premiums', 'revenue', 'revenues', 'margin', 'margins', 'channel', 'payout', 'payouts',
                'indirect', 'spend', 'spends', 'costs', 'cost', 'advertising', 'payroll', 'equity', 'raised', 'venture', 'debt',
                'pre', 'post', 'money', 'valuation', 'shareholding', 'exchange', 'rate', 'customer', 'customers', 'count',
                'channel', 'partners', 'partner', 'milestone', 'run', 'total', 'potential', 'policies', 'policy', 'growth',
                'profit', 'loss', 'income', 'operating', 'cash', 'burn', 'runway', 'headcount', 'users', 'orders', 'share',
                'and', 'of', 'per', 'to', 'by', 'for', 'the', 'in'}


def _name(fact):
    segment = str(fact.get('segment') or '').strip()
    return _display_metric(fact) + ('' if segment.lower() in NO_SEGMENT else f' for {segment}')


def _decimals(raw):
    match = re.search(r'\.(\d+)', str(raw))
    return len(match.group(1)) if match else 0


def _plain_amount(unit, value, decimals):
    text = re.sub(r'\s+counts?$', '', _amount(unit, value, decimals), flags=re.IGNORECASE)
    return re.sub(r'\b(?:million|mn)\b', 'Mn', re.sub(r'\b(?:billion|bn)\b', 'Bn', text, flags=re.IGNORECASE), flags=re.IGNORECASE)


def _fact_amount(fact):
    value = _value(fact)
    return ('negative ' if value < 0 else '') + _plain_amount(fact.get('unit', ''), abs(value), _decimals(fact.get('value')))


def _when(fact, index, fiscal_year_end_month=3):
    """The period a figure covers, in words: 'in Q1-FY23', 'in the 12 months to Sep-23', 'at Sep 21'."""
    parsed, label = fact_period(fact, index, fiscal_year_end_month), ' '.join(str(fact.get('period') or '').split())
    if parsed is None:
        return ''
    if parsed[0] == 'span':
        return f'in the {parsed[2]} months to {month_label(parsed[1])}'
    if parsed[0] == 'month':
        return f'at {label}'
    if parsed[0] == 'run_rate':
        return f'at the {label}' if 'run rate' in label.lower() else f'at the {label} run rate'
    if parsed[0] == 'quarter' and not re.match(r'q[1-4]', label.lower()):
        return f'in the quarter to {month_label(parsed[1])}'
    return f'in {label}'


def _listing(items):
    items = [item for item in items if item]
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]


def _capital(text):
    text = ' '.join(text.split())
    text = re.sub(r'(\d)\s+%', r'\1%', re.sub(r'\b(?:Million|mn)\b', 'Mn', re.sub(r'\b(?:Billion|bn)\b', 'Bn', text)))
    return text[:1].upper() + text[1:]


def _figure_sentence(parts, index, fiscal_year_end_month=3):
    """'Revenue was USD 0.40 Mn in Q3-FY22 and USD 0.73 Mn in Q4-FY22; EBITDA ...', in period order per series."""
    order = []
    for part in parts:
        if _name(part) not in order:
            order.append(_name(part))
    clauses = []
    for name in order:
        series = sorted((p for p in parts if _name(p) == name), key=lambda p: (fact_period(p, index, fiscal_year_end_month) or ('', 0, 0))[1])
        runs = []
        for part in series:
            verb = VERBS.get(part.get('basis'), 'was')
            if runs and runs[-1][0] == verb:
                runs[-1][1].append(part)
            else:
                runs.append((verb, [part]))
        said = [f'{verb} ' + _listing([f'{_fact_amount(p)} {_when(p, index, fiscal_year_end_month)}'.strip() for p in items]) for verb, items in runs]
        clauses.append(f'{name} ' + ' and '.join(said))
    return _capital('; '.join(clauses)) + '.'


def _rank_sentence(ordered, index, fiscal_year_end_month=3):
    """'Gross margin is projected highest for Home & Content (45%), then EV & Motor (20%), and lowest for SME & Gig (15%).'"""
    segments = {str(p.get('segment') or '').strip() for p in ordered}
    def where(part):
        segment = str(part.get('segment') or '').strip()
        if len(segments) > 1 and segment.lower() not in NO_SEGMENT:
            return f'for {segment}'
        return _when(part, index, fiscal_year_end_month) or f'for {segment or "the total"}'
    verb = 'is projected' if all(_is_projection(p, fiscal_year_end_month) for p in ordered) else 'is'
    if (len(segments) > 1 and len({' '.join(str(p.get('period') or '').split()) for p in ordered}) == 1
            and _when(ordered[0], index, fiscal_year_end_month)):
        verb += f' {_when(ordered[0], index, fiscal_year_end_month)}'
    middle = ''.join(f', then {where(p)} ({_fact_amount(p)})' for p in ordered[1:-1])
    return _capital(f'{_display_metric(ordered[0])} {verb} highest {where(ordered[0])} ({_fact_amount(ordered[0])}){middle}, '
                    f'and lowest {where(ordered[-1])} ({_fact_amount(ordered[-1])})') + '.'


def _calculation_sentence(kind, result, inputs, index, decimals, stated=None, fiscal_year_end_month=3):
    value, text = result['value'], result['text']
    projected = result['projection']
    if kind in ('growth', 'multiple', 'cagr'):
        a, b = inputs
        start, end = (f'{_fact_amount(a)} {_when(a, index, fiscal_year_end_month)}'.strip(),
                      f'{_fact_amount(b)} {_when(b, index, fiscal_year_end_month)}'.strip())
        span = result['over_time']['gap']
        over = '' if span in (result['over_time']['length'], 12) else f', over {span} months'
        if kind == 'growth':
            verb = ('is projected to rise' if projected else 'rose') if value >= 0 else ('is projected to fall' if projected else 'fell')
            # "+4,100%" is how a spreadsheet prints a large rise; an investor reads it as a multiple.
            amount = f'{1 + value / 100:.1f}x' if value > 200 else f'{_number(abs(value), decimals)}%'
            return _capital(f'{_name(a)} {verb} {amount} from {start} to {end}{over}') + '.'
        if kind == 'multiple':
            return _capital(f'{_name(b)} of {end} {"is projected at" if projected else "was"} {_number(value, decimals)} times '
                            f'its level of {start}{over}') + '.'
        verb = ('is projected to grow' if projected else 'grew') if value >= 0 else ('is projected to fall' if projected else 'fell')
        return _capital(f'{_name(a)} {verb} at a compound {_number(abs(value), decimals)}% a year from {start} to {end}') + '.'
    if kind in ('share', 'ratio'):
        a, b = inputs
        # "0.1 times" reads as a rounding accident; below one, a ratio is a percentage.
        whole = kind == 'share' or abs(value) < 1
        amount = f'{_number(value, decimals)}%' if kind == 'share' else f'{_number(value * 100, decimals)}%' if whole else f'{_number(value, decimals)} times'
        verb = 'is projected at' if projected else 'was'
        return _capital(f'{_name(a)} ({_fact_amount(a)}) {verb} {amount} {"of" if whole else ""} '
                        f'{_name(b)} ({_fact_amount(b)}) {_when(a, index, fiscal_year_end_month)}') + '.'
    if kind == 'sum':
        verb = 'are projected to total' if projected else 'total'
        if result['over_time']:
            ordered = sorted(inputs, key=lambda p: (fact_period(p, index, fiscal_year_end_month) or ('', 0, 0))[1])
            return _capital(f'{_name(ordered[0])} {"is projected to total" if projected else "totalled"} {text} across '
                            f'{ordered[0].get("period")} to {ordered[-1].get("period")}') + '.'
        when = _when(inputs[0], index, fiscal_year_end_month)
        if len({_metric(p) for p in inputs}) == 1 and all(str(p.get('segment') or '').strip() for p in inputs):
            segments = [str(p['segment']).strip() for p in inputs]
            named = _listing(segments) if len(segments) <= 5 else f'the {len(segments)} listed, from {segments[0]} to {segments[-1]}'
            return _capital(f'The {_display_metric(inputs[0])} figures for {named} {verb} {text} {when}') + '.'
        names = [_name(p) for p in inputs]
        named = _listing(names) if len(names) <= 5 else f'{len(names)} figures, from {names[0]} to {names[-1]}'
        return _capital(f'{named} {verb} {text} {when}') + '.'
    if kind == 'difference':
        a, b = inputs
        gap = _plain_amount(a.get('unit', ''), abs(value), decimals)
        if result['over_time']:
            direction = 'higher' if value > 0 else 'lower'
            return _capital(f'{_name(a)} {_when(a, index, fiscal_year_end_month)} ({_fact_amount(a)}) was {gap} {direction} than '
                            f'{_when(b, index, fiscal_year_end_month)} ({_fact_amount(b)})') + '.'
        relation = 'equals' if value == 0 else ('exceeds' if value > 0 else 'is below')
        by = '' if value == 0 else f' by {gap}'
        return _capital(f'{_name(a)} ({_fact_amount(a)}) {relation} {_name(b)} ({_fact_amount(b)}){by} '
                        f'{_when(a, index, fiscal_year_end_month)}') + '.'
    if kind == 'convert':
        a, rate = inputs
        rate_text = f'{rate.get("value")} {rate.get("unit")}'.strip()
        sentence = f'{_name(a)} of {_fact_amount(a)} converts to {text} at {rate_text}'
        if stated is not None and _same_item(a, stated) and _currency(stated) == text.split()[0]:
            difference = _value(stated) - value
            if round(difference, decimals) != 0:
                gap = _plain_amount(stated.get('unit', ''), abs(difference), decimals)
                sentence += (f', while the materials state {_fact_amount(stated)}, {gap} '
                             f'{"more" if difference > 0 else "less"} than the conversion')
        return _capital(sentence) + '.'
    if kind == 'implied_rate':
        a, b = inputs
        return _capital(f'{_name(a)} is stated as {_fact_amount(a)} and as {_fact_amount(b)}, which implies {text}') + '.'
    return _capital(f'{result["label"]} is {text}') + '.'


# ---------------------------------------------------------------- sentence checks

CHANGE_WORDS = re.compile(r'\b(grow|grew|grown|growth|growing|increas\w*|rose|rise|rises|rising|up from|doubl\w*|tripl\w*|'
                          r'declin\w*|decreas\w*|fell|fall|falls|falling|jump\w*|surg\w*|expan\w*|contract\w*|climb\w*|'
                          r'yoy|year-on-year|year-over-year|qoq|quarter-on-quarter|quarter-over-quarter|cagr|annuali[sz]ed|'
                          r'compound\w*|accelerat\w*|scal(?:ed|ing) from|improv\w*|narrow\w*|widen\w*|deteriorat\w*|'
                          r'worsen\w*|recover\w*)\b', re.IGNORECASE)
# Words that set two figures against each other without describing a change; across periods they still need
# periods of the same length.
COMPARE_WORDS = re.compile(r'\b(exceed\w*|outpac\w*|higher than|lower than|more than|less than|above|below|'
                           r'compared (?:with|to)|versus|vs\.?|against|relative to)\b', re.IGNORECASE)
# A named profit or margin measure; a calculation must not be given a name its inputs do not carry.
NAMED_MEASURE = re.compile(r'\b(ebitda|ebit|gross margin|net margin|operating margin|contribution margin|gross profit|'
                           r'net profit|operating profit|pat)\b', re.IGNORECASE)
# Saying a figure is over- or understated is a direction claim; it needs the comparison in front of the reader.
DIRECTION_WORDS = re.compile(r'\b(overstat\w*|understat\w*|overvalu\w*|undervalu\w*)\b', re.IGNORECASE)
# "The remaining 29%" is a claim about what is left of a whole; only a difference computes it.
REMAINDER_WORDS = re.compile(r'\b(remaining|remainder|the rest|balance of)\b', re.IGNORECASE)
# A change across a gap longer than one period must say how long the span is ("over two quarters").
# Two rates set against each other: both must be printed, and in the order the words claim.
PACE_WORDS = re.compile(r'\b(outpac\w+|outgrew|outstrip\w*|faster than|slower than|(?:a )?(?:slower|faster) pace|lagg\w+)\b', re.IGNORECASE)
# A claim that margins or unit economics are moving needs a figure on the page.
MARGIN_CLAIM = re.compile(r'\b(?:improv\w+|expand\w+|widen\w+|better\w*)\b[^.]{0,30}\b(?:unit economics|margins?|spread)\b|'
                          r'\b(?:unit economics|margins?|spread)\b[^.]{0,20}\b(?:improv\w+|expand\w+|widen\w+)\b', re.IGNORECASE)
# "The final quarter of FY23" is a period claim, so it needs a figure whose period code can check.
QUARTER_OF_YEAR = re.compile(r'\b(?:first|second|third|fourth|final|last) quarter of FY\s?-?\d', re.IGNORECASE)
# A change printed as a level: "widened to USD -0.47 Mn" reads as the loss itself, when it is how far the loss moved.
NAME_NOISE = {'usd', 'inr', 'eur', 'gbp', 'total', 'the', 'and', 'for', 'per'}
LEVEL_WORDS = re.compile(r'\b(to|at|reached|reaching|was|were)\s*$', re.IGNORECASE)
SPAN_WORDS = re.compile(r'\bthat (?:span|period)\b|\b(over|across|in) (?:the )?(?:two|three|four|five|six|\d+) (?:quarters|months|years)\b|'
                        r'\bcumulative\w*\b', re.IGNORECASE)
FY_LABEL = re.compile(r'(?<![\w-])FY\s?-?\s?(\d{2}|(?:19|20)\d{2})(?![\w-])')
ANNUAL_WORDS = re.compile(r'\b(cagr|compound annual|annuali[sz]ed growth|per annum|a year|per year|yearly|annual growth|'
                          r'year-on-year|year-over-year|yoy)\b', re.IGNORECASE)
QUARTER_WORDS = re.compile(r'\b(qoq|quarter-on-quarter|quarter-over-quarter|sequential\w*)\b', re.IGNORECASE)
PROJECTION_WORDS = re.compile(r'\b(project\w*|forecast\w*|plan|plans|planned|planning|target\w*|expect\w*|estimat\w*|budget\w*|'
                              r'model\w*|aim\w*|assum\w*|anticipat\w*|guidance|outlook|scenario\w*|would|run[- ]rate|exit rate|'
                              r'goal\w*|ambition\w*|intend\w*|seek\w*|potential|pipeline)\b', re.IGNORECASE)
RUN_RATE_WORDS = re.compile(r'\b(run[- ]rate|exit|annuali[sz]ed|arr)\b', re.IGNORECASE)
ATTRIBUTION_WORDS = re.compile(r'\b(according to|estimat\w*|report\w*|source\w*|research|survey\w*|cited|per|data from|'
                               r'states?|stated|says|publishes|published)\b', re.IGNORECASE)
# Metric words that are commonly swapped. If a cited figure measures the first and the
# sentence names only the second, the sentence describes a different metric.
CONFUSABLE = [('premium', 'revenue'), ('polic', 'customer'), ('gmv', 'revenue'), ('booking', 'revenue'),
              ('user', 'customer'), ('install', 'customer'), ('lead', 'customer'), ('arr', 'revenue')]
# Direction words, checked against the sign of a change. A loss that shrinks is a positive change, so
# narrower and wider are read from the change in the figure and not from its size.
RISE_WORDS = re.compile(r'\b(grow|grew|grown|increas\w*|rose|rise|rises|rising|doubl\w*|tripl\w*|jump\w*|surg\w*|climb\w*|expan\w*)\b', re.IGNORECASE)
FALL_WORDS = re.compile(r'\b(declin\w*|decreas\w*|fell|fall|falls|falling|contract\w*|shrank|shrink\w*|dropp\w*)\b', re.IGNORECASE)
WIDER_WORDS = re.compile(r'\b(widen\w*|wider|deepen\w*|deteriorat\w*|worsen\w*)\b', re.IGNORECASE)
NARROWER_WORDS = re.compile(r'\b(narrow(?:ed|ing|s|er)|improv\w*)\b', re.IGNORECASE)
# "A outpaced B" claims A is the larger of two like readings; "A trailed B" the smaller.
LARGER_WORDS = re.compile(r'\b(outpac\w*|outgrew|exceed\w*|ahead of|higher than|greater than|larger than|faster than)\b', re.IGNORECASE)
SMALLER_WORDS = re.compile(r'\b(lag\w*|trail\w*|behind|lower than|less than|smaller than|slower than)\b', re.IGNORECASE)
# A run rate or projection is never an actual: the word beside it would misstate what the figure is.
ACTUAL_WORDS = re.compile(r'\b(actual|actuals|realized|realised|reported|recorded|achieved)\b', re.IGNORECASE)
PLACEHOLDER = re.compile(r'\{(c\w{0,10})\}')
SENTENCE = re.compile(r'(?<=[.!?;])\s+(?=[A-Z(\"“{])')


def sentences(text):
    return [part for part in SENTENCE.split(text) if part.strip()]


def _clip(sentence):
    return sentence if len(sentence) <= 140 else sentence[:137] + '...'


def _matched_facts(sentence, cited):
    """Cited facts whose value is printed in the sentence."""
    printed = numbers_in(PLACEHOLDER.sub('', sentence))
    matches = []
    for fact in cited:
        value = parse_value(fact.get('value', ''))
        if value is not None and abs(value) >= 1e-12 and number_present(value, printed):
            matches.append(fact)
    return matches


def _word(pattern, text):
    return re.search(pattern, text, re.IGNORECASE) is not None


def sentence_problems(text, cited, results, *, label, index=None, fiscal_year_end_month=3):
    """Deterministic meaning problems in one paragraph. `cited` are the paragraph's fact dicts;
    `results` maps calculation id -> compute() result; `index` (all facts) adds comparable periods to the fix."""
    problems = []
    text = restore_placeholders(text, results)
    for sentence in sentences(text):
        quote = _clip(sentence)
        if evidence_only(sentence):
            continue  # code writes this sentence from the calculation
        changes = CHANGE_WORDS.search(sentence)
        projected_words = PROJECTION_WORDS.search(sentence)
        for calc_id in PLACEHOLDER.findall(sentence):
            result = results.get(calc_id)
            if not isinstance(result, dict):
                continue
            as_amount = re.search(CURRENCY + r'\s*\{' + calc_id + r'\}|\{' + calc_id + r'\}\s*' + SCALE_WORD, sentence)
            if as_amount and (result['kind'] not in AMOUNT_KINDS or result['text'].rstrip().endswith('%')):
                problems.append(f'{label}: "{quote}" writes {calc_id} as a money amount, but it is a {result["kind"]} '
                                f'({result["label"]} = {result["text"]}); write the placeholder alone, without a currency or scale')
            over_time = result['over_time']
            # "Grew from {a} to {b}, a {c} increase": the figures are fine when the same sentence carries their change.
            if changes and over_time is None and not any(
                    isinstance(results.get(c), dict) and results[c].get('over_time') for c in PLACEHOLDER.findall(sentence)):
                problems.append(f'{label}: "{quote}" uses "{changes.group(0)}" for {calc_id} ({result["label"]}), which compares '
                                f'two figures for one period, not a change over time; describe it as a {result["kind"]}')
            if over_time and ANNUAL_WORDS.search(sentence) and result['kind'] != 'cagr' and \
                    not (over_time['length'] == 12 or over_time['gap'] == 12):
                problems.append(f'{label}: "{quote}" calls {calc_id} annual, but it compares periods {over_time["gap"]} months apart '
                                f'({result["label"]}); declare a cagr or describe the actual periods')
            if over_time and QUARTER_WORDS.search(sentence) and not (over_time['length'] == 3 and over_time['gap'] == 3):
                problems.append(f'{label}: "{quote}" calls {calc_id} quarter-on-quarter, but it is {result["label"]}')
            # Printing both end figures beside the growth states the span.
            printed_ends = {item for other in PLACEHOLDER.findall(sentence) if other != calc_id and isinstance(results.get(other), dict)
                            and results[other]['kind'] == 'figure' for item in results[other]['facts']}
            if (result['kind'] == 'growth' and over_time and over_time['gap'] not in (over_time['length'], 12)
                    and not SPAN_WORDS.search(sentence) and not set(result['facts']) <= printed_ends):
                problems.append(f'{label}: "{quote}" states {calc_id} ({result["label"]}), which skips the periods in between; '
                                'compare consecutive periods or the same period a year earlier, or state the span')
            if result['projection'] and not projected_words:
                problems.append(f'{label}: "{quote}" states {calc_id}, which uses company projections or run rates, without '
                                'saying it is a projection')
            # The words since the previous figure name this one.
            before = re.split(r'\}|\d[\d,.]*\s*(?:%|x\b|mn\b|bn\b|million\b|billion\b)', sentence[:sentence.index('{' + calc_id + '}')],
                              flags=re.IGNORECASE)[-1]
            if over_time and result['kind'] in ('growth', 'difference'):
                near = before[-60:] + ' ' + PLACEHOLDER.split(sentence[sentence.index('{' + calc_id + '}') + len(calc_id) + 2:])[0][:30]
                up, down = result['value'] > 0, result['value'] < 0
                word = (FALL_WORDS.search(near) if up and not RISE_WORDS.search(near) else
                        RISE_WORDS.search(near) if down and not FALL_WORDS.search(near) else None)
                word = word or (WIDER_WORDS.search(near) if up else NARROWER_WORDS.search(near) if down else None)
                if word:
                    problems.append(f'{label}: "{quote}" says "{word.group(0)}", but {calc_id} ({result["label"]}) is {result["text"]}; '
                                    'the words must match the direction of the change')
            if result['kind'] == 'difference' and over_time and LEVEL_WORDS.search(before[-14:]):
                problems.append(f'{label}: "{quote}" prints {calc_id} as a level, but it is the change between two periods '
                                f'({result["label"]} = {result["text"]}); write "by" before it, or use the figure for the period')
            # A change belongs to a measure: with no name beside it, the reader assumes the measure in the sentence before.
            if index and result['kind'] in ('growth', 'difference'):
                measure = {word for item in result['facts'] if item in index for word in re.findall(r'[a-z]{3,}', str(index[item].get('metric', '')).lower())}
                if measure and not any(re.search(r'\b' + word, sentence.lower()) for word in measure):
                    problems.append(f'{label}: "{quote}" states {calc_id} ({result["label"]}) without naming that measure; name it')
            # A figure keeps its own name: renaming it can turn a past valuation into the terms of a live round.
            if index and result['kind'] == 'figure':
                named_as = {word for item in result['facts'] if item in index for word in re.findall(r'[a-z]{3,}', str(index[item].get('metric', '')).lower())} - NAME_NOISE
                missing = sorted(word for word in named_as if not re.search(r'\b' + word.rstrip('s'), sentence.lower()))
                if missing and len(named_as) <= 4:
                    problems.append(f'{label}: "{quote}" calls {calc_id} something other than its name ({result["label"]}); use the words "{" ".join(missing)}"')
            if result['projection'] and ACTUAL_WORDS.search(before[-45:]):
                problems.append(f'{label}: "{quote}" calls {calc_id} "{ACTUAL_WORDS.search(before[-45:]).group(0)}", but {result["label"]} is a '
                                'projection or run rate; name it as what it is')
            named = list(NAMED_MEASURE.finditer(before[-80:]))
            if named and named[-1].group(0).lower() not in result['label'].lower():
                problems.append(f'{label}: "{quote}" calls {calc_id} {named[-1].group(0)}, but it is {result["label"]}; '
                                'use the name of the measure it was computed from')
            if REMAINDER_WORDS.search(before[-40:]) and result['kind'] != 'difference':
                problems.append(f'{label}: "{quote}" calls {calc_id} the {REMAINDER_WORDS.search(before[-40:]).group(0)}, but it '
                                f'is {result["label"]}; a remainder needs a difference calculation from the whole')
        if DIRECTION_WORDS.search(sentence) and not any(
                isinstance(results.get(c), dict) and results[c]['kind'] in ('convert', 'difference')
                for c in PLACEHOLDER.findall(sentence)):
            problems.append(f'{label}: "{quote}" says a figure is {DIRECTION_WORDS.search(sentence).group(0)} without a '
                            'code-computed comparison; declare the convert or difference calculation and print both figures')
        pair = [results.get(c) for c in PLACEHOLDER.findall(sentence)]
        if len(pair) == 2 and all(isinstance(item, dict) for item in pair) and pair[0]['kind'] == pair[1]['kind']:
            between = sentence[sentence.index('}') + 1:sentence.rindex('{')]
            larger, smaller = LARGER_WORDS.search(between), SMALLER_WORDS.search(between)
            if larger and pair[0]['value'] < pair[1]['value'] or smaller and pair[0]['value'] > pair[1]['value']:
                problems.append(f'{label}: "{quote}" says "{(larger or smaller).group(0)}", but {pair[0]["text"]} ({pair[0]["label"]}) '
                                f'against {pair[1]["text"]} ({pair[1]["label"]}) shows the opposite')
        # A fiscal-year name beside a printed reading must be the period of a figure behind that reading.
        printed = [results[c] for c in PLACEHOLDER.findall(sentence) if isinstance(results.get(c), dict)]
        pace = PACE_WORDS.search(sentence)
        moves = [result for result in printed if result.get('over_time')]
        if pace and len(moves) < 2:
            problems.append(f'{label}: "{quote}" says "{pace.group(0)}" without both rates; print both readings, the one the sentence is about first')
        elif pace and (moves[0]['value'] < moves[1]['value']) != bool(re.search('slow|lag', pace.group(0), re.IGNORECASE)):
            problems.append(f'{label}: "{quote}" says "{pace.group(0)}", but {moves[0]["text"]} ({moves[0]["label"]}) against {moves[1]["text"]} '
                            f'({moves[1]["label"]}) shows the opposite')
        if not printed and MARGIN_CLAIM.search(sentence):
            problems.append(f'{label}: "{quote}" says margins or unit economics moved without a reading; print the reading, or leave the claim out')
        if not printed and QUARTER_OF_YEAR.search(sentence):
            problems.append(f'{label}: "{quote}" names a fiscal quarter without a figure; print the figure for that period')
        if index and printed:
            behind = [fact_period(index[item], index) for result in printed for item in result['facts'] if item in index]
            for year in FY_LABEL.finditer(sentence):
                named = _year(year.group(1)) * 12 + 3
                if behind and all(period and period[1] != named and not (period[0] == 'quarter' and named - 12 < period[1] <= named) for period in behind):
                    problems.append(f'{label}: "{quote}" says {year.group(0)}, but its figure covers {describe_period(behind[0])}; '
                                    'name the period the figure actually covers')
        loss_word = WIDER_WORDS.search(sentence) or NARROWER_WORDS.search(sentence)
        if loss_word and numbers_in(PLACEHOLDER.sub('', sentence)) and not any(
                isinstance(results.get(c), dict) and results[c].get('over_time') for c in PLACEHOLDER.findall(sentence)):
            problems.append(f'{label}: "{quote}" says "{loss_word.group(0)}" without a code-computed change; use a reading that compares the two periods')
        matched = _matched_facts(sentence, cited)
        # Two literal figures of one series set against each other across different kinds of period. The
        # earlier figure is often an uncited fact of the same series, so the index is searched for it too.
        compares = COMPARE_WORDS.search(sentence)
        if changes or compares:
            compared = list(matched)
            if index:
                series = {(_metric(f), str(f.get('segment', '')).lower()) for f in matched}
                printed = numbers_in(PLACEHOLDER.sub('', sentence))
                for other in index.values():
                    value = parse_value(other.get('value', ''))
                    if ((_metric(other), str(other.get('segment', '')).lower()) in series and other not in compared
                            and value is not None and abs(value) >= 1e-12 and number_present(value, printed)):
                        compared.append(other)
            for i, first in enumerate(compared):
                for second in compared[i + 1:]:
                    if _metric(first) != _metric(second):
                        continue
                    p1, p2 = fact_period(first, index, fiscal_year_end_month), fact_period(second, index, fiscal_year_end_month)
                    if p1 and p2 and _length_key(p1) != _length_key(p2):
                        shorter = first if p1[2] < p2[2] else second
                        problems.append(f'{label}: "{quote}" sets {first.get("period")} ({describe_period(p1)}) against '
                                        f'{second.get("period")} ({describe_period(p2)}); compare periods of the same length'
                                        + comparable(shorter, index, fiscal_year_end_month=fiscal_year_end_month))
        problems += _fiscal_label_problems(sentence, matched, index, label, quote, fiscal_year_end_month)
        lowered = sentence.lower()
        for fact in matched:
            value = fact.get('value')
            same_value = [other for other in matched if other.get('value') == value]
            if fact.get('basis') in ('projection', 'target') and not projected_words and \
                    all(other.get('basis') in ('projection', 'target') for other in same_value):
                problems.append(f'{label}: "{quote}" states {value} ({fact["statement"][:80]}) as fact; it is a company '
                                f'{fact["basis"]} and must be labelled as one')
            elif (period_of(fact.get('period'), fiscal_year_end_month) or ('',))[0] == 'run_rate' and not RUN_RATE_WORDS.search(sentence):
                problems.append(f'{label}: "{quote}" states {value} without saying it is a run rate ({fact.get("period")})')
            if fact.get('basis') == 'third_party' and not ATTRIBUTION_WORDS.search(sentence):
                problems.append(f'{label}: "{quote}" uses third-party figure {value} without naming its source')
            measured = f'{fact.get("metric", "")} {fact.get("statement", "")}'.lower()
            for actual, named in CONFUSABLE:
                if (_word(actual, measured) and not _word(named, measured) and
                        _word(named, lowered) and not _word(actual, lowered)):
                    problems.append(f'{label}: "{quote}" calls {value} {named}, but the cited fact measures '
                                    f'{actual} ("{fact["statement"][:80]}")')
    return list(dict.fromkeys(problems))


def restore_placeholders(text, results):
    """Put {cN} back where a calculation's result was typed out, so the calculation checks still apply.

    A revision sees the filled text and often copies the value ("0.30x") instead of the placeholder.
    """
    for calc_id, result in sorted(((c, r) for c, r in results.items() if isinstance(r, dict) and r.get('text')),
                                  key=lambda item: -len(item[1]['text'])):
        text = re.sub(r'(?<![\w.{])' + re.escape(result['text']) + r'(?![\w}]|\.\d)', '{' + calc_id + '}', text, count=0)
    return text


def _fiscal_label_problems(sentence, matched, index, label, quote, fiscal_year_end_month=3):
    """A fiscal-year name must match the period of the figure it labels: the nearest printed cited figure."""
    positions = []
    for fact in matched:
        value = str(fact.get('value', '')).strip()
        if value:
            positions += [(m.start(), m.end(), fact) for m in re.finditer(r'(?<![\d.])' + re.escape(value) + r'(?!\d)', sentence)]
    problems = []
    for match in FY_LABEL.finditer(sentence):
        if not positions or re.search(r'\b[QH][1-4][\s-]?$', sentence[:match.start()]):
            continue
        distance, fact = min(((min(abs(start - match.end()), abs(match.start() - end)), fact) for start, end, fact in positions),
                             key=lambda item: item[0])
        parsed, named = fact_period(fact, index, fiscal_year_end_month), ('year', _year(match.group(1)) * 12 + fiscal_year_end_month, 12)
        if distance > 40 or parsed is None or parsed == named or (parsed[0] in ('run_rate', 'month') and parsed[1] == named[1]):
            continue
        problems.append(f'{label}: "{quote}" names {match.group(0)} for {fact.get("value")} {fact.get("unit", "")}, which covers '
                        f'{describe_period(parsed)} ({fact.get("period")}); name the period the figure actually covers')
    return problems


PLACEHOLDER_WITH_UNIT = re.compile(r'(\b(?:USD|INR|EUR|GBP)\s)?\{(c\w{0,10})\}'
                                   r'((?:\s?%|x\b|\s(?:[A-Z]{3}/[A-Z]{3}|USD|INR|EUR|GBP|Mn|Bn|mn|bn|Million|Billion|million|billion)\b)*)')


def evidence_only(sentence):
    """True when a sentence is only calculation placeholders: code writes it in full."""
    return bool(PLACEHOLDER.search(sentence)) and not PLACEHOLDER.sub('', sentence).strip(' .;,:')


def fill_evidence(text, results):
    """Replace each placeholder-only sentence with the code-written evidence sentences of its calculations."""
    out = []
    for sentence in sentences(text):
        ids = PLACEHOLDER.findall(sentence)
        if evidence_only(sentence) and all(isinstance(results.get(i), dict) and results[i].get('sentence') for i in ids):
            out.append(' '.join(results[i]['sentence'] for i in ids))
        else:
            out.append(sentence.strip())
    return ' '.join(out)


def fill_placeholders(text, results):
    """Replace {c1} with the code-formatted result, which carries its own unit; units the model repeats around it are dropped."""
    def replace(match):
        result = results.get(match.group(2))
        if not isinstance(result, dict):
            return match.group(0)
        words = result['text'].lower().replace('%', ' % ').replace('x', ' x ').split()
        before = match.group(1) or ''
        before = '' if before.strip().lower() in words else before
        after = ''.join(token for token in re.findall(r'\s?%|x\b|\s[\w/]+', match.group(3) or '')
                        if token.strip().lower() not in words)
        return before + result['text'] + after
    # A writer's own "negative" before a value code already prints as negative must not double it.
    # And after "by", the verb already gives the direction: "widened by USD 0.76 Mn", never "by USD -0.76 Mn".
    filled = re.sub(r'\b(negative)\s+\1\b', r'\1', PLACEHOLDER_WITH_UNIT.sub(replace, text), flags=re.IGNORECASE)
    # The same goes for a word that names the direction: "a deterioration of USD 0.76 Mn".
    return re.sub(r'\b(by|(?:deteriorat\w+|widening|worsening|decline|fall|drop|swing) of) ([A-Z]{3}) -(?=\d)', r'\1 \2 ', filled)


def sentence_failures(sentence, cited, results, allowed, *, index=None, fiscal_year_end_month=3):
    """Reasons one sentence cannot stay in an investor document (empty when it may stay)."""
    reasons = []
    for calc_id in PLACEHOLDER.findall(sentence):
        if not isinstance(results.get(calc_id), dict):
            reasons.append(f'{{{calc_id}}} is not a valid calculation')
    for value in numbers_in(PLACEHOLDER.sub('', sentence)):
        if not number_present(value, allowed):
            reasons.append(f'{value:g} is not a cited value or a calculation')
    reasons += [problem.split(': ', 1)[1] for problem in sentence_problems(
        sentence, cited, results, label='s', index=index, fiscal_year_end_month=fiscal_year_end_month)]
    return reasons
