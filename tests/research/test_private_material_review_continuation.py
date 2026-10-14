"""Fresh batched material review and immutable historical continuation."""
import json
from pathlib import Path
from scripts import evaluate_private_material_acceptance as cli
from agents.research.material_relation_review import BATCH_OPTIONS
from delivery import material_review_stage as stage


def test_private_manifest_keeps_historical_contracts_on_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'OUTPUT_ROOT', tmp_path)
    projection = {'acceptance_root': str(tmp_path), 'draft_model': 'qwen3:14b',
                  'content_revision': {'root': str(tmp_path / 'units'), 'record': {'state': 'accepted'}},
                  'input_revision': 'a' * 64, 'source_hash': 'b' * 64, 'memo_digest': 'c' * 64,
                  'draft_pin': 'd'*64, 'sections': [], 'financial_unknown_candidates': {}, 'memo_sentence_candidates': {}, 'memo_assertion_candidates': {'as_of_date':'2026-10-04'}}
    monkeypatch.setattr(cli, '_memo_projection', lambda *args, **kwargs: projection)
    root = tmp_path / 'materials'
    fresh = cli._frozen(tmp_path / 'memo', root, create=True)
    request=json.loads((root/'material_request.json').read_text())
    assert request['as_of_date']=='2026-10-04'
    assert request['draft_model']['options']==__import__('delivery.material_stage',fromlist=['COMPACT_MATERIAL_AUTHOR_OPTIONS']).COMPACT_MATERIAL_AUTHOR_OPTIONS
    assert fresh['review_contract'] == 'semantic_v20' and fresh['draft_contract'] == 'purpose_v18'
    historical = {**fresh, 'review_contract': 'semantic_v10', 'draft_contract': 'purpose_v13'}
    historical.pop('author_options_contract')
    (root / 'manifest.json').write_text(json.dumps(historical))
    original = (root / 'manifest.json').read_bytes()
    assert cli._frozen(tmp_path / 'memo', root, create=False) == historical
    assert (root / 'manifest.json').read_bytes() == original


def test_private_review_freezes_batch_options_before_call(tmp_path, monkeypatch):
    manifest = {'review_contract': 'semantic_v12', 'review_model': 'qwen3:14b', 'review_pin': 'a' * 64,
                'input_revision': 'b' * 64, 'source_hash': 'c' * 64, 'memo_digest': 'd' * 64,
                'sections': [], 'section_projection': 'reader_v2'}
    monkeypatch.setattr(cli, '_frozen', lambda *args, **kwargs: manifest)
    monkeypatch.setattr(cli, '_material_replay', lambda *args: {'intro_deck': [], 'pitch_deck': []})
    monkeypatch.setattr(cli, '_installed_digest', lambda name: 'a' * 64)
    (tmp_path / 'material_result.json').write_text(json.dumps({'state': 'accepted'}))
    calls = []
    def private(command, root, **kwargs):
        request = json.loads((root / 'material_review_request.json').read_text())
        assert request['review_contract'] == 'semantic_v12'
        assert request['review_model']['options'] == BATCH_OPTIONS
        calls.append(1)
        (root / 'material_review_result.json').write_text(json.dumps({'state': 'needs_resume'}))
    monkeypatch.setattr(cli, 'run_private', private)
    assert cli.run(tmp_path / 'memo', tmp_path, 'review')['state'] == 'needs_resume'
    assert calls == [1]


def test_production_batch_review_selects_accepted_core_role_without_changing_old_flow(tmp_path, monkeypatch):
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'draft': 'qwen3.5:9b', 'review': 'qwen3.5:9b'}}))
    monkeypatch.setattr(stage, 'validate_material_checkpoint', lambda *args: {'memo_digest': 'a' * 64,
        'decks': {'intro_deck': {'sections': []}, 'pitch_deck': {'sections': []}}})
    monkeypatch.setattr(stage, '_installed_digest', lambda name: 'b' * 64 if name == 'qwen3.5:9b' else 'c' * 64)
    memo = {'source_hash': 'd' * 64, 'sections': [],
            'content_core_reviewer_pin': {'name': 'qwen3:14b', 'digest': 'c' * 64}}
    job = {'input_revision': 'e' * 64, 'checkpoint': {'workflow_contract': 'room-v49-batched-material-review'}}
    assert stage.fresh_material_review_contract(job) == 'semantic_v12'
    request = stage._review_request(job, memo, {}, tmp_path, review_contract='semantic_v12')
    assert request['review_model'] == {**memo['content_core_reviewer_pin'], 'options': BATCH_OPTIONS}
    old = {**job, 'checkpoint': {'workflow_contract': 'room-v48-narrative-function-review'}}
    assert stage.fresh_material_review_contract(old) == 'semantic_v10'


def test_production_compact_review_pins_new_options_preserving_semantic17(tmp_path,monkeypatch):
    from delivery import material_stage
    from agents.research.material_narrative_review import COMPACT_OPTIONS
    (tmp_path/'model.json').write_text(json.dumps({'profiles':{'draft':'qwen3.5:9b','review':'qwen3.5:9b'}}))
    monkeypatch.setattr(stage,'validate_material_checkpoint',lambda *args:{'memo_digest':'a'*64,'decks':{'intro_deck':{'sections':[]},'pitch_deck':{'sections':[]}}})
    monkeypatch.setattr(stage,'_installed_digest',lambda name:'c'*64)
    monkeypatch.setattr(material_stage,'_financial_unknown_candidates',lambda *args:{'unknowns':[],'claims':[]})
    monkeypatch.setattr(material_stage,'_memo_assertion_candidates',lambda *args:{'as_of_date':'2026-10-04','funding_required':False,'slots':{}})
    memo={'source_hash':'d'*64,'sections':[],'content_core_reviewer_pin':{'name':'qwen3:14b','digest':'c'*64}}
    new={'input_revision':'e'*64,'checkpoint':{'workflow_contract':'room-v55-compact-material-review'}}
    assert stage.fresh_material_review_contract(new)=='semantic_v18'
    request=stage._review_request(new,memo,{},tmp_path,review_contract='semantic_v18')
    assert request['review_model']=={**memo['content_core_reviewer_pin'],'options':COMPACT_OPTIONS}
    old={**new,'checkpoint':{'workflow_contract':'room-v54-typed-temporal-selector'}}
    assert stage.fresh_material_review_contract(old)=='semantic_v17'
    historical=stage._review_request(old,memo,{},tmp_path,review_contract='semantic_v17')
    assert historical['review_model']['options']==BATCH_OPTIONS
