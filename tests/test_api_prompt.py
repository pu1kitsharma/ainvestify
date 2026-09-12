"""
Coverage for api/routers/prompt.py -- previously zero tests of any kind for
/api/prompt/classify, and directive/preview was only ever exercised with
the deterministic "continue" path, never with a real free-text directive
that requires the LLM classifier (agents/planner_agent.classify_directive).
Both hit real Ollama models (ROUTER_MODEL/PLANNER_MODEL, both llama3.2:3b)
-- slower than a mocked test, but this project's whole testing philosophy
so far has been real models/APIs over mocks, and a router that silently
broke would be a real regression a mock could hide.
"""
from conftest import TENANT
from fastapi.testclient import TestClient

import api.deps as deps
from agents.planner_agent import start_deal
from api.main import app
from store import Store


def _client_for(db_path):
    def override_get_store():
        with Store(db_path) as s:
            yield s

    app.dependency_overrides[deps.get_store] = override_get_store
    app.dependency_overrides[deps.get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_classify_prompt_source_leads(tmp_path):
    client = _client_for(tmp_path / "test.db")
    r = client.post("/api/prompt/classify", json={
        "prompt": "find early-stage companies in the fintech space worth incubating",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "source_leads"
    assert body["sector_keyword"]


def test_classify_prompt_screen_deal(tmp_path):
    client = _client_for(tmp_path / "test.db")
    r = client.post("/api/prompt/classify", json={
        "prompt": "screen this deal, I have the pitch deck for Acme Robotics ready to review",
    })
    assert r.status_code == 200
    assert r.json()["action"] == "screen_deal"


def test_directive_preview_with_real_llm_classification(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    # REVIEWED is the state with the richest valid-action set (research,
    # compile, compile_teaser, compile_proforma, add_investor,
    # view_demand_book, rerun_extraction) -- exactly the state that exposed
    # the real llama3.2:1b->3b misclassification bug logged in CLAUDE.md,
    # so it's the meaningful state to test the API's classify path against.
    from schemas import DealStatus
    deal.status = DealStatus.REVIEWED
    store.save_deal(deal)
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/directive/preview", json={
        "directive": "generate the anonymous teaser so we can start showing this around",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "compile_teaser"
    assert body["reasoning"]


def test_directive_preview_rerun_extraction_names_target_field(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    from schemas import DealStatus
    deal.status = DealStatus.REVIEWED
    store.save_deal(deal)
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/directive/preview", json={
        "directive": "the burn number looks wrong, please re-check it",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "rerun_extraction"
    assert body["target_field"] == "burn_monthly"
