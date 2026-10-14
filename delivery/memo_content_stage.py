"""Durable private rationale gate before room memo rendering.

The original accepted draft is immutable. A separate versioned directory records
local relation reviews, patches and exact re-review; saved passing output is
replayed without another inference call. Independent approval remains pending.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from agents.inference.model_authorship import digest
from agents.inference.model_routing import validate_local_model_name
from agents.research.investment_memo import Memo, Source
from agents.research import memo_content_repair as repair
from agents.research.memo_content_review_v2 import FRESH_CONTRACT as CONTRACT
from delivery.isolation import run_private

PROJECT = Path(__file__).resolve().parents[1]


def _write(path, value):
    temporary = path.with_name(path.name + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False)
    temporary.replace(path)


def _inventory():
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
        return {row['name']: row.get('digest') for row in json.load(response)['models']}


def _pins(profile, installed):
    roles = profile['profiles']
    author_role = 'author' if roles.get('author') else 'corrector'
    reviewer_role = 'challenge' if roles.get('challenge') else 'review'
    expected = profile.get('memo_role_model_digests') or {}
    result = {}
    for kind, role in (('author', author_role), ('review', reviewer_role)):
        name = roles[role]
        validate_local_model_name(name)
        value = installed.get(name)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError('Content gate requires installed pinned local roles')
        historical = expected.get(role)
        if role == 'author':
            historical = historical or profile.get('memo_author_model_digest')
        if role == 'review':
            historical = historical or profile.get('memo_causal_review_model_digest')
        if historical is not None and historical != value:
            raise ValueError('Content gate local model differs from original frozen role')
        result[kind] = {'name': name, 'digest': value}
    return result


def _load_revision(root):
    from scripts.evaluate_private_memo_content import load_revision
    return load_revision(root)


def content_gate_contract(review_version):
    if review_version == 3:
        return CONTRACT
    if review_version == 4:
        from agents.research.memo_content_review_v2 import SCOPE_CONTRACT
        return SCOPE_CONTRACT
    if review_version == 5:
        from agents.research.memo_content_review_v2 import BLIND_CONTRACT
        return BLIND_CONTRACT
    raise ValueError("Unknown memo content gate version")




def content_repair_contract(review_version, repair_contract=None):
    default = 'memo-content-repair-v4' if review_version in (4, 5) else None
    selected = repair_contract if repair_contract is not None else default
    if selected != default and not (review_version == 5 and selected in {'memo-content-repair-v5', 'memo-content-repair-v6'}):
        raise ValueError('Repair contract does not match memo content gate version')
    return selected


def _validate_blind_production_acceptance(root, revision):
    """Production blind review needs bounded execution plus current source-only proof."""
    history_file = root / 'content_passes.json'
    if not history_file.exists():
        raise ValueError('Blind production acceptance requires bounded pass history')
    history = json.loads(history_file.read_text())
    if not isinstance(history, list) or not 1 <= len(history) <= 3:
        raise ValueError('Blind production acceptance requires one to three passes')
    for number, row in enumerate(history, 1):
        allowed = {'accepted'} if number == len(history) else {'needs_resume', 'time_limit', 'worker_error'}
        if (not isinstance(row, dict) or set(row) != {'pass', 'state'} or
                type(row.get('pass')) is not int or row['pass'] != number or
                row.get('state') not in allowed):
            raise ValueError('Blind production acceptance has unresolved or invalid pass history')
    from agents.research.rationale_evidence import CONTRACT as source_contract
    from agents.research.memo_content_review_v2 import BLIND_CONTRACT
    contract = revision.get('review_contract', {})
    proof = contract.get('source_characterization', {}).get('result', {})
    if (contract.get('version') != BLIND_CONTRACT or
            proof.get('state') != 'accepted' or proof.get('contract') != source_contract):
        raise ValueError('Blind production acceptance requires current source characterization')


def run_content_pass(memo_root, accepted, sources, profile, *, timeout, review_version=3, repair_contract=None):
    """Return resume/block, or exact replayed revised memo and revision record."""
    started = time.monotonic()
    memo = Memo.model_validate(accepted['memo'])
    source_rows = [Source.model_validate(row).model_dump(mode='json') for row in sources]
    contract = content_gate_contract(review_version)
    author_contract = content_repair_contract(review_version, repair_contract)
    root = Path(memo_root) / f'content_v{review_version}'
    root.mkdir(mode=0o700, exist_ok=True)
    request_file = root / 'content_request.json'
    current_base = {'memo': memo.model_dump(mode='json'), 'sources': source_rows}
    installed = None
    if request_file.exists():
        request = json.loads(request_file.read_text())
        if (request.get('digest') != digest({key: value for key, value in request.items()
                                            if key != 'digest'}) or
                any(request.get(key) != value for key, value in current_base.items()) or
                request.get('review_contract', {}).get('version') != contract or
                request.get('author_pin', {}).get('repair_contract') !=
                author_contract):
            return {'state': 'blocked', 'reason': 'memo_content_request_changed'}
        try:
            _pins(profile, {request['author_pin']['name']: request['author_pin']['digest'],
                            request['review_contract']['model_name']: request['review_contract']['model_digest']})
        except (ValueError, KeyError, TypeError):
            return {'state': 'blocked', 'reason': 'memo_content_model_profile_invalid'}
        roles = profile['profiles']
        if (request['author_pin']['name'] != roles.get('author', roles['corrector']) or
                request['review_contract']['model_name'] != roles.get('challenge', roles['review'])):
            return {'state': 'blocked', 'reason': 'memo_content_roles_changed'}
    else:
        try:
            installed = _inventory()
            pins = _pins(profile, installed)
        except (OSError, TimeoutError):
            return {'state': 'needs_resume', 'reason': 'local_model_inventory_unavailable'}
        except (ValueError, KeyError, TypeError):
            return {'state': 'blocked', 'reason': 'memo_content_model_profile_invalid'}
        request = {**current_base,
                   'review_contract': {'version': contract, 'model_name': pins['review']['name'],
                                       'model_digest': pins['review']['digest']},
                   'author_pin': {**pins['author'], **({'repair_contract': author_contract} if author_contract else {})}}
        request['digest'] = digest(request)
        _write(request_file, request)
    result_file = root / 'content_result.json'
    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    if result.get('state') not in {'accepted', 'blocked'}:
        if timeout < 10:
            return {'state': 'needs_resume', 'reason': 'room_pass_time_limit'}
        if installed is None:
            try:
                installed = _inventory()
            except (OSError, TimeoutError, ValueError, KeyError, TypeError):
                return {'state': 'needs_resume', 'reason': 'local_model_inventory_unavailable'}
        if (installed.get(request['author_pin']['name']) != request['author_pin']['digest'] or
                installed.get(request['review_contract']['model_name']) !=
                request['review_contract']['model_digest']):
            return {'state': 'blocked', 'reason': 'memo_content_installed_model_changed'}
        history_file = root / 'content_passes.json'
        history = json.loads(history_file.read_text()) if history_file.exists() else []
        cap = 3  # Separate production content phase: three finite six-call passes.
        if len(history) >= cap:
            return {'state': 'blocked', 'reason': 'bounded_memo_content_passes_exhausted'}
        history.append({'pass': len(history) + 1, 'state': 'started'})
        _write(history_file, history)
        remaining = timeout - (time.monotonic() - started)
        if remaining < 10:
            history[-1]['state'] = 'time_limit'
            _write(history_file, history)
            return {'state': 'needs_resume', 'reason': 'room_pass_time_limit'}
        _write(root / 'content_budget.json', {'seconds': min(105, remaining - 8), 'max_calls': 6})
        try:
            run_private([sys.executable, PROJECT / 'scripts/private_memo_content_worker.py'],
                        root, timeout=remaining, extra_read=(PROJECT / 'agents', PROJECT / 'schemas.py'),
                        local_model=True)
            result = json.loads(result_file.read_text())
        except (TimeoutError, RuntimeError):
            history[-1]['state'] = 'worker_error'
            _write(history_file, history)
            return {'state': 'needs_resume', 'reason': 'private_memo_content_worker_interrupted'}
        history[-1]['state'] = result.get('state')
        _write(history_file, history)
    if result.get('state') != 'accepted':
        return {'state': 'blocked' if result.get('state') == 'blocked' else 'needs_resume',
                'reason': result.get('reason', 'next_bounded_content_review'),
                'phase': 'memo_content_review_pending',
                'content_revision_path': str(root), 'independent_review': 'pending'}
    revision = _load_revision(root)
    if review_version == 5:
        try:
            _validate_blind_production_acceptance(root, revision)
        except ValueError as exc:
            return {'state': 'blocked', 'reason': 'memo_content_production_proof_invalid',
                    'detail': str(exc)}
    revised, lineage = repair.replay_content_revision(memo, source_rows, revision)
    if result.get('final_memo_digest') != digest(revised.model_dump(mode='json')):
        return {'state': 'blocked', 'reason': 'memo_content_result_digest_changed'}
    return {'state': 'accepted', 'memo': revised.model_dump(mode='json'),
            'content_revision': revision, 'content_review': lineage,
            'content_revision_path': str(root), 'independent_review': 'pending',
            'content_review_version': review_version,
            **({'content_repair_contract': author_contract} if author_contract in {'memo-content-repair-v5', 'memo-content-repair-v6'} else {})}


def replay_content_gate(memo_root, accepted, sources, profile, *, review_version=3, repair_contract=None):
    """Read-only artifact-boundary check; never starts inference or a new gate."""
    contract = content_gate_contract(review_version)
    author_contract = content_repair_contract(review_version, repair_contract)
    root = Path(memo_root) / f'content_v{review_version}'
    request = json.loads((root / 'content_request.json').read_text())
    result = json.loads((root / 'content_result.json').read_text())
    source_rows = [Source.model_validate(row).model_dump(mode='json') for row in sources]
    if (request.get('digest') != digest({key: value for key, value in request.items() if key != 'digest'}) or
            request.get('memo') != Memo.model_validate(accepted['memo']).model_dump(mode='json') or
            request.get('sources') != source_rows or
            request.get('review_contract', {}).get('version') != contract or
            request.get('author_pin', {}).get('repair_contract') !=
            author_contract or
            result.get('state') != 'accepted'):
        raise ValueError('Material requires exact accepted memo content gate')
    roles = profile['profiles']
    if (request['author_pin']['name'] != roles.get('author', roles['corrector']) or
            request['review_contract']['model_name'] != roles.get('challenge', roles['review'])):
        raise ValueError('Material memo content roles differ from frozen profile')
    _pins(profile, {request['author_pin']['name']: request['author_pin']['digest'],
                    request['review_contract']['model_name']: request['review_contract']['model_digest']})
    revision = _load_revision(root)
    if review_version == 5:
        _validate_blind_production_acceptance(root, revision)
    revised, lineage = repair.replay_content_revision(accepted['memo'], source_rows, revision)
    if result.get('final_memo_digest') != digest(revised.model_dump(mode='json')):
        raise ValueError('Material memo content result differs from exact replay')
    return revised, revision, lineage
