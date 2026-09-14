import json
from unittest.mock import Mock
import pytest
from agents.growth_analysis import GrowthPair, validate_comparison, analyze_growth
from agents.operating_research import extract_business_evidence, research_company
from agents.web_sources import Page
from schemas import CompanyEvidence, CompanyProfile, SourcedLead
from store import Store


def comparison(quote='Acme revenue rose from 10 crore in FY2024 to 25 crore in FY2025.'):
    evidence=CompanyEvidence(field='traction',value=quote,quote=quote,source_url='https://acme.example/report')
    pair=GrowthPair(evidence_id=evidence.id,metric='revenue',scope='company',before='10',after='25',unit='crore',period_before='FY2024',period_after='FY2025')
    return pair,evidence


def test_calculation_is_from_literals_and_handles_decline():
    p,e=comparison();assert validate_comparison(p,e,'Acme')['change_pct']==150
    p,e=comparison('Acme revenue fell from 10 crore in FY2024 to 5 crore in FY2025.')
    p.after='5';assert validate_comparison(p,e,'Acme')['change_pct']==-50


@pytest.mark.parametrize('change',[
 {'scope':'customer_case_study'},{'scope':'forecast'},{'after':'999'},
 {'period_after':'2025'},{'period_after':'FY2024'},{'before':'0'},
 {'unit':'million'},{'metric':'customers'},
])
def test_reject_uncomparable_or_unsupported_pairs(change):
    p,e=comparison();p=p.model_copy(update=change)
    assert validate_comparison(p,e,'Acme') is None


def test_substring_numbers_forecasts_and_other_entities_are_rejected():
    p,e=comparison('Acme revenue rose from 100 crore in FY2024 to 250 crore in FY2025.')
    assert validate_comparison(p,e,'Acme') is None
    p,e=comparison('Acme projected revenue from 10 crore in FY2024 to 25 crore in FY2025.')
    assert validate_comparison(p,e,'Acme') is None
    p,e=comparison();assert validate_comparison(p,e,'Other') is None


def test_no_traction_does_not_call_model_or_claim_no_growth():
    model=Mock();profile=CompanyProfile(tenant_id='one',name='Acme',website='https://acme.example')
    report=analyze_growth(profile,model)
    assert report['status']=='no_comparable_metrics' and not report['comparisons']
    assert 'does not establish' in report['explanation'];model.generate.assert_not_called()


def test_model_selects_literal_blocks_not_paraphrased_facts():
    profile=CompanyProfile(tenant_id='one',name='Acme',website='https://acme.example')
    page=Page(url=profile.website,title='Acme',text='Acme handles physical delivery and supplier payments for hardware teams.',links=[])
    class Model:
        def generate(self,instruction,payload,schema):
            data=json.loads(payload);assert data['PAGE_BLOCKS']['b1']==page.text
            return schema.model_validate({'passages':[{'field':'business_model','block_id':'b1'}]})
    facts=extract_business_evidence(profile,page,Model())
    assert facts[0].quote==facts[0].value==page.text
    assert facts[0].source_url==page.url


def test_research_persists_real_passages_and_reuses_completed_basis(tmp_path):
    profile=CompanyProfile(tenant_id='one',name='Acme',website='https://acme.example',evidence=[CompanyEvidence(field='offering',value='hardware deliveries',quote='hardware deliveries',source_url='https://acme.example')])
    page=Page(url=profile.website,title='Acme',text='Acme handles physical delivery and supplier payments for hardware teams.',links=[])
    class Model:
        def generate(self,instruction,payload,schema):
            return schema.model_validate({'passages':[{'field':'business_model','block_id':'b1'}]})
    fetcher=Mock();fetcher.fetch.return_value=page
    with Store(tmp_path/'db') as store:
        lead=SourcedLead(tenant_id='one',company_name='Acme',company_id=profile.id,company_profile=profile);store.save_company(profile);store.save_lead(lead)
        updated=research_company(store,lead,Model(),fetcher)
        assert len(updated.company_profile.evidence)==2
        w=store.get_workspace('one',lead_id=lead.id);assert w.research['new_facts']==1
        research_company(store,updated,Model(),fetcher)
        assert fetcher.fetch.call_count==1
        assert store.list_workspaces('two')==[]


def test_specific_output_failures_are_rejected_before_saving():
    from agents.business_analysis import analysis_schema, validate_business_answers
    from tests.analysis_fixtures import analytical_fixture
    output=analytical_fixture(analysis_schema('incubation',{'C1'}),'C1')
    output.route_to_buyer='Contact Acme support to book a call'
    with pytest.raises(ValueError,match='reversed'): validate_business_answers(output,'incubation','Acme')
    output.route_to_buyer='Find prospective operations buyers through industry associations'
    output.offer_sentence='Start a free trial with no strings attached'
    with pytest.raises(ValueError,match='PAY'): validate_business_answers(output,'incubation','Acme')
    with pytest.raises(ValueError):
        analysis_schema('incubation',{'C1'}).model_validate({**output.model_dump(),'primary_metric':'invented_metric'})


def test_internal_brief_export_is_scoped_and_blocks_stale_analysis(tmp_path):
    from fastapi.testclient import TestClient
    from api.main import app
    import api.deps as deps
    from tests.test_operating_workflow import company, DraftModel
    from agents.operating_workflow import prepare_operating_drafts
    path=tmp_path/'export.db'
    with Store(path) as s:
        lead=company(s);w=prepare_operating_drafts(s,lead,DraftModel())
    def database():
        with Store(path) as s: yield s
    original=app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_store]=database
    app.dependency_overrides[deps.get_tenant_id]=lambda:'one'
    try:
        client=TestClient(app);url=f'/api/operations/workspaces/{w.id}/internal-brief'
        r=client.get(url);assert r.status_code==200
        assert 'not approved for investor release' in r.text
        assert 'source' in r.text.lower() and 'https://hotel.example/' in r.text
        app.dependency_overrides[deps.get_tenant_id]=lambda:'two';assert client.get(url).status_code==404
        app.dependency_overrides[deps.get_tenant_id]=lambda:'one'
        with Store(path) as s:
            changed=s.get_lead('one',lead.id);changed.company_profile.evidence.append(CompanyEvidence(field='traction',value='New claim',quote='New claim',source_url=changed.company_profile.website));s.save_lead(changed)
        assert client.get(url).status_code==409
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(original)


@pytest.mark.parametrize('identity_linked',[True,False])
def test_company_profile_research_requires_name_and_official_website_link(tmp_path,identity_linked):
    profile=CompanyProfile(tenant_id='one',name='Acme',website='https://acme.example',evidence=[
        CompanyEvidence(field='offering',value='hardware delivery',quote='hardware delivery',source_url='https://acme.example'),
        CompanyEvidence(field='directory_profile',value='https://directory.example/acme',quote='Acme profile',source_url='https://directory.example/')])
    page=Page(url='https://directory.example/acme',title='Acme',text='Acme founder previously built logistics software and requests introductions to hardware procurement teams.',links=[{'url':profile.website,'label':'Website'}] if identity_linked else [])
    class Model:
        def generate(self,instruction,payload,schema):
            return schema.model_validate({'passages':[{'field':'founder_ask','block_id':'b1'}]})
    fetcher=Mock();fetcher.fetch.return_value=page
    with Store(tmp_path/'db') as store:
        lead=SourcedLead(tenant_id='one',company_name='Acme',company_id=profile.id,company_profile=profile);store.save_company(profile);store.save_lead(lead)
        updated=research_company(store,lead,Model(),fetcher,page_limit=1)
        assert fetcher.fetch.call_args.args[0]=='https://directory.example/acme'
        assert any(e.field=='founder_ask' for e in updated.company_profile.evidence)==identity_linked


def test_product_copy_is_not_founder_biography_or_request():
    from agents.operating_research import evidence_field
    text='What takes a team four days of email happens here in minutes. Then it negotiates.'
    assert evidence_field('team',text)=='product'
    assert evidence_field('founder_ask',text)=='product'
    assert evidence_field('founder_ask','Founder previously built logistics software.')=='team'
    assert evidence_field('founder_ask','The founder requests introductions to hardware procurement teams.')=='founder_ask'


def test_company_research_follows_www_canonical_commercial_links(tmp_path):
 profile=CompanyProfile(tenant_id='one',name='Acme',website='https://acme.example',evidence=[CompanyEvidence(field='offering',value='hardware deliveries',quote='hardware deliveries',source_url='https://acme.example')])
 pages=[Page(url='https://www.acme.example/',title='Acme',text='Acme handles physical delivery and supplier payments for hardware teams.',links=[{'url':'https://www.acme.example/our-company','label':'Our company'}]),Page(url='https://www.acme.example/our-company',title='Acme company',text='The company was founded to supply hardware teams with replacement parts.',links=[])]
 class Model:
  def generate(self,instruction,payload,schema):return schema.model_validate({'passages':[{'field':'business_model','block_id':'b1'}]})
 fetcher=Mock();fetcher.fetch.side_effect=pages
 with Store(tmp_path/'db') as store:
  lead=SourcedLead(tenant_id='one',company_name='Acme',company_id=profile.id,company_profile=profile);store.save_company(profile);store.save_lead(lead)
  result=research_company(store,lead,Model(),fetcher,page_limit=2)
  assert fetcher.fetch.call_count==2
  assert any(e.source_url.endswith('/our-company') for e in result.company_profile.evidence)


def test_ai_research_plan_selects_observed_commercial_page_not_company_category():
 from agents.operating_research import select_research_links
 profile=CompanyProfile(tenant_id='one',name='Example Business',website='https://example.test')
 links=[{'url':'https://example.test/careers','label':'Jobs'},{'url':'https://example.test/services','label':'Customer services'}]
 class Model:
  def generate(self,instruction,payload,schema):
   data=json.loads(payload)
   assert data['links']['L2']['url']==links[1]['url']
   return schema.model_validate({'choices':[{'link_id':'L2','reason':'Determine who buys the service and how it is delivered.'}]})
 result=select_research_links(profile,links,Model())
 assert [l['url'] for l in result]==[links[1]['url']]
 assert 'research_question' in result[0]
