from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from agents.analyst_pack import (SourceClaim, FactSelection, Request, Action, source_passages,
    bind_source_claims, section_facts, validate_saved_sections, current_review_hash, export_pack)
from tests.test_measurement_plan import contribution_plan

CASES=Path(__file__).resolve().parents[1]/'evals/investment_preparation/section-workflows'


def test_html_context_preserves_complete_qualification_and_footer_but_removes_navigation():
    from agents.web_sources import parse_page
    from agents.analyst_pack import preparation_contexts
    paragraph='Apex charges an annual fee collected monthly. '+('The relevant service is advisory. '*25)+'Brokerage remains separate; no brokerage markup applies to Apex.'
    page=parse_page('https://company.example/pricing', '<div class="header-nav"><a href="/plans">Plans</a><span>Log in</span></div><main><h1>Commercial terms</h1><p>'+paragraph+'</p></main><footer><div class="footer-menu">Resources Careers</div><p>Services are provided by Named Partner Limited, not the investment target.</p></footer>')
    groups,_,omitted=preparation_contexts(page)
    assert omitted==0 and paragraph in groups[0]
    assert 'Named Partner Limited, not the investment target.' in groups[0]
    assert 'Log in' not in page.text and 'Resources Careers' not in page.text
    assert any(link['url'].endswith('/plans') for link in page.links)


def test_oversized_unsplittable_source_is_omitted_without_a_false_complete_fragment():
    from agents.web_sources import Page
    from agents.analyst_pack import preparation_contexts
    text='Long qualification without a safe block boundary. '*100
    groups,_,omitted=preparation_contexts(Page('https://example.org/','Example',text))
    assert groups==[] and omitted==1


def test_legacy_page_without_content_blocks_preserves_source_and_qualifications(tmp_path):
    from agents.analyst_pack import collect_preparation_evidence
    from tests.test_operating_workflow import company
    from store import Store
    text='Hotel Example operates hotels. The room price excludes meals; partner charges remain separate.'
    class Fetcher:
        def fetch(self,url):
            return SimpleNamespace(url=url,title='Hotel Example',text=text,links=[],truncated=False)
    with Store(tmp_path/'db') as store:
        lead=company(store)
        original=[e.model_dump() for e in lead.company_profile.evidence]
        saved=collect_preparation_evidence(store,lead,Fetcher())
        assert [e.model_dump() for e in saved.company_profile.evidence[:len(original)]]==original
        assert saved.company_profile.evidence[-1].quote==text
        workspace=store.get_workspace('one',lead_id=lead.id)
        assert workspace.research['preparation_sources']['pages'][0]['status']=='ok'


def test_current_page_context_takes_precedence_without_deleting_original_evidence(tmp_path):
    from agents.analyst_pack import raw_sources,collect_preparation_evidence
    from agents.web_sources import parse_page
    from tests.test_operating_workflow import company
    from store import Store
    class Fetcher:
        def fetch(self,url):return parse_page(url,'<p>The company offers business hotel rooms at a nightly price.</p>')
    with Store(tmp_path/'db') as store:
        lead=company(store);before=[e.id for e in lead.company_profile.evidence]
        lead=collect_preparation_evidence(store,lead,Fetcher())
        assert set(before)<={e.id for e in lead.company_profile.evidence}
        assert all(s['origin']=='preparation_public_page' for s in raw_sources(lead))


def test_exports_cite_once_instead_of_repeating_sources_for_every_plan(tmp_path):
    from agents.analyst_pack import prepare_analyst_pack
    from tests.test_authored_preparation import Model
    from tests.test_operating_workflow import company
    from store import Store
    with Store(tmp_path/'db') as store:
        pack=prepare_analyst_pack(store,company(store),Model()).analyst_pack
        text=export_pack(pack,'readiness')
        quote=pack['record']['facts'][0]['quote']
        assert text.count(quote)==1
        assert text.count('<a id="source-s1"></a>')==1
        assert '[S1](#source-s1)' in text


def test_fresh_pricing_and_closing_terms_survive_a_large_homepage(tmp_path):
    from agents.analyst_pack import raw_sources
    from agents.shared_preparation import source_record
    from agents.operating_workflow import reconcile_workspace
    from schemas import CompanyEvidence
    from tests.test_operating_workflow import company
    from store import Store
    with Store(tmp_path/'db') as store:
        lead=company(store);lead.company_profile.evidence=[]
        for url,count,category in [('https://hotel.example/',6,'source_passage'),('https://hotel.example/pricing',4,'commercial_terms')]:
            for i in range(count):
                text=f'Complete section {i}. '+('Full content and qualifications. '*95)
                lead.company_profile.evidence.append(CompanyEvidence(field=category,value=text,quote=text,source_url=url,
                    origin='preparation_public_page',row_key='preparation_context_v3:'+str(i)))
        store.save_lead(lead)
        record=source_record(lead,reconcile_workspace(store,lead))
        facts=record['facts']
        assert facts[0]['source_url'].endswith('/pricing')
        assert facts[1]['source_url']=='https://hotel.example/'
        assert facts[2]['quote'].startswith('Complete section 3.') and facts[2]['source_url'].endswith('/pricing')
        assert record['coverage']=='partial'


def test_control_labels_are_removed_without_erasing_monthly_annual_price_controls():
    from agents.web_sources import parse_page
    page=parse_page('https://example.org/','<button><span>Open main menu</span></button><a href="/start">Get started</a><button>Monthly</button><button>Annual</button><p>Billing is monthly with an annual commitment.</p>')
    assert 'Open main menu' not in page.text and 'Get started' not in page.text
    assert 'Monthly Annual Billing is monthly with an annual commitment.'==page.text
    assert page.links[0]['label']=='Get started'


def test_observed_price_schedule_survives_link_cap_and_beats_fee_calculators(tmp_path):
    from agents.web_sources import parse_page
    from agents.analyst_pack import collect_preparation_evidence
    from tests.test_operating_workflow import company
    from store import Store
    body=''.join(f'<a href="/article/{i}">Article {i}</a>' for i in range(120))
    page=parse_page('https://hotel.example/','<nav><a href="/pricing">Pricing</a></nav><p>Room stays for business travelers.</p><a href="/tools/fees-calculator">Fee calculator</a>'+body)
    assert len(page.links)==100
    assert any(link['url']=='https://hotel.example/pricing' for link in page.links)
    class Fetcher:
        def __init__(self):self.urls=[]
        def fetch(self,url):
            self.urls.append(url)
            return page if url.endswith('/') else parse_page(url,'<p>Nightly rates are charged to guests; separate services cost extra.</p>')
    with Store(tmp_path/'db') as store:
        fetcher=Fetcher();collect_preparation_evidence(store,company(store),fetcher)
        assert fetcher.urls==['https://hotel.example/','https://hotel.example/pricing']


def test_retained_apex_fragment_cannot_drop_its_subject_or_qualifications():
    source=json.loads((CASES/'paasa-reference-input.json').read_text())[0]['evidence'][2]
    passage=source_passages([source])[0]
    lost_fragment='Its percentage charge is based on assets under management, stated annually and collected monthly.'
    old=SourceClaim(passage_id=passage['passage_id'],quote=lost_fragment,category='pricing',subject='target')
    fact=bind_source_claims(SimpleNamespace(facts=[old]),[passage])[0]
    assert fact['quote']==source['quote']
    assert fact['selected_quote']==lost_fragment
    assert 'Apex plan' in fact['quote'] and 'Brokerage fees apply separately.' in fact['quote']
    assert 'brokerage markups are not applied' in fact['quote']
    assert section_facts([fact],'research','economics')[0]['quote']==source['quote']
    assert 'quote' not in FactSelection.model_json_schema()['properties']


def test_passage_ids_are_stable_and_long_context_is_never_split():
    source=json.loads((CASES/'paasa-reference-input.json').read_text())[0]['evidence'][3]
    source['quote']='Relevant opening subject. '+'Context about service responsibilities. '*35+'Separate partner qualification.'
    passages=source_passages([source])
    assert len(passages)==1 and passages[0]['quote']==source['quote']
    other={**source,'id':'another-source','quote':'Another company statement.'}
    assert source_passages([other,source])[1]['passage_id']==passages[0]['passage_id']
    source['quote']+=' Revised terms.'
    assert source_passages([source])[0]['passage_id']!=passages[0]['passage_id']


def test_original_failed_requests_and_actions_are_rejected_without_inference():
    original=json.loads((CASES/'paasa_reference_test.json').read_text())['pack']
    for key,schema in [('diligence.request_a',Request),('readiness.action_a',Action)]:
        with pytest.raises(ValueError,match='analysis_plan'):schema.model_validate(original['sections'][key]['content'])
    pack=deepcopy(original)
    # Even an artificially current critic's pass cannot bypass the new contract.
    for section in pack['sections'].values():section['review_hash']=current_review_hash(pack)
    checked=validate_saved_sections(pack)
    assert checked['sections']['diligence.request_a']['status']=='needs_revision'
    assert checked['sections']['readiness.action_a']['status']=='needs_revision'
    text=export_pack(pack)
    assert 'fees collected are significantly below AUM' not in text
    assert 'Compare total brokerage pass-throughs' not in text
    assert original['sections']['diligence.request_a']['status']=='complete'


def test_prose_cannot_override_the_reviewed_method_or_decision():
    request=Request(question='Do room stays cover variable servicing costs?',analysis_plan=contribution_plan(),fact_ids=['f'])
    action=Action(analysis_plan=request.analysis_plan,fact_ids=['f'])
    pack={'company':'Example','record':{'facts':[{'id':'f','quote':'The company operates hotels.'}]},'sections':{
        'diligence.request_a':{'document':'diligence','title':'Request','status':'complete','content':request.model_dump()},
        'readiness.action_a':{'document':'readiness','title':'Action','status':'complete','dependency':'diligence.request_a','content':action.model_dump()}}}
    for s in pack['sections'].values():s['review_hash']=current_review_hash(pack)
    pack['sections']['readiness.action_a']['content']['decision']='Reject if fees are smaller than customer assets.'
    checked=validate_saved_sections(pack)
    assert checked['sections']['readiness.action_a']['status']=='needs_revision'
    assert 'Reject if fees' not in export_pack(pack)


def test_new_irrelevant_source_reuses_unchanged_work_and_source_selections(tmp_path):
    from tests.test_analyst_pack import Model
    from tests.test_operating_workflow import company
    from agents.analyst_pack import prepare_section_pack as prepare_analyst_pack
    from schemas import CompanyEvidence
    from store import Store
    class SelectOnlyNew(Model):
        def generate(self,instruction,evidence,schema):
            payload=json.loads(evidence)
            if 'passages' in payload:
                self.calls.append((instruction,payload))
                assert len(payload['passages'])==1
                assert payload['passages'][0]['text']=='An unrelated source footer to omit.'
                return schema(facts=[])
            return super().generate(instruction,evidence,schema)
    with Store(tmp_path/'db') as store:
        lead=company(store);original=prepare_analyst_pack(store,lead,Model())
        lead.company_profile.evidence.append(CompanyEvidence(field='source_passage',value='Footer',quote='An unrelated source footer to omit.',source_url='https://hotel.example/terms'))
        store.save_lead(lead)
        model=SelectOnlyNew();updated=prepare_analyst_pack(store,lead,model)
        assert updated.analyst_pack['status']=='complete'
        assert len(model.calls)==1
        assert updated.analyst_pack['sections']==original.analyst_pack['sections']
        assert updated.analyst_pack_history[-1]['sections']==original.analyst_pack['sections']


def test_budget_stop_after_changed_evidence_never_exposes_stale_sections(tmp_path):
    from tests.test_analyst_pack import Model
    from tests.test_operating_workflow import company
    from agents.analyst_pack import prepare_section_pack as prepare_analyst_pack
    from agents.preparation_budget import PreparationBudget
    from store import Store
    with Store(tmp_path/'db') as store:
        lead=company(store);original=prepare_analyst_pack(store,lead,Model())
        next(e for e in lead.company_profile.evidence if e.field=='offering').quote='The company now reports a changed hotel service.'
        store.save_lead(lead)
        updated=prepare_analyst_pack(store,lead,Model(),budget=PreparationBudget(10,max_calls=1))
        assert updated.analyst_pack['status']=='partial'
        assert updated.analyst_pack['sections']=={}
        assert updated.analyst_pack_history[-1]['sections']==original.analyst_pack['sections']
        assert 'Hotel Example operates hotels' not in str(updated.analyst_pack['record']['facts'])
