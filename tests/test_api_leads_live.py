"""
Live-network coverage for the leads sourcing endpoints (api/routers/leads.py).
Gap identified after Milestone 3's check-in: /api/leads/source and
/api/leads/source-ib had zero test coverage of any kind -- every existing
leads test seeded a SourcedLead directly via the store, bypassing sourcing
entirely. These hit real GitHub/HN/SEC EDGAR APIs (same zero-budget sources
agents/sourcing_agent.py already uses live elsewhere in this project), so
they're slower and can occasionally return zero leads for a given keyword/
window -- assertions below only require the calls to succeed and return a
well-formed list, not a guaranteed non-empty result, since "no candidates
found right now" is a legitimate real answer, not a failure.
"""
from conftest import TENANT
from fastapi.testclient import TestClient

import api.deps as deps
from api.main import app
from store import Store


def _client_for(db_path):
    def override_get_store():
        with Store(db_path) as s:
            yield s

    app.dependency_overrides[deps.get_store] = override_get_store
    app.dependency_overrides[deps.get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_source_leads_live_vc_style(tmp_path):
    client = _client_for(tmp_path / "test.db")
    r = client.post("/api/leads/source", json={"sector_keyword": "robotics"})
    assert r.status_code == 200
    leads = r.json()
    assert isinstance(leads, list)
    for lead in leads:
        assert lead["tenant_id"] == TENANT
        assert lead["status"] == "new"

    # Persisted, not just returned -- GET /api/leads must see the same rows.
    listed = client.get("/api/leads").json()
    assert len(listed) == len(leads)


def test_source_ib_targets_live(tmp_path):
    client = _client_for(tmp_path / "test.db")
    r = client.post("/api/leads/source-ib", json={"sector_keyword": "software"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_source_then_decide_then_promote_live(tmp_path):
    client = _client_for(tmp_path / "test.db")
    leads = client.post("/api/leads/source", json={"sector_keyword": "robotics"}).json()
    if not leads:
        return  # legitimate "nothing found this run" -- nothing further to exercise

    lead = leads[0]
    r = client.post(f"/api/leads/{lead['id']}/decision", json={"decision": "keep"})
    assert r.status_code == 200
    assert r.json()["status"] == "reviewed"

    r = client.post(f"/api/leads/{lead['id']}/promote", json={})
    assert r.status_code == 200
    deal = r.json()
    assert deal["status"] == "new"
    assert deal["name"] == lead["company_name"]

    r = client.get(f"/api/leads/{lead['id']}")
    assert r.json()["status"] == "promoted_to_deal"
    assert r.json()["promoted_deal_id"] == deal["id"]
