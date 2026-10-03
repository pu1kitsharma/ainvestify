import json
import time
from copy import deepcopy
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from pydantic import BaseModel

from agents.inference.deepseek_api import DeepSeekPublicModel, run_public
from agents.inference.public_cache import PublicResultCache, cache_key
from agents.inference.model_authorship import recorded_call, response_answer
from agents.inference.subscription_model import make_preparation_model, default_preparation_name
from agents.preparation.preparation_budget import preparation_budget, PreparationBudget, PreparationBudgetExceeded


class Answer(BaseModel):
    text: str


class FakeES:
    """Exercise the ES wire shapes, lease conflicts and sequence fencing."""
    def __init__(self):
        self.rows = {}
        self.headers = {}
        self.requests = []
        self.fail = False

    def request(self, method, url, json=None, params=None, **kwargs):
        self.requests.append((method,url,deepcopy(json),params,kwargs))
        assert kwargs['allow_redirects'] is False
        if self.fail:
            return Mock(status_code=503)
        index, operation, key = urlsplit(url).path.strip('/').split('/')
        identity = (index,key)
        prior = self.rows.get(identity)
        if method == 'GET':
            return Mock(status_code=200 if prior else 404, json=lambda:deepcopy(prior or {}))
        if operation == '_create' and prior:
            return Mock(status_code=409)
        if params and (not prior or params != {'if_seq_no':prior['_seq_no'],'if_primary_term':prior['_primary_term']}):
            return Mock(status_code=409)
        if method == 'DELETE':
            self.rows.pop(identity,None)
            return Mock(status_code=200)
        self.rows[identity] = {'_source':deepcopy(json),'_seq_no':prior['_seq_no']+1 if prior else 0,'_primary_term':1}
        return Mock(status_code=200 if prior else 201,json=lambda:{'result':'created'})

    def put(self,url,**kwargs):return self.request('PUT',url,**kwargs)
    def get(self,url,**kwargs):return self.request('GET',url,**kwargs)
    def delete(self,url,**kwargs):return self.request('DELETE',url,**kwargs)


@pytest.fixture
def es(monkeypatch,tmp_path):
    monkeypatch.setenv('ELASTICSEARCH_URL','http://127.0.0.1:9200')
    monkeypatch.delenv('ELASTICSEARCH_API_KEY',raising=False)
    monkeypatch.setenv('PUBLIC_REASONING_LEDGER',str(tmp_path/'spend.db'))
    monkeypatch.setenv('PUBLIC_REASONING_MONTHLY_USD','5')
    instance=FakeES()
    monkeypatch.setattr('agents.inference.public_cache.requests.Session',lambda:instance)
    return instance


def model():
    result=DeepSeekPublicModel()
    result._public_context={'company':'Synthetic Example','facts':[]}
    return result


def http(monkeypatch, *, finish='stop', code=0, raw='{"text":"Sourced synthetic answer."}'):
    process=Mock(returncode=code)
    process.poll.return_value=code
    process.communicate.return_value=(json.dumps({'model':'deepseek-flash','id':'test_response','usage':{'prompt_tokens':20,'completion_tokens':10},
        'finish_reason':finish,'content':raw,'tool_calls':False}),'')
    start=Mock(return_value=process)
    monkeypatch.setattr('agents.inference.deepseek_api.subprocess.Popen',start)
    monkeypatch.setenv('DEEPSEEK_API_KEY','synthetic-test-key')
    return start


def test_default_is_local_without_hosted_fallback(monkeypatch):
    monkeypatch.delenv('PREPARATION_PROVIDER',raising=False)
    assert not default_preparation_name().startswith(('deepseek-api:', 'anthropic-api:', 'claude-pro'))
    assert not isinstance(make_preparation_model(),DeepSeekPublicModel)
    assert not hasattr(make_preparation_model(),'_run_cli')


def test_repeat_request_reuses_exact_raw_answer_with_zero_paid_requests(es,monkeypatch):
    start=http(monkeypatch)
    payload={'company':'Synthetic Example','facts':[],'request':{}}
    for index in range(2):
        attempts=[]
        with preparation_budget(PreparationBudget(10,max_calls=1,max_requests=1)) as budget:
            answer,ref=recorded_call(model(),'authored_draft','Write sourced JSON',payload,Answer,attempts,lambda:None)
        assert response_answer(attempts,ref)==answer.model_dump()
        assert attempts[0]['routing']['cache_hit']==bool(index)
        assert budget.requests==(0 if index else 1)
        assert (budget.reserved_cost_usd==0)==bool(index)
        assert 'synthetic-test-key' not in json.dumps(attempts)
    assert start.call_count==1
    body=json.loads(start.return_value.communicate.call_args.kwargs['input'])
    assert 'tools' not in body
    assert es.trust_env is False


def test_changed_evidence_or_prompt_cannot_reuse_result(es,monkeypatch):
    start=http(monkeypatch)
    for text in ['first source revision','second source revision']:
        with preparation_budget():
            run_public(model(),'public_test',text,'{}',Answer)
    assert start.call_count==2


def test_cache_outage_blocks_spend(es,monkeypatch):
    es.fail=True
    start=http(monkeypatch)
    with preparation_budget(),pytest.raises(ValueError,match='cache unavailable'):
        run_public(model(),'public_test','test','{}',Answer)
    start.assert_not_called()


def test_missing_cache_blocks_uncached_spend(monkeypatch):
    monkeypatch.delenv('ELASTICSEARCH_URL',raising=False)
    start=http(monkeypatch)
    with preparation_budget(),pytest.raises(ValueError,match='ELASTICSEARCH_URL'):
        run_public(model(),'public_test','test','{}',Answer)
    start.assert_not_called()


def test_missing_key_does_not_fall_back(es,monkeypatch):
    start=http(monkeypatch)
    monkeypatch.delenv('DEEPSEEK_API_KEY')
    monkeypatch.delenv('DEEPSEEK_API_KEY_FILE',raising=False)
    with preparation_budget(),pytest.raises(ValueError,match='server-side'):
        run_public(model(),'public_test','test','{}',Answer)
    start.assert_not_called()


@pytest.mark.parametrize('extra',[{'private_notes':'secret'},{'request':'confidential strategy'},{'facts':[{'text':'private ledger'}]}])
def test_private_or_changed_payload_blocked_before_cache_and_network(es,monkeypatch,extra):
    start=http(monkeypatch)
    payload={'company':'Synthetic Example','facts':[],'request':{},**extra}
    with pytest.raises(ValueError,match='Private context'):
        model().generate_for_task('authored_draft','test',json.dumps(payload),Answer)
    assert es.requests==[]
    start.assert_not_called()


def test_private_source_cannot_be_registered():
    with pytest.raises(ValueError,match='public website'):
        model().set_public_context('Synthetic Example',[{'origin':'uploaded_document','source_url':'https://example.com/','text':'secret'}])


@pytest.mark.parametrize('url',['https://external.example:9200','http://user:pass@localhost:9200','http://localhost:9200/?secret=x'])
def test_cache_cannot_silently_be_hosted_elsewhere(monkeypatch,url):
    monkeypatch.setenv('ELASTICSEARCH_URL',url)
    with pytest.raises(ValueError,match='loopback'):
        PublicResultCache()


def test_expired_corrupt_or_different_key_is_not_a_cache_hit(es):
    cache=PublicResultCache()
    key=cache_key('model','task','prompt','{}',Answer,{})
    cache.put(key,'{"text":"saved"}','model',{})
    row=es.rows[(cache.index,key)]['_source']
    assert cache.get(key,Answer)
    row['expires_at']=0
    assert cache.get(key,Answer) is None
    row['expires_at']=time.time()+100
    row['raw_response']='{"text":"tampered"}'
    assert cache.get(key,Answer) is None
    row['key']='another-request'
    assert cache.get(key,Answer) is None


def test_lease_prevents_duplicate_and_stale_owner_release(es):
    cache=PublicResultCache()
    first=cache.claim('key')
    with pytest.raises(ValueError,match='identical request'):
        cache.claim('key')
    es.rows[('ainvestify-public-leases-v1','key')]['_source']['expires_at']=0
    second=cache.claim('key')
    cache.release('key',first)
    assert es.rows[('ainvestify-public-leases-v1','key')]['_source']['owner']==second
    cache.release('key',second)
    assert ('ainvestify-public-leases-v1','key') not in es.rows


def test_incomplete_response_is_not_cached_or_automatically_repeated(es,monkeypatch):
    start=http(monkeypatch,finish='length')
    for index in range(2):
        with preparation_budget(),pytest.raises(ValueError,match='incomplete' if index==0 else 'identical request'):
            run_public(model(),'public_test','test','{}',Answer)
    assert start.call_count==1
    assert not any(index=='ainvestify-public-results-v1' for index,key in es.rows)


def test_cost_limit_blocks_before_http(es,monkeypatch):
    start=http(monkeypatch)
    with preparation_budget() as budget:
        budget.reserve_cost(.25)
        with pytest.raises(PreparationBudgetExceeded,match='cost ceiling'):
            run_public(model(),'public_test','test','{}',Answer)
    start.assert_not_called()


@pytest.mark.parametrize('amount',[float('nan'),float('inf'),-1])
def test_invalid_cost_reservations_fail_closed(amount):
    with pytest.raises(PreparationBudgetExceeded):
        PreparationBudget().reserve_cost(amount)


def test_monthly_guard_survives_new_job_objects(es,monkeypatch):
    from agents.inference.spend_guard import reserve_monthly
    monkeypatch.setenv('PUBLIC_REASONING_MONTHLY_USD','.02')
    reserve_monthly(.015,'first-job')
    with pytest.raises(PreparationBudgetExceeded,match='monthly'):
        reserve_monthly(.015,'second-job')
