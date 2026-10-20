"""Verifiable E1-E7 modelling tasks with automatic answer keys from XBRL companyfacts.

Every task row carries only `input`; the key (training.envs.scoring format) is returned
separately so samplers never see it. Keys are arithmetic/reported facts, so they are
verifiable but are NOT independently adjudicated gold: they inherit any filer error and
the canonical tag mapping in taxonomy.py.

Schema notes (scoring.py is unchanged):
- E1 `historical_cells`/`citations` and E7 `source_figures` have no per-cell kind, so they are
  `set` checks over canonical strings; F1 is all-or-nothing per extra/missing cell.
- E3 `scenarios` and E6 `sections` have no automatic key -> declared `unsupported` (zero reward).
- E3 tolerance is a fixed fraction of the actual; not a calibrated forecasting loss.
- `live_formulas`/`no_calculation_hardcodes` (E2) are declarations, not workbook inspection.
"""
import hashlib
import json
import random
from collections import Counter
from datetime import date

from . import taxonomy

ANNUAL_FORMS = {'10-K', '10-K/A', '20-F', '40-F'}
E3_TOLERANCE = 0.10
INJECTIONS = ('unit_scale_slip', 'fy_cy_mix', 'wrong_comparator', 'projection_vs_actual', 'sum_ne_total', 'cross_statement_mismatch')


def sha256_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def _rng(*parts):
    return random.Random(int(hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:16], 16))


def annual_series(companyfacts):
    """canonical -> {period_end: {value, tag, accn, filed, form, unit}} (latest filing wins)."""
    out = {}
    facts = companyfacts.get('facts', {}).get('us-gaap', {})
    for name, spec in taxonomy.CANONICAL.items():
        for tag in spec['us_gaap']:
            node = facts.get(tag)
            if not node:
                continue
            series = {}
            for unit, entries in node.get('units', {}).items():
                if unit != 'USD':
                    continue
                for e in entries:
                    if e.get('form') not in ANNUAL_FORMS or e.get('fp') != 'FY':
                        continue
                    if spec['kind'] == 'flow':
                        if 'start' not in e:
                            continue
                        days = (date.fromisoformat(e['end']) - date.fromisoformat(e['start'])).days
                        if not 350 <= days <= 380:
                            continue
                    old = series.get(e['end'])
                    if old is None or e['filed'] >= old['filed']:
                        series[e['end']] = {'value': e['val'], 'tag': tag, 'accn': e['accn'], 'filed': e['filed'], 'form': e['form'], 'unit': unit}
            if series:
                out[name] = series
                break
    return out


def fye_month(series):
    ends = [e for e in series.get('revenue', series.get('net_income', {}))]
    if not ends:
        raise ValueError('No annual revenue or net income series')
    return Counter(int(e[5:7]) for e in ends).most_common(1)[0][0]


def _years(series, items):
    common = None
    for item in items:
        if item not in series:
            return []
        ends = set(series[item])
        common = ends if common is None else common & ends
    return sorted(common)


def _cell(item, end, series):
    return '%s|%s|%d' % (item, end, series[item][end]['value'])


def _base(env, company, descriptor, accns, source_sha, extra=None):
    row = {'case_id': '%s-%s-%s' % (env, company['company_key'], descriptor), 'environment': env,
           'company_key': company['company_key'], 'sector': company['sector'], 'origin': company['origin'],
           'rights_status': company['rights_status'], 'private': False,
           'evidence_family_ids': sorted('%s:%s' % (company['company_key'], a) for a in set(accns)),
           'source_sha256': [source_sha], 'synthetic_figures': company['origin'] != 'sec_edgar'}
    row.update(extra or {})
    return row


def _key(case_id, env, **checks):
    return {'case_id': case_id, 'environment': env, 'checks': checks}


def _avail(kind, expected, **kw):
    return dict(status='available', kind=kind, expected=expected, **kw)


UNSUPPORTED = {'status': 'unsupported'}
E1_ITEMS = ('revenue', 'cogs', 'gross_profit', 'opex', 'operating_income', 'net_income', 'cash', 'ocf')


def build_e1(company, series, sha):
    out, ye = [], _years(series, E1_ITEMS)
    fm = fye_month(series)
    for end in ye:
        scale = _rng('E1', company['company_key'], end).choice([1, 1000, 1000000])
        rows = [{'row_id': 'r%d' % i, 'tag': series[it][end]['tag'], 'label': it, 'period_end': end, 'accn': series[it][end]['accn'],
                 'scale': scale, 'displayed_value': series[it][end]['value'] / scale, 'unit_label': {1: 'USD', 1000: 'USD thousands', 1000000: 'USD millions'}[scale]}
                for i, it in enumerate(E1_ITEMS)]
        t = _base('E1', company, end, [series[i][end]['accn'] for i in E1_ITEMS], sha,
                  {'input': {'instruction': 'Rebuild canonical raw-unit line items for the fiscal year ending on period_end; output item|period_end|raw_integer_value and tag|accn citations.',
                             'fiscal_year_end_month': fm, 'fiscal_year_label': taxonomy.fiscal_year_label(end), 'rows': rows}})
        k = _key(t['case_id'], 'E1', historical_cells=_avail('set', [_cell(i, end, series) for i in E1_ITEMS]),
                 citations=_avail('set', sorted('%s|%s' % (series[i][end]['tag'], series[i][end]['accn']) for i in E1_ITEMS)))
        out.append((t, k))
    return out


def build_e2(company, series, sha):
    out = []
    for end in _years(series, ('revenue', 'revenue_goods', 'revenue_services')):
        if series['revenue_goods'][end]['value'] + series['revenue_services'][end]['value'] != series['revenue'][end]['value']:
            continue
        t = _base('E2', company, end, [series[i][end]['accn'] for i in ('revenue', 'revenue_goods', 'revenue_services')], sha,
                  {'input': {'instruction': 'Build a driver table whose components tie to reported total revenue using live formulas.',
                             'period_end': end, 'components': {'revenue_goods': series['revenue_goods'][end]['value'],
                                                               'revenue_services': series['revenue_services'][end]['value']}}})
        out.append((t, _key(t['case_id'], 'E2', reported_totals=_avail('numeric', series['revenue'][end]['value'], absolute_tolerance=0),
                            live_formulas=_avail('exact', True), no_calculation_hardcodes=_avail('exact', True))))
    return out


def build_e3(company, series, sha):
    out, ends = [], _years(series, ('revenue', 'net_income'))
    for i in range(2, len(ends) - 1):
        hist, target = ends[:i + 1], ends[i + 1]
        actual = series['revenue'][target]['value']
        history = [{'period_end': e, 'revenue': series['revenue'][e]['value'], 'net_income': series['net_income'][e]['value'],
                    'citation': '%s|%s' % (series['revenue'][e]['tag'], series['revenue'][e]['accn'])} for e in hist]
        t = _base('E3', company, target, [series['revenue'][e]['accn'] for e in hist], sha,
                  {'input': {'instruction': 'Forecast next fiscal year revenue from history only; cite history rows used.',
                             'history': history, 'forecast_period_end': target, 'tolerance_fraction': E3_TOLERANCE}})
        # Future filing evidence is deliberately absent from evidence_family_ids of the input; key target accn is kept in the key row only.
        k = _key(t['case_id'], 'E3', future_actuals=_avail('numeric', actual, absolute_tolerance=round(E3_TOLERANCE * abs(actual), 2)),
                 assumption_citations=_avail('set', sorted(h['citation'] for h in history)), scenarios=UNSUPPORTED)
        k['target_accn'] = series['revenue'][target]['accn']
        t['evidence_family_ids'] = sorted(set(t['evidence_family_ids']) | {'%s:%s' % (company['company_key'], series['revenue'][target]['accn'])})
        out.append((t, k))
    return out


PKG_ITEMS = ('revenue', 'cogs', 'gross_profit', 'net_income', 'ocf', 'icf', 'fcf_financing', 'cash')


def _package(company, series, end, prior):
    def line(item, statement, e, label=None):
        return {'item': label or item, 'statement': statement, 'period_end': e, 'value': series[item][e]['value'], 'unit': 'USD', 'basis': 'actual'}
    lines = []
    for e in (prior, end):
        lines += [line('revenue', 'income', e), line('cogs', 'income', e), line('gross_profit', 'income', e), line('net_income', 'income', e),
                  line('net_income', 'cashflow', e), line('ocf', 'cashflow', e), line('icf', 'cashflow', e), line('fcf_financing', 'cashflow', e),
                  line('cash', 'balance', e)]
    growth = round((series['revenue'][end]['value'] / series['revenue'][prior]['value'] - 1) * 100, 2)
    return {'company': company['company_key'], 'header_unit': 'USD', 'periods': [{'period_end': prior, 'basis': 'actual'}, {'period_end': end, 'basis': 'actual'}],
            'lines': lines, 'stated': {'revenue_growth_yoy_pct': growth, 'comparator_period_end': prior}}


def _find(pkg, item, statement, end):
    return next(l for l in pkg['lines'] if l['item'] == item and l['statement'] == statement and l['period_end'] == end)


def inject(pkg, flag, series, end, ends, fm):
    """Returns True when applicable. Mutates pkg."""
    if flag == 'unit_scale_slip':
        _find(pkg, 'cogs', 'income', end)['unit'] = 'USD thousands'
    elif flag == 'fy_cy_mix':
        if fm == 12:
            return False
        _find(pkg, 'revenue', 'income', end)['period_end'] = '%s-12-31' % end[:4]
    elif flag == 'wrong_comparator':
        i = ends.index(end)
        if i < 2:
            return False
        old = ends[i - 2]
        pkg['stated']['comparator_period_end'] = old
        pkg['stated']['revenue_growth_yoy_pct'] = round((series['revenue'][end]['value'] / series['revenue'][old]['value'] - 1) * 100, 2)
    elif flag == 'projection_vs_actual':
        l = _find(pkg, 'cash', 'balance', end)
        l['basis'] = 'projected'
        l['value'] = int(round(l['value'] * 1.1 / 1000)) * 1000
    elif flag == 'sum_ne_total':
        g = _find(pkg, 'gross_profit', 'income', end)
        g['value'] += int(round(_find(pkg, 'revenue', 'income', end)['value'] * 0.07 / 1000)) * 1000
    elif flag == 'cross_statement_mismatch':
        l = _find(pkg, 'net_income', 'cashflow', end)
        l['value'] = int(round(l['value'] * 1.15 / 1000)) * 1000 or 1000
    return True


def build_e4(company, series, sha):
    out, ends = [], _years(series, PKG_ITEMS)
    fm = fye_month(series)
    for i, end in enumerate(ends[1:], 1):
        prior = ends[i - 1]
        accns = [series[it][e]['accn'] for it in PKG_ITEMS for e in (prior, end)]
        for flag in ('none',) + INJECTIONS:
            pkg = _package(company, series, end, prior)
            if flag != 'none' and not inject(pkg, flag, series, end, ends, fm):
                continue
            t = _base('E4', company, '%s-%s' % (end, flag), accns, sha,
                      {'input': {'instruction': 'Reconcile this statement package and return the set of inconsistency flag ids found (empty if none).',
                                 'flag_vocabulary': list(INJECTIONS), 'fiscal_year_end_month': fm, 'package': pkg}})
            out.append((t, _key(t['case_id'], 'E4', flags=_avail('set', [] if flag == 'none' else [flag]))))
    return out


def build_e5(company, series, sha):
    out = []
    for end in _years(series, ('cash', 'ocf', 'capex')):
        fcf = series['ocf'][end]['value'] - abs(series['capex'][end]['value'])
        rng = _rng('E5', company['company_key'], end)
        # Stress: operating cash flow shortfall of `stress` fraction of revenue-independent baseline FCF magnitude, so the scenario is
        # always a burn even for cash-generative companies. Monthly burn = max(-fcf, |fcf|*stress)/12.
        stress = rng.choice([0.5, 0.75, 1.0])
        burn_year = -fcf if fcf < 0 else abs(fcf) * stress
        monthly = round(burn_year / 12.0, 2)
        horizon, buffer_pct = rng.choice([12, 18, 24]), rng.choice([0.1, 0.2, 0.25])
        cash = series['cash'][end]['value']
        need = round(max(0.0, monthly * horizon - cash), 2)
        buffer = round(need * buffer_pct, 2)
        t = _base('E5', company, end, [series[i][end]['accn'] for i in ('cash', 'ocf', 'capex')], sha,
                  {'input': {'instruction': 'Compute funding need over the horizon, funding buffer on that need, and maximum draw (need plus buffer) with a clean recalculation.',
                             'opening_cash': cash, 'monthly_burn': monthly, 'horizon_months': horizon, 'buffer_pct_of_need': buffer_pct,
                             'burn_basis': 'scenario' if fcf >= 0 else 'reported_free_cash_flow'}})
        out.append((t, _key(t['case_id'], 'E5', cash_need=_avail('numeric', need, absolute_tolerance=1.0), maximum_draw=_avail('numeric', round(need + buffer, 2), absolute_tolerance=1.0),
                            funding_buffer=_avail('numeric', buffer, absolute_tolerance=1.0), recalc_clean=_avail('exact', True))))
    return out


def _money(v):
    return '$%.1f million' % (v / 1e6)


def build_e6(company, series, sha):
    out, ends = [], _years(series, ('revenue', 'net_income', 'cash', 'gross_profit'))
    for i, end in enumerate(ends[1:], 1):
        prior = ends[i - 1]
        rng = _rng('E6', company['company_key'], end)
        rev, rev0 = series['revenue'][end]['value'], series['revenue'][prior]['value']
        ni, ni0 = series['net_income'][end]['value'], series['net_income'][prior]['value']
        specs = [  # id, kind, true text pieces
            ('s1', 'dir', 'Revenue', rev, rev0), ('s2', 'dir', 'Net income', ni, ni0),
            ('s3', 'level', 'Cash and cash equivalents', series['cash'][end]['value'], None),
            ('s4', 'margin', 'Gross margin', series['gross_profit'][end]['value'] / rev, None)]
        stmts, agree, direction = [], [], []
        for sid, kind, name, v, v0 in specs:
            corruption = rng.choice(['none', 'none', 'wrong_number', 'direction_flip', 'wrong_period'])
            if kind != 'dir' and corruption in ('direction_flip', 'wrong_period'):
                corruption = 'wrong_number'
            true_up = kind == 'dir' and v >= v0
            shown_v = v * 1.1 if corruption == 'wrong_number' else v
            if kind == 'dir':
                word_up = (not true_up) if corruption == 'direction_flip' else true_up
                base = v0 if corruption != 'wrong_period' else (series['revenue' if name == 'Revenue' else 'net_income'][ends[i - 2]]['value'] if i >= 2 else v0 * 0.5)
                text = '%s %s to %s in the fiscal year ended %s, from %s the prior year.' % (name, 'increased' if word_up else 'decreased', _money(shown_v), end, _money(base))
                if corruption == 'direction_flip':
                    direction_ok = False
                else:
                    direction_ok = True
                if corruption == 'wrong_period':
                    corrupt_agree = False
                else:
                    corrupt_agree = corruption == 'none'
                direction.append(sid) if direction_ok else None
                if corrupt_agree:
                    agree.append(sid)
            elif kind == 'level':
                text = '%s were %s at %s.' % (name, _money(shown_v), end)
                if corruption == 'none':
                    agree.append(sid)
            else:
                text = '%s was %.1f%% for the fiscal year ended %s.' % (name, shown_v * 100, end)
                if corruption == 'none':
                    agree.append(sid)
            stmts.append({'statement_id': sid, 'text': text})
        cells = {'period_end': end, 'prior_period_end': prior, 'revenue': rev, 'revenue_prior': rev0, 'net_income': ni, 'net_income_prior': ni0,
                 'cash': series['cash'][end]['value'], 'gross_profit': series['gross_profit'][end]['value']}
        t = _base('E6', company, end, [series[x][e]['accn'] for x in ('revenue', 'net_income', 'cash', 'gross_profit') for e in (prior, end)], sha,
                  {'input': {'instruction': 'Check each MD&A-style statement against the cells: return ids that agree and ids whose comparison direction is right.',
                             'cells': cells, 'statements': stmts}})
        out.append((t, _key(t['case_id'], 'E6', text_cell_agreement=_avail('set', sorted(agree)), comparison_direction=_avail('set', sorted(direction)), sections=UNSUPPORTED)))
    return out


def build_e7(company, series, sha):
    """Synthetic market-size passages; arithmetic drill only, no real market claim."""
    out = []
    for end in _years(series, ('revenue',))[1:]:
        rng = _rng('E7', company['company_key'], end)
        start_v, years = rng.randrange(2, 90) * 1.0, rng.choice([3, 4, 5, 6])
        cagr_true = rng.choice([0.05, 0.08, 0.1, 0.12, 0.15, 0.2])
        end_v = round(start_v * (1 + cagr_true) ** years, 1)
        y0 = int(end[:4])
        passages = [{'passage_id': 'p1', 'text': 'Illustrative market size of $%.1f billion in %d.' % (start_v, y0)},
                    {'passage_id': 'p2', 'text': 'Projected to reach $%.1f billion by %d.' % (end_v, y0 + years)}]
        t = _base('E7', company, end, [series['revenue'][end]['accn']], sha,
                  {'input': {'instruction': 'Extract start and end figures with years and compute CAGR.', 'passages': passages}})
        t['synthetic_figures'] = True
        figs = ['start=%.1f' % start_v, 'end=%.1f' % end_v, 'years=%d' % years]
        out.append((t, _key(t['case_id'], 'E7', source_figures=_avail('set', figs), source_citations=_avail('set', ['p1', 'p2']),
                            cagr=_avail('numeric', round((end_v / start_v) ** (1.0 / years) - 1, 6), absolute_tolerance=1e-4))))
    return out


BUILDERS = (build_e1, build_e2, build_e3, build_e4, build_e5, build_e6, build_e7)


def build_company_tasks(companyfacts, company):
    """company: {company_key, sector, origin, rights_status}. Returns [(task_row, answer_key)]."""
    series = annual_series(companyfacts)
    sha = sha256_json(companyfacts)
    result = []
    for build in BUILDERS:
        result += build(company, series, sha)
    return result
