import asyncio
import json
import time
from unittest.mock import AsyncMock
import pytest
from agents.local_models import LocalModel, generate_task, MODEL_JOB_SLOT
from agents.preparation_budget import PreparationBudget, PreparationBudgetExceeded, preparation_budget, ACTIVE_BUDGET
from agents.analyst_pack import prepare_section_pack as prepare_analyst_pack
from tests.test_analyst_pack import Model
from tests.test_local_models import Output
from tests.test_operating_workflow import company
from store import Store


def test_deadline_cancels_inflight_request_and_releases_queue(monkeypatch):
    cancelled=[]
    class Client:
        def __init__(self,**kwargs):self._client=type('Transport',(),{'aclose':AsyncMock()})()
        async def chat(self,**kwargs):
            try:await asyncio.sleep(10)
            finally:cancelled.append(True)
    monkeypatch.setattr('agents.local_models.ollama.AsyncClient',Client)
    start=time.monotonic()
    with preparation_budget(PreparationBudget(.05)) as budget:
        with pytest.raises(PreparationBudgetExceeded):generate_task(LocalModel(),'analyst_section','Write','{}',Output)
    assert time.monotonic()-start<1
    assert cancelled==[True] and budget.calls==budget.requests==1
    assert MODEL_JOB_SLOT.acquire(blocking=False)
    MODEL_JOB_SLOT.release()
    assert ACTIVE_BUDGET.get() is None


def test_reasoning_continuation_shares_request_budget(monkeypatch):
    class Client:
        def __init__(self,**kwargs):self._client=type('Transport',(),{'aclose':AsyncMock()})()
        async def chat(self,**kwargs):return {'message':{'thinking':'private','content':''},'done_reason':'length','eval_count':512}
    monkeypatch.setattr('agents.local_models.ollama.AsyncClient',Client)
    with preparation_budget(PreparationBudget(1,max_requests=1)) as budget:
        with pytest.raises(PreparationBudgetExceeded,match='request limit'):
            generate_task(LocalModel('qwen3:8b',thinking=True,max_tokens=1400,reasoning_budget=512),'analyst_section','Write','{}',Output)
    assert budget.requests==1
    assert MODEL_JOB_SLOT.acquire(blocking=False)
    MODEL_JOB_SLOT.release()


def test_raw_reasoning_continuation_is_cancelled_within_the_same_deadline(monkeypatch):
    cancelled=[];transports=[]
    class Client:
        def __init__(self,**kwargs):
            self._client=type('Transport',(),{'aclose':AsyncMock()})()
            transports.append(self._client)
        async def chat(self,**kwargs):
            return {'message':{'thinking':'private test reasoning','content':''},'done_reason':'length','eval_count':512}
        async def generate(self,**kwargs):
            assert kwargs['raw'] is True and kwargs['think'] is False
            try:await asyncio.sleep(10)
            finally:cancelled.append(True)
    monkeypatch.setattr('agents.local_models.ollama.AsyncClient',Client)
    model=LocalModel('qwen3.5:9b',thinking=True,max_tokens=1024,reasoning_budget=512)
    start=time.monotonic()
    with preparation_budget(PreparationBudget(.05)) as budget:
        with pytest.raises(PreparationBudgetExceeded,match='cancelled'):
            generate_task(model,'shared_review','Review','{}',Output)
    assert time.monotonic()-start<1
    assert budget.calls==1 and budget.requests==2 and cancelled==[True]
    assert len(transports)==2 and all(t.aclose.await_count==1 for t in transports)
    assert model.last_response_text==''
    assert MODEL_JOB_SLOT.acquire(blocking=False)
    MODEL_JOB_SLOT.release()


def test_queue_wait_uses_same_deadline_and_never_starts_inference(monkeypatch):
    client=AsyncMock();monkeypatch.setattr('agents.local_models.ollama.AsyncClient',client)
    assert MODEL_JOB_SLOT.acquire(blocking=False)
    try:
        with preparation_budget(PreparationBudget(.02)):
            with pytest.raises(PreparationBudgetExceeded,match='waiting'):
                generate_task(LocalModel(),'analyst_section','Write','{}',Output)
        client.assert_not_called()
    finally:MODEL_JOB_SLOT.release()


def test_call_cap_saves_partial_results_and_explicit_resume_reuses_them(tmp_path):
    with Store(tmp_path/'db') as store:
        lead=company(store);model=Model()
        partial=prepare_analyst_pack(store,lead,model,budget=PreparationBudget(10,max_calls=4))
        assert len(model.calls)==4
        assert partial.analyst_pack['sections']['research.business']['status']=='complete'
        assert 'model-call limit' in partial.analyst_pack['stop_reason']
        first=partial.analyst_pack['sections']['research.business']['content']
        resumed=prepare_analyst_pack(store,lead,Model())
        assert resumed.analyst_pack['status']=='complete'
        assert resumed.analyst_pack['sections']['research.business']['content']==first
        assert 'stop_reason' not in resumed.analyst_pack


def test_cached_pack_uses_no_inference_and_actions_do_not_need_writers(tmp_path):
    with Store(tmp_path/'db') as store:
        lead=company(store);model=Model()
        first=prepare_analyst_pack(store,lead,model)
        assert first.analyst_pack['status']=='complete'
        assert len(model.calls)==16  # Previously 20 on this no-retry fixture.
        for suffix in ('a','b'):
            rows=first.analyst_pack['sections']
            assert rows['readiness.action_'+suffix]['content']['analysis_plan']==rows['diligence.request_'+suffix]['content']['analysis_plan']
        resumed=Model();start=time.monotonic()
        result=prepare_analyst_pack(store,lead,resumed)
        assert result.analyst_pack['status']=='complete' and resumed.calls==[]
        assert time.monotonic()-start<1


def test_budget_configuration_is_bounded_and_defaults_to_users_two_minutes(monkeypatch):
    monkeypatch.delenv('PREPARATION_MAX_SECONDS',raising=False)
    assert PreparationBudget().max_seconds==120
    for seconds in (0,121,float('nan'),float('inf')):
        with pytest.raises(ValueError):PreparationBudget(seconds)


def test_expiring_before_review_keeps_candidate_without_another_writer(tmp_path):
    with Store(tmp_path/'db') as store:
        lead=company(store)
        first=prepare_analyst_pack(store,lead,Model(),budget=PreparationBudget(10,max_calls=3))
        assert first.analyst_pack['sections']['research.business']['status']=='review_pending'
        model=Model();prepare_analyst_pack(store,lead,model)
        assert 'draft' in model.calls[0][1]  # Resume the critic, not the writer.
        assert first.analyst_pack['attempts'][-1]['invoked'] is False
