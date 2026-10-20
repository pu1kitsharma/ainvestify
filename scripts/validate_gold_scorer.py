#!/usr/bin/env python3
"""Prove a gold set and the offline scorer work together (G-READY criterion 3).

For each gold directory: oracle must score the exact supported maximum; every
degraded variant must score strictly lower with its specific penalty firing;
unsupported dimensions must be reported as unsupported with zero reward.
Stdout is committable (counts and pass/fail only; deals labelled deal_a, deal_b,
...). The full report, which names gold ids, goes to a new private ignored file.
No inference, no network.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training import gold_adapter as ga
from training.envs import evaluate

DEFAULT_GOLD = ROOT / 'evals/agentic_banker/gold'
PRIVATE_OUT = DEFAULT_GOLD / '_scorer_validation'


def _checks(report):
    return {(c['environment'], n): r for c in report['cases'] for n, r in c['checks'].items()}


def validate(gold_dir, label):
    gold = ga.load_gold(gold_dir)
    keys = ga.build_answer_keys(gold, label)
    results = []

    def check(name, ok, detail=''):
        results.append({'check': name, 'passed': bool(ok), 'detail': detail})

    oracle_rep = evaluate(ga.build_oracle(gold, label, keys), keys)
    oc = _checks(oracle_rep)
    supported = [k for k in oc if next(x for x in keys if x['environment'] == k[0])['checks'][k[1]]['status'] == 'available']
    unsupported = [k for k in oc if k not in supported]
    check('oracle_every_supported_dimension_is_max',
          all(oc[k]['reward'] == 1.0 and oc[k]['status'] == 'matched' for k in supported),
          f'{len(supported)} supported dimensions')
    check('unsupported_reported_not_hidden',
          all(oc[k]['status'] == 'unsupported' and oc[k]['reward'] == 0.0 for k in unsupported),
          f'{len(unsupported)} unsupported dimensions')
    check('oracle_mean_equals_supported_fraction',
          abs(oracle_rep['mean_reward'] - _expected_mean(keys)) < 1e-9)
    degraded = {}
    for kind in ga.DEGRADATIONS:
        effects = ga.expected_effects(gold, kind)
        if not effects:
            check(f'degraded_{kind}', True, 'not_applicable')
            degraded[kind] = 'not_applicable'
            continue
        rep = evaluate(ga.degrade(gold, label, kind), keys)
        dc = _checks(rep)
        lower = rep['mean_reward'] < oracle_rep['mean_reward']
        fired = True
        for env, name, metric, pred in effects:
            val = dc[(env, name)].get(metric)
            fired &= (val is not None and (val < 1.0 if pred == 'lt' else val == 1.0))
        check(f'degraded_{kind}_strictly_lower', lower)
        check(f'degraded_{kind}_penalty_fires', fired)
        degraded[kind] = {'mean': rep['mean_reward'], 'oracle_mean': oracle_rep['mean_reward']}
    return {'label': label, 'checks': results, 'counts': _counts(gold, keys, supported, unsupported),
            'gaps': ga.gap_report(gold), 'oracle_mean': oracle_rep['mean_reward'], 'degraded': degraded}


def _expected_mean(keys):
    per_case = [sum(c['status'] == 'available' for c in k['checks'].values()) / len(k['checks']) for k in keys]
    return sum(per_case) / len(per_case)


def _counts(gold, keys, supported, unsupported):
    return {'findings': len(gold['findings']['findings']), 'traps': len(gold['findings']['traps']),
            'flag_expected_findings': len(ga.flag_ids(gold)), 'strict_traps': len(ga.forbidden_ids(gold)),
            'supported_dimensions': len(supported), 'unsupported_dimensions': len(unsupported),
            'cases': len(keys)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gold-root', type=Path, default=DEFAULT_GOLD)
    parser.add_argument('--out', type=Path, default=None, help='New private report path (must not exist)')
    args = parser.parse_args(argv)
    dirs = sorted(p for p in args.gold_root.iterdir()
                  if p.is_dir() and not p.name.startswith('_') and (p / 'expected_findings.json').exists()) \
        if args.gold_root.exists() else []
    labels = [f'deal_{chr(97 + i)}' for i in range(len(dirs))]
    full = [dict(validate(d, lab), directory=d.name) for d, lab in zip(dirs, labels)]
    if full:
        out = args.out or PRIVATE_OUT / 'report.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(full, handle, indent=2)
    summary = [{'deal': r['label'], **r['counts'],
                'checks_passed': sum(c['passed'] for c in r['checks']), 'checks_failed': sum(not c['passed'] for c in r['checks']),
                'failed': [c['check'] for c in r['checks'] if not c['passed']],
                'gap_counts': {k: v for k, v in r['gaps'].items() if isinstance(v, int) and not isinstance(v, bool)}}
               for r in full]
    print(json.dumps({'gold_sets_found': len(full), 'summary': summary}, indent=2))
    return 0 if full and all(s['checks_failed'] == 0 for s in summary) else 1


if __name__ == '__main__':
    sys.exit(main())
