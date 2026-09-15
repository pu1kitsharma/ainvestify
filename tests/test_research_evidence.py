import json
from copy import deepcopy
from pathlib import Path

import pytest

from agents.research_evidence import business_excerpts, resolve_excerpt
from agents.shared_preparation import SharedAnalysis, SharedFounder, render_sections, review_request
from agents.analyst_pack import validate_section


def retained_resend():
    path=Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-unseen-source-cleanup/resend-retest/resend_us.json'
    return json.loads(path.read_text())['pack']


def current_resend():
    pack=retained_resend();facts=pack['record']['facts']
    excerpt=next(e for e in business_excerpts(facts) if 'Deliver transactional and marketing emails' in e.quote)
    analysis=SharedAnalysis(**pack['shared']['analysis'])
    analysis.business.excerpt_id=excerpt.id;analysis.business.fact_ids=[excerpt.fact_id]
    founder=SharedFounder(**pack['shared']['founder']);founder.opening.fact_ids=[excerpt.fact_id]
    return facts,analysis,founder


def test_original_passed_pricing_footer_is_no_longer_a_business_description():
    pack=retained_resend()
    assert pack['shared']['review']['verdict']=='pass'
    assert 'Glauber Costa' in pack['sections']['research.business']['content']['text']
    with pytest.raises(ValueError,match='business: Select a supplied concise'):
        render_sections(SharedAnalysis(**pack['shared']['analysis']),None,pack['record']['facts'])
    candidates=business_excerpts(pack['record']['facts'])
    assert candidates and all(e.fact_id=='S2' for e in candidates)
    assert all('HTTP 200:' not in e.quote and 'await resend' not in e.quote for e in candidates)


def test_unsupported_order_is_excluded_before_generation_without_hiding_valid_orders():
    from agents.shared_preparation import bound_schema
    facts=retained_resend()['record']['facts']
    schema=bound_schema(SharedAnalysis,facts)
    data=retained_resend()['shared']['analysis']
    data['economics']['summary']='The published sources describe paid email delivery plans with usage-based limits. Actual retained income and delivery costs require company records.'
    data['business']={'fact_ids':['S2'],'excerpt_id':business_excerpts(facts)[0].id}
    data['customer_test']['event']='completed order'
    with pytest.raises(ValueError,match='customer_test.event'):
        schema.model_validate(data)
    data['customer_test']['event']='recorded product use'
    schema.model_validate(data)
    facts[0]['quote']='The company delivers customer orders for shops.'
    schema=bound_schema(SharedAnalysis,facts)
    data['customer_test']['event']='completed order'
    schema.model_validate(data)


def test_managed_plan_cannot_borrow_order_activation_from_neighboring_trading_plan():
    from agents.research_evidence import managed_service
    from agents.shared_preparation import plans_from_analysis
    from tests.test_shared_preparation import analysis_data
    facts=[{'id':'S1','quote':'Basic Plan\n\nCustomers place their own trades. No advisory services are included.\n\nGuided Plan\n\nIncludes managed strategies and portfolio monitoring.\n\nBasic customers pay brokerage on order execution.'}]
    assert managed_service('Guided Plan',facts,['S1'])
    assert not managed_service('Basic Plan',facts,['S1'])
    data=analysis_data();data['customer_test'].update(service='Guided Plan',event='completed order')
    with pytest.raises(ValueError,match='managed/advisory service'):
        plans_from_analysis(SharedAnalysis(**data),facts)
    data['customer_test'].update(service='Basic Plan')
    plans_from_analysis(SharedAnalysis(**data),facts)
    data['customer_test'].update(service='Guided Plan',event='enrollment')
    plans_from_analysis(SharedAnalysis(**data),facts)


def test_retained_live_model_pass_cannot_publish_order_activation_for_advisory_plan():
    from agents.shared_preparation import plans_from_analysis
    path=Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-research-reliability/live-paasa.json'
    pack=json.loads(path.read_text())['pack']
    assert pack['shared']['review']['verdict']=='pass'
    assert pack['shared']['analysis']['customer_test']['event']=='completed order'
    with pytest.raises(ValueError,match='managed/advisory service'):
        plans_from_analysis(SharedAnalysis(**pack['shared']['analysis']),pack['record']['facts'])


def test_business_and_founder_are_short_with_original_context_preserved():
    facts,analysis,founder=current_resend();original=deepcopy(facts)
    drafts=render_sections(analysis,founder,facts)
    business=drafts['research.business'];opening=drafts['founder.observation']
    assert 'Email for\n\ndevelopers' in business.text
    assert 'Deliver transactional and marketing emails' in business.text
    assert len(business.text)<250 and len(opening.reported_observation)<250
    assert 'Glauber Costa' not in business.text
    assert facts==original and len(next(f['quote'] for f in facts if f['id']=='S2'))>3000
    assert business.source_excerpt.quote in next(f['quote'] for f in facts if f['id']=='S2')
    # Published pricing is never shortened to an unqualified summary.
    economics=drafts['research.economics'].revenue_mechanism
    assert all(f['quote'] in economics for f in facts if f['category']=='commercial_terms')


def test_excerpt_cannot_be_rewritten_or_detached_from_parent():
    facts,analysis,founder=current_resend()
    draft=render_sections(analysis,founder,facts)['research.business']
    draft.source_excerpt.quote='An invented claim of independently verified company profitability.'
    with pytest.raises(ValueError,match='complete parent source'):
        validate_section(draft,facts,'research.business')
    with pytest.raises(ValueError,match='supplied business excerpt'):
        resolve_excerpt('invented',facts)


def test_adjacent_qualification_is_inseparable_from_excerpt():
    facts=[{'id':'S1','category':'offering','quote':'Business accounts\n\nThe company provides a payment processing service for shops.\n\nOnly available to approved enterprises; partners operate the accounts.'}]
    excerpt=business_excerpts(facts)[0]
    assert 'Only available' in excerpt.quote and 'partners operate' in excerpt.quote


def test_review_checks_relevance_and_full_context_without_duplicating_sources():
    facts,analysis,founder=current_resend()
    _,payload,passages,_=review_request(analysis,founder,facts)
    assert {'analysis.business','analysis.economics','founder.opening'}<={p['field'] for p in passages}
    check=next(p for p in passages if p['field']=='analysis.business')
    assert 'COMPLETE parent source' in check['check']
    assert check['basis']['S2']==next(f['quote'] for f in facts if f['id']=='S2')
    encoded=json.dumps(payload)
    for quote in payload['basis'].values():
        assert encoded.count(json.dumps(quote))==1


def test_financial_qualification_reaches_analysis_and_blocks_false_contribution(tmp_path):
    from agents.company_metrics import metrics_report
    from agents.analyst_pack import financial_facts
    from agents.shared_preparation import source_record
    from agents.operating_workflow import reconcile_workspace
    from tests.test_operating_workflow import company
    from api.routers.operations import metrics_markdown
    from store import Store
    source='Revenue: GBP 1000, net of direct variable delivery costs. This is not gross revenue.'
    with Store(tmp_path/'db') as store:
        lead=company(store);w=reconcile_workspace(store,lead)
        w.metrics=metrics_report([{'id':'M1','month':'2025-08','currency':'GBP','revenue':'1000','direct_costs':'700','source_note':'Company finance update',
            'field_sources':{'revenue':{'quote':source,'source_name':'Company finance update'}}}])
        facts=financial_facts(w,'2026-09-15')
        assert source in facts[0]['quote'] and 'Calculation deferred' in facts[0]['quote']
        assert not any(f.get('category')=='calculated_metrics' for f in facts)
        assert source in next(f['quote'] for f in source_record(lead,w)['facts'] if f['id']=='M1')
        assert 'Delivery contribution — unresolved' in metrics_markdown(w)


def test_large_financial_packet_is_bounded_without_cutting_qualifications(tmp_path):
    from agents.company_metrics import metrics_report
    from agents.shared_preparation import source_record
    from agents.operating_workflow import reconcile_workspace
    from tests.test_operating_workflow import company
    from store import Store
    with Store(tmp_path/'db') as store:
        lead=company(store);w=reconcile_workspace(store,lead)
        w.metrics=metrics_report([{'id':str(i),'month':f'2025-{i:02}','currency':'GBP','revenue':'1000','source_note':'Company finance update',
            'field_sources':{'revenue':{'quote':('Complete context. '*180)+'Revenue is net of partner charges.'}}} for i in range(1,13)])
        record=source_record(lead,w)
        assert sum(len(f['quote']) for f in record['facts'])<=14000
        assert record['coverage']=='partial' and record['source_selection']['omitted_for_context']>0
        assert any(f['category']=='offering' for f in record['facts'])
        assert all('Revenue is net of partner charges.' in f['quote'] for f in record['facts'] if f['origin']=='company_reported')


def test_reported_waybill_excerpt_citation_error_is_resolved_without_inference():
    path=Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-readable-research/waybill-before.json'
    pack=json.loads(path.read_text())['workspace']['analyst_pack']
    answer=pack['attempts'][0]['answer'];facts=pack['record']['facts']
    assert answer['business']['fact_ids']==['S6','S7']
    excerpt=resolve_excerpt(answer['business']['excerpt_id'],facts)
    assert excerpt.fact_id=='S1'
    original=deepcopy(answer)
    rendered=render_sections(SharedAnalysis(**answer),None,facts)
    assert rendered['research.business'].fact_ids==['S1']
    assert rendered['research.business'].source_excerpt==excerpt
    assert answer==original


def test_business_inference_contract_requests_only_excerpt_not_redundant_parent_ids():
    from agents.shared_preparation import bound_schema
    facts,analysis,_=current_resend()
    schema=bound_schema(SharedAnalysis,facts)
    assert set(schema.model_fields['business'].annotation.model_fields)=={'excerpt_id'}
    data=analysis.model_dump()
    data['business']={'excerpt_id':analysis.business.excerpt_id}
    data['economics']['summary']='The published sources describe paid email plans with usage limits. Company records are needed to establish realized income and delivery costs.'
    parsed=SharedAnalysis.model_validate(schema.model_validate(data).model_dump())
    assert render_sections(parsed,None,facts)['research.business'].fact_ids==['S2']


def test_economics_explanation_is_short_and_source_context_stays_separate():
    facts,analysis,founder=current_resend()
    analysis.economics.summary='The published pricing describes email delivery plans with usage limits and optional add-ons. Company records are needed to establish realized income and delivery costs.'
    drafts=render_sections(analysis,founder,facts)
    economics=drafts['research.economics']
    assert economics.source_quotes is False
    assert economics.revenue_mechanism=='Published source summary: '+analysis.economics.summary
    assert len(economics.revenue_mechanism)<800
    assert set(f['id'] for f in facts if f['category']=='commercial_terms')<=set(economics.fact_ids)
    economics.revenue_mechanism='The website states that customers pay 999999 every month.'
    with pytest.raises(ValueError,match='NO|No|numerical|numerical rates|without numerical'):
        validate_section(economics,facts)


def test_source_attribution_is_attached_without_an_extra_generation_call():
    facts,analysis,_=current_resend()
    analysis.economics.summary='Customers pay for email delivery plans with usage limits. Realized income and costs need company records.'
    economics=render_sections(analysis,None,facts)['research.economics']
    assert economics.revenue_mechanism=='Published source summary: '+analysis.economics.summary
    validate_section(economics,facts)


def test_actual_waybill_payment_cannot_be_published_as_a_consolidated_company_fee():
    path=Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-readable-research/waybill-first-attempt.json'
    pack=json.loads(path.read_text())['analyst_pack']
    analysis=SharedAnalysis(**pack['attempts'][0]['answer']);facts=pack['record']['facts']
    with pytest.raises(ValueError,match='payment that settles suppliers'):
        render_sections(analysis,None,facts)
    analysis.economics.summary='Customers make one payment covering parts, freight, duties and delivery; Waybill settles the suppliers and other parties. The supplied material does not disclose its own fee or retained share.'
    draft=render_sections(analysis,None,facts)['research.economics']
    assert 'does not disclose its own fee' in draft.revenue_mechanism


def test_retained_paasa_review_pass_still_requires_correct_billing_periods():
    from agents.shared_preparation import AnalysisCorrections
    path=Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-readable-research/final/paasa.json'
    pack=json.loads(path.read_text())['workspace']['analyst_pack']
    assert pack['shared']['review']['verdict']=='pass'
    analysis=SharedAnalysis(**pack['shared']['analysis']);facts=pack['record']['facts']
    with pytest.raises(AnalysisCorrections) as error:render_sections(analysis,None,facts)
    assert error.value.fields=={'economics'}
    assert 'annual fee from monthly collection' in str(error.value)
    analysis.customer_test.event='completed order'
    with pytest.raises(AnalysisCorrections) as error:render_sections(analysis,None,facts)
    assert error.value.fields=={'economics','customer_test'}
    analysis.customer_test.event='enrollment'
    analysis.economics.summary='Access customers pay trade-based charges without a recurring plan fee. Apex customers pay an annual asset-based advisory fee, collected monthly; brokerage remains separate and licensed partners provide banking and brokerage services.'
    render_sections(analysis,None,facts)
    analysis.economics.summary='Apex fees are deducted annually. Monthly charges are also mentioned by the website.'
    with pytest.raises(ValueError,match='not an annual deduction'):render_sections(analysis,None,facts)


def test_custodian_role_is_not_evidence_of_a_custody_fee():
    path=Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-readable-research/verified/paasa.json'
    pack=json.loads(path.read_text())['workspace']['analyst_pack']
    assert pack['shared']['review']['verdict']=='pass'
    with pytest.raises(ValueError,match='Custody of assets does not establish'):
        render_sections(SharedAnalysis(**pack['shared']['analysis']),None,pack['record']['facts'])
    from agents.research_evidence import validate_billing_summary
    facts=[{'id':'f','quote':'Assets are held by the custodian. Brokerage is charged per trade.'}]
    validate_billing_summary('The source does not disclose custody fees.',facts,['f'])
    facts[0]['quote']='A separate custody fee applies.'
    validate_billing_summary('The company reports a custody fee.',facts,['f'])


def test_published_terms_do_not_turn_into_asserted_accounting_results():
    from agents.research_evidence import commercial_terms_text
    path=Path(__file__).parents[1]/'evals/investment_preparation/section-workflows/v9-readable-research/accepted/paasa.json'
    pack=json.loads(path.read_text())['workspace']['analyst_pack'];original=deepcopy(pack['shared']['analysis'])
    raw=original['economics']['summary'];assert 'recognized as company revenue' in raw
    rendered=render_sections(SharedAnalysis(**original),SharedFounder(**pack['shared']['founder']),pack['record']['facts'])
    summary=rendered['research.economics'].revenue_mechanism
    assert 'recognized as company revenue' not in summary
    assert 'annual percentage fee' in summary and 'automatic monthly deductions' in summary
    assert 'Published statements do not establish realized income' in rendered['research.economics'].unknown_economics
    assert pack['shared']['analysis']==original
    _,payload,passages,_=review_request(SharedAnalysis(**original),SharedFounder(**pack['shared']['founder']),pack['record']['facts'])
    assert next(p['text'] for p in passages if p['field']=='analysis.economics')==summary
    assert commercial_terms_text('All collected fees are recognized as company revenue.')==''
