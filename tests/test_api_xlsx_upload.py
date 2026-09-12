"""
Coverage for the gap identified after the Milestone 1-4 check-in: the
document-upload endpoint's unsupported-extension *rejection* was tested,
but a real .xlsx was never actually uploaded and ingested through the API
-- agents/ingestion_agent.ingest_excel has its own parsing logic distinct
from the PDF path (row-by-row via openpyxl, sheet+row as the citation
instead of page number) and had no API-level coverage at all.
"""
import openpyxl
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


def _build_sample_xlsx(path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Financials"
    ws.append(["Metric", "Value"])
    ws.append(["ARR", 2_400_000])
    ws.append(["Monthly Burn", 180_000])
    wb.save(path)


def test_upload_xlsx_document_ingests_via_excel_parser(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    import api.routers.deals as deals_router
    monkeypatch.setattr(deals_router, "UPLOAD_ROOT", tmp_path / "uploads")

    xlsx_path = tmp_path / "financials.xlsx"
    _build_sample_xlsx(xlsx_path)

    client = _client_for(db_path)
    with open(xlsx_path, "rb") as f:
        r = client.post(
            f"/api/deals/{deal.id}/documents",
            files={"file": ("financials.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ingested"
    assert len(body["document_ids"]) == 1

    store = Store(db_path)
    documents = store.get_documents_for_deal(TENANT, deal.id)
    store.close()
    assert len(documents) == 1
    assert documents[0].type == "xlsx"
    assert len(documents[0].blocks) == 3  # header row + 2 data rows
    assert documents[0].blocks[0].coordinates["sheet"] == "Financials"
