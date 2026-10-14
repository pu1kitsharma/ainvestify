"""Mocked file export tests for recorded-prefix fidelity and immutable caching."""
from copy import deepcopy
import hashlib
import json

import pytest

from agents.research import document_generation as generation
from delivery import document_generation_stage as stage
from scripts import private_reference_generation_worker as worker
from tests.research.test_document_generation import PIN, manifest, record, planned, author


def prepared_run(root):
    stage.prepare_document_generation(root, [manifest()], PIN, PIN, 'intro_deck',
        catalog_encoding=generation.CATALOG_ENCODING_V2)
    body, request, _ = stage._load_run(root)
    return body, request


def store(root, body, request, answer, number):
    row = record(request, answer, number)
    stage._write_new(root / f'call_{number}.started.json', {
        'run_binding_digest': body['run_binding_digest'],
        'request_digest': generation.canonical_digest(generation.request_json(request))})
    stage._write_new(root / f'response_{number}.json', row)
    return row


def reviewed_prefix(root):
    body, request = prepared_run(root)
    choice = planned(body['inventory'])
    choice['pages'].append({**deepcopy(choice['pages'][0]), 'page_id': 'P2', 'topic': 'risks_and_countercase'})
    choice['unsupported_topics'].remove('risks_and_countercase')
    plan = store(root, body, request, choice, 1)
    page_request = generation.frozen_page_request(request, plan, 'P1', body['inventory'])
    authored = store(root, body, page_request, author(page_request), 2)
    review_request = generation.frozen_page_review_request(page_request, authored, PIN)
    store(root, body, review_request, {'verdict': 'pass', 'issues': [], 'financial_status': 'not_established'}, 3)
    return body, page_request, authored


def mock_renderer(captured):
    def render(title, sections, *, kind, format):
        captured.append({'title': title, 'sections': deepcopy(sections), 'kind': kind, 'format': format})
        return json.dumps([title, sections, kind, format], ensure_ascii=False).encode('utf-8')
    return render


def test_failed_plan_cannot_create_artifact_or_reach_renderer(tmp_path, monkeypatch):
    root = tmp_path / 'failed'
    body, request = prepared_run(root)
    # Actual overflow-shaped context receipt is the failure under test; raw
    # output is retained and cannot be rendered as an accepted source plan.
    row = store(root, body, request, planned(body['inventory']), 1)
    row['routing']['prompt_tokens'] = 8194
    (root / 'response_1.json').write_text(json.dumps(row))
    def no_render(*args, **kwargs):
        pytest.fail('Failed planning must not produce investor files')
    monkeypatch.setattr(worker, 'render_evidence_document', no_render)
    with pytest.raises(ValueError, match='context integrity'):
        worker.export_prefix(root)
    assert not list(root.glob('draft_prefix_*'))
    assert (root / 'response_1.json').is_file()


def test_partial_reviewed_prefix_projects_exact_recorded_prose_and_remains_unapproved(tmp_path, monkeypatch):
    root = tmp_path / 'partial'
    body, page_request, authored = reviewed_prefix(root)
    captured = []
    monkeypatch.setattr(worker, 'render_evidence_document', mock_renderer(captured))
    result = worker.export_prefix(root)
    assert result['state'] == 'draft_exported' and result['authored_pages'] == 1 and result['planned_pages'] == 2
    assert result['generation_state'] == 'needs_call'
    expected = generation.renderable_document_page(page_request, authored)
    assert [item['format'] for item in captured] == ['pptx', 'pdf']
    assert all(item['sections'] == [expected] for item in captured)
    assert authored['answer']['claims'][0]['text'] in expected[1]
    folder = __import__('pathlib').Path(result['diagnostic_path'])
    receipt = stage._read(folder / 'export_receipt.json')
    assert receipt['complete_draft'] is False
    assert receipt['content_review'] == 'local_model_only_unqualified'
    assert receipt['release_status'] == 'draft_only'
    assert receipt['financial_validation'] == receipt['regulatory_approval'] == receipt['investor_approval'] == 'not_established'
    assert receipt['byte_receipt']['sections_digest'] == generation.canonical_digest([expected])
    assert receipt['byte_receipt']['page_receipts'][0]['author_response_hash'] == authored['response_hash']
    assert receipt['byte_receipt']['inventory_revision'] == body['inventory']['inventory_revision']
    for entry in receipt['byte_receipt']['files']:
        file = folder / ('draft.' + entry['format'])
        assert hashlib.sha256(file.read_bytes()).hexdigest() == entry['sha256']
        assert file.stat().st_size == entry['byte_count']


def test_export_cache_refuses_altered_bytes_without_overwriting_them(tmp_path, monkeypatch):
    root = tmp_path / 'cached'
    reviewed_prefix(root)
    monkeypatch.setattr(worker, 'render_evidence_document', mock_renderer([]))
    first = worker.export_prefix(root)
    folder = __import__('pathlib').Path(first['diagnostic_path'])
    original_receipt = (folder / 'export_receipt.json').read_bytes()
    assert worker.export_prefix(root) == first
    changed = folder / 'draft.pdf'
    tampered = b'modified existing PDF bytes'
    changed.write_bytes(tampered)
    with pytest.raises(ValueError, match='export bytes changed'):
        worker.export_prefix(root)
    assert changed.read_bytes() == tampered
    assert (folder / 'export_receipt.json').read_bytes() == original_receipt
    assert len(list(root.glob('draft_prefix_*'))) == 1


def source_mapped_prefix(root, *, include_page, mandate=''):
    from tests.delivery.test_document_generation_stage_source_maps import full_source, map_answer
    stage.prepare_document_generation(root, [full_source()], PIN, PIN, 'intro_deck',
        catalog_encoding=generation.CATALOG_ENCODING_V3, mandate=mandate)
    body, _, _ = stage._load_run(root)
    maps = generation.frozen_source_map_requests(body['inventory'], PIN, kind='intro_deck', mandate=mandate)
    rows = [store(root, body, request, map_answer(request), number)
            for number, request in enumerate(maps, 1)]
    if not include_page:
        return body, rows, None, None
    plan_request = generation.frozen_document_request(body['inventory'], PIN, 'intro_deck',
        catalog_encoding=generation.CATALOG_ENCODING_V3, source_maps=rows, mandate=mandate)
    plan = store(root, body, plan_request, planned(body['inventory']), len(rows) + 1)
    page_request = generation.frozen_page_request(plan_request, plan, 'P1', body['inventory'])
    page = store(root, body, page_request, author(page_request), len(rows) + 2)
    review_request = generation.frozen_page_review_request(page_request, page, PIN)
    store(root, body, review_request, {'verdict': 'pass', 'issues': [],
        'financial_status': 'not_established'}, len(rows) + 3)
    return body, rows, page_request, page


def test_source_maps_alone_never_export_as_company_pages(tmp_path, monkeypatch):
    root = tmp_path / 'only-source-maps'
    source_mapped_prefix(root, include_page=False)
    def never(*args, **kwargs):
        pytest.fail('Source-reading proposals are not authored company pages')
    monkeypatch.setattr(worker, 'render_evidence_document', never)
    result = worker.export_prefix(root)
    assert result['reason'] == 'source_map_prefix_has_no_recorded_document_plan'
    assert result['generation_state'] == 'needs_call'
    assert not list(root.glob('draft_prefix_*'))


def test_source_mapped_export_uses_actual_plan_after_complete_map_prefix(tmp_path, monkeypatch):
    root = tmp_path / 'mapped-export'
    body, maps, page_request, page = source_mapped_prefix(root, include_page=True)
    captured = []
    monkeypatch.setattr(worker, 'render_evidence_document', mock_renderer(captured))
    result = worker.export_prefix(root)
    folder = __import__('pathlib').Path(result['diagnostic_path'])
    receipt = stage._read(folder / 'export_receipt.json')
    expected = generation.renderable_document_page(page_request, page)
    assert all(item['sections'] == [expected] for item in captured)
    assert receipt['byte_receipt']['plan_response_id'] == 'response_3'
    assert [item['response_id'] for item in receipt['source_map_receipts']] == ['response_1', 'response_2']
    assert [item['response_hash'] for item in receipt['source_map_receipts']] == [row['response_hash'] for row in maps]
    assert receipt['complete_draft'] is True and receipt['source_map_status'] == 'proposed_unreviewed'
    assert receipt['release_status'] == 'draft_only'
    assert receipt['financial_validation'] == receipt['regulatory_approval'] == receipt['investor_approval'] == 'not_established'


def test_historical_user_scope_reaches_source_reader_page_author_and_reviewer(tmp_path):
    mandate = 'Describe supplied historical evidence; never call old plans current results.'
    root = tmp_path / 'historical-scope'
    _, maps, page_request, _ = source_mapped_prefix(root, include_page=True, mandate=mandate)
    assert all(row['input']['mandate'] == mandate for row in maps)
    assert page_request[2]['mandate'] == mandate
    assert stage._read(root / 'response_3.json')['input']['mandate'] == mandate
    assert stage._read(root / 'response_5.json')['input']['mandate'] == mandate
