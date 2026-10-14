"""One fictional source: reuse actual-style raw receipts, never training gold."""
from copy import deepcopy
import hashlib
import json

import pytest

from agents.research import document_generation as dg
from agents.research import document_source_index as indexer
from agents.research.document_context_capacity import MATERIAL_CONTEXT_PROFILE_32K
from delivery import document_generation_stage as stage
from delivery import document_prefix_adoption as adoption
from tests.delivery.test_document_generation_stage_source_maps import full_source
from tests.research.test_document_generation import PIN
from tests.research.test_document_source_index import actual_mock_record

SMALL = {'name': 'qwen3.5:4b', 'digest': 'b' * 64}


def prepare(root, manifest, proof, *, planner=PIN, reader=None, source32=True, material=None, assignment=None,
            repair=None):
    stage.prepare_document_generation(root, [manifest], PIN, PIN, 'intro_deck',
        catalog_encoding=dg.CATALOG_ENCODING_V6, qualification_context_profile='complete-literal-context-v2',
        planning_schema_profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5,
        planning_context_profile=dg.PLAN_CONTEXT_PROFILE_32K, planner_pin=planner,
        **({'source_reader_pin': reader} if reader is not None else {}),
        **({'source_context_profile': indexer.SOURCE_CONTEXT_PROFILE_32K} if source32 else {}),
        source_index_encoding=indexer.SOURCE_INDEX_ENCODING_V2,
        **({'material_context_profile': material} if material is not None else {}),
        **({'planning_assignment_profile': assignment} if assignment is not None else {}),
        **({'document_page_repair_profile': repair} if repair is not None else {}))
    stage._write_new(root / 'source_provenance.json', proof)


def save(root, body, req, row, phase):
    n = int(row['id'].split('_')[1])
    intent = {'contract': dg.CONTRACT, 'run_binding_digest': body['run_binding_digest'],
        'phase': phase, 'page_id': req[2]['planned_page']['page_id'] if phase.startswith('document_page') else None,
        'model_pin': req[2]['model_pin'],
        'request_digest': dg.canonical_digest(dg.request_json(req))}
    stage._write_new(root / f'call_{n}.started.json', intent)
    stage._write_new(root / f'response_{n}.json', row)
    start = {'max_seconds': 105, 'max_calls': 1, 'max_requests': 6, 'calls': 0, 'requests': 0,
        'elapsed_seconds': 0, 'reserved_cost_usd': 0}
    stage._write_new(root / f'budget_{n}.started.json', start)
    stage._write_new(root / f'budget_{n}.completed.json', {**start, 'calls': 1, 'requests': 1, 'elapsed_seconds': 1})


def test_changed_global_planner_reuses_only_raw_source_and_detects_tamper_and_context_change(tmp_path, monkeypatch):
    raw, manifest = full_source(blank_pages=0, return_bytes=True)
    source = tmp_path / 'source.pptx'; source.write_bytes(raw)
    manifest_path = tmp_path / 'document_evidence_manifest.json'; manifest_path.write_text(json.dumps(manifest))
    manifest_receipt = tmp_path / 'document_manifest_receipt.json'
    manifest_receipt.write_text(json.dumps({'binding': manifest['binding'],
        'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'manifest_digest': manifest['manifest_digest']}))
    proof = {'sources': [{'manifest_path': str(manifest_path),
        'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'original_path': str(source), 'original_sha256': hashlib.sha256(raw).hexdigest()}]}
    parent = tmp_path / 'parent'; prepare(parent, manifest, proof)
    body, seed, _ = stage._load_run(parent)
    req = dg._source_index_requests_from_seed(seed, body['inventory'])[0]
    answer = {'group_id': 'G1', 'focus_unit_ids': ['U1'], 'visual_semantics': 'unassessed',
        'scope_status': 'local_source_selection_proposal_not_diligence'}
    row = actual_mock_record(req, answer, 1)
    save(parent, body, req, row, 'document_source_index')
    plan = dg._source_index_plan_request(seed, body['inventory'], [row],
        source_index_encoding=body['source_index_encoding'])
    failed = {'id': 'response_2', 'task': plan[0], 'instruction': plan[1], 'input': plan[2],
        'schema': plan[3].model_json_schema(), 'model': PIN['name'], 'raw_response': '{"partial":',
        'response_hash': dg.digest('{"partial":'), 'error': 'synthetic bounded plan cancellation'}
    save(parent, body, plan, failed, 'document_plan')
    (parent / 'advance.lock').touch(mode=0o600)
    original = {f.name: f.read_bytes() for f in parent.iterdir() if f.is_file()}
    count, requests, _ = adoption.verified_document_prefix(parent)
    assert count == 1 and len(requests) == 2
    same = tmp_path / 'same'; prepare(same, manifest, proof, material=MATERIAL_CONTEXT_PROFILE_32K)
    unchanged = {f.name: f.read_bytes() for f in same.iterdir() if f.is_file()}
    with pytest.raises(dg.GenerationError, match='identical_failed_or_orphan'):
        adoption.adopt_document_prefix(same, parent)
    assert {f.name: f.read_bytes() for f in same.iterdir() if f.is_file()} == unchanged
    wrong_context = tmp_path / 'different-source'; prepare(wrong_context, manifest, proof, source32=False)
    unchanged = {f.name: f.read_bytes() for f in wrong_context.iterdir() if f.is_file()}
    with pytest.raises(dg.GenerationError, match='scope_pins_inventory_or_source_context'):
        adoption.adopt_document_prefix(wrong_context, parent)
    assert {f.name: f.read_bytes() for f in wrong_context.iterdir() if f.is_file()} == unchanged
    assignment_child = tmp_path / 'new-assignment'
    prepare(assignment_child, manifest, proof, assignment='page-topics-v1')
    new_body, new_seed, _ = stage._load_run(assignment_child)
    assert dg.request_json(new_seed) == dg.request_json(seed)
    result = adoption.adopt_document_prefix(assignment_child, parent)
    assert result['adopted_model_responses'] == 1 and result['new_model_invocations'] == 0
    assert (assignment_child / 'response_1.json').read_bytes() == (parent / 'response_1.json').read_bytes()
    assert not (assignment_child / 'response_2.json').exists()
    assignment_receipt = stage._read(assignment_child / adoption.RECEIPT)
    assert assignment_receipt['changed_unadopted_request']['parent_next_request_digest'] != assignment_receipt['changed_unadopted_request']['child_next_request_digest']
    child = tmp_path / 'child'
    prepare(child, manifest, proof, planner=SMALL, reader=PIN, material=MATERIAL_CONTEXT_PROFILE_32K)
    result = adoption.adopt_document_prefix(child, parent)
    assert result['adopted_model_responses'] == 1
    assert result['new_model_invocations'] == result['new_physical_requests'] == 0
    assert (child / 'response_1.json').read_bytes() == (parent / 'response_1.json').read_bytes()
    assert not (child / 'response_2.json').exists() and not list(child.glob('budget_*.json'))
    assert {f.name: f.read_bytes() for f in parent.iterdir() if f.is_file()} == original
    child_body, _, attempts = stage._load_run(child)
    adoption.verify_document_prefix_adoption(child, child_body, attempts, (child,))
    budget = parent / 'budget_1.completed.json'; exact_budget = budget.read_bytes()
    changed = json.loads(exact_budget); changed['elapsed_seconds'] = 106
    budget.write_text(json.dumps(changed))
    with pytest.raises(dg.GenerationError):
        adoption.verify_document_prefix_adoption(child, child_body, attempts, (child,))
    budget.write_bytes(exact_budget)
    copied = child / 'response_1.json'; exact_raw = copied.read_bytes()
    changed = json.loads(exact_raw); changed['raw_response'] += ' '
    changed['response_hash'] = dg.digest(changed['raw_response'])
    copied.write_text(json.dumps(changed))
    with pytest.raises(dg.GenerationError, match='raw_intent_or_budget_changed'):
        adoption.verify_document_prefix_adoption(child, child_body, [changed], (child,))
    copied.write_bytes(exact_raw)
    receipt = stage._read(child / adoption.RECEIPT)
    assert receipt['changed_unadopted_request']['parent_next_request_digest'] != receipt['changed_unadopted_request']['child_next_request_digest']
    assert receipt['financial_validation'] == receipt['investor_approval'] == 'not_established'
    from scripts import evaluate_reference_generation as cli
    monkeypatch.setattr(cli, 'PRIVATE_ROOT', tmp_path)
    sibling = parent / 'other_private_tenant.json'; sibling.write_text('{"private":true}')
    reads = cli._document_adoption_read_literals(child)
    assert sibling not in reads and parent in reads
    assert parent / 'response_1.json' in reads and parent / 'budget_1.completed.json' in reads
    assert manifest_path in reads and manifest_receipt in reads and source in reads


def test_derived_source_and_actual_plan_author_reuse_preserves_budgets_and_excludes_failed_review(tmp_path, monkeypatch):
    raw, manifest = full_source(blank_pages=0, return_bytes=True)
    source = tmp_path / 'source.pptx'; source.write_bytes(raw)
    path = tmp_path / 'document_evidence_manifest.json'; path.write_text(json.dumps(manifest))
    manifest_receipt = tmp_path / 'document_manifest_receipt.json'
    manifest_receipt.write_text(json.dumps({'binding': manifest['binding'],
        'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'manifest_digest': manifest['manifest_digest']}))
    proof = {'sources': [{'manifest_path': str(path),
        'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'original_path': str(source), 'original_sha256': hashlib.sha256(raw).hexdigest()}]}
    original = tmp_path / 'actual-source'; prepare(original, manifest, proof)
    body, seed, _ = stage._load_run(original)
    read = dg._source_index_requests_from_seed(seed, body['inventory'])[0]
    read_row = actual_mock_record(read, {'group_id': 'G1', 'focus_unit_ids': ['U1'],
        'visual_semantics': 'unassessed', 'scope_status': 'local_source_selection_proposal_not_diligence'}, 1)
    save(original, body, read, read_row, 'document_source_index')
    failed_plan = adoption._plan_request(body, seed, [read_row])
    failed = {'id': 'response_2', 'task': failed_plan[0], 'instruction': failed_plan[1],
        'input': failed_plan[2], 'schema': failed_plan[3].model_json_schema(), 'model': PIN['name'],
        'raw_response': '{"partial":', 'response_hash': dg.digest('{"partial":'), 'error': 'bounded failure'}
    save(original, body, failed_plan, failed, 'document_plan')
    (original / 'advance.lock').touch(mode=0o600)
    common = dict(planner=SMALL, reader=PIN, material=MATERIAL_CONTEXT_PROFILE_32K,
                  assignment=dg.SINGLE_SOURCE_OUTLINE_ASSIGNMENT_PROFILE)
    parent = tmp_path / 'derived-parent'; prepare(parent, manifest, proof, **common)
    adoption.adopt_document_prefix(parent, original)
    parent_body, parent_seed, rows = stage._load_run(parent)
    plan = adoption._plan_request(parent_body, parent_seed, rows)
    plan_row = actual_mock_record(plan, {'p': [{'t': ['customers_and_traction'], 'l': 'evidence',
        'e': ['G1'], 's': 'limited'}]}, 2)
    save(parent, parent_body, plan, plan_row, 'document_plan')
    author = dg.frozen_page_request(plan, plan_row, 'P1', parent_body['inventory'],
        material_context_profile=MATERIAL_CONTEXT_PROFILE_32K)
    authored = actual_mock_record(author, {'page_id': 'P1', 'title': 'Supplied pilot',
        'claims': [{'text': 'The company completed a limited pilot in 2024.', 'basis': 'reported',
            'evidence': [{'unit_id': 'U1', 'quote': 'a limited pilot in 2024'}]}], 'table_labels': []}, 3)
    save(parent, parent_body, author, authored, 'document_page')
    review = dg.frozen_page_review_request(author, authored, PIN,
        material_context_profile=MATERIAL_CONTEXT_PROFILE_32K)
    rejected = actual_mock_record(review, {'verdict': 'revise', 'financial_status': 'not_established',
        'issues': [{'claim_index': 0, 'exact_claim_phrase': 'The company completed', 'unit_id': 'U1',
            'exact_source_quote': 'The source reports a limited pilot in 2024.', 'kind': 'scope'}]}, 4)
    save(parent, parent_body, review, rejected, 'document_page_review')
    before = {f.name: f.read_bytes() for f in parent.iterdir() if f.is_file()}
    count, requests, _ = adoption.verified_document_prefix(parent, include_first_author=True)
    assert count == 3 and len(requests) == 4
    child = tmp_path / 'review-continuation'
    prepare(child, manifest, proof, repair=adoption.REPAIR_PROFILE, **common)
    result = adoption.adopt_document_prefix(child, parent)
    assert result['adopted_model_responses'] == 3
    assert result['new_model_invocations'] == result['new_physical_requests'] == 0
    assert not list(child.glob('budget_*.json')) and not (child / 'response_4.json').exists()
    assert {f.name: f.read_bytes() for f in parent.iterdir() if f.is_file()} == before
    receipt = stage._read(child / adoption.RECEIPT)
    assert receipt['contract'] == adoption.CONTRACT_V2
    actual = receipt['records'][0]['actual_call_proof']
    assert actual['actual_execution']['directory'] == str(original)
    assert actual['adoption_hops'][0]['directory'] == str(parent)
    assert receipt['records'][2]['actual_call_proof']['actual_execution']['directory'] == str(parent)
    for i in range(1, 4):
        assert (child / f'response_{i}.json').read_bytes() == (parent / f'response_{i}.json').read_bytes()
    child_body, child_seed, attempts = stage._load_run(child)
    future = dg.generation_progress(child_seed, child_body['inventory'], attempts, PIN,
        **stage._qualification_context_profile(child_body))
    assert future['phase'] == 'document_page_review'
    assert dg.request_json(future['request']) != dg.request_json(review)
    assert dg.request_json(adoption._author_request(child_body, requests[1], plan_row)) == dg.request_json(author)
    assert receipt['changed_unadopted_request']['response_4.json_sha256'] == hashlib.sha256((parent/'response_4.json').read_bytes()).hexdigest()
    from scripts import evaluate_reference_generation as cli
    monkeypatch.setattr(cli, 'PRIVATE_ROOT', tmp_path)
    inspected = []
    checked_manifest = cli._checked_manifest
    def checked_once(source_path):
        inspected.append(source_path)
        return checked_manifest(source_path)
    monkeypatch.setattr(cli, '_checked_manifest', checked_once)
    fresh_proof = cli._check_run_provenance(child)
    assert inspected == [path]
    sibling = parent / 'other_private_tenant.json'; sibling.write_text('{"private":true}')
    reads = cli._adoption_read_literals(child, verified_source_provenance=fresh_proof)
    assert inspected == [path]  # Shared exact derivative is not reconstructed per ancestor.
    assert sibling not in reads
    assert path in reads and manifest_receipt in reads and source in reads
    assert original / 'budget_1.completed.json' in reads and parent / 'response_4.json' in reads
    changed_raw = parent / 'response_3.json'; exact_raw = changed_raw.read_bytes()
    altered = json.loads(exact_raw); altered['raw_response'] += ' '
    altered['response_hash'] = dg.digest(altered['raw_response'])
    changed_raw.write_text(json.dumps(altered))
    with pytest.raises(dg.GenerationError): cli._check_run_provenance(child)
    changed_raw.write_bytes(exact_raw)
    budget = original / 'budget_1.completed.json'; exact = budget.read_bytes()
    altered = json.loads(exact); altered['elapsed_seconds'] = 106; budget.write_text(json.dumps(altered))
    with pytest.raises(dg.GenerationError): cli._check_run_provenance(child)
    budget.write_bytes(exact)
    stage._write_new(child / 'budget_1.completed.json', {'calls': 1, 'requests': 1})
    with pytest.raises(dg.GenerationError, match='fake_budget'):
        stage._load_run(child)
    (child / 'budget_1.completed.json').unlink()
    wrong = tmp_path / 'changed-author-context'
    prepare(wrong, manifest, proof, repair=adoption.REPAIR_PROFILE,
        planner=SMALL, reader=PIN, assignment=dg.SINGLE_SOURCE_OUTLINE_ASSIGNMENT_PROFILE)
    before_wrong = {f.name: f.read_bytes() for f in wrong.iterdir() if f.is_file()}
    with pytest.raises(dg.GenerationError, match='only_future_review_profile'):
        adoption.adopt_document_prefix(wrong, parent)
    assert {f.name: f.read_bytes() for f in wrong.iterdir() if f.is_file()} == before_wrong
