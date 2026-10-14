"""Byte-exact reuse of successful local source-reading and plan records only.

Adoption invokes no models and copies no physical budgets. Sources and proposals
remain unqualified. The stage supplies its normal ancestry/cycle checks; the CLI
also reconstructs immutable native/OCR derivatives inside the private boundary.
"""
from __future__ import annotations

import fcntl
import hashlib
import math
import os

from agents.research import document_generation as dg
from agents.research.document_source_index import replay_source_index
from delivery import document_generation_stage as stage

CONTRACT = 'private-document-prefix-adoption-v1'
RECEIPT = 'private_document_prefix_adoption.json'
ORIGIN = 'adopted_recorded_document_prefix'
CONTRACT_V2 = 'private-document-prefix-adoption-v2'
ORIGIN_V2 = 'adopted_recorded_document_author_prefix'
REPAIR_PROFILE = 'scope-feedback-once-v1'


def _source_requests(body, seed):
    if (body.get('planning_schema_profile') != dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5 or
            body.get('catalog_encoding') != dg.CATALOG_ENCODING_V6):
        raise dg.GenerationError('document_prefix_requires_selected_physical_reading_profile')
    dg._validate_material_profile(body.get('material_context_profile'), seed)
    return dg._source_index_requests_from_seed(seed, body['inventory'])


def _budget(parent, index):
    started = stage._read(parent / f'budget_{index}.started.json')
    completed = stage._read(parent / f'budget_{index}.completed.json')
    for value in (started, completed):
        if (type(value.get('max_seconds')) not in (int, float) or value['max_seconds'] != 105 or
                type(value.get('max_calls')) is not int or value['max_calls'] != 1 or
                type(value.get('max_requests')) is not int or value['max_requests'] != 6):
            raise dg.GenerationError('document_prefix_parent_budget_limits_changed')
    if (started.get('calls') != 0 or started.get('requests') != 0 or
            type(completed.get('calls')) is not int or completed['calls'] != 1 or
            type(completed.get('requests')) is not int or not 1 <= completed['requests'] <= 6 or
            type(completed.get('elapsed_seconds')) not in (int, float) or
            not math.isfinite(completed['elapsed_seconds']) or not 0 < completed['elapsed_seconds'] <= 105):
        raise dg.GenerationError('document_prefix_parent_completed_budget_unqualified')
    return {'parent_budget_started_sha256': stage._hash_file(parent / f'budget_{index}.started.json'),
            'parent_budget_completed_sha256': stage._hash_file(parent / f'budget_{index}.completed.json')}


def _replay(request, row, inventory, source_count, index):
    if index <= source_count:
        replay_source_index(request, row)
    else:
        dg.replay_document_plan(request, row, inventory)


def _plan_request(body, seed, rows):
    return dg._source_index_plan_request(seed, body['inventory'], rows,
        source_index_encoding=body.get('source_index_encoding'),
        **({'planning_assignment_profile': body['planning_assignment_profile']}
           if 'planning_assignment_profile' in body else {}),
        **({'document_planner_pin': body.get('planner_pin', body['author_pin'])}
           if 'source_reader_pin' in body else {}))


def _actual_intent(parent, index, body, request, phase):
    intent = stage._read(parent / f'call_{index}.started.json')
    if (intent.get('contract') != dg.CONTRACT or intent.get('run_binding_digest') != body['run_binding_digest'] or
            intent.get('request_digest') != dg.canonical_digest(dg.request_json(request)) or
            intent.get('model_pin') != request[2]['model_pin'] or intent.get('phase') != phase or
            'execution_origin' in intent):
        raise dg.GenerationError('document_prefix_parent_actual_intent_changed')


def _prefix(parent, body, seed, attempts):
    """Construct the source vector once and the actual plan at most once."""
    requests = _source_requests(body, seed)
    source_count, count = len(requests), 0
    for index, row in enumerate(attempts[:source_count], 1):
        try:
            if 'error' in row: break
            _actual_intent(parent, index, body, requests[index-1], 'document_source_index')
            _budget(parent, index)
            _replay(requests[index-1], row, body['inventory'], source_count, index)
        except (ValueError, KeyError, TypeError, IndexError, OSError):
            break
        count += 1
    if count == source_count:
        plan = _plan_request(body, seed, attempts[:source_count])
        requests.append(plan)
        if len(attempts) > source_count:
            try:
                if 'error' not in attempts[source_count]:
                    _actual_intent(parent, source_count + 1, body, plan, 'document_plan')
                    _budget(parent, source_count + 1)
                    _replay(plan, attempts[source_count], body['inventory'], source_count, source_count + 1)
                    count += 1
            except (ValueError, KeyError, TypeError, IndexError, OSError):
                pass
    return count, requests


def _verified_v1(parent_directory):
    """Return successful count, frozen source/actual-plan requests, parent body."""
    parent = stage._no_links(parent_directory)
    body, seed, attempts = stage._load_run(parent)
    stage._source_proof(parent, body)
    count, requests = _prefix(parent, body, seed, attempts)
    return count, requests, body


def _same_scope(child_body, parent_body, seed):
    ignored = {'run_binding_digest', 'material_context_profile', 'planner_pin', 'source_reader_pin',
               'planning_assignment_profile'}
    if ({k: v for k, v in child_body.items() if k not in ignored} !=
            {k: v for k, v in parent_body.items() if k not in ignored}):
        raise dg.GenerationError('document_prefix_scope_pins_inventory_or_source_context_changed')
    def reader(body):
        return dg._pin(body.get('source_reader_pin', body.get('planner_pin', body['author_pin'])))
    if reader(child_body) != reader(parent_body) or reader(child_body) != seed[2]['model_pin']:
        raise dg.GenerationError('document_prefix_effective_source_reader_pin_changed')
    dg._validate_material_profile(child_body.get('material_context_profile'), seed)


def _changed_boundary(parent, body, attempts, successful, source_requests, parent_requests, child_plan):
    maximum = len(source_requests) + 1
    if successful >= maximum or (len(attempts) <= successful and
            not (parent / f'call_{successful+1}.started.json').exists()):
        return None
    old_request = parent_requests[successful]
    new_request = child_plan if successful == len(source_requests) else source_requests[successful]
    if dg.request_json(old_request) == dg.request_json(new_request):
        raise dg.GenerationError('document_prefix_cannot_retry_identical_failed_or_orphan_source_plan')
    intent = stage._read(parent / f'call_{successful+1}.started.json')
    if (intent.get('request_digest') != dg.canonical_digest(dg.request_json(old_request)) or
            intent.get('run_binding_digest') != body['run_binding_digest'] or
            intent.get('model_pin') != old_request[2]['model_pin']):
        raise dg.GenerationError('document_prefix_failed_parent_request_changed')
    if len(attempts) > successful:
        row = attempts[successful]
        if ([row.get('task'), row.get('instruction'), row.get('input'), row.get('schema')] !=
                dg.request_json(old_request) or row.get('model') != old_request[2]['model_pin']['name'] or
                row.get('response_hash') != dg.digest(row.get('raw_response'))):
            raise dg.GenerationError('document_prefix_failed_parent_raw_changed')
    value = {'parent_next_request_digest': dg.canonical_digest(dg.request_json(old_request)),
             'child_next_request_digest': dg.canonical_digest(dg.request_json(new_request))}
    for name in (f'call_{successful+1}.started.json', f'response_{successful+1}.json',
                 f'budget_{successful+1}.started.json', f'budget_{successful+1}.completed.json'):
        if (parent / name).exists(): value[name + '_sha256'] = stage._hash_file(parent / name)
    return value


def _intent(body, receipt, record, request):
    payload = request[2]
    value = {'contract': dg.CONTRACT, 'run_binding_digest': body['run_binding_digest'],
        'phase': record['phase'], 'page_id': None,
        'request_digest': dg.canonical_digest(dg.request_json(request)), 'model_pin': payload['model_pin'],
        'execution_origin': ORIGIN, 'adoption_receipt_digest': receipt['adoption_digest'],
        'parent_directory': receipt['parent_directory'], 'parent_response_id': record['response_id'],
        'parent_response_file_sha256': record['response_file_sha256'],
        'parent_intent_file_sha256': record['parent_intent_file_sha256']}
    if record['phase'] == 'document_source_index':
        value.update(source_page_read_index=payload['source_index'], source_page_read_id=payload['source_group_id'])
    if body.get('qualification_context_profile') is not None:
        value['qualification_context_profile'] = body['qualification_context_profile']
    return value


def verify_document_prefix_adoption(root, body, attempts, lineage):
    """Called by stage load; replay provenance without running future authors."""
    root = stage._no_links(root)
    if (root / RECEIPT).exists() and stage._read(root / RECEIPT).get('contract') == CONTRACT_V2:
        return _verify_v2(root, body, attempts, lineage)
    adopted = [i for i in range(1, len(attempts) + 1)
               if stage._read(root / f'call_{i}.started.json').get('execution_origin') in (ORIGIN, ORIGIN_V2)]
    path = root / RECEIPT
    if not path.exists():
        if adopted: raise dg.GenerationError('document_prefix_adoption_receipt_missing')
        return
    receipt = stage._read(path)
    if (receipt.get('contract') != CONTRACT or receipt.get('adoption_digest') !=
            dg.canonical_digest({k: v for k, v in receipt.items() if k != 'adoption_digest'}) or
            receipt.get('new_run_binding_digest') != body['run_binding_digest'] or
            receipt.get('new_request_file_sha256') != stage._hash_file(root / 'request.json') or
            receipt.get('new_model_invocations') != 0 or receipt.get('new_physical_requests') != 0 or
            any(receipt.get(k) != 'not_established' for k in
                ('financial_validation', 'regulatory_approval', 'investor_approval'))):
        raise dg.GenerationError('document_prefix_adoption_receipt_changed')
    parent = stage._no_links(receipt['parent_directory'])
    parent_body, seed, parent_attempts = stage._load_run(parent, _lineage=lineage)
    _same_scope(body, parent_body, seed)
    successful, requests = _prefix(parent, parent_body, seed, parent_attempts)
    count = receipt.get('adopted_response_count')
    source_count = len(parent_body['inventory']['source_map_topology'])
    if (type(count) is not int or not 1 <= count <= min(successful, source_count + 1) or
            len(attempts) < count or adopted != list(range(1, count + 1)) or
            len(receipt.get('records', [])) != count):
        raise dg.GenerationError('document_prefix_adoption_incomplete_or_outside_bounds')
    if (receipt.get('parent_run_binding_digest') != parent_body['run_binding_digest'] or
            receipt.get('parent_request_file_sha256') != stage._hash_file(parent / 'request.json') or
            receipt.get('parent_source_provenance_sha256') != stage._source_proof(parent, parent_body) or
            receipt.get('new_source_provenance_sha256') != stage._source_proof(root, body)):
        raise dg.GenerationError('document_prefix_adoption_parent_or_source_changed')
    # The stage already reconstructed this child's exact seed. Its immutable
    # initial_request equals the parent's under _same_scope; planner role is the
    # one permitted external change to a future global plan. The explicit
    # assignment profile also affects only that unadopted future plan.
    child_plan = (_plan_request(body, seed, parent_attempts[:source_count])
                  if successful >= source_count else None)
    if count > source_count:
        if dg.request_json(child_plan) != dg.request_json(requests[source_count]):
            raise dg.GenerationError('document_prefix_adopted_plan_request_changed')
    if receipt.get('changed_unadopted_request') != _changed_boundary(parent, parent_body, parent_attempts,
            successful, requests[:source_count], requests, child_plan):
        raise dg.GenerationError('document_prefix_unadopted_failure_proof_changed')
    for index, record in enumerate(receipt['records'], 1):
        expected_phase = 'document_source_index' if index <= source_count else 'document_plan'
        if (record.get('response_id') != f'response_{index}' or record.get('phase') != expected_phase or
                record.get('request_digest') != dg.canonical_digest(dg.request_json(requests[index-1])) or
                record.get('response_file_sha256') != stage._hash_file(parent / f'response_{index}.json') or
                record['response_file_sha256'] != stage._hash_file(root / f'response_{index}.json') or
                record.get('parent_intent_file_sha256') != stage._hash_file(parent / f'call_{index}.started.json') or
                any(record.get(k) != v for k, v in _budget(parent, index).items()) or
                stage._read(root / f'call_{index}.started.json') != _intent(body, receipt, record, requests[index-1])):
            raise dg.GenerationError('document_prefix_adopted_raw_intent_or_budget_changed')
        if any((root / f'budget_{index}.{name}.json').exists() for name in ('started', 'completed')):
            raise dg.GenerationError('document_prefix_adoption_must_not_fabricate_budget')
        _replay(requests[index-1], attempts[index-1], body['inventory'], source_count, index)


def _adopt_v1(child_directory, parent_directory, *, count=None):
    """Preflight before writes, then freeze exact prefix under both run locks."""
    root, parent = map(stage._no_links, (child_directory, parent_directory))
    if root == parent: raise dg.GenerationError('document_prefix_requires_distinct_branches')

    def preflight():
        body, seed, existing = stage._load_run(root)
        if (existing or list(root.glob('call_*.started.json')) or list(root.glob('budget_*.json')) or
                (root / RECEIPT).exists() or (root / 'source_map_prefix_adoption.json').exists()):
            raise dg.GenerationError('document_prefix_requires_unstarted_target')
        parent_body, parent_seed, attempts = stage._load_run(parent)
        _same_scope(body, parent_body, seed)
        parent_proof = stage._source_proof(parent, parent_body)
        child_proof = stage._source_proof(root, body)
        successful, requests = _prefix(parent, parent_body, parent_seed, attempts)
        source_requests = _source_requests(body, seed)
        if ([dg.request_json(r) for r in source_requests] !=
                [dg.request_json(r) for r in requests[:len(source_requests)]]):
            raise dg.GenerationError('document_prefix_source_request_context_changed')
        child_plan = (_plan_request(body, seed, attempts[:len(source_requests)])
                      if successful >= len(source_requests) else None)
        shared = successful
        if shared > len(source_requests) and dg.request_json(child_plan) != dg.request_json(requests[len(source_requests)]):
            shared = len(source_requests)
        selected = shared if count is None else count
        if type(selected) is not int or not 1 <= selected <= shared:
            raise dg.GenerationError('only_successful_identical_source_and_plan_prefix_may_be_adopted')
        # A changed writer context cannot fix/retry an unchanged failed source
        # or plan request. A later failed author is preserved but not adopted.
        boundary = _changed_boundary(parent, parent_body, attempts, successful, source_requests, requests, child_plan)
        records, originals = [], []
        for index in range(1, selected + 1):
            original = stage._bytes(parent / f'response_{index}.json')
            records.append({'response_id': f'response_{index}',
                'phase': 'document_source_index' if index <= len(source_requests) else 'document_plan',
                'response_file_sha256': hashlib.sha256(original).hexdigest(),
                'parent_intent_file_sha256': stage._hash_file(parent / f'call_{index}.started.json'),
                'request_digest': dg.canonical_digest(dg.request_json(requests[index-1])), **_budget(parent, index)})
            originals.append(original)
        value = {'contract': CONTRACT, 'parent_directory': str(parent),
            'parent_run_binding_digest': parent_body['run_binding_digest'],
            'parent_request_file_sha256': stage._hash_file(parent / 'request.json'),
            'parent_source_provenance_sha256': parent_proof,
            'new_run_binding_digest': body['run_binding_digest'],
            'new_request_file_sha256': stage._hash_file(root / 'request.json'),
            'new_source_provenance_sha256': child_proof,
            'adopted_response_count': selected, 'records': records,
            'new_model_invocations': 0, 'new_physical_requests': 0,
            'financial_validation': 'not_established', 'regulatory_approval': 'not_established',
            'investor_approval': 'not_established'}
        if boundary is not None: value['changed_unadopted_request'] = boundary
        return body, requests, originals, {**value, 'adoption_digest': dg.canonical_digest(value)}

    expected = preflight()
    child_fd = os.open(root / 'advance.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    parent_fd = None
    try:
        parent_fd = os.open(parent / 'advance.lock', os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(child_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(parent_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise dg.GenerationError('document_prefix_parent_or_target_busy') from exc
        current = preflight()
        def proof(value):
            body, requests, originals, receipt = value
            return body, [dg.request_json(r) for r in requests], originals, receipt
        if proof(current) != proof(expected):
            raise dg.GenerationError('document_prefix_preflight_changed')
        body, requests, originals, receipt = current
        stage._write_new(root / RECEIPT, receipt)
        for index, (record, original) in enumerate(zip(receipt['records'], originals), 1):
            stage._write_new(root / f'call_{index}.started.json', _intent(body, receipt, record, requests[index-1]))
            stage._write_bytes_new(root / f'response_{index}.json', original)
        loaded_body, _, attempts = stage._load_run(root)
        verify_document_prefix_adoption(root, loaded_body, attempts, (root,))
        return {'state': 'document_prefix_adopted', 'adopted_model_responses': receipt['adopted_response_count'],
            'new_model_invocations': 0, 'new_physical_requests': 0,
            'adoption_digest': receipt['adoption_digest'], 'parent_directory': str(parent)}
    finally:
        if parent_fd is not None: os.close(parent_fd)
        os.close(child_fd)


def verified_document_prefix(parent_directory, *, include_first_author=False):
    """First-author inclusion is an explicit, unqualified intro continuation."""
    if not include_first_author:
        return _verified_v1(parent_directory)
    parent = stage._no_links(parent_directory)
    body, seed, rows = stage._load_run(parent)
    stage._source_proof(parent, body)
    count, requests, _ = _author_prefix(parent, body, seed, rows)
    return count, requests, body


def adopt_document_prefix(child_directory, parent_directory, *, count=None):
    root = stage._no_links(child_directory)
    body, _, _ = stage._load_run(root)
    if body.get('document_page_repair_profile') is not None:
        return _adopt_v2(root, parent_directory, count=count)
    return _adopt_v1(root, parent_directory, count=count)


def _v2_intent(body, receipt, record, request):
    value = _intent(body, receipt, record, request)
    value['execution_origin'] = ORIGIN_V2
    if record['phase'] == 'document_page':
        value['page_id'] = request[2]['planned_page']['page_id']
    return value


def _repair_scope(child, parent):
    if (child.get('document_page_repair_profile') != REPAIR_PROFILE or child.get('kind') != 'intro_deck' or
            parent.get('kind') != 'intro_deck'):
        raise dg.GenerationError('document_author_prefix_requires_explicit_intro_repair_profile')
    ignored = {'run_binding_digest', 'document_page_repair_profile'}
    if ({k: v for k, v in child.items() if k not in ignored} !=
            {k: v for k, v in parent.items() if k not in ignored}):
        raise dg.GenerationError('document_author_prefix_only_future_review_profile_may_change')


def _actual_call_proof(directory, index, body, request, phase, cache, seen=()):
    """Resolve checked adoption ancestry to its real call; never invent budgets."""
    directory = stage._no_links(directory)
    if directory in seen or len(seen) >= 8:
        raise dg.GenerationError('document_author_prefix_actual_lineage_cyclic_or_too_deep')
    intent = stage._read(directory / f'call_{index}.started.json')
    origin = intent.get('execution_origin')
    if origin is None:
        _actual_intent(directory, index, body, request, phase)
        if phase == 'document_page' and intent.get('page_id') != request[2]['planned_page']['page_id']:
            raise dg.GenerationError('document_author_prefix_actual_page_changed')
        return {'actual_execution': {'directory': str(directory),
            'run_binding_digest': body['run_binding_digest'],
            'request_file_sha256': stage._hash_file(directory / 'request.json'),
            'response_file_sha256': stage._hash_file(directory / f'response_{index}.json'),
            'intent_file_sha256': stage._hash_file(directory / f'call_{index}.started.json'),
            **_budget(directory, index)}, 'adoption_hops': []}
    receipt = stage._read(directory / RECEIPT)
    contract_origin = {CONTRACT: ORIGIN, CONTRACT_V2: ORIGIN_V2}
    if (contract_origin.get(receipt.get('contract')) != origin or
            receipt.get('adoption_digest') != dg.canonical_digest({k: v for k, v in receipt.items() if k != 'adoption_digest'}) or
            receipt.get('new_run_binding_digest') != body['run_binding_digest'] or
            receipt.get('new_request_file_sha256') != stage._hash_file(directory / 'request.json') or
            type(receipt.get('adopted_response_count')) is not int or
            not 1 <= index <= receipt['adopted_response_count']):
        raise dg.GenerationError('document_author_prefix_parent_adoption_changed')
    record = receipt['records'][index - 1]
    expected_intent = (_v2_intent if origin == ORIGIN_V2 else _intent)(body, receipt, record, request)
    if (intent != expected_intent or record.get('phase') != phase or
            record.get('request_digest') != dg.canonical_digest(dg.request_json(request)) or
            record.get('response_file_sha256') != stage._hash_file(directory / f'response_{index}.json') or
            any((directory / f'budget_{index}.{s}.json').exists() for s in ('started', 'completed'))):
        raise dg.GenerationError('document_author_prefix_parent_raw_or_fake_budget_changed')
    original = stage._no_links(receipt['parent_directory'])
    if original not in cache:
        cache[original] = stage._load_run(original)[0]
    original_body = cache[original]
    if (receipt.get('parent_run_binding_digest') != original_body['run_binding_digest'] or
            receipt.get('parent_request_file_sha256') != stage._hash_file(original / 'request.json') or
            record['response_file_sha256'] != stage._hash_file(original / f'response_{index}.json') or
            record.get('parent_intent_file_sha256') != stage._hash_file(original / f'call_{index}.started.json')):
        raise dg.GenerationError('document_author_prefix_original_call_changed')
    proof = _actual_call_proof(original, index, original_body, request, phase, cache, (*seen, directory))
    if origin == ORIGIN:
        if any(record.get(k) != v for k, v in _budget(original, index).items()):
            raise dg.GenerationError('document_author_prefix_original_budget_changed')
    elif record.get('actual_call_proof') != proof:
        raise dg.GenerationError('document_author_prefix_transitive_budget_proof_changed')
    hop = {'directory': str(directory), 'receipt_file_sha256': stage._hash_file(directory / RECEIPT),
        'request_file_sha256': stage._hash_file(directory / 'request.json'),
        'source_provenance_file_sha256': stage._hash_file(directory / 'source_provenance.json'),
        'intent_file_sha256': stage._hash_file(directory / f'call_{index}.started.json'),
        'response_file_sha256': record['response_file_sha256']}
    return {**proof, 'adoption_hops': [hop, *proof['adoption_hops']]}


def _author_request(body, plan, plan_row):
    projected = dg.replay_document_plan(plan, plan_row, body['inventory'])
    return dg.frozen_page_request(plan, plan_row, projected['pages'][0]['page_id'], body['inventory'],
        **({'material_context_profile': body['material_context_profile']}
           if 'material_context_profile' in body else {}))


def _first_review(body, author, row):
    return dg.frozen_page_review_request(author, row, body['reviewer_pin'],
        **({'material_context_profile': body['material_context_profile']}
           if 'material_context_profile' in body else {}),
        **({'document_page_repair_profile': body['document_page_repair_profile']}
           if 'document_page_repair_profile' in body else {}))


def _author_prefix(parent, body, seed, rows):
    if body.get('kind') != 'intro_deck':
        raise dg.GenerationError('document_author_prefix_requires_intro_scope')
    requests = _source_requests(body, seed)
    source_count, count, proofs = len(requests), 0, []
    cache = {parent: body}
    for i, row in enumerate(rows[:source_count], 1):
        try:
            if 'error' in row: break
            _replay(requests[i-1], row, body['inventory'], source_count, i)
            proofs.append(_actual_call_proof(parent, i, body, requests[i-1], 'document_source_index', cache))
        except (ValueError, KeyError, TypeError, IndexError, OSError):
            break
        count += 1
    if count < source_count:
        return count, requests, proofs
    plan = _plan_request(body, seed, rows[:source_count]); requests.append(plan)
    if len(rows) <= source_count: return count, requests, proofs
    try:
        if 'error' in rows[source_count]: return count, requests, proofs
        dg.replay_document_plan(plan, rows[source_count], body['inventory'])
        proofs.append(_actual_call_proof(parent, source_count+1, body, plan, 'document_plan', cache))
    except (ValueError, KeyError, TypeError, IndexError, OSError):
        return count, requests, proofs
    count += 1
    author = _author_request(body, plan, rows[source_count]); requests.append(author)
    if len(rows) <= source_count+1: return count, requests, proofs
    try:
        if 'error' in rows[source_count+1]: return count, requests, proofs
        dg.replay_document_page(author, rows[source_count+1])
        proofs.append(_actual_call_proof(parent, source_count+2, body, author, 'document_page', cache))
    except (ValueError, KeyError, TypeError, IndexError, OSError):
        return count, requests, proofs
    count += 1
    requests.append(_first_review(body, author, rows[source_count+1]))
    return count, requests, proofs


def _review_boundary(parent, body, rows, index, old_review, new_review):
    if dg.request_json(old_review) == dg.request_json(new_review):
        raise dg.GenerationError('document_author_prefix_cannot_retry_identical_review')
    if len(rows) <= index and not (parent / f'call_{index+1}.started.json').exists(): return None
    _actual_intent(parent, index+1, body, old_review, 'document_page_review')
    if len(rows) > index:
        row = rows[index]
        if ([row.get('task'), row.get('instruction'), row.get('input'), row.get('schema')] !=
                dg.request_json(old_review) or row.get('model') != old_review[2]['model_pin']['name'] or
                row.get('response_hash') != dg.digest(row.get('raw_response'))):
            raise dg.GenerationError('document_author_prefix_failed_review_raw_changed')
        if 'error' not in row and dg.replay_document_review(old_review, row)['verdict'] == 'pass':
            raise dg.GenerationError('document_author_prefix_cannot_discard_passing_review')
    result = {'parent_next_request_digest': dg.canonical_digest(dg.request_json(old_review)),
              'child_next_request_digest': dg.canonical_digest(dg.request_json(new_review))}
    for name in (f'call_{index+1}.started.json', f'response_{index+1}.json',
                 f'budget_{index+1}.started.json', f'budget_{index+1}.completed.json'):
        if (parent / name).exists(): result[name + '_sha256'] = stage._hash_file(parent / name)
    return result


def _v2_requests(body, seed, rows):
    requests = _source_requests(body, seed)
    n = len(requests)
    plan = _plan_request(body, seed, rows[:n]); requests.append(plan)
    author = _author_request(body, plan, rows[n]); requests.append(author)
    requests.append(_first_review(body, author, rows[n+1]))
    return requests


def _verify_v2(root, body, attempts, lineage):
    receipt = stage._read(root / RECEIPT)
    if (receipt.get('contract') != CONTRACT_V2 or receipt.get('adoption_digest') !=
            dg.canonical_digest({k: v for k, v in receipt.items() if k != 'adoption_digest'}) or
            receipt.get('new_run_binding_digest') != body['run_binding_digest'] or
            receipt.get('new_request_file_sha256') != stage._hash_file(root / 'request.json') or
            type(receipt.get('new_model_invocations')) is not int or receipt['new_model_invocations'] != 0 or
            type(receipt.get('new_physical_requests')) is not int or receipt['new_physical_requests'] != 0 or
            any(receipt.get(k) != 'not_established' for k in
                ('financial_validation', 'regulatory_approval', 'investor_approval'))):
        raise dg.GenerationError('document_author_prefix_receipt_changed')
    parent = stage._no_links(receipt['parent_directory'])
    parent_body, seed, rows = stage._load_run(parent, _lineage=lineage)
    _repair_scope(body, parent_body)
    count, old_requests, proofs = _author_prefix(parent, parent_body, seed, rows)
    required = len(parent_body['inventory']['source_map_topology']) + 2
    adopted = [i for i in range(1, len(attempts)+1) if
               stage._read(root / f'call_{i}.started.json').get('execution_origin') in (ORIGIN, ORIGIN_V2)]
    if (type(receipt.get('adopted_response_count')) is not int or count != required or
            receipt['adopted_response_count'] != required or len(attempts) < required or
            adopted != list(range(1, required+1)) or len(receipt.get('records', [])) != required):
        raise dg.GenerationError('document_author_prefix_complete_source_plan_author_required')
    child_requests = _v2_requests(body, seed, rows)
    if ([dg.request_json(r) for r in child_requests[:required]] !=
            [dg.request_json(r) for r in old_requests[:required]]):
        raise dg.GenerationError('document_author_prefix_adopted_request_changed')
    if (receipt.get('parent_run_binding_digest') != parent_body['run_binding_digest'] or
            receipt.get('parent_request_file_sha256') != stage._hash_file(parent / 'request.json') or
            receipt.get('parent_source_provenance_sha256') != stage._source_proof(parent, parent_body) or
            receipt.get('new_source_provenance_sha256') != stage._source_proof(root, body) or
            receipt.get('changed_unadopted_request') != _review_boundary(parent, parent_body, rows, required,
                old_requests[required], child_requests[required])):
        raise dg.GenerationError('document_author_prefix_parent_source_or_failed_review_changed')
    for i, record in enumerate(receipt['records'], 1):
        phase = 'document_source_index' if i <= required-2 else ('document_plan' if i == required-1 else 'document_page')
        if (record.get('response_id') != f'response_{i}' or record.get('phase') != phase or
                record.get('request_digest') != dg.canonical_digest(dg.request_json(old_requests[i-1])) or
                record.get('response_file_sha256') != stage._hash_file(parent / f'response_{i}.json') or
                record['response_file_sha256'] != stage._hash_file(root / f'response_{i}.json') or
                record.get('parent_intent_file_sha256') != stage._hash_file(parent / f'call_{i}.started.json') or
                record.get('actual_call_proof') != proofs[i-1] or
                stage._read(root / f'call_{i}.started.json') != _v2_intent(body, receipt, record, old_requests[i-1]) or
                any((root / f'budget_{i}.{s}.json').exists() for s in ('started', 'completed'))):
            raise dg.GenerationError('document_author_prefix_raw_actual_proof_or_fake_budget_changed')
        if phase == 'document_page':
            dg.replay_document_page(old_requests[i-1], attempts[i-1])
        else:
            _replay(old_requests[i-1], attempts[i-1], body['inventory'], required-2, i)


def _adopt_v2(root, parent_directory, *, count=None):
    parent = stage._no_links(parent_directory)
    if root == parent: raise dg.GenerationError('document_prefix_requires_distinct_branches')

    def preflight():
        body, seed, existing = stage._load_run(root)
        if (existing or list(root.glob('call_*.started.json')) or list(root.glob('budget_*.json')) or
                (root / RECEIPT).exists() or (root / 'source_map_prefix_adoption.json').exists()):
            raise dg.GenerationError('document_prefix_requires_unstarted_target')
        parent_body, parent_seed, rows = stage._load_run(parent)
        _repair_scope(body, parent_body)
        successful, old_requests, proofs = _author_prefix(parent, parent_body, parent_seed, rows)
        required = len(parent_body['inventory']['source_map_topology']) + 2
        if successful != required or (count is not None and (type(count) is not int or count != required)):
            raise dg.GenerationError('document_author_prefix_complete_source_plan_author_required')
        requests = _v2_requests(body, seed, rows)
        if ([dg.request_json(r) for r in requests[:required]] !=
                [dg.request_json(r) for r in old_requests[:required]]):
            raise dg.GenerationError('document_author_prefix_adopted_request_changed')
        boundary = _review_boundary(parent, parent_body, rows, required, old_requests[required], requests[required])
        records, originals = [], []
        for i in range(1, required+1):
            raw = stage._bytes(parent / f'response_{i}.json')
            phase = 'document_source_index' if i <= required-2 else ('document_plan' if i == required-1 else 'document_page')
            records.append({'response_id': f'response_{i}', 'phase': phase,
                'response_file_sha256': hashlib.sha256(raw).hexdigest(),
                'parent_intent_file_sha256': stage._hash_file(parent / f'call_{i}.started.json'),
                'request_digest': dg.canonical_digest(dg.request_json(old_requests[i-1])),
                'actual_call_proof': proofs[i-1]})
            originals.append(raw)
        receipt = {'contract': CONTRACT_V2, 'parent_directory': str(parent),
            'parent_run_binding_digest': parent_body['run_binding_digest'],
            'parent_request_file_sha256': stage._hash_file(parent / 'request.json'),
            'parent_source_provenance_sha256': stage._source_proof(parent, parent_body),
            'new_run_binding_digest': body['run_binding_digest'],
            'new_request_file_sha256': stage._hash_file(root / 'request.json'),
            'new_source_provenance_sha256': stage._source_proof(root, body),
            'adopted_response_count': required, 'records': records,
            'new_model_invocations': 0, 'new_physical_requests': 0,
            'financial_validation': 'not_established', 'regulatory_approval': 'not_established',
            'investor_approval': 'not_established'}
        if boundary is not None: receipt['changed_unadopted_request'] = boundary
        return body, requests, originals, {**receipt, 'adoption_digest': dg.canonical_digest(receipt)}

    expected = preflight()
    child_fd = os.open(root / 'advance.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    parent_fd = None
    try:
        parent_fd = os.open(parent / 'advance.lock', os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(child_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(parent_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise dg.GenerationError('document_prefix_parent_or_target_busy') from exc
        current = preflight()
        def signature(value):
            body, requests, originals, receipt = value
            return body, [dg.request_json(r) for r in requests], originals, receipt
        if signature(current) != signature(expected):
            raise dg.GenerationError('document_prefix_preflight_changed')
        body, requests, originals, receipt = current
        stage._write_new(root / RECEIPT, receipt)
        for i, (record, raw) in enumerate(zip(receipt['records'], originals), 1):
            stage._write_new(root / f'call_{i}.started.json', _v2_intent(body, receipt, record, requests[i-1]))
            stage._write_bytes_new(root / f'response_{i}.json', raw)
        loaded_body, _, rows = stage._load_run(root)
        _verify_v2(root, loaded_body, rows, (root,))
        return {'state': 'document_author_prefix_adopted', 'adopted_model_responses': receipt['adopted_response_count'],
            'new_model_invocations': 0, 'new_physical_requests': 0,
            'adoption_digest': receipt['adoption_digest'], 'parent_directory': str(parent)}
    finally:
        if parent_fd is not None: os.close(parent_fd)
        os.close(child_fd)
