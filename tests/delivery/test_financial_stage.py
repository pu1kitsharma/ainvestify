"""Private room financial bridge tests use only synthetic bytes and a fake worker."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from agents.analysis.workbook_reconciliation import SCOPE
from agents.inference.model_authorship import digest
from delivery import financial_stage as stage
from schemas import Document


class FakeStore:
    conn = object()

    def __init__(self, document):
        self.document = document
        self.room = SimpleNamespace(id='room-a', deal_id='deal-a')

    def get_workspace(self, tenant, workspace_id):
        return self.room if (tenant, workspace_id) == ('tenant-a', 'room-a') else None

    def get_document(self, tenant, document_id):
        return self.document if (tenant, document_id) == ('tenant-a', self.document.id) else None


def setup(tmp_path, monkeypatch):
    source = tmp_path / 'uploaded.xlsx'
    source.write_bytes(b'synthetic workbook bytes; parsed by a fake worker only')
    document = Document(id='doc-a', tenant_id='tenant-a', deal_id='deal-a',
                        filename='uploaded.xlsx', type='xlsx', storage_uri=str(source))
    store = FakeStore(document)
    job = {'id': 'job-a', 'tenant_id': 'tenant-a', 'workspace_id': 'room-a',
           'actor_id': 'actor-a', 'input_revision': 'revision-a'}
    monkeypatch.setattr(stage, 'has_access', lambda *args: True)
    from api.routers import rooms
    monkeypatch.setattr(rooms, 'revision_for', lambda *args: 'revision-a')
    return store, job, document, source


def accepted_worker(command, root, **options):
    assert options['local_model'] is True
    request = json.loads((root / 'request.json').read_text())
    model = json.loads((root / 'model.json').read_text())['profiles']['financial']
    bound = {'workbook_sha256': request['workbook_sha256'],
             'as_of_date': request['as_of_date'], 'model': model}
    bound['request_digest'] = digest(bound)
    (root / 'binding.json').write_text(json.dumps(bound))
    (root / 'result.json').write_text(json.dumps({
        'state': 'partial_evidence', 'analysis_state': 'analysed',
        'request_digest': bound['request_digest'],
        'workbook_sha256': request['workbook_sha256'],
        'findings': [{'text': 'Model-authored synthetic finding'}],
        'unknowns': ['Audit status unknown'], **SCOPE,
        'artifact_status': 'diagnostic_partial_evidence_no_release',
        'independent_review': 'pending'}))


def run(store, job, document, root):
    return stage.run_financial_stage(store, job, document, model_name='qwen3.5:9b',
                                     as_of_date='2026-10-03', stage_root=root)


def test_scoped_request_replays_exact_bytes_and_returns_only_partial_evidence(tmp_path, monkeypatch):
    store, job, document, source = setup(tmp_path, monkeypatch)
    calls = []

    def worker(command, root, **options):
        calls.append(1)
        accepted_worker(command, root, **options)

    monkeypatch.setattr(stage, 'run_private', worker)
    root = tmp_path / 'private-stage'
    first = run(store, job, document, root)
    assert first['state'] == 'partial_evidence'
    assert first['financial_validation'] == 'not_established'
    assert first['artifact_status'] == 'diagnostic_partial_evidence_no_release'
    assert first['findings'] == [{'text': 'Model-authored synthetic finding'}]
    assert first['document_id'] == 'doc-a'
    binding = json.loads((root / 'adapter_binding.json').read_text())
    assert binding['input_revision'] == 'revision-a'
    assert binding['document_id'] == 'doc-a'
    assert binding['workbook_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (root / 'source.xlsx').read_bytes() == source.read_bytes()
    assert run(store, job, document, root) == first
    assert len(calls) == 2  # the worker replays saved attempts without new inference


def test_changed_source_or_model_or_revision_blocks_before_worker(tmp_path, monkeypatch):
    store, job, document, source = setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(stage, 'run_private', lambda *a, **k: (calls.append(1), accepted_worker(*a, **k)))
    root = tmp_path / 'private-stage'
    assert run(store, job, document, root)['state'] == 'partial_evidence'
    source.write_bytes(b'different synthetic bytes')
    assert run(store, job, document, root)['reason'] == 'financial_request_differs_from_bound_request'
    source.write_bytes((root / 'source.xlsx').read_bytes())
    changed_model = stage.run_financial_stage(store, job, document, model_name='qwen3.5:4b',
        as_of_date='2026-10-03', stage_root=root)
    assert changed_model['reason'] == 'financial_request_differs_from_bound_request'
    job['input_revision'] = 'revision-b'
    assert run(store, job, document, root)['reason'] == 'input_revision_changed'
    assert len(calls) == 1


def test_foreign_document_and_result_cannot_escape_partial_scope(tmp_path, monkeypatch):
    store, job, document, source = setup(tmp_path, monkeypatch)
    foreign = document.model_copy(update={'deal_id': 'another-deal'})
    monkeypatch.setattr(stage, 'run_private', lambda *a, **k: pytest.fail('worker must not run'))
    assert run(store, job, foreign, tmp_path / 'private-stage')['reason'] == 'workbook_outside_room_scope'
    assert not (tmp_path / 'private-stage').exists()
    wrong_type = stage.run_financial_stage(store, job, document.model_copy(update={'type': 'pdf'}),
        model_name='qwen3.5:9b', as_of_date='2026-10-03',
        stage_root=tmp_path / 'private-stage')
    assert wrong_type['reason'] == 'workbook_outside_room_scope'


def test_worker_validation_claim_is_not_exposed(tmp_path, monkeypatch):
    store, job, document, _ = setup(tmp_path, monkeypatch)

    def worker(command, root, **options):
        accepted_worker(command, root, **options)
        path = root / 'result.json'
        result = json.loads(path.read_text())
        result['financial_validation'] = 'passed'
        path.write_text(json.dumps(result))

    monkeypatch.setattr(stage, 'run_private', worker)
    result = run(store, job, document, tmp_path / 'private-stage')
    assert result['state'] == 'blocked'
    assert result['reason'] == 'private_financial_result_binding_failed'
    assert result['financial_validation'] == 'not_established'
