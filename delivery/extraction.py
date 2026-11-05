"""One bounded private extraction, with exact response replay before persistence."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from threading import BoundedSemaphore
import time

from agents.core.extraction_agent import build_extraction_request, project_extraction_response
from agents.inference.local_ollama import effective_chat_options
from agents.inference.local_models import validate_full_context_receipt
from agents.inference.model_routing import validate_local_model_name
from delivery.artifacts import artifact_root
from delivery.isolation import run_private
from delivery.storage import read_source_bytes, scoped_directory, scope_component
from schemas import Document, ExtractionResult, new_id, utcnow

CONTRACT = 'private-deal-extraction-v1'
MAX_SECONDS = 120
MAX_JSON_BYTES = 8 * 1024**2
PROJECT = Path(__file__).resolve().parents[1]
_EXTRACTION_SLOT = BoundedSemaphore(1)  # Deployment has one API process.


class ExtractionConflict(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def write_json(path, value):
    raw = encoded(value)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('Private extraction JSON exceeds its byte limit')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return hashlib.sha256(raw).hexdigest()


def load_json(raw):
    if not 0 < len(raw) <= MAX_JSON_BYTES:
        raise ValueError('Private extraction JSON exceeds its byte limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate extraction JSON property')
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError('Nonfinite extraction JSON value')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 64 or count > 250000:
            raise ValueError('Private extraction JSON exceeds its structure limit')
        if type(item) is float and not math.isfinite(item):
            raise ValueError('Nonfinite extraction JSON value')
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def model_request(document, model, feedback):
    request = build_extraction_request(document, model, feedback)
    # The existing extraction estimator reserves 1,024 output tokens. Bound the
    # private API worker explicitly; direct CLI defaults remain unchanged.
    request['options']['num_predict'] = 1024
    request['options'] = effective_chat_options(model, request['options'])
    request.update(keep_alive=0.0, stream=False, tools=[])
    if model.startswith(('qwen3:', 'qwen3.5:')):
        request['think'] = False
    prompt = request['messages'][0]['content']
    if len(prompt) // 4 + 1024 > request['options']['num_ctx']:
        raise ValueError('Private extraction exceeds its complete-context estimate')
    return request


def validate_response(response, model, document, timestamp, call):
    if not isinstance(response, dict):
        raise ValueError('Unexpected private model response shape')
    expected = {model} if ':' in model else {model, model + ':latest'}
    message = response.get('message')
    if (response.get('model') not in expected or response.get('done') is not True
            or response.get('done_reason') != 'stop' or type(message) is not dict
            or message.get('role') != 'assistant' or type(message.get('content')) is not str
            or not 0 < len(message['content']) <= 512 * 1024 or message.get('tool_calls')):
        raise ValueError('Private model response is incomplete or has changed identity')
    if call.get('think') is False and message.get('thinking') not in (None, ''):
        raise ValueError('Private model returned unexpected thinking despite its frozen request')
    for key in ('prompt_eval_count', 'eval_count', 'total_duration', 'load_duration',
                'prompt_eval_duration', 'eval_duration'):
        if response.get(key) is not None and (type(response[key]) is not int or response[key] < 0):
            raise ValueError('Invalid private model usage receipt')
    validate_full_context_receipt({'prompt_tokens': response.get('prompt_eval_count'),
        'context_tokens': call['options']['num_ctx'], 'max_tokens': call['options']['num_predict']})
    if (type(response.get('eval_count')) is not int
            or not 0 < response['eval_count'] <= call['options']['num_predict']):
        raise ValueError('Private model token receipt exceeds the frozen context/output bounds')
    content = load_json(message['content'].encode('utf-8'))
    if (type(content) is not dict or any(type(content.get(key)) is not list
            or len(content[key]) > 256 for key in ('cap_table', 'funding_history'))):
        raise ValueError('Private model extraction exceeds its schema scope')
    projected = project_extraction_response(document, response, model=model, extracted_at=timestamp)
    blocks = {block.id: block for block in document.blocks}
    values = [getattr(projected, key) for key in ('arr', 'arr_prior_year', 'mrr',
              'growth_rate_yoy', 'burn_monthly', 'cash_on_hand', 'runway_months', 'headcount')]
    for value in [*values, *projected.funding_history]:
        if value.source_block_id is not None:
            block = blocks.get(value.source_block_id)
            if block is None or value.source_page != block.page:
                raise ValueError('Private model citation page is not bound to its source block')
    if any(value.source_block_id not in blocks for value in projected.funding_history):
        raise ValueError('Private funding claims require a source block even without an amount')
    return projected


def extract_private(document: Document, model: str, reviewer_feedback=None):
    if not _EXTRACTION_SLOT.acquire(blocking=False):
        raise RuntimeError('Private extraction worker is busy; saved inputs are retained')
    try:
        return _extract_private(document, model, reviewer_feedback)
    finally:
        _EXTRACTION_SLOT.release()


def _extract_private(document, model, reviewer_feedback):
    started = time.monotonic()
    validate_local_model_name(model)
    # Freeze a detached trusted snapshot; no caller mutation can change replay.
    document = Document.model_validate(load_json(encoded(document.model_dump(mode='json'))))
    if (not document.blocks or len(document.blocks) > 50000
            or len({block.id for block in document.blocks}) != len(document.blocks)
            or any(block.document_id != document.id or block.page <= 0 for block in document.blocks)
            or reviewer_feedback is not None and (type(reviewer_feedback) is not str
                                                    or len(reviewer_feedback) > 16384)):
        raise ValueError('Private extraction source or feedback is outside its contract')
    source_hash = digest(document.model_dump(mode='json'))
    root, identifier = artifact_root(), new_id('extract')
    with scoped_directory(root, document.tenant_id, document.deal_id, create=True) as descriptor:
        os.mkdir(identifier, mode=0o700, dir_fd=descriptor)
    job = root / scope_component(document.tenant_id) / scope_component(document.deal_id) / identifier
    receipt = {'contract': CONTRACT, 'document_sha256': source_hash, 'state': 'started'}
    try:
        call = model_request(document, model, reviewer_feedback)
        call_hash = write_json(job / 'model-request.json', call)
        request = {'contract': CONTRACT, 'document': document.model_dump(mode='json'),
                   'document_sha256': source_hash, 'model': model, 'reviewer_feedback': reviewer_feedback,
                   'extracted_at': utcnow(), 'model_request_sha256': call_hash,
                   'max_seconds': MAX_SECONDS - (time.monotonic() - started)}
        request_hash = write_json(job / 'request.json', request)
        receipt.update(request_sha256=request_hash, model_request_sha256=call_hash)
        remaining = MAX_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError('Private extraction budget expired before execution')
        run_private([__import__('sys').executable, '-I', '-B', PROJECT / 'scripts/private_extraction_worker.py'],
                    job, timeout=remaining, extra_read=(PROJECT / 'agents', PROJECT / 'schemas.py'),
                    local_model=True)
        result_raw = read_source_bytes(job / 'result.json')
        result = load_json(result_raw)
        if (type(result) is not dict or set(result) != {'contract', 'request_sha256',
                'document_sha256', 'model_request_sha256', 'response_sha256', 'usage_sha256', 'result'}
                or result['contract'] != CONTRACT or result['request_sha256'] != request_hash
                or result['document_sha256'] != source_hash or result['model_request_sha256'] != call_hash
                or hashlib.sha256(read_source_bytes(job / 'request.json')).hexdigest() != request_hash
                or hashlib.sha256(read_source_bytes(job / 'model-request.json')).hexdigest() != call_hash):
            raise ValueError('Private extraction input binding changed')
        response_raw = read_source_bytes(job / 'raw-response.json')
        usage_raw = read_source_bytes(job / 'usage.json')
        if (hashlib.sha256(response_raw).hexdigest() != result['response_sha256']
                or hashlib.sha256(usage_raw).hexdigest() != result['usage_sha256']):
            raise ValueError('Private extraction response or usage binding changed')
        usage = load_json(usage_raw)
        if (type(usage) is not dict or type(usage.get('max_calls')) is not int or usage['max_calls'] != 6
                or type(usage.get('max_requests')) is not int or usage['max_requests'] != 6
                or type(usage.get('max_seconds')) not in (float, int)
                or usage['max_seconds'] != request['max_seconds']
                or type(usage.get('calls')) is not int or not 1 <= usage['calls'] <= 6
                or type(usage.get('requests')) is not int or not 1 <= usage['requests'] <= 6
                or type(usage.get('elapsed_seconds')) not in (float, int)
                or not 0 <= usage['elapsed_seconds'] <= usage['max_seconds'] + .001):
            raise ValueError('Private extraction exceeded its inference budget')
        projected = validate_response(load_json(response_raw), model, document, request['extracted_at'], call)
        if projected.model_dump(mode='json') != result['result']:
            raise ValueError('Private extraction result does not replay its recorded response')
        if time.monotonic() - started > MAX_SECONDS:
            raise TimeoutError('Private extraction exceeded its parent deadline')
        receipt.update(state='validated', response_sha256=result['response_sha256'],
                       usage_sha256=result['usage_sha256'], result_sha256=hashlib.sha256(result_raw).hexdigest())
        return projected
    except Exception as exc:
        receipt.update(state='failed', error_type=type(exc).__name__)
        raise
    finally:
        write_json(job / 'receipt.json', receipt)


def require_current_access(store, tenant_id):
    """Recheck this exact authenticated session, not merely another user session."""
    from security.identity import IDLE_SECONDS, token_hash
    identity = getattr(store, 'authenticated_identity', None)
    if identity is None or identity.tenant_id != tenant_id:
        raise PermissionError('Private extraction requires a current sandbox identity')
    now = time.time()
    active = store.conn.execute('''SELECT 1 FROM auth_sessions s
        JOIN auth_memberships m ON m.user_id=s.user_id AND m.tenant_id=s.tenant_id
        JOIN auth_users u ON u.id=s.user_id WHERE s.user_id=? AND s.tenant_id=?
        AND s.csrf=? AND s.revoked=0 AND s.expires>? AND s.touched>?
        AND m.active=1 AND u.disabled=0''',
        (identity.user_id, tenant_id, token_hash(identity.csrf), now, now-IDLE_SECONDS)).fetchone()
    if not active:
        raise PermissionError('Private extraction session or membership was revoked')
    return identity


def persist_private_result(store, result, document, expected_raw, *, status=None, audit_events=()):
    """No model call while locked; authorization/source/CAS share one transaction."""
    store.conn.execute('BEGIN IMMEDIATE')
    try:
        identity = require_current_access(store, result.tenant_id)
        deal = store.get_deal(result.tenant_id, result.deal_id)
        if document is None or deal is None or document.id not in deal.document_ids:
            raise ExtractionConflict('Private extraction source association is unavailable')
        current = store.get_document(result.tenant_id, document.id)
        if (current is None or current.deal_id != result.deal_id or result.document_id != document.id
                or digest(current.model_dump(mode='json')) != digest(document.model_dump(mode='json'))):
            raise ExtractionConflict('Private extraction source changed before persistence')
        if expected_raw is None:
            cursor = store.conn.execute('''INSERT INTO extraction_results (deal_id,tenant_id,data)
                VALUES (?,?,?) ON CONFLICT(deal_id) DO NOTHING''',
                (result.deal_id, result.tenant_id, result.model_dump_json()))
        else:
            cursor = store.conn.execute('''UPDATE extraction_results SET data=?
                WHERE deal_id=? AND tenant_id=? AND data=?''',
                (result.model_dump_json(), result.deal_id, result.tenant_id, expected_raw))
        if cursor.rowcount != 1:
            raise ExtractionConflict('Review data changed while private extraction was running')
        for event in audit_events:
            if (event.tenant_id, event.deal_id, event.actor) != (
                    result.tenant_id, result.deal_id, identity.user_id):
                raise ValueError('Private review audit identity changed')
            store.conn.execute('''INSERT INTO audit_log (id,tenant_id,deal_id,timestamp,data)
                VALUES (?,?,?,?,?)''', (event.id,event.tenant_id,event.deal_id,event.timestamp,event.model_dump_json()))
        if status is not None:
            from schemas import DealStatus
            deal.status = DealStatus(status)
            store.conn.execute('UPDATE deals SET data=? WHERE id=? AND tenant_id=?',
                               (deal.model_dump_json(), deal.id, deal.tenant_id))
        store.conn.commit()
        return deal
    except Exception:
        store.conn.rollback()
        raise
