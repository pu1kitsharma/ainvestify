"""Explicit full-literal planning has real author/review records, never fake maps."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json

import pytest

from agents.research import document_generation as dg
from delivery import document_generation_stage as stage
from scripts import evaluate_reference_generation as cli
from scripts import private_reference_generation_worker as worker
from tests.delivery.test_document_generation_stage_source_maps import full_source
from tests.delivery.test_private_reference_export import mock_renderer
from tests.research.test_document_generation import PIN, author, planned, record
from tests.research.test_evaluate_reference_generation import synthetic_source


ENCODING='complete-document-literals-v1'
PROFILE='complete-literal-context-v2'


@pytest.fixture(autouse=True,params=['complete-document-literals-v1','complete-document-literals-v2'])
def literal_encoding(request,monkeypatch):
    monkeypatch.setitem(globals(),'ENCODING',request.param)


def prepare(root,**kwargs):
    return stage.prepare_document_generation(root,[full_source()],PIN,PIN,'intro_deck',
        catalog_encoding=ENCODING,qualification_context_profile=PROFILE,**kwargs)


def advance(root):
    return stage.advance_document_generation(root,tenant_id='tenant',deal_id='deal',
        installed_digest=lambda name:PIN['digest'],model_factory=lambda *a,**k:object())


def test_full_literal_plan_freezes_actual_request_and_physical_topology_without_map_rows(tmp_path):
    root=tmp_path/'complete-literals'
    prepare(root)
    body,request,rows=stage._load_run(root)
    assert rows==[] and body['maximum_lifetime_model_calls']==81
    assert body['qualification_context_profile']==PROFILE
    assert body['plan_request']==dg.request_json(request)
    assert request[2]['catalog_encoding']==ENCODING
    assert request[2]['qualification_context_profile']==PROFILE
    assert len(body['inventory']['source_map_topology'])==2  # Includes physical blank page.
    assert not {'source_map_count','source_map_requests','source_map_profiles',
                'source_map_token_budgets','initial_request','source_coverage_reviewer_pin'}&body.keys()
    progress=stage.replay_document_generation(root,tenant_id='tenant',deal_id='deal')
    assert progress['phase']=='document_plan' and progress['maximum_model_calls']==81
    assert not list(root.glob('call_*.started.json'))


@pytest.mark.parametrize('kwargs',[
    {'qualification_context_profile':None},
    {'qualification_context_profile':'complete-page-context-v1'},
    {'source_coverage_reviewer_pin':{'name':'qwen3:14b','digest':'b'*64}},
    {'source_map_token_budgets':[900,900]},
    {'source_map_profiles':['quoted-v1','quoted-v1']},
])
def test_literal_profile_rejects_mapper_options_or_missing_context_before_writes(tmp_path,kwargs):
    root=tmp_path/'rejected'
    values={'catalog_encoding':ENCODING,'qualification_context_profile':PROFILE,**kwargs}
    with pytest.raises(dg.GenerationError):
        stage.prepare_document_generation(root,[full_source()],PIN,PIN,'intro_deck',**values)
    assert not root.exists()


def test_complete_literal_progress_export_and_reopen_bind_only_three_actual_roles(tmp_path,monkeypatch):
    root=tmp_path/'complete'
    prepare(root)
    calls=[]
    def fake(model,task,instruction,payload,schema,attempts,save):
        request=(task,instruction,payload,schema)
        calls.append((task,payload['model_pin']))
        if schema is dg.DocumentPlan:answer=planned(stage._read(root/'request.json')['inventory'])
        elif schema is dg.DocumentPage:answer=author(request)
        else:answer={'verdict':'pass','issues':[],'financial_status':'not_established'}
        attempts.append(record(request,answer,len(attempts)+1));save()
    monkeypatch.setattr(stage,'recorded_call',fake)
    assert advance(root)['phase']=='document_page'
    def no_early_render(*a,**k):pytest.fail('An actual plan alone is not company-authored material')
    monkeypatch.setattr(worker,'render_evidence_document',no_early_render)
    assert worker.export_prefix(root)['reason']=='no_complete_model_authored_page'
    assert not list(root.glob('draft_prefix_*'))
    assert advance(root)['phase']=='document_page_review'
    final=advance(root)
    assert final['state']=='draft_complete' and final['plan_response_id']=='response_1'
    assert len(calls)==3 and all(pin==PIN for _,pin in calls)
    before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert advance(root)==final and len(calls)==3
    assert before=={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
    for number,phase in enumerate(['document_plan','document_page','document_page_review'],1):
        intent=stage._read(root/f'call_{number}.started.json')
        assert intent['phase']==phase and intent['qualification_context_profile']==PROFILE
        assert stage._read(root/f'budget_{number}.started.json')['max_calls']==1
        assert stage._read(root/f'budget_{number}.started.json')['max_requests']==6
    captured=[]
    monkeypatch.setattr(worker,'render_evidence_document',mock_renderer(captured))
    result=worker.export_prefix(root)
    receipt=stage._read(Path(result['diagnostic_path'])/'export_receipt.json')
    assert receipt['byte_receipt']['plan_response_id']=='response_1'
    assert receipt['byte_receipt']['page_receipts'][0]['author_response_id']=='response_2'
    assert receipt['byte_receipt']['page_receipts'][0]['review_response_id']=='response_3'
    assert receipt['source_map_status']==receipt['source_coverage_review_status']=='not_performed'
    assert 'source_map_receipts' not in receipt and 'source_coverage_review_receipts' not in receipt
    assert receipt['qualification_context_profile']==PROFILE
    assert receipt['literal_catalog_digest']==dg.canonical_digest(stage._load_run(root)[1][2]['catalog'])
    assert receipt['financial_validation']==receipt['regulatory_approval']==receipt['investor_approval']=='not_established'
    assert result['release_status']=='draft_only' and len(captured)==2 and len(calls)==3
    assert all('The source reports a limited pilot in 2024.' in item['sections'][0][1] for item in captured)
    assert all('[Reported]' in item['sections'][0][1] for item in captured)


def test_unknown_or_failed_plan_never_repeats_or_creates_mapper_records(tmp_path,monkeypatch):
    orphan=tmp_path/'unknown-plan'
    prepare(orphan)
    stage._write_new(orphan/'call_1.started.json',{'unknown_transport':True})
    def never(*a,**k):pytest.fail('An unknown or failed plan must not infer again')
    monkeypatch.setattr(stage,'recorded_call',never)
    assert advance(orphan)['reason']=='unresolved_document_call_intent'
    failed=tmp_path/'failed-plan'
    prepare(failed)
    def failure(model,task,instruction,payload,schema,attempts,save):
        attempts.append({'id':'response_1','task':task,'instruction':instruction,'input':payload,
            'schema':schema.model_json_schema(),'raw_response':'','response_hash':dg.digest(''),
            'error':'synthetic failed full-literal plan','model':PIN['name']})
        save();raise RuntimeError('synthetic failed full-literal plan')
    monkeypatch.setattr(stage,'recorded_call',failure)
    assert advance(failed)['state']=='blocked'
    raw=(failed/'response_1.json').read_bytes()
    monkeypatch.setattr(stage,'recorded_call',never)
    assert advance(failed)['state']=='blocked'
    assert (failed/'response_1.json').read_bytes()==raw
    assert not (failed/'response_2.json').exists() and not (failed/'call_2.started.json').exists()


@pytest.mark.parametrize('change',['lifetime','map_count','critic'])
def test_resealed_literal_body_cannot_invent_source_calls_or_critic(tmp_path,change):
    root=tmp_path/'tampered'
    prepare(root)
    value=stage._read(root/'request.json')
    if change=='lifetime':value['maximum_lifetime_model_calls']=83
    elif change=='map_count':value['source_map_count']=2
    else:value['source_coverage_reviewer_pin']={'name':'qwen3:14b','digest':'b'*64}
    value['run_binding_digest']=dg.canonical_digest({k:v for k,v in value.items() if k!='run_binding_digest'})
    (root/'request.json').write_text(json.dumps(value))
    with pytest.raises(dg.GenerationError):stage._load_run(root)


def test_cli_freezes_literal_plan_and_verify_replays_without_model_lookup(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'PRIVATE_ROOT',tmp_path)
    source,_=synthetic_source(tmp_path/'source')
    lookups=[]
    monkeypatch.setattr(cli,'installed_digest',lambda name:lookups.append(name) or PIN['digest'])
    root=tmp_path/'literal-cli'
    assert cli.run(root,'prepare',manifests=[source],catalog_encoding=ENCODING,
                   qualification_context_profile=PROFILE)['state']=='prepared'
    body,request,rows=stage._load_run(root)
    assert body['maximum_lifetime_model_calls']==81 and rows==[]
    assert request[2]['qualification_context_profile']==PROFILE
    assert lookups==[PIN['name'],PIN['name']]
    def never(*a,**k):pytest.fail('Read-only replay must not access installed models')
    monkeypatch.setattr(cli,'installed_digest',never)
    def isolated(command,job,*,timeout,extra_read,local_model):
        assert command[-1]=='verify' and not local_model and timeout==118
        output=StringIO()
        with redirect_stdout(output):worker.main(job,'verify')
        return output.getvalue()
    monkeypatch.setattr(cli,'run_private',isolated)
    assert cli.run(root,'verify')['phase']=='document_plan'
    assert not list(root.glob('call_*.started.json'))


@pytest.mark.parametrize('kwargs',[
    {'qualification_context_profile':None},
    {'qualification_context_profile':'complete-page-context-v1'},
    {'source_coverage_reviewer':'qwen3:14b'},
    {'source_map_output_tokens':1600},
    {'source_map_profile':'unit-ids-bound-v3'},
    {'reuse_source_map_prefix':'unused-parent'},
])
def test_cli_rejects_literal_flow_mapper_or_critic_options_before_model_lookup(tmp_path,monkeypatch,kwargs):
    monkeypatch.setattr(cli,'PRIVATE_ROOT',tmp_path)
    source,_=synthetic_source(tmp_path/'source')
    def never(*a,**k):pytest.fail('Invalid mode must not reach model inventory or private worker')
    monkeypatch.setattr(cli,'installed_digest',never)
    monkeypatch.setattr(cli,'run_private',never)
    root=tmp_path/'rejected-cli'
    values={'catalog_encoding':ENCODING,'qualification_context_profile':PROFILE,**kwargs}
    with pytest.raises(ValueError):cli.run(root,'prepare',manifests=[source],**values)
    assert not root.exists()
