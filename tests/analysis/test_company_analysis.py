import json
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks,HTTPException
from agents.analysis.company_analysis import Analysis,Review,validate_answer,run_analysis,analysis_view,calculate_scenarios,ScenarioRequest,numeric_candidates,review_issues,analysis_markdown
from agents.analysis.operating_workflow import reconcile_workspace
from schemas import utcnow
from store import Store
from tests.analysis.test_operating_workflow import company
from workflow_schemas import AutomationRun

QUOTE='Hotel Example recognized revenue of USD 100 million in 2025. It operates hotels and restaurants. Customer demand is seasonal.'
SOURCE={'id':'F1','quote':QUOTE,'source_url':'https://hotel.example/results','retrieved_at':utcnow()}


def answer():
    return {'summary':{'text':'Hotel Example reports revenue from hotel operations; the available result does not establish profitability.','source_ids':['F1']},
        'observations':[{'metric':'revenue','label':'Annual recognized revenue','candidate_id':'N1','period':'P1','qualification':'reported','meaning':'Annual revenue is reported; operating costs and profit are not established.'}],
        'findings':[{'text':'Seasonal demand could affect the timing of cash receipts; a revenue figure alone cannot establish cash coverage.','source_ids':['F1']}],
        'outlook':[{'case':case,'condition':'If room demand '+condition+', operating conditions could change.','implication':'Revenue resilience depends on occupied rooms and actual delivery costs, which remain unmeasured.','watch':'Monitor dated occupancy and cost records across comparable seasons.','source_ids':['F1']} for case,condition in [('downside','weakens'),('base','remains stable'),('upside','strengthens')]],
        'needs':[{'kind':'financial_records','question':'Can you provide a completed month of revenue and direct delivery costs?','why':'These matched figures allow a contribution calculation without guessing costs.'}]}


class Model:
    name='fixture';last_route={}
    def __init__(self,revise=False):self.payloads=[];self.reviews=0;self.revise=revise
    def approve(self,task,payload):pass
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        self.payloads.append(json.loads(evidence))
        if task=='public_analysis_review':
            self.reviews+=1;data={'issues':[{'field':'findings.0.text','answer_quote':'Seasonal demand could affect the timing of cash receipts','source_id':'F1','source_quote':'Customer demand is seasonal.','kind':'source_support','correction':'Clarify that seasonality is reported and cash timing is an inference.'}] if self.revise and self.reviews==1 else []}
        elif task=='public_analysis_patch':data={'patches':[{'field':'findings.0.text','value':'Customer demand is reported as seasonal. Its effect on cash timing is an inference that needs dated collections records.'}]}
        else:data=answer()
        self.last_response_text=json.dumps(data)
        return schema.model_validate(data)


def setup(store):
    lead=company(store);w=reconcile_workspace(store,lead)
    w.thesis='PRIVATE_SENTINEL'
    w.metric_updates=[{'id':'m1','month':'2025-01','currency':'USD','source_note':'PRIVATE_SENTINEL company accounts','revenue':'100','direct_costs':'40','cash':'900','net_burn':'30'}]
    w.automation=AutomationRun(model='fixture',worker_id='fixture',status='running')
    w.company_analysis={'at':utcnow(),'source_collected_at':utcnow(),'public_basis':w.public_evidence_hash,'sources':[SOURCE]}
    store.save_workspace(w,expected_revision=w.revision)
    return lead,w


def test_model_analysis_is_recorded_private_metrics_stay_local_and_calculations_execute(tmp_path):
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);model=Model()
        result=run_analysis(store,lead,w.automation.id,model=model)
        view=analysis_view(result)
        assert view['status']=='waiting_for_input'
        assert view['observations'][0]['value']=='100000000'
        assert view['answer']==answer()
        assert all('PRIVATE_SENTINEL' not in json.dumps(p) for p in model.payloads)
        assert {r['name']:r['value'] for r in view['calculations']['calculations']}['Delivery contribution']=='60.00'
        assert 'attempts' not in view
        assert len(result.company_analysis['attempts'])==2
        result.company_analysis['answer']['summary']['text']='Changed without a model response.'
        assert 'answer' not in analysis_view(result)


def test_review_correction_loop_is_bounded_and_uses_recorded_model_outputs(tmp_path):
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);model=Model(revise=True)
        result=run_analysis(store,lead,w.automation.id,model=model)
        assert result.company_analysis['status']=='waiting_for_input'
        assert len(result.company_analysis['attempts'])==4
        assert model.payloads[2]['correction_required']
        assert result.company_analysis['attempts'][0]['input']['correction_required']==[]
        assert result.company_analysis['attempts'][1]['input']['answer_to_check']==answer()
        assert result.company_analysis['answer_response_id']==result.company_analysis['attempts'][0]['id']
        assert result.company_analysis['answer_patch_response_ids']==[result.company_analysis['attempts'][2]['id']]
        assert analysis_view(result)['answer']['findings'][0]['text']==result.company_analysis['attempts'][2]['answer']['patches'][0]['value']
        result.company_analysis['attempts'][2]['input']['answer_to_check']['summary']['text']='Wrong base draft'
        assert 'answer' not in analysis_view(result)


def test_resume_corrects_only_saved_model_fields_and_keeps_original_responses(tmp_path):
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);first=run_analysis(store,lead,w.automation.id,model=Model())
        first.company_analysis.update(status='needs_review',issues=['findings.0.text: Distinguish reported seasonality from inferred cash timing.'])
        for key in ['answer','answer_response_id','observations']:first.company_analysis.pop(key,None)
        original=deepcopy(first.company_analysis['attempts']);store.save_workspace(first,expected_revision=first.revision)
        result=run_analysis(store,lead,w.automation.id,model=Model())
        assert result.company_analysis['attempts'][:2]==original
        assert [r['task'] for r in result.company_analysis['attempts'][2:]]==['public_analysis_patch','public_analysis_review']
        assert result.company_analysis['budget']['calls']==2
        assert analysis_view(result)['answer']['findings'][0]['text'].startswith('Customer demand is reported')


def test_metric_correction_requires_headline_and_explanation_together_without_rewriting_either():
    from agents.analysis.company_analysis import AnalysisPatch, apply_model_patch
    original = answer()
    patch = AnalysisPatch(patches=[{'field': 'observations.0.meaning',
        'value': 'The source reports revenue; attributable costs remain unavailable.'}])
    with pytest.raises(ValueError, match='both label and meaning'):
        apply_model_patch(original, patch, require_coherent_observations=True)
    # Older independently reviewed single-field patches still replay unchanged.
    assert apply_model_patch(original, patch)['observations'][0]['label'] == original['observations'][0]['label']
    patch = AnalysisPatch(patches=[*patch.model_dump()['patches'],
        {'field': 'observations.0.label', 'value': 'Reported annual revenue'}])
    corrected = apply_model_patch(original, patch, require_coherent_observations=True)
    assert corrected['observations'][0]['label'] == patch.patches[1].value
    assert corrected['observations'][0]['meaning'] == patch.patches[0].value
    assert original == answer()


def test_patch_format_retry_receives_its_rejected_output_and_keeps_the_original_base(tmp_path):
    class PatchRepair(Model):
        def __init__(self):super().__init__(revise=True);self.patches=0
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task=='public_analysis_patch':
                self.patches+=1
                payload=json.loads(evidence)
                if self.patches==1:
                    self.payloads.append(payload)
                    self.last_response_text=json.dumps({'patches':[{'field':'findings.0.text','value':'REJECTED_LONG_PATCH '*60}]})
                    return schema.model_validate_json(self.last_response_text)
                assert payload['answer_to_check']==answer()
                assert 'REJECTED_LONG_PATCH' in json.dumps(payload['correction_required'])
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);model=PatchRepair()
        result=run_analysis(store,lead,w.automation.id,model=model)
        assert result.company_analysis['status']=='waiting_for_input'
        assert model.patches==2
        assert len(result.company_analysis['attempts'])==5
        assert 'REJECTED_LONG_PATCH' not in json.dumps(analysis_view(result)['answer'])
        assert result.company_analysis['answer_patch_response_ids']==[result.company_analysis['attempts'][3]['id']]


def test_complete_json_with_unclosed_presentation_fence_keeps_exact_content():
    from agents.inference.model_output import decode_model_object
    raw='```json\n'+json.dumps(answer())
    assert decode_model_object(raw)==answer()
    for malformed in [raw[:-1],raw+'\nThis is an explanation.',raw+'\n'+json.dumps(answer())]:
        with pytest.raises(ValueError):decode_model_object(malformed)


def test_public_gaps_are_researched_by_the_system_without_private_questions(tmp_path):
    from agents.discovery.web_sources import Page
    public={'kind':'public_source','question':'Find the official annual revenue disclosure.','why':'Compare the public result against the previous reporting period.'}
    class ResearchModel(Model):
        search_transcript=[{'type':'user','tool_use_result':{'query':'official results','results':[{'content':[{'url':SOURCE['source_url'],'title':'Company results'}]}]}}]
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task=='public_navigation':
                self.payloads.append(json.loads(evidence));self.last_route={'search_transcript':self.search_transcript}
                data={'interpretation':'Read the official company annual results.','urls':[SOURCE['source_url']],'official_website':SOURCE['source_url']}
            else:
                result=super().generate_for_task(task,instruction,evidence,schema,**kwargs);data=result.model_dump()
                if task=='public_analysis':data['needs'].append(public)
            self.last_response_text=json.dumps(data)
            return schema.model_validate(data)
    class Fetcher:
        def fetch(self,url):return Page(url,'Official annual results',QUOTE)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store)
        w.company_analysis['needs']=[{**public,'id':'public_1'},{'id':'private_1','kind':'financial_records','question':'PRIVATE_SENTINEL request','why':'Private accounts.'}]
        store.save_workspace(w,expected_revision=w.revision)
        model=ResearchModel();result=run_analysis(store,lead,w.automation.id,model=model,fetcher=Fetcher(),research_gaps=True)
        assert public['question'] in model.payloads[0]['public_request']
        assert all('PRIVATE_SENTINEL' not in json.dumps(p) for p in model.payloads)
        assert result.company_analysis['public_gap_research']['tasks']==['public_1']
        assert {n['kind']:n['owner'] for n in result.company_analysis['needs']}=={'financial_records':'user','public_source':'system'}


def test_pending_research_keeps_the_last_verified_analysis_visible(tmp_path):
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);complete=run_analysis(store,lead,w.automation.id,model=Model())
        complete.company_analysis_history.append(deepcopy(complete.company_analysis))
        complete.company_analysis={'status':'running'}
        view=analysis_view(complete)
        assert not view.get('answer')
        assert view['last_completed_analysis']['answer']==answer()
        markdown=analysis_markdown(complete)
        assert 'Last completed analysis' in markdown
        assert answer()['summary']['text'] in markdown
        complete.company_analysis_history[-1]['answer']['summary']['text']='Unrecorded replacement'
        assert not analysis_view(complete).get('last_completed_analysis')
        with pytest.raises(ValueError,match='No reviewed analysis'):analysis_markdown(complete)


def test_analysis_download_refuses_an_unreviewed_placeholder(tmp_path):
    import api.routers.operations as api
    with Store(tmp_path/'db') as store:
        lead,w=setup(store)
        with pytest.raises(HTTPException) as denied:api.download_analysis(w.id,store,lead.tenant_id)
        assert denied.value.status_code==409


@pytest.mark.parametrize('change,match',[
    ({'candidate_id':'N999'},'numeric candidate'),({'period':'2024'},'period')])
def test_unbound_numeric_observations_are_rejected(change,match):
    data=answer();data['observations'][0].update(change)
    with pytest.raises(ValueError,match=match):validate_answer(Analysis.model_validate(data),[SOURCE])


def test_arr_bounds_never_become_earned_revenue_or_exact_forecast_baselines(tmp_path):
    source={**SOURCE,'quote':'Hotel Example is approaching USD 20 million in ARR in 2025.'}
    data=answer();data['observations'][0].update(metric='arr')
    with pytest.raises(ValueError,match='bound'):validate_answer(Analysis.model_validate(data),[source])
    data['observations'][0].update(qualification='upper_bound',metric='revenue')
    with pytest.raises(ValueError,match='recognized revenue'):validate_answer(Analysis.model_validate(data),[source])


def test_literal_numeric_candidates_keep_scale_currency_and_source_context():
    source={**SOURCE,'quote':'Example raised $30m in 2023. There are over 100 employees. Revenue was EUR 12 million in 2025.'}
    rows=numeric_candidates([source])
    assert [(r['number_text'],r['value'],r['unit']) for r in rows]==[('30m','30000000','unknown'),('100','100','count'),('12 million','12000000','EUR')]
    assert all(r['quote'] in source['quote'] and r['number_text'] in r['quote'] for r in rows)


def test_numeric_bounds_keep_scale_after_plus_without_changing_candidate_order():
    rows=numeric_candidates([{**SOURCE,'quote':'The project reports 5+ billion gallons. It has over 150 customers and 2+ million devices.'}])
    assert [(r['id'],r['number_text'],r['value']) for r in rows]==[
        ('N1','5+ billion','5000000000'),('N2','150','150'),('N3','2+ million','2000000')]
    assert rows[-1]['unit']=='count'


@pytest.mark.parametrize('syntax_error',[True,False])
def test_format_repairs_are_model_authored_recorded_and_do_not_rerun_writer(tmp_path,syntax_error):
    from agents.analysis.company_analysis import apply_format_repair,FormatRepair
    class FormatModel(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task=='public_analysis':
                data=answer()
                if not syntax_error:data['observations'][0]['meaning_note']=''
                raw=json.dumps(data)
                if syntax_error:raw=raw.replace('"summary":','"summary"',1)
                self.last_response_text=raw
                return schema.model_validate_json(raw)
            if task=='public_analysis_format':
                payload=json.loads(evidence);self.payloads.append(payload)
                assert isinstance(payload['answer_to_check'],str)
                edit={'old':'"summary" {','new':'"summary": {'} if syntax_error else {'old':', "meaning_note": ""','new':''}
                edit['occurrences']=1
                self.last_response_text=json.dumps({'edits':[edit] if syntax_error else [],'remove_fields':[] if syntax_error else ['observations.0.meaning_note']})
                return schema.model_validate_json(self.last_response_text)
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);done=run_analysis(store,lead,w.automation.id,model=FormatModel())
        report=done.company_analysis
        assert [a['task'] for a in report['attempts']]==['public_analysis','public_analysis_format','public_analysis_review']
        assert analysis_view(done)['answer']==answer()
        assert report['attempts'][0].get('error')
        report['attempts'][1]['input']['answer_to_check']='Wrong original'
        assert 'answer' not in analysis_view(done)
    assert apply_format_repair('x x',FormatRepair(remove_fields=[],edits=[{'old':'x','new':'y','occurrences':2}]))=='y y'
    with pytest.raises(ValueError,match='declared 1 occurrences but matched 2'):
        apply_format_repair('x x',FormatRepair(remove_fields=[],edits=[{'old':'x','new':'y','occurrences':1}]))
    with pytest.raises(ValueError,match='schema-forbidden extra keys'):
        apply_format_repair(json.dumps(answer()),FormatRepair(remove_fields=['summary.text'],edits=[]))


def test_review_objections_must_quote_actual_answer_and_source():
    issue={'field':'findings.0.text','answer_quote':'Seasonal demand could affect the timing of cash receipts','source_id':'F1','source_quote':'Customer demand is seasonal.','kind':'source_support','correction':'Clarify what is reported and what is an inference.'}
    assert review_issues(Review(issues=[issue]),answer(),[SOURCE])
    for changed in [{'field':'findings.9.text'},{'answer_quote':'invented criticism'},{'source_quote':'invented evidence'}]:
        with pytest.raises(ValueError):review_issues(Review(issues=[{**issue,**changed}]),answer(),[SOURCE])


def test_review_can_cite_short_enum_values_but_still_requires_exact_evidence():
    data=answer();data['observations'][0]['metric']='arr'
    issue={'field':'observations.0.metric','answer_quote':'arr','source_id':'F1',
        'source_quote':'recognized revenue of USD 100 million', 'kind':'metric_meaning',
        'correction':'The disclosed metric is recognized revenue, not annual recurring revenue.'}
    assert review_issues(Review(issues=[issue]),data,[SOURCE])
    with pytest.raises(ValueError):
        review_issues(Review(issues=[{**issue,'answer_quote':'cash'}]),data,[SOURCE])


def test_review_can_identify_an_actual_citation_array_member():
    issue={'field':'outlook.0.source_ids','answer_quote':'F1','source_id':'F1',
        'source_quote':'recognized revenue of USD 100 million','kind':'source_support',
        'correction':'This source supports revenue, not the asserted cash collection schedule.'}
    assert review_issues(Review(issues=[issue]),answer(),[SOURCE])
    for change in [{'answer_quote':'F9'},{'source_id':'F9'},{'field':'outlook'}]:
        with pytest.raises(ValueError):review_issues(Review(issues=[{**issue,**change}]),answer(),[SOURCE])


def test_review_policy_change_reuses_original_draft_but_not_old_rejection(tmp_path):
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);first=run_analysis(store,lead,w.automation.id,model=Model())
        reference=first.company_analysis['candidate_response_id']
        first.company_analysis.update(review_contract='previous-review-policy',issues=['OBSOLETE_REJECTION'])
        store.save_workspace(first,expected_revision=first.revision)
        model=Model();result=run_analysis(store,lead,w.automation.id,model=model)
        assert result.company_analysis['candidate_response_id']==reference
        assert len(model.payloads)==1
        assert model.payloads[0]['answer_to_check']==answer()
        assert 'OBSOLETE_REJECTION' not in json.dumps(model.payloads)
        assert analysis_view(result).get('answer')


def test_review_timeout_retains_corrected_candidate_without_stale_objections(tmp_path):
    class TimeoutAfterCorrection(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task=='public_analysis_review' and self.reviews:
                raise RuntimeError('Simulated review deadline')
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store)
        with pytest.raises(RuntimeError,match='review deadline'):
            run_analysis(store,lead,w.automation.id,model=TimeoutAfterCorrection(revise=True))
        failed=store.get_workspace(lead.tenant_id,workspace_id=w.id)
        assert failed.company_analysis['candidate_patch_response_ids']
        assert not failed.company_analysis.get('issues')
        assert not analysis_view(failed).get('answer')
        model=Model();resumed=run_analysis(store,lead,w.automation.id,model=model)
        assert len(model.payloads)==1
        assert model.payloads[0]['answer_to_check']['findings'][0]['text'].startswith('Customer demand is reported')
        assert analysis_view(resumed).get('answer')


def test_second_material_correction_can_finish_inside_the_same_budget(tmp_path):
    class TwoCorrections(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            payload=json.loads(evidence)
            if task=='public_analysis_review' and self.reviews==1:
                self.reviews+=1; self.payloads.append(payload)
                data={'issues':[{'field':'summary.text',
                    'answer_quote':'the available result does not establish profitability',
                    'source_id':'F1','source_quote':'recognized revenue of USD 100 million',
                    'kind':'source_support','correction':'Clarify that this revenue disclosure contains no operating costs.'}]}
            elif task=='public_analysis_patch' and self.reviews==2:
                self.payloads.append(payload)
                data={'patches':[{'field':'summary.text','value':'Hotel Example reports recognized revenue; this disclosure supplies no operating costs to establish profitability.'}]}
            else:return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            self.last_response_text=json.dumps(data)
            return schema.model_validate(data)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);done=run_analysis(store,lead,w.automation.id,model=TwoCorrections(revise=True))
        assert len(done.company_analysis['attempts'])==6
        assert len(done.company_analysis['answer_patch_response_ids'])==2
        assert analysis_view(done).get('answer')


@pytest.mark.parametrize('blocked_task,attempt_count',[
    ('public_analysis',1),('public_analysis_review',2),('public_analysis_patch',3)])
def test_provider_quota_never_enters_format_or_content_retry(tmp_path,blocked_task,attempt_count):
    from agents.inference.subscription_model import SubscriptionLimitError
    class Limited(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task==blocked_task:
                self.last_response_text='Provider usage limit reached'
                raise SubscriptionLimitError('Usage limit reached; try after reset.')
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store)
        with pytest.raises(SubscriptionLimitError):run_analysis(store,lead,w.automation.id,model=Limited(revise=True))
        report=store.get_workspace(lead.tenant_id,workspace_id=w.id).company_analysis
        assert len(report['attempts'])==attempt_count
        assert not report.get('answer')


@pytest.mark.parametrize('phase',['review','format'])
def test_automatic_loop_resumes_checkpoint_without_rewriting_or_researching(tmp_path,phase):
    from agents.analysis.company_analysis import run_analysis_loop
    from agents.preparation.preparation_budget import PreparationBudgetExceeded
    class CheckpointModel(Model):
        def __init__(self):super().__init__();self.tasks=[];self.stopped=False
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            self.tasks.append(task)
            if task=='public_analysis' and phase=='format':
                data=answer();data['observations'][0]['meaning_note']=''
                self.last_response_text=json.dumps(data)
                return schema.model_validate_json(self.last_response_text)
            if task=='public_analysis_'+phase and not self.stopped:
                self.stopped=True
                raise PreparationBudgetExceeded('Simulated per-pass deadline')
            if task=='public_analysis_format':
                self.last_response_text=json.dumps({'remove_fields':['observations.0.meaning_note'],'edits':[]})
                return schema.model_validate_json(self.last_response_text)
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);model=CheckpointModel()
        done=run_analysis_loop(store,lead,w.automation.id,model=model)
        assert model.tasks.count('public_analysis')==1
        assert 'public_navigation' not in model.tasks
        assert analysis_view(done)['answer']==answer()
        loop=done.company_analysis['retry_loop']
        assert loop['status']=='complete' and len(loop['passes'])==2
        assert loop['total_calls']==sum(p['budget']['calls'] for p in loop['passes'])


def test_automatic_loop_stops_on_quota_cancel_and_no_progress(tmp_path):
    from agents.analysis.company_analysis import run_analysis_loop
    from agents.inference.subscription_model import SubscriptionLimitError
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);calls=[]
        def unchanged(s,l,j,**kwargs):
            calls.append(kwargs);current=s.get_workspace(l.tenant_id,lead_id=l.id)
            current.company_analysis.update(status='needs_review',budget={'calls':1,'requests':1})
            s.save_workspace(current,expected_revision=current.revision)
        done=run_analysis_loop(store,lead,w.automation.id,pass_runner=unchanged,refresh=True)
        assert len(calls)==2 and calls==[{'refresh':True},{}]
        assert done.company_analysis['retry_loop']['status']=='no_progress'
        calls.clear()
        def quota(*args,**kwargs):
            calls.append(1);raise SubscriptionLimitError('Quota reset required')
        with pytest.raises(SubscriptionLimitError):run_analysis_loop(store,lead,w.automation.id,pass_runner=quota)
        assert len(calls)==1
        calls.clear()
        def cancel(s,l,j,**kwargs):
            calls.append(1);current=s.get_workspace(l.tenant_id,lead_id=l.id)
            current.automation.status='cancelled';s.save_workspace(current,expected_revision=current.revision)
        done=run_analysis_loop(store,lead,w.automation.id,pass_runner=cancel)
        assert done.automation.status=='cancelled' and len(calls)==1


def test_analysis_export_retains_narrative_citations_and_metric_sources(tmp_path):
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);done=run_analysis(store,lead,w.automation.id,model=Model())
        markdown=analysis_markdown(done)
        assert markdown.count('[F1](https://hotel.example/results)')==5
        assert 'Hotel Example recognized revenue of USD 100 million in 2025.' in markdown
        assert 'These are conditional scenarios' in markdown


def test_forecast_executes_approved_assumptions_without_changing_observed_baseline(tmp_path):
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);done=run_analysis(store,lead,w.automation.id,model=Model())
        request=ScenarioRequest(expected_revision=done.revision,metric_id='metric_1',horizon_years=2,downside_growth=-10,base_growth=0,upside_growth=10,rationale='Explicit sensitivity assumptions for the test, not predicted growth.')
        original=deepcopy(done.company_analysis['observations'])
        result=calculate_scenarios(done,request)
        assert [Decimal(v['value']) for v in result['values']]==[Decimal('81000000'),Decimal('100000000'),Decimal('121000000')]
        assert done.company_analysis['observations']==original
        request.downside_growth=Decimal('20')
        with pytest.raises(ValueError,match='ordered'):calculate_scenarios(done,request)


def test_reuse_does_not_refresh_collection_age_and_private_updates_do_not_stale_public_analysis(tmp_path):
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);collected=(datetime.now(timezone.utc)-timedelta(hours=23)).isoformat()
        w.company_analysis['source_collected_at']=collected;store.save_workspace(w,expected_revision=w.revision)
        done=run_analysis(store,lead,w.automation.id,model=Model())
        assert done.company_analysis['source_collected_at']==collected
        updated=reconcile_workspace(store,lead)
        assert not analysis_view(updated)['stale']
        updated.company_analysis['source_collected_at']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        assert analysis_view(updated)['stale']


def test_input_api_checks_tenant_revision_and_never_marks_a_note_as_actuals(tmp_path):
    import api.routers.operations as api
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);done=run_analysis(store,lead,w.automation.id,model=Model())
        done.automation.status='completed';store.save_workspace(done,expected_revision=done.revision)
        body=api.AnalysisInput(expected_revision=done.revision,need_id='need_1',note='These records have been requested from our finance team.')
        with pytest.raises(HTTPException) as denied:api.save_analysis_input(done.id,body,store,'other')
        assert denied.value.status_code==404
        before=deepcopy(done.metric_updates)
        api.save_analysis_input(done.id,body,store,'one')
        saved=store.get_workspace('one',workspace_id=done.id)
        assert saved.metric_updates==before and saved.company_analysis['needs'][0]['status']=='response_saved'
        with pytest.raises(HTTPException) as stale:api.save_analysis_input(done.id,body,store,'one')
        assert stale.value.status_code==409


def test_private_metric_import_recalculates_without_regenerating_public_drafts(tmp_path,monkeypatch):
    import api.routers.operations as api
    from tests.analysis.test_metric_extraction import TEXT,ExtractionModel
    monkeypatch.setattr(api,'LocalModel',ExtractionModel)
    def no_remote(*args,**kwargs):raise AssertionError('Private import must not use remote drafting')
    monkeypatch.setattr(api,'make_preparation_model',no_remote)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store);w.metric_updates=[];w.automation.status='completed';store.save_workspace(w,expected_revision=w.revision)
        tasks=BackgroundTasks()
        api.import_metrics(w.id,api.MetricImportRequest(expected_revision=w.revision,source_name='Local founder monthly accounts',text=TEXT),tasks,store,'one')
        task=tasks.tasks[0];task.func(*task.args,**task.kwargs)
        done=store.get_workspace('one',workspace_id=w.id)
        assert done.automation.status=='completed',done.automation.error
        assert len(done.metric_updates)==2 and done.metrics['calculations']
        assert done.company_analysis['sources']==[SOURCE]
        assert not done.analyst_pack


def test_discovery_continuation_carries_exclusions_and_enforces_tenant(tmp_path):
    import api.routers.leads as api
    from agents.discovery.eligibility import GLOBAL_POLICY
    from api.models import WebSourceRequest
    from schemas import WebSourcingRun
    with Store(tmp_path/'db') as store:
        lead=company(store)
        previous=WebSourcingRun(tenant_id='one',thesis='hotel operators',geography=None,status='completed',model='fixture',company_profiles=[lead.company_profile],generation_config={'discovery_policy':GLOBAL_POLICY,'exclude_names':['Earlier Hotel']})
        store.save_web_run(previous)
        body=WebSourceRequest(thesis=previous.thesis,continuation_of=previous.id,prepare_workflow=False)
        with pytest.raises(HTTPException) as denied:api.start_web_run(body,BackgroundTasks(),store,'other')
        assert denied.value.status_code==404
        tasks=BackgroundTasks();run=api.start_web_run(body,tasks,store,'one')
        try:
            assert run.generation_config['exclude_names']==['Earlier Hotel','Hotel Example']
            assert run.generation_config['continuation_of']==previous.id
            previous.lead_ids=[lead.id];store.save_web_run(previous)
            assert api.web_run_leads(run.id,store,'one')==[]
            assert [r.id for r in api.web_run_leads(run.id,store,'one',include_previous=True)]==[lead.id]
            run.lead_ids=[lead.id];store.save_web_run(run)
            assert len(api.web_run_leads(run.id,store,'one',include_previous=True))==1
            previous.thesis='Different search';store.save_web_run(previous)
            run.lead_ids=[];store.save_web_run(run)
            assert api.web_run_leads(run.id,store,'one',include_previous=True)==[]
        finally:
            api._web_slot.release()  # Do not start a network job in this test.


def test_historical_discovery_cannot_continue_and_releases_job_slot(tmp_path):
    import api.routers.leads as api
    from api.models import WebSourceRequest
    from schemas import WebSourcingRun
    with Store(tmp_path/'db') as store:
        previous=WebSourcingRun(tenant_id='one',thesis='hotel operators',status='completed',model='fixture')
        store.save_web_run(previous)
        tasks=BackgroundTasks()
        with pytest.raises(HTTPException) as denied:
            api.start_web_run(WebSourceRequest(thesis=previous.thesis,continuation_of=previous.id),tasks,store,'one')
        assert denied.value.status_code==422
        assert tasks.tasks==[]
        assert api._web_slot.acquire(blocking=False)
        api._web_slot.release()
        assert store.get_web_run('one',previous.id)==previous


def test_malformed_saved_review_is_repaired_without_losing_or_rewriting_candidate(tmp_path):
    from agents.analysis.company_analysis import run_analysis_loop
    class BadCritic(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task=='public_analysis_review' and self.reviews<2:
                self.reviews+=1
                data={'issues':[{'field':'findings.0.text','answer_quote':'Seasonal demand',
                    'source_id':'F1','source_quote':'This invented quote does not exist.',
                    'kind':'source_support','correction':'Clarify source support.'}]}
                self.last_response_text=json.dumps(data)
                return schema.model_validate(data)
            if task=='public_analysis_review':
                assert 'Correct this invalid review' in json.dumps(json.loads(evidence)['correction_required'])
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store)
        done=run_analysis_loop(store,lead,w.automation.id,model=BadCritic())
        assert analysis_view(done)['answer']==answer()
        assert len(done.company_analysis['retry_loop']['passes'])==2
        attempts=done.company_analysis['attempts']
        assert [a['task'] for a in attempts].count('public_analysis')==1
        assert [a['task'] for a in attempts].count('public_analysis_review')==3
        assert done.company_analysis['candidate_response_id']==attempts[0]['id']


def test_model_removes_only_forbidden_patch_keys_and_provenance_replays(tmp_path):
    class ExtraPatch(Model):
        def __init__(self):super().__init__(revise=True)
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task=='public_analysis_patch':
                data={'patches':[{'field':'findings.0.text','value':'Customer demand is reported as seasonal; cash timing remains an inference.','unwanted_note':None}]}
                self.last_response_text=json.dumps(data)
                return schema.model_validate(data)
            if task=='public_analysis_patch_cleanup':
                self.last_response_text=json.dumps({'remove_fields':['patches.0.unwanted_note']})
                return schema.model_validate_json(self.last_response_text)
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'db') as store:
        lead,w=setup(store)
        done=run_analysis(store,lead,w.automation.id,model=ExtraPatch())
        assert analysis_view(done)['answer']['findings'][0]['text'].startswith('Customer demand is reported')
        rows=done.company_analysis['attempts']
        assert any(a['task']=='public_analysis_patch_cleanup' for a in rows)
        original=next(a for a in rows if a['task']=='public_analysis_patch')
        assert 'unwanted_note' in original['raw_response']
        original['raw_response']='tampered'
        assert 'answer' not in analysis_view(done)


def test_patch_cleanup_cannot_remove_valid_content():
    from agents.analysis.company_analysis import FormatRepair,AnalysisPatch,apply_format_repair
    raw=json.dumps({'patches':[{'field':'findings.0.text','value':'Some existing content.','extra':None}]})
    with pytest.raises(ValueError,match='only distinct schema-forbidden'):
        apply_format_repair(raw,FormatRepair(remove_fields=['patches.0.value'],edits=[]),AnalysisPatch)
