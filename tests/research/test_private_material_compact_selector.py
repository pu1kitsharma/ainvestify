"""Versioned capacity options and persisted budget failures, without inference."""
import json
import pytest
from agents.inference.model_authorship import digest
from delivery import material_stage as stage
from scripts import private_material_worker as worker


def fixture(tmp_path):
    request={'input_revision':'a'*64,'source_hash':'b'*64,'memo_digest':'c'*64,
             'sections':[['Synthetic source','One source-bound test unit.']],
             'replay_contracts':{'intro_deck':'purpose_v16','pitch_deck':'purpose_v16'},
             'memo_assertion_candidates':{},'financial_unknown_candidates':{},
             'as_of_date':'2026-10-04','author_options_contract':stage.COMPACT_AUTHOR_OPTIONS_CONTRACT,
             'draft_model':{'name':'qwen3:14b','digest':'d'*64,'options':stage.COMPACT_MATERIAL_AUTHOR_OPTIONS}}
    (tmp_path/'material_request.json').write_text(json.dumps({**request,'digest':digest(request)}))
    (tmp_path/'model.json').write_text(json.dumps({'profiles':{'draft':'qwen3:14b'}}))
    (tmp_path/'material_budget.json').write_text(json.dumps({'seconds':105}))
    return request


def test_frozen_options_and_outer_date_are_used_and_persisted_error_blocks(tmp_path,monkeypatch):
    request=fixture(tmp_path);constructed=[]
    class Model:
        name='qwen3:14b'
        def __init__(self,name,**options):constructed.append((name,options))
    monkeypatch.setattr(worker,'LocalModel',Model)
    monkeypatch.setattr(worker,'_installed_material_digest',lambda name:'d'*64)
    def replay(kind,payload,*args,**kwargs):
        assert payload['as_of_date']=='2026-10-04'
        return {'state':'needs_resume','task':'synthetic_selector','instruction':'Select recorded evidence.', 'payload':payload,'schema':None}
    monkeypatch.setattr(worker,'replay_material_rows',replay)
    def call(model,task,instruction,payload,schema,attempts,save):
        attempts.append({'id':'failed','task':task,'error':'PreparationBudgetExceeded','raw_response':'','routing':stage.COMPACT_MATERIAL_AUTHOR_OPTIONS})
        save();raise worker.PreparationBudgetExceeded('Synthetic measured deadline')
    monkeypatch.setattr(worker,'recorded_call',call)
    result=worker.draft_materials(tmp_path)
    assert result=={'state':'blocked','reason':'material_author_budget_failed_recorded'}
    assert constructed==[('qwen3:14b',stage.COMPACT_MATERIAL_AUTHOR_OPTIONS)]
    assert json.loads((tmp_path/'material_attempts.json').read_text())[0]['error']=='PreparationBudgetExceeded'
    assert stage._draft_options({'replay_contracts':request['replay_contracts']})==stage.MATERIAL_AUTHOR_OPTIONS


def test_compact_model_and_route_options_cannot_be_rebased(tmp_path):
    request=fixture(tmp_path)
    changed={**request,'draft_model':{**request['draft_model'],'options':stage.MATERIAL_AUTHOR_OPTIONS}}
    with pytest.raises(ValueError,match='Invalid frozen'):stage._draft_model_pin(changed,{'profiles':{'draft':'qwen3:14b'}})
    with pytest.raises(ValueError,match='requires frozen'):stage._draft_model_pin({**request,'draft_model':None},{'profiles':{'draft':'qwen3:14b'}})
    with pytest.raises(ValueError,match='route differs'):stage._validate_draft_routes(request,[{'routing':stage.MATERIAL_AUTHOR_OPTIONS}])
