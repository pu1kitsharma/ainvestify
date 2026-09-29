import json
import sqlite3

from agents.preparation.authored_discovery import source_companies
from agents.preparation.authored_discovery import Extraction
from agents.discovery.web_discovery import SearchHit
from agents.discovery.web_sources import Page
from schemas import WebSourcingRun
from scripts.reset_company_workspace import reset
from store import Store
from tests.analysis.test_operating_workflow import company


class Model:
    name='test-model'
    last_route={}
    def __init__(self, fail=False):
        self.calls=[]
        self.fail=fail
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        self.calls.append(task)
        if self.fail:
            raise ValueError('Planning failed')
        if task.endswith('discovery_plan'):
            answer={'interpretation':'Find operating companies across sectors and regions.',
                    'criteria':[{'dimension':'business','requirement':'Operating company','evidence_needed':'A source describing a company product and its customers.'}],
                    'queries':['operating businesses worldwide portfolio'],'coverage_aim':'Include a variety of sectors and regions in the overall results.'}
        elif task.endswith('discovery_sources'):
            answer={'urls':['https://hotel.example/'],'refined_queries':[]}
        elif task.endswith('discovery_extract'):
            answer=Extraction.model_validate({'companies':[{'name':'Hotel Example','name_block_id':'b1','entity_type':'company','website':'https://hotel.example/',
                  'facts':[{'field':'offering','value':'operates hotels','source_block_id':'b1'}]}],'follow_links':[]}).model_dump()
        else:
            answer={'recommendation':'investigate','rationale':'The website describes hotel operations. Customer demand remains unestablished.',
                    'strengths':['The source identifies the operating service.'],'concerns':[],
                    'missing_information':['Guest demand and pricing records are needed.'],
                    'incubation_actions':['Propose reviewing reservation fulfilment with the founders.'],'evidence_ids':['E2']}
        self.last_response_text=json.dumps(answer)
        return schema.model_validate(answer)


class Search:
    name='test-search'
    def __init__(self):self.queries=[]
    def search(self,query,limit):
        self.queries.append(query)
        return [SearchHit('https://hotel.example/','Hotel Example')]


class Fetch:
    def __init__(self):self.urls=[]
    def fetch(self,url):
        self.urls.append(url)
        return Page(url,'Hotel Example','Hotel Example operates hotels')


def test_discovery_uses_model_queries_sources_and_unmodified_assessment(tmp_path):
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Companies across sectors worldwide',model='test-model')
        model=Model();search=Search();fetch=Fetch()
        result=source_companies(store,run,model=model,fetcher=fetch,search_provider=search,max_companies=1)
        assert result.status=='completed', result.error
        assert search.queries==['operating businesses worldwide portfolio']
        assert fetch.urls==['https://hotel.example/']
        assert len(result.lead_ids)==1
        profile=store.get_lead('one',result.lead_ids[0]).company_profile
        response=result.model_attempts[-1]['answer']
        for key in ('rationale','recommendation','strengths','concerns','missing_information','incubation_actions'):
            assert getattr(profile.assessment,key)==response[key]
        assert profile.provenance['pipeline']=='model_authored_v1'
        w=store.get_workspace('one',lead_id=result.lead_ids[0])
        assert not w.work_items and not w.preparation and not w.drafts
        assert len(model.calls)==4


def test_planner_failure_does_not_search_canned_queries_or_publish_companies(tmp_path):
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Companies worldwide',model='test-model')
        search=Search();fetch=Fetch()
        result=source_companies(store,run,model=Model(fail=True),fetcher=fetch,search_provider=search)
        assert result.status=='failed'
        assert result.research_plan=={}
        assert search.queries==[] and fetch.urls==[]
        assert store.list_leads('one')==[]


def test_unrequested_year_is_rewritten_by_model_not_removed_by_code(tmp_path):
    class BadYear(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if len(self.calls)==1:
                data=result.model_dump()
                data['queries']=['operating businesses worldwide portfolio 2024']
                self.last_response_text=json.dumps(data)
                return schema.model_validate(data)
            return result
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Companies worldwide',model='test-model')
        search=Search()
        result=source_companies(store,run,model=BadYear(),fetcher=Fetch(),search_provider=search,max_companies=1)
        assert result.status=='completed'
        assert '2024' in result.model_attempts[0]['raw_response']
        assert search.queries==result.model_attempts[1]['answer']['queries']
        assert search.queries==['operating businesses worldwide portfolio']


def test_api_automatically_prepares_first_discovered_company_using_authored_writer(tmp_path,monkeypatch):
    from api.routers import leads,operations
    from api.models import WebSourceRequest
    from tests.preparation.test_authored_preparation import Model as Writer
    import agents.analysis.analyst_pack as pipeline
    path=tmp_path/'test.db'
    with Store(path) as store:
        lead=company(store)
        run=WebSourcingRun(tenant_id='one',thesis='Companies worldwide',model='test-model')
        store.save_web_run(run)
    def discover(store,run,**kwargs):
        run.lead_ids=[lead.id]
        run.status='completed'
        store.save_web_run(run)
        return run
    model=Writer()
    monkeypatch.setattr(leads,'source_companies',discover)
    monkeypatch.setattr(operations,'make_preparation_model',lambda *args,**kwargs:model)
    monkeypatch.setattr(pipeline,'collect_preparation_evidence',lambda store,lead,**kwargs:lead)
    assert leads._web_slot.acquire(blocking=False)
    leads._run_web_job(path,run,WebSourceRequest(thesis=run.thesis,prepare_workflow=True))
    with Store(path) as store:
        w=store.get_workspace('one',lead_id=lead.id)
        assert w.automation.status=='completed'
        assert w.analyst_pack['generation_config']['mode']=='model_authored_v1'
        assert w.analyst_pack['status']=='complete'
        assert model.calls==['research','work','founder','review']
        assert store.get_web_run('one',run.id).generation_config['automatic_preparation_lead_id']==lead.id


def test_reset_preserves_backup_and_other_tenants(tmp_path):
    path=tmp_path/'test.db'
    with Store(path) as store:
        first=company(store,'one');second=company(store,'two')
    manifest=reset(path,'one',tmp_path/'backup')
    assert manifest['before']['sourced_leads']==1
    assert all(n==0 for n in manifest['after'].values())
    with Store(path) as store:
        assert not store.get_lead('one',first.id)
        assert store.get_lead('two',second.id)
    with sqlite3.connect(manifest['backup']) as backup:
        assert backup.execute('SELECT count(*) FROM sourced_leads').fetchone()[0]==2


def test_short_sector_query_is_kept_verbatim_and_padding_requires_model_repair():
    import pytest
    from agents.preparation.authored_discovery import Plan, validate_plan
    data = {'interpretation': 'Find companies working in agricultural technology.',
            'criteria': [], 'coverage_aim': 'Companies across sectors worldwide.',
            'queries': ['agrotech', 'agritech companies']}
    plan = Plan.model_validate(data)
    validate_plan(plan, 'agrotech')
    assert plan.queries == data['queries']
    padded = plan.model_copy(update={'queries': ['agrotech operating companies global directory']})
    with pytest.raises(ValueError, match='short topic query'):
        validate_plan(padded, 'agrotech')
    assert padded.queries == ['agrotech operating companies global directory']


def test_provider_failure_does_not_generate_company_or_trigger_more_model_work(tmp_path):
    from agents.discovery.web_sources import SourceError
    class Offline(Search):
        def search(self, query, limit):
            self.queries.append(query)
            raise SourceError('failed', 'Timed out', retryable=True)
    with Store(tmp_path/'test.db') as store:
        model = Model(); search = Offline(); fetch = Fetch()
        run = WebSourcingRun(tenant_id='one', thesis='agrotech', model='test-model')
        result = source_companies(store, run, model=model, search_provider=search, fetcher=fetch)
        assert result.status == 'failed'
        assert result.error.startswith('Search services were unavailable.')
        assert model.calls == ['authored_discovery_plan']
        assert len(search.queries) == 2
        assert not fetch.urls and not store.list_leads('one')


def test_model_refines_irrelevant_search_results_with_snippets_then_reads_real_source(tmp_path):
    class Refining(Model):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            payload = json.loads(evidence)
            if task.endswith('discovery_sources') and len(self.calls) == 1:
                self.calls.append(task)
                assert payload['results'][0]['snippet'] == 'An unrelated financial services company.'
                self.last_response_text = json.dumps({'urls': [], 'refined_queries': ['hotel operators']})
                return schema.model_validate(json.loads(self.last_response_text))
            return super().generate_for_task(task, instruction, evidence, schema, **kwargs)
    class AdaptiveSearch(Search):
        def search(self, query, limit):
            self.queries.append(query)
            if query == 'hotel operators':
                return [SearchHit('https://hotel.example/', 'Hotel Example', 'Search-only claim: serves a billion guests.')]
            return [SearchHit('https://finance.example/', 'Financial news', 'An unrelated financial services company.')]
    with Store(tmp_path/'test.db') as store:
        model = Refining(); search = AdaptiveSearch(); fetch = Fetch()
        run = WebSourcingRun(tenant_id='one', thesis='Hotel companies', model='test-model')
        result = source_companies(store, run, model=model, search_provider=search, fetcher=fetch, max_companies=1)
        assert result.status == 'completed', result.error
        assert search.queries == ['operating businesses worldwide portfolio', 'hotel operators']
        assert fetch.urls == ['https://hotel.example/']
        assert result.model_attempts[1]['answer']['refined_queries'] == ['hotel operators']
        assert result.model_attempts[1]['input']['previous_queries'] == ['operating businesses worldwide portfolio']
        profile = store.get_lead('one', result.lead_ids[0]).company_profile
        assert all('billion' not in evidence.value for evidence in profile.evidence)
        assert len(model.calls) == 5


def test_search_refinement_is_bounded_and_does_not_crawl_irrelevant_sources(tmp_path):
    class Rejecting(Model):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            if task.endswith('discovery_sources'):
                self.calls.append(task)
                self.last_response_text = json.dumps({'urls': [], 'refined_queries': ['different company search']})
                return schema.model_validate(json.loads(self.last_response_text))
            return super().generate_for_task(task, instruction, evidence, schema, **kwargs)
    with Store(tmp_path/'test.db') as store:
        model = Rejecting(); search = Search(); fetch = Fetch()
        result = source_companies(store, WebSourcingRun(tenant_id='one', thesis='Hotels', model='test-model'),
                                  model=model, search_provider=search, fetcher=fetch)
        assert result.status == 'failed'
        assert len(model.calls) == 3 and len(search.queries) == 2
        assert not fetch.urls and not result.lead_ids
        assert 'no relevant company sources' in result.error
