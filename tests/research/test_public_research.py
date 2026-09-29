import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from agents.research.public_research import PublicResearchModel, Navigation, observed_search, navigate, fresh_collection
from agents.preparation.preparation_budget import preparation_budget, PreparationBudget
from agents.discovery.web_sources import Page


def transcript():
    return [{'type':'assistant','message':{'content':[{'type':'tool_use','name':'WebSearch','input':{'query':'hotel businesses'}}]}},
        {'type':'user','tool_use_result':{'query':'hotel businesses','results':[
        {'content':[{'title':'Hotel Example','url':'https://hotel.example/'}]},
        'Generated summary says https://invented.example/ is official.']}}]


def test_only_structured_tool_links_establish_observed_destinations():
    links,queries=observed_search(transcript()+[{'type':'assistant','tool_use_result':{'query':'fake','results':[{'content':[{'url':'https://fake.example/'}]}]}}])
    assert links=={'https://hotel.example/':'Hotel Example'}
    assert queries==['hotel businesses']


def test_public_research_manifest_blocks_private_fields_and_changed_payloads(monkeypatch):
    model=PublicResearchModel(); start=Mock(); monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen',start)
    payload={'purpose':'company','public_request':'Hotel Example','geography':None,'as_of':'2026-09-25'}
    with pytest.raises(ValueError,match='Unexpected fields'):
        model.approve('public_navigation',{**payload,'private_notes':'secret'})
    model.approve('public_navigation',payload)
    with pytest.raises(ValueError,match='approved task'):
        model.generate_for_task('public_navigation','test',json.dumps({**payload,'public_request':'different'}),Navigation)
    start.assert_not_called()


def test_search_cli_has_only_search_tool_and_reserves_both_turns(monkeypatch):
    model=PublicResearchModel();model._authenticated=True
    payload={'purpose':'company','public_request':'Hotel Example','geography':None,'as_of':'2026-09-25'}
    model.approve('public_navigation',payload)
    answer={'interpretation':'Read public company evidence.','urls':['https://hotel.example/'],'official_website':'https://hotel.example/'}
    process=Mock();process.returncode=0;process.poll.return_value=0
    process.communicate.return_value=(json.dumps(transcript()+[{'type':'result','num_turns':2,'result':json.dumps(answer)}]),'')
    start=Mock(return_value=process);monkeypatch.setattr('agents.inference.subscription_model.subprocess.Popen',start)
    with preparation_budget(PreparationBudget(10,max_requests=3)) as budget:
        result=model.generate_for_task('public_navigation','test',json.dumps(payload),Navigation)
    command=start.call_args[0][0]
    assert command[command.index('--tools')+1]=='WebSearch'
    assert command[command.index('--max-turns')+1]=='2'
    assert '--safe-mode' in command and '--no-session-persistence' in command
    assert budget.requests==2 and result.urls==answer['urls']


def test_complete_source_claim_crossing_old_character_boundary_still_binds():
    from agents.research.public_research import research_blocks
    from agents.discovery.company_sourcing import accepted_candidate, Candidate
    text=('Earlier source sentence. '*23)+'Hotel Example operates hotels with on-site restaurants and conference rooms.'
    page=Page('https://hotel.example/','Hotel Example',text)
    blocks=research_blocks(page)
    claim='operates hotels with on-site restaurants and conference rooms'
    key=next(k for k,v in blocks.items() if claim in v)
    candidate=Candidate(name='Hotel Example',name_block_id=key,entity_type='company',website=page.url,
        facts=[{'field':'offering','value':claim,'source_block_id':key}])
    profile=accepted_candidate(candidate,page,context_blocks=blocks)
    assert profile.evidence[1].value==claim
    assert claim in profile.evidence[1].quote
    candidate.facts[0].value='operates fifty profitable hotels'
    assert len(accepted_candidate(candidate,page,context_blocks=blocks).evidence)==1


def test_navigation_rejects_url_existing_only_in_generated_summary():
    class Model:
        name='test';last_route={};search_transcript=transcript()
        def approve(self,*args):pass
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            self.last_response_text=json.dumps({'interpretation':'Read public company evidence.','urls':['https://invented.example/'],'official_website':None})
            return schema.model_validate_json(self.last_response_text)
    with pytest.raises(ValueError,match='absent from the recorded'):
        navigate('Hotels','discovery',[],lambda:None,model=Model())


def test_navigation_schema_repair_uses_original_search_without_another_web_call():
    from agents.research.public_research import recorded_navigation
    class Model:
        name='test';search_transcript=transcript()
        def __init__(self):self.tasks=[];self.last_route={'search_transcript':self.search_transcript}
        def approve(self,*args):pass
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            self.tasks.append(task)
            data={'interpretation':'x'*401 if task=='public_navigation' else 'Find the official hotel company sources.',
                  'urls':['https://hotel.example/'],'official_website':'https://hotel.example/'}
            if task=='public_navigation_correction':
                payload=json.loads(evidence)
                assert payload['observed_urls']==['https://hotel.example/']
            self.last_response_text=json.dumps(data)
            return schema.model_validate(data)
    model=Model();attempts=[]
    with preparation_budget(PreparationBudget(10)):
        choice,urls,_,_=navigate('Hotels','company',attempts,lambda:None,model=model)
    assert model.tasks==['public_navigation','public_navigation_correction']
    assert urls==choice.urls and attempts[0]['failure_kind']=='schema_validation'
    resumed=Model()
    with preparation_budget(PreparationBudget(10)):
        choice,_,_=recorded_navigation(resumed,'search',{},attempts,lambda:None,prior=attempts[0])
    assert resumed.tasks==['public_navigation_correction']
    assert choice.urls==urls


def test_evidence_cache_expires_and_rejects_future_or_missing_timestamps():
    now=datetime.now(timezone.utc)
    assert fresh_collection({'at':now.isoformat()})
    for value in ({},{'at':'invalid'},{'at':(now-timedelta(days=2)).isoformat()},{'at':(now+timedelta(days=1)).isoformat()}):
        assert not fresh_collection(value)


def test_multiple_companies_from_one_directory_are_independently_bound(tmp_path,monkeypatch):
    from agents.discovery.subscription_discovery import source_public_companies
    from schemas import WebSourcingRun
    from store import Store
    page=Page('https://directory.example/','Hotels','Hotel Alpha operates hotels. Hotel Beta operates resorts.')
    def navigation(*args,**kwargs):
        return Navigation(interpretation='Find companies running hotels and resorts.',urls=[page.url],official_website=None),[page.url],['hotel operators'],'search1'
    monkeypatch.setattr('agents.discovery.subscription_discovery.navigate',navigation)
    class Fetcher:
        def fetch(self,url):return page
    class Model:
        name='test';last_route={}
        def approve(self,*args):pass
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            companies=[]
            for name,offering in [('Hotel Alpha','operates hotels'),('Hotel Beta','operates resorts')]:
                companies.append({'name':name,'page_id':'P1','name_block_id':'b1','entity_type':'company','website':None,
                    'facts':[{'field':'offering','value':offering,'source_block_id':'b1'}],
                    'assessment':{'recommendation':'investigate','rationale':f'{name} reports that it {offering}. Guest demand needs investigation.',
                    'strengths':[],'concerns':['Demand has not been established.'],'missing_information':[],
                    'incubation_actions':[],'evidence_ids':['E2']}})
            self.last_response_text=json.dumps({'companies':companies,'coverage_limits':[]})
            return schema.model_validate_json(self.last_response_text)
    with Store(tmp_path/'db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test')
        result=source_public_companies(store,run,model=Model(),fetcher=Fetcher(),max_companies=2)
        assert len(result.lead_ids)==2,result.error
        assert result.status=='completed'
        for lead_id in result.lead_ids:
            profile=store.get_lead('one',lead_id).company_profile
            assert profile.assessment.evidence_ids==[profile.evidence[1].id]
            assert profile.assessment.rationale.startswith(profile.name)


def test_company_research_collects_status_and_product_sources_and_reuses_fresh_evidence(tmp_path,monkeypatch):
    from agents.research.public_research import collect_company_research
    from tests.analysis.test_operating_workflow import company
    from store import Store
    urls=['https://hotel.example/','https://owner.example/news/acquisition']
    calls=[]
    def navigation(*args,**kwargs):
        calls.append(args[0])
        return Navigation(interpretation='Check current ownership and hotel operations.',urls=urls,official_website=urls[0]),urls,['hotel ownership'],'response1'
    monkeypatch.setattr('agents.research.public_research.navigate',navigation)
    class Fetcher:
        def fetch(self,url):
            text='Hotel Example operates hotels serving business travellers.' if url==urls[0] else 'On September 1, Owner completed its acquisition of Hotel Example.'
            return Page(url,'Hotel Example',text,content_blocks=[text])
    with Store(tmp_path/'db') as store:
        lead=collect_company_research(store,company(store),fetcher=Fetcher())
        assert any('completed its acquisition' in e.quote for e in lead.company_profile.evidence)
        assert lead.company_profile.website==urls[0]
        collect_company_research(store,lead,fetcher=Fetcher())
        assert len(calls)==1
        w=store.get_workspace(lead.tenant_id,lead_id=lead.id)
        w.research['preparation_sources']['at']='2020-01-01T00:00:00+00:00'
        store.save_workspace(w,expected_revision=w.revision)
        collect_company_research(store,lead,fetcher=Fetcher())
        assert len(calls)==2


def test_one_directory_cannot_satisfy_company_research_gate(tmp_path,monkeypatch):
    from agents.research.public_research import collect_company_research
    from tests.analysis.test_operating_workflow import company
    from store import Store
    url='https://directory.example/'
    monkeypatch.setattr('agents.research.public_research.navigate',lambda *a,**k:(Navigation(interpretation='Research the current company.',urls=[url],official_website=None),[url],['hotels'],'response1'))
    class Fetcher:
        def fetch(self,url):
            text='Hotel Example operates hotels according to this directory.'
            return Page(url,'Directory',text,content_blocks=[text])
    with Store(tmp_path/'db') as store:
        lead=company(store)
        with pytest.raises(ValueError,match='official company page'):
            collect_company_research(store,lead,fetcher=Fetcher())
        saved=store.get_lead(lead.tenant_id,lead.id)
        assert any(e.source_url==url for e in saved.company_profile.evidence)
        assert store.get_workspace(lead.tenant_id,lead_id=lead.id).research['preparation_sources']['coverage_issue']


def test_deleted_search_pages_recover_from_model_selected_observed_homepage_links(tmp_path, monkeypatch):
    from agents.research.public_research import collect_company_research
    from agents.discovery.web_sources import SourceError
    from tests.analysis.test_operating_workflow import company
    from store import Store
    root, deleted, actual = 'https://hotel.example/', 'https://hotel.example/old-products/', 'https://hotel.example/operations.html'
    monkeypatch.setattr('agents.research.public_research.navigate', lambda *a, **k: (
        Navigation(interpretation='Research the current company.', urls=[root, deleted], official_website=root),
        [root, deleted], ['hotel operations'], 'search1'))
    class Researcher:
        name = 'fixture'; last_route = {}; search_transcript = []
        def approve(self, task, payload):
            assert task == 'public_source_recovery'
            assert set(payload) == {'company', 'observed_links', 'failed_urls'}
            assert payload['failed_urls'] == [deleted]
            assert payload['observed_links'] == [{'url': actual, 'label': 'Our operations', 'from_url': root}]
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            self.last_response_text = json.dumps({'urls': [actual]})
            return schema.model_validate_json(self.last_response_text)
    monkeypatch.setattr('agents.research.public_research.PublicResearchModel', Researcher)
    fetched = []
    class Fetcher:
        def fetch(self, url):
            fetched.append(url)
            if url == deleted: raise SourceError('failed', 'HTTP 404')
            text = 'Hotel Example operates hotels serving travellers.' if url == root else 'Hotel Example reports a new property management programme.'
            return Page(url, 'Hotel Example', text, content_blocks=[text],
                links=[{'url': actual, 'label': 'Our operations'}] if url == root else [])
    with Store(tmp_path/'db') as store:
        lead = collect_company_research(store, company(store), fetcher=Fetcher())
        collection = store.get_workspace(lead.tenant_id, lead_id=lead.id).research['preparation_sources']
        assert 'coverage_issue' not in collection
        assert collection['recovery_response_id'] == collection['attempts'][0]['id']
        assert collection['attempts'][0]['answer'] == {'urls': [actual]}
        assert sorted(fetched) == sorted([root, deleted, actual])
        assert any(e.source_url == actual for e in lead.company_profile.evidence)


def test_source_recovery_rejects_invented_paths_before_fetching():
    from agents.research.public_research import recover_source_pages
    page = Page('https://hotel.example/', 'Hotel Example', 'Hotel operations',
                links=[{'url': 'https://hotel.example/about.html', 'label': 'About us'}])
    class Researcher:
        name = 'fixture'; last_route = {}; search_transcript = []
        def approve(self, *args): pass
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            self.last_response_text = json.dumps({'urls': ['https://hotel.example/invented']})
            return schema.model_validate_json(self.last_response_text)
    fetcher = Mock()
    with pytest.raises(ValueError, match='absent from its observed links'):
        recover_source_pages('Hotel Example', [(page, None)], [page.url], Researcher(), [], lambda: None, fetcher=fetcher)
    fetcher.fetch.assert_not_called()


def test_source_repairs_are_model_authored_and_cannot_change_assessment():
    from agents.discovery.subscription_discovery import Shortlist, correct_sources
    data={'companies':[{'name':'Hotel Example (Group)','name_block_id':'b1','entity_type':'company','website':None,
        'page_id':'P1','facts':[{'field':'offering','value':'operates hotels','source_block_id':'b1'}],
        'assessment':{'recommendation':'investigate','rationale':'Hotel Example operates hotels serving travellers. Occupancy evidence is still missing.',
        'strengths':[],'concerns':[],'missing_information':[],'incubation_actions':[],'evidence_ids':['E2']}}],
        'coverage_limits':[]}
    pages=[{'page_id':'P1','PAGE_BLOCKS':{'b1':'Hotel Example operates hotels.'}}]
    class Model:
        name='test';last_route={}
        field='name'
        def approve(self,*args):pass
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            self.last_response_text=json.dumps({'patches':[{'candidate_index':0,'field':self.field,'value':'Hotel Example'}]})
            return schema.model_validate_json(self.last_response_text)
    attempts=[];model=Model()
    repaired,reference=correct_sources(Shortlist.model_validate(data),pages,model,attempts,lambda:None)
    assert repaired.companies[0].name==attempts[0]['answer']['patches'][0]['value']
    assert repaired.companies[0].assessment.model_dump()==data['companies'][0]['assessment']
    assert data['companies'][0]['name']=='Hotel Example (Group)'
    model.field='assessment.rationale'
    with pytest.raises(ValueError,match='unrequested field'):
        correct_sources(Shortlist.model_validate(data),pages,model,attempts,lambda:None)


def test_discovery_streams_more_than_five_and_reuses_identity_across_runs(tmp_path):
    from agents.discovery.subscription_discovery import source_public_companies
    from schemas import WebSourcingRun
    from store import Store
    page=Page('https://directory.example/','Hotel directory',' '.join(f'Hotel {i} operates resorts.' for i in range(12)))
    class Fetcher:
        def fetch(self,url):return page
    class Model:
        name='test';last_route={}
        def __init__(self):self.calls=0;self.during=[]
        def approve(self,*args):pass
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            payload=json.loads(evidence);self.calls+=1
            self.during.append(len(store.get_web_run('one',run.id).lead_ids))
            names=[f'Hotel {i}' for i in range(12) if f'"Hotel {i}"' not in payload['public_request']][:payload['max_companies']]
            companies=[{'name':name,'page_id':'P1','name_block_id':'b1','entity_type':'company','website':None,
                'facts':[{'field':'offering','value':'operates resorts','source_block_id':'b1'}],
                'assessment':{'recommendation':'investigate','rationale':f'{name} operates resorts. Guest demand remains to be assessed.','strengths':[],'concerns':[],'missing_information':[],'incubation_actions':[],'evidence_ids':['E2']}} for name in names]
            self.last_response_text=json.dumps({'companies':companies,'coverage_limits':[]})
            return schema.model_validate_json(self.last_response_text)
    with Store(tmp_path/'db') as store:
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test',seed_urls=[page.url]);model=Model()
        source_public_companies(store,run,model=model,fetcher=Fetcher(),max_companies=12)
        assert len(run.lead_ids)==12,run.error
        assert model.during==[0,8]
        assert run.generation_config['requested_companies']==12
        previous=set(run.lead_ids)
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test',seed_urls=[page.url])
        source_public_companies(store,run,model=Model(),fetcher=Fetcher(),max_companies=12)
        assert set(run.lead_ids)==previous
        assert len(store.list_leads('one'))==12


def test_fetch_pages_honors_explicit_discovery_limit_beyond_six():
    from agents.research.public_research import fetch_pages
    class Fetcher:
        def fetch(self,url):return Page(url,'Company','Company operates hotels.')
    urls=[f'https://company{i}.example/' for i in range(9)]
    assert len(fetch_pages(urls,fetcher=Fetcher(),max_pages=9))==9
    assert len(fetch_pages(urls,fetcher=Fetcher()))==6


def test_discovery_continuation_reuses_retained_pages_without_search_or_fetch(tmp_path,monkeypatch):
    from agents.discovery.subscription_discovery import source_public_companies
    from schemas import WebSourcingRun,utcnow
    from store import Store
    page={'page_id':'P4','PAGE_URL':'https://directory.example/','PAGE_TITLE':'Hotels','PAGE_BLOCKS':{'b1':'Hotel New operates resorts.'},'PAGE_LINKS':[]}
    def forbidden(*a,**k):raise AssertionError('Retained source collection must not repeat')
    monkeypatch.setattr('agents.discovery.subscription_discovery.navigate',forbidden)
    monkeypatch.setattr('agents.discovery.subscription_discovery.fetch_pages',forbidden)
    class Model:
        name='test';last_route={}
        def approve(self,*args):pass
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            payload=json.loads(evidence)
            assert task=='public_discovery' and payload['pages']==[page]
            self.last_response_text=json.dumps({'companies':[{'name':'Hotel New','page_id':'P4','name_block_id':'b1','entity_type':'company','website':None,'facts':[{'field':'offering','value':'operates resorts','source_block_id':'b1'}],'assessment':{'recommendation':'investigate','rationale':'Hotel New operates resorts; occupancy is unknown.','strengths':[],'concerns':[],'missing_information':[],'incubation_actions':[],'evidence_ids':['E2']}}],'coverage_limits':[]})
            return schema.model_validate_json(self.last_response_text)
    with Store(tmp_path/'db') as store:
        previous=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test',generation_config={'retained_pages':[page],'pending_page_groups':[['P4']],'source_collected_at':utcnow()})
        store.save_web_run(previous)
        run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test',generation_config={'continuation_of':previous.id,'exclude_names':['Hotel Earlier']})
        source_public_companies(store,run,model=Model(),max_companies=1)
        assert len(run.lead_ids)==1,run.error
        assert run.generation_config['reused_sources_from']==previous.id
        assert run.generation_config['budget']['calls']==1
