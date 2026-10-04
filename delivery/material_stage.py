"""Exact replay gateway for local-model-authored intro and pitch drafts."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from agents.inference.model_authorship import digest
from agents.inference.model_routing import validate_local_model_name
from agents.research.material_slides import replay_material_rows, render_sections
from delivery.investment_memo_stage import memo_directory
from delivery.isolation import run_private


TASKS = ('intro_deck', 'pitch_deck')
RECORDED_DRAFT_CONTRACTS = (
    'structured', 'structured_v2', 'structured_v3', 'structured_v4',
    'structured_v5', 'evidence_v7', 'evidence_v8', 'purpose_v1',
    'purpose_v2', 'purpose_v3', 'purpose_v4', 'purpose_v5', 'purpose_v6',
    'purpose_v7', 'purpose_v8', 'purpose_v9', 'purpose_v10',
    'purpose_v11', 'purpose_v12', 'purpose_v13',
)
FRESH_DRAFT_CONTRACT = 'purpose_v11'
MATERIAL_AUTHOR_OPTIONS = {'thinking': False, 'max_tokens': 2600,
                           'context_tokens': 16384, 'temperature': 0}


class LocalMaterialModelInventoryUnavailable(RuntimeError):
    pass


def _installed_material_digest(name):
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            installed = {row['name']: row.get('digest') for row in json.load(response)['models']}
    except (OSError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise LocalMaterialModelInventoryUnavailable('Local material model inventory unavailable') from exc
    value = installed.get(name)
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError('Requested local material author is not installed')
    return value


def _draft_model_pin(request, profile):
    pin = request.get('draft_model')
    if pin is None:
        return profile['profiles']['draft']
    if (not isinstance(pin, dict) or set(pin) != {'name', 'digest', 'options'} or
            pin['options'] != MATERIAL_AUTHOR_OPTIONS or
            not isinstance(pin['digest'], str) or len(pin['digest']) != 64):
        raise ValueError('Invalid frozen material author pin')
    validate_local_model_name(pin['name'])
    return pin['name']


def _accepted_memo_for_material(root, memo):
    """Replay the accepted memo before freezing any copied sentence options."""
    from agents.research.investment_memo import Source, renderable_sections

    result = json.loads((root / 'result.json').read_text())
    request = json.loads((root / 'request.json').read_text())
    attempts = json.loads((root / 'attempts.json').read_text())
    profile = json.loads((root / 'model.json').read_text())
    if result.get('state') != 'accepted':
        raise ValueError('Purpose v12 requires an accepted recorded memo')
    sections = renderable_sections(result['accepted'],
        [Source.model_validate(row) for row in request['sources']], attempts,
        projection=profile.get('section_projection'))
    if [list(row) for row in sections] != memo['sections']:
        raise ValueError('Material memo options differ from exact raw replay')
    return result['accepted']


def _financial_unknown_candidates(root, memo):
    from agents.research.material_purpose_draft import financial_unknown_candidates
    return financial_unknown_candidates(_accepted_memo_for_material(root, memo))


def _memo_sentence_candidates(root, memo):
    from agents.research.material_purpose_draft import memo_sentence_candidates
    return memo_sentence_candidates(_accepted_memo_for_material(root, memo))


def _recorded_versions(saved_request):
    versions = saved_request.get('replay_contracts')
    if (not isinstance(versions, dict) or set(versions) != set(TASKS) or
            any(versions[kind] not in RECORDED_DRAFT_CONTRACTS for kind in TASKS) or
            versions['intro_deck'] != versions['pitch_deck']):
        raise ValueError('Unknown material replay contract')
    return versions


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
    versions = _recorded_versions(saved_request)
    request_base = {**base, 'replay_contracts': versions}
    if 'draft_model' in saved_request:
        request_base['draft_model'] = saved_request['draft_model']
    if versions['intro_deck'] in {'purpose_v12', 'purpose_v13'}:
        request_base['financial_unknown_candidates'] = _financial_unknown_candidates(root, memo)
    elif 'financial_unknown_candidates' in saved_request:
        raise ValueError('Historical material request has unexpected financial candidates')
    if versions['intro_deck'] == 'purpose_v13':
        request_base['memo_sentence_candidates'] = _memo_sentence_candidates(root, memo)
    elif 'memo_sentence_candidates' in saved_request:
        raise ValueError('Historical material request has unexpected sentence candidates')
    request = {**request_base, 'digest': digest(request_base)}
    if saved_request != request:
        raise ValueError('Accepted memo changed after material drafting began')
    profile = json.loads((root / 'model.json').read_text())
    model_name = _draft_model_pin(saved_request, profile)
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
        if versions[kind] in {'purpose_v12', 'purpose_v13'}:
            payload['financial_unknown_candidates'] = request_base['financial_unknown_candidates']
        if versions[kind] == 'purpose_v13':
            payload['memo_sentence_candidates'] = request_base['memo_sentence_candidates']
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


def run_material_pass(job, memo, *, timeout, draft_contract=FRESH_DRAFT_CONTRACT,
                      draft_model=None):
    if memo.get('state') != 'accepted' or not memo.get('source_hash'):
        raise ValueError('Material drafting requires an accepted source-bound memo')
    project = Path(__file__).resolve().parents[1]
    root = memo_directory(job)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    memo_digest = _memo_digest(memo)
    base = {'input_revision': job['input_revision'], 'source_hash': memo['source_hash'],
            'memo_digest': memo_digest, 'sections': memo['sections']}
    if draft_contract not in {FRESH_DRAFT_CONTRACT, 'structured_v5', 'purpose_v3', 'purpose_v4',
                              'purpose_v5', 'purpose_v6', 'purpose_v7',
                              'purpose_v8', 'purpose_v9', 'purpose_v10',
                              'purpose_v11', 'purpose_v12', 'purpose_v13'}:
        raise ValueError('Unknown fresh material draft contract')
    request_base = {**base, 'replay_contracts': {
        kind: draft_contract for kind in TASKS}}
    request_file = root / 'material_request.json'
    requested_model = draft_model or os.environ.get('LOCAL_MATERIAL_DRAFT_MODEL')
    if requested_model:
        validate_local_model_name(requested_model)
    if request_file.exists():
        existing = json.loads(request_file.read_text())
        versions = _recorded_versions(existing)
        old_base = {**base, 'replay_contracts': versions}
        if versions['intro_deck'] in {'purpose_v12', 'purpose_v13'}:
            old_base['financial_unknown_candidates'] = _financial_unknown_candidates(root, memo)
        elif 'financial_unknown_candidates' in existing:
            raise ValueError('Historical material request has unexpected financial candidates')
        if versions['intro_deck'] == 'purpose_v13':
            old_base['memo_sentence_candidates'] = _memo_sentence_candidates(root, memo)
        elif 'memo_sentence_candidates' in existing:
            raise ValueError('Historical material request has unexpected sentence candidates')
        if 'draft_model' in existing:
            old_base['draft_model'] = existing['draft_model']
        profile = json.loads((root / 'model.json').read_text())
        frozen_name = _draft_model_pin(existing, profile)
        if requested_model and requested_model != frozen_name:
            raise ValueError('Material author model changed after request freeze; new immutable branch required')
        if (existing.get('draft_model') and
                _installed_material_digest(frozen_name) != existing['draft_model']['digest']):
            raise ValueError('Installed material author differs from frozen model digest')
        request = {**old_base, 'digest': digest(old_base)}
        if existing != request:
            raise ValueError('Accepted memo changed after material drafting began')
    else:
        if (root / 'material_attempts.json').exists():
            raise ValueError('Saved material attempts lack a frozen request')
        if draft_contract in {'purpose_v12', 'purpose_v13'}:
            request_base['financial_unknown_candidates'] = _financial_unknown_candidates(root, memo)
        if draft_contract == 'purpose_v13':
            request_base['memo_sentence_candidates'] = _memo_sentence_candidates(root, memo)
        if requested_model:
            request_base['draft_model'] = {'name': requested_model,
                'digest': _installed_material_digest(requested_model),
                'options': MATERIAL_AUTHOR_OPTIONS}
        request = {**request_base, 'digest': digest(request_base)}
        temporary = request_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(request, ensure_ascii=False))
        temporary.replace(request_file)
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
