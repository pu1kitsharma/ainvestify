import json

import pytest

from agents.discovery.web_discovery import MwmblSearch, SearchSession
from agents.discovery.web_sources import SourceError
from schemas import WebSourcingRun


def body(**updates):
    return {'query':'synthetic topic','number_of_results':1,
        'results':[{'url':'https://service.example/','title':'Service Example','content':'Navigation hint only'}],
        'monthly_usage':None,'monthly_limit':None,**updates}


class Transport:
    def __init__(self, result=None, status=200):
        self.result=body() if result is None else result
        self.status=status
        self.urls=[]
    def _request(self,url,deadline):
        assert url.startswith('https://api.mwmbl.org/api/v2/search/?q=')
        assert 'api_key' not in url and '/v1/' not in url
        self.urls.append(url)
        return self.status,{},json.dumps(self.result).encode()


@pytest.mark.parametrize('result',[
    [],body(number_of_results=True),body(results={}),
    body(results=[{'url':'https://service.example/','title':'Name','content':{'claim':'bad shape'}}]),
    body(monthly_usage='untrusted'),body(monthly_limit=-1),
])
def test_v2_rejects_legacy_or_invalid_shapes_without_alternate_version(result,monkeypatch):
    monkeypatch.setattr(MwmblSearch,'_last_request',0)
    transport=Transport(result)
    with pytest.raises(SourceError,match='invalid search response'):
        MwmblSearch(transport).search('synthetic topic')
    assert len(transport.urls)==1


def test_429_disables_provider_for_the_entire_run_without_v1_retry(monkeypatch):
    monkeypatch.setattr(MwmblSearch,'_last_request',0)
    transport=Transport(status=429)
    run=WebSourcingRun(tenant_id='one',thesis='Synthetic topic',model='fixture')
    session=SearchSession([MwmblSearch(transport)])
    assert session.search_queries(['first','second'],run,lambda:True)==[]
    assert session.search_queries(['third'],run,lambda:True)==[]
    assert len(transport.urls)==1
    assert run.sources[0].status=='rate_limited'


def test_anonymous_requests_are_spaced_and_snippets_remain_navigation_hints(monkeypatch):
    import agents.discovery.web_discovery as module
    clock=[20.0]
    sleeps=[]
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    def sleep(seconds):
        sleeps.append(seconds);clock[0]+=seconds
    monkeypatch.setattr(module.time,'sleep',sleep)
    monkeypatch.setattr(MwmblSearch,'_last_request',0)
    transport=Transport(body(results=[{'url':'https://service.example/','title':'Service Example','content':'x'*5000}]))
    search=MwmblSearch(transport)
    first=search.search('first')
    second=search.search('second')
    assert sleeps==[1]
    assert len(first[0].snippet)==700 and first==second
    assert search.last_metadata['api_version']=='v2'
    assert search.last_metadata['monthly_limit'] is None
