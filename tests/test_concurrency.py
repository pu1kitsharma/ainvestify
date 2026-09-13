"""
Coverage for gap 8, previously deferred as "disproportionate for Phase 0
single-user local usage" -- the user asked for it explicitly, so this
proves the backend behaves correctly under real concurrent load, not just
sequential requests one at a time.

Two things are tested:
1. Realistic concurrency: multiple different deals being worked on at once
   (several analysts, or one analyst with several browser tabs) -- this is
   the scenario store.py's WAL + busy_timeout change (Store.__init__) and
   api/main.py's explicit thread-pool sizing (lifespan) target.
2. The one real data-loss race found while auditing the backend for this:
   concurrent document uploads to the SAME deal used to silently drop one
   upload's document_id (a plain get_deal()+save_deal() read-modify-write).
   Fixed via Store.update_deal()'s atomic BEGIN IMMEDIATE transaction; this
   test drives real concurrent HTTP requests against a real uvicorn server
   (not TestClient's single-threaded-by-default dispatch) to prove it holds
   under genuine parallelism, not just sequential calls that happen to not
   race.
"""
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
import requests
from conftest import TENANT, make_extraction_result
from fastapi.testclient import TestClient

import api.deps as deps
from agents.planner_agent import start_deal
from api.main import app
from schemas import DealStatus
from store import Store

SAMPLE_DOC = Path(__file__).parent.parent / "sample_docs" / "acme_robotics_fact_sheet.pdf"


def _client_for(db_path):
    def override_get_store():
        with Store(db_path) as s:
            yield s

    app.dependency_overrides[deps.get_store] = override_get_store
    app.dependency_overrides[deps.get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_concurrent_requests_across_different_deals_all_succeed(tmp_path):
    """Simulates several analysts (or tabs) working different deals at
    once. Every request must succeed -- none should hit sqlite3's
    "database is locked" under real thread-pool concurrency."""
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal_ids = []
    for i in range(10):
        deal = start_deal(store, TENANT, f"Deal {i}")
        result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
        store.save_extraction_result(result)
        deal_ids.append(deal.id)
    store.close()

    client = _client_for(db_path)

    def approve_a_field(deal_id):
        return client.post(f"/api/deals/{deal_id}/review/fields/arr", json={"decision": "approve"})

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(approve_a_field, d) for d in deal_ids]
        responses = [f.result() for f in as_completed(futures)]

    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]

    store = Store(db_path)
    for deal_id in deal_ids:
        result = store.get_extraction_result(TENANT, deal_id)
        assert result.arr.status.value == "approved"
    store.close()


def test_concurrent_field_decisions_on_same_deal_never_silently_lose_one(tmp_path):
    """The second real race this pass found: two review decisions on the
    SAME deal's extraction result (even on two different fields) racing a
    plain get+mutate+save would let whichever save() commits second
    silently discard the first decision. Fixed via
    Store.save_extraction_result_if_unchanged's compare-and-swap (not a
    held write lock, since a reject decision can trigger a real multi-
    minute Ollama call -- see api/routers/review.py's _persist_and_respond
    docstring comment). A CAS conflict surfaces as 409, not data loss, so
    this fires many concurrent decisions and asserts every field that
    *did* land recorded correctly, and that none vanished silently: the
    number of 200s plus the number of 409s must account for every request,
    and every approved field must show up as approved with an audit event."""
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    result = make_extraction_result(tenant_id=TENANT, deal_id=deal.id)
    store.save_extraction_result(result)
    store.close()

    client = _client_for(db_path)
    fields = ["arr", "arr_prior_year", "burn_monthly", "cash_on_hand", "runway_months", "headcount"]

    def approve(field):
        return field, client.post(f"/api/deals/{deal.id}/review/fields/{field}", json={"decision": "approve"})

    with ThreadPoolExecutor(max_workers=len(fields)) as pool:
        futures = [pool.submit(approve, f) for f in fields]
        results = [f.result() for f in as_completed(futures)]

    statuses = [r.status_code for _, r in results]
    assert all(s in (200, 409) for s in statuses), statuses
    succeeded = {field for field, r in results if r.status_code == 200}

    store = Store(db_path)
    final_result = store.get_extraction_result(TENANT, deal.id)
    audit = store.get_audit_log(TENANT, deal.id)
    store.close()

    # Every decision the API said succeeded must actually be reflected --
    # this is the actual regression check: before the CAS fix, some subset
    # of these would report 200 but the field would still show "proposed"
    # because a concurrent save() had clobbered it right after.
    for field in succeeded:
        assert getattr(final_result, field).status.value == "approved", field
    approve_events = [e for e in audit if e.action == "approve"]
    assert len(approve_events) == len(succeeded)
    assert {e.target_id for e in approve_events} == succeeded


def test_concurrent_document_uploads_to_same_deal_lose_no_document_id(tmp_path):
    """The real race this pass found: two concurrent uploads to the SAME
    deal each read document_ids=[], each append their own id, and without
    Store.update_deal's atomic transaction, whichever save_deal() commits
    second silently overwrites the other's append. Runs against a real
    uvicorn process (not TestClient) since TestClient's transport can
    serialize requests in ways that wouldn't actually exercise the race
    the fix targets.
    """
    db_path = tmp_path / "test.db"
    upload_dir = tmp_path / "uploads"
    store = Store(db_path)
    deal = start_deal(store, TENANT, "Acme Robotics")
    store.close()

    port = 8799
    env_script = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(Path(__file__).parent.parent)!r})
import api.deps as deps
import api.routers.deals as deals_router
from api.main import app
from store import Store

deals_router.UPLOAD_ROOT = Path({str(upload_dir)!r})

def override_get_store():
    with Store({str(db_path)!r}) as s:
        yield s

app.dependency_overrides[deps.get_store] = override_get_store
app.dependency_overrides[deps.get_tenant_id] = lambda: {TENANT!r}

import uvicorn
uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
"""
    script_path = tmp_path / "server.py"
    script_path.write_text(env_script)
    server_log = open(tmp_path / "server.log", "w")
    proc = subprocess.Popen([sys.executable, str(script_path)], stdout=server_log, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                if requests.get(f"http://127.0.0.1:{port}/api/health", timeout=0.5).status_code == 200:
                    break
            except requests.exceptions.ConnectionError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("server never came up")

        def upload(n):
            dest = tmp_path / f"copy_{n}.pdf"
            shutil.copy(SAMPLE_DOC, dest)
            with open(dest, "rb") as f:
                return requests.post(
                    f"http://127.0.0.1:{port}/api/deals/{deal.id}/documents",
                    files={"file": (f"doc_{n}.pdf", f, "application/pdf")},
                    timeout=30,
                )

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(upload, n) for n in range(5)]
            responses = [f.result() for f in as_completed(futures)]

        assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    store = Store(db_path)
    documents = store.get_documents_for_deal(TENANT, deal.id)
    persisted_deal = store.get_deal(TENANT, deal.id)
    store.close()

    assert len(documents) == 5, f"expected 5 documents in the documents table, found {len(documents)}"
    assert len(persisted_deal.document_ids) == 5, (
        f"expected all 5 uploads' ids on the deal, found {len(persisted_deal.document_ids)} -- "
        "this is exactly the race Store.update_deal's atomic transaction fixes"
    )
    assert len(set(persisted_deal.document_ids)) == 5  # no duplicates either
