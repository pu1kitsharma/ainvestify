import json
import hashlib
from pathlib import Path
import pytest
from scripts import evaluate_private_material_acceptance as module

def fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'OUTPUT_ROOT',tmp_path)
    source=tmp_path/'old';root=tmp_path/'new';source.mkdir();root.mkdir()
    manifest={'input_revision':'revision','source_hash':'source','memo_digest':'memo','sections':[],
        'content_revision':{'root':'private-memo','record':'pin'},'draft_contract':'purpose_v18',
        'draft_model':'local','draft_pin':'digest','author_options_contract':'compact','review_contract':'semantic_v17'}
    target=dict(manifest,review_contract='semantic_v18')
    request={'digest':'frozen','as_of_date':'2026-10-09','draft_model':{'name':'local','digest':'digest'},'sections':[]}
    model={'profiles':{'draft':'local'}}
    attempts=[{'id':'response_1','task':'material_intro_deck_company','raw_response':'{ "selected": "literal" }'},
              {'id':'response_2','task':'material_pitch_deck_thesis','raw_response':'{ "selected": "literal2" }'}]
    result={'state':'accepted','source_hash':'source','memo_digest':'memo','attempt_count':2,
        'decks':{'intro_deck':{'response_ids':['response_1'],'sections':[]},'pitch_deck':{'response_ids':['response_2'],'sections':[]}}}
    documents={'manifest.json':manifest,'material_request.json':request,'model.json':model,
        'material_attempts.json':attempts,'material_result.json':result,
        'draft_passes.json':[{'pass':1,'state':'needs_resume'},{'pass':2,'state':'accepted'}],
        'material_review_attempts.json':[{'failed_review':'must not copy'}]}
    for name,value in documents.items():(source/name).write_text(json.dumps(value,indent=2))
    for name,value in [('manifest.json',target),('material_request.json',request),('model.json',model)]:
        (root/name).write_text(json.dumps(value))
    calls=[]
    monkeypatch.setattr(module,'_material_replay',lambda path,manifest:calls.append(path))
    return source,root,target,calls

def test_fork_byteexact_author_evidence_history_and_replays_both_sides(tmp_path,monkeypatch):
    source,root,manifest,calls=fixture(tmp_path,monkeypatch)
    proof=module._reuse_material_draft(root,source,manifest)
    assert calls==[source,root]
    for name in proof['imported_files']:assert (root/name).read_bytes()==(source/name).read_bytes()
    assert not (root/'material_review_attempts.json').exists()
    assert proof['review_state_imported'] is False
    assert proof['author_attempt_count']==2 and proof['author_pass_count']==2
    assert proof['source_files']['material_attempts.json']==hashlib.sha256((source/'material_attempts.json').read_bytes()).hexdigest()
    assert (root/'material_attempts.json').stat().st_mode&0o777==0o600

@pytest.mark.parametrize('change',['pin','asof','history','result','extra_review','failed_author'])
def test_mismatched_incomplete_or_review_evidence_rejected_before_copy(tmp_path,monkeypatch,change):
    source,root,manifest,_=fixture(tmp_path,monkeypatch)
    if change=='pin':manifest['draft_pin']='changed'
    elif change=='asof':
        name='material_request.json';value=json.loads((root/name).read_text());value['as_of_date']='2026-10-10';(root/name).write_text(json.dumps(value))
    elif change=='history':(source/'draft_passes.json').write_text(json.dumps([{'pass':1,'state':'started'}]))
    elif change=='result':
        name='material_result.json';value=json.loads((source/name).read_text());value['state']='blocked';(source/name).write_text(json.dumps(value))
    else:
        name='material_attempts.json';value=json.loads((source/name).read_text())
        if change=='extra_review':value[0]['task']='material_content_review'
        else:value[0]['error']='failed'
        (source/name).write_text(json.dumps(value))
    with pytest.raises(ValueError):module._reuse_material_draft(root,source,manifest)
    assert not (root/'material_attempts.json').exists()

def test_replay_failure_rejects_without_import_and_no_inference(tmp_path,monkeypatch):
    source,root,manifest,_=fixture(tmp_path,monkeypatch)
    def failed(*args):raise ValueError('Raw response did not replay')
    monkeypatch.setattr(module,'_material_replay',failed)
    with pytest.raises(ValueError,match='did not replay'):module._reuse_material_draft(root,source,manifest)
    assert not (root/'material_attempts.json').exists()

def test_nonprepare_cannot_fork_or_create_branch(tmp_path):
    with pytest.raises(ValueError,match='only during fresh prepare'):
        module.run(tmp_path/'memo',tmp_path/'output','review',reuse_material_draft=tmp_path/'source')
    assert not (tmp_path/'output').exists()
