"""Exact replay gateway for local-model-authored intro and pitch drafts."""
from __future__ import annotations

import json
from pathlib import Path

from agents.inference.model_authorship import digest
from agents.inference.model_routing import validate_local_model_name
from agents.research.material_slides import replay_material_rows, render_sections
from delivery.investment_memo_stage import memo_directory
from delivery.isolation import run_private


TASKS = ('intro_deck', 'pitch_deck')


def _memo_digest(memo):
    return digest({key: memo.get(key) for key in (
        'sections', 'recommendation', 'source_hash', 'part_a_response_id',
        'part_b_response_id', 'review_response_id')})


def validate_material_checkpoint(job, memo, material=None):
    """Replay accepted specs before rendering, without calling inference."""
    if memo.get('state') != 'accepted' or not memo.get('source_hash'):
        raise ValueError('Material drafting requires an accepted source-bound memo')
    root = memo_directory(job)
    memo_digest = _memo_digest(memo)
    base = {'input_revision': job['input_revision'], 'source_hash': memo['source_hash'],
            'memo_digest': memo_digest, 'sections': memo['sections']}
    request_file = root / 'material_request.json'
    saved_request = json.loads(request_file.read_text())
    versions = saved_request.get('replay_contracts')
    if versions not in ({'intro_deck': 'structured', 'pitch_deck': 'structured'},
                        {'intro_deck': 'structured_v2', 'pitch_deck': 'structured_v2'},
                        {'intro_deck': 'structured_v3', 'pitch_deck': 'structured_v3'},
                        {'intro_deck': 'structured_v4', 'pitch_deck': 'structured_v4'},
                        {'intro_deck': 'structured_v5', 'pitch_deck': 'structured_v5'}):
        raise ValueError('Unknown material replay contract')
    request_base = {**base, 'replay_contracts': versions}
    request = {**request_base, 'digest': digest(request_base)}
    if saved_request != request:
        raise ValueError('Accepted memo changed after material drafting began')
    profile = json.loads((root / 'model.json').read_text())
    model_name = profile['profiles']['draft']
    validate_local_model_name(model_name)
    result = json.loads((root / 'material_result.json').read_text())
    if result['state'] != 'accepted':
        raise ValueError('Saved material result is not accepted')
    if result.get('source_hash') != memo['source_hash'] or result.get('memo_digest') != memo_digest:
        raise ValueError('Material result scope changed')
    attempts = json.loads((root / 'material_attempts.json').read_text())
    decks = {}
    for kind in TASKS:
        payload = {**base, 'kind': kind}
        replayed = replay_material_rows(kind, payload, attempts, memo['sections'],
                                        model_name=model_name,
                                        contract_version=versions[kind])
        if (replayed['state'] != 'accepted' or
                replayed['response_ids'] != result['decks'][kind]['response_ids'] or
                replayed['response_ids'][-1] != result['decks'][kind]['response_id']):
            raise ValueError('Material response is not bound to frozen model and inputs')
        rendered = render_sections(replayed['spec'], memo['sections'])
        if [list(section) for section in rendered] != result['decks'][kind]['sections']:
            raise ValueError('Material section projection differs from recorded model response')
        decks[kind] = {'response_id': replayed['response_ids'][-1],
                       'response_ids': replayed['response_ids'], 'sections': rendered}
    if decks['intro_deck']['sections'] == decks['pitch_deck']['sections']:
        raise ValueError('Local model returned duplicate intro and pitch decks')
    expected = {'state': 'accepted', 'source_hash': memo['source_hash'],
            'memo_digest': memo_digest, 'decks': decks,
            'private_attempts_path': str(root / 'material_attempts.json')}
    if material is not None and material != expected:
        raise ValueError('Material checkpoint differs from recorded local responses')
    return expected


def run_material_pass(job, memo, *, timeout):
    if memo.get('state') != 'accepted' or not memo.get('source_hash'):
        raise ValueError('Material drafting requires an accepted source-bound memo')
    project = Path(__file__).resolve().parents[1]
    root = memo_directory(job)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    memo_digest = _memo_digest(memo)
    base = {'input_revision': job['input_revision'], 'source_hash': memo['source_hash'],
            'memo_digest': memo_digest, 'sections': memo['sections']}
    request_base = {**base, 'replay_contracts': {
        'intro_deck': 'structured_v5', 'pitch_deck': 'structured_v5'}}
    request = {**request_base, 'digest': digest(request_base)}
    request_file = root / 'material_request.json'
    if request_file.exists():
        existing = json.loads(request_file.read_text())
        if existing.get('replay_contracts') in (
                {'intro_deck': 'structured', 'pitch_deck': 'structured'},
                {'intro_deck': 'structured_v2', 'pitch_deck': 'structured_v2'},
                {'intro_deck': 'structured_v3', 'pitch_deck': 'structured_v3'},
                {'intro_deck': 'structured_v4', 'pitch_deck': 'structured_v4'}):
            old_base = {**base, 'replay_contracts': existing['replay_contracts']}
            request = {**old_base, 'digest': digest(old_base)}
        if existing != request:
            raise ValueError('Accepted memo changed after material drafting began')
    else:
        request_file.write_text(json.dumps(request, ensure_ascii=False))
    (root / 'material_budget.json').write_text(json.dumps({
        'seconds': max(1, min(105, timeout - 8))}))
    run_private([__import__('sys').executable, project / 'scripts/private_material_worker.py'],
                root, timeout=timeout, extra_read=(project / 'agents', project / 'schemas.py'),
                local_model=True)
    result = json.loads((root / 'material_result.json').read_text())
    if result['state'] != 'accepted':
        return {'state': result['state'], 'reason': result.get('reason', 'materials_incomplete'),
                'source_hash': memo['source_hash'], 'memo_digest': memo_digest}
    return validate_material_checkpoint(job, memo)
