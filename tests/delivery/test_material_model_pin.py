import json

import pytest

from delivery import material_stage


def test_material_author_pin_freezes_before_first_call(tmp_path, monkeypatch):
    monkeypatch.setattr(material_stage, 'memo_directory', lambda job: tmp_path)
    monkeypatch.setattr(material_stage, '_installed_material_digest',
                        lambda name: 'a' * 64)
    (tmp_path / 'model.json').write_text(json.dumps({
        'profiles': {'draft': 'qwen3.5:9b'}}))

    def private_call(*args, **kwargs):
        (tmp_path / 'material_result.json').write_text(json.dumps({
            'state': 'blocked', 'reason': 'synthetic_stop'}))

    monkeypatch.setattr(material_stage, 'run_private', private_call)
    job = {'input_revision': 'r' * 64}
    memo = {'state': 'accepted', 'source_hash': 's' * 64,
            'sections': [['Overview', 'Source-bound draft']]}
    result = material_stage.run_material_pass(
        job, memo, timeout=90, draft_model='qwen3:14b')
    assert result['state'] == 'blocked'
    request = json.loads((tmp_path / 'material_request.json').read_text())
    assert request['draft_model'] == {
        'name': 'qwen3:14b', 'digest': 'a' * 64,
        'options': material_stage.MATERIAL_AUTHOR_OPTIONS}
    assert material_stage._draft_model_pin(request, json.loads(
        (tmp_path / 'model.json').read_text())) == 'qwen3:14b'
    with pytest.raises(ValueError, match='new immutable branch'):
        material_stage.run_material_pass(
            job, memo, timeout=90, draft_model='qwen3.5:9b')
    assert json.loads((tmp_path / 'material_request.json').read_text()) == request


@pytest.mark.parametrize("workflow,contract", [("room-v47-prospective-risk-scope", "purpose_v14"), ("room-v48-narrative-function-review", "purpose_v14"), ("room-v50-complete-narrative-materials", "purpose_v15"), ("room-v51-temporal-material-scope", "purpose_v16"), ("room-v52-compact-material-selector", "purpose_v16"), ("room-v53-attributed-period-selector", "purpose_v17"), ("room-v54-typed-temporal-selector", "purpose_v18"), ("room-v55-compact-material-review", "purpose_v18"), ("room-v56-inline-material-provenance", "purpose_v18"), ("room-v57-full-relation-material-review", "purpose_v18"), ("room-v58-complete-source-concise-memo", "purpose_v18"), ("room-v59-sharded-source-adjudication", "purpose_v18"), ("room-v60-blind-group-source-assessment", "purpose_v18"), ("room-v61-supported-topic-groups", "purpose_v18"), ("room-v62-explicit-topic-status", "purpose_v18")])
def test_new_room_freezes_purpose_v14_and_exact_accepted_core_author(tmp_path, monkeypatch, workflow, contract):
    monkeypatch.setattr(material_stage, 'memo_directory', lambda job: tmp_path)
    monkeypatch.setattr(material_stage, '_require_content_gate', lambda *args: None)
    monkeypatch.setattr(material_stage, '_installed_material_digest', lambda name: 'a' * 64)
    monkeypatch.setattr(material_stage, '_financial_unknown_candidates', lambda *args: {'synthetic': 'financial lineage'})
    monkeypatch.setattr(material_stage, '_memo_sentence_candidates', lambda *args: {'synthetic': 'sentence lineage'})
    monkeypatch.setattr(material_stage, '_memo_assertion_candidates', lambda *args: {'synthetic': 'assertion lineage'})
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b'}}))
    profile_before = (tmp_path / 'model.json').read_bytes()
    (tmp_path/'request.json').write_text(json.dumps({'as_of_date':'2026-10-04'}))
    calls = []
    def private_call(*args, **kwargs):
        calls.append(1)
        (tmp_path / 'material_result.json').write_text(json.dumps({'state': 'blocked', 'reason': 'synthetic_stop'}))
    monkeypatch.setattr(material_stage, 'run_private', private_call)
    job = {'input_revision': 'r' * 64, 'checkpoint': {'workflow_contract': workflow}}
    memo = {'state': 'accepted', 'source_hash': 's' * 64, 'sections': [['Overview', 'Source-bound draft']],
            'content_core_author_pin': {'name': 'qwen3:14b', 'digest': 'a' * 64}}
    assert material_stage.run_material_pass(job, memo, timeout=90)['state'] == 'blocked'
    request = json.loads((tmp_path / 'material_request.json').read_text())
    assert request['replay_contracts'] == {'intro_deck': contract, 'pitch_deck': contract}
    assert request['draft_model'] == {**memo['content_core_author_pin'], 'options': material_stage.COMPACT_MATERIAL_AUTHOR_OPTIONS if workflow in {'room-v52-compact-material-selector','room-v53-attributed-period-selector','room-v54-typed-temporal-selector','room-v55-compact-material-review','room-v56-inline-material-provenance','room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status'} else material_stage.MATERIAL_AUTHOR_OPTIONS}
    if workflow in {'room-v52-compact-material-selector','room-v53-attributed-period-selector','room-v54-typed-temporal-selector','room-v55-compact-material-review','room-v56-inline-material-provenance','room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status'}:
        assert request['as_of_date']=='2026-10-04' and request['author_options_contract']==material_stage.COMPACT_AUTHOR_OPTIONS_CONTRACT
    assert request['financial_unknown_candidates'] == {'synthetic': 'financial lineage'}
    if contract in {'purpose_v15','purpose_v16','purpose_v17','purpose_v18'}:
        assert request['memo_assertion_candidates'] == {'synthetic': 'assertion lineage'}
        assert 'memo_sentence_candidates' not in request
    else:
        assert request['memo_sentence_candidates'] == {'synthetic': 'sentence lineage'}
    assert (tmp_path / 'model.json').read_bytes() == profile_before
    with pytest.raises(ValueError, match='frozen '+contract):
        material_stage.run_material_pass(job, memo, timeout=90, draft_contract='purpose_v11')
    with pytest.raises(ValueError, match='accepted core author role'):
        material_stage.run_material_pass(job, memo, timeout=90, draft_model='qwen3.5:9b')
    assert calls == [1]
    assert json.loads((tmp_path / 'material_request.json').read_text()) == request
    request['replay_contracts'] = {'intro_deck': 'purpose_v13', 'pitch_deck': 'purpose_v13'}
    (tmp_path / 'material_request.json').write_text(json.dumps(request))
    with pytest.raises(ValueError, match='frozen room contract'):
        material_stage.run_material_pass(job, memo, timeout=90)
    assert calls == [1]


def test_historical_room_keeps_original_material_default():
    assert material_stage.fresh_material_contract({'checkpoint': {'workflow_contract':
        'room-v46-structured-core-decisions'}}) == 'purpose_v11'
    assert material_stage.fresh_material_contract({'checkpoint': {'workflow_contract':
        'room-v47-prospective-risk-scope'}}) == 'purpose_v14'
