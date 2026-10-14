"""Synthetic scope/revision gates, not regulatory or legal acceptance."""
from datetime import date
import hashlib
import json
import sqlite3

import pytest
from pydantic import ValidationError

from delivery.compliance import (ApplicabilityMatrix, ComplianceReviewRecord, ComplianceScope,
    ComplianceSignoff, QualifiedComplianceOwner, RegulatoryRule, RuleReview,
    assess_compliance, official_source_hosts, qualified_compliance_owners)
from tests.api.test_authentication import secured, sign_in
from delivery.review_integrity import BoundEvidenceInventory, RetainedOfficialSource


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def complete():
    scope = ComplianceScope(jurisdictions=("IN",), activity="private_fundraising",
        issuer_form="fixture-private-company", instrument="fixture-equity",
        investor_residency="domestic", sector="fixture-sector", regulated_activities=(),
        audience="identified_investors", transaction_evidence_revision=digest("evidence"),
        evidence_ids=("fixture-transaction",), unresolved_fields=())
    rule = RegulatoryRule(rule_id="fixture-rule", version="fixture-v1", jurisdiction="IN",
        reference="Synthetic requirement, not an actual law", source_url="https://authority.example/rule",
        source_sha256=digest("synthetic official snapshot"), effective_from=date(2026, 1, 1),
        verified_on=date(2026, 10, 1), valid_until=date(2026, 10, 31))
    review = RuleReview(rule_id=rule.rule_id, rule_version=rule.version, applicability="applies",
        source_sha256=rule.source_sha256,
        reason="Synthetic reviewed transaction evidence", evidence_status="satisfied",
        evidence_ids=("fixture-transaction",), coverage_complete=True)
    matrix = ApplicabilityMatrix(scope_digest=scope.digest(), rules=(rule,), reviews=(review,),
        scope_coverage_complete=True)
    owner = QualifiedComplianceOwner(reviewer_id="fixture-human", reviewer_kind="qualified_human",
        authority_record_id="fixture-verified-authority", jurisdictions=("IN",),
        activities=("private_fundraising",), valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31))
    signoff = ComplianceSignoff(reviewer_id=owner.reviewer_id, manifest_digest=digest("manifest"),
        scope_digest=scope.digest(), matrix_digest=matrix.digest(), decision="approved",
        reviewed_on=date(2026, 10, 1))
    return dict(manifest_digest=digest("manifest"), evidence_revision=digest("evidence"),
        scope=scope, matrix=matrix, signoff=signoff, qualified_owners={owner.reviewer_id: owner},
        official_source_snapshots={rule.source_url: RetainedOfficialSource("synthetic", rule.source_url,
            rule.source_sha256, len("synthetic official snapshot"), digest("synthetic receipt"))},
        evidence_inventory=BoundEvidenceInventory("fixture-tenant", "fixture-room", digest("evidence"),
                                                  {"fixture-transaction": digest("retained evidence")}),
        official_source_hosts={"authority.example"}, as_of=date(2026, 10, 10))


def assess(complete, **changes):
    return assess_compliance(**{**complete, **changes})


def changed_review(complete, **changes):
    matrix = complete["matrix"]
    return matrix.model_copy(update={"reviews": (matrix.reviews[0].model_copy(update=changes),)})


def test_exact_scoped_human_approval_is_not_a_general_release(complete):
    result = assess(complete)
    assert result.status == "approved_for_declared_scope"
    assert result.blockers == ()
    assert "release" not in type(result).model_fields
    assert "declared scope" in result.summary


def test_private_review_revision_excludes_signoff_but_binds_scope_and_rules(complete):
    record = ComplianceReviewRecord(scope=complete["scope"], matrix=complete["matrix"],
        signoff=complete["signoff"])
    revoked = record.model_copy(update={"signoff": complete["signoff"].model_copy(
        update={"decision": "rejected"})})
    assert record.content_revision() == revoked.content_revision()
    changed = record.model_copy(update={"scope": complete["scope"].model_copy(
        update={"instrument": "fixture-convertible"})})
    assert record.content_revision() != changed.content_revision()


@pytest.mark.parametrize("missing, blocker", [
    ("scope", "compliance_scope_missing"), ("matrix", "compliance_matrix_missing"),
    ("signoff", "compliance_qualified_signoff_missing")])
def test_missing_mandatory_review_record_blocks(complete, missing, blocker):
    result = assess(complete, **{missing: None})
    assert result.status == "blocked"
    assert blocker in result.blockers


def test_changed_transaction_scope_and_export_invalidate_signoff(complete):
    scope = complete["scope"].model_copy(update={"investor_residency": "nonresident"})
    result = assess(complete, scope=scope, manifest_digest=digest("changed export"))
    assert "compliance_matrix_stale" in result.blockers
    assert "compliance_signoff_stale" in result.blockers
    assert "compliance_scope_stale" in assess(complete,
        evidence_revision=digest("changed evidence")).blockers


@pytest.mark.parametrize("field, value", [
    ("unresolved_fields", ("instrument",)), ("investor_residency", "unknown")])
def test_unresolved_scope_cannot_be_approved(complete, field, value):
    result = assess(complete, scope=complete["scope"].model_copy(update={field: value}))
    assert "compliance_scope_unresolved" in result.blockers


def test_incomplete_rule_universe_blocks_even_with_human_signoff(complete):
    result = assess(complete, matrix=complete["matrix"].model_copy(
        update={"scope_coverage_complete": False}))
    assert "compliance_rule_coverage_incomplete" in result.blockers


@pytest.mark.parametrize("status", ["missing", "contradicted", "not_run", "not_applicable"])
def test_required_evidence_failures_cannot_be_waived(complete, status):
    result = assess(complete, matrix=changed_review(complete, evidence_status=status))
    assert f"compliance_evidence_{status}:fixture-rule" in result.blockers


def test_unknown_applicability_is_not_an_exclusion(complete):
    result = assess(complete, matrix=changed_review(complete, applicability="undetermined"))
    assert "compliance_applicability_unresolved:fixture-rule" in result.blockers


def test_exclusion_requires_evidence_and_qualified_exact_signoff(complete):
    matrix = changed_review(complete, applicability="not_applicable", evidence_status="not_applicable")
    signoff = complete["signoff"].model_copy(update={"matrix_digest": matrix.digest()})
    assert assess(complete, matrix=matrix, signoff=signoff).status == "approved_for_declared_scope"
    bad = changed_review(complete, applicability="not_applicable", evidence_status="missing")
    assert "compliance_invalid_exclusion:fixture-rule" in assess(complete, matrix=bad).blockers
    no_evidence = changed_review(complete, applicability="not_applicable",
        evidence_status="not_applicable", evidence_ids=())
    assert "compliance_evidence_incomplete:fixture-rule" in assess(complete, matrix=no_evidence).blockers


def test_source_domain_is_authority_configured_not_selected_by_model(complete):
    assert "compliance_source_unverified:fixture-rule" in assess(complete,
        official_source_hosts=set()).blockers


@pytest.mark.parametrize("field, value, blocker", [
    ("verified_on", date(2026, 10, 11), "compliance_rule_stale"),
    ("valid_until", date(2026, 10, 9), "compliance_rule_stale"),
    ("effective_from", date(2026, 10, 11), "compliance_rule_outside_effective_period"),
    ("effective_through", date(2026, 10, 9), "compliance_rule_outside_effective_period")])
def test_current_date_checks_block_stale_or_not_effective_rules(complete, field, value, blocker):
    matrix = complete["matrix"]
    rule = matrix.rules[0].model_copy(update={field: value})
    result = assess(complete, matrix=matrix.model_copy(update={"rules": (rule,)}))
    assert blocker + ":fixture-rule" in result.blockers


def test_changed_rule_version_or_matrix_changes_invalidates_approval(complete):
    matrix = changed_review(complete, rule_version="fixture-v2")
    result = assess(complete, matrix=matrix)
    assert "compliance_rule_version_mismatch:fixture-rule" in result.blockers
    assert "compliance_signoff_stale" in result.blockers
    changed_source = changed_review(complete, source_sha256=digest("another source"))
    assert "compliance_rule_source_mismatch:fixture-rule" in assess(
        complete, matrix=changed_source).blockers


def test_every_rule_requires_exactly_one_review(complete):
    matrix = complete["matrix"].model_copy(update={"reviews": ()})
    assert "compliance_rule_review_missing_or_unexpected:fixture-rule" in assess(
        complete, matrix=matrix).blockers
    with pytest.raises(ValidationError, match="Duplicate rule review"):
        ApplicabilityMatrix.model_validate({**complete["matrix"].model_dump(),
            "reviews": (complete["matrix"].reviews[0],) * 2})


def test_role_alone_and_model_approval_never_establish_qualified_owner(complete):
    assert "compliance_owner_unqualified" in assess(complete, qualified_owners={}).blockers
    assert "compliance_owner_unqualified" in assess(complete,
        qualified_owners={"fixture-human": {"role": "compliance"}}).blockers
    owner = complete["qualified_owners"]["fixture-human"]
    with pytest.raises(ValidationError):
        QualifiedComplianceOwner.model_validate({**owner.model_dump(), "reviewer_kind": "llm"})


@pytest.mark.parametrize("changes", [
    {"jurisdictions": ("US",)}, {"activities": ("internal_diligence",)},
    {"valid_until": date(2026, 10, 9)}, {"valid_from": date(2026, 10, 2)}])
def test_qualified_owner_must_cover_exact_scope_and_review_date(complete, changes):
    owner = complete["qualified_owners"]["fixture-human"].model_copy(update=changes)
    result = assess(complete, qualified_owners={"fixture-human": owner})
    assert "compliance_owner_scope_or_authority_mismatch" in result.blockers


def test_rejected_and_future_dated_approvals_block(complete):
    assert "compliance_signoff_rejected" in assess(complete,
        signoff=complete["signoff"].model_copy(update={"decision": "rejected"})).blockers
    assert "compliance_signoff_future_dated" in assess(complete,
        signoff=complete["signoff"].model_copy(update={"reviewed_on": date(2026, 10, 11)})).blockers
    assert "compliance_signoff_predates_rule_verification" in assess(complete,
        signoff=complete["signoff"].model_copy(update={"reviewed_on": date(2026, 9, 30)})).blockers


@pytest.mark.parametrize("value", ["true", 1, "false", 0])
def test_rule_coverage_requires_a_strict_boolean(complete, value):
    with pytest.raises(ValidationError):
        RuleReview.model_validate({**complete["matrix"].reviews[0].model_dump(),
            "coverage_complete": value})


@pytest.mark.parametrize("url", ["http://authority.example/rule", "https://user:secret@authority.example/rule",
    "https://authority.example:8080/rule", "authority.example/rule"])
def test_source_record_rejects_unsecured_or_credential_bearing_urls(complete, url):
    with pytest.raises(ValidationError):
        RegulatoryRule.model_validate({**complete["matrix"].rules[0].model_dump(), "source_url": url})


def test_scope_has_no_implicit_india_or_fundraising_default(complete):
    payload = complete["scope"].model_dump()
    payload.pop("jurisdictions")
    with pytest.raises(ValidationError):
        ComplianceScope.model_validate(payload)
    assert ComplianceScope.model_json_schema()["additionalProperties"] is False


def _authority_database(complete):
    from security.identity import SCHEMA

    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    owner = complete["qualified_owners"]["fixture-human"]
    conn.execute("INSERT INTO auth_users(id) VALUES (?)", (owner.reviewer_id,))
    conn.execute("INSERT INTO auth_memberships VALUES (?,?,?,1)",
        ("fixture-tenant", owner.reviewer_id, "compliance"))
    conn.execute("INSERT INTO auth_reviewer_qualifications VALUES (?,?,?, ?,1)",
        ("fixture-tenant", owner.reviewer_id, "compliance", owner.model_dump_json()))
    return conn, owner


def test_qualification_database_requires_active_private_membership(complete):
    conn, owner = _authority_database(complete)
    assert qualified_compliance_owners(conn, "fixture-tenant") == {owner.reviewer_id: owner}
    assert qualified_compliance_owners(conn, "different-tenant") == {}
    conn.execute("UPDATE auth_memberships SET active=0")
    assert qualified_compliance_owners(conn, "fixture-tenant") == {}
    conn.close()


@pytest.mark.parametrize("mutation", [
    "UPDATE auth_reviewer_qualifications SET active=0",
    "UPDATE auth_users SET disabled=1",
    "UPDATE auth_memberships SET role='owner'",
    "UPDATE auth_reviewer_qualifications SET qualification='{}'",
    "UPDATE auth_reviewer_qualifications SET qualification='not-json'"])
def test_revoked_malformed_or_self_appointed_owner_records_fail_closed(complete, mutation):
    conn, _ = _authority_database(complete)
    conn.execute(mutation)
    assert qualified_compliance_owners(conn, "fixture-tenant") == {}
    conn.close()


def test_host_admission_does_not_approve_any_rule(tmp_path, complete):
    register = tmp_path / "register.json"
    register.write_text(json.dumps({"contract": "official-regulatory-reference-v1", "sources": [
        {"official_url": "https://authority.example/rule", "host": "authority.example",
         "status": "research_only", "last_checked": "2026-10-10"}]}))
    assert official_source_hosts(register) == {"authority.example"}
    result = assess(complete, official_source_hosts=official_source_hosts(register), signoff=None)
    assert result.status == "blocked"
    assert "compliance_qualified_signoff_missing" in result.blockers


@pytest.mark.parametrize("payload", ["not-json", {},
    {"contract": "another-contract", "sources": []},
    {"contract": "official-regulatory-reference-v1", "sources": [
        {"official_url": "https://other.example/rule", "host": "authority.example"}]},
    {"contract": "official-regulatory-reference-v1", "sources": [
        {"official_url": "https://user:secret@authority.example/rule", "host": "authority.example"}]}])
def test_invalid_register_admits_no_source_hosts(tmp_path, payload):
    register = tmp_path / "register.json"
    register.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    assert official_source_hosts(register) == set()


def test_production_package_requires_qualified_scope_even_for_disclosed_unknowns(
        complete, secured, monkeypatch):
    from api.routers.rooms import revision_for
    from delivery.release import evaluate_package, load_package, validate_room
    from store import Store

    client, db, users = secured
    sign_in(client, users[0])
    created = client.post("/api/rooms", json={"name": "Synthetic compliance fixture",
        "website": "https://fixture.example", "mandate_type": "fundraising_advisory",
        "terms_summary": "Synthetic engagement terms"})
    assert created.status_code == 201
    tenant, room_id = users[0][1], created.json()["workspace_id"]
    monkeypatch.setattr("delivery.release.official_source_hosts", lambda _: {"authority.example"})
    monkeypatch.setattr("delivery.release.retained_official_sources", lambda *_: complete["official_source_snapshots"])
    monkeypatch.setattr("delivery.release.room_evidence_inventory", lambda store, tenant, room, revision:
        BoundEvidenceInventory(tenant, room.id, revision, {"fixture-transaction": digest("retained evidence")}))
    monkeypatch.setattr("delivery.release.datetime", type("FixedClock", (), {
        "now": staticmethod(lambda _: __import__("datetime").datetime(2026, 10, 10))}))
    with Store(db) as store:
        room = store.get_workspace(tenant, workspace_id=room_id)
        package_id, missing = validate_room(store, tenant, room)
        assert "compliance_scope_missing" in missing.blockers
        assert "compliance_qualified_signoff_missing" in missing.blockers
        scope = complete["scope"].model_copy(update={
            "transaction_evidence_revision": revision_for(store, room)})
        matrix = complete["matrix"].model_copy(update={"scope_digest": scope.digest()})
        room.compliance_review = ComplianceReviewRecord(scope=scope, matrix=matrix)
        store.save_workspace(room, expected_revision=room.revision)
        assert "compliance_content_revision_changed" in evaluate_package(store, tenant, package_id).blockers
        package_id, current = validate_room(store, tenant, room)
        manifest, _, _, _ = load_package(store, tenant, package_id)
        assert manifest.compliance_revision == room.compliance_review.content_revision()
        signoff = complete["signoff"].model_copy(update={"manifest_digest": manifest.digest(),
            "scope_digest": scope.digest(), "matrix_digest": matrix.digest()})
        room.compliance_review = room.compliance_review.model_copy(update={"signoff": signoff})
        store.save_workspace(room, expected_revision=room.revision)
        assert "compliance_owner_unqualified" in evaluate_package(store, tenant, package_id).blockers
        # Qualification alone is insufficient; server membership is also required.
        owner = complete["qualified_owners"]["fixture-human"]
        store.conn.execute("INSERT INTO auth_users(id) VALUES (?)", (owner.reviewer_id,))
        store.conn.execute("INSERT INTO auth_reviewer_qualifications VALUES (?,?,?, ?,1)",
            (tenant, owner.reviewer_id, "compliance", owner.model_dump_json()))
        store.conn.commit()
        assert "compliance_owner_unqualified" in evaluate_package(store, tenant, package_id).blockers
        store.conn.execute("INSERT INTO auth_memberships VALUES (?,?,?,1)",
            (tenant, owner.reviewer_id, "compliance"))
        store.conn.commit()
        qualified = evaluate_package(store, tenant, package_id)
        assert not any(blocker.startswith("compliance_") for blocker in qualified.blockers)
        assert not qualified.eligible_for_release  # Missing files and financial checks remain.
        store.conn.execute("UPDATE auth_reviewer_qualifications SET active=0 WHERE user_id=?",
            (owner.reviewer_id,))
        store.conn.commit()
        assert "compliance_owner_unqualified" in evaluate_package(store, tenant, package_id).blockers
