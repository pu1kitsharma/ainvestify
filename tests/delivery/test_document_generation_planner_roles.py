"""Separate local roles must bind their actual recorded model, not imply approval."""
import json

import pytest

from agents.research import document_generation as dg
from delivery import document_generation_stage as stage
from tests.delivery.test_document_generation_stage_source_maps import full_source
from tests.research.test_document_generation import PIN, author, planned, record


PLANNER = {'name': 'qwen3.5:4b', 'digest': 'b' * 64}


def prepare(root):
    stage.prepare_document_generation(root, [full_source()], PIN, PIN, 'intro_deck',
        catalog_encoding='complete-document-literals-v2',
        qualification_context_profile='complete-literal-context-v2', planner_pin=PLANNER)


def test_plan_author_and_review_use_distinct_frozen_role_pins(tmp_path, monkeypatch):
    root = tmp_path / 'roles'
    prepare(root)
    pins = []

    def fake(model, task, instruction, payload, schema, attempts, save):
        request = (task, instruction, payload, schema)
        pins.append(payload['model_pin'])
        answer = (planned(stage._read(root / 'request.json')['inventory']) if schema is dg.DocumentPlan
                  else author(request) if schema is dg.DocumentPage else
                  {'verdict': 'pass', 'issues': [], 'financial_status': 'not_established'})
        attempts.append(record(request, answer, len(attempts) + 1)); save()

    monkeypatch.setattr(stage, 'recorded_call', fake)
    for _ in range(3):
        final = stage.advance_document_generation(root, tenant_id='tenant', deal_id='deal',
            installed_digest=lambda name: PLANNER['digest'] if name == PLANNER['name'] else PIN['digest'],
            model_factory=lambda *a, **k: object())
    assert pins == [PLANNER, PIN, PIN]
    assert final['state'] == 'draft_complete'
    assert final['financial_validation'] == final['regulatory_approval'] == final['investor_approval'] == 'not_established'
    body, request, rows = stage._load_run(root)
    assert body['planner_pin'] == request[2]['model_pin'] == PLANNER
    assert request[2]['page_author_pin'] == PIN
    assert len(rows) == 3 and body['maximum_lifetime_model_calls'] == 81


def test_resealed_planner_pin_and_uninstalled_pin_block_before_inference(tmp_path):
    root = tmp_path / 'changed'
    prepare(root)
    with pytest.raises(dg.GenerationError, match='installed_model_pin_changed'):
        stage.advance_document_generation(root, tenant_id='tenant', deal_id='deal',
            installed_digest=lambda name: 'c' * 64, model_factory=lambda *a, **k: object())
    assert not list(root.glob('call_*.started.json'))
    body = stage._read(root / 'request.json')
    body['planner_pin']['digest'] = 'c' * 64
    body['run_binding_digest'] = dg.canonical_digest({k: v for k, v in body.items() if k != 'run_binding_digest'})
    (root / 'request.json').write_text(json.dumps(body))
    with pytest.raises(dg.GenerationError, match='plan_profile_changed'):
        stage._load_run(root)


def test_legacy_profile_rejects_separate_planner_before_writes(tmp_path):
    root = tmp_path / 'legacy'
    with pytest.raises(dg.GenerationError, match='separate_planner_requires'):
        stage.prepare_document_generation(root, [full_source()], PIN, PIN, 'intro_deck',
            catalog_encoding='complete-document-literals-v1',
            qualification_context_profile='complete-literal-context-v2', planner_pin=PLANNER)
    assert not root.exists()
