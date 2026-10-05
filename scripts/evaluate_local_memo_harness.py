"""Bounded, public/synthetic-only evaluation of the real staged memo path.

This script writes diagnostic evidence only. It never registers or renders an
investor artifact. Invoke from the repository root with an explicit fixture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from datetime import date
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget, PreparationBudgetExceeded
from agents.research.investment_memo import (FRESH_SECTION_PROJECTION, Memo, Source,
                                             renderable_sections, review_outcome,
                                             validate_memo, validate_sources)
from agents.research.staged_memo import run_stage
from scripts.private_investment_memo_worker import validate_saved_model_roles


ROLES = ('draft', 'draft_b', 'corrector', 'prose', 'challenge', 'review')
WORKSPACE = Path(__file__).resolve().parents[1]
FIXTURE_ROOTS = (WORKSPACE / 'tests/fixtures/public_memo',
                 WORKSPACE / 'runtime_qualification/public_fixtures')
OUTPUT_ROOT = WORKSPACE / 'runtime_qualification/local_memo_harness'


def load_fixture(path: Path):
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in FIXTURE_ROOTS):
        raise ValueError('Fixture must live in the public/synthetic fixture allowlist')
    if not resolved.name.endswith(('.public.json', '.synthetic.json')):
        raise ValueError('Fixture filename must declare .public.json or .synthetic.json')
    data = json.loads(path.read_text())
    if set(data) != {'classification', 'rights_reviewed', 'company', 'as_of_date', 'sources'}:
        raise ValueError('Fixture needs only classification, rights_reviewed, company, as_of_date and sources')
    if data['classification'] not in {'public', 'synthetic'} or data['rights_reviewed'] is not True:
        raise ValueError('Only explicitly rights-reviewed public or synthetic fixtures are allowed')
    if not resolved.name.endswith('.' + data['classification'] + '.json'):
        raise ValueError('Fixture filename and classification disagree')
    if not isinstance(data['company'], str) or not data['company'].strip() or len(data['company']) > 200:
        raise ValueError('Invalid company label')
    date.fromisoformat(data['as_of_date'])
    sources = [Source.model_validate(row) for row in data['sources']]
    validate_sources(sources)
    for source in sources:
        if data['classification'] == 'public' and not source.url.startswith('https://'):
            raise ValueError('Public fixture source URLs require HTTPS')
        if data['classification'] == 'synthetic' and not source.url.startswith('https://example.invalid/'):
            raise ValueError('Synthetic fixture sources require example.invalid URLs')
    return data, sources


def installed_models():
    # Ollama tags are read over loopback. No pull, hosted endpoint, or fallback.
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
        rows = json.load(response)['models']
    return {row['name']: row.get('digest') for row in rows}


def pin_roles(names, installed):
    pinned = {}
    for role in ROLES:
        name = names[role]
        exact = name if ':' in name else name + ':latest'
        if exact not in installed or not installed[exact]:
            raise ValueError(f'{role} model {name!r} is not installed with a digest')
        pinned[role] = {'name': exact, 'digest': installed[exact]}
    return pinned


def model_options(role):
    """The frozen local generation options of each role, recorded in the profile."""
    return {'thinking': False, 'temperature': 0,
            'max_tokens': 1000 if role == 'prose' else
                          1400 if role in {'draft', 'draft_b'} else 1500,
            'context_tokens': 8192 if role in {'prose', 'draft_b'} else 16384}


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


class ReplayOnlyModel:
    """Fail closed if a saved draft would require a new model response."""

    def generate_for_task(self, *args, **kwargs):
        raise ValueError('Saved draft replay attempted fresh local inference')


def replay_attempts(previous: Path, *, data, pinned, phase_limits, seconds):
    previous = previous.resolve()
    if not previous.is_relative_to(OUTPUT_ROOT.resolve()) or previous == OUTPUT_ROOT.resolve():
        raise ValueError('Replay source must be a prior diagnostic run')
    profile = json.loads((previous / 'profile.json').read_text())
    report = json.loads((previous / 'result.json').read_text())
    raw = (previous / 'attempts.json').read_bytes()
    attempts = json.loads(raw)
    pass_rows = json.loads((previous / 'passes.json').read_text())
    if report.get('workflow_state') not in {'awaiting_input', 'blocked'} or (
            previous / 'accepted.json').exists():
        raise ValueError('Replay source must be a terminal unaccepted diagnostic')
    if profile.get('kind') != 'public_synthetic_staged_memo_evaluation' or (
            profile.get('fixture_sha256') != digest(data) or
            profile.get('source_set_sha256') != digest(data['sources']) or
            profile.get('classification') != data['classification'] or
            profile.get('as_of_date') != data['as_of_date'] or
            profile.get('operator_attested_public_or_synthetic') is not True):
        raise ValueError('Replay fixture or source set differs')
    if (profile.get('models') != pinned or
            profile.get('model_options') != {role: model_options(role) for role in ROLES} or
            profile.get('seconds_per_pass') != seconds or
            profile.get('calls_per_pass') != 5 or profile.get('requests_per_pass') != 5):
        raise ValueError('Replay model or bounded pass configuration differs')
    old_limits = profile.get('phase_limits')
    if (profile.get('phase_split') is not True or not isinstance(old_limits, dict) or
            set(old_limits) != set(phase_limits) or
            any(old_limits[key] != phase_limits[key] for key in phase_limits
                if key != 'ledger_only') or
            not 1 <= old_limits.get('ledger_only', 0) < phase_limits['ledger_only']):
        raise ValueError('Replay may only increase the finite ledger pass cap')
    if not isinstance(attempts, list) or not isinstance(pass_rows, list) or not pass_rows:
        raise ValueError('Replay raw attempts or pass ledger is missing')
    if (profile.get('max_passes') != sum(old_limits.values()) or
            report.get('pass_count') != len(pass_rows)):
        raise ValueError('Replay profile or pass count is inconsistent')
    ids = [row.get('id') for row in attempts]
    if any(not isinstance(identifier, str) or not identifier for identifier in ids) or len(set(ids)) != len(ids):
        raise ValueError('Replay raw attempts have missing or repeated IDs')
    observed = {row['id']: row.get('task') for row in attempts}
    if any(not isinstance(row, dict) or
           any(observed.get(identifier) != task for identifier, task in zip(
               row.get('attempt_ids', []), row.get('attempt_tasks', []))) or
           len(row.get('attempt_ids', [])) != len(row.get('attempt_tasks', []))
           for row in pass_rows):
        raise ValueError('Replay pass ledger does not match raw attempts')
    if [identifier for row in pass_rows for identifier in row['attempt_ids']] != ids:
        raise ValueError('Replay pass ledger does not account for all raw attempts')
    if not any(row.get('job_phase') == 'draft_only' and row.get('state') == 'draft_ready'
               for row in pass_rows):
        raise ValueError('Replay source has no completed source-bound draft')
    validate_saved_model_roles(attempts, {role: pinned[role]['name'] for role in ROLES})
    return attempts, {'path': str(previous), 'attempts_sha256': hashlib.sha256(raw).hexdigest(),
                      'profile_sha256': hashlib.sha256((previous / 'profile.json').read_bytes()).hexdigest(),
                      'prior_ledger_cap': old_limits['ledger_only']}


def evaluate(fixture_path: Path, output: Path, names: dict[str, str], *, passes=3, seconds=105,
             operator_attested=False, phase_split=False, draft_passes=6,
             ledger_passes=5, review_passes=2, replay_from=None,
             memo_draft_contract='memo-cards-v2'):
    if not 1 <= passes <= 3 or not 1 <= seconds <= 105:
        raise ValueError('Evaluation is limited to three passes of at most 105 seconds')
    if not 1 <= draft_passes <= 6:
        raise ValueError('Draft evaluation is limited to six bounded passes')
    if not 1 <= ledger_passes <= 5 or not 1 <= review_passes <= 2:
        raise ValueError('Ledger/review evaluation exceeds finite phase caps')
    if not operator_attested:
        raise ValueError('An operator must attest that every fixture byte is public or synthetic')
    if not output.resolve().is_relative_to(OUTPUT_ROOT.resolve()) or output.resolve() == OUTPUT_ROOT.resolve():
        raise ValueError('Diagnostic output must be inside ignored runtime_qualification/local_memo_harness')
    data, sources = load_fixture(fixture_path)
    pinned = pin_roles(names, installed_models())
    phase_limits = ({'draft_only': draft_passes, 'correction_only': passes,
                     'ledger_only': ledger_passes, 'review_only': review_passes}
                    if phase_split else {'all': passes})
    if replay_from is not None and not phase_split:
        raise ValueError('Saved replay requires the finite phase split')
    attempts, replay_provenance = replay_attempts(Path(replay_from), data=data, pinned=pinned,
        phase_limits=phase_limits, seconds=seconds) if replay_from is not None else ([], None)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    output.chmod(0o700)
    profile = {'kind': 'public_synthetic_staged_memo_evaluation',
               'fixture_sha256': digest(data), 'source_set_sha256': digest(data['sources']),
               'classification': data['classification'], 'as_of_date': data['as_of_date'],
               'operator_attested_public_or_synthetic': True,
               'models': pinned, 'max_passes': sum(phase_limits.values()),
               'phase_split': phase_split, 'phase_limits': phase_limits,
               'seconds_per_pass': seconds,
               'calls_per_pass': 5, 'requests_per_pass': 5,
               'model_options': {role: model_options(role) for role in ROLES},
               # Frozen with the run; a profile saved without it keeps the first layout.
               'section_projection': FRESH_SECTION_PROJECTION,
               **({'memo_draft_contract': memo_draft_contract}
                  if replay_from is None else {})}
    if replay_provenance is not None:
        profile['replay_from'] = replay_provenance
    atomic_json(output / 'profile.json', profile)
    if replay_provenance is not None:
        (output / 'attempts.json').write_bytes((Path(replay_from).resolve() / 'attempts.json').read_bytes())
        os.chmod(output / 'attempts.json', 0o600)
    pass_rows = []

    def save():
        atomic_json(output / 'attempts.json', attempts)

    result = {'state': 'not_started'}
    phase = 'draft_only' if phase_split else 'all'
    checkpoint = None
    phase_attempt = 0
    next_phase = {'draft_only': ('draft_ready', 'correction_only'),
                  'correction_only': ('correction_ready', 'ledger_only'),
                  'ledger_only': ('ledger_ready', 'review_only')}
    for number in range(1, sum(phase_limits.values()) + 1):
        phase_attempt += 1
        before = len(attempts)
        budget = PreparationBudget(seconds, max_calls=5, max_requests=5)
        started = time.monotonic()
        try:
            current = installed_models()
            if any(current.get(pinned[role]['name']) != pinned[role]['digest'] for role in ROLES):
                raise ValueError('Installed local model digest changed during evaluation')
            role_names = {role: pinned[role]['name'] for role in ROLES}
            validate_saved_model_roles(attempts, role_names)
            models = {role: (ReplayOnlyModel() if replay_provenance is not None and
                             phase == 'draft_only' else
                             LocalModel(pinned[role]['name'], **model_options(role)))
                      for role in ROLES}
            result = run_stage(data['company'], sources, attempts, save,
                draft_model=models['draft'], part_b_model=models['draft_b'],
                review_model=models['review'], challenge_model=models['challenge'],
                correction_model=models['corrector'], prose_model=models['prose'],
                as_of_date=data['as_of_date'], budget=budget, phase=phase,
                phase_checkpoint=checkpoint,
                compact_part_a=phase_split, compact_part_b=phase_split,
                memo_draft_contract=profile.get('memo_draft_contract'))
            validate_saved_model_roles(attempts, role_names)
        except PreparationBudgetExceeded as exc:
            result = {'state': 'needs_resume', 'reason': 'bounded_time_or_call_limit',
                      'error': str(exc)}
        except Exception as exc:
            result = {'state': 'blocked', 'reason': type(exc).__name__, 'error': str(exc)}
        try:
            validate_saved_model_roles(attempts, {role: pinned[role]['name'] for role in ROLES})
        except ValueError as exc:
            result = {'state': 'blocked', 'reason': 'model_role_mismatch', 'error': str(exc)}
        try:
            current = installed_models()
            if any(current.get(pinned[role]['name']) != pinned[role]['digest'] for role in ROLES):
                result = {'state': 'blocked', 'reason': 'model_digest_changed'}
        except Exception as exc:
            result = {'state': 'blocked', 'reason': 'model_digest_recheck_failed',
                      'error': str(exc)}
        if phase_split and result['state'] in {
                'draft_ready', 'correction_ready', 'ledger_ready', 'accepted'}:
            expected = {name: state for name, (state, _) in next_phase.items()}
            expected['review_only'] = 'accepted'
            if result['state'] != expected.get(phase):
                result = {'state': 'blocked', 'reason': 'memo_phase_result_mismatch'}
        pass_rows.append({'pass': number, 'job_phase': phase, 'phase_attempt': phase_attempt,
                          'checkpoint_digest': digest(checkpoint) if checkpoint else None,
                          'state': result['state'],
                          'phase': result.get('phase'), 'reason': result.get('reason'),
                          'elapsed_seconds': round(time.monotonic() - started, 3),
                          'budget': budget.snapshot(),
                          'attempt_ids': [row['id'] for row in attempts[before:]],
                          'attempt_tasks': [row['task'] for row in attempts[before:]]})
        atomic_json(output / 'passes.json', pass_rows)
        save()
        if phase_split and phase in next_phase and result['state'] == next_phase[phase][0]:
            checkpoint = result
            phase = next_phase[phase][1]
            phase_attempt = 0
            continue
        if result['state'] != 'needs_resume':
            break
        if phase_split and phase_attempt >= phase_limits[phase]:
            result = {**result, 'state': 'awaiting_input',
                      'reason': 'bounded_' + phase + '_attempts_exhausted'}
            break

    source_validation = 'not_reached'
    render_validation, rendered_sections = 'not_reached', 0
    review_status = 'not_reached'
    ledger = result.get('accepted', {}).get('challenge') or {}
    challenge_status = ('not_reached' if not ledger else
                        'conflict_corrected' if ledger['coverage']['conflicts'] else
                        'no_direct_conflict')
    if result.get('reason') in ('challenge_coverage_incomplete', 'challenge_conflict_unresolved'):
        challenge_status = result['reason']
    if result['state'] == 'accepted':
        # A digest field alone proves nothing. The ledger record must be complete
        # and conflict-free here, and the renderer replay below must rebuild it.
        post = (ledger.get('post_correction') or {}).get('coverage', {})
        if not ledger or 'challenged_memo_digest' not in result['accepted']:
            result = {'state': 'blocked', 'reason': 'challenge_role_did_not_run'}
        elif ledger.get('coverage', {}).get('complete') is not True or post.get('conflicts', 0):
            result = {'state': 'blocked', 'reason': 'challenge_ledger_incomplete_or_conflicting'}
    if result['state'] == 'accepted':
        try:
            memo = Memo.model_validate(result['accepted']['memo'])
            validate_memo(memo, sources)
            source_validation = 'pass'
            review = result['accepted']['review']
            review_status = 'pass' if review_outcome(review, memo, sources)[0] else 'fail'
        except Exception as exc:
            source_validation = 'fail: ' + str(exc)
        try:
            # Draft-to-render: the production renderer rebuilds the memo from the
            # exact recorded responses. Nothing is written or registered; only the
            # count and the outcome are reported.
            sections = renderable_sections(result['accepted'], sources, attempts,
                                           projection=profile.get('section_projection'))
            rendered_sections = len(sections)
            render_validation = 'pass' if sections and all(
                heading and body for heading, body, _ in sections) else 'fail: empty section'
        except Exception as exc:
            render_validation = 'fail: ' + str(exc)[:300]
    else:
        review_rows = [row for row in attempts if row['task'] == 'investment_memo_review']
        if review_rows:
            latest = review_rows[-1]
            reviewed = None      # set only when the reviewed memo is valid AND source-bound
            try:
                candidate = Memo.model_validate(latest['input']['memo'])
                validate_memo(candidate, sources)
                reviewed, source_validation = candidate, 'pass'
            except Exception as exc:
                source_validation = 'fail: ' + str(exc)
            answer = latest.get('answer', {})
            if latest.get('error'):
                review_status = 'failed_generation'
            elif 'blocking' in answer and reviewed is None:
                # The reviewed memo failed schema or source validation, so a review of
                # it can be neither bound nor counted as a pass.
                review_status = 'unbindable_reviewed_memo_invalid'
            elif 'blocking' in answer:
                try:
                    review_status = ('pass' if review_outcome(answer, reviewed, sources)[0]
                                     else 'revise')
                except Exception:
                    review_status = 'failed_generation'
            else:
                review_status = answer.get('verdict', 'failed_generation')
    report = {'workflow_state': result['state'], 'phase': result.get('phase'),
              'reason': result.get('reason'), 'failure_detail': result.get('error'),
              'source_validation': source_validation,
              'render_validation': render_validation, 'rendered_sections': rendered_sections,
              'recommendation': (result.get('accepted') or {}).get('memo', {}).get('recommendation')
                                if isinstance((result.get('accepted') or {}).get('memo'), dict)
                                else None,
              'independent_review': 'pending',
              'review_status': review_status, 'challenge_status': challenge_status,
              'acceptance_scope': 'local_model_checks_only',
              'attempt_count': len(attempts),
              'pass_count': len(pass_rows), 'fixture_sha256': profile['fixture_sha256'],
              'phase_pass_counts': {name: sum(row['job_phase'] == name for row in pass_rows)
                                    for name in phase_limits},
              'phase_limits': phase_limits,
              'source_set_sha256': profile['source_set_sha256'],
              'artifact_status': 'diagnostic_only_no_promotion'}
    report['evaluation_state'] = (
        'local_review_passed_independent_review_pending' if result['state'] == 'accepted' and
        source_validation == 'pass' and review_status == 'pass' and render_validation == 'pass' else
        'blocked' if result['state'] == 'accepted' else result['state'])
    if result['state'] == 'accepted' and report['evaluation_state'] == 'local_review_passed_independent_review_pending':
        # Public/synthetic diagnostic only. The separate material harness
        # replays this exact model object and the raw attempt log.
        atomic_json(output / 'accepted.json', result['accepted'])
    atomic_json(output / 'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path, help='Explicit rights-reviewed public/synthetic JSON fixture')
    parser.add_argument('output', type=Path, help='New diagnostic directory; existing paths are refused')
    for role in ROLES:
        parser.add_argument('--' + ('part-b' if role == 'draft_b' else role) + '-model',
                            required=role not in ('draft_b', 'challenge'),
                            help='Defaults to the draft model' if role == 'draft_b' else
                                 'Defaults to the review model' if role == 'challenge' else None)
    parser.add_argument('--passes', type=int, default=3)
    parser.add_argument('--draft-passes', type=int, default=6)
    parser.add_argument('--ledger-passes', type=int, default=5)
    parser.add_argument('--review-passes', type=int, default=2)
    parser.add_argument('--seconds', type=float, default=105)
    parser.add_argument('--operator-attested', action='store_true',
                        help='I inspected this fixture and attest it contains only public or synthetic data')
    parser.add_argument('--phase-split', action='store_true',
                        help='Use finite draft, correction, ledger and review pass budgets')
    parser.add_argument('--memo-contract', choices=('memo-cards-v2', 'memo-cards-v3',
                                                    'memo-cards-v4', 'memo-cards-v5',
                                                    'memo-cards-v6', 'memo-cards-v7',
                                                    'memo-cards-v8', 'memo-cards-v9',
                                                    'memo-cards-v10', 'memo-cards-v11',
                                                    'memo-cards-v12', 'memo-cards-v13'),
                        default='memo-cards-v2',
                        help='Fresh source-bound memo draft contract; saved replay stays frozen')
    parser.add_argument('--replay-from', type=Path,
                        help='New run from exact saved public/synthetic attempts; only ledger cap may increase')
    args = parser.parse_args()
    names = {role: getattr(args, ('part_b' if role == 'draft_b' else role) + '_model')
             or (args.review_model if role == 'challenge' else args.draft_model)
             for role in ROLES}
    print(json.dumps(evaluate(args.fixture, args.output, names,
                              passes=args.passes, seconds=args.seconds,
                              operator_attested=args.operator_attested,
                              phase_split=args.phase_split,
                              draft_passes=args.draft_passes,
                              ledger_passes=args.ledger_passes,
                              review_passes=args.review_passes,
                              replay_from=args.replay_from,
                              memo_draft_contract=args.memo_contract)))


if __name__ == '__main__':
    main()
