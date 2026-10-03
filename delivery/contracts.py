"""L0 contracts for the new investor package (legacy Markdown is not a package).

These records describe required validation, not implementations of the checks.
Only trusted validators/review services may supply their results. The evaluator
does not authenticate users, inspect file contents, persist or release artifacts.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ArtifactKind = Literal["intro_deck", "pitch_deck", "investment_memorandum", "financial_projection"]
REQUIRED_MATERIAL_KINDS = ("intro_deck", "pitch_deck", "investment_memorandum")
FileFormat = Literal["pptx", "docx", "xlsx", "pdf"]
CheckStatus = Literal["pass", "fail", "not_run", "unsupported", "not_applicable"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactContract(Contract):
    kind: ArtifactKind
    formats: tuple[FileFormat, ...]
    required_sections: tuple[str, ...]
    checks: tuple[str, ...]
    reviewer_roles: tuple[str, ...]


COMMON_CHECKS = (
    "input_provenance", "financial_semantics", "chart_binding",
    "narrative_support", "visual_rendering", "file_compatibility", "confidentiality",
)
ARTIFACT_CONTRACTS = (
    ArtifactContract(kind="intro_deck", formats=("pptx", "pdf"),
        required_sections=("company_identity", "offering", "market", "traction", "fundraising", "sources"),
        checks=COMMON_CHECKS, reviewer_roles=("financial",)),
    ArtifactContract(kind="pitch_deck", formats=("pptx", "pdf"),
        required_sections=("company_identity", "problem", "offering", "market", "business_model",
            "traction", "competition", "team", "financials", "fundraising", "sources"),
        checks=COMMON_CHECKS, reviewer_roles=("financial",)),
    ArtifactContract(kind="investment_memorandum", formats=("docx", "pdf"),
        required_sections=("company_identity", "business", "market", "financials", "transaction",
            "risks", "assumptions", "sources", "review_appendix"),
        checks=COMMON_CHECKS + ("compliance_applicability",), reviewer_roles=("financial", "compliance")),
    ArtifactContract(kind="financial_projection", formats=("xlsx",),
        required_sections=("assumptions", "operating_drivers", "profit_and_loss", "cash_rollforward",
            "scenarios", "sources", "checks"),
        checks=COMMON_CHECKS + ("formula_execution_all_sheets", "scenario_execution"),
        reviewer_roles=("financial",)),
)


class ValidationPolicy(Contract):
    version: Literal["local-artifacts-v2"] = "local-artifacts-v2"
    artifacts: tuple[ArtifactContract, ...] = ARTIFACT_CONTRACTS
    package_checks: tuple[str, ...] = ("cross_artifact_consistency", "source_rights_freshness")
    # Conservative initial contract: no N/A waivers until a reviewed applicability
    # rule exists. No-chart fixtures still verify absence of unexpected payloads.
    allowed_not_applicable: tuple[str, ...] = ()


POLICY = ValidationPolicy()


class ArtifactFile(Contract):
    artifact_id: Identifier
    kind: ArtifactKind
    format: FileFormat
    sha256: Digest
    size_bytes: Annotated[int, Field(strict=True, gt=0)]


class ArtifactManifest(Contract):
    tenant_id: Identifier
    workspace_id: Identifier
    audience: Identifier
    policy_version: Identifier
    evidence_revision: Digest
    model_revision: Digest
    assumption_revision: Digest
    material_revision: Digest
    renderer_version: Identifier
    calculation_version: Identifier
    template_version: Identifier
    requested: tuple[ArtifactKind, ...] = Field(min_length=1)
    files: tuple[ArtifactFile, ...] = ()

    @model_validator(mode="after")
    def unique_members(self):
        if len(set(self.requested)) != len(self.requested):
            raise ValueError("Duplicate requested artifact kind")
        ids = [f.artifact_id for f in self.files]
        slots = [(f.kind, f.format) for f in self.files]
        if len(set(ids)) != len(ids) or len(set(slots)) != len(slots):
            raise ValueError("Duplicate artifact ID or kind/format")
        return self

    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        payload["requested"] = sorted(payload["requested"])
        payload["files"] = sorted(payload["files"], key=lambda f: f["artifact_id"])
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CheckResult(Contract):
    check_id: Identifier
    target: Identifier  # artifact ID, or reserved package target
    manifest_digest: Digest
    status: CheckStatus
    coverage_complete: bool = False
    validator_version: Identifier
    report_id: Identifier
    reason: str = ""


class ReviewDecision(Contract):
    role: Literal["financial", "compliance"]
    reviewer_id: Identifier
    manifest_digest: Digest
    decision: Literal["approved", "rejected"]


class ReleaseAssessment(Contract):
    # Deliberately not a Released state: authorization and transactional publishing
    # belong to L1/L4. Even a passing assessment cannot serve a download.
    eligible_for_release: bool
    manifest_digest: Digest
    blockers: tuple[str, ...]


def assess_release(
    manifest: ArtifactManifest,
    checks: tuple[CheckResult, ...],
    reviews: tuple[ReviewDecision, ...],
    *,
    observed_hashes: dict[str, str],
    authorized_reviewers: dict[str, set[str]],
) -> ReleaseAssessment:
    """Fail-closed aggregation over trusted, exact-revision check results.

Hashes must be freshly observed by private storage; reviewer grants must come
from server-side authorization. Never pass request-body values as either input.
This function is intentionally I/O-free and cannot certify a validator's work.
"""
    digest = manifest.digest()
    blockers = []
    if manifest.policy_version != POLICY.version:
        blockers.append("policy_version_mismatch")
    contracts = {c.kind: c for c in POLICY.artifacts}
    for kind in REQUIRED_MATERIAL_KINDS:
        if kind not in manifest.requested:
            blockers.append(f"missing_required_kind:{kind}")
    expected = {(kind, fmt) for kind in manifest.requested for fmt in contracts[kind].formats}
    present = {(f.kind, f.format) for f in manifest.files}
    for kind, fmt in sorted(expected - present):
        blockers.append(f"missing_file:{kind}:{fmt}")
    for kind, fmt in sorted(present - expected):
        blockers.append(f"unexpected_file:{kind}:{fmt}")
    if set(observed_hashes) != {f.artifact_id for f in manifest.files}:
        blockers.append("observed_file_set_mismatch")
    required = {("package", name) for name in POLICY.package_checks}
    for file in manifest.files:
        if file.artifact_id == "package":
            blockers.append("reserved_artifact_id")
        if observed_hashes.get(file.artifact_id) != file.sha256:
            blockers.append(f"file_hash_mismatch:{file.artifact_id}")
        required.update((file.artifact_id, name) for name in contracts[file.kind].checks)
    indexed = {}
    for check in checks:
        key = (check.target, check.check_id)
        if key in indexed:
            blockers.append(f"duplicate_check:{check.target}:{check.check_id}")
        indexed[key] = check
        if key not in required:
            blockers.append(f"unexpected_check:{check.target}:{check.check_id}")
    for target, name in sorted(required):
        check = indexed.get((target, name))
        label = f"{target}:{name}"
        if check is None:
            blockers.append(f"missing_check:{label}")
        elif check.manifest_digest != digest:
            blockers.append(f"stale_check:{label}")
        elif check.status != "pass" or not check.coverage_complete:
            blockers.append(f"blocking_check:{label}:{check.status}")
    roles = {role for kind in manifest.requested for role in contracts[kind].reviewer_roles}
    for role in sorted(roles):
        decisions = [r for r in reviews if r.role == role]
        if len(decisions) != 1:
            blockers.append(f"missing_or_ambiguous_review:{role}")
            continue
        review = decisions[0]
        if (review.manifest_digest != digest or review.decision != "approved"
                or review.reviewer_id not in authorized_reviewers.get(role, set())):
            blockers.append(f"invalid_review:{role}")
    return ReleaseAssessment(eligible_for_release=not blockers, manifest_digest=digest,
        blockers=tuple(blockers))
