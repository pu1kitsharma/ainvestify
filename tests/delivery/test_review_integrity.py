"""Synthetic byte/identity gates; these are not professional signoffs."""
from datetime import date
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from delivery.compliance import QualifiedFinancialOwner
from delivery.review_integrity import (BoundEvidenceInventory, financial_reviewer_grants,
    retained_official_sources, room_evidence_inventory)
from tests.delivery.test_compliance import complete, assess, digest
from tests.api.test_authentication import secured, sign_in


@pytest.fixture
def archive(tmp_path):
    root = tmp_path
    folder = root / "runtime_qualification/regulatory_sources/synthetic"
    folder.mkdir(parents=True)
    body = folder / "official.bin"
    body.write_bytes(b"Synthetic official source, not an actual law")
    sha = hashlib.sha256(body.read_bytes()).hexdigest()
    url = "https://authority.example/rule"
    rel = body.relative_to(root).as_posix()
    receipt = folder / "receipt.json"
    receipt.write_text(json.dumps({"contract": "official-source-byte-receipt-v1",
        "reference_id": "synthetic", "requested_url": url, "resolved_url": url,
        "response_body_path": rel, "source_sha256": sha, "response_body_sha256": sha,
        "byte_length": body.stat().st_size, "http_status": 200,
        "fetch_status": "source_bytes_retained"}))
    item = {"reference_id": "synthetic", "official_url": url, "host": "authority.example",
        "fetch_status": "source_bytes_retained", "source_bytes_path": rel,
        "source_sha256": sha, "source_byte_length": body.stat().st_size,
        "retrieval_receipts": [{"receipt_path": receipt.relative_to(root).as_posix(),
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}]}
    register = root / "register.json"
    register.write_text(json.dumps({"contract": "official-regulatory-reference-v1", "sources": [item]}))
    return root, register, body, receipt, item


def test_source_body_and_receipt_are_rehashed_without_approving_law(archive):
    root, register, body, _, item = archive
    sources = retained_official_sources(register, root)
    assert sources[item["official_url"]].source_sha256 == hashlib.sha256(body.read_bytes()).hexdigest()
    assert not hasattr(sources[item["official_url"]], "applicability")
    body.write_bytes(b"Changed original")
    assert retained_official_sources(register, root) == {}


@pytest.mark.parametrize("mutation", ["missing_body", "changed_receipt", "borrowed_url", "borrowed_reference",
    "parent_escape", "absolute_path", "symlink_file", "symlink_directory", "symlink_archive_parent"])
def test_source_receipt_or_path_mutations_fail_closed(archive, mutation):
    root, register, body, receipt, item = archive
    if mutation == "missing_body":
        body.unlink()
    elif mutation == "changed_receipt":
        receipt.write_text("{}")
    elif mutation in {"borrowed_url", "borrowed_reference"}:
        record = json.loads(receipt.read_text())
        record["requested_url" if mutation == "borrowed_url" else "reference_id"] = "borrowed"
        receipt.write_text(json.dumps(record))
        item["retrieval_receipts"][0]["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    elif mutation == "parent_escape":
        item["source_bytes_path"] = "runtime_qualification/regulatory_sources/../../../borrowed.bin"
    elif mutation == "absolute_path":
        item["source_bytes_path"] = str(body)
    elif mutation == "symlink_file":
        target = root / "outside.bin"
        target.write_bytes(body.read_bytes())
        body.unlink()
        body.symlink_to(target)
    elif mutation == "symlink_directory":
        folder = body.parent
        renamed = folder.with_name("moved")
        folder.rename(renamed)
        folder.symlink_to(renamed, target_is_directory=True)
    else:
        folder = root / "runtime_qualification"
        renamed = root / "moved_archive"
        folder.rename(renamed)
        folder.symlink_to(renamed, target_is_directory=True)
    register.write_text(json.dumps({"contract": "official-regulatory-reference-v1", "sources": [item]}))
    assert retained_official_sources(register, root) == {}


def test_declared_rule_hash_and_official_host_are_insufficient(complete):
    result = assess(complete, official_source_snapshots={})
    assert "compliance_source_bytes_unavailable:fixture-rule" in result.blockers
    snapshot = next(iter(complete["official_source_snapshots"].values()))
    from dataclasses import replace
    result = assess(complete, official_source_snapshots={snapshot.source_url:
        replace(snapshot, source_sha256=digest("changed original"))})
    assert "compliance_source_bytes_mismatch:fixture-rule" in result.blockers


@pytest.mark.parametrize("mutation", ["missing", "borrowed_revision", "missing_id"])
def test_scope_and_rule_ids_need_exact_bound_inventory(complete, mutation):
    inventory = complete["evidence_inventory"]
    if mutation == "missing":
        inventory = None
    elif mutation == "borrowed_revision":
        inventory = BoundEvidenceInventory(inventory.tenant_id, inventory.workspace_id,
                                           digest("another revision"), inventory.evidence)
    else:
        inventory = BoundEvidenceInventory(inventory.tenant_id, inventory.workspace_id,
                                           inventory.evidence_revision, {})
    result = assess(complete, evidence_inventory=inventory)
    assert result.status == "blocked"
    if mutation == "missing_id":
        assert "compliance_scope_evidence_unresolved" in result.blockers
        assert "compliance_rule_evidence_unresolved:fixture-rule" in result.blockers
    else:
        assert "compliance_evidence_inventory_unavailable" in result.blockers


def test_retained_private_blocks_bind_actual_originals_and_scope(tmp_path, monkeypatch):
    from schemas import DocBlock, Document
    from delivery.storage import scope_component
    upload_root = tmp_path / "uploads"
    folder = upload_root / scope_component("tenant1") / scope_component("deal1")
    folder.mkdir(parents=True)
    monkeypatch.setattr("api.routers.deals.UPLOAD_ROOT", upload_root)
    original = folder / "original.pdf"
    original.write_bytes(b"Synthetic original bytes")
    document = Document(id="doc1", tenant_id="tenant1", deal_id="deal1", filename="fixture.pdf",
        type="pdf", storage_uri=str(original), blocks=[DocBlock(id="block1", document_id="doc1",
        page=1, block_type="text", coordinates={}, content="Synthetic retained block")])
    profile = SimpleNamespace(tenant_id="tenant1", provenance={}, evidence=[])
    lead = SimpleNamespace(tenant_id="tenant1", company_profile=profile)
    room = SimpleNamespace(tenant_id="tenant1", id="room1", lead_id="lead1", deal_id="deal1")
    store = SimpleNamespace(get_lead=lambda *_: lead, get_documents_for_deal=lambda *_: [document])
    monkeypatch.setattr("api.routers.rooms.revision_for", lambda *_: digest("revision"))
    resolved = room_evidence_inventory(store, "tenant1", room, digest("revision"))
    assert resolved.evidence["block1"] == resolved.evidence["private://doc1/block1"]
    original.write_bytes(b"Changed original bytes")
    changed = room_evidence_inventory(store, "tenant1", room, digest("revision"))
    assert changed.evidence["block1"] != resolved.evidence["block1"]
    assert room_evidence_inventory(store, "tenant2", room, digest("revision")) is None
    assert room_evidence_inventory(store, "tenant1", room, digest("borrowed revision")) is None
    path = document.storage_uri
    document.storage_uri = str(tmp_path / "borrowed.pdf")
    (tmp_path / "borrowed.pdf").write_bytes(original.read_bytes())
    assert room_evidence_inventory(store, "tenant1", room, digest("revision")) is None
    document.storage_uri = path
    document.tenant_id = "tenant2"
    assert room_evidence_inventory(store, "tenant1", room, digest("revision")) is None


def test_scoped_upload_parent_symlink_cannot_borrow_originals(tmp_path, monkeypatch):
    from schemas import DocBlock, Document
    from delivery.storage import scope_component
    upload_root = tmp_path / "uploads"
    tenant_folder = upload_root / scope_component("tenant1")
    outside = tmp_path / "outside"
    outside.mkdir()
    folder = outside / scope_component("deal1")
    folder.mkdir()
    original = folder / "original.pdf"
    original.write_bytes(b"Borrowed bytes")
    upload_root.mkdir()
    tenant_folder.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr("api.routers.deals.UPLOAD_ROOT", upload_root)
    document = Document(id="doc1", tenant_id="tenant1", deal_id="deal1", filename="fixture.pdf",
        type="pdf", storage_uri=str(tenant_folder / scope_component("deal1") / "original.pdf"),
        blocks=[DocBlock(id="block1", document_id="doc1", page=1, block_type="text",
                         coordinates={}, content="Borrowed retained block")])
    lead = SimpleNamespace(tenant_id="tenant1", company_profile=SimpleNamespace(
        tenant_id="tenant1", provenance={}, evidence=[]))
    room = SimpleNamespace(tenant_id="tenant1", id="room1", lead_id="lead1", deal_id="deal1")
    store = SimpleNamespace(get_lead=lambda *_: lead, get_documents_for_deal=lambda *_: [document])
    monkeypatch.setattr("api.routers.rooms.revision_for", lambda *_: digest("revision"))
    assert room_evidence_inventory(store, "tenant1", room, digest("revision")) is None
    document.tenant_id = "tenant1"
    original.unlink()
    assert room_evidence_inventory(store, "tenant1", room, digest("revision")) is None


def test_db_quote_without_retained_original_does_not_resolve(tmp_path, monkeypatch):
    from schemas import CompanyEvidence
    profile = SimpleNamespace(tenant_id="tenant1", provenance={}, evidence=[CompanyEvidence(
        id="borrowed-id", field="fixture", value="fixture", quote="Unverified copied quote",
        source_url="https://fixture.example/source")])
    lead = SimpleNamespace(tenant_id="tenant1", company_profile=profile)
    room = SimpleNamespace(tenant_id="tenant1", id="room1", lead_id="lead1", deal_id=None)
    store = SimpleNamespace(get_lead=lambda *_: lead)
    monkeypatch.setattr("api.routers.rooms.revision_for", lambda *_: digest("revision"))
    assert room_evidence_inventory(store, "tenant1", room, digest("revision")).evidence == {}


def financial_database(complete):
    from security.identity import SCHEMA
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    owner = QualifiedFinancialOwner.model_validate(
        complete["qualified_owners"]["fixture-human"].model_dump())
    conn.execute("INSERT INTO auth_users(id) VALUES (?)", (owner.reviewer_id,))
    conn.execute("INSERT INTO auth_memberships VALUES (?,?,?,1)", ("fixture-tenant", owner.reviewer_id, "financial"))
    conn.execute("INSERT INTO auth_reviewer_qualifications VALUES (?,?,?, ?,1)",
        ("fixture-tenant", owner.reviewer_id, "financial", owner.model_dump_json()))
    return conn, owner


@pytest.mark.parametrize("mutation", [None, "role_only", "disabled", "revoked", "malformed", "wrong_tenant"])
def test_financial_professional_authority_is_server_derived(complete, mutation):
    conn, owner = financial_database(complete)
    tenant = "fixture-tenant"
    if mutation == "role_only":
        conn.execute("DELETE FROM auth_reviewer_qualifications")
    elif mutation == "disabled":
        conn.execute("UPDATE auth_users SET disabled=1")
    elif mutation == "revoked":
        conn.execute("UPDATE auth_reviewer_qualifications SET active=0")
    elif mutation == "malformed":
        conn.execute("UPDATE auth_reviewer_qualifications SET qualification='{}'")
    elif mutation == "wrong_tenant":
        tenant = "another-tenant"
    grants = financial_reviewer_grants(conn, tenant, complete["scope"], date(2026, 10, 10))
    assert grants == ({owner.reviewer_id} if mutation is None else set())
    conn.close()


@pytest.mark.parametrize("changes", [{"jurisdictions": ["US"]}, {"activities": ["internal_diligence"]},
    {"valid_until": "2026-10-09"}, {"valid_from": "2026-10-11"}, {"reviewer_id": "borrowed-human"}])
def test_financial_professional_scope_and_expiry_cannot_be_borrowed(complete, changes):
    conn, owner = financial_database(complete)
    payload = {**owner.model_dump(mode="json"), **changes}
    conn.execute("UPDATE auth_reviewer_qualifications SET qualification=?", (json.dumps(payload),))
    assert financial_reviewer_grants(conn, "fixture-tenant", complete["scope"], date(2026, 10, 10)) == set()
    conn.close()


@pytest.mark.parametrize("reviewed_on", [date(2025, 12, 31), date(2026, 10, 11)])
def test_financial_approval_cannot_predate_professional_grant_or_be_future_dated(complete, reviewed_on):
    conn, _ = financial_database(complete)
    assert financial_reviewer_grants(conn, "fixture-tenant", complete["scope"],
        date(2026, 10, 10), reviewed_on=reviewed_on) == set()
    conn.close()


def test_financial_review_date_is_additive_and_historical_record_stays_undated():
    from delivery.contracts import ReviewDecision
    legacy = {"role": "financial", "reviewer_id": "fixture-human",
              "manifest_digest": digest("manifest"), "decision": "approved"}
    unchanged = json.dumps(legacy, sort_keys=True)
    review = ReviewDecision.model_validate(legacy)
    assert review.reviewed_on is None
    assert json.dumps(legacy, sort_keys=True) == unchanged
    dated = ReviewDecision.model_validate({**legacy, "reviewed_on": "2026-10-10"})
    assert dated.reviewed_on == date(2026, 10, 10)


def test_production_undated_financial_approval_cannot_gain_authority_later(
        complete, secured, monkeypatch):
    from api.routers.rooms import revision_for
    from delivery.compliance import ComplianceReviewRecord
    from delivery.release import evaluate_package, load_package, validate_room
    from store import Store

    client, db, users = secured
    sign_in(client, users[0])
    created = client.post("/api/rooms", json={"name": "Synthetic financial reviewer fixture",
        "website": "https://fixture.example", "mandate_type": "fundraising_advisory",
        "terms_summary": "Synthetic engagement terms"})
    assert created.status_code == 201
    tenant, room_id = users[0][1], created.json()["workspace_id"]
    monkeypatch.setattr("delivery.release.datetime", type("FixedClock", (), {
        "now": staticmethod(lambda _: __import__("datetime").datetime(2026, 10, 10))}))
    with Store(db) as store:
        room = store.get_workspace(tenant, workspace_id=room_id)
        scope = complete["scope"].model_copy(update={"transaction_evidence_revision": revision_for(store, room)})
        room.compliance_review = ComplianceReviewRecord(scope=scope)
        store.save_workspace(room, expected_revision=room.revision)
        package_id, _ = validate_room(store, tenant, room)
        manifest, _, _, _ = load_package(store, tenant, package_id)
        owner = QualifiedFinancialOwner.model_validate(complete["qualified_owners"]["fixture-human"].model_dump())
        store.conn.execute("INSERT INTO auth_users(id) VALUES (?)", (owner.reviewer_id,))
        store.conn.execute("INSERT INTO auth_memberships VALUES (?,?,?,1)", (tenant, owner.reviewer_id, "financial"))
        store.conn.execute("INSERT INTO auth_reviewer_qualifications VALUES (?,?,?, ?,1)",
            (tenant, owner.reviewer_id, "financial", owner.model_dump_json()))
        legacy = {"role": "financial", "reviewer_id": owner.reviewer_id,
                  "manifest_digest": manifest.digest(), "decision": "approved"}
        stored = json.dumps([legacy])
        store.conn.execute("UPDATE room_packages SET reviews=? WHERE id=?", (stored, package_id))
        store.conn.commit()
        result = evaluate_package(store, tenant, package_id)
        assert "financial_review_date_missing_or_invalid" in result.blockers
        assert store.conn.execute("SELECT reviews FROM room_packages WHERE id=?", (package_id,)).fetchone()[0] == stored
        legacy["reviewed_on"] = "2026-10-10"
        store.conn.execute("UPDATE room_packages SET reviews=? WHERE id=?", (json.dumps([legacy]), package_id))
        store.conn.commit()
        result = evaluate_package(store, tenant, package_id)
        assert "financial_review_date_missing_or_invalid" not in result.blockers
        assert "financial_owner_unqualified_for_scope" not in result.blockers
        assert not result.eligible_for_release  # Required files/evidence/compliance are still missing.
        store.conn.execute("UPDATE auth_reviewer_qualifications SET active=0 WHERE user_id=?", (owner.reviewer_id,))
        store.conn.commit()
        assert "financial_owner_unqualified_for_scope" in evaluate_package(store, tenant, package_id).blockers


def test_missing_trusted_snapshots_do_not_change_existing_signature_digests(complete):
    scope_digest, matrix_digest = complete["scope"].digest(), complete["matrix"].digest()
    result = assess(complete, official_source_snapshots=None, evidence_inventory=None)
    assert result.status == "blocked"
    assert result.verification_contract == "compliance-source-evidence-v2"
    assert (complete["scope"].digest(), complete["matrix"].digest()) == (scope_digest, matrix_digest)
