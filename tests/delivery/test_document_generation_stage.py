"""Durable exact replay / crash protection; all transport responses are mocked."""
from copy import deepcopy

import pytest

from agents.research import document_generation as dg
from delivery import document_generation_stage as stage
from tests.research.test_document_generation import PIN, manifest, planned, author, record


def test_bounded_advance_complete_reopen_makes_no_inference_and_enforces_scope(tmp_path, monkeypatch):
    root = tmp_path / 'private-run'
    stage.prepare_document_generation(root, [manifest()], PIN, PIN, 'pitch_deck')
    calls = []
    def fake_call(model, task, instruction, payload, schema, attempts, save):
        request = (task, instruction, payload, schema)
        calls.append(task)
        if task == 'document_plan_v1':
            answer = planned(stage._read(root / 'request.json')['inventory'])
        elif task == 'document_page_v1':
            answer = author(request)
        else:
            answer = {'verdict': 'pass', 'issues': [], 'financial_status': 'not_established'}
        attempts.append(record(request, answer, len(attempts) + 1))
        save()
    monkeypatch.setattr(stage, 'recorded_call', fake_call)
    advance = lambda: stage.advance_document_generation(root, tenant_id='tenant', deal_id='deal',
        installed_digest=lambda name: PIN['digest'], model_factory=lambda *a, **k: object())
    assert advance()['phase'] == 'document_page'
    assert advance()['phase'] == 'document_page_review'
    assert advance()['state'] == 'draft_complete'
    assert advance()['state'] == 'draft_complete' and len(calls) == 3
    assert [stage._read(root / f'budget_{i}.started.json')['max_calls'] for i in (1, 2, 3)] == [1, 1, 1]
    assert all((root / f'call_{i}.started.json').exists() for i in (1, 2, 3))
    with pytest.raises(dg.GenerationError, match='scope_mismatch'):
        stage.replay_document_generation(root, tenant_id='foreign', deal_id='deal')


def test_orphan_intent_and_recorded_failure_never_repeat(tmp_path, monkeypatch):
    root = tmp_path / 'crashed-run'
    stage.prepare_document_generation(root, [manifest()], PIN, PIN, 'pitch_deck')
    stage._write_new(root / 'call_1.started.json', {'unknown_transport': True})
    def no_call(*args, **kwargs):
        pytest.fail('An unresolved transport must not be repeated')
    monkeypatch.setattr(stage, 'recorded_call', no_call)
    result = stage.advance_document_generation(root, tenant_id='tenant', deal_id='deal',
        installed_digest=lambda name: PIN['digest'], model_factory=no_call)
    assert result['reason'] == 'unresolved_document_call_intent'
    failed = tmp_path / 'failed-run'
    stage.prepare_document_generation(failed, [manifest()], PIN, PIN, 'pitch_deck')
    def failure(model, task, instruction, payload, schema, attempts, save):
        attempts.append({'id': 'response_1', 'task': task, 'instruction': instruction, 'input': payload,
                         'schema': schema.model_json_schema(), 'error': 'transport failed',
                         'raw_response': '', 'response_hash': dg.digest(''), 'model': PIN['name']})
        save()
        raise RuntimeError('transport failed')
    monkeypatch.setattr(stage, 'recorded_call', failure)
    result = stage.advance_document_generation(failed, tenant_id='tenant', deal_id='deal',
        installed_digest=lambda name: PIN['digest'], model_factory=lambda *a, **k: object())
    assert result['state'] == 'blocked'
    monkeypatch.setattr(stage, 'recorded_call', no_call)
    assert stage.advance_document_generation(failed, tenant_id='tenant', deal_id='deal',
        installed_digest=no_call, model_factory=no_call)['state'] == 'blocked'


def test_scope_original_hash_pin_or_symlink_changes_block_before_transport(tmp_path, monkeypatch):
    root = tmp_path / 'pin-run'
    stage.prepare_document_generation(root, [manifest()], PIN, PIN, 'pitch_deck')
    def no_call(*args, **kwargs):
        pytest.fail('Changed installed model must not receive private text')
    monkeypatch.setattr(stage, 'recorded_call', no_call)
    with pytest.raises(dg.GenerationError, match='installed_model_pin_changed'):
        stage.advance_document_generation(root, tenant_id='tenant', deal_id='deal',
            installed_digest=lambda name: 'b' * 64, model_factory=no_call)
    link = tmp_path / 'linked'
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(dg.GenerationError, match='symlink_rejected'):
        stage.replay_document_generation(link, tenant_id='tenant', deal_id='deal')
    assert not (root / 'call_1.started.json').exists()


def test_explicit_catalog_encoding_frozen_in_new_runs_and_historical_absence_remains_old(tmp_path):
    oldroot, newroot = tmp_path / 'old', tmp_path / 'compact'
    original = manifest()
    stage.prepare_document_generation(oldroot, [original], PIN, PIN, 'pitch_deck')
    stage.prepare_document_generation(newroot, [original], PIN, PIN, 'pitch_deck',
                                      catalog_encoding=dg.CATALOG_ENCODING_V2)
    old, oldrequest, _ = stage._load_run(oldroot)
    current, request, _ = stage._load_run(newroot)
    assert 'catalog_encoding' not in old and 'catalog_encoding' not in oldrequest[2]
    assert current['catalog_encoding'] == request[2]['catalog_encoding'] == dg.CATALOG_ENCODING_V2
    assert current['inventory'] == old['inventory']
    assert request[1] == oldrequest[1] and request[2]['options'] == oldrequest[2]['options']
    assert stage.replay_document_generation(newroot, tenant_id='tenant', deal_id='deal')['state'] == 'needs_call'
    # A changed declaration cannot silently reinterpret the frozen request.
    current['catalog_encoding'] = dg.CATALOG_ENCODING_V1
    current['run_binding_digest'] = dg.canonical_digest({k: v for k, v in current.items() if k != 'run_binding_digest'})
    (newroot / 'request.json').write_text(__import__('json').dumps(current))
    with pytest.raises(dg.GenerationError, match='plan_profile_changed'):
        stage._load_run(newroot)
