"""
Coverage for the Milestone 3 write endpoints (leads, deal lifecycle,
review decisions, research, investors) added across api/routers/*.py.

LLM-dependent paths (extract, and the retry side of a rejected field/cap
table/funding-history decision) need a live Ollama model and are covered by
the live HTTP smoke test instead (see the milestone verification notes),
not here -- this file covers the deterministic wiring: does each endpoint
call the right pure function, persist correctly, and return the right
shape/status code.
"""
from pathlib import Path

from conftest import TENANT, make_extraction_result
from fastapi.testclient import TestClient

import api.deps as deps
from agents.planner_agent import start_deal
from api.main import app
from schemas import DealStatus, FieldStatus, InvestorContact, LeadStatus, ResearchFinding, SourcedLead
from store import Store

SAMPLE_DOC = Path(__file__).parent.parent / "sample_docs" / "acme_robotics_fact_sheet.pdf"


def _client_for(db_path):
    def override_get_store():
        with Store(db_path) as s:
            yield s

    app.dependency_overrides[deps.get_store] = override_get_store
    app.dependency_overrides[deps.get_tenant_id] = lambda: TENANT
    app.dependency_overrides[deps.get_reviewer] = lambda: "alice"
    return TestClient(app)


# --- Deals: create / mandate / audit-log -----------------------------------

def test_create_deal_and_sign_mandate(tmp_path):
    db_path = tmp_path / "test.db"
    client = _client_for(db_path)

    r = client.post("/api/deals", json={"name": "Acme Robotics", "stage": "Series A"})
    assert r.status_code == 200
    deal_id = r.json()["id"]
    assert r.json()["status"] == "new"

    r = client.post(f"/api/deals/{deal_id}/mandate", json={
        "mandate_type": "sell_side_advisory", "terms_summary": "2% fee, 90-day exclusivity",
    })
    assert r.status_code == 200
    assert r.json()["status"] == "mandate_signed"
    assert r.json()["mandate_type"] == "sell_side_advisory"


def test_sign_mandate_404_for_unknown_deal(tmp_path):
    client = _client_for(tmp_path / "test.db")
    r = client.post("/api/deals/does-not-exist/mandate", json={
        "mandate_type": "sell_side_advisory", "terms_summary": "x",
    })
    assert r.status_code == 404


def test_list_source_documents_returns_blocks_for_citation_lookup(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    import api.routers.deals as deals_router
    monkeypatch.setattr(deals_router, "UPLOAD_ROOT", tmp_path / "uploads")

    client = _client_for(db_path)
    with open(SAMPLE_DOC, "rb") as f:
        client.post(
            f"/api/deals/{deal.id}/documents",
            files={"file": ("acme_robotics_fact_sheet.pdf", f, "application/pdf")},
        )

    r = client.get(f"/api/deals/{deal.id}/source-documents")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "acme_robotics_fact_sheet.pdf"
    assert len(docs[0]["blocks"]) == 7  # matches the live-verified block count from earlier milestones
    assert all("id" in b and "page" in b and "content" in b for b in docs[0]["blocks"])


def test_upload_document_ingests_and_advances_status(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    # Uploaded files land under the real project's uploads/ dir by default --
    # redirect that to tmp_path for this test so it doesn't litter the repo.
    import api.routers.deals as deals_router
    monkeypatch.setattr(deals_router, "UPLOAD_ROOT", tmp_path / "uploads")

    client = _client_for(db_path)
    with open(SAMPLE_DOC, "rb") as f:
        r = client.post(
            f"/api/deals/{deal.id}/documents",
            files={"file": ("acme_robotics_fact_sheet.pdf", f, "application/pdf")},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "ingested"
    assert len(r.json()["document_ids"]) == 1
    # Saved under a fresh per-upload subdirectory, not directly at
    # uploads/{deal_id}/{filename} -- see api/routers/deals.py's
    # upload_document docstring comment on the filename-collision bug this
    # avoids. The original filename is still the leaf name, one level down.
    matches = list((tmp_path / "uploads" / deal.id).glob("*/acme_robotics_fact_sheet.pdf"))
    assert len(matches) == 1


def test_upload_document_rejects_unsupported_extension(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    import api.routers.deals as deals_router
    monkeypatch.setattr(deals_router, "UPLOAD_ROOT", tmp_path / "uploads")

    client = _client_for(db_path)
    r = client.post(
        f"/api/deals/{deal.id}/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_audit_log_reflects_field_decisions(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
    store.save_extraction_result(result)
    store.close()

    client = _client_for(db_path)
    client.post(f"/api/deals/{deal.id}/review/fields/arr", json={"decision": "approve"})

    r = client.get(f"/api/deals/{deal.id}/audit-log")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["action"] == "approve"
    assert r.json()[0]["target_id"] == "arr"


# --- Review decision endpoints ----------------------------------------------

def test_decide_field_approve_persists_and_recomputes_status(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
    store.save_extraction_result(result)
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/review/fields/arr", json={"decision": "approve"})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"]["resolved"] is True
    assert body["extraction_result"]["arr"]["status"] == "approved"
    assert body["extraction_result"]["arr"]["reviewer"] == "alice"
    # Not every field is resolved yet -- deal shouldn't be REVIEWED.
    assert body["deal"]["status"] == "needs_manual_input"


def test_decide_field_bad_edit_value_returns_graceful_message_not_500(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
    store.save_extraction_result(result)
    store.close()

    client = _client_for(db_path)
    r = client.post(
        f"/api/deals/{deal.id}/review/fields/arr",
        json={"decision": "edit", "new_value": "not-a-number"},
    )
    assert r.status_code == 200  # graceful, never a 500 -- the Milestone 1 crash fix, over HTTP
    body = r.json()
    assert body["outcome"]["resolved"] is False
    assert "isn't a number" in body["outcome"]["message"]
    assert body["extraction_result"]["arr"]["value"] == 2_400_000


def test_decide_field_unknown_field_404(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
    store.save_extraction_result(result)
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/review/fields/not_a_real_field", json={"decision": "approve"})
    assert r.status_code == 404


def test_decide_field_no_extraction_result_404(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/review/fields/arr", json={"decision": "approve"})
    assert r.status_code == 404


def test_decide_cap_table_empty_auto_acknowledges(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
    store.save_extraction_result(result)
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/review/cap-table", json={"decision": "approve"})
    assert r.status_code == 200
    assert r.json()["extraction_result"]["cap_table_status"] == "not_found"


def test_decide_funding_history_unknown_decision_400(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    from schemas import FundingRound
    result = make_extraction_result(
        tenant_id=TENANT, deal_id=deal.id,
        funding_history=[FundingRound(round_name="Seed", amount=1_500_000, source_block_id="blk_3")],
    )
    store.save_extraction_result(result)
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/review/funding-history", json={"decision": "acknowledge"})
    assert r.status_code == 400


def test_full_review_pass_reaches_ready_for_compilation_over_http(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
    store.save_extraction_result(result)
    store.close()

    client = _client_for(db_path)
    for name in ("arr", "arr_prior_year", "burn_monthly", "cash_on_hand", "runway_months", "headcount"):
        r = client.post(f"/api/deals/{deal.id}/review/fields/{name}", json={"decision": "approve"})
        assert r.status_code == 200
    for name in ("mrr", "growth_rate_yoy"):
        r = client.post(f"/api/deals/{deal.id}/review/fields/{name}", json={"decision": "acknowledge"})
        assert r.status_code == 200
    client.post(f"/api/deals/{deal.id}/review/cap-table", json={"decision": "approve"})
    r = client.post(f"/api/deals/{deal.id}/review/funding-history", json={"decision": "approve"})

    assert r.json()["deal"]["status"] == "reviewed"
    review = client.get(f"/api/deals/{deal.id}/review").json()
    assert review["ready_for_compilation"] is True


# --- Leads -------------------------------------------------------------

def test_lead_decision_and_promote(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    lead = SourcedLead(tenant_id=TENANT, company_name="Acme")
    store.save_lead(lead)
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/leads/{lead.id}/decision", json={"decision": "keep"})
    assert r.status_code == 200
    assert r.json()["status"] == "reviewed"

    r = client.post(f"/api/leads/{lead.id}/promote", json={})
    assert r.status_code == 200
    assert r.json()["name"] == "Acme"
    assert r.json()["status"] == "new"

    r = client.get(f"/api/leads/{lead.id}")
    assert r.json()["status"] == "promoted_to_deal"


def test_lead_decision_invalid_value_400(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    lead = SourcedLead(tenant_id=TENANT, company_name="Acme")
    store.save_lead(lead)
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/leads/{lead.id}/decision", json={"decision": "maybe"})
    assert r.status_code == 400


def test_list_leads_filters_by_status(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    store.save_lead(SourcedLead(tenant_id=TENANT, company_name="Acme"))
    store.save_lead(SourcedLead(tenant_id=TENANT, company_name="Beta", status=LeadStatus.DISMISSED))
    store.close()

    client = _client_for(db_path)
    assert len(client.get("/api/leads").json()) == 2
    assert len(client.get("/api/leads", params={"status": "dismissed"}).json()) == 1


# --- Research ------------------------------------------------------------

def test_research_finding_decision_and_mark_reviewed(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    finding = ResearchFinding(
        tenant_id=TENANT, deal_id=deal.id, topic="oss_traction", content="...", source_type="github",
    )
    store.save_research_findings([finding])
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/research/{finding.id}/decision", json={"decision": "approve"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    r = client.get(f"/api/deals/{deal.id}/research")
    assert len(r.json()) == 1
    assert r.json()[0]["status"] == "approved"

    r = client.post(f"/api/deals/{deal.id}/research/mark-reviewed")
    assert r.status_code == 200
    assert r.json()["status"] == "research_reviewed"


def test_research_finding_decision_404_unknown_finding(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/research/does-not-exist/decision", json={"decision": "approve"})
    assert r.status_code == 404


# --- Investors -------------------------------------------------------------

def test_add_and_list_investors(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/investors", json={
        "investor_name": "Jane Doe", "firm": "Example Capital", "interest_level": "warm",
    })
    assert r.status_code == 200
    assert r.json()["investor_name"] == "Jane Doe"

    r = client.get(f"/api/deals/{deal.id}/investors")
    assert len(r.json()) == 1
    assert r.json()[0]["firm"] == "Example Capital"


# --- Prompt / directive preview --------------------------------------------

def test_directive_preview_plain_continue_uses_deterministic_default(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    client = _client_for(db_path)
    r = client.post(f"/api/deals/{deal.id}/directive/preview", json={"directive": "continue"})
    assert r.status_code == 200
    assert r.json()["action"] == "sign_mandate"  # DEFAULT_ACTION[DealStatus.NEW]


def test_directive_preview_404_unknown_deal(tmp_path):
    client = _client_for(tmp_path / "test.db")
    r = client.post("/api/deals/does-not-exist/directive/preview", json={"directive": "continue"})
    assert r.status_code == 404
