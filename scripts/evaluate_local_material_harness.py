"""Public/synthetic-only local material drafting from an accepted memo diagnostic.

No artifact is registered or investor material accepted. Each pass makes at most
one installed local-model call and retains every raw response in the output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.research.investment_memo import renderable_sections
from agents.research.material_slides import replay_material_rows, render_sections
from delivery.inspection import inspect_export_pair
from delivery.rendering import render_intro, render_deck_pdf, render_memo, render_memo_pdf
from scripts.evaluate_local_memo_harness import (OUTPUT_ROOT as MEMO_OUTPUT_ROOT,
    load_fixture, installed_models, atomic_json)
from scripts.private_material_worker import draft_materials


OUTPUT_ROOT = Path(__file__).resolve().parents[1] / 'runtime_qualification/local_material_harness'


def reusable_intro(replay_from: Path, base, pinned_name):
    """Verify a terminal synthetic run before copying only its accepted intro rows."""
    if (not replay_from.resolve().is_relative_to(OUTPUT_ROOT.resolve()) or
            replay_from.resolve() == OUTPUT_ROOT.resolve()):
        raise ValueError('Material replay source is outside its diagnostic root')
    prior_result = json.loads((replay_from / 'result.json').read_text())
    if (prior_result.get('state') not in {'blocked', 'needs_resume'} or
            prior_result.get('acceptance_scope') != 'public_synthetic_diagnostic_only' or
            prior_result.get('investor_material_accepted') is not False):
        raise ValueError('Material replay requires a terminal nonaccepted synthetic diagnostic')
    old_request = json.loads((replay_from / 'material_request.json').read_text())
    if (old_request.get('digest') != digest({key: value for key, value in old_request.items()
                                              if key != 'digest'}) or
            digest({key: value for key, value in old_request.items() if key != 'digest'}) !=
            digest(base)):
        raise ValueError('Material replay source memo, fixture, or input digest differs')
    if json.loads((replay_from / 'model.json').read_text()) != {
            'profiles': {'draft': pinned_name}}:
        raise ValueError('Material replay source model differs')
    raw_bytes = (replay_from / 'material_attempts.json').read_bytes()
    rows = json.loads(raw_bytes)
    replayed = replay_material_rows('intro_deck', {**base, 'kind': 'intro_deck'},
                                    rows, base['sections'], model_name=pinned_name,
                                    contract_version='v5')
    if replayed['state'] != 'accepted':
        raise ValueError('Material replay source intro was not accepted')
    intro_rows = [row for row in rows if row.get('task') in {
        'material_intro_deck', 'material_intro_deck_patch'}]
    if not 1 <= len(intro_rows) <= 3 or [row['id'] for row in intro_rows] != [
            'response_' + str(number) for number in range(1, len(intro_rows) + 1)]:
        raise ValueError('Material replay source intro response sequence differs')
    return intro_rows, {'source': str(replay_from.resolve()),
                        'source_attempts_sha256': hashlib.sha256(raw_bytes).hexdigest(),
                        'intro_rows_digest': digest(intro_rows),
                        'intro_response_ids': replayed['response_ids'],
                        'contract_version': 'v5'}


def evaluate(memo_output: Path, fixture: Path, output: Path, *, operator_attested=False,
             replay_from: Path | None = None, resume_existing=False):
    if not operator_attested:
        raise ValueError('Public or synthetic fixture bytes require operator attestation')
    if not memo_output.resolve().is_relative_to(MEMO_OUTPUT_ROOT.resolve()):
        raise ValueError('Memo diagnostic must be under the allowlisted output root')
    if not output.resolve().is_relative_to(OUTPUT_ROOT.resolve()) or output.resolve() == OUTPUT_ROOT.resolve():
        raise ValueError('Material diagnostic must be under its ignored output root')
    data, sources = load_fixture(fixture)
    profile = json.loads((memo_output / 'profile.json').read_text())
    report = json.loads((memo_output / 'result.json').read_text())
    if (profile['fixture_sha256'] != digest(data) or
            report['evaluation_state'] != 'local_review_passed_independent_review_pending'):
        raise ValueError('Memo fixture or acceptance is not exact')
    accepted = json.loads((memo_output / 'accepted.json').read_text())
    attempts = json.loads((memo_output / 'attempts.json').read_text())
    sections = renderable_sections(accepted, sources, attempts)
    pinned = profile['models']['draft']
    if installed_models().get(pinned['name']) != pinned['digest']:
        raise ValueError('Installed local draft model digest changed')
    base = {'input_revision': digest(data), 'source_hash': profile['source_set_sha256'],
            'memo_digest': digest(accepted), 'sections': sections}
    # Recorded requests pass through JSON; normalize tuple sections before
    # comparing exact saved payloads during a continuation.
    base = json.loads(json.dumps(base, ensure_ascii=False))
    prior_intro = None
    replay_manifest = None
    if resume_existing and replay_from is not None:
        raise ValueError('Existing material finalization cannot start a new replay')
    if replay_from is not None:
        prior_intro, replay_manifest = reusable_intro(replay_from, base, pinned['name'])
    request_base = {**base, 'replay_contracts': {
        'intro_deck': 'v5' if prior_intro is not None else 'structured_v5',
        'pitch_deck': 'structured_v5'}}
    if resume_existing:
        saved_versions = json.loads((output / 'material_request.json').read_text()).get('replay_contracts')
        if saved_versions in ({'intro_deck': 'structured', 'pitch_deck': 'structured'},
                              {'intro_deck': 'structured_v2', 'pitch_deck': 'structured_v2'},
                              {'intro_deck': 'structured_v3', 'pitch_deck': 'structured_v3'},
                              {'intro_deck': 'structured_v4', 'pitch_deck': 'structured_v4'},
                              {'intro_deck': 'v5', 'pitch_deck': 'structured'}):
            request_base['replay_contracts'] = saved_versions
    expected_request = {**request_base, 'digest': digest(request_base)}
    expected_model = {'profiles': {'draft': pinned['name']}}
    if resume_existing:
        if (json.loads((output / 'material_request.json').read_text()) != expected_request or
                json.loads((output / 'model.json').read_text()) != expected_model):
            raise ValueError('Existing material output does not match exact memo and model')
        passes = json.loads((output / 'passes.json').read_text())
        if not passes:
            raise ValueError('Existing material output lacks recorded passes')
        if passes[-1]['state'] == 'accepted':
            prior_attempts = (output / 'material_attempts.json').read_bytes()
            class NoInference:
                name = pinned['name']
                def generate_for_task(self, *args, **kwargs):
                    raise AssertionError('Finalization must not call inference')
            result = draft_materials(output, NoInference())
            if (result['state'] != 'accepted' or
                    (output / 'material_attempts.json').read_bytes() != prior_attempts):
                raise ValueError('Existing material finalization changed model attempts')
        elif passes[-1]['state'] == 'needs_resume':
            result = {'state': 'not_started'}
        else:
            raise ValueError('Existing material output is already terminal')
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
        output.chmod(0o700)
        atomic_json(output / 'material_request.json', expected_request)
        atomic_json(output / 'model.json', expected_model)
        if prior_intro is not None:
            atomic_json(output / 'material_attempts.json', prior_intro)
            atomic_json(output / 'reused_intro.json', replay_manifest)
        passes = []
        result = {'state': 'not_started'}
    if result['state'] == 'not_started':
        for number in range(len(passes) + 1, 7):
            if installed_models().get(pinned['name']) != pinned['digest']:
                result = {'state': 'blocked', 'reason': 'installed_model_digest_changed'}
                break
            atomic_json(output / 'material_budget.json', {'seconds': 105})
            model = LocalModel(pinned['name'], thinking=False, max_tokens=2600,
                               context_tokens=16384, temperature=0)
            result = draft_materials(output, model)
            passes.append({'pass': number, 'state': result['state'],
                           'reason': result.get('reason')})
            atomic_json(output / 'passes.json', passes)
            if result['state'] != 'needs_resume':
                break
    pair_reports = {}
    if result['state'] == 'accepted':
        recorded = json.loads((output / 'material_attempts.json').read_text())
        for kind in ('intro_deck', 'pitch_deck'):
            replayed = replay_material_rows(kind, {**base, 'kind': kind}, recorded,
                                           base['sections'], model_name=pinned['name'],
                                           contract_version=request_base['replay_contracts'][kind])
            if (replayed['state'] != 'accepted' or
                    replayed['response_ids'] != result['decks'][kind]['response_ids'] or
                    [list(row) for row in render_sections(replayed['spec'], base['sections'])] !=
                    [list(row) for row in result['decks'][kind]['sections']]):
                raise ValueError('Material diagnostic projection differs from exact model replay')
        for stem, kind in (('intro', 'intro_deck'), ('pitch', 'pitch_deck')):
            slide_sections = result['decks'][kind]['sections']
            pptx = render_intro(data['company'], slide_sections)
            pdf = render_deck_pdf(data['company'], slide_sections)
            pair = inspect_export_pair(pptx, 'pptx', pdf)
            pair_reports[stem] = pair
            if pair['pair_status'] == 'pass' and pair['editable_text_status'] == 'pass':
                (output / f'{stem}.pptx').write_bytes(pptx)
                (output / f'{stem}.pdf').write_bytes(pdf)
        docx = render_memo(data['company'], sections)
        pdf = render_memo_pdf(data['company'], sections)
        pair = inspect_export_pair(docx, 'docx', pdf)
        pair_reports['memo'] = pair
        if pair['pair_status'] == 'pass' and pair['editable_text_status'] == 'pass':
            (output / 'memo.docx').write_bytes(docx)
            (output / 'memo.pdf').write_bytes(pdf)
    summary = {'state': result['state'], 'reason': result.get('reason'),
               'passes': len(passes), 'attempt_count': len(json.loads(
                   (output / 'material_attempts.json').read_text())) if
                   (output / 'material_attempts.json').exists() else 0,
               'pair_reports': pair_reports,
               'acceptance_scope': 'public_synthetic_diagnostic_only',
               'investor_material_accepted': False}
    atomic_json(output / 'result.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('memo_output', type=Path)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--operator-attested-public-or-synthetic', action='store_true')
    parser.add_argument('--replay-from', type=Path)
    parser.add_argument('--resume-existing', action='store_true')
    args = parser.parse_args()
    print(json.dumps(evaluate(args.memo_output, args.fixture, args.output,
        operator_attested=args.operator_attested_public_or_synthetic,
        replay_from=args.replay_from, resume_existing=args.resume_existing), indent=2))


if __name__ == '__main__':
    main()
