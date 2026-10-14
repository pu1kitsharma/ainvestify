"""L0 contracts for the new investor package (legacy Markdown is not a package).

These records describe required validation, not implementations of the checks.
Only trusted validators/review services may supply their results. The evaluator
does not authenticate users, inspect file contents, persist or release artifacts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ArtifactKind = Literal["intro_deck", "pitch_deck", "investment_memorandum", "financial_projection"]
REQUIRED_MATERIAL_KINDS = ("intro_deck", "pitch_deck", "investment_memorandum")
FileFormat = Literal["pptx", "docx", "xlsx", "pdf"]
CheckStatus = Literal["pass", "fail", "not_run", "unsupported", "not_applicable"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceTableColumn(Contract):
    """Recorded labels for a bounded editable table; no numerical derivation."""
    label: Annotated[str, Field(min_length=1, max_length=100)]
    period: Annotated[str, Field(max_length=60)] = ""
    unit: Annotated[str, Field(max_length=60)] = ""


class EvidenceTableCell(Contract):
    """An exact source-cell projection, not a model-authored financial value.

    Upstream replay must bind value_ref/text to the immutable evidence table.
    This shape validator deliberately cannot certify that evidence or its status.
    """
    text: Annotated[str, Field(max_length=180)]
    status: Literal["source_reported", "projection", "illustrative", "missing"]
    source_refs: tuple[Identifier, ...] = Field(default=(), max_length=4)
    value_ref: Optional[Identifier] = None

    @model_validator(mode="after")
    def evidence_shape(self):
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("Duplicate table cell source reference")
        if self.status != "missing" and (not self.source_refs or self.value_ref is None):
            raise ValueError("Nonmissing table cell requires immutable value and source references")
        if self.status == "missing" and self.value_ref is not None:
            raise ValueError("Missing table cell cannot bind a supplied value")
        if not self.text.strip():
            raise ValueError("Table cell requires explicit exact text or a missing label")
        return self


class EvidenceTableRow(Contract):
    cells: tuple[EvidenceTableCell, ...] = Field(min_length=2, max_length=7)


class EvidenceTable(Contract):
    """Renderer input for a selected immutable source table.

    The renderer lays out these bytes and refuses unreadable overflow. It does
    not calculate, reconcile, approve or repair values. Table selection and
    labels must project recorded local-model output; cell text must project the
    corresponding original source values in a separately checked evidence view.
    """
    contract: Literal["evidence-table-v1"] = "evidence-table-v1"
    table_id: Identifier
    evidence_revision: Digest
    columns: tuple[EvidenceTableColumn, ...] = Field(min_length=2, max_length=7)
    rows: tuple[EvidenceTableRow, ...] = Field(min_length=1, max_length=36)

    @model_validator(mode="after")
    def rectangular(self):
        if any(len(row.cells) != len(self.columns) for row in self.rows):
            raise ValueError("Evidence table must be rectangular")
        return self


class EvidenceChartLiteral(Contract):
    text: Annotated[str, Field(min_length=1, max_length=120)]
    literal_unit_id: Identifier
    literal_sha256: Digest

    @model_validator(mode="after")
    def literal_bytes(self):
        import re
        if self.text.lstrip().startswith('=') or re.match(r'(?i)^\s*(?:https?|ftp|mailto):', self.text):
            raise ValueError('Unsafe source chart label cannot enter an editable workbook')
        expected = hashlib.sha256(json.dumps(self.text, ensure_ascii=False,
                                  separators=(',', ':')).encode()).hexdigest()
        if self.literal_sha256 != expected:
            raise ValueError('Chart original literal hash mismatch')
        return self


class EvidenceChartPoint(Contract):
    numeric_literal: Annotated[str, Field(min_length=1, max_length=80)]
    literal_unit_id: Identifier
    literal_sha256: Digest

    @model_validator(mode="after")
    def finite_exact_number(self):
        from decimal import Decimal, InvalidOperation
        import math
        import re
        if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',
                            self.numeric_literal):
            raise ValueError('Chart point requires an exact finite OOXML numeric literal')
        try:
            number = Decimal(self.numeric_literal)
            plotted = float(number)
        except (InvalidOperation, OverflowError):
            raise ValueError('Unsupported source chart numeric literal')
        # OOXML caches are rendered through native floating-point chart APIs.
        # Refuse an observation whose original decimal value would be changed.
        if not number.is_finite() or not math.isfinite(plotted) or Decimal(str(plotted)) != number:
            raise ValueError('Source chart number cannot survive exact native chart conversion')
        if abs(plotted) > 1e15:
            raise ValueError('Source chart numeric range exceeds qualified renderer')
        expected = hashlib.sha256(json.dumps(self.numeric_literal, ensure_ascii=False,
                                  separators=(',', ':')).encode()).hexdigest()
        if self.literal_sha256 != expected:
            raise ValueError('Chart original numeric literal hash mismatch')
        return self


class EvidenceChartSeries(Contract):
    name: EvidenceChartLiteral
    points: tuple[EvidenceChartPoint, ...] = Field(min_length=1, max_length=12)


class EvidenceChart(Contract):
    """Complete single-axis original chart-cache observation, always unreviewed.

    A separately checked original manifest supplies every name, category and
    numeric literal. The renderer never asks a model to invent a data series.
    Reproducible stored caches are not recalculated or financially qualified.
    """
    contract: Literal['evidence-chart-v1'] = 'evidence-chart-v1'
    chart_unit_id: Identifier
    chart_part: Annotated[str, Field(pattern=r'^ppt/charts/chart[1-9][0-9]*\.xml$')]
    evidence_revision: Digest
    source_sha256: Digest
    cache_digest: Digest
    plot_type: Literal['column_clustered', 'column_stacked', 'bar_clustered', 'line', 'pie']
    categories: tuple[EvidenceChartLiteral, ...] = Field(min_length=1, max_length=12)
    series: tuple[EvidenceChartSeries, ...] = Field(min_length=1, max_length=3)
    source_refs: tuple[Identifier, ...] = Field(min_length=1, max_length=4)
    source_status: Literal['source_cache_unreviewed'] = 'source_cache_unreviewed'
    financial_validation: Literal['not_established'] = 'not_established'
    recalculation: Literal['not_performed'] = 'not_performed'
    period: Literal['unassessed'] = 'unassessed'
    unit: Literal['unassessed'] = 'unassessed'
    axis_count: Literal[0, 2]
    external_dependencies: Literal[False] = False

    @model_validator(mode="after")
    def exact_cache_shape(self):
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError('Duplicate chart source reference')
        if any(len(series.points) != len(self.categories) for series in self.series):
            raise ValueError('Chart cache point/category count mismatch')
        if self.plot_type == 'pie':
            if self.axis_count != 0 or len(self.series) != 1:
                raise ValueError('Only one complete original pie series without axes is supported')
            values = [float(point.numeric_literal) for point in self.series[0].points]
            if any(value < 0 for value in values) or sum(values) <= 0:
                raise ValueError('Original pie cache requires nonnegative nonzero observations')
        elif self.axis_count != 2:
            raise ValueError('Chart requires exactly one original category/value axis pair')
        payload = self.model_dump(mode='json', exclude={'cache_digest'})
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                  ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if self.cache_digest != expected:
            raise ValueError('Exact source chart cache digest mismatch')
        return self


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
    # New compliance content binds exact scope/rules. Absence preserves the
    # historical manifest digest; production release still requires a review.
    compliance_revision: Optional[Digest] = None

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
        if self.compliance_revision is None:
            payload.pop("compliance_revision")
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
    # Absent on historical records. Production financial review cannot use an
    # undated approval or retrospectively qualify it through a later grant.
    reviewed_on: Optional[date] = None


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
