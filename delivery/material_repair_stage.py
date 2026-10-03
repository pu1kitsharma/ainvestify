"""One exact local slide repair after a quote-bound semantic review block."""
from __future__ import annotations

import json
from pathlib import Path

from agents.inference.model_authorship import digest
from agents.inference.model_routing import validate_local_model_name
from agents.research.material_slides import replay_material_rows
from delivery.investment_memo_stage import memo_directory
from delivery.isolation import run_private
from delivery.material_stage import validate_material_checkpoint
from delivery.material_review_stage import (_installed_digest,
    validate_material_review_checkpoint)
from scripts.private_material_repair_worker import repair_materials


def _repair_request(job, memo, material, blocked_review, memo_root):
    exact = validate_material_checkpoint(job, memo, material)
    block = validate_material_review_checkpoint(job, memo, material,
        blocked_review, expected_state='blocked')
    finding = block['review']['findings'][0]
    kind = finding['deck']
    request = json.loads((memo_root / 'material_request.json').read_text())
    attempts = json.loads((memo_root / 'material_attempts.json').read_text())
    payload = {'kind': kind, 'input_revision': job['input_revision'],
               'source_hash': memo['source_hash'], 'memo_digest': exact['memo_digest'],
               'sections': request['sections']}
    authored = replay_material_rows(kind, payload, attempts, request['sections'],
                                    contract_version=request['replay_contracts'][kind])
    if authored['state'] != 'accepted':
        raise ValueError('Material repair requires a replayed structured deck')
    profile = json.loads((memo_root / 'model.json').read_text())
    name = profile['profiles'].get('corrector', profile['profiles']['draft'])
    validate_local_model_name(name)
    pin = {'name': name, 'digest': _installed_digest(name),
           'options': {'thinking': False, 'max_tokens': 1500,
                       'context_tokens': 16384, 'temperature': 0}}
    base = {'input_revision': job['input_revision'], 'source_hash': memo['source_hash'],
            'memo_digest': exact['memo_digest'], 'material_digest': digest(exact),
            'blocked_review_digest': digest(block), 'review_finding': finding,
            'target_deck': kind, 'target_slide_index': finding['slide_index'],
            'material_contract': request['replay_contracts'][kind],
            'target_deck_spec': authored['authored_spec'].model_dump(mode='json'),
            'original_decks': exact['decks'], 'memo_sections': memo['sections'],
            'repair_model': pin, 'repair_contract': 'review_dispute_v1'}
    base = json.loads(json.dumps(base, ensure_ascii=False))
    return {**base, 'digest': digest(base)}


class _NoInference:
    def __init__(self, name):
        self.name = name
    def generate_for_task(self, *args, **kwargs):
        raise AssertionError('Material repair replay must not call inference')


def validate_material_repair_checkpoint(job, memo, repair):
    original = repair['original_material']
    block = repair['blocked_review']
    memo_root = memo_directory(job)
    root = memo_root / 'material_repair'
    expected = _repair_request(job, memo, original, block, memo_root)
    if json.loads((root / 'material_repair_request.json').read_text()) != expected:
        raise ValueError('Material repair frozen inputs or model changed')
    recorded = json.loads((root / 'material_repair_result.json').read_text())
    replayed = repair_materials(root, _NoInference(expected['repair_model']['name']))
    if (digest(recorded) != digest(replayed) or
            replayed['state'] not in {'accepted', 'disputed_without_change'}):
        raise ValueError('Material repair is not an exact local model response')
    result = {'state': replayed['state'], 'source_hash': memo['source_hash'],
              'memo_digest': expected['memo_digest'], 'original_material': original,
              'blocked_review': block, 'request_digest': expected['digest'],
              'repair_response_id': replayed['response_id'], 'decks': replayed['decks'],
              'private_attempts_path': str(root / 'material_repair_attempts.json')}
    result = json.loads(json.dumps(result, ensure_ascii=False))
    if digest(repair) != digest(result):
        raise ValueError('Material repair checkpoint differs from recorded local response')
    return result


def run_material_repair_pass(job, memo, material, blocked_review, *, timeout):
    memo_root = memo_directory(job)
    root = memo_root / 'material_repair'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    request = _repair_request(job, memo, material, blocked_review, memo_root)
    path = root / 'material_repair_request.json'
    if path.exists():
        if json.loads(path.read_text()) != request:
            raise ValueError('Material repair frozen inputs or model changed')
    else:
        path.write_text(json.dumps(request, ensure_ascii=False))
    (root / 'material_repair_budget.json').write_text(json.dumps({
        'seconds': max(1, min(105, timeout - 8))}))
    project = Path(__file__).resolve().parents[1]
    run_private([__import__('sys').executable,
        project / 'scripts/private_material_repair_worker.py'], root, timeout=timeout,
        extra_read=(project / 'agents', project / 'schemas.py'), local_model=True)
    saved = json.loads((root / 'material_repair_result.json').read_text())
    if saved['state'] not in {'accepted', 'disputed_without_change'}:
        return {'state': saved['state'], 'reason': saved.get('reason', 'repair_incomplete')}
    checkpoint = {'state': saved['state'], 'source_hash': memo['source_hash'],
                  'memo_digest': request['memo_digest'],
                  'original_material': material, 'blocked_review': blocked_review,
                  'request_digest': request['digest'],
                  'repair_response_id': saved['response_id'], 'decks': saved['decks'],
                  'private_attempts_path': str(root / 'material_repair_attempts.json')}
    return validate_material_repair_checkpoint(job, memo, checkpoint)
