"""Two private, read-only text classifications; never dispatch an action."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat
from threading import BoundedSemaphore
import time

from delivery.artifacts import artifact_root
from delivery.ingestion import _write_new
from delivery.isolation import run_private
from delivery.storage import scoped_directory, scope_component
from schemas import new_id
from security.identity import IDLE_SECONDS, token_hash

CONTRACT = 'private-text-classification-v1'
MODEL = 'llama3.2:3b'
CONTEXT, OUTPUT = 8192, 512
PROJECT = Path(__file__).resolve().parents[1]
_SLOT = BoundedSemaphore(1)


def _read_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1024 * 1024:
            raise ValueError('Classification evidence exceeds its file limit')
        raw = stream.read(1024 * 1024 + 1)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate classification JSON property')
            result[key] = value
        return result
    def invalid(value): raise ValueError('Non-finite classification JSON value')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop(); count += 1
        if count > 10000 or depth > 32 or type(item) is float and not math.isfinite(item):
            raise ValueError('Classification evidence exceeds its structure limit')
        if isinstance(item, dict): pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list): pending.extend((v, depth + 1) for v in item)
    return value, hashlib.sha256(raw).hexdigest()


def _session(store, identity):
    now = time.time()
    if identity is None or not store.conn.execute('''SELECT 1 FROM auth_sessions s
        JOIN auth_users u ON u.id=s.user_id
        JOIN auth_memberships m ON m.user_id=s.user_id AND m.tenant_id=s.tenant_id
        WHERE s.user_id=? AND s.tenant_id=? AND s.csrf=? AND s.revoked=0
        AND s.expires>? AND s.touched>? AND m.active=1 AND u.disabled=0''',
        (identity.user_id, identity.tenant_id, token_hash(identity.csrf), now, now-IDLE_SECONDS)).fetchone():
        raise PermissionError('Private classification session is no longer active')


def _model_request(operation, text, deal):
    from agents.inference.local_ollama import effective_chat_options
    if operation == 'prompt':
        from main import build_router_request
        request = build_router_request(text)
        actions = ['source_leads', 'screen_deal', 'unknown']
    elif operation == 'directive' and deal is not None:
        from agents.core.planner_agent import build_directive_request, VALID_ACTIONS
        request = build_directive_request(deal, text)
        actions = VALID_ACTIONS[deal.status]
    else:
        raise ValueError('Unsupported private classification operation')
    if request['model'] != MODEL:
        raise ValueError('Private classifier model requires a new explicit qualification')
    request['format']['additionalProperties'] = False
    request['format']['properties']['action']['enum'] = actions
    request['format']['properties']['reasoning']['maxLength'] = 512
    request['options'] = effective_chat_options(MODEL, {'temperature': 0.0, 'num_ctx': CONTEXT, 'num_predict': OUTPUT})
    request.update(keep_alive=0.0, stream=False, tools=[])
    if sum(len(m['content'].encode()) for m in request['messages']) + OUTPUT + 256 > CONTEXT:
        raise ValueError('Classification input exceeds its complete-context bound')
    return request


def _project(operation, text, deal, response):
    from agents.inference.local_models import validate_full_context_receipt
    if (not isinstance(response, dict) or response.get('model') != MODEL
            or response.get('done') is not True or response.get('done_reason') != 'stop'
            or type(response.get('eval_count')) is not int or not 0 < response['eval_count'] <= OUTPUT):
        raise ValueError('Private classification has no matching complete model response')
    validate_full_context_receipt({'prompt_tokens': response.get('prompt_eval_count'),
                                  'context_tokens': CONTEXT, 'max_tokens': OUTPUT})
    message = response.get('message')
    if (not isinstance(message, dict) or message.get('thinking') or message.get('tool_calls')
            or not isinstance(message.get('content'), str) or len(message['content'].encode()) > 32768):
        raise ValueError('Private classification returned an invalid message')
    # Parse the exact JSON body; no fence repair, extraction or default action.
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise ValueError('Duplicate classifier decision property')
            value[key] = item
        return value
    decision = json.loads(message['content'], object_pairs_hook=unique)
    allowed = {'action', 'reasoning', 'sector_keyword', 'location_filter'} if operation == 'prompt' else {'action', 'reasoning', 'target_field'}
    if (type(decision) is not dict or set(decision) - allowed
            or not {'action', 'reasoning'} <= set(decision)
            or type(decision['action']) is not str or type(decision['reasoning']) is not str
            or not 0 < len(decision['reasoning']) <= 512
            or any(value is not None and (type(value) is not str or len(value) > 128)
                   for key, value in decision.items() if key not in {'action', 'reasoning'})):
        raise ValueError('Private classifier decision does not match its strict schema')
    if operation == 'prompt':
        from main import project_router_response
        if decision['action'] not in {'source_leads', 'screen_deal', 'unknown'}:
            raise ValueError('Private router proposed an unknown action')
        return project_router_response(text, response)
    from agents.core.planner_agent import project_directive_response, EXTRACTION_SCHEMA_FIELDS
    if decision.get('target_field') is not None and decision['target_field'] not in EXTRACTION_SCHEMA_FIELDS:
        raise ValueError('Private directive proposed an unknown extraction field')
    return project_directive_response(deal, response, strict=True)


def classify_private(store, operation, text, *, deal=None):
    started = time.monotonic()
    identity = getattr(store, 'authenticated_identity', None)
    _session(store, identity)
    if type(text) is not str or not 0 < len(text.encode()) <= 4096:
        raise ValueError('Private classification text must contain 1 to 4096 UTF-8 bytes')
    if operation not in {'prompt', 'directive'} or operation == 'directive' and (deal is None or deal.tenant_id != identity.tenant_id):
        raise ValueError('Unsupported private classification scope')
    if not _SLOT.acquire(blocking=False): raise RuntimeError('Private classifier is busy')
    try:
        model_request = _model_request(operation, text, deal)
        root = artifact_root(); scope = deal.id if deal is not None else 'prompt-router'
        identifier = new_id('classification')
        with scoped_directory(root, identity.tenant_id, scope, create=True) as directory:
            os.mkdir(identifier, mode=0o700, dir_fd=directory)
        job = root / scope_component(identity.tenant_id) / scope_component(scope) / identifier
        request = {'contract': CONTRACT, 'operation': operation, 'tenant_id': identity.tenant_id,
                   'actor_id': identity.user_id, 'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
                   'deal_status': deal.status.value if deal is not None else None,
                   'model_request': model_request}
        frozen = _write_new(job/'request.json', request)
        receipt = {'contract': CONTRACT, 'request_sha256': frozen, 'state': 'started'}
        try:
            remaining = 120 - (time.monotonic() - started)
            if remaining <= 0: raise TimeoutError('Private classifier deadline expired before execution')
            run_private([__import__('sys').executable, '-I', '-B', PROJECT/'scripts/private_classification_worker.py'],
                        job, timeout=remaining, extra_read=(PROJECT/'agents', PROJECT/'schemas.py'), local_model=True)
            current, current_hash = _read_json(job/'request.json')
            response, response_hash = _read_json(job/'raw-response.json')
            outcome, _ = _read_json(job/'outcome.json')
            usage, usage_hash = _read_json(job/'usage.json')
            if (current_hash != frozen or current != request or type(outcome) is not dict or type(usage) is not dict
                    or set(outcome) != {'state', 'request_sha256', 'response_sha256', 'usage_sha256'}
                    or outcome.get('state') != 'complete'
                    or outcome.get('request_sha256') != frozen or outcome.get('response_sha256') != response_hash
                    or outcome.get('usage_sha256') != usage_hash
                    or any(type(usage.get(key)) is not int or usage[key] != value
                           for key, value in {'calls': 1, 'requests': 1, 'max_calls': 1, 'max_requests': 6}.items())
                    or type(usage.get('max_seconds')) not in (int, float) or usage['max_seconds'] != 110
                    or type(usage.get('elapsed_seconds')) not in (int, float)
                    or not 0 <= usage['elapsed_seconds'] <= 110):
                raise ValueError('Private classifier request, response or usage binding changed')
            result = _project(operation, text, deal, response)
            if time.monotonic() - started >= 120:
                raise TimeoutError('Private classifier exceeded its parent deadline')
            store.conn.execute('BEGIN IMMEDIATE')
            try:
                _session(store, identity)
                if deal is not None:
                    fresh = store.get_deal(identity.tenant_id, deal.id)
                    if fresh is None or fresh.status != deal.status:
                        raise ValueError('Deal changed during private classification')
                store.conn.commit()
            except Exception:
                store.conn.rollback()
                raise
            receipt.update(state='validated', response_sha256=response_hash, usage_sha256=usage_hash,
                           decision_sha256=_write_new(job/'decision.json', result.model_dump(mode='json')))
            return result
        except Exception as exc:
            receipt.update(state='failed', error_type=type(exc).__name__)
            raise
        finally:
            _write_new(job/'receipt.json', receipt)
    finally:
        _SLOT.release()
