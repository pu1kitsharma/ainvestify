"""
Coverage for the Milestone 4 compilation endpoints (api/routers/compilation.py):
CIM, the teaser's two-step draft/confirm, pro-forma with override, rerun
analytics, and the document-suite GET endpoints. Real matplotlib chart
rendering runs here (agents/analytics_agent.generate_charts is deterministic,
no LLM/network needed) -- only the CIM's narrative paragraph is skipped via
include_narrative machinery already being off by default in these tests'
data (no LLM call needed since compile_cim's own narrative failure path
returns None on any exception, verified separately in test_compilation_agent.py).
"""
import shutil
from pathlib import Path

from conftest import TENANT, make_extraction_result
from fastapi.testclient import TestClient

import api.deps as deps
from agents.planner_agent import start_deal
from api.main import app
from schemas import FieldStatus
from store import Store

MEMO_OUTPUT_ROOT = Path(__file__).parent.parent / "memo_output"


def _client_for(db_path):
    def override_get_store():
        with Store(db_path) as s:
            yield s

    app.dependency_overrides[deps.get_store] = override_get_store
    app.dependency_overrides[deps.get_tenant_id] = lambda: TENANT
    app.dependency_overrides[deps.get_reviewer] = lambda: "alice"
    return TestClient(app)


def _fully_approved_result(deal):
    result = make_extraction_result(tenant_id=deal.tenant_id, deal_id=deal.id)
    for name in ("arr", "arr_prior_year", "burn_monthly", "cash_on_hand", "runway_months", "headcount"):
        getattr(result, name).status = FieldStatus.APPROVED
    for name in ("mrr", "growth_rate_yoy"):
        ev = getattr(result, name)
        ev.status = FieldStatus.NOT_FOUND
        ev.reviewed_at = "2026-01-01T00:00:00"
    result.cap_table_status = FieldStatus.NOT_FOUND
    result.cap_table_reviewed_at = "2026-01-01T00:00:00"
    result.funding_history_status = FieldStatus.NOT_FOUND
    result.funding_history_reviewed_at = "2026-01-01T00:00:00"
    return result


def _cleanup_memo_output(deal_id: str) -> None:
    shutil.rmtree(MEMO_OUTPUT_ROOT / deal_id, ignore_errors=True)


def test_compile_cim_returns_structured_data(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.save_extraction_result(_fully_approved_result(deal))
    store.close()

    client = _client_for(db_path)
    try:
        r = client.post(f"/api/deals/{deal.id}/compile/cim")
        assert r.status_code == 200
        body = r.json()
        assert body["document_type"] == "cim"
        assert body["structured_data"] is not None
        assert body["structured_data"]["financials"]["arr"]["value"] == 2_400_000
        assert Path(body["content_uri"]).exists()
    finally:
        _cleanup_memo_output(deal.id)


def test_compile_cim_blocked_before_review_returns_409(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.save_extraction_result(make_extraction_result(tenant_id=TENANT, deal_id=deal.id))  # not reviewed
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/compile/cim")
    assert r.status_code == 409


def test_teaser_draft_then_confirm_over_http(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.save_extraction_result(_fully_approved_result(deal))
    store.close()

    client = _client_for(db_path)
    try:
        draft = client.post(
            f"/api/deals/{deal.id}/compile/teaser/draft",
            json={"business_description": "A robotics platform for warehouse operators."},
        )
        assert draft.status_code == 200
        memo = draft.json()
        assert memo["approved_by"] is None  # draft only
        assert "deal_name" not in memo["structured_data"]
        assert "cap_table" not in memo["structured_data"]

        confirmed = client.post(
            f"/api/deals/{deal.id}/compile/teaser/{memo['id']}/confirm", json={"confirmed": True},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["approved_by"] == "alice"

        # Re-fetch to prove it's real persisted state, not just the response echo.
        latest = client.get(f"/api/deals/{deal.id}/documents/latest", params={"document_type": "teaser"})
        assert latest.json()["approved_by"] == "alice"
    finally:
        _cleanup_memo_output(deal.id)


def test_confirm_teaser_unknown_memo_id_404(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/compile/teaser/does-not-exist/confirm", json={"confirmed": True})
    assert r.status_code == 404


def test_compile_proforma_with_override_over_http(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.save_extraction_result(_fully_approved_result(deal))
    store.close()

    client = _client_for(db_path)
    try:
        r = client.post(f"/api/deals/{deal.id}/compile/proforma", json={"growth_rate_override": 42.0})
        assert r.status_code == 200
        body = r.json()
        assert body["document_type"] == "proforma"
        assert body["approved_by"] == "alice"
        assert body["structured_data"]["is_projected"] is True
        assert "42.0" in body["structured_data"]["assumptions"][0]
    finally:
        _cleanup_memo_output(deal.id)


def test_rerun_analytics_over_http(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.save_extraction_result(_fully_approved_result(deal))
    store.close()

    client = _client_for(db_path)
    try:
        r = client.post(f"/api/deals/{deal.id}/analytics/rerun")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
    finally:
        _cleanup_memo_output(deal.id)


def test_list_documents_filters_by_type(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.save_extraction_result(_fully_approved_result(deal))
    store.close()

    client = _client_for(db_path)
    try:
        client.post(f"/api/deals/{deal.id}/compile/cim")
        client.post(f"/api/deals/{deal.id}/compile/proforma", json={})

        all_docs = client.get(f"/api/deals/{deal.id}/documents")
        assert len(all_docs.json()) == 2

        cim_only = client.get(f"/api/deals/{deal.id}/documents", params={"document_type": "cim"})
        assert len(cim_only.json()) == 1
        assert cim_only.json()[0]["document_type"] == "cim"
    finally:
        _cleanup_memo_output(deal.id)


def test_get_latest_document_404_when_none_exists(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    client = _client_for(db_path)
    r = client.get(f"/api/deals/{deal.id}/documents/latest", params={"document_type": "teaser"})
    assert r.status_code == 404
