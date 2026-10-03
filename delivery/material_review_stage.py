"""Private local semantic review gate before investor draft rendering."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from agents.inference.model_authorship import digest
from agents.inference.model_routing import validate_local_model_name
from delivery.investment_memo_stage import memo_directory
from delivery.isolation import run_private
from delivery.material_stage import validate_material_checkpoint
from scripts.private_material_review_worker import review_materials


def _installed_digest(name):
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
        rows = json.load(response)['models']
    value = next((row.get('digest') for row in rows if row.get('name') == name), None)
    if not value:
        raise ValueError('Pinned local material reviewer is not installed')
    return value


def _review_request(job, memo, material, memo_root, *, repaired=False,
                    review_contract='semantic_v8'):
    if repaired:
        from delivery.material_repair_stage import validate_material_repair_checkpoint
        exact = validate_material_repair_checkpoint(job, memo, material)
    else:
        exact = validate_material_checkpoint(job, memo, material)
    profile = json.loads((memo_root / 'model.json').read_text())
    name = profile['profiles'].get('review', profile['profiles']['draft'])
    validate_local_model_name(name)
    pin = {'name': name, 'digest': _installed_digest(name),
           'options': {'thinking': False, 'max_tokens': 1200,
                       'context_tokens': 16384, 'temperature': 0}}
    base = {'input_revision': job['input_revision'], 'source_hash': memo['source_hash'],
            'memo_digest': exact['memo_digest'], 'material_digest': digest(exact),
            'memo_sections': memo['sections'],
            'decks': {kind: exact['decks'][kind]['sections']
                      for kind in ('intro_deck', 'pitch_deck')},
            'review_model': pin}
    if review_contract is not None:
        base['review_contract'] = review_contract
    base = json.loads(json.dumps(base, ensure_ascii=False))
    return {**base, 'digest': digest(base)}


def _recorded_review_contract(path):
    if not path.exists():
        return 'semantic_v8'
    recorded = json.loads(path.read_text())
    contract = recorded.get('review_contract')
    if contract not in (None, 'semantic_v2', 'semantic_v3', 'semantic_v4', 'semantic_v5', 'semantic_v6', 'semantic_v7', 'semantic_v8'):
        raise ValueError('Unknown recorded material review contract')
    return contract


class _NoInference:
    def __init__(self, name):
        self.name = name
    def generate_for_task(self, *args, **kwargs):
        raise AssertionError('Material review checkpoint must not call inference')


def validate_material_review_checkpoint(job, memo, material, review=None, *,
                                        expected_state='accepted', repaired=False):
    memo_root = memo_directory(job)
    root = memo_root / 'material_re_review' if repaired else memo_root
    path = root / 'material_review_request.json'
    expected = _review_request(job, memo, material, memo_root, repaired=repaired,
        review_contract=_recorded_review_contract(path))
    if json.loads(path.read_text()) != expected:
        raise ValueError('Material review frozen memo, deck, or model changed')
    recorded = json.loads((root / 'material_review_result.json').read_text())
    replayed = review_materials(root, _NoInference(expected['review_model']['name']))
    if recorded != replayed or replayed['state'] != expected_state or not replayed.get('response_id'):
        raise ValueError('Material review is not an exact local response of required state')
    result = {'state': expected_state, 'response_id': replayed['response_id'],
              'request_digest': expected['digest'],
              'review': replayed['review'],
              'private_attempts_path': str(root / 'material_review_attempts.json')}
    if review is not None and review != result:
        raise ValueError('Material review checkpoint differs from recorded response')
    return result


def run_material_review_pass(job, memo, material, *, timeout, repaired=False):
    memo_root = memo_directory(job)
    root = memo_root / 'material_re_review' if repaired else memo_root
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / 'material_review_request.json'
    request = _review_request(job, memo, material, memo_root, repaired=repaired,
        review_contract=_recorded_review_contract(path))
    if path.exists():
        if json.loads(path.read_text()) != request:
            raise ValueError('Material review frozen memo, deck, or model changed')
    else:
        path.write_text(json.dumps(request, ensure_ascii=False))
    (root / 'material_review_budget.json').write_text(json.dumps({
        'seconds': max(1, min(105, timeout - 8))}))
    project = Path(__file__).resolve().parents[1]
    run_private([__import__('sys').executable, project / 'scripts/private_material_review_worker.py'],
                root, timeout=timeout, extra_read=(project / 'agents', project / 'schemas.py'),
                local_model=True)
    result = json.loads((root / 'material_review_result.json').read_text())
    if result['state'] != 'accepted':
        if result['state'] == 'blocked' and result.get('response_id'):
            return validate_material_review_checkpoint(job, memo, material,
                expected_state='blocked', repaired=repaired)
        return {'state': result['state'], 'reason': result.get('reason', 'review_incomplete'),
                'request_digest': request['digest']}
    return validate_material_review_checkpoint(job, memo, material, repaired=repaired)
