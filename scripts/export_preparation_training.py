"""Export original teaching examples for experimental local SFT.

This does not train weights. Evaluation cases are never exported into training.
No live company data is accessed. The tiny seed set is not release-quality data.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.company_brief import CONTRACTS, INSTRUCTIONS
from agents.investment_case import WorkProduct, FitNarrative, WORK
from agents.investment_practice import ROOT


def export(output):
    source = ROOT / 'teaching_examples.json'
    data = json.loads(source.read_text())
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    split_rows = {'train':[], 'validation':[]}
    ids, inputs = set(), set()
    for example in data['examples']:
        key = hashlib.sha256(json.dumps(example['input'], sort_keys=True).encode()).hexdigest()
        if example['id'] in ids or key in inputs:
            raise ValueError('Duplicate example or input across training/validation splits')
        ids.add(example['id']); inputs.add(key)
        contract = FitNarrative if example['stage']=='company suitability' else CONTRACTS.get(example['stage'], WorkProduct)
        contract.model_validate(example['response'])
        allowed = {e['id'] for e in example['input'].get('evidence',example['input'].get('sources',[]))}
        if not set(example['response']['evidence_ids']) <= allowed:
            raise ValueError('Unsupported teaching-example citation')
        split_rows[example['split']].append({'messages':[
            {'role':'system','content':{**INSTRUCTIONS, **WORK, 'company suitability':'Assess whether initial company research and fundraising-preparation work is useful, not whether to invest capital. Cite company evidence and state the specific next deliverable.'}[example['stage']]},
            {'role':'user','content':json.dumps(example['input'])},
            {'role':'assistant','content':json.dumps(example['response'])}]})
    for split, rows in split_rows.items():
        (target / ('valid.jsonl' if split=='validation' else 'train.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows))
    manifest = {'counts':{s:len(rows) for s,rows in split_rows.items()}, 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                'provenance':data['provenance'], 'weights_trained':False, 'expert_reviewed':False,
                'held_out_cases_exported':False, 'release_suitable':False}
    (target/'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    print(json.dumps(export(parser.parse_args().output), indent=2))
