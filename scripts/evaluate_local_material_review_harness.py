"""Public/synthetic-only local semantic review of frozen material diagnostics."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pptx import Presentation

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from scripts.evaluate_local_memo_harness import installed_models
from scripts.private_material_review_worker import review_materials


ROOT = Path(__file__).resolve().parents[1]
MATERIAL_ROOT = ROOT / 'runtime_qualification/local_material_harness'
OUTPUT_ROOT = ROOT / 'runtime_qualification/local_material_review_harness'


def _slides(path):
    presentation = Presentation(str(path))
    result = []
    for slide in presentation.slides:
        text = [shape.text.strip() for shape in slide.shapes
                if shape.has_text_frame and shape.text.strip()]
        if len(text) < 5 or text[0] != 'DRAFT • NOT APPROVED FOR INVESTOR DISTRIBUTION':
            raise ValueError('Material diagnostic editable slide structure changed')
        notes = text.index('SOURCE NOTES')
        if notes <= 2:
            raise ValueError('Material diagnostic slide body is missing')
        result.append([text[1], '\n'.join(text[2:notes]), '', 'diagnostic'])
    return result


def evaluate(material_dir: Path, output: Path, *, operator_attested=False):
    if not operator_attested:
        raise ValueError('Public or synthetic material bytes require operator attestation')
    if not material_dir.resolve().is_relative_to(MATERIAL_ROOT.resolve()):
        raise ValueError('Material diagnostic must be under its allowlisted root')
    if not output.resolve().is_relative_to(OUTPUT_ROOT.resolve()) or output.resolve() == OUTPUT_ROOT.resolve():
        raise ValueError('Review diagnostic must be under its output root')
    report = json.loads((material_dir / 'result.json').read_text())
    if (report.get('state') != 'accepted' or
            report.get('acceptance_scope') != 'public_synthetic_diagnostic_only' or
            report.get('investor_material_accepted') is not False):
        raise ValueError('Material diagnostic lacks a historical accepted synthetic result')
    for stem in ('intro', 'pitch', 'memo'):
        for extension, key in (('pptx' if stem != 'memo' else 'docx', 'editable_sha256'),
                               ('pdf', 'pdf_sha256')):
            actual = hashlib.sha256((material_dir / f'{stem}.{extension}').read_bytes()).hexdigest()
            if actual != report['pair_reports'][stem][key]:
                raise ValueError('Material diagnostic artifact hash changed')
    old_request = json.loads((material_dir / 'material_request.json').read_text())
    if old_request['digest'] != digest({key: value for key, value in old_request.items()
                                        if key != 'digest'}):
        raise ValueError('Material diagnostic request digest changed')
    profile = json.loads((material_dir / 'model.json').read_text())
    name = profile['profiles']['draft']
    model_digest = installed_models().get(name)
    if not model_digest:
        raise ValueError('Installed local reviewer digest is unavailable')
    pin = {'name': name, 'digest': model_digest,
           'options': {'thinking': False, 'max_tokens': 1200,
                       'context_tokens': 16384, 'temperature': 0}}
    decks = {kind: _slides(material_dir / f'{stem}.pptx') for kind, stem in
             (('intro_deck', 'intro'), ('pitch_deck', 'pitch'))}
    base = {'review_contract': 'semantic_v8',
            'input_revision': old_request['input_revision'],
            'source_hash': old_request['source_hash'],
            'memo_digest': old_request['memo_digest'],
            'material_digest': digest({'request': old_request['digest'],
                'pair_reports': report['pair_reports']}),
            'memo_sections': old_request['sections'], 'decks': decks,
            'review_model': pin}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / 'material_review_request.json').write_text(json.dumps({**base,
        'digest': digest(base)}, ensure_ascii=False))
    passes = []
    result = None
    for number in range(1, 3):
        if installed_models().get(name) != model_digest:
            result = {'state': 'blocked', 'reason': 'installed_review_model_digest_changed'}
            break
        (output / 'material_review_budget.json').write_text(json.dumps({'seconds': 105}))
        model = LocalModel(name, thinking=False, max_tokens=1200,
                           context_tokens=16384, temperature=0)
        result = review_materials(output, model)
        passes.append({'pass': number, 'state': result['state'],
                       'reason': result.get('reason')})
        (output / 'passes.json').write_text(json.dumps(passes))
        if result['state'] != 'needs_resume':
            break
    if result.get('response_id'):
        class NoInference:
            def __init__(self, model_name):
                self.name = model_name
            def generate_for_task(self, *args, **kwargs):
                raise AssertionError('Review replay must not call inference')
        if review_materials(output, NoInference(name)) != result:
            raise ValueError('Review diagnostic differs from exact recorded model replay')
    summary = {'state': result['state'], 'reason': result.get('reason'),
               'passes': len(passes), 'response_id': result.get('response_id'),
               'review': result.get('review'),
               'acceptance_scope': 'public_synthetic_diagnostic_only',
               'investor_material_accepted': False}
    (output / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('material_dir', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--operator-attested-public-or-synthetic', action='store_true')
    args = parser.parse_args()
    print(json.dumps(evaluate(args.material_dir, args.output,
        operator_attested=args.operator_attested_public_or_synthetic), indent=2))


if __name__ == '__main__':
    main()
