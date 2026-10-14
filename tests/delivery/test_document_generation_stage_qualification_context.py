"""Optional local source reviews retain real call provenance and finite bounds."""
import json

import pytest

from agents.research import document_generation as dg
from delivery import document_generation_stage as stage
from scripts import private_reference_generation_worker as worker
from tests.delivery.test_document_generation_stage_source_maps import full_source,map_answer,adoption_fixture
from tests.research.test_document_generation import PIN,author,planned,record


PROFILE='complete-page-context-v1'
CRITIC_PIN={'name':'qwen3:14b','digest':'b'*64}


def advance(root):
    installed={PIN['name']:PIN['digest'],CRITIC_PIN['name']:CRITIC_PIN['digest']}
    return stage.advance_document_generation(root,tenant_id='tenant',deal_id='deal',
        installed_digest=installed.__getitem__,model_factory=lambda *args,**kwargs:object())


def prepare(root,source,**kwargs):
    return stage.prepare_document_generation(root,[source],PIN,PIN,'pitch_deck',
        catalog_encoding=dg.CATALOG_ENCODING_V3,**kwargs)


def test_explicit_context_freezes_profile_and_two_m_calls_without_changing_map_requests(tmp_path):
    source=full_source()
    old,new=tmp_path/'old',tmp_path/'context'
    prepare(old,source)
    prepare(new,source,qualification_context_profile=PROFILE)
    before,seed,_=stage._load_run(old)
    current,new_seed,_=stage._load_run(new)
    assert 'qualification_context_profile' not in before
    assert current['qualification_context_profile']==PROFILE
    assert before['source_map_requests']==current['source_map_requests']
    assert before['initial_request']==current['initial_request']==dg.request_json(seed)==dg.request_json(new_seed)
    assert before['maximum_lifetime_model_calls']==83
    assert current['maximum_lifetime_model_calls']==85
    assert current['run_binding_digest']!=before['run_binding_digest']
    assert stage._qualification_context_profile(before)=={}
    assert stage._qualification_context_profile(current)=={'qualification_context_profile':PROFILE}


@pytest.mark.parametrize('encoding,profile',[(dg.CATALOG_ENCODING_V1,PROFILE),(dg.CATALOG_ENCODING_V3,'approved-context')])
def test_unknown_or_non_v3_context_rejected_before_directory_write(tmp_path,encoding,profile):
    root=tmp_path/'rejected'
    with pytest.raises(dg.GenerationError):
        stage.prepare_document_generation(root,[full_source()],PIN,PIN,'pitch_deck',
            catalog_encoding=encoding,qualification_context_profile=profile)
    assert not root.exists()


def test_profile_or_lifetime_tamper_cannot_reinterpret_frozen_source_review_run(tmp_path):
    root=tmp_path/'context'
    prepare(root,full_source(),qualification_context_profile=PROFILE)
    value=stage._read(root/'request.json')
    value['maximum_lifetime_model_calls']=value['source_map_count']+81
    value['run_binding_digest']=dg.canonical_digest({k:v for k,v in value.items() if k!='run_binding_digest'})
    (root/'request.json').write_text(json.dumps(value))
    with pytest.raises(dg.GenerationError,match='finite_bounds'):
        stage._load_run(root)


def test_separate_coverage_critic_requires_context_and_valid_frozen_pin_before_writes(tmp_path):
    root=tmp_path/'missing-context'
    with pytest.raises(dg.GenerationError,match='requires_explicit_qualification_context'):
        prepare(root,full_source(),source_coverage_reviewer_pin=CRITIC_PIN)
    assert not root.exists()
    invalid=tmp_path/'invalid-critic'
    with pytest.raises(dg.GenerationError):
        prepare(invalid,full_source(),qualification_context_profile=PROFILE,
                source_coverage_reviewer_pin={**CRITIC_PIN,'digest':'not-an-installed-pin'})
    assert not invalid.exists()


def test_source_map_prefix_adoption_allows_new_context_profile_but_never_invents_reviews(tmp_path,monkeypatch):
    parent,source,proof=adoption_fixture(tmp_path,monkeypatch)
    child=tmp_path/'context-child'
    prepare(child,source,qualification_context_profile=PROFILE,
            source_coverage_reviewer_pin=CRITIC_PIN,
            source_map_token_budgets=[900,900,1600],source_map_profiles=['quoted-v1','quoted-v1','unit-ids-v2'])
    stage._write_new(child/'source_provenance.json',proof)
    assert stage.adopt_source_map_prefix(child,parent,count=2)['new_model_invocations']==0
    body,_,rows=stage._load_run(child)
    assert body['maximum_lifetime_model_calls']==87
    assert body['source_coverage_reviewer_pin']==CRITIC_PIN
    assert len(rows)==2 and all(row['task']=='document_source_map_v1' for row in rows)
    assert not list(child.glob('budget_*.json'))
    assert not (child/'response_3.json').exists()


def _coverage_answer(request):
    # Exact schema fields are provided by the generation owner. These are
    # synthetic transport fixtures, never private company answers/gold labels.
    return {'verdict':'pass','topic_patches':[],
            'review_scope':'local_model_source_reading_only','financial_validation':'not_established',
            'regulatory_approval':'not_established','investor_approval':'not_established'}


def fake_call(root,calls):
    def fake(model,task,instruction,payload,schema,attempts,save):
        request=(task,instruction,payload,schema)
        calls.append(task)
        if task=='document_source_map_v1':answer=map_answer(request)
        elif task=='document_source_coverage_review_v1':answer=_coverage_answer(request)
        elif task=='document_plan_v1':answer=planned(stage._read(root/'request.json')['inventory'])
        elif schema is dg.DocumentPage:answer=author(request)
        else:answer={'verdict':'pass','issues':[],'financial_status':'not_established'}
        attempts.append(record(request,answer,len(attempts)+1));save()
    return fake


@pytest.mark.parametrize('coverage_pin',[None,CRITIC_PIN])
def test_actual_source_review_calls_follow_complete_map_prefix_and_precede_plan(tmp_path,monkeypatch,coverage_pin):
    root=tmp_path/'reviewed-source'
    prepare(root,full_source(),qualification_context_profile=PROFILE,
            source_coverage_reviewer_pin=coverage_pin)
    calls=[]
    monkeypatch.setattr(stage,'recorded_call',fake_call(root,calls))
    assert advance(root)['phase']=='document_source_map'
    assert advance(root)['phase']=='document_source_coverage_review'
    assert advance(root)['phase']=='document_source_coverage_review'
    assert advance(root)['phase']=='document_plan'
    assert advance(root)['phase']=='document_page'
    assert advance(root)['phase']=='document_page_review'
    final=advance(root)
    assert final['state']=='draft_complete'
    assert final['plan_response_id']=='response_5'
    assert len(calls)==7
    assert calls[2:4]==['document_source_coverage_review_v1']*2
    assert advance(root)==final and len(calls)==7
    body,_,rows=stage._load_run(root)
    expected_critic=coverage_pin or PIN
    assert [row['input']['model_pin'] for row in rows]==[
        PIN,PIN,expected_critic,expected_critic,PIN,PIN,PIN]
    assert ('source_coverage_reviewer_pin' in body)==(coverage_pin is not None)
    assert body['reviewer_pin']==PIN
    for number in (3,4):
        intent=stage._read(root/f'call_{number}.started.json')
        assert intent['phase']=='document_source_coverage_review'
        assert intent['qualification_context_profile']==PROFILE
        assert intent['model_pin']==expected_critic
        assert stage._read(root/f'budget_{number}.started.json')['max_calls']==1
    assert final['financial_validation']=='not_established'
    # Export reconstructs the real plan after two maps AND two reviews, and
    # records both reviewer roles without elevating local review to approval.
    from tests.delivery.test_private_reference_export import mock_renderer
    captured=[]
    monkeypatch.setattr(worker,'render_evidence_document',mock_renderer(captured))
    exported=worker.export_prefix(root)
    receipt=stage._read(__import__('pathlib').Path(exported['diagnostic_path'])/'export_receipt.json')
    assert [item['response_id'] for item in receipt['source_map_receipts']]==['response_1','response_2']
    assert [item['response_id'] for item in receipt['source_coverage_review_receipts']]==['response_3','response_4']
    assert receipt['byte_receipt']['plan_response_id']=='response_5'
    assert receipt['byte_receipt']['page_receipts'][0]['author_response_id']=='response_6'
    assert receipt['source_coverage_reviewer_pin']==expected_critic
    assert receipt['page_reviewer_pin']==PIN
    assert receipt['financial_validation']==receipt['regulatory_approval']==receipt['investor_approval']=='not_established'
    assert exported['release_status']=='draft_only'
    assert len(captured)==2 and len(calls)==7


def test_source_review_prefix_never_exports_as_document_plan_or_invents_pages(tmp_path,monkeypatch):
    root=tmp_path/'only-source-reviews'
    prepare(root,full_source(),qualification_context_profile=PROFILE)
    monkeypatch.setattr(stage,'recorded_call',fake_call(root,[]))
    for _ in range(3):advance(root)
    def never(*args,**kwargs):pytest.fail('Source proposals are not model-authored document pages')
    monkeypatch.setattr(worker,'render_evidence_document',never)
    assert worker.export_prefix(root)['reason']=='source_map_prefix_has_no_recorded_document_plan'
    assert not list(root.glob('draft_prefix_*'))
