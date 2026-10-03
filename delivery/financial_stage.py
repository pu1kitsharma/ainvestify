"""Tenant-scoped bridge from a room workbook to isolated local financial inference.

The isolated worker owns reconciliation and model-authored findings. This bridge
only fixes its private input identity and exposes a deliberately partial result.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
import sys

from agents.analysis.workbook_reconciliation import MAX_BYTES, SCOPE
from agents.inference.model_authorship import digest as record_digest
from agents.inference.model_routing import validate_local_model_name
from delivery.artifacts import artifact_root
from delivery.isolation import run_private
from delivery.storage import read_source_bytes, scope_component
from security.identity import has_access

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/private_financial_worker.py'
_READ_CODE = (SCRIPT.parents[1] / 'agents', SCRIPT.parents[1] / 'schemas.py',
              SCRIPT.parents[1] / 'workflow_schemas.py')


def _blocked(reason: str) -> dict:
    return {'state': 'blocked', 'reason': reason, **SCOPE,
            'artifact_status': 'diagnostic_partial_evidence_no_release',
            'independent_review': 'pending'}


def _write_new(path: Path, content: bytes) -> None:
    """Create once, with no path-following or overwrite of retained attempts."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _same_file(path: Path, content: bytes) -> bool:
    try:
        return read_source_bytes(path) == content
    except (OSError, ValueError):
        return False


def _stage_dir(job: dict) -> Path:
    return (artifact_root() / scope_component(job['tenant_id']) /
            scope_component(job['workspace_id']) / 'jobs' /
            scope_component(job['id']) / 'financial')


def run_financial_stage(store, job: dict, document, *, model_name: str,
                        as_of_date: str, timeout: float = 110,
                        budget_seconds: int = 105,
                        stage_root: Path | None = None) -> dict:
    """Run one bounded pass, or replay the same private workbook request.

    The caller chooses a workbook from the room's tenant/deal-scoped upload
    list. The adapter independently checks that association and current room
    revision before copying bytes. Its return value is never a validation or
    release decision, even if the local worker produces findings.
    """
    from api.routers.rooms import revision_for

    if not 1 <= timeout <= 120:
        raise ValueError('Financial process timeout must be 1 to 120 seconds')
    if not 1 <= budget_seconds <= 105:
        raise ValueError('Financial model budget must be 1 to 105 seconds')
    date.fromisoformat(as_of_date)
    validate_local_model_name(model_name)
    tenant, workspace_id = job['tenant_id'], job['workspace_id']
    if not has_access(store.conn, job['actor_id'], tenant):
        return _blocked('job_access_revoked')
    room = store.get_workspace(tenant, workspace_id=workspace_id)
    if room is None or not room.deal_id or document.tenant_id != tenant or document.deal_id != room.deal_id:
        return _blocked('workbook_outside_room_scope')
    bound_document = store.get_document(tenant, document.id)
    if (bound_document is None or bound_document.deal_id != room.deal_id or
            bound_document.type != 'xlsx' or document.type != 'xlsx' or
            bound_document.storage_uri != document.storage_uri):
        return _blocked('workbook_outside_room_scope')
    if revision_for(store, room) != job['input_revision']:
        return _blocked('input_revision_changed')
    try:
        content = read_source_bytes(bound_document.storage_uri)
    except (OSError, ValueError):
        return _blocked('workbook_unavailable_or_unsafe')
    if len(content) > MAX_BYTES:
        return _blocked('workbook_exceeds_size_limit')
    digest = hashlib.sha256(content).hexdigest()
    # A source can change between the room revision calculation and this read.
    if revision_for(store, room) != job['input_revision']:
        return _blocked('input_revision_changed')
    root = Path(stage_root) if stage_root is not None else _stage_dir(job) / scope_component(document.id)
    if root.is_symlink():
        return _blocked('financial_stage_directory_unsafe')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    binding = {'tenant_id': tenant, 'workspace_id': workspace_id,
               'job_id': job['id'], 'input_revision': job['input_revision'],
               'deal_id': room.deal_id, 'document_id': bound_document.id,
               'document_record_sha256': hashlib.sha256(
                   _json_bytes(bound_document.model_dump())).hexdigest(),
               'workbook_sha256': digest, 'as_of_date': as_of_date,
               'model': model_name}
    required = {
        'adapter_binding.json': _json_bytes(binding),
        'source.xlsx': content,
        'request.json': _json_bytes({'workbook': 'source.xlsx',
                                     'workbook_sha256': digest,
                                     'as_of_date': as_of_date}),
        'model.json': _json_bytes({'profiles': {'financial': model_name}}),
        'budget.json': _json_bytes({'seconds': budget_seconds}),
    }
    for name, value in required.items():
        path = root / name
        if path.exists() or path.is_symlink():
            if not _same_file(path, value):
                return _blocked('financial_request_differs_from_bound_request')
        else:
            _write_new(path, value)
    try:
        run_private([sys.executable, SCRIPT], root, timeout=timeout,
                    extra_read=_READ_CODE, local_model=True)
    except TimeoutError:
        return {'state': 'needs_resume', 'reason': 'private_financial_worker_timeout', **SCOPE,
                'artifact_status': 'diagnostic_partial_evidence_no_release',
                'independent_review': 'pending'}
    except RuntimeError:
        return _blocked('private_financial_worker_failed')
    if not has_access(store.conn, job['actor_id'], tenant):
        return _blocked('job_access_revoked')
    if revision_for(store, room) != job['input_revision']:
        return _blocked('input_revision_changed')
    try:
        result = json.loads((root / 'result.json').read_text(encoding='utf-8'))
        worker_binding = json.loads((root / 'binding.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return _blocked('private_financial_result_unavailable')
    if (not isinstance(result, dict) or not isinstance(worker_binding, dict) or
            worker_binding.get('workbook_sha256') != digest or
            worker_binding.get('as_of_date') != as_of_date or
            worker_binding.get('model') != model_name or
            record_digest({key: value for key, value in worker_binding.items()
                           if key != 'request_digest'}) != worker_binding.get('request_digest') or
            result.get('request_digest') != worker_binding.get('request_digest') or
            result.get('workbook_sha256') not in (None, digest) or
            any(result.get(key) != value for key, value in SCOPE.items()) or
            result.get('artifact_status') != 'diagnostic_partial_evidence_no_release' or
            result.get('independent_review') != 'pending'):
        return _blocked('private_financial_result_binding_failed')
    state = result.get('state')
    if state not in {'partial_evidence', 'blocked', 'needs_resume'}:
        return _blocked('private_financial_result_state_invalid')
    exposed = {key: result[key] for key in (
        'reason', 'phase', 'contract', 'request_digest', 'workbook_sha256',
        'as_of_date', 'evidence_digest', 'coverage', 'excluded_cells',
        'passes_used', 'attempt_count', 'response_id') if key in result}
    if state == 'partial_evidence':
        if result.get('analysis_state') != 'analysed' or not isinstance(result.get('findings'), list):
            return _blocked('private_financial_partial_result_invalid')
        exposed.update({'analysis_state': 'analysed', 'findings': result['findings'],
                        'unknowns': result.get('unknowns', []),
                        'acceptance_scope': 'local_model_checks_only'})
    return {'state': state, 'document_id': bound_document.id, **exposed, **SCOPE,
            'artifact_status': 'diagnostic_partial_evidence_no_release',
            'independent_review': 'pending'}
