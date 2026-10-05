"""Synthetic-only reviewer pair diagnostic: a clean deck and the same deck with one
planted false assertion, each reviewed by a pinned local model.

The control states only what its cited source reports. The defect differs by one
sentence that claims a receipt of funds the same source does not report. A
reviewer passes the pair only by accepting the control and blocking the defect
with a finding bound to exactly the planted sentence and its source.

Nothing here registers, renders or approves investor material, and no production
output is read or written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from scripts.evaluate_local_material_review_harness import (FRESH_REVIEW_CONTRACT, REVIEW_OPTIONS,
    model_slug, require_supported_contract, review_pin)
from scripts.evaluate_local_memo_harness import installed_models
from scripts.private_material_review_worker import review_materials

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / 'tests/fixtures/material_review'
OUTPUT_ROOT = ROOT / 'runtime_qualification/local_material_review_pair'
MAX_PASSES = 2          # the worker's own cap: one call per pass, two recorded attempts
PASS_SECONDS = 105
SCOPE = {'acceptance_scope': 'public_synthetic_diagnostic_only',
         'investor_material_accepted': False, 'independent_review': 'pending'}


class NoInference:
    def __init__(self, name):
        self.name = name

    def generate_for_task(self, *args, **kwargs):
        raise AssertionError('Pair diagnostic replay must not call inference')


def load_fixture(path: Path) -> dict:
    """A synthetic pair whose two decks differ by exactly the planted sentence."""
    path = Path(path).resolve()
    if not path.is_relative_to(FIXTURE_ROOT.resolve()) or not path.name.endswith('.synthetic.json'):
        raise ValueError('Pair fixture must be a .synthetic.json file in the review fixture folder')
    data = json.loads(path.read_text())
    if set(data) - {'claim_flag'} != {'classification', 'pair', 'memo_sections', 'shared_decks',
                                      'control', 'defect'} or data['classification'] != 'synthetic':
        raise ValueError('Pair fixture needs classification synthetic and its six fields')
    flag = data.get('claim_flag')
    if flag is not None and (not isinstance(flag, dict) or set(flag) != {'name', 'definition'}
                             or not re.fullmatch(r'[a-z][a-z0-9_]{2,40}', str(flag['name']))
                             or not 20 <= len(str(flag['definition'])) <= 300):
        raise ValueError('claim_flag needs a snake_case name and a one-sentence definition')
    text = json.dumps(data)
    urls = re.findall(r'https?://[^\s"|]+', text)
    if any(not url.startswith('https://example.invalid/') for url in urls):
        raise ValueError('Synthetic pair fixture may cite only example.invalid URLs')
    planted = data['defect']['planted']
    decks = {case: {**data['shared_decks'], **{kind: rows for kind, rows in data[case].items()
                                               if kind != 'planted'}}
             for case in ('control', 'defect')}
    for case in decks.values():
        if set(case) != {'intro_deck', 'pitch_deck'}:
            raise ValueError('Each case needs an intro deck and a pitch deck')
    control_body = decks['control'][planted['deck']][planted['slide_index']][1]
    defect_body = decks['defect'][planted['deck']][planted['slide_index']][1]
    if defect_body.count(planted['sentence']) != 1 or planted['sentence'] in control_body:
        raise ValueError('The planted sentence must be in the defect deck once and not in the '
                         'control')
    if planted['source_id'] not in planted['sentence'] or not any(
            planted['source_id'] in section[1] for section in data['memo_sections']):
        raise ValueError('The planted sentence must cite a source the memo also cites')
    # The decks differ by the planted sentence and nothing else: taking that one
    # sentence out of the defect must give the control exactly, slide for slide.
    restored = json.loads(json.dumps(decks['defect']))
    plain = lambda text: ' '.join(text.split())
    restored[planted['deck']][planted['slide_index']][1] = plain(
        defect_body.replace(planted['sentence'], ''))
    expected = json.loads(json.dumps(decks['control']))
    expected[planted['deck']][planted['slide_index']][1] = plain(control_body)
    if restored != expected:
        raise ValueError('Control and defect may differ only by the planted sentence')
    return {'pair': data['pair'], 'memo_sections': data['memo_sections'], 'decks': decks,
            'planted': planted, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            **({'claim_flag': flag} if flag else {})}


def score_case(case: str, result: dict, planted: dict) -> dict:
    """Decision properties only: the verdict, and where the blocking finding points."""
    findings = (result.get('review') or {}).get('findings') or []
    if case == 'control':
        passed = result.get('state') == 'accepted' and not findings
        return {'case': case, 'expected': 'accepted_with_no_finding', 'passed': passed,
                'state': result.get('state'), 'reason': result.get('reason'),
                'false_positive_findings': len(findings)}
    exact = [item for item in findings
             if item.get('deck') == planted['deck']
             and item.get('slide_index') == planted['slide_index']
             and item.get('body_quote') and (item['body_quote'] in planted['sentence']
                                             or planted['sentence'] in item['body_quote'])
             and planted['source_id'] in (item.get('memo_quote') or '')
             # Where the contract carries the disputed proposition, it must lie in
             # the planted sentence too.
             and (item.get('unsupported_proposition') is None
                  or item['unsupported_proposition'] in planted['sentence'])
             and item.get('issue') in planted['allowed_issues']]
    blocked = result.get('state') == 'blocked' and result.get('reason') == 'model_review_blocked'
    elsewhere = len(findings) - len(exact)
    # Exactly the planted defect and nothing else: a second finding on a sentence
    # the control also contains is a false positive, and it fails the case.
    return {'case': case, 'expected': 'blocked_on_only_the_planted_sentence_and_its_source',
            'passed': blocked and bool(exact) and elsewhere == 0, 'state': result.get('state'),
            'reason': result.get('reason'), 'planted_sentence_flagged_exactly': bool(exact),
            'findings_elsewhere': elsewhere}


def evaluate(fixture_path: Path, output: Path, review_model: str, *, operator_attested=False,
             review_contract=FRESH_REVIEW_CONTRACT):
    if not operator_attested:
        raise ValueError('Synthetic fixture use requires operator attestation')
    output = Path(output).resolve()
    if not output.is_relative_to(OUTPUT_ROOT.resolve()) or output == OUTPUT_ROOT.resolve():
        raise ValueError('Pair diagnostic must be under its ignored output root')
    fixture = load_fixture(fixture_path)
    require_supported_contract(review_contract)
    # A pinned, installed local model, named in the output directory. Nothing is downloaded.
    pin, pin_record = review_pin(review_model, review_model, installed_models(), output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700, exist_ok=False)
    profile = {'kind': 'material_review_pair_diagnostic', 'pair': fixture['pair'],
               'fixture_sha256': fixture['sha256'], 'review_contract': review_contract,
               'review_model': pin_record, 'max_passes_per_case': MAX_PASSES,
               'calls_per_pass': 1, 'seconds_per_pass': PASS_SECONDS, **SCOPE}
    (output / 'profile.json').write_text(json.dumps(profile, ensure_ascii=False, indent=1))
    cases = []
    for case in ('control', 'defect'):
        root = output / case            # each case is frozen in its own directory
        root.mkdir(mode=0o700)
        base = {'review_contract': review_contract,
                'input_revision': f"{fixture['pair']}:{case}",
                'source_hash': fixture['sha256'], 'memo_digest': digest(fixture['memo_sections']),
                'material_digest': digest(fixture['decks'][case]),
                'memo_sections': fixture['memo_sections'], 'decks': fixture['decks'][case],
                'review_model': pin}
        base = json.loads(json.dumps(base, ensure_ascii=False))
        (root / 'material_review_request.json').write_text(json.dumps(
            {**base, 'digest': digest(base)}, ensure_ascii=False))
        passes, result = [], None
        for number in range(1, MAX_PASSES + 1):
            if installed_models().get(pin['name']) != pin['digest']:
                result = {'state': 'blocked', 'reason': 'installed_review_model_digest_changed'}
                break
            (root / 'material_review_budget.json').write_text(json.dumps(
                {'seconds': PASS_SECONDS}))
            result = review_materials(root, LocalModel(pin['name'], **REVIEW_OPTIONS))
            passes.append({'pass': number, 'state': result['state'],
                           'reason': result.get('reason')})
            (root / 'passes.json').write_text(json.dumps(passes))
            if result['state'] != 'needs_resume':
                break
        if result.get('response_id') and review_materials(root, NoInference(pin['name'])) != result:
            raise ValueError('Pair diagnostic differs from exact recorded model replay')
        (root / 'material_review_result.json').write_text(json.dumps(result, ensure_ascii=False))
        cases.append({**score_case(case, result, fixture['planted']), 'passes': len(passes),
                      'response_id': result.get('response_id'), 'directory': case})
    scorecard = {'kind': 'material_review_pair_scorecard', 'pair': fixture['pair'],
                 'review_contract': review_contract, 'review_model': pin_record,
                 'cases': cases,
                 # Both sides must be right: accepting everything or blocking everything fails.
                 'pair_passed': all(case['passed'] for case in cases),
                 'control_false_positive': not cases[0]['passed'],
                 'defect_missed_or_misplaced': not cases[1]['passed'],
                 'score_limits': 'two synthetic cases, one run; a pass says the reviewer '
                                 'separated this one planted sentence from its control',
                 **SCOPE}
    (output / 'scorecard.json').write_text(json.dumps(scorecard, ensure_ascii=False, indent=1))
    return scorecard


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('output', type=Path,
                        help='A new directory under runtime_qualification/'
                             'local_material_review_pair, named with the model')
    parser.add_argument('--review-model', required=True,
                        help='An installed local model; pinned by digest, never downloaded')
    parser.add_argument('--operator-attested-public-or-synthetic', action='store_true')
    args = parser.parse_args()
    print(json.dumps(evaluate(args.fixture, args.output, args.review_model,
        operator_attested=args.operator_attested_public_or_synthetic), indent=1))


if __name__ == '__main__':
    main()
