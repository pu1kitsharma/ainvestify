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
        if task.endswith('discovery_plan') and 'topic_query' in schema.model_fields:
            queries=answer.pop('queries')
            answer.update(topic_query=queries[0],geography_adjective=None)
        if task.endswith('discovery_assess') and 'product_support' in schema.model_fields:
            answer.update(product_support='direct_service_evidence',product_attribution='same_company',product_evidence_ids=['E2'],geography_support='unrestricted',geography_evidence_ids=[])
        if task.endswith('discovery_extract') and json.loads(evidence).get('SOURCE_SPAN_CONTRACT'):
            for candidate in answer['companies']:
                candidate['facts']=[{'field':f['field'],'source_span_id':next(
                    sid for spans in json.loads(evidence)['PAGE_BLOCKS'].values() for sid,text in spans.items()
                    if f['value'] in text)} for f in candidate['facts']]
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
                data['topic_query']='operating businesses worldwide portfolio 2024'
                self.last_response_text=json.dumps(data)
                return schema.model_validate(data)
            return result
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Companies worldwide',model='test-model')
        search=Search()
        result=source_companies(store,run,model=BadYear(),fetcher=Fetch(),search_provider=search,max_companies=1)
        assert result.status=='completed'
        assert '2024' in result.model_attempts[0]['raw_response']
        assert search.queries==[result.model_attempts[1]['answer']['topic_query']]
        assert search.queries==['operating businesses worldwide portfolio']


def test_automatic_preparation_without_verified_actor_never_runs_legacy_writer(tmp_path,monkeypatch):
    from api.routers import leads,operations
    from api.models import WebSourceRequest
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
    calls=[]
    def forbidden_writer(*args,**kwargs):
        calls.append(True)
        raise AssertionError('Legacy writer must not run without a verified actor')
    monkeypatch.setattr(leads,'source_companies',discover)
    monkeypatch.setattr(operations,'make_preparation_model',forbidden_writer)
    assert leads._web_slot.acquire(blocking=False)
    leads._run_web_job(path,run,WebSourceRequest(thesis=run.thesis,prepare_workflow=True))
    with Store(path) as store:
        assert store.get_workspace('one',lead_id=lead.id) is None
        assert calls==[]
        saved=store.get_web_run('one',run.id)
        assert 'automatic_preparation_lead_id' not in saved.generation_config
        assert any('PermissionError' in warning for warning in saved.warnings)


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


def test_failed_observed_source_recovers_to_another_observed_url(tmp_path):
    from agents.discovery.web_sources import SourceError
    class Choices(Model):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            if task.endswith('discovery_sources'):
                self.calls.append(task)
                payload=json.loads(evidence)
                url='https://dead.example/' if 'previous_source_outcomes' not in payload else 'https://hotel.example/'
                if url.endswith('hotel.example/'):
                    assert payload['previous_source_outcomes'][0]['status']=='failed'
                self.last_response_text=json.dumps({'urls':[url],'refined_queries':[]})
                return schema.model_validate(json.loads(self.last_response_text))
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    class TwoSources(Search):
        def search(self,query,limit):
            self.queries.append(query)
            return [SearchHit('https://dead.example/','Dead'),SearchHit('https://hotel.example/','Hotel Example')]
    class DeadThenReal(Fetch):
        def fetch(self,url):
            if 'dead.example' in url:
                self.urls.append(url)
                raise SourceError('failed','HTTP 404')
            return super().fetch(url)
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model')
        fetch=DeadThenReal()
        result=source_companies(store,run,model=Choices(),fetcher=fetch,search_provider=TwoSources(),max_companies=1)
        assert len(result.lead_ids)==1
        assert fetch.urls==['https://dead.example/','https://hotel.example/']
        assert result.sources[1].status=='failed'
        assert result.generation_config['candidate_outcomes'][0]['outcome']=='retained'


def test_empty_source_does_not_call_extractor(tmp_path):
    class Empty(Fetch):
        def fetch(self,url):return Page(url,'Empty','   ')
    with Store(tmp_path/'test.db') as store:
        model=Model()
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=model,fetcher=Empty())
        assert model.calls==['authored_discovery_plan']
        assert result.sources[0].matches==0
        assert not result.lead_ids


def test_oversized_first_block_does_not_hide_later_complete_evidence(tmp_path,monkeypatch):
    import agents.preparation.authored_discovery as module
    monkeypatch.setattr(module,'page_blocks',lambda page:{'oversized':'x'*12001,'b1':page.text})
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Model(),fetcher=Fetch(),max_companies=1)
        assert len(result.lead_ids)==1
        receipt=result.generation_config['page_contexts'][0]
        assert receipt['omitted_block_ids']==['oversized']
        assert receipt['selected_block_ids']==['b1']
        assert result.sources[0].status=='partial'


def test_source_block_schema_and_missing_fact_binding_fail_closed():
    import pytest
    from agents.preparation.authored_discovery import extraction_schema
    schema=extraction_schema({'b1':'Hotel Example operates hotels'})
    answer={'companies':[{'name':'Hotel Example','name_block_id':'not_seen','entity_type':'company','website':None,
        'facts':[{'field':'offering','value':'operates hotels','source_block_id':'b1'}]}],'follow_links':[]}
    with pytest.raises(ValueError):schema.model_validate(answer)
    answer['companies'][0]['name_block_id']='b1'
    answer['companies'][0]['facts'][0]['source_block_id']='not_seen'
    with pytest.raises(ValueError):schema.model_validate(answer)


def test_model_pass_is_preserved_with_its_exact_response_and_reason(tmp_path):
    class Passing(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task.endswith('discovery_assess'):
                answer=result.model_dump();answer['recommendation']='pass'
                answer['rationale']='The source identifies hotel operations, which contradicts the requested medical service.'
                self.last_response_text=json.dumps(answer)
                return schema.model_validate(answer)
            return result
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Medical services',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Passing(),fetcher=Fetch())
        assert not result.lead_ids
        outcome=result.generation_config['candidate_outcomes'][0]
        assert outcome['reason']=='model_pass'
        assert outcome['assessment']==result.model_attempts[-1]['answer']
        assert result.generation_config['empty_result_reasons']=={'model_pass':1}


def test_one_candidate_binding_failure_does_not_skip_next_candidate(tmp_path,monkeypatch):
    import agents.preparation.authored_discovery as module
    original=module.accepted_candidate
    def bind(candidate,*args,**kwargs):
        if candidate.name=='Bad Company':raise ValueError('Synthetic identity conflict')
        return original(candidate,*args,**kwargs)
    monkeypatch.setattr(module,'accepted_candidate',bind)
    class Two(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task.endswith('discovery_extract'):
                answer=result.model_dump();bad={**answer['companies'][0],'name':'Bad Company'}
                answer['companies'].insert(0,bad)
                self.last_response_text=json.dumps(answer)
                return schema.model_validate(answer)
            return result
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        class Both(Fetch):
            def fetch(self,url):return Page(url,'Hotel Example','Bad Company is listed. Hotel Example operates hotels')
        result=source_companies(store,run,model=Two(),fetcher=Both(),max_companies=1)
        assert len(result.lead_ids)==1
        outcomes=result.generation_config['candidate_outcomes']
        assert outcomes[0]['reason']=='candidate_validation: Synthetic identity conflict'
        assert outcomes[1]['outcome']=='retained'


def test_recovery_refinement_is_model_authored_and_failure_receipts_survive(tmp_path):
    from agents.discovery.web_sources import SourceError
    class Refine(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            payload=json.loads(evidence)
            if task.endswith('discovery_sources'):
                self.calls.append(task)
                if 'previous_source_outcomes' in payload:
                    answer={'urls':[],'refined_queries':['hotel operators']}
                elif 'hotel operators' in payload['previous_queries']:
                    answer={'urls':['https://hotel.example/'],'refined_queries':[]}
                else:answer={'urls':['https://dead.example/'],'refined_queries':[]}
                self.last_response_text=json.dumps(answer)
                return schema.model_validate(answer)
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    class Adaptive(Search):
        def search(self,query,limit):
            self.queries.append(query)
            return [SearchHit('https://hotel.example/' if query=='hotel operators' else 'https://dead.example/','Source')]
    class Dead(Fetch):
        def fetch(self,url):
            if 'dead.example' in url:raise SourceError('failed','HTTP 404')
            return super().fetch(url)
    with Store(tmp_path/'test.db') as store:
        model=Refine();search=Adaptive()
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model')
        result=source_companies(store,run,model=model,fetcher=Dead(),search_provider=search,max_companies=1)
        assert len(result.lead_ids)==1
        assert search.queries==['operating businesses worldwide portfolio','hotel operators']
        assert any(s.detail=='HTTP 404' for s in result.sources)
        assert len(model.calls)==6
        assert result.generation_config['budget']['max_seconds']==120
        assert result.generation_config['budget']['max_calls']==9


def test_api_preference_avoids_blocked_html_when_api_has_diverse_results(monkeypatch):
    import agents.discovery.web_discovery as module
    calls=[]
    class API(Search):
        name='api'
        def search(self,query,limit):
            calls.append('api')
            return [SearchHit(f'https://source{i}.example/','Company source') for i in range(6)]
    class HTML(Search):
        name='html'
        def search(self,query,limit):raise AssertionError('Adequate API results must not incur HTML challenge latency')
    monkeypatch.setattr(module,'MwmblSearch',API)
    monkeypatch.setattr(module,'DuckDuckGoSearch',HTML)
    run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model')
    hits=module.SearchSession(prefer_api=True).search_queries(['hotels'],run,lambda:True)
    assert len(hits)==6 and calls==['api']


def test_html_paragraph_blocks_keep_sentence_and_attribution_boundaries():
    from agents.preparation.authored_discovery import source_blocks
    first='Acme Example provides payments. '*30
    second='Beta Example provides invoice financing.'
    page=Page('https://example.org/','Companies',first+' '+second,content_blocks=[first,second,'omitted unretained text'])
    blocks=source_blocks(page)
    assert blocks=={'b1':first.strip(),'b2':second}
    assert len(blocks['b1'])>600
    assert 'omitted unretained text' not in blocks.values()


def test_observed_span_offsets_hashes_and_decoder_ids_are_exact():
    import hashlib,pytest
    from agents.preparation.authored_discovery import source_spans,extraction_schema
    block='Acme Example provides caf? payments in ?. '+('A complete source sentence with words and attribution '*12)+'. End.'
    spans,index,coverage=source_spans({'b1':block})
    assert len(spans)>=2
    assert coverage['omitted_units'][0]['reason']=='overlong_complete_unit'
    for sid,span in spans.items():
        assert block[span['start']:span['end']]==span['text']==index['b1'][sid]
        assert block.encode()[span['byte_start']:span['byte_end']].decode()==span['text']
        assert span['offset_unit']=='unicode_codepoints'
        assert span['text_sha256']==hashlib.sha256(span['text'].encode()).hexdigest()
        assert span['block_sha256']==hashlib.sha256(block.encode()).hexdigest()
        assert len(span['text'])<=500
    schema=extraction_schema({'b1':block},spans=spans)
    candidate={'name':'Acme Example','name_block_id':'b1','entity_type':'company','website':None,
        'facts':[{'field':'offering','source_span_id':'q1_1'}]}
    schema.model_validate({'companies':[candidate],'follow_links':[]})
    candidate['facts'][0]['source_span_id']='invented'
    with pytest.raises(ValueError):schema.model_validate({'companies':[candidate],'follow_links':[]})
    candidate['facts'][0]={'field':'offering','source_span_id':'q1_1','value':'rewritten claim'}
    with pytest.raises(ValueError):schema.model_validate({'companies':[candidate],'follow_links':[]})


def test_selected_source_span_projects_verbatim_and_retains_authorship(tmp_path):
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Model(),fetcher=Fetch(),max_companies=1)
        profile=result.company_profiles[0]
        offering=next(e for e in profile.evidence if e.field=='offering')
        assert offering.value=='Hotel Example operates hotels'
        extraction=next(a for a in result.model_attempts if a['task'].endswith('extract'))
        assert extraction['answer']['companies'][0]['facts']==[{'field':'offering','source_span_id':'q1_1'}]
        assert extraction['input']['PAGE_BLOCKS']['b1']['q1_1']==offering.value
        assert profile.provenance['span_bindings'][0]['span_id']=='q1_1'
        assert profile.provenance['release_status']=='preliminary_discovery'
        assert profile.provenance['current_operating_status']=='not_verified'


def test_find_more_preserves_trusted_continuation_and_rejects_previous_name_before_assessment(tmp_path):
    with Store(tmp_path/'test.db') as store:
        model=Model()
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'],
            generation_config={'continuation_of':'source_run_prior','exclude_names':['Hotel Example']})
        result=source_companies(store,run,model=model,fetcher=Fetch(),max_companies=4)
        assert result.generation_config['continuation_of']=='source_run_prior'
        assert result.generation_config['exclude_names']==['Hotel Example']
        assert result.generation_config['requested_companies']==4
        assert result.generation_config['candidate_outcomes'][0]['reason']=='previous_batch_company'
        assert model.calls==['authored_discovery_plan','authored_discovery_extract']
        assert not result.lead_ids


def test_literal_ownership_without_offering_does_not_become_a_credible_company(tmp_path):
    class Ownership(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task.endswith('discovery_extract'):
                answer=result.model_dump();answer['companies'][0]['facts'][0]['field']='business_model'
                self.last_response_text=json.dumps(answer)
                return schema.model_validate(answer)
            return result
    with Store(tmp_path/'test.db') as store:
        model=Ownership()
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=model,fetcher=Fetch())
        assert not result.lead_ids
        assert result.generation_config['candidate_outcomes'][0]['reason']=='identity_or_literal_offering_not_bound'
        assert model.calls==['authored_discovery_plan','authored_discovery_extract']


def test_geography_first_query_requires_model_correction_without_rewriting():
    import pytest
    from agents.preparation.authored_discovery import Plan,validate_plan
    plan=Plan.model_validate({'interpretation':'Find fintech company research candidates in India.',
        'criteria':[],'coverage_aim':'A varied set of fintech products.',
        'queries':['india fintech companies','Indian fintech']})
    with pytest.raises(ValueError,match='sector/topic alone'):
        validate_plan(plan,'fintrch',first_query_geography='india')
    assert plan.queries==['india fintech companies','Indian fintech']
    corrected=plan.model_copy(update={'queries':['fintech','Indian fintech']})
    validate_plan(corrected,'fintrch',first_query_geography='india')


def test_typed_topic_and_regional_queries_project_verbatim_without_mutating_response():
    from agents.preparation.authored_discovery import TypedQueryPlan,project_query_plan,validate_plan
    raw={'interpretation':'Find preliminary financial technology candidates in India.',
        'criteria':[],'coverage_aim':'Include varied fintech product offerings.',
        'topic_query':'fintech','geography_adjective':'Indian'}
    response=TypedQueryPlan.model_validate(raw)
    plan=project_query_plan(response)
    assert response.model_dump()==raw
    assert plan.queries==['fintech','Indian fintech']
    validate_plan(plan,'fintrch',first_query_geography='india')
    one=response.model_copy(update={'geography_adjective':None})
    assert project_query_plan(one).queries==['fintech']


def test_recorded_typed_planner_response_supports_exact_projected_searches(tmp_path):
    with Store(tmp_path/'test.db') as store:
        search=Search()
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model')
        result=source_companies(store,run,model=Model(),fetcher=Fetch(),search_provider=search,max_companies=1)
        raw=result.model_attempts[0]['answer']
        assert 'queries' not in raw
        assert search.queries==[raw['topic_query']]
        projection=result.research_plan['query_projection']
        assert projection['contract']=='topic-geography-args-v2'
        assert projection['topic_query']==raw['topic_query']
        assert projection['rendered_queries']==search.queries
        assert projection['response_id']==result.model_attempts[0]['id']
        assert result.generation_config['planner_contract']=='topic-geography-args-v2'



def test_structured_query_projection_uses_only_recorded_args_and_never_ignores_old_freeform_query():
    import pytest
    from agents.preparation.authored_discovery import TypedQueryPlan,project_query_plan,query_projection
    from agents.inference.model_authorship import digest
    data={'interpretation':'Find fintech research candidates located in India.',
        'criteria':[],'coverage_aim':'A range of product types.',
        'topic_query':'fintech','geography_adjective':'Indian'}
    response=TypedQueryPlan.model_validate(data)
    plan=project_query_plan(response,geography='india')
    assert plan.queries==['fintech','Indian fintech']
    projection=query_projection(response,'response_1',plan.queries)
    assert projection['queries_digest']==digest(plan.queries)
    with pytest.raises(ValueError,match='recorded ordered'):
        query_projection(response,'response_1',['fintech','Indian fintech companies'])
    assert all(' '.join(part['value'] for part in parts)==query for parts,query in zip(projection['ordered_parts'],plan.queries))
    assert not any('companies' in query or 'directory' in query or 'list' in query for query in plan.queries)
    with pytest.raises(ValueError):TypedQueryPlan.model_validate({**data,'regional_query':'Indian fintech companies list'})
    with pytest.raises(ValueError,match='padding'):
        project_query_plan(response.model_copy(update={'topic_query':'fintech companies'}),geography='india')
    with pytest.raises(ValueError,match='geography_adjective'):
        project_query_plan(response.model_copy(update={'geography_adjective':None}),geography='india')


def test_model_cannot_admit_name_or_ipo_as_service_merely_by_labelling_offering(tmp_path):
    class MissingProduct(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task.endswith('discovery_assess'):
                answer=result.model_dump();answer.update(product_support='not_established',product_attribution='unclear',product_evidence_ids=[])
                self.last_response_text=json.dumps(answer)
                return schema.model_validate(answer)
            return result
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=MissingProduct(),fetcher=Fetch())
        assert not result.lead_ids
        outcome=result.generation_config['candidate_outcomes'][0]
        assert outcome['reason']=='product_or_same_company_support_unresolved'
        assert outcome['assessment']['recommendation']=='investigate'
        assert outcome['assessment']==result.model_attempts[-1]['answer']


def test_unknown_requested_geography_is_retained_unresolved_not_published_or_rewritten_pass(tmp_path):
    class Regional(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task.endswith('discovery_plan'):
                answer=result.model_dump();answer.update(geography_adjective='Indian')
                self.last_response_text=json.dumps(answer)
                return schema.model_validate(answer)
            return result
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',geography='india',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Regional(),fetcher=Fetch())
        assert not result.lead_ids
        outcome=result.generation_config['candidate_outcomes'][0]
        assert outcome['reason']=='requested_geography_unresolved_or_contradicted'
        assert outcome['assessment']['recommendation']=='investigate'
        assert result.model_attempts[-1]['answer']==outcome['assessment']


def test_assessment_sees_asof_source_and_deduplicated_complete_quotes(tmp_path):
    from datetime import date
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Model(),fetcher=Fetch(),max_companies=1)
        payload=result.model_attempts[-1]['input']
        assert date.fromisoformat(payload['as_of_date'])
        assert payload['source_url']=='https://hotel.example/'
        assert payload['source_title']=='Hotel Example'
        assert payload['source_publication_date']=='not_established'
        assert len(payload['source_quotes'])==1
        assert all('quote' not in f and f['quote_id'] in payload['source_quotes'] for f in payload['facts'])


def test_invented_assessment_number_or_asof_year_cannot_become_reported_company_fact(tmp_path):
    class Invented(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if task.endswith('discovery_assess'):
                answer=result.model_dump();answer['rationale']='The company reported revenue of 999 million during 2026, which needs diligence.'
                self.last_response_text=json.dumps(answer)
                return schema.model_validate(answer)
            return result
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Invented(),fetcher=Fetch())
        assert not result.lead_ids
        assert result.generation_config['candidate_outcomes'][0]['reason']=='unsupported_numeric_or_date_assertion'
        assert '999' in result.model_attempts[-1]['raw_response']


def test_cancel_after_assessment_capture_before_publish_writes_no_company(tmp_path,monkeypatch):
    import agents.preparation.authored_discovery as module
    original=module.recorded_call
    with Store(tmp_path/'test.db') as store:
        def cancel_after_capture(*args,**kwargs):
            result=original(*args,**kwargs)
            if args[1].endswith('discovery_assess'):
                run=store.get_web_run('one',saved_id[0]);run.status='cancel_requested';store.save_web_run(run)
            return result
        monkeypatch.setattr(module,'recorded_call',cancel_after_capture)
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        saved_id=[run.id]
        result=source_companies(store,run,model=Model(),fetcher=Fetch())
        assert result.status=='cancelled'
        assert not store.list_leads('one') and not result.company_ids
        assert result.generation_config['candidate_outcomes'][0]['reason']=='cancelled_before_publish'
        assert not any(source.status=='failed' for source in result.sources)
        assert result.model_attempts[-1]['answer']['recommendation']=='investigate'


def test_budget_exhaustion_keeps_explicit_candidate_and_page_outcome(tmp_path):
    from agents.preparation.preparation_budget import PreparationBudgetExceeded
    class Exhausted(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task.endswith('discovery_assess'):raise PreparationBudgetExceeded('Synthetic deadline')
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Exhausted(),fetcher=Fetch())
        assert result.generation_config['candidate_outcomes'][0]['reason']=='budget_exhausted'
        assert result.sources[-1].status=='partial' and result.sources[-1].matches==0
        assert 'Synthetic deadline' in result.model_attempts[-1]['error']


def test_same_complete_offering_block_antecedent_can_differ_from_selected_headline_block(tmp_path):
    class Antecedent(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            if task.endswith('discovery_extract'):
                self.calls.append(task)
                answer={'companies':[{'name':'Hotel Example','name_block_id':'b1','entity_type':'company','website':None,
                    'facts':[{'field':'offering','source_span_id':'q2_1'}]}],'follow_links':[]}
                self.last_response_text=json.dumps(answer)
                return schema.model_validate(answer)
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
    class TwoBlocks(Fetch):
        def fetch(self,url):
            blocks=['Hotel Example','It operates hotels. Hotel Example serves business travellers.']
            return Page(url,'Hotel Example',' '.join(blocks),content_blocks=blocks)
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Antecedent(),fetcher=TwoBlocks(),max_companies=1)
        assert len(result.lead_ids)==1
        assert result.company_profiles[0].evidence[1].value=='It operates hotels.'
        assert 'Hotel Example' in result.company_profiles[0].evidence[1].quote



class PreliminaryModel(Model):
    def match_answer(self,payload):
        return {'companies':[{'name':'Hotel Example','name_block_id':'b1','entity_type':'company','website':'https://hotel.example/',
            'facts':[{'field':'offering','source_span_id':'q1_1'}],
            'proof_contract':'selected_fact_roles_v3','decision':'match','topic_fit':'supported','topic_evidence_ids':['OFFERING'],'product_support':'direct_service_evidence','product_attribution':'same_company',
            'product_evidence_ids':['OFFERING'],'geography_support':'unrestricted','geography_evidence_ids':[],
            'explicit_requirements':'supported','criteria_checks':[{'criterion_index':i,'support':'supported','same_company':True,'evidence_ids':['OFFERING']} for i,_ in enumerate(payload['CRITERIA'])],
            'known_closed_or_discontinued':False,'current_verification_required':False,
            'current_operating_status':'not_verified','financial_assessment':'not_performed','scope':'preliminary_research_only'}],
            'follow_links':[]}
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        if not task.endswith('discovery_match'):
            return super().generate_for_task(task,instruction,evidence,schema,**kwargs)
        self.calls.append(task)
        answer=self.match_answer(json.loads(evidence))
        self.last_response_text=json.dumps(answer)
        return schema.model_validate(answer)


def test_fresh_preliminary_match_contract_has_no_financial_assessment_and_creates_no_legacy_work(tmp_path):
    with Store(tmp_path/'test.db') as store:
        model=PreliminaryModel()
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model')
        result=source_companies(store,run,model=model,fetcher=Fetch(),search_provider=Search(),max_companies=1,preliminary_only=True)
        assert result.status=='completed',result.error
        assert model.calls==['authored_discovery_plan','authored_discovery_sources','authored_discovery_match']
        assert len(result.lead_ids)==1
        profile=result.company_profiles[0]
        assert profile.assessment is None
        assert profile.provenance['source_match']['decision']=='match'
        assert profile.provenance['financial_assessment']=='not_performed'
        assert profile.provenance['current_operating_status']=='not_verified'
        assert result.generation_config['mode']=='model_authored_preliminary_match_v3'
        assert 'rationale' not in result.model_attempts[-1]['answer']['companies'][0]
        workspace=store.get_workspace('one',lead_id=result.lead_ids[0])
        assert workspace.work_items==[] and workspace.preparation=={} and workspace.drafts==[]
        assert result.generation_config['budget']['max_seconds']==120
        assert result.generation_config['budget']['max_calls']==9


def test_preliminary_match_preserves_rich_canonical_profile_reviewed_lead_and_workspace(tmp_path):
    from schemas import CompanyProfile,CompanyEvidence,SelectionAssessment,SourcedLead,LeadStatus
    from workflow_schemas import OperatingWorkspace
    with Store(tmp_path/'test.db') as store:
        canonical=CompanyProfile(tenant_id='one',name='Hotel Example',website='https://hotel.example/',
            evidence=[CompanyEvidence(field='offering',value='Rich prior reviewed evidence',quote='Rich prior reviewed evidence',source_url='https://hotel.example/')],
            assessment=SelectionAssessment(model='prior-model',rationale='Prior financial and business assessment must be preserved.'))
        store.save_company(canonical)
        lead=SourcedLead(tenant_id='one',company_name=canonical.name,company_id=canonical.id,company_profile=canonical,
            status=LeadStatus.PROMOTED_TO_DEAL,promoted_deal_id='preserved-deal',sector_tag='Reviewed sector')
        store.save_lead(lead)
        workspace=OperatingWorkspace(tenant_id='one',lead_id=lead.id,company_id=canonical.id,company_name=canonical.name,
            preparation={'reviewed_financials':{'revenue':100,'status':'reviewed'}},analyst_pack={'artifact':'preserved-artifact'},events=[{'action':'reviewed'}])
        store.save_workspace(workspace)
        before_company=store.get_company_by_website('one',canonical.website).model_dump_json()
        before_lead=store.get_lead('one',lead.id).model_dump_json()
        before_workspace=store.get_workspace('one',lead_id=lead.id).model_dump_json()
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=PreliminaryModel(),fetcher=Fetch(),max_companies=1,preliminary_only=True)
        assert len(result.lead_ids)==1 and result.company_profiles[0].assessment is None
        assert store.get_company_by_website('one',canonical.website).model_dump_json()==before_company
        assert store.get_lead('one',lead.id).model_dump_json()==before_lead
        assert store.get_workspace('one',lead_id=lead.id).model_dump_json()==before_workspace


def test_preliminary_explicit_criterion_unresolved_never_publishes_partial_proof(tmp_path):
    class Unresolved(PreliminaryModel):
        def match_answer(self,payload):
            answer=super().match_answer(payload)
            answer['companies'][0]['criteria_checks'][0].update(support='unresolved',evidence_ids=[])
            return answer
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Unresolved(),fetcher=Fetch(),preliminary_only=True)
        assert not result.lead_ids
        assert result.generation_config['candidate_outcomes'][0]['reason']=='explicit_criterion_unresolved_or_contradicted'


def test_preliminary_closed_company_or_current_verification_requirement_never_qualifies(tmp_path):
    for flag,reason in [('known_closed_or_discontinued','source_reports_closed_or_discontinued'),('current_verification_required','current_status_mandate_unresolved')]:
        class Excluded(PreliminaryModel):
            def match_answer(self,payload):
                answer=super().match_answer(payload);answer['companies'][0][flag]=True;return answer
        with Store(tmp_path/(flag+'.db')) as store:
            run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
            result=source_companies(store,run,model=Excluded(),fetcher=Fetch(),preliminary_only=True)
            assert not result.lead_ids
            assert result.generation_config['candidate_outcomes'][0]['reason']==reason


def test_preliminary_unsolicited_financial_prose_rejects_entire_new_response(tmp_path):
    class Financial(PreliminaryModel):
        def match_answer(self,payload):
            answer=super().match_answer(payload);answer['companies'][0]['rationale']='Invented 2023 financial opinion.';return answer
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=Financial(),fetcher=Fetch(),preliminary_only=True)
        assert not result.lead_ids and not result.company_profiles
        assert result.model_attempts[-1]['failure_kind']=='schema_validation'
        assert 'Invented 2023' in result.model_attempts[-1]['raw_response']


def test_preliminary_match_cannot_cite_title_as_product_evidence(tmp_path):
    class TitleProduct(PreliminaryModel):
        def match_answer(self,payload):
            answer=super().match_answer(payload);answer['companies'][0]['product_evidence_ids']=['TITLE'];return answer
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=TitleProduct(),fetcher=Fetch(),preliminary_only=True)
        assert not result.lead_ids
        assert result.model_attempts[-1]['failure_kind']=='schema_validation'


def test_preliminary_topic_mismatch_and_cross_company_criterion_do_not_publish(tmp_path):
    for change,reason in [('topic','requested_topic_unresolved_or_contradicted'),('criterion','explicit_criterion_company_scope_unresolved')]:
        class Wrong(PreliminaryModel):
            def match_answer(self,payload):
                answer=super().match_answer(payload)
                if change=='topic':answer['companies'][0]['topic_fit']='contradicted'
                else:answer['companies'][0]['criteria_checks'][0]['same_company']=False
                return answer
        with Store(tmp_path/(change+'.db')) as store:
            run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
            result=source_companies(store,run,model=Wrong(),fetcher=Fetch(),preliminary_only=True)
            assert not result.lead_ids
            assert result.generation_config['candidate_outcomes'][0]['reason']==reason


def test_preliminary_topic_cannot_be_borrowed_from_another_company_page_span():
    from types import SimpleNamespace
    from agents.preparation.authored_discovery import source_match_issue
    raw=PreliminaryModel().match_answer({'CRITERIA':[]})['companies'][0]
    raw['topic_evidence_ids']=['q2_1']
    raw['facts']=[SimpleNamespace(field='offering',source_span_id='q1_1')]
    candidate=SimpleNamespace(**raw)
    spans={'q1_1':{'block_id':'b1','text':'Hotel Example operates hotels.'},
           'q2_1':{'block_id':'b2','text':'Other Company provides fintech payments.'}}
    assert source_match_issue(candidate,spans,[],None,False)=='requested_topic_unresolved_or_contradicted'
    candidate.facts.append(SimpleNamespace(field='sector',source_span_id='q2_1'))
    candidate.topic_evidence_ids=['SECTOR']
    assert source_match_issue(candidate,spans,[],None,False,blocks={'b1':'Hotel Example operates hotels.','b2':'Other Company provides fintech payments.'})=='proof_company_scope_unresolved'


def test_preliminary_matcher_never_sees_selected_fact_without_complete_parent_scope(tmp_path):
    class MissingNegation(Fetch):
        def fetch(self,url):
            block='Hotel Example no longer operates hotels, '+('because conditions changed '*30)+'. Hotel Example operates hotels.'
            return Page(url,'Hotel Example',block,content_blocks=[block])
    with Store(tmp_path/'test.db') as store:
        model=PreliminaryModel()
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',seed_urls=['https://hotel.example/'])
        result=source_companies(store,run,model=model,fetcher=MissingNegation(),preliminary_only=True)
        assert not result.lead_ids
        assert model.calls==['authored_discovery_plan']
        coverage=result.generation_config['page_contexts'][0]['span_coverage']
        assert coverage['withheld_parent_blocks']==['b1']
        assert coverage['selectable_complete_parent_units']==0


def test_v2_proof_roles_expand_whole_groups_and_never_fall_back_from_missing_role():
    from types import SimpleNamespace
    from agents.preparation.authored_discovery import source_match_roles,expand_match_roles
    candidate=SimpleNamespace(facts=[SimpleNamespace(field='offering',source_span_id='q1_1'),
        SimpleNamespace(field='offering',source_span_id='q2_1'),SimpleNamespace(field='location',source_span_id='q3_1')])
    roles=source_match_roles(candidate,True)
    assert roles['OFFERING']=={'q1_1','q2_1'}
    assert roles['COMPANY_LOCATION']=={'q3_1','TITLE'}
    assert expand_match_roles(['COMPANY_LOCATION'],roles)=={'q3_1','TITLE'}
    assert expand_match_roles(['OFFERING','SECTOR'],roles) is None
    assert expand_match_roles(['q1_1'],roles) is None
    assert source_match_roles(candidate,False)['COMPANY_LOCATION']=={'q3_1'}
    no_location=SimpleNamespace(facts=[SimpleNamespace(field='offering',source_span_id='q1_1')])
    assert expand_match_roles(['COMPANY_LOCATION','TITLE'],source_match_roles(no_location,True)) is None


def test_v2_fresh_run_guard_does_not_retag_or_reuse_failed_old_assessment(tmp_path):
    import pytest
    with Store(tmp_path/'test.db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test-model',status='failed',error='Unsupported old financial year',
            model_attempts=[{'task':'authored_discovery_assess','raw_response':'old failed response','error':'old failure'}])
        store.save_web_run(run)
        before=store.get_web_run('one',run.id).model_dump_json()
        model=PreliminaryModel()
        with pytest.raises(ValueError,match='fresh run'):
            source_companies(store,run,model=model,fetcher=Fetch(),preliminary_only=True)
        assert model.calls==[]
        assert store.get_web_run('one',run.id).model_dump_json()==before


def test_v3_own_geography_union_is_entire_title_only_or_location_only_without_fallback():
    from types import SimpleNamespace
    from agents.preparation.authored_discovery import source_match_roles,expand_match_roles
    no_location=SimpleNamespace(facts=[SimpleNamespace(field='offering',source_span_id='q1_1')])
    roles=source_match_roles(no_location,True)
    assert roles['OWN_GEOGRAPHY']=={'TITLE'}
    assert expand_match_roles(['OWN_GEOGRAPHY'],roles)=={'TITLE'}
    assert expand_match_roles(['COMPANY_LOCATION'],roles) is None
    assert expand_match_roles(['OWN_GEOGRAPHY'],source_match_roles(no_location,False)) is None
    with_location=SimpleNamespace(facts=[SimpleNamespace(field='location',source_span_id='q2_1')])
    assert source_match_roles(with_location,True)['OWN_GEOGRAPHY']=={'q2_1','TITLE'}
    assert source_match_roles(with_location,False)['OWN_GEOGRAPHY']=={'q2_1'}


def test_v3_title_only_geography_needs_own_company_and_explicit_country_support():
    from types import SimpleNamespace
    from agents.preparation.authored_discovery import source_match_issue
    raw=PreliminaryModel().match_answer({'CRITERIA':[]})['companies'][0]
    raw.update(geography_support='requested_region_supported',geography_evidence_ids=['OWN_GEOGRAPHY'])
    raw['facts']=[SimpleNamespace(field='offering',source_span_id='q1_1')]
    candidate=SimpleNamespace(**raw)
    spans={'q1_1':{'block_id':'b1','text':'Hotel Example operates hotels.'}}
    blocks={'b1':'Hotel Example operates hotels.'}
    assert source_match_issue(candidate,spans,[],'India',True,blocks=blocks,publisher_title='Indian Hotel Example',geography_adjective='Indian') is None
    assert source_match_issue(candidate,spans,[],'India',False,blocks=blocks,publisher_title='Indian Other Company',geography_adjective='Indian')=='requested_geography_unresolved_or_contradicted'
    assert source_match_issue(candidate,spans,[],'India',True,blocks=blocks,publisher_title='German Hotel Example',geography_adjective='Indian')=='requested_geography_not_literally_supported'
    candidate.geography_support='contradicted'
    assert source_match_issue(candidate,spans,[],'India',True,blocks=blocks,publisher_title='Indian Hotel Example',geography_adjective='Indian')=='requested_geography_unresolved_or_contradicted'
    candidate.geography_support='unrestricted'
    assert source_match_issue(candidate,spans,[],None,False,blocks=blocks)=='requested_geography_unresolved_or_contradicted'
