"""Bounded, resumable battle test of installed local model roles on synthetic fixtures.

Diagnostic evidence only: nothing here registers, renders or promotes an
investor artifact, and every company-like statement in the output is a raw
local-model response. Run from the repository root, for example:

    python3 -m evals.local_model_battle.runner challenge \\
        runtime_qualification/local_model_battle/challenge-9b --model qwen3.5:9b

Re-running the same command resumes: saved responses are replayed, not
requested again.
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from evals.local_model_battle.fixtures import FIXTURE_ROOT, load_fixture
from evals.local_model_battle.suites import AUTHORSHIP, ISOLATED_SUITES, STIMULUS_MODEL, SUITES
from scripts.evaluate_local_memo_harness import atomic_json, installed_models

WORKSPACE = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = WORKSPACE / 'runtime_qualification/local_model_battle'
MAX_CASES = 24
TERMINAL = ('answered', 'failed_generation', 'blocked')


def pin_models(names: dict[str, str], installed: dict) -> dict:
    pinned = {}
    for role, name in names.items():
        exact = name if ':' in name else name + ':latest'
        if not installed.get(exact):
            raise ValueError(f'{role} model {name!r} is not installed with a digest; '
                             'nothing was downloaded')
        pinned[role] = {'name': exact, 'digest': installed[exact]}
    return pinned


def scorecard(suite_name, profile, rows):
    metrics, pairs = {}, {}
    for row in rows:
        for key, value in row['counts'].items():
            metrics[key] = metrics.get(key, 0) + value
        passed = row['state'] == 'answered' and all(check['passed'] for check in row['checks'])
        for unit in row['pair_units']:
            pair = pairs.setdefault(unit['pair'], {'pair': unit['pair'], 'variants': {}})
            ok = passed if unit['checks'] is None else (row['state'] == 'answered' and all(
                check['passed'] for check in row['checks'] if check['property'] in unit['checks']))
            pair['variants'][unit['variant']] = pair['variants'].get(unit['variant'], True) and ok
    for pair in pairs.values():
        # A counterfactual pair passes only when the model is right on both sides.
        pair['passed'] = pair['variants'].get('defect') is True and pair['variants'].get('control') is True
    states = [row['state'] for row in rows]
    return {'kind': 'local_model_battle_scorecard', 'suite': suite_name,
            'profile_digest': digest(profile),
            'cases_total': profile['case_count'], 'cases_reached': len(rows),
            'cases_by_state': {state: states.count(state) for state in sorted(set(states))},
            'complete': len(rows) == profile['case_count'] and all(s in TERMINAL for s in states),
            'checks_passed': sum(c['passed'] for row in rows for c in row['checks']),
            'checks_total': sum(len(row['checks']) for row in rows),
            'pairs_passed': sum(pair['passed'] for pair in pairs.values()),
            'pairs': sorted(pairs.values(), key=lambda pair: pair['pair']),
            'metrics': metrics,
            'cases': [{key: row[key] for key in ('id', 'state', 'reason', 'response_ids',
                                                 'checks', 'counts', 'elapsed_seconds',
                                                 'passes_used')}
                      for row in rows],
            'authorship': AUTHORSHIP.get(suite_name, 'local_model_responses_only'),
            'artifact_status': 'diagnostic_only_no_promotion',
            # A passing pair is a software diagnostic of local-model behaviour on
            # synthetic cases. It accepts nothing, whatever the local reviewer said.
            'acceptance_scope': 'software_scored_properties_only_not_investment_quality',
            'independent_review': 'pending'}


def prior_responses(attempts, cases, used_ids):
    """Saved responses this run did not use, kept in the scorecard as evidence.

    A response to an earlier contract is never replayed, but it is not hidden
    either. A per-assertion check that called a planted defect supported is
    labelled as a counterexample, from the fixture's location labels alone.
    """
    by_memo = {digest(case.memo.model_dump()): case for case in cases if hasattr(case, 'memo')}
    kept = []
    for row in attempts:
        if row['id'] in used_ids:
            continue
        supplied, answer = row.get('input', {}), row.get('answer')
        entry = {'response_id': row['id'], 'task': row.get('task'),
                 'contract': supplied.get('contract') or supplied.get('challenge_contract'),
                 'model': row.get('model'), 'response_hash': row.get('response_hash'),
                 'elapsed_seconds': row.get('elapsed_seconds'), 'error': row.get('error'),
                 'input_sha256': digest(supplied), 'answer': answer}
        case = by_memo.get(supplied.get('memo_digest'))
        flag = case.expected.flag if case else None
        options = supplied.get('evidence_options')
        if (flag and isinstance(answer, dict) and options and supplied.get('field') == flag.field
                and flag.memo_span in supplied.get('assertion', '')
                and supplied.get('source_id') in flag.source_spans):
            span = flag.source_spans[supplied['source_id']]
            entry.update(case_id=case.id, assertion=supplied['assertion'],
                         evidence_options=options,
                         planted_option=[item['option'] for item in options if span in item['text']],
                         missed_planted_defect=answer.get('verdict') == 'supported')
        kept.append(entry)
    return kept


# The worker's frozen local options for each role, recorded in the profile.
def model_options(role: str) -> dict:
    return {'thinking': False, 'temperature': 0,
            'max_tokens': 1000 if role == 'prose' else 1400 if role == 'draft' else 1500,
            'context_tokens': 8192 if role == 'prose' else 16384}


def _pair_units(case):
    if hasattr(case, 'statements'):
        return [{'pair': item.pair, 'variant': item.variant,
                 'checks': {f'label_allowed[{item.id}]', f'excerpt_exact[{item.id}]'}}
                for item in case.statements]
    return [{'pair': case.pair, 'variant': case.variant, 'checks': None}]


def evaluate(suite_name: str, output: Path, names: dict[str, str], *, fixture: Path | None = None,
             seconds: float = 105, max_cases: int = MAX_CASES, models: dict | None = None,
             only: list[str] | None = None):
    """Run or resume one suite. `models` is for offline tests; otherwise roles are pinned."""
    if suite_name not in SUITES:
        raise ValueError('Unknown battle suite')
    fixture_suite, run, score, roles, calls, passes = SUITES[suite_name]
    if not 1 <= seconds <= 105 or not 1 <= max_cases <= MAX_CASES:
        raise ValueError(f'A battle run is limited to {MAX_CASES} cases of at most 105 seconds')
    if set(names) != set(roles):
        raise ValueError(f'Suite {suite_name} needs exactly these model roles: {roles}')
    output = Path(output).resolve()
    if not output.is_relative_to(OUTPUT_ROOT.resolve()) or output == OUTPUT_ROOT.resolve():
        raise ValueError('Diagnostic output must be inside ignored runtime_qualification/local_model_battle')
    fixture = fixture or FIXTURE_ROOT / (fixture_suite + '.synthetic.json')
    loaded_suite, cases = load_fixture(fixture)
    if loaded_suite != fixture_suite:
        raise ValueError('Fixture belongs to a different suite')
    if only:
        cases = [case for case in cases if case.id in only]
        if len(cases) != len(set(only)):
            raise ValueError('Unknown case id in --only')
    live_models = models is None
    pinned = (pin_models(names, installed_models()) if live_models else
              {role: {'name': names[role], 'digest': 'offline-test-double'} for role in roles})
    def verify_installed_model_digests():
        if not live_models:
            return
        current = installed_models()
        if any(current.get(entry['name']) != entry['digest'] for entry in pinned.values()):
            raise ValueError('Installed local model digest changed during the battle run')

    profile = {'kind': 'local_model_battle_profile', 'suite': suite_name,
               'fixture_sha256': digest(json.loads(Path(fixture).read_text())),
               'case_ids': [case.id for case in cases], 'case_count': len(cases),
               'models': pinned, 'seconds_per_pass': seconds, 'calls_per_pass': calls,
               'passes_per_case': passes,
               'adapter': 'agents.inference.local_models.LocalModel (loopback only)',
               'model_options': {role: model_options(role) for role in roles}}
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile_file, attempts_file = output / 'profile.json', output / 'attempts.json'
    if profile_file.exists():
        if json.loads(profile_file.read_text()) != profile:
            raise ValueError('Output directory holds a different fixture, case set or model profile')
    else:
        atomic_json(profile_file, profile)
    shared = json.loads(attempts_file.read_text()) if attempts_file.exists() else []
    # The stimulus rows replay a fixture memo as the draft; they are not model output.
    allowed_models = {entry['name'] for entry in pinned.values()} | {STIMULUS_MODEL}
    isolated = suite_name in ISOLATED_SUITES

    def store(case):
        """The response rows a case reads and writes, and how they are saved."""
        if not isolated:
            return shared, lambda: atomic_json(attempts_file, shared)
        (output / 'attempts').mkdir(exist_ok=True, mode=0o700)
        case_file = output / 'attempts' / (case.id + '.json')
        case_rows = json.loads(case_file.read_text()) if case_file.exists() else []
        return case_rows, lambda: atomic_json(case_file, case_rows)

    for case in cases:
        if any(row.get('model') not in allowed_models for row in store(case)[0]):
            raise ValueError('Saved response came from a model outside the frozen profile')

    if models is None:
        models = {role: LocalModel(pinned[role]['name'], **model_options(role))
                  for role in roles}
    # Passes that produced a new response, accumulated across invocations so a
    # replayed scorecard reports the same number.
    passes_file = output / 'passes.json'
    productive = json.loads(passes_file.read_text()) if passes_file.exists() else {}
    rows, new_calls = [], 0
    for case in cases:
        attempts, save = store(case)
        before = len(attempts)
        # Past the per-run cap only saved responses are replayed.
        active = models if new_calls < max_cases else {}
        response_ids = []
        for _ in range(passes):
            size = len(attempts)
            budget = PreparationBudget(seconds, max_calls=calls, max_requests=calls + 2)
            with preparation_budget(budget):
                outcome = (run(case, attempts, save, active, budget)
                           if 'budget' in inspect.signature(run).parameters
                           else run(case, attempts, save, active))
            response_ids += [item for item in outcome['response_ids'] if item not in response_ids]
            productive[case.id] = productive.get(case.id, 0) + int(len(attempts) > size)
            if outcome['state'] != 'needs_resume' or len(attempts) == size:
                break
        atomic_json(passes_file, productive)
        passes_used = productive[case.id]
        outcome['response_ids'] = response_ids
        new_calls += int(len(attempts) > before)
        checks, counts = score(case, outcome) if outcome['state'] != 'not_run' else ([], {})
        rows.append({'id': case.id, 'state': outcome['state'], 'reason': outcome.get('reason'),
                     'response_ids': outcome['response_ids'], 'checks': checks, 'counts': counts,
                     'pair_units': _pair_units(case), 'passes_used': passes_used,
                     # From the saved rows, so a replayed scorecard is identical.
                     'elapsed_seconds': round(sum(row.get('elapsed_seconds', 0) for row in attempts
                                                  if row['id'] in outcome['response_ids']), 3)})
        save()
        card = scorecard(suite_name, profile, [row for row in rows if row['state'] != 'not_run'])
        used = {item for row in rows for item in row['response_ids']}
        card['prior_responses'] = [] if isolated else prior_responses(attempts, cases, used)
        card['prior_counterexamples'] = sum(bool(item.get('missed_planted_defect'))
                                            for item in card['prior_responses'])
        # Never persist a passing card before verifying the installed model still
        # matches the profile. Attempts and pass counters remain as raw evidence.
        verify_installed_model_digests()
        atomic_json(output / 'scorecard.json', card)
    return card


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('suite', choices=sorted(SUITES))
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', required=True, help='Installed local model for the judged role')
    parser.add_argument('--prose-model', help='Field-correction role; defaults to --model')
    parser.add_argument('--review-model', help='Review role; defaults to --model')
    parser.add_argument('--seconds', type=float, default=105)
    parser.add_argument('--max-cases', type=int, default=MAX_CASES,
                        help='New model-calling cases in this invocation; rerun to continue')
    parser.add_argument('--only', nargs='+', help='Restrict the run to these case ids')
    args = parser.parse_args()
    roles = SUITES[args.suite][3]
    names = {role: (args.prose_model if role == 'prose' else args.review_model if role == 'review'
                    else None) or args.model for role in roles}
    card = evaluate(args.suite, args.output, names, seconds=args.seconds,
                    max_cases=args.max_cases, only=args.only)
    print(json.dumps({key: card[key] for key in ('suite', 'cases_total', 'cases_reached',
          'cases_by_state', 'complete', 'checks_passed', 'checks_total', 'pairs_passed',
          'metrics')}, indent=1))


if __name__ == '__main__':
    main()
