import json
from unittest.mock import Mock
from types import SimpleNamespace

from agents.discovery.web_sources import Page
from agents.preparation.preparation_budget import preparation_budget
from agents.research.independent_search import search_and_select
from agents.research.public_research import Navigation, observed_search
from agents.research.source_cache import fetch_public_page


class MemoryCache:
    rows={}
    def __init__(self,namespace='results',**kwargs):self.namespace=namespace
    def get(self,key,schema):return self.rows.get((self.namespace,key))
    def put(self,key,raw,*args):self.rows[(self.namespace,key)]={'raw_response':raw}


def test_source_snapshot_reuses_original_blocks_without_fetch(monkeypatch):
    MemoryCache.rows={}
    monkeypatch.setattr('agents.research.source_cache.PublicResultCache',MemoryCache)
    page=Page('https://example.com/','Synthetic','Original source',content_blocks=['Original source'])
    fetch=Mock(return_value=page)
    monkeypatch.setattr('agents.research.source_cache.PublicWebFetcher',lambda **kw:Mock(fetch=fetch))
    assert fetch_public_page(page.url)==page
    assert fetch_public_page(page.url)==page
    assert fetch.call_count==1


def test_search_result_cache_preserves_observed_links_without_second_search(monkeypatch):
    MemoryCache.rows={}
    monkeypatch.setattr('agents.research.independent_search.PublicResultCache',MemoryCache)
    from agents.discovery.web_discovery import SearchHit
    search=Mock(return_value=[SearchHit('https://example.com/','Synthetic','Observed snippet')])
    monkeypatch.setattr('agents.research.independent_search.SearchSession',lambda:Mock(providers=[SimpleNamespace(name='test')],search_queries=search))
    class Model:
        name='synthetic-test'
        def _reason(self,task,instruction,evidence,schema):
            value={'queries':['India seed fintech']} if task=='public_search_queries' else {
                'interpretation':'Research Indian seed companies.','urls':['https://example.com/'],'official_website':None}
            self.last_response_text=json.dumps(value)
            self.last_route={'invoked':True}
            return schema.model_validate(value)
    request=json.dumps({'public_request':'Indian seed fintech','geography':'India','purpose':'discovery'})
    for _ in range(2):
        model=Model()
        with preparation_budget():
            result=search_and_select(model,'Discover companies',request,Navigation)
        assert result.urls==['https://example.com/']
        assert observed_search(model.search_transcript)==({'https://example.com/':'Synthetic'},['India seed fintech'])
        assert model.last_route['query_generation']['raw_response']
    assert search.call_count==1
