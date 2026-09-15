import json
from copy import deepcopy

import pytest

from agents.analyst_pack import prepare_analyst_pack as _prepare_pack, export_pack, VERSION, validate_saved_sections
from agents.measurement_plan import contribution_method, customer_method, DecisionMeasurementPlan
from agents.preparation_budget import PreparationBudget
from agents.shared_preparation import SharedAnalysis, plans_from_analysis
from store import Store
from tests.test_operating_workflow import company


# Preserve v9 regression evidence through its explicit historical entry point.
# The application default is tested in test_authored_preparation.py.
def prepare_analyst_pack(*args, **kwargs):
    return _prepare_pack(*args, **kwargs, workflow='shared')


def analysis_data(identifier='S1'):
    return {'economics_test':{'service':'Room stays','fact_ids':[identifier]},
        'customer_test':{'service':'Room stays','method':'activation','event':'completed booking','fact_ids':[identifier]},
        'business':{'fact_ids':[identifier]},
        'economics':{'fact_ids':[identifier]},
        'risk':{'focus':'delivery_costs','fact_ids':[identifier]}}


class SharedModel:
    name='offline'
    def __init__(self,objections=False):self.calls=[];self.objections=objections;self.last_route={};self.last_response_text=''
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        payload=json.loads(evidence);self.calls.append((task,payload))
        if task=='shared_analysis':
            data=analysis_data()
            data['economics']['summary']='The supplied sources describe hotel operations. They do not establish the charging terms, realized revenue or the cost of providing the service.'
            if payload.get('business_excerpts'):
                excerpt=payload['business_excerpts'][0]
                data['business']={'fact_ids':[excerpt['fact_id']],'excerpt_id':excerpt['id']}
        elif task=='shared_founder':
            data={'opening':{'text':'Your website describes hotel rooms for business travelers.','fact_ids':['S1']},
                'offer':{'text':'We could request redacted room billing, settlement, service-cost and booking records to prepare a contribution table and booking-activation cohorts. These would identify pricing or delivery-cost work and which customer groups merit further acquisition effort.','fact_ids':['S1']},
                'customer_records':'We would request redacted account-event and cohort exports with anonymized customer IDs, dates and completed booking status.',
                'invitation':'Would you be open to discussing these records and the proposed assessment?'}
        else:
            data={'verdict':'revise' if self.objections else 'pass','issues':[
                {'passage_id':'D1','basis_id':'task','defect':'entity_scope','explanation':'The selected service is assigned to the wrong operating entity; confirm the contracting entity.'}] if self.objections else []}
        self.last_response_text=json.dumps(data)
        return schema.model_validate(data)


def test_registered_methods_are_coherent_without_model_arithmetic():
    plan=contribution_method('Hotel stays')
    assert plan.operation=='subtract' and plan.purpose=='contribution'
    assert plan.left.deducted_costs==['partner_charge']
    assert plan.partner_charge_treatment=='already_deducted_from_revenue'
    assert 'Entity chart' in plan.records() and 'staff-time allocations' in plan.records()
    for method in ('activation','repeat_use','retention'):
        plan=customer_method(method,'Hotel stays','a completed stay')
        assert plan.operation=='divide' and plan.left.unit==plan.right.unit=='unique customers'
        assert plan.population_relation=='numerator_subset_of_denominator'
        assert plan.left.exposure==plan.right.exposure
        assert 'exclude immature' in plan.left.exposure
        assert 'customer key' in plan.left.record_needed and 'customer key' in plan.right.record_needed
        DecisionMeasurementPlan.model_validate(plan.model_dump())
    with pytest.raises(ValueError):customer_method('problem_resolution','Hotels','delight')


def test_retained_unseen_email_api_cannot_use_an_unsupported_order_event():
    from pathlib import Path
    original=json.loads((Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-unseen-source-cleanup/resend_us.json').read_text())['pack']
    assert original['shared']['review']['verdict']=='pass'
    analysis=SharedAnalysis(**original['shared']['analysis'])
    assert analysis.customer_test.event=='completed order'
    with pytest.raises(ValueError,match='Completed order requires source evidence'):
        plans_from_analysis(analysis,original['record']['facts'])
    from agents.analyst_pack import current_review_hash
    for section in original['sections'].values():section['review_hash']=current_review_hash(original)
    validate_saved_sections(original)
    assert not any(s['status']=='complete' for s in original['sections'].values())


def test_literal_instruction_label_is_removed_but_invitation_is_not_rewritten():
    from agents.shared_preparation import SharedFounder
    data=SharedModel().generate_for_task('shared_founder','','{}',SharedFounder).model_dump()
    data['invitation']='Invite a conversation with one question: Are you available to discuss these records?'
    founder=SharedFounder(**data)
    assert founder.invitation=='Are you available to discuss these records?'
    assert data['invitation'].startswith('Invite a conversation')


def test_retained_live_offer_cannot_promise_contribution_without_cost_inputs():
    from pathlib import Path
    from agents.shared_preparation import SharedFounder,render_sections
    original=json.loads((Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-unseen-source-cleanup/paasa-refresh-retest/live-paasa.json').read_text())['pack']
    # Supply the new reading-aid selection while retaining the original failed
    # offer verbatim, so this regression continues to isolate cost omission.
    from agents.research_evidence import business_excerpts
    excerpt=business_excerpts(original['record']['facts'])[0]
    original['shared']['analysis']['business']={'fact_ids':[excerpt.fact_id],'excerpt_id':excerpt.id}
    original['shared']['analysis']['customer_test']['event']='enrollment'
    original['shared']['founder']['opening']={'fact_ids':[excerpt.fact_id]}
    with pytest.raises(ValueError,match='offer: The contribution offer must request'):
        render_sections(SharedAnalysis(**original['shared']['analysis']),SharedFounder(**original['shared']['founder']),original['record']['facts'])


def test_missing_cost_input_repairs_only_offer_and_preserves_customer_request(tmp_path):
    class MissingCosts(SharedModel):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            payload=json.loads(evidence)
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task=='shared_founder' and 'code_feedback' not in payload:
                result.offer.text='We propose using your billing ledger to prepare a contribution table and a customer-cohort table before an expansion decision.'
                self.last_response_text=json.dumps(result.model_dump())
            if 'code_feedback' in payload:
                assert set(schema.model_fields)=={'offer'}
                assert 'cost inputs' in payload['code_feedback']
                assert 'opening_sources' not in payload
                assert 'proposed_work' in payload and 'citation_ids' in payload
            return result
    with Store(tmp_path/'db') as store:
        model=MissingCosts();pack=prepare_analyst_pack(store,company(store),model).analyst_pack
        assert pack['status']=='complete'
        assert [t for t,_ in model.calls]==['shared_analysis','shared_founder','shared_founder','shared_review']
        assert pack['shared']['founder']['customer_records'].startswith('We would request redacted account-event')


def test_retired_shared_workflow_produces_nine_sections_in_three_calls_then_zero(tmp_path):
    with Store(tmp_path/'db') as store:
        lead=company(store);model=SharedModel();updates=[]
        w=prepare_analyst_pack(store,lead,model,lambda p:updates.append(deepcopy(p)))
        assert w.analyst_pack['version']==VERSION
        assert w.analyst_pack['status']=='complete'
        assert len(w.analyst_pack['sections'])==9
        assert [t for t,_ in model.calls]==['shared_analysis','shared_founder','shared_review']
        assert w.analyst_pack['record']['facts'][0]['quote'] in [e.quote for e in lead.company_profile.evidence]
        assert not any(s.get('status')=='complete' for p in updates[:-1] for s in p['sections'].values())
        assert 'Entity chart' in export_pack(w.analyst_pack)
        assert 'First ninety days' in export_pack(w.analyst_pack)
        cached=SharedModel();prepare_analyst_pack(store,lead,cached)
        assert cached.calls==[]


def test_economics_repair_uses_sources_without_reinserting_rejected_prose(tmp_path):
    class BadEconomics(SharedModel):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            payload=json.loads(evidence)
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task=='shared_analysis' and 'code_feedback' not in payload:
                result.economics.summary='Customers pay an invented monthly charge of 999999 for hotel rooms.'
                self.last_response_text=json.dumps(result.model_dump())
            elif task=='shared_analysis':
                assert set(schema.model_fields)=={'economics'}
                assert set(payload)=={'company','facts','code_feedback'}
                assert payload['facts'] and 'invented monthly charge' not in evidence
                assert 'retained share' in instruction
            return result
    with Store(tmp_path/'db') as store:
        model=BadEconomics();pack=prepare_analyst_pack(store,company(store),model).analyst_pack
        assert pack['status']=='complete'
        assert [t for t,_ in model.calls]==['shared_analysis','shared_analysis','shared_founder','shared_review']


def test_a_new_defect_in_a_correction_gets_one_more_bounded_targeted_repair(tmp_path):
    class TwoCorrections(SharedModel):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task=='shared_analysis' and sum(t==task for t,_ in self.calls)<3:
                result.economics.summary='Customers pay 999999 per month for an invented package.'
                self.last_response_text=json.dumps(result.model_dump())
            return result
    with Store(tmp_path/'db') as store:
        model=TwoCorrections();w=prepare_analyst_pack(store,company(store),model)
        assert w.analyst_pack['status']=='complete'
        assert [t for t,_ in model.calls]==['shared_analysis']*3+['shared_founder','shared_review']


def test_budget_stop_reuses_analysis_without_a_second_analysis_call(tmp_path):
    with Store(tmp_path/'db') as store:
        lead=company(store)
        w=prepare_analyst_pack(store,lead,SharedModel(),budget=PreparationBudget(10,max_calls=1))
        assert w.analyst_pack['shared']['analysis']
        assert 'model-call limit' in w.analyst_pack['stop_reason']
        resumed=SharedModel();w=prepare_analyst_pack(store,lead,resumed)
        assert w.analyst_pack['status']=='complete'
        assert [t for t,_ in resumed.calls]==['shared_founder','shared_review']


def test_validator_update_revalidates_saved_candidates_and_only_repeats_review(tmp_path,monkeypatch):
    import agents.shared_preparation as shared
    with Store(tmp_path/'db') as store:
        lead=company(store);before=prepare_analyst_pack(store,lead,SharedModel()).analyst_pack
        original=deepcopy(before['shared']);monkeypatch.setattr(shared,'CONTRACT_HASH','updated-test-contract')
        model=SharedModel();w=prepare_analyst_pack(store,lead,model)
        assert w.analyst_pack['status']=='complete'
        assert [t for t,_ in model.calls]==['shared_review']
        assert w.analyst_pack['shared']==original
        assert w.analyst_pack['candidate_reuse']['requires_current_validation_and_review'] is True
        assert w.analyst_pack_history[-1]['shared']==original


def test_validator_update_repairs_only_invalid_saved_economics_then_reviews(tmp_path,monkeypatch):
    import agents.shared_preparation as shared
    with Store(tmp_path/'db') as store:
        lead=company(store);w=prepare_analyst_pack(store,lead,SharedModel())
        w.analyst_pack['shared']['analysis']['economics']['summary']='Customers pay 999999 per month for an invented package.'
        store.save_workspace(w,expected_revision=w.revision)
        monkeypatch.setattr(shared,'CONTRACT_HASH','updated-test-contract')
        model=SharedModel();w=prepare_analyst_pack(store,lead,model)
        assert w.analyst_pack['status']=='complete'
        assert [t for t,_ in model.calls]==['shared_analysis','shared_review']
        payload=model.calls[0][1]
        assert 'code_feedback' in payload and 'draft_to_correct' not in payload
        assert '999999' in w.analyst_pack_history[-1]['shared']['analysis']['economics']['summary']


def test_changed_source_does_not_reuse_old_analysis_candidates(tmp_path,monkeypatch):
    import agents.shared_preparation as shared
    with Store(tmp_path/'db') as store:
        lead=company(store);w=prepare_analyst_pack(store,lead,SharedModel())
        w.analyst_pack['record']['facts'][0]['quote']='A changed source record.'
        store.save_workspace(w,expected_revision=w.revision)
        monkeypatch.setattr(shared,'CONTRACT_HASH','updated-test-contract')
        model=SharedModel();w=prepare_analyst_pack(store,lead,model)
        assert [t for t,_ in model.calls]==['shared_analysis','shared_founder','shared_review']
        assert 'candidate_reuse' not in w.analyst_pack


def test_rejected_review_is_not_published_and_exact_passage_is_retained(tmp_path):
    with Store(tmp_path/'db') as store:
        w=prepare_analyst_pack(store,company(store),SharedModel(objections=True))
        assert w.analyst_pack['status']=='partial'
        assert 'material review objections' in w.analyst_pack['stop_reason']
        assert all(s['status']=='needs_revision' for s in w.analyst_pack['sections'].values())
        assert 'room billing' not in export_pack(w.analyst_pack)
        objection=w.analyst_pack['shared']['review']['objections'][0]
        assert objection['field']=='analysis.economics_test' and 'Room stays' in objection['passage']


def test_existing_semantic_and_citation_guards_still_apply_to_choices():
    facts=[{'id':'S1','quote':'The company offers rooms.'}]
    for mutate in (lambda d:d['economics_test'].update(fact_ids=['fake']),lambda d:d['economics_test'].update(service='Rooms for 999 customers')):
        data=analysis_data();mutate(data)
        with pytest.raises(ValueError):plans_from_analysis(SharedAnalysis(**data),facts)


@pytest.mark.parametrize('event',['customer satisfaction','problem resolution','guaranteed returns','customer loyalty'])
def test_customer_events_cannot_claim_unmeasured_outcomes(event):
    data=analysis_data();data['customer_test']['event']=event
    with pytest.raises(ValueError):SharedAnalysis(**data)


@pytest.mark.parametrize('method',['repeat_use','retention'])
def test_initial_pack_does_not_assume_repeat_purchase_or_retention(method):
    data=analysis_data();data['customer_test']['method']=method
    with pytest.raises(ValueError):SharedAnalysis(**data)


def test_derived_founder_question_keeps_its_own_product_number_citations():
    from agents.shared_preparation import SharedFounder,render_sections
    facts=[{'id':'S1','quote':'The website describes pumps for smallholder farmers.'},
           {'id':'S2','quote':'ClimateSmart Direct 2 uses the RainMaker 2S pump.'}]
    data=analysis_data()
    for key in ('economics_test','customer_test'):
        data[key].update(service='ClimateSmart Direct 2',fact_ids=['S2'])
    founder=SharedModel().generate_for_task('shared_founder','','{}',SharedFounder)
    drafts=render_sections(SharedAnalysis(**data),founder,facts)
    assert set(drafts['founder.observation'].fact_ids)=={'S1','S2'}
    assert 'ClimateSmart Direct 2' in drafts['founder.observation'].question_to_explore


def test_founder_opening_cannot_transfer_another_products_edibility_claim():
    from pathlib import Path
    from agents.shared_preparation import SharedFounder,render_sections
    original=json.loads((Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-final/notpla_uk.json').read_text())['pack']
    assert 'entirely edible' in original['shared']['founder']['opening']['text']
    facts=original['record']['facts'];source=next(f for f in facts if f['category']=='offering')
    data=deepcopy(original['shared']['founder'])
    data['opening']={'fact_ids':[source['id']],'text':data['opening']['text']}
    rendered=render_sections(SharedAnalysis(**original['shared']['analysis']),SharedFounder(**data),facts)
    opening=rendered['founder.observation']
    assert opening.reported_observation=='Your published materials state: “'+source['quote']+'”'
    assert 'edible' not in opening.reported_observation


def test_saved_source_marker_cannot_bypass_exact_quotation_validation(tmp_path):
    with Store(tmp_path/'db') as store:
        pack=prepare_analyst_pack(store,company(store),SharedModel()).analyst_pack
        for key in ['research.business','founder.observation']:
            content=pack['sections'][key]['content'];content.pop('source_quotes')
            content['text' if key=='research.business' else 'reported_observation']='Your website reports independently verified profitable growth.'
        validate_saved_sections(pack)
        assert all(pack['sections'][key]['status']=='needs_revision' for key in ['research.business','founder.observation'])


def test_reported_service_gets_its_complete_source_without_model_citation_repair():
    from pathlib import Path
    from agents.shared_preparation import service_citations,ContributionChoice
    original=json.loads((Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-initial-preparation/sunculture_kenya.json').read_text())['pack']
    choice=SharedAnalysis(**original['attempts'][0]['answer'])
    assert choice.customer_test.fact_ids==['S6']
    requests=plans_from_analysis(choice,original['record']['facts'])
    assert requests[1].fact_ids==['S6','S4']
    # A superficially similar word is not source support for another product.
    assert service_citations(ContributionChoice(service='Apex',fact_ids=['S1']),[
        {'id':'S1','quote':'Business activity is reported.'},{'id':'S2','quote':'The company reports CAPEX spending.'}])==['S1']


def test_saved_derived_method_cannot_be_replaced_with_bad_arithmetic(tmp_path):
    with Store(tmp_path/'db') as store:
        w=prepare_analyst_pack(store,company(store),SharedModel())
        pack=deepcopy(w.analyst_pack)
        pack['sections']['diligence.request_a']['content']['analysis_plan']['operation']='divide'
        validate_saved_sections(pack)
        assert pack['sections']['diligence.request_a']['status']=='needs_revision'
        assert pack['sections']['readiness.action_a']['status']!='complete'


def test_invalid_customer_request_repairs_only_that_sentence_and_keeps_opening(tmp_path):
    class MissingCustomerRecords(SharedModel):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            payload=json.loads(evidence)
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task=='shared_founder' and 'code_feedback' not in payload:
                result.customer_records='We would request a final cohort table showing the resulting customer metric.'
                self.last_response_text=json.dumps(result.model_dump())
            if 'code_feedback' in payload:
                assert set(schema.model_fields)=={'customer_records'}
                assert 'underlying redacted customer' in payload['code_feedback']
            return result
    with Store(tmp_path/'db') as store:
        model=MissingCustomerRecords();w=prepare_analyst_pack(store,company(store),model)
        assert w.analyst_pack['status']=='complete'
        assert [t for t,_ in model.calls]==['shared_analysis','shared_founder','shared_founder','shared_review']
        assert w.analyst_pack['shared']['founder']['opening']['fact_ids']==['S1']


def test_missing_selection_repairs_only_missing_field(tmp_path):
    class MissingSelection(SharedModel):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            payload=json.loads(evidence)
            if task=='shared_analysis' and 'code_feedback' not in payload:
                self.calls.append((task,payload))
                data=analysis_data();data.pop('customer_test')
                data['economics']['summary']='The supplied sources describe hotel operations. Charging terms, realized revenue and delivery costs require more evidence.'
                self.last_response_text=json.dumps(data)
                return schema.model_validate(data)
            if 'code_feedback' in payload:
                assert set(schema.model_fields)=={'customer_test'}
                assert kwargs['attempt']==1
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'db') as store:
        model=MissingSelection();w=prepare_analyst_pack(store,company(store),model)
        assert w.analyst_pack['status']=='complete'
        assert [t for t,_ in model.calls]==['shared_analysis','shared_analysis','shared_founder','shared_review']


def test_polling_omits_shared_candidates_without_mutating_saved_state(tmp_path):
    from api.routers.operations import company_work_view
    with Store(tmp_path/'db') as store:
        w=prepare_analyst_pack(store,company(store),SharedModel(),budget=PreparationBudget(10,max_calls=1))
        assert 'analysis' in w.analyst_pack['shared']
        assert 'shared' not in company_work_view(w)['analyst_pack']
        assert 'analysis' in w.analyst_pack['shared']


def test_source_attribution_and_cohort_event_exports_do_not_need_rewrites(tmp_path):
    class Wording(SharedModel):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task=='shared_founder':result.customer_records='We could request redacted cohort event exports for completed bookings, with anonymized customer IDs and event dates.'
            return result
    with Store(tmp_path/'db') as store:
        model=Wording();w=prepare_analyst_pack(store,company(store),model)
        assert w.analyst_pack['status']=='complete' and len(model.calls)==3
        assert w.analyst_pack['sections']['research.business']['content']['text'].startswith('The supplied sources state:')


def test_quoted_descriptions_preserve_qualifications_and_reject_tampering():
    from agents.shared_preparation import render_sections
    from agents.analyst_pack import validate_section
    facts=[{'id':'S1','quote':'A plan charges 1% of assets annually, collected monthly. Brokerage remains separate, with no markup.'}]
    from agents.research_evidence import business_excerpts
    data=analysis_data();data['business']['excerpt_id']=business_excerpts(facts)[0].id
    drafts=render_sections(SharedAnalysis(**data),None,facts)
    for key,field in (('research.business','text'),('research.economics','revenue_mechanism')):
        draft=drafts[key]
        assert facts[0]['quote'] in getattr(draft,field)
        setattr(draft,field,'The supplied sources state: Assets generate profit without brokerage costs.')
        with pytest.raises(ValueError,match='exact complete cited excerpts'):validate_section(draft,facts,key)
    decision=drafts['research.decision']
    assert 'covers attributable variable delivery costs' in decision.reason_to_engage
    assert 'consumes its retained income' in decision.unresolved_risk
    assert 'assets' not in decision.reason_to_engage+decision.unresolved_risk


def test_source_topic_coverage_cannot_drop_core_offering_or_plan_qualification():
    from agents.shared_preparation import render_sections,review_request,SharedFounder
    facts=[{'id':'S1','category':'company_structure','quote':'The company works with licensed service partners.'},
           {'id':'S2','category':'offering','quote':'The website offers rooms to business travelers.'},
           {'id':'S3','category':'pricing','quote':'Flexible bookings have a nightly fee. Partner charges apply separately.'}]
    analysis=SharedAnalysis(**analysis_data())
    drafts=render_sections(analysis,None,facts)
    assert facts[1]['quote'] in drafts['research.business'].text
    assert facts[2]['quote'] in drafts['research.economics'].revenue_mechanism
    founder=SharedModel().generate_for_task('shared_founder','', '{}',SharedFounder)
    founder.opening.fact_ids=['S2']
    _,payload,passages,_=review_request(analysis,founder,facts)
    assert any(p['field']=='analysis.business' for p in passages)
    assert any(p['field']=='analysis.economics' for p in passages)
    assert any(p['field']=='founder.opening' for p in passages)
    assert payload['basis']['S2']==facts[1]['quote']
    assert all('basis_ids' in p and 'basis' not in p for p in payload['review_checks'])
    offer=next(p for p in passages if p['field']=='founder.offer')
    assert set(offer['basis'])=={'work_contract'}
    assert 'Redacted account-event' in offer['basis']['work_contract']


def test_api_worker_uses_model_authored_workflow_and_publishes_only_completed_work(tmp_path,monkeypatch):
    from fastapi import BackgroundTasks
    from api.routers import operations as api
    import agents.analyst_pack as pipeline
    from tests.test_authored_preparation import Model
    model=Model()
    monkeypatch.setattr(api,'LocalModel',lambda:model)
    monkeypatch.setattr(pipeline,'collect_preparation_evidence',lambda store,lead,**kwargs:lead)
    with Store(tmp_path/'db') as store:
        lead=company(store)
        queued=api.start_analyst_preparation(lead.id,BackgroundTasks(),store,'one')
        api._prepare_job(store.db_path,'one',lead.id,queued['automation']['id'],analyst=True)
        w=store.get_workspace('one',lead_id=lead.id)
        assert w.automation.status=='completed'
        assert w.analyst_pack['status']=='complete'
        assert w.analyst_pack['last_run_budget']['calls']==4
        view=api.company_work_view(w)['analyst_pack']
        assert 'attempts' not in view and 'authored' not in view


def test_unexpected_worker_failure_preserves_saved_work_and_records_stack(tmp_path,monkeypatch,caplog):
    from fastapi import BackgroundTasks
    from api.routers import operations as api
    import agents.analyst_pack as pipeline
    model=SharedModel()
    monkeypatch.setattr(api,'LocalModel',lambda:model)
    def broken_fetcher(*args,**kwargs):
        raise AttributeError('private source detail must not appear in diagnostics')
    monkeypatch.setattr(pipeline,'collect_preparation_evidence',broken_fetcher)
    with Store(tmp_path/'db') as store:
        lead=company(store)
        original=prepare_analyst_pack(store,lead,model).analyst_pack
        calls=len(model.calls)
        queued=api.start_analyst_preparation(lead.id,BackgroundTasks(),store,'one',refresh=True)
        api._prepare_job(store.db_path,'one',lead.id,queued['automation']['id'],analyst=True,refresh=True)
        saved=store.get_workspace('one',lead_id=lead.id)
        assert saved.automation.status=='failed'
        assert 'AttributeError' in saved.automation.error
        assert saved.analyst_pack==original
        assert store.get_lead('one',lead.id).company_profile==lead.company_profile
        assert len(model.calls)==calls
        event=saved.events[-1]
        assert event['action']=='automation_failed' and event['error_type']=='AttributeError'
        assert 'test_shared_preparation.py:' in event['error_traceback']
        assert 'in broken_fetcher' in event['error_traceback']
        assert saved.automation.id in caplog.text and 'in broken_fetcher' in caplog.text
        assert 'private source detail' not in caplog.text+json.dumps(event)+saved.automation.error


def test_migrating_old_work_does_not_restore_the_failed_long_reasoning_profile(tmp_path):
    from fastapi import BackgroundTasks
    from api.routers.operations import start_analyst_preparation
    from agents.operating_workflow import reconcile_workspace
    with Store(tmp_path/'db') as store:
        lead=company(store);w=reconcile_workspace(store,lead)
        w.analyst_pack={'version':7,'generation_config':{'mode':'section_router','model':'qwen3.5:9b','thinking':False,'review_thinking':True}}
        store.save_workspace(w,expected_revision=w.revision)
        tasks=BackgroundTasks();start_analyst_preparation(lead.id,tasks,store,'one')
        kwargs=tasks.tasks[0].kwargs
        assert kwargs['analyst_model'] is None and kwargs['analyst_review_thinking'] is None
        assert store.get_workspace('one',lead_id=lead.id).automation.model=='qwen3.5:9b'
