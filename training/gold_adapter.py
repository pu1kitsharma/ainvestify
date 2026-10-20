"""Adapter from a gold directory (GOLD_SCHEMA.md) to training.envs.scoring keys.

Produces (a) answer keys, (b) an oracle prediction derived from the same gold,
(c) programmatically degraded predictions, and (d) a gap report of gold content
the existing scorer schema cannot express. No inference, no network. Gold content
may be confidential: callers must write outputs derived from it only to ignored
private paths. Gap reports built here contain counts and category names only.
"""
import copy
import json
import math
from pathlib import Path

FLAG_ACTIONS = ('flag', 'correct', 'ask_user')   # findings the agent must raise
ENVIRONMENTS = ('E1', 'E2', 'E4', 'E5', 'E6')
UNSUPPORTED_ALWAYS = {
    'E1': (), 'E2': ('live_formulas', 'no_calculation_hardcodes'),
    'E4': (), 'E5': ('funding_buffer', 'recalc_clean'), 'E6': ('comparison_direction',),
}
CASH_TOLERANCE = 0.5  # absolute, in the gold summary's stated scale
DEGRADATIONS = ('miss_findings', 'flag_traps', 'wrong_units', 'wrong_period',
                'extra_unsupported', 'wrong_cash_scale')


def _load(path):
    return json.loads(Path(path).read_text())


def load_gold(directory):
    d = Path(directory)
    summary = None
    for candidate in (d / 'corrected_summary.json', d / 'corrected_model' / 'corrected_summary.json'):
        if candidate.exists():
            summary = _load(candidate)
            break
    return {'findings': _load(d / 'expected_findings.json'), 'facts': _load(d / 'facts.json'),
            'sections': _load(d / 'sections.json'), 'summary': summary}


def _num(v):
    return type(v) in (int, float) and math.isfinite(v)


def _canon(v):
    return format(float(v), '.10g')


def fact_token(fact, **override):
    f = {**fact, **override}
    return '|'.join([f['id'], _canon(f['value']), str(f.get('unit')), str(f.get('scale')),
                     str(f.get('currency')), str(f.get('period'))])


def citation_token(fact):
    return '|'.join([fact['id'], str(fact.get('source')), str(fact.get('locator'))])


def _is_total(fact):
    return 'total' in str(fact.get('label', '')).lower()


def e1_facts(gold):
    return [f for f in gold['facts']['facts'] if f.get('provenance') == 'actual' and _num(f.get('value'))]


def e2_facts(gold):
    return [f for f in e1_facts(gold) if _is_total(f)]


def flag_ids(gold):
    return [x['id'] for x in gold['findings']['findings'] if x.get('expected_agent_action') in FLAG_ACTIONS]


def forbidden_ids(gold):
    return [t['id'] for t in gold['findings']['traps'] if t.get('expected_agent_action') == 'do_not_flag']


def section_bindings(gold):
    fact_ids = {f['id'] for f in gold['facts']['facts']}
    return [f"{s['id']}|{sf}" for s in gold['sections']['sections'] for sf in s.get('source_facts', [])
            if sf in fact_ids]


def section_tokens(gold):
    return [f"{s['order']}|{s['id']}" for s in gold['sections']['sections'] if s.get('required', True)]


def cash_need(gold):
    """Peak cash need as a single number, only where the summary states it explicitly."""
    cn = (gold['summary'] or {}).get('cash_need')
    if isinstance(cn, dict):
        for k, v in cn.items():
            if k.startswith('peak') and 'cash_need' in k and _num(v):
                return float(v)
    return None


def _set_key(values):
    return {'status': 'available', 'kind': 'set', 'expected': list(dict.fromkeys(values))}


def _unsupported():
    return {'status': 'unsupported'}


def build_answer_keys(gold, label):
    """Return answer-key array for E1, E2, E4, E5, E6 cases of one deal."""
    f1, f2 = e1_facts(gold), e2_facts(gold)
    cash = cash_need(gold)
    keys = {
        'E1': {'historical_cells': _set_key(map(fact_token, f1)) if f1 else _unsupported(),
               'citations': _set_key(map(citation_token, f1)) if f1 else _unsupported()},
        'E2': {'reported_totals': _set_key(map(fact_token, f2)) if f2 else _unsupported(),
               'live_formulas': _unsupported(), 'no_calculation_hardcodes': _unsupported()},
        'E4': {'flags': _set_key(flag_ids(gold))},
        'E5': {'cash_need': ({'status': 'available', 'kind': 'numeric', 'expected': cash,
                              'absolute_tolerance': CASH_TOLERANCE} if cash is not None else _unsupported()),
               'maximum_draw': _unsupported(), 'funding_buffer': _unsupported(), 'recalc_clean': _unsupported()},
        'E6': {'text_cell_agreement': _set_key(section_bindings(gold)) if section_bindings(gold) else _unsupported(),
               'comparison_direction': _unsupported(),
               'sections': _set_key(section_tokens(gold)) if section_tokens(gold) else _unsupported()},
    }
    return [{'case_id': f'{label}-{env}', 'environment': env, 'checks': checks} for env, checks in keys.items()]


def _observe(key, value):
    if key.get('status') == 'unsupported':
        return {'status': 'unsupported'}
    return {'status': 'observed', 'value': value}


def build_oracle(gold, label, keys=None):
    """Perfect prediction: copies exactly what the key expects, nothing more."""
    keys = keys or build_answer_keys(gold, label)
    preds = []
    for k in keys:
        obs = {name: _observe(c, copy.deepcopy(c.get('expected'))) for name, c in k['checks'].items()}
        preds.append({'case_id': k['case_id'], 'environment': k['environment'], 'observations': obs})
    return preds


def _obs(preds, env):
    return next(p for p in preds if p['environment'] == env)['observations']


def degrade(gold, label, kind):
    """Oracle with one targeted defect. Unaffected checks stay perfect."""
    if kind not in DEGRADATIONS:
        raise ValueError(f'unknown degradation {kind}')
    keys = build_answer_keys(gold, label)
    preds = build_oracle(gold, label, keys)
    e1, e2, e4, e5, e6 = (_obs(preds, e) for e in ENVIRONMENTS)
    f1, f2 = e1_facts(gold), e2_facts(gold)
    scale_swap = {'units': 'thousand', 'thousand': 'mn', 'mn': 'units', 'lakh': 'mn', 'crore': 'mn', 'bn': 'mn'}
    if kind == 'miss_findings':
        wanted = flag_ids(gold)
        e4['flags']['value'] = wanted[: len(wanted) // 2]
    elif kind == 'flag_traps':
        e4['flags']['value'] = flag_ids(gold) + forbidden_ids(gold)
    elif kind == 'wrong_units':
        for env, facts, name in (('E1', f1, 'historical_cells'), ('E2', f2, 'reported_totals')):
            obs = _obs(preds, env)[name]
            if obs['status'] == 'observed':
                obs['value'] = [fact_token(f, scale=scale_swap.get(f.get('scale'), 'units')) for f in facts]
    elif kind == 'wrong_period':
        obs = e1['historical_cells']
        if obs['status'] == 'observed':
            obs['value'] = [fact_token(f, period=str(f.get('period')) + '-shifted') for f in f1]
    elif kind == 'extra_unsupported':
        e4['flags']['value'] = e4['flags']['value'] + ['X-UNSUPPORTED-1', 'X-UNSUPPORTED-2']
        if e1['historical_cells']['status'] == 'observed':
            e1['historical_cells']['value'] = e1['historical_cells']['value'] + ['invented|1|usd|units|USD|FY00']
        if e6['text_cell_agreement']['status'] == 'observed':
            e6['text_cell_agreement']['value'] = e6['text_cell_agreement']['value'] + ['no_section|no_fact']
    elif kind == 'wrong_cash_scale':
        if e5['cash_need']['status'] == 'observed':
            e5['cash_need']['value'] = e5['cash_need']['value'] * 1000
    return preds


def expected_effects(gold, kind):
    """Per-degradation penalty that must fire: list of (env, check, metric, predicate-name).
    metric is 'reward', 'precision' or 'recall'; 'lt' means strictly below 1.0 and
    'eq' means exactly 1.0 (the penalty must be specific, not collateral)."""
    flags, forb = flag_ids(gold), forbidden_ids(gold)
    f1, f2 = e1_facts(gold), e2_facts(gold)
    out = []
    if kind == 'miss_findings' and len(flags) >= 2:
        out += [('E4', 'flags', 'recall', 'lt'), ('E4', 'flags', 'precision', 'eq')]
    elif kind == 'flag_traps' and forb:
        out += [('E4', 'flags', 'precision', 'lt'), ('E4', 'flags', 'recall', 'eq')]
    elif kind == 'wrong_units':
        if f1:
            out.append(('E1', 'historical_cells', 'reward', 'lt'))
        if f2:
            out.append(('E2', 'reported_totals', 'reward', 'lt'))
    elif kind == 'wrong_period' and f1:
        out.append(('E1', 'historical_cells', 'reward', 'lt'))
    elif kind == 'extra_unsupported':
        out += [('E4', 'flags', 'precision', 'lt'), ('E4', 'flags', 'recall', 'eq')]
    elif kind == 'wrong_cash_scale' and cash_need(gold) is not None:
        out.append(('E5', 'cash_need', 'reward', 'lt'))
    return out


def gap_report(gold):
    """Counts and categories of gold content the scorer schema cannot express."""
    fs, ts = gold['findings']['findings'], gold['findings']['traps']
    facts = gold['facts']['facts']
    summary = gold['summary'] or {}
    fact_ids = {f['id'] for f in facts}
    sf_all = [x for s in gold['sections']['sections'] for x in s.get('source_facts', [])]
    gaps = {
        'findings_total': len(fs), 'traps_total': len(ts),
        'findings_scored_in_e4': sum(f.get('expected_agent_action') in FLAG_ACTIONS for f in fs),
        'findings_not_flag_class_unscored': sum(f.get('expected_agent_action') not in FLAG_ACTIONS for f in fs),
        'findings_with_recomputed_values_only_id_scored': sum(bool(f.get('recomputed_values')) for f in fs),
        'findings_direction_of_error_not_expressible': len(fs),
        'findings_unverified_or_read_only': sum(f.get('verification') != 'recomputed' for f in fs),
        'traps_scored_as_do_not_flag': sum(t.get('expected_agent_action') == 'do_not_flag' for t in ts),
        'traps_low_severity_allowance_not_expressible': sum(t.get('expected_agent_action') == 'flag_low_at_most' for t in ts),
        'traps_other_action_unscored': sum(t.get('expected_agent_action') not in ('do_not_flag', 'flag_low_at_most') for t in ts),
        'facts_total': len(facts),
        'facts_scored_e1_actual_numeric': len(e1_facts(gold)),
        'facts_company_projection_no_env_key_E3': sum(f.get('provenance') == 'company_projection' for f in facts),
        'facts_derived_unscored': sum(f.get('provenance') == 'derived' for f in facts),
        'facts_non_numeric_unscored': sum(not _num(f.get('value')) for f in facts),
        'facts_scored_e2_totals_heuristic': len(e2_facts(gold)),
        'section_fact_refs_total': len(sf_all),
        'section_fact_refs_unresolved_to_fact_ids': sum(x not in fact_ids for x in sf_all),
        'sections_required_content_text_not_scored': len(gold['sections']['sections']),
        'cash_need_key_available': cash_need(gold) is not None,
        'summary_present': bool(summary),
        'summary_top_level_groups_unconsumed': sum(k not in ('deal', 'currency', 'scale', 'periods', 'assumptions')
                                                   for k in summary) - (1 if cash_need(gold) is not None else 0),
        'environments_without_any_gold_key': ['E3', 'E7'],
        'dimensions_unsupported_by_design': ['E2.live_formulas', 'E2.no_calculation_hardcodes', 'E5.maximum_draw',
                                             'E5.funding_buffer', 'E5.recalc_clean', 'E6.comparison_direction'],
    }
    return gaps
