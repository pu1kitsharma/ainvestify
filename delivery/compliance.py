"""Exact-version compliance review contracts, not an automated legal opinion.

An applicability matrix must be supplied by a qualified human for the declared
activity and jurisdictions. Engineering and model checks cannot appoint that
person, establish the complete legal ruleset, or sign off a transaction.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Annotated, Literal, Optional
from urllib.parse import urlsplit

from pydantic import Field, StrictBool, model_validator

from delivery.contracts import Contract, Digest, Identifier

Activity = Literal["internal_diligence", "private_fundraising", "public_offer",
                   "investment_advice", "fund_disclosure", "other"]
Country = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
Reason = Annotated[str, Field(min_length=8, max_length=300)]


def _digest(record):
    return hashlib.sha256(json.dumps(record.model_dump(mode="json"),
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _unique(values, label):
    if len(set(values)) != len(values):
        raise ValueError("Duplicate " + label)


class ComplianceScope(Contract):
    """Declared facts for a review; no default geography or implied mandate."""
    jurisdictions: tuple[Country, ...] = Field(min_length=1, max_length=20)
    activity: Activity
    issuer_form: Identifier
    instrument: Identifier
    investor_residency: Literal["domestic", "nonresident", "mixed", "not_applicable", "unknown"]
    sector: Identifier
    regulated_activities: tuple[Identifier, ...] = Field(max_length=20)
    audience: Literal["internal", "identified_investors", "public", "other"]
    transaction_evidence_revision: Digest
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=30)
    unresolved_fields: tuple[Identifier, ...] = Field(max_length=30)

    @model_validator(mode="after")
    def unique_fields(self):
        for name in ("jurisdictions", "regulated_activities", "evidence_ids", "unresolved_fields"):
            _unique(getattr(self, name), name)
        return self

    def digest(self):
        return _digest(self)


class RegulatoryRule(Contract):
    """A reviewed official-source snapshot, with explicit date coverage."""
    rule_id: Identifier
    version: Identifier
    jurisdiction: Country
    reference: Identifier
    source_url: Identifier
    source_sha256: Digest
    effective_from: date
    effective_through: Optional[date] = None  # Inclusive when present.
    verified_on: date
    valid_until: date  # A reviewer-set freshness deadline, not a statutory claim.

    @model_validator(mode="after")
    def source_and_dates(self):
        parsed = urlsplit(self.source_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)):
            raise ValueError("A rule needs a credential-free HTTPS official source")
        if self.valid_until < self.verified_on:
            raise ValueError("Rule freshness deadline precedes verification")
        if self.effective_through and self.effective_through < self.effective_from:
            raise ValueError("Rule effective date range is reversed")
        return self


class RuleReview(Contract):
    rule_id: Identifier
    rule_version: Identifier
    source_sha256: Digest
    applicability: Literal["applies", "not_applicable", "undetermined"]
    reason: Reason
    evidence_status: Literal["satisfied", "missing", "contradicted", "not_run", "not_applicable"]
    evidence_ids: tuple[Identifier, ...] = Field(max_length=30)
    coverage_complete: StrictBool

    @model_validator(mode="after")
    def unique_evidence(self):
        _unique(self.evidence_ids, "rule evidence")
        return self


class ApplicabilityMatrix(Contract):
    policy_version: Literal["compliance-applicability-v1"] = "compliance-applicability-v1"
    scope_digest: Digest
    rules: tuple[RegulatoryRule, ...] = Field(min_length=1, max_length=200)
    reviews: tuple[RuleReview, ...] = Field(min_length=1, max_length=200)
    # A qualified owner must attest the universe is complete for this scope.
    # A model's selected subset is never sufficient to make this True.
    scope_coverage_complete: StrictBool

    @model_validator(mode="after")
    def unique_rules(self):
        _unique([r.rule_id for r in self.rules], "rule")
        _unique([r.rule_id for r in self.reviews], "rule review")
        return self

    def digest(self):
        return _digest(self)


class QualifiedComplianceOwner(Contract):
    """Trusted server-side qualification, never a request-body appointment."""
    reviewer_id: Identifier
    reviewer_kind: Literal["qualified_human"]
    authority_record_id: Identifier
    jurisdictions: tuple[Country, ...] = Field(min_length=1, max_length=20)
    activities: tuple[Activity, ...] = Field(min_length=1, max_length=6)
    valid_from: date
    valid_until: date

    @model_validator(mode="after")
    def valid_grant(self):
        _unique(self.jurisdictions, "qualified jurisdiction")
        _unique(self.activities, "qualified activity")
        if self.valid_until < self.valid_from:
            raise ValueError("Reviewer qualification dates are reversed")
        return self


class QualifiedFinancialOwner(QualifiedComplianceOwner):
    """Operator-verified professional authority for financial review scopes.

    This separate record is read only from the financial qualification role;
    membership or a model-written review cannot supply professional authority.
    """


class ComplianceSignoff(Contract):
    reviewer_id: Identifier
    manifest_digest: Digest
    scope_digest: Digest
    matrix_digest: Digest
    decision: Literal["approved", "rejected"]
    reviewed_on: date


class ComplianceReviewRecord(Contract):
    """Private workspace review; a signoff never changes its content revision."""
    scope: Optional[ComplianceScope] = None
    matrix: Optional[ApplicabilityMatrix] = None
    signoff: Optional[ComplianceSignoff] = None

    def content_revision(self):
        # Signoff references the manifest, which references this content revision.
        # Excluding that decision avoids a circular digest and permits revocation.
        payload = self.model_dump(mode="json", exclude={"signoff"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()


class ComplianceAssessment(Contract):
    verification_contract: Literal["compliance-source-evidence-v2"] = "compliance-source-evidence-v2"
    status: Literal["blocked", "approved_for_declared_scope"]
    manifest_digest: Digest
    scope_digest: Optional[Digest] = None
    matrix_digest: Optional[Digest] = None
    blockers: tuple[str, ...]
    summary: str


def assess_compliance(*, manifest_digest: str, evidence_revision: str,
        scope: Optional[ComplianceScope], matrix: Optional[ApplicabilityMatrix],
        signoff: Optional[ComplianceSignoff], qualified_owners: dict,
        official_source_hosts: set, as_of: date, official_source_snapshots=None,
        evidence_inventory=None) -> ComplianceAssessment:
    """Check trusted records and exact revisions; do not determine the law.

`qualified_owners`, `official_source_hosts` and `as_of` must be supplied by the
server's reviewed configuration and clock. An LLM result or user-supplied role
cannot be used as any of these inputs. This does not inspect evidence content;
independent financial/narrative/file checks remain mandatory release gates.
"""
    blockers = []
    from delivery.review_integrity import BoundEvidenceInventory, RetainedOfficialSource
    inventory_valid = (isinstance(evidence_inventory, BoundEvidenceInventory)
                       and evidence_inventory.evidence_revision == evidence_revision)
    if not inventory_valid:
        blockers.append("compliance_evidence_inventory_unavailable")
    scope_hash = scope.digest() if scope else None
    matrix_hash = matrix.digest() if matrix else None
    if scope is None:
        blockers.append("compliance_scope_missing")
    else:
        if scope.transaction_evidence_revision != evidence_revision:
            blockers.append("compliance_scope_stale")
        if scope.unresolved_fields or scope.investor_residency == "unknown":
            blockers.append("compliance_scope_unresolved")
        if inventory_valid and any(identifier not in evidence_inventory.evidence
                                   for identifier in scope.evidence_ids):
            blockers.append("compliance_scope_evidence_unresolved")
    if matrix is None:
        blockers.append("compliance_matrix_missing")
    else:
        if matrix.scope_digest != scope_hash:
            blockers.append("compliance_matrix_stale")
        if not matrix.scope_coverage_complete:
            blockers.append("compliance_rule_coverage_incomplete")
        rules = {rule.rule_id: rule for rule in matrix.rules}
        reviews = {review.rule_id: review for review in matrix.reviews}
        for rule_id in sorted(set(rules) ^ set(reviews)):
            blockers.append("compliance_rule_review_missing_or_unexpected:" + rule_id)
        for rule in matrix.rules:
            label = ":" + rule.rule_id
            if urlsplit(rule.source_url).hostname not in official_source_hosts:
                blockers.append("compliance_source_unverified" + label)
            snapshot = (official_source_snapshots or {}).get(rule.source_url)
            if (not isinstance(snapshot, RetainedOfficialSource)
                    or snapshot.source_url != rule.source_url):
                blockers.append("compliance_source_bytes_unavailable" + label)
            elif snapshot.source_sha256 != rule.source_sha256:
                blockers.append("compliance_source_bytes_mismatch" + label)
            if rule.verified_on > as_of or rule.valid_until < as_of:
                blockers.append("compliance_rule_stale" + label)
            if rule.effective_from > as_of or (
                    rule.effective_through and rule.effective_through < as_of):
                blockers.append("compliance_rule_outside_effective_period" + label)
            review = reviews.get(rule.rule_id)
            if review is None:
                continue
            if review.rule_version != rule.version:
                blockers.append("compliance_rule_version_mismatch" + label)
            if review.source_sha256 != rule.source_sha256:
                blockers.append("compliance_rule_source_mismatch" + label)
            if review.applicability == "undetermined":
                blockers.append("compliance_applicability_unresolved" + label)
            elif review.applicability == "applies":
                if scope and rule.jurisdiction not in scope.jurisdictions:
                    blockers.append("compliance_rule_jurisdiction_mismatch" + label)
                if review.evidence_status != "satisfied":
                    blockers.append("compliance_evidence_" + review.evidence_status + label)
            elif review.evidence_status != "not_applicable":
                blockers.append("compliance_invalid_exclusion" + label)
            # Exclusion also needs reviewed transaction evidence and coverage.
            if not review.evidence_ids or not review.coverage_complete:
                blockers.append("compliance_evidence_incomplete" + label)
            if inventory_valid and any(identifier not in evidence_inventory.evidence
                                       for identifier in review.evidence_ids):
                blockers.append("compliance_rule_evidence_unresolved" + label)
    if signoff is None:
        blockers.append("compliance_qualified_signoff_missing")
    else:
        if (signoff.manifest_digest != manifest_digest or signoff.scope_digest != scope_hash
                or signoff.matrix_digest != matrix_hash):
            blockers.append("compliance_signoff_stale")
        if signoff.decision != "approved":
            blockers.append("compliance_signoff_rejected")
        if signoff.reviewed_on > as_of:
            blockers.append("compliance_signoff_future_dated")
        if matrix and any(rule.verified_on > signoff.reviewed_on for rule in matrix.rules):
            blockers.append("compliance_signoff_predates_rule_verification")
        owner = qualified_owners.get(signoff.reviewer_id)
        if not isinstance(owner, QualifiedComplianceOwner) or owner.reviewer_id != signoff.reviewer_id:
            blockers.append("compliance_owner_unqualified")
        elif scope and (not set(scope.jurisdictions) <= set(owner.jurisdictions)
                or scope.activity not in owner.activities or not owner.valid_from <= as_of <= owner.valid_until
                or signoff.reviewed_on < owner.valid_from):
            blockers.append("compliance_owner_scope_or_authority_mismatch")
    status = "blocked" if blockers else "approved_for_declared_scope"
    return ComplianceAssessment(status=status, manifest_digest=manifest_digest,
        scope_digest=scope_hash, matrix_digest=matrix_hash, blockers=tuple(blockers),
        summary="Compliance review required" if blockers else "Compliance review approved for the declared scope")


def qualified_compliance_owners(conn, tenant):
    """Read operator-provisioned authority plus active server membership.

    There is deliberately no model/room/request-body fallback or grant route.
    Invalid qualification records fail closed and must be fixed by the operator.
    """
    from pydantic import ValidationError

    rows = conn.execute("""SELECT q.user_id,q.qualification
        FROM auth_reviewer_qualifications q
        JOIN auth_memberships m ON m.tenant_id=q.tenant_id AND m.user_id=q.user_id
        JOIN auth_users u ON u.id=q.user_id
        WHERE q.tenant_id=? AND q.role='compliance' AND q.active=1
          AND m.role='compliance' AND m.active=1 AND u.disabled=0""", (tenant,)).fetchall()
    owners = {}
    for user_id, payload in rows:
        try:
            owner = QualifiedComplianceOwner.model_validate_json(payload)
        except (ValidationError, ValueError, TypeError):
            continue
        if owner.reviewer_id == user_id:
            owners[user_id] = owner
    return owners


def official_source_hosts(path):
    """Host admission from a reviewed research register, not rule approval."""
    try:
        payload = json.loads(path.read_text())
        if payload.get("contract") != "official-regulatory-reference-v1":
            return set()
        hosts = set()
        for item in payload["sources"]:
            url = urlsplit(item["official_url"])
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or url.port not in (None, 443) or item["host"] != url.hostname):
                return set()
            hosts.add(url.hostname)
        return hosts
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return set()
