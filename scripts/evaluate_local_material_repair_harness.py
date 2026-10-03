"""Synthetic-only, one-call local slide repair followed by frozen re-review.

This diagnostic never registers or approves investor materials. It retains new
raw responses separately from the accepted material and blocked review inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.research.material_slides import replay_material_rows, render_sections
from scripts.evaluate_local_material_review_harness import (_slides,
    MATERIAL_ROOT, OUTPUT_ROOT as REVIEW_ROOT)
from scripts.evaluate_local_memo_harness import installed_models
from scripts.private_material_repair_worker import repair_materials
from scripts.private_material_review_worker import review_materials


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / 'runtime_qualification/local_material_repair_harness'


class NoInference:
    def __init__(self, name):
        self.name = name

    def generate_for_task(self, *args, **kwargs):
        raise AssertionError('Diagnostic replay must not call inference')


def _read_json(path):
    return json.loads(path.read_text())


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_review_request(base, recorded):
    """Bind a recorded review version without upgrading historical replays."""
    if 'review_contract' in recorded:
        base = {**base, 'review_contract': recorded['review_contract']}
    return {**base, 'digest': digest(base)}


def _re_review_request(base):
    """Apply the current contract only to a new, frozen re-review."""
    versioned = {**base, 'review_contract': 'semantic_v8'}
    return {**versioned, 'digest': digest(versioned)}


def _source_inputs(material_dir, review_dir):
    report = _read_json(material_dir / 'result.json')
    if (report.get('state') != 'accepted' or
            report.get('acceptance_scope') != 'public_synthetic_diagnostic_only' or
            report.get('investor_material_accepted') is not False):
        raise ValueError('Material input is not accepted synthetic diagnostic evidence')
    request = _read_json(material_dir / 'material_request.json')
    if request.get('digest') != digest({k: v for k, v in request.items() if k != 'digest'}):
        raise ValueError('Material request digest changed')
    for stem in ('intro', 'pitch', 'memo'):
        editable = 'docx' if stem == 'memo' else 'pptx'
        for extension, key in ((editable, 'editable_sha256'), ('pdf', 'pdf_sha256')):
            if _sha(material_dir / f'{stem}.{extension}') != report['pair_reports'][stem][key]:
                raise ValueError('Material export hash changed')
    attempts = _read_json(material_dir / 'material_attempts.json')
    model_name = _read_json(material_dir / 'model.json')['profiles']['draft']
    base = {k: request[k] for k in ('input_revision', 'source_hash',
                                      'memo_digest', 'sections')}
    decks = {}
    authored = {}
    for kind, stem in (('intro_deck', 'intro'), ('pitch_deck', 'pitch')):
        state = replay_material_rows(kind, {**base, 'kind': kind}, attempts,
            request['sections'], model_name=model_name,
            contract_version=request['replay_contracts'][kind])
        if state['state'] != 'accepted':
            raise ValueError('Material raw response no longer replays as accepted')
        rendered = [list(row) for row in render_sections(state['spec'], request['sections'])]
        exported = _slides(material_dir / f'{stem}.pptx')
        if len(rendered) != len(exported) or any(
                row[0] != slide[0] or ' '.join(row[1].split()) != ' '.join(slide[1].split())
                for row, slide in zip(rendered, exported)):
            raise ValueError('Material exported slide text differs from exact raw replay')
        decks[kind] = {'response_id': state['response_ids'][-1],
                       'response_ids': state['response_ids'], 'sections': rendered}
        authored[kind] = state['authored_spec'].model_dump(mode='json')
    review_request = _read_json(review_dir / 'material_review_request.json')
    if review_request.get('digest') != digest({k: v for k, v in review_request.items()
                                               if k != 'digest'}):
        raise ValueError('Blocked review request digest changed')
    expected_review = {'input_revision': request['input_revision'],
        'source_hash': request['source_hash'], 'memo_digest': request['memo_digest'],
        'material_digest': digest({'request': request['digest'],
                                   'pair_reports': report['pair_reports']}),
        'memo_sections': request['sections'],
        'decks': {kind: _slides(material_dir / f'{stem}.pptx')
                  for kind, stem in (('intro_deck', 'intro'), ('pitch_deck', 'pitch'))},
        'review_model': review_request['review_model']}
    if review_request != _bound_review_request(expected_review, review_request):
        raise ValueError('Blocked review is not bound to exact material exports')
    saved_review = _read_json(review_dir / 'result.json')
    replayed_review = review_materials(review_dir,
        NoInference(review_request['review_model']['name']))
    if (saved_review.get('state') != 'blocked' or
            saved_review.get('acceptance_scope') != 'public_synthetic_diagnostic_only' or
            saved_review.get('investor_material_accepted') is not False or
            saved_review.get('response_id') != replayed_review.get('response_id') or
            saved_review.get('review') != replayed_review.get('review') or
            replayed_review.get('reason') != 'model_review_blocked' or
            not replayed_review['review']['findings']):
        raise ValueError('Blocked local review did not replay quote-bound')
    return request, report, decks, authored, review_request, replayed_review


def evaluate(material_dir: Path, review_dir: Path, output: Path, *,
             operator_attested=False):
    if not operator_attested:
        raise ValueError('Synthetic fixture use requires operator attestation')
    if (not material_dir.resolve().is_relative_to(MATERIAL_ROOT.resolve()) or
            not review_dir.resolve().is_relative_to(REVIEW_ROOT.resolve()) or
            not output.resolve().is_relative_to(OUTPUT_ROOT.resolve()) or
            output.resolve() == OUTPUT_ROOT.resolve()):
        raise ValueError('Diagnostic path is outside its allowlisted root')
    material, report, decks, authored, review, blocked = _source_inputs(
        material_dir, review_dir)
    name = review['review_model']['name']
    installed = installed_models()
    if installed.get(name) != review['review_model']['digest']:
        raise ValueError('Installed local model differs from blocked review pin')
    finding = blocked['review']['findings'][0]
    kind = finding['deck']
    pin = {'name': name, 'digest': installed[name], 'options': {
        'thinking': False, 'max_tokens': 1500, 'context_tokens': 16384,
        'temperature': 0}}
    frozen_sources = {str(path.resolve().relative_to(ROOT)): _sha(path)
        for path in (material_dir / 'material_request.json',
                     material_dir / 'material_attempts.json',
                     material_dir / 'result.json',
                     review_dir / 'material_review_request.json',
                     review_dir / 'material_review_attempts.json',
                     review_dir / 'result.json')}
    base = {'input_revision': material['input_revision'],
            'source_hash': material['source_hash'],
            'memo_digest': material['memo_digest'],
            'material_digest': digest({'request': material['digest'],
                'pair_reports': report['pair_reports']}),
            'blocked_review_digest': digest(blocked),
            'review_finding': finding, 'target_deck': kind,
            'target_slide_index': finding['slide_index'],
            'material_contract': material['replay_contracts'][kind],
            'target_deck_spec': authored[kind], 'original_decks': decks,
            'memo_sections': material['sections'], 'repair_model': pin,
            'repair_contract': 'review_dispute_v1',
            'synthetic_source_hashes': frozen_sources}
    base = json.loads(json.dumps(base, ensure_ascii=False))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / 'material_repair_request.json').write_text(json.dumps(
        {**base, 'digest': digest(base)}, ensure_ascii=False))
    (output / 'material_repair_budget.json').write_text(json.dumps({'seconds': 105}))
    repaired = repair_materials(output, LocalModel(name, thinking=False,
        max_tokens=1500, context_tokens=16384, temperature=0))
    (output / 'material_repair_result.json').write_text(json.dumps(repaired,
        ensure_ascii=False))
    if digest(repair_materials(output, NoInference(name))) != digest(repaired):
        raise ValueError('Material repair differs from exact raw replay')
    review_result = None
    review_passes = []
    if repaired['state'] in {'accepted', 'disputed_without_change'}:
        re_root = output / 'material_re_review'
        re_root.mkdir(mode=0o700)
        review_base = {'input_revision': material['input_revision'],
            'source_hash': material['source_hash'], 'memo_digest': material['memo_digest'],
            'material_digest': digest(repaired), 'memo_sections': material['sections'],
            'decks': {deck_kind: repaired['decks'][deck_kind]['sections']
                      for deck_kind in ('intro_deck', 'pitch_deck')},
            'review_model': review['review_model']}
        review_base = json.loads(json.dumps(review_base, ensure_ascii=False))
        (re_root / 'material_review_request.json').write_text(json.dumps(
            _re_review_request(review_base), ensure_ascii=False))
        for number in range(1, 3):
            if installed_models().get(name) != pin['digest']:
                raise ValueError('Installed local re-review model digest changed')
            (re_root / 'material_review_budget.json').write_text(json.dumps(
                {'seconds': 105}))
            review_result = review_materials(re_root, LocalModel(name,
                thinking=False, max_tokens=1200, context_tokens=16384,
                temperature=0))
            review_passes.append({'pass': number, 'state': review_result['state'],
                                  'reason': review_result.get('reason')})
            (re_root / 'passes.json').write_text(json.dumps(review_passes))
            if review_result['state'] != 'needs_resume':
                break
        (re_root / 'material_review_result.json').write_text(json.dumps(
            review_result, ensure_ascii=False))
        if digest(review_materials(re_root, NoInference(name))) != digest(review_result):
            raise ValueError('Re-review differs from exact recorded raw response')
    summary = {'state': ('blocked' if repaired['state'] not in {
                         'accepted', 'disputed_without_change'} else
                         review_result['state']),
               'repair_state': repaired['state'],
               'repair_reason': repaired.get('reason'),
               'repair_response_id': repaired.get('response_id'),
               're_review_state': review_result['state'] if review_result else 'not_run',
               're_review_reason': review_result.get('reason') if review_result else None,
               're_review_passes': len(review_passes),
               're_review_response_id': review_result.get('response_id') if review_result else None,
               'acceptance_scope': 'public_synthetic_diagnostic_only',
               'investor_material_accepted': False}
    (output / 'result.json').write_text(json.dumps(summary, ensure_ascii=False,
                                            indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('material_dir', type=Path)
    parser.add_argument('review_dir', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--operator-attested-public-or-synthetic', action='store_true')
    args = parser.parse_args()
    print(json.dumps(evaluate(args.material_dir, args.review_dir, args.output,
        operator_attested=args.operator_attested_public_or_synthetic), indent=2))


if __name__ == '__main__':
    main()
