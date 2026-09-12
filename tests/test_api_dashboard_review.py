"""
Coverage for the Milestone 2 read-only FastAPI layer (api/routers/dashboard.py,
api/routers/review.py). Uses FastAPI's dependency_overrides to point the app
at the same isolated `store` fixture every other test uses, rather than the
real on-disk deal_automation.db.
"""
from conftest import DEAL, TENANT, make_extraction_result
from fastapi.testclient import TestClient

import api.deps as deps
from agents.planner_agent import start_deal
from agents.review_checkpoint import apply_field_decision
from api.main import app
from schemas import FieldStatus
from store import Store


def _client_for(db_path):
    # TestClient runs sync endpoint functions in a worker thread pool, and
    # sqlite3 connections aren't safe to hand across threads -- so, exactly
    # like the real get_store dependency, open a fresh Store per request
    # rather than reusing one connection created in the test's own thread.
    def override_get_store():
        with Store(db_path) as s:
            yield s

    app.dependency_overrides[deps.get_store] = override_get_store
    app.dependency_overrides[deps.get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_list_deals_returns_summary(store, tmp_path):
    db_path = tmp_path / "test.db"
    start_deal(store, TENANT, "Acme Robotics")
    client = _client_for(db_path)

    r = client.get("/api/deals")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["deal"]["name"] == "Acme Robotics"
    assert body[0]["document_count"] == 0


def test_list_deals_filters_by_status(store, tmp_path):
    db_path = tmp_path / "test.db"
    start_deal(store, TENANT, "Acme Robotics")
    client = _client_for(db_path)

    assert client.get("/api/deals", params={"status": "new"}).json()
    assert client.get("/api/deals", params={"status": "compiled"}).json() == []


def test_get_deal_404_for_unknown_id(store, tmp_path):
    db_path = tmp_path / "test.db"
    client = _client_for(db_path)
    r = client.get("/api/deals/does-not-exist")
    assert r.status_code == 404


def test_get_review_reflects_ready_for_compilation(store, tmp_path):
    db_path = tmp_path / "test.db"
    deal = start_deal(store, TENANT, "Acme Robotics")
    result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
    store.save_extraction_result(result)
    client = _client_for(db_path)

    # Not everything is resolved yet -- not ready.
    r = client.get(f"/api/deals/{deal.id}/review")
    assert r.status_code == 200
    assert r.json()["ready_for_compilation"] is False

    # Resolve every required field the same way the CLI's review loop would,
    # via the Milestone 1 pure functions -- then the GET payload must flip.
    for name in ("arr", "arr_prior_year", "burn_monthly", "cash_on_hand", "runway_months", "headcount"):
        apply_field_decision(result, name, "alice", "approve")
    for name in ("mrr", "growth_rate_yoy"):
        apply_field_decision(result, name, "alice", "acknowledge")
    result.cap_table_status = FieldStatus.NOT_FOUND
    result.cap_table_reviewed_at = "2026-01-01T00:00:00"
    result.funding_history_status = FieldStatus.NOT_FOUND
    result.funding_history_reviewed_at = "2026-01-01T00:00:00"
    store.save_extraction_result(result)

    r = client.get(f"/api/deals/{deal.id}/review")
    assert r.json()["ready_for_compilation"] is True


def test_get_review_404_for_unknown_deal(store, tmp_path):
    db_path = tmp_path / "test.db"
    client = _client_for(db_path)
    r = client.get("/api/deals/does-not-exist/review")
    assert r.status_code == 404
