"""Private append-only bounded document-generation continuation.

Claude Code contributed the generic intent/terminal journal and finite advance
design in an isolated sanitized coding session. This adapter invokes installed
local models only; it never repairs a failed company answer or releases a draft.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from agents.inference.local_models import LocalModel, _validate_exact_json
from agents.inference.model_authorship import recorded_call
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research.document_generation import (
    CONTRACT, CATALOG_ENCODING_V1, GenerationError, canonical_digest, evidence_inventory,
    frozen_document_request, generation_progress, request_json,
)


def _no_links(path):
    path = Path(path).absolute()
    for current in [path, *path.parents]:
        if current.is_symlink():
            raise GenerationError('private_document_journal_symlink_rejected')
    return path


def _write_new(path, value):
    path = _no_links(path)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # An incomplete record is deliberately retained as a blocked journal.
        raise
    directory = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read(path):
    fd = os.open(str(_no_links(path)), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise GenerationError('private_document_journal_regular_file_required')
        raw = stream.read()
    _validate_exact_json(raw)
    return json.loads(raw)


def prepare_document_generation(directory, manifests, author_pin, reviewer_pin, kind, *, mandate='',
                                catalog_encoding=CATALOG_ENCODING_V1, source_map_token_budgets=None, source_map_profiles=None,
                                qualification_context_profile=None, source_coverage_reviewer_pin=None,
                                planner_pin=None, streaming_transport_contract=None,
                                planning_schema_profile=None, planning_context_profile=None,
                                source_context_profile=None, source_index_encoding=None, material_context_profile=None,
                                source_reader_pin=None, planning_assignment_profile=None,
                                document_page_repair_profile=None):
    """Freeze a fresh private run; originals and past runs remain untouched."""
    from agents.research.document_generation import _pin
    root = _no_links(directory)
    if not root.parent.is_dir():
        raise GenerationError('existing_private_document_generation_parent_required')
    from agents.research.document_generation import CATALOG_ENCODING_V3, CATALOG_ENCODING_V4, CATALOG_ENCODING_V5, CATALOG_ENCODING_V6, frozen_source_map_requests
    mapped = catalog_encoding == CATALOG_ENCODING_V3
    literal = catalog_encoding in {CATALOG_ENCODING_V4,CATALOG_ENCODING_V5,CATALOG_ENCODING_V6}
    indexed = planning_schema_profile in {'indexed-physical-plan-v4','selected-physical-plan-v5'}
    if document_page_repair_profile is not None and (kind != 'intro_deck' or
            planning_schema_profile != 'selected-physical-plan-v5' or
            document_page_repair_profile != 'scope-feedback-once-v1'):
        raise GenerationError('page_repair_requires_explicit_selected_intro_profile')
    if planning_assignment_profile is not None and (planning_schema_profile != 'selected-physical-plan-v5' or
            planning_assignment_profile not in {'page-topics-v1','single-source-outline-v2'}):
        raise GenerationError('planning_assignment_requires_explicit_selected_reading_profile')
    if indexed and catalog_encoding != CATALOG_ENCODING_V6:
        raise GenerationError('indexed_physical_reading_requires_dense_literal_profile')
    if source_context_profile is not None and (planning_schema_profile != 'selected-physical-plan-v5' or
            source_context_profile != 'complete-local-source-32k-v1'):
        raise GenerationError('source_context_requires_explicit_selected_reading_profile')
    if source_index_encoding is not None and (planning_schema_profile != 'selected-physical-plan-v5' or
            source_index_encoding != 'bound-selected-refs-v2'):
        raise GenerationError('source_index_encoding_requires_explicit_selected_reading_profile')
    if material_context_profile is not None and (planning_schema_profile != 'selected-physical-plan-v5' or
            source_context_profile != 'complete-local-source-32k-v1' or
            material_context_profile != 'complete-local-materials-32k-v1'):
        raise GenerationError('material_context_requires_measured_selected_source_profile')
    if planner_pin is not None and catalog_encoding not in {CATALOG_ENCODING_V5,CATALOG_ENCODING_V6}:
        raise GenerationError('separate_planner_requires_explicit_compact_literal_profile')
    if streaming_transport_contract is not None and (catalog_encoding not in {CATALOG_ENCODING_V5,CATALOG_ENCODING_V6} or
            streaming_transport_contract != 'local-stream-observation-v1'):
        raise GenerationError('stream_observation_requires_explicit_compact_literal_profile')
    planner = _pin(planner_pin) if planner_pin is not None else None
    reader = _pin(source_reader_pin) if source_reader_pin is not None else None
    if reader is not None and (planning_schema_profile != 'selected-physical-plan-v5' or planner is None):
        raise GenerationError('separate_source_reader_requires_selected_flow_and_planner')
    if planning_schema_profile is not None and (catalog_encoding not in {CATALOG_ENCODING_V5,CATALOG_ENCODING_V6} or
            planning_schema_profile not in {'compact-anchor-pages-v1','compact-anchor-pages-v2','finite-physical-plan-v3','indexed-physical-plan-v4','selected-physical-plan-v5'}):
        raise GenerationError('compact_planning_requires_explicit_compact_literal_profile')
    if planning_context_profile is not None and (catalog_encoding != CATALOG_ENCODING_V6 or
            planning_schema_profile not in {'compact-anchor-pages-v2','finite-physical-plan-v3','indexed-physical-plan-v4','selected-physical-plan-v5'} or
            planning_context_profile != 'complete-local-32k-v1'):
        raise GenerationError('larger_planning_context_requires_explicit_dense_finite_profile')
    if literal and (qualification_context_profile != 'complete-literal-context-v2' or
                    source_coverage_reviewer_pin is not None):
        raise GenerationError('complete_literal_context_requires_exact_profile_without_source_critic')
    if source_coverage_reviewer_pin is not None and qualification_context_profile is None:
        raise GenerationError('source_coverage_reviewer_requires_explicit_qualification_context')
    coverage_pin = _pin(source_coverage_reviewer_pin) if source_coverage_reviewer_pin is not None else None
    if qualification_context_profile is not None and not literal and (not mapped or qualification_context_profile != 'complete-page-context-v1'):
        raise GenerationError('explicit_complete_page_qualification_context_required')
    if (source_map_token_budgets is not None or source_map_profiles is not None) and not mapped:
        raise GenerationError('source_map_token_budget_requires_explicit_profile')
    profile = {name:value for name,value in [('source_map_token_budgets',source_map_token_budgets),
        ('source_map_profiles',source_map_profiles)] if value is not None}
    inventory = (evidence_inventory(manifests, catalog_encoding=catalog_encoding)
                 if mapped or literal else evidence_inventory(manifests))
    map_requests = (frozen_source_map_requests(inventory, author_pin, kind=kind, mandate=mandate, **profile)
                    if mapped else [])
    request = frozen_document_request(inventory, planner if planner is not None else author_pin, kind, mandate=mandate,
                                     catalog_encoding=catalog_encoding, **profile,
                                     **({'page_author_pin':author_pin} if planner is not None else {}),
                                     **({'streaming_transport_contract':streaming_transport_contract}
                                        if streaming_transport_contract is not None else {}),
                                     **({'planning_schema_profile':planning_schema_profile}
                                        if planning_schema_profile is not None else {}),
                                     **({'planning_context_profile':planning_context_profile}
                                        if planning_context_profile is not None else {}),
                                     **({'source_context_profile':source_context_profile}
                                        if source_context_profile is not None else {}),
                                     **({'source_index_encoding':source_index_encoding}
                                        if source_index_encoding is not None else {}),
                                     **({'source_reader_pin':reader} if reader is not None else {}),
                                     **({'qualification_context_profile':qualification_context_profile} if literal else {}))
    root.mkdir(mode=0o700, exist_ok=False)
    body = {'contract': CONTRACT, 'inventory': inventory,
            'author_pin': author_pin, 'reviewer_pin': _pin(reviewer_pin), 'kind': kind, 'mandate': mandate,
            'maximum_seconds_per_advance': 105, 'maximum_calls_per_advance': 1,
            'maximum_requests_per_advance': 6, 'maximum_lifetime_model_calls':
                (len(inventory['source_map_topology']) if indexed else
                 len(map_requests) * (2 if qualification_context_profile is not None else 1)) + 81}
    if indexed:
        body['initial_request'] = request_json(request)
        body['source_page_read_count'] = len(inventory['source_map_topology'])
        body['qualification_context_profile'] = qualification_context_profile
    elif mapped:
        body['initial_request'] = request_json(request)
        body['source_map_requests'] = [request_json(item) for item in map_requests]
        body['source_map_count'] = len(map_requests)
        if qualification_context_profile is not None:
            body['qualification_context_profile'] = qualification_context_profile
            if coverage_pin is not None:
                body['source_coverage_reviewer_pin'] = coverage_pin
        if source_map_token_budgets is not None:
            body['source_map_token_budgets'] = list(source_map_token_budgets)
        if source_map_profiles is not None:
            body['source_map_profiles'] = list(source_map_profiles)
    else:
        body['plan_request'] = request_json(request)
        if literal:
            body['qualification_context_profile'] = qualification_context_profile
    if catalog_encoding != CATALOG_ENCODING_V1:
        body['catalog_encoding'] = catalog_encoding
    if planner is not None:
        body['planner_pin'] = planner
    if reader is not None:
        body['source_reader_pin'] = reader
    if planning_assignment_profile is not None:
        body['planning_assignment_profile'] = planning_assignment_profile
    if document_page_repair_profile is not None:
        body['document_page_repair_profile'] = document_page_repair_profile
    if streaming_transport_contract is not None:
        body['streaming_transport_contract'] = streaming_transport_contract
    if planning_schema_profile is not None:
        body['planning_schema_profile'] = planning_schema_profile
    if planning_context_profile is not None:
        body['planning_context_profile'] = planning_context_profile
    if source_context_profile is not None:
        body['source_context_profile'] = source_context_profile
    if source_index_encoding is not None:
        body['source_index_encoding'] = source_index_encoding
    if material_context_profile is not None:
        body['material_context_profile'] = material_context_profile
    _write_new(root / 'request.json', {**body, 'run_binding_digest': canonical_digest(body)})
    result = {'state': 'prepared', 'inventory_revision': inventory['inventory_revision'],
              'original_units': len(inventory['units']), 'original_tables': len(inventory['tables'])}
    if mapped:
        result.update(source_map_count=len(map_requests), maximum_lifetime_model_calls=body['maximum_lifetime_model_calls'])
    if indexed:
        result.update(source_page_read_count=body['source_page_read_count'],
                      maximum_lifetime_model_calls=body['maximum_lifetime_model_calls'])
    return result


def _load_run(root, *, _lineage=()):
    root = _no_links(root)
    if root in _lineage or len(_lineage) >= 8:
        raise GenerationError('private_document_adoption_lineage_cycle_or_limit')
    lineage = (*_lineage, root)
    body = _read(root / 'request.json')
    unsigned = {key: value for key, value in body.items() if key != 'run_binding_digest'}
    if body.get('contract') != CONTRACT or body.get('run_binding_digest') != canonical_digest(unsigned):
        raise GenerationError('private_document_generation_request_changed')
    from agents.research.document_generation import CATALOG_ENCODING_V3, CATALOG_ENCODING_V4, CATALOG_ENCODING_V5, CATALOG_ENCODING_V6, frozen_source_map_requests
    encoding = body.get('catalog_encoding', CATALOG_ENCODING_V1)
    from agents.research.document_generation import _pin
    if 'planner_pin' in body and encoding not in {CATALOG_ENCODING_V5,CATALOG_ENCODING_V6}:
        raise GenerationError('separate_planner_requires_explicit_compact_literal_profile')
    planner = _pin(body['planner_pin']) if 'planner_pin' in body else None
    if planner is not None and planner != body['planner_pin']:
        raise GenerationError('private_document_planner_pin_changed')
    reader = _pin(body['source_reader_pin']) if 'source_reader_pin' in body else None
    if reader is not None and (body.get('planning_schema_profile') != 'selected-physical-plan-v5' or
            planner is None or reader != body['source_reader_pin']):
        raise GenerationError('separate_source_reader_requires_selected_flow_and_planner')
    stream = body.get('streaming_transport_contract')
    if 'streaming_transport_contract' in body and (encoding not in {CATALOG_ENCODING_V5,CATALOG_ENCODING_V6} or
            stream != 'local-stream-observation-v1'):
        raise GenerationError('stream_observation_requires_explicit_compact_literal_profile')
    compact_profile = body.get('planning_schema_profile')
    indexed = compact_profile in {'indexed-physical-plan-v4','selected-physical-plan-v5'}
    if 'document_page_repair_profile' in body and (body['kind'] != 'intro_deck' or
            compact_profile != 'selected-physical-plan-v5' or
            body['document_page_repair_profile'] != 'scope-feedback-once-v1'):
        raise GenerationError('page_repair_requires_explicit_selected_intro_profile')
    if 'planning_assignment_profile' in body and (compact_profile != 'selected-physical-plan-v5' or
            body['planning_assignment_profile'] not in {'page-topics-v1','single-source-outline-v2'}):
        raise GenerationError('planning_assignment_requires_explicit_selected_reading_profile')
    source_context = body.get('source_context_profile')
    if 'source_context_profile' in body and (compact_profile != 'selected-physical-plan-v5' or
            source_context != 'complete-local-source-32k-v1'):
        raise GenerationError('source_context_requires_explicit_selected_reading_profile')
    if 'source_index_encoding' in body and (compact_profile != 'selected-physical-plan-v5' or
            body['source_index_encoding'] != 'bound-selected-refs-v2'):
        raise GenerationError('source_index_encoding_requires_explicit_selected_reading_profile')
    if 'material_context_profile' in body and (compact_profile != 'selected-physical-plan-v5' or
            source_context != 'complete-local-source-32k-v1' or
            body['material_context_profile'] != 'complete-local-materials-32k-v1'):
        raise GenerationError('material_context_requires_measured_selected_source_profile')
    if 'planning_schema_profile' in body and (encoding not in {CATALOG_ENCODING_V5,CATALOG_ENCODING_V6} or
            compact_profile not in {'compact-anchor-pages-v1','compact-anchor-pages-v2','finite-physical-plan-v3','indexed-physical-plan-v4','selected-physical-plan-v5'}):
        raise GenerationError('compact_planning_requires_explicit_compact_literal_profile')
    context_profile = body.get('planning_context_profile')
    if 'planning_context_profile' in body and (encoding != CATALOG_ENCODING_V6 or
            compact_profile not in {'compact-anchor-pages-v2','finite-physical-plan-v3','indexed-physical-plan-v4','selected-physical-plan-v5'} or context_profile != 'complete-local-32k-v1'):
        raise GenerationError('larger_planning_context_requires_explicit_dense_finite_profile')
    qualification = _qualification_context_profile(body)
    literal = encoding in {CATALOG_ENCODING_V4,CATALOG_ENCODING_V5,CATALOG_ENCODING_V6}
    if qualification and encoding not in {CATALOG_ENCODING_V3,CATALOG_ENCODING_V4,CATALOG_ENCODING_V5,CATALOG_ENCODING_V6}:
        raise GenerationError('explicit_complete_page_qualification_context_required')
    if literal and qualification.get('qualification_context_profile') != 'complete-literal-context-v2':
        raise GenerationError('complete_literal_context_requires_exact_profile_without_source_critic')
    if literal and not indexed and any(name in body for name in ('initial_request','source_map_count','source_map_requests',
                                               'source_map_profiles','source_map_token_budgets')):
        raise GenerationError('complete_literal_catalog_cannot_claim_source_map_calls')
    if indexed and (encoding != CATALOG_ENCODING_V6 or any(name in body for name in
            ('plan_request','source_map_count','source_map_requests','source_map_profiles','source_map_token_budgets'))):
        raise GenerationError('indexed_original_reading_cannot_claim_legacy_map_or_direct_plan')
    if not indexed and 'source_page_read_count' in body:
        raise GenerationError('source_page_read_count_requires_explicit_indexed_profile')
    if not literal and qualification.get('qualification_context_profile') == 'complete-literal-context-v2':
        raise GenerationError('complete_literal_context_requires_explicit_literal_catalog')
    profile = _source_map_profile(body)
    request = frozen_document_request(body['inventory'], planner if planner is not None else body['author_pin'],
        body['kind'], mandate=body['mandate'], catalog_encoding=encoding, **profile,
        **({'page_author_pin':body['author_pin']} if planner is not None else {}),
        **({'streaming_transport_contract':stream} if stream is not None else {}),
        **({'planning_schema_profile':compact_profile} if compact_profile is not None else {}),
        **({'planning_context_profile':context_profile} if context_profile is not None else {}),
        **({'source_context_profile':source_context} if source_context is not None else {}),
        **({'source_reader_pin':reader} if reader is not None else {}),
        **({key:value for key,value in qualification.items() if key not in
            {'material_context_profile','document_planner_pin','planning_assignment_profile','document_page_repair_profile'}} if literal else {}))
    if indexed:
        count = len(body['inventory']['source_map_topology'])
        if (type(body.get('source_page_read_count')) is not int or body['source_page_read_count'] != count or
                body.get('initial_request') != request_json(request)):
            raise GenerationError('private_document_generation_source_page_read_profile_changed')
        lifetime = count + 81
    elif encoding == CATALOG_ENCODING_V3:
        maps = frozen_source_map_requests(body['inventory'], body['author_pin'], kind=body['kind'], mandate=body['mandate'], **profile)
        if (type(body.get('source_map_count')) is not int or body['source_map_count'] != len(maps) or
                body.get('source_map_requests') != [request_json(item) for item in maps] or
                body.get('initial_request') != request_json(request)):
            raise GenerationError('private_document_generation_source_map_profile_changed')
        lifetime = len(maps) * (2 if qualification else 1) + 81
    else:
        if body['plan_request'] != request_json(request):
            raise GenerationError('private_document_generation_plan_profile_changed')
        lifetime = 81
    if (body.get('maximum_lifetime_model_calls') != lifetime or
            body.get('maximum_seconds_per_advance') != 105 or
            body.get('maximum_calls_per_advance') != 1 or
            body.get('maximum_requests_per_advance') != 6):
        raise GenerationError('private_document_generation_finite_bounds_changed')
    paths = sorted(root.glob('response_*.json'), key=lambda p: int(p.stem.split('_')[1]))
    attempts = []
    for index, path in enumerate(paths, 1):
        if path.name != f'response_{index}.json':
            raise GenerationError('private_document_generation_response_gap')
        row = _read(path)
        intent = _read(root / f'call_{index}.started.json')
        if (row.get('id') != f'response_{index}' or intent.get('run_binding_digest') != body['run_binding_digest'] or
                intent.get('request_digest') != canonical_digest([row.get('task'), row.get('instruction'),
                    row.get('input'), row.get('schema')])):
            raise GenerationError('private_document_generation_intent_response_mismatch')
        attempts.append(row)
    if len(attempts) > lifetime:
        raise GenerationError('private_document_generation_lifetime_calls_exceeded')
    _verify_prefix_adoption(root, body, attempts, lineage)
    from delivery.document_prefix_adoption import verify_document_prefix_adoption
    verify_document_prefix_adoption(root, body, attempts, lineage)
    return body, request, attempts


def replay_document_generation(directory, *, tenant_id, deal_id):
    root = _no_links(directory)
    body, request, attempts = _load_run(root)
    return _replay_loaded_document_generation(root, body, request, attempts,
        tenant_id=tenant_id, deal_id=deal_id)


def _replay_loaded_document_generation(root, body, request, attempts, *, tenant_id, deal_id):
    """Reuse one freshly verified snapshot while its advance lock is held."""
    if body['inventory']['tenant_id'] != tenant_id or body['inventory']['deal_id'] != deal_id:
        raise GenerationError('private_document_generation_scope_mismatch')
    progress = generation_progress(request, body['inventory'], attempts, body['reviewer_pin'],
        **_source_map_profile(body), **_qualification_context_profile(body))
    from agents.research.document_generation import CATALOG_ENCODING_V3, CATALOG_ENCODING_V4, CATALOG_ENCODING_V5, CATALOG_ENCODING_V6
    number = len(attempts) + 1
    if body.get('catalog_encoding') in {CATALOG_ENCODING_V3,CATALOG_ENCODING_V4,CATALOG_ENCODING_V5,CATALOG_ENCODING_V6}:
        for path in root.glob('call_*.started.json'):
            try:
                call_number = int(path.name.split('_', 1)[1].split('.', 1)[0])
            except ValueError as error:
                raise GenerationError('private_document_generation_invalid_intent_name') from error
            if path.name != f'call_{call_number}.started.json' or call_number < 1:
                raise GenerationError('private_document_generation_invalid_intent_name')
            if call_number > len(attempts):
                return {'state': 'blocked', 'reason': 'unresolved_document_call_intent',
                        'recorded_model_calls': len(attempts), 'next_response_id': f'response_{call_number}'}
    if progress['state'] == 'needs_call' and (root / f'call_{number}.started.json').exists():
        return {'state': 'blocked', 'reason': 'unresolved_document_call_intent',
                'recorded_model_calls': len(attempts), 'next_response_id': f'response_{number}'}
    return progress


def advance_document_generation(directory, *, tenant_id, deal_id, installed_digest, model_factory=LocalModel):
    """Run one new model task, at most105 seconds/six physical requests.

    installed_digest is a trusted read-only installed-model inventory callback.
    No inference is made when exact replay is complete or blocked.
    """
    root = _no_links(directory)
    lockpath = root / 'advance.lock'
    lockfd = os.open(str(lockpath), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'busy', 'reason': 'private_document_advance_already_running'}
        body, request, attempts = _load_run(root)
        progress = _replay_loaded_document_generation(root, body, request, attempts,
            tenant_id=tenant_id, deal_id=deal_id)
        if progress['state'] != 'needs_call':
            return progress
        task, instruction, payload, schema = progress['request']
        if installed_digest(payload['model_pin']['name']) != payload['model_pin']['digest']:
            raise GenerationError('private_document_installed_model_pin_changed')
        role = model_factory(payload['model_pin']['name'], **payload['options'])
        number = len(attempts) + 1
        if number > body['maximum_lifetime_model_calls']:
            raise GenerationError('private_document_generation_lifetime_calls_exceeded')
        intent = {
            'contract': CONTRACT, 'run_binding_digest': body['run_binding_digest'],
            'phase': progress['phase'], 'page_id': progress.get('page_id'),
            'request_digest': canonical_digest(request_json(progress['request'])),
            'model_pin': payload['model_pin']}
        if body.get('planning_schema_profile') in {'indexed-physical-plan-v4','selected-physical-plan-v5'} and progress['phase'] == 'document_source_index':
            intent['source_page_read_index'] = payload['source_index']
            intent['source_page_read_id'] = payload['source_group_id']
        if body.get('source_map_count') is not None:
            intent['source_map_index'] = payload.get('source_map_index') if progress['phase'] == 'document_source_map' else None
            intent['source_map_id'] = payload.get('map_id') if progress['phase'] == 'document_source_map' else None
            intent['source_page_id'] = payload.get('source_page_id') if progress['phase'] == 'document_source_map' else None
        if body.get('qualification_context_profile') is not None:
            intent['qualification_context_profile'] = body['qualification_context_profile']
            if progress['phase'] == 'document_source_coverage_review':
                intent['source_map_index'] = payload.get('source_map_index')
                intent['source_map_id'] = payload.get('map_id')
                intent['source_page_id'] = payload.get('source_page_id')
        _write_new(root / f'call_{number}.started.json', intent)
        budget = PreparationBudget(105, max_calls=1, max_requests=6)
        _write_new(root / f'budget_{number}.started.json', budget.snapshot())
        def save():
            _write_new(root / f'response_{number}.json', attempts[-1])
        try:
            with preparation_budget(budget):
                recorded_call(role, task, instruction, payload, schema, attempts, save)
        except Exception:
            # Actual failed raw response remains terminal; no repeated call.
            pass
        finally:
            _write_new(root / f'budget_{number}.completed.json', budget.snapshot())
        final = replay_document_generation(root, tenant_id=tenant_id, deal_id=deal_id)
        snapshot = {key: value for key, value in final.items() if key != 'request'}
        _write_new(root / f'checkpoint_{number}.json', snapshot)
        return final
    finally:
        os.close(lockfd)


def _qualification_context_profile(body):
    from agents.research.document_generation import _pin
    if 'qualification_context_profile' not in body:
        if 'source_coverage_reviewer_pin' in body:
            raise GenerationError('source_coverage_reviewer_requires_explicit_qualification_context')
        return {}
    if body['qualification_context_profile'] not in {'complete-page-context-v1','complete-literal-context-v2'}:
        raise GenerationError('explicit_complete_page_qualification_context_required')
    result = {'qualification_context_profile': body['qualification_context_profile']}
    if 'source_reader_pin' in body:
        if body.get('planning_schema_profile') != 'selected-physical-plan-v5' or 'planner_pin' not in body:
            raise GenerationError('separate_source_reader_requires_selected_flow_and_planner')
        result['document_planner_pin'] = _pin(body['planner_pin'])
    if 'planning_assignment_profile' in body:
        result['planning_assignment_profile'] = body['planning_assignment_profile']
    if 'document_page_repair_profile' in body:
        result['document_page_repair_profile'] = body['document_page_repair_profile']
    if 'source_index_encoding' in body:
        if (body.get('planning_schema_profile') != 'selected-physical-plan-v5' or
                body['source_index_encoding'] != 'bound-selected-refs-v2'):
            raise GenerationError('source_index_encoding_requires_explicit_selected_reading_profile')
        result['source_index_encoding'] = body['source_index_encoding']
    if 'material_context_profile' in body:
        if (body.get('planning_schema_profile') != 'selected-physical-plan-v5' or
                body.get('source_context_profile') != 'complete-local-source-32k-v1' or
                body['material_context_profile'] != 'complete-local-materials-32k-v1'):
            raise GenerationError('material_context_requires_measured_selected_source_profile')
        result['material_context_profile'] = body['material_context_profile']
    if body['qualification_context_profile'] == 'complete-literal-context-v2' and 'source_coverage_reviewer_pin' in body:
        raise GenerationError('complete_literal_context_requires_exact_profile_without_source_critic')
    if 'source_coverage_reviewer_pin' in body:
        result['source_coverage_reviewer_pin'] = _pin(body['source_coverage_reviewer_pin'])
        if result['source_coverage_reviewer_pin'] != body['source_coverage_reviewer_pin']:
            raise GenerationError('source_coverage_reviewer_pin_changed')
    return result


def _source_map_profile(body):
    result = {}
    for name in ('source_map_token_budgets', 'source_map_profiles'):
        if name in body:
            if not isinstance(body[name], list):
                raise GenerationError('private_document_source_map_profile_vector_required')
            result[name] = body[name]
    return result


def _bytes(path):
    from delivery.storage import read_source_bytes
    return read_source_bytes(_no_links(path))


def _hash_file(path):
    return hashlib.sha256(_bytes(path)).hexdigest()


def _write_bytes_new(path, content):
    path = _no_links(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _maps(body):
    from agents.research.document_generation import CATALOG_ENCODING_V3, frozen_source_map_requests
    if body.get('catalog_encoding') != CATALOG_ENCODING_V3:
        raise GenerationError('explicit_source_map_profile_required_for_prefix_adoption')
    return frozen_source_map_requests(body['inventory'], body['author_pin'],
        kind=body['kind'], mandate=body['mandate'], **_source_map_profile(body))


def _source_proof(root, body):
    """Resolve immutable private source paths; the CLI also checks full parsers."""
    proof = _read(root / 'source_provenance.json')
    if not isinstance(proof.get('sources'), list) or not proof['sources']:
        raise GenerationError('private_source_provenance_required_for_adoption')
    actual = []
    for item in proof['sources']:
        manifest_path = _no_links(item['manifest_path'])
        original_path = _no_links(item['original_path'])
        manifest = _read(manifest_path)
        binding = manifest.get('binding', {})
        if (_hash_file(manifest_path) != item['manifest_sha256'] or
                _hash_file(original_path) != item['original_sha256'] or
                binding.get('source_sha256') != item['original_sha256'] or
                (binding.get('tenant_id'), binding.get('deal_id')) !=
                (body['inventory']['tenant_id'], body['inventory']['deal_id']) or
                manifest.get('manifest_digest') != canonical_digest({key:value for key,value in manifest.items()
                    if key != 'manifest_digest'})):
            raise GenerationError('private_source_adoption_provenance_changed')
        actual.append((binding['source_sha256'], manifest['manifest_digest']))
    expected = [(source['source_id'], source['manifest_digest']) for source in body['inventory']['sources']]
    if actual != expected:
        raise GenerationError('private_source_adoption_inventory_provenance_changed')
    return _hash_file(root / 'source_provenance.json')


def _same_prefix_scope(new_body, parent_body):
    for key in ('author_pin', 'reviewer_pin', 'kind', 'mandate'):
        if new_body[key] != parent_body[key]:
            raise GenerationError('private_source_map_adoption_scope_or_pin_changed')
    if (new_body['inventory'] != parent_body['inventory'] or
            new_body['inventory']['inventory_revision'] != parent_body['inventory']['inventory_revision'] or
            new_body['inventory']['source_map_topology_digest'] != parent_body['inventory']['source_map_topology_digest']):
        raise GenerationError('private_source_map_adoption_inventory_or_topology_changed')


def verified_source_map_prefix(parent_directory):
    """Return (successful prefix count, complete frozen requests, parent body).

    Only exact actual raw model responses qualify. The first failed/unmatched
    map ends the prefix; no answer, call, budget or successful status is created.
    """
    from agents.research.document_generation import replay_source_map
    parent = _no_links(parent_directory)
    body, _, attempts = _load_run(parent)
    requests = _maps(body)
    _source_proof(parent, body)
    count = 0
    for request, row in zip(requests, attempts):
        try:
            replay_source_map(request, row)
        except (ValueError, KeyError, TypeError, IndexError):
            break
        count += 1
    return count, requests, body


def _adopted_intent(body, receipt, record, request):
    payload = request[2]
    return {'contract': CONTRACT, 'run_binding_digest': body['run_binding_digest'],
        'phase': 'document_source_map', 'page_id': None,
        'request_digest': canonical_digest(request_json(request)), 'model_pin': payload['model_pin'],
        'source_map_index': payload['source_map_index'], 'source_map_id': payload['map_id'],
        'source_page_id': payload['source_page_id'],
        'execution_origin': 'adopted_recorded_source_map',
        'adoption_receipt_digest': receipt['adoption_digest'],
        'parent_directory': receipt['parent_directory'],
        'parent_response_id': record['response_id'],
        'parent_response_file_sha256': record['response_file_sha256'],
        'parent_intent_file_sha256': record['parent_intent_file_sha256']}


def _verify_prefix_adoption(root, body, attempts, lineage):
    from agents.research.document_generation import replay_source_map
    path = root / 'source_map_prefix_adoption.json'
    adopted_intents = []
    for index in range(1, len(attempts) + 1):
        intent = _read(root / f'call_{index}.started.json')
        if intent.get('execution_origin') == 'adopted_recorded_source_map':
            adopted_intents.append(index)
    if not path.exists():
        if adopted_intents:
            raise GenerationError('private_source_map_adoption_receipt_missing')
        return
    receipt = _read(path)
    if (receipt.get('contract') != 'private-source-map-prefix-adoption-v1' or
            receipt.get('adoption_digest') != canonical_digest({key:value for key,value in receipt.items()
                if key != 'adoption_digest'}) or receipt.get('new_run_binding_digest') != body['run_binding_digest'] or
            receipt.get('new_request_file_sha256') != _hash_file(root / 'request.json') or
            receipt.get('new_model_invocations') != 0 or receipt.get('new_physical_requests') != 0 or
            receipt.get('inventory_revision') != body['inventory']['inventory_revision'] or
            receipt.get('source_map_topology_digest') != body['inventory']['source_map_topology_digest'] or
            receipt.get('financial_validation') != 'not_established' or
            receipt.get('investor_approval') != 'not_established'):
        raise GenerationError('private_source_map_adoption_receipt_changed')
    count = receipt.get('adopted_response_count')
    if type(count) is not int or not 1 <= count <= body.get('source_map_count', 0) or len(attempts) < count:
        raise GenerationError('private_source_map_adoption_incomplete_or_outside_bounds')
    if adopted_intents != list(range(1, count + 1)) or len(receipt.get('records', [])) != count:
        raise GenerationError('private_source_map_adoption_prefix_changed')
    parent = _no_links(receipt['parent_directory'])
    parent_body, _, parent_attempts = _load_run(parent, _lineage=lineage)
    _same_prefix_scope(body, parent_body)
    if (receipt.get('parent_run_binding_digest') != parent_body['run_binding_digest'] or
            receipt.get('parent_request_file_sha256') != _hash_file(parent / 'request.json') or
            receipt.get('parent_source_provenance_sha256') != _source_proof(parent, parent_body) or
            receipt.get('new_source_provenance_sha256') != _source_proof(root, body)):
        raise GenerationError('private_source_map_adoption_parent_or_source_changed')
    new_requests, parent_requests = _maps(body), _maps(parent_body)
    for index, record in enumerate(receipt['records'], 1):
        response_id = f'response_{index}'
        if (index > len(parent_attempts) or record.get('response_id') != response_id or
                request_json(new_requests[index-1]) != request_json(parent_requests[index-1]) or
                record.get('request_digest') != canonical_digest(request_json(new_requests[index-1])) or
                record.get('response_file_sha256') != _hash_file(root / f'{response_id}.json') or
                record.get('response_file_sha256') != _hash_file(parent / f'{response_id}.json') or
                record.get('parent_intent_file_sha256') != _hash_file(parent / f'call_{index}.started.json') or
                _read(root / f'call_{index}.started.json') != _adopted_intent(body, receipt, record, new_requests[index-1])):
            raise GenerationError('private_source_map_adopted_raw_or_request_changed')
        replay_source_map(parent_requests[index-1], parent_attempts[index-1])
        replay_source_map(new_requests[index-1], attempts[index-1])
        if (root / f'budget_{index}.started.json').exists() or (root / f'budget_{index}.completed.json').exists():
            raise GenerationError('adopted_source_map_must_not_fabricate_physical_budget')


def adopt_source_map_prefix(new_directory, parent_directory, *, count=None):
    """Adopt only verified, byte-identical maps into a fresh immutable branch.

    Pure preflight rejects failed/mismatched prefixes before any target write.
    Under both journal locks the same proof is checked again before committing.
    No physical budget/call is fabricated; incomplete adoption remains blocked.
    """
    from agents.research.document_generation import replay_source_map
    root, parent = _no_links(new_directory), _no_links(parent_directory)
    if root == parent:
        raise GenerationError('source_map_adoption_requires_distinct_private_branch')

    def preflight():
        body, _, existing = _load_run(root)
        if (existing or list(root.glob('call_*.started.json')) or list(root.glob('budget_*.json')) or
                (root / 'source_map_prefix_adoption.json').exists()):
            raise GenerationError('source_map_adoption_requires_unstarted_branch')
        success_count, parent_requests, parent_body = verified_source_map_prefix(parent)
        selected_count = success_count if count is None else count
        if type(selected_count) is not int or not 1 <= selected_count <= success_count:
            raise GenerationError('only_verified_successful_source_map_prefix_may_be_adopted')
        _same_prefix_scope(body, parent_body)
        requests = _maps(body)
        records, originals = [], []
        for index in range(1, selected_count + 1):
            if request_json(requests[index-1]) != request_json(parent_requests[index-1]):
                raise GenerationError('source_map_adoption_request_profile_changed')
            original = _bytes(parent / f'response_{index}.json')
            replay_source_map(requests[index-1], _read(parent / f'response_{index}.json'))
            records.append({'response_id': f'response_{index}',
                'response_file_sha256': hashlib.sha256(original).hexdigest(),
                'parent_intent_file_sha256': _hash_file(parent / f'call_{index}.started.json'),
                'request_digest': canonical_digest(request_json(requests[index-1]))})
            originals.append(original)
        value = {'contract': 'private-source-map-prefix-adoption-v1',
            'parent_directory': str(parent), 'parent_run_binding_digest': parent_body['run_binding_digest'],
            'parent_request_file_sha256': _hash_file(parent / 'request.json'),
            'parent_source_provenance_sha256': _source_proof(parent, parent_body),
            'new_run_binding_digest': body['run_binding_digest'],
            'new_request_file_sha256': _hash_file(root / 'request.json'),
            'new_source_provenance_sha256': _source_proof(root, body),
            'inventory_revision': body['inventory']['inventory_revision'],
            'source_map_topology_digest': body['inventory']['source_map_topology_digest'],
            'adopted_response_count': selected_count, 'records': records,
            'new_model_invocations': 0, 'new_physical_requests': 0,
            'financial_validation': 'not_established', 'investor_approval': 'not_established'}
        return body, requests, originals, {**value, 'adoption_digest': canonical_digest(value)}

    expected = preflight()
    child_fd = os.open(root / 'advance.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    parent_fd = None
    try:
        parent_fd = os.open(parent / 'advance.lock', os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(child_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(parent_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GenerationError('source_map_adoption_parent_or_target_busy') from error
        current = preflight()
        # Per-page finite decoding schemas are independently reconstructed
        # Pydantic classes. Bind their complete serialized schemas, not Python
        # object identity; the two preflights must still match every byte proof.
        def proof(value):
            body, requests, originals, receipt = value
            return body, [request_json(item) for item in requests], originals, receipt
        if proof(current) != proof(expected):
            raise GenerationError('source_map_adoption_preflight_changed')
        body, requests, originals, receipt = current
        _write_new(root / 'source_map_prefix_adoption.json', receipt)
        for index, (record, original) in enumerate(zip(receipt['records'], originals), 1):
            _write_new(root / f'call_{index}.started.json', _adopted_intent(body, receipt, record, requests[index-1]))
            _write_bytes_new(root / f'response_{index}.json', original)
        _load_run(root)
        return {'state': 'source_map_prefix_adopted', 'adopted_model_responses': receipt['adopted_response_count'],
                'new_model_invocations': 0, 'new_physical_requests': 0,
                'adoption_digest': receipt['adoption_digest'], 'parent_directory': str(parent)}
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(child_fd)
