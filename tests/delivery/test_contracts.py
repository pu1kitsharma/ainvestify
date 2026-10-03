"""Synthetic control-plane tests, not file/engine or investment acceptance."""
import hashlib

import pytest
from pydantic import ValidationError

from delivery.contracts import (
    POLICY, REQUIRED_MATERIAL_KINDS, ArtifactFile, ArtifactManifest, CheckResult,
    ReviewDecision, assess_release,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def package():
    files = tuple(ArtifactFile(artifact_id=f"{c.kind}.{fmt}", kind=c.kind, format=fmt,
        sha256=digest(f"synthetic:{c.kind}:{fmt}"), size_bytes=10)
        for c in POLICY.artifacts for fmt in c.formats)
    manifest = ArtifactManifest(tenant_id="synthetic-owner", workspace_id="synthetic-room",
        audience="investor", policy_version=POLICY.version, evidence_revision=digest("evidence"),
        model_revision=digest("model"), assumption_revision=digest("assumptions"),
        material_revision=digest("material"), renderer_version="synthetic-only-v1",
        calculation_version="unqualified-fixture", template_version="fixture-v1",
        requested=tuple(c.kind for c in POLICY.artifacts), files=files)
    targets = [(f.artifact_id, name) for f in files
        for name in next(c for c in POLICY.artifacts if c.kind == f.kind).checks]
    targets += [("package", name) for name in POLICY.package_checks]
    checks = tuple(CheckResult(target=target, check_id=name, manifest_digest=manifest.digest(),
        status="pass", coverage_complete=True, validator_version="fixture-only-v1",
        report_id=f"fixture:{target}:{name}") for target, name in targets)
    reviews = tuple(ReviewDecision(role=role, reviewer_id=f"synthetic-{role}",
        manifest_digest=manifest.digest(), decision="approved") for role in ("financial", "compliance"))
    return manifest, checks, reviews


def assess(package, **overrides):
    manifest, checks, reviews = package
    args = dict(observed_hashes={f.artifact_id: f.sha256 for f in manifest.files},
        authorized_reviewers={role: {f"synthetic-{role}"} for role in ("financial", "compliance")})
    args.update(overrides)
    return assess_release(manifest, checks, reviews, **args)


def test_complete_synthetic_package_is_eligible_but_not_released(package):
    result = assess(package)
    assert result.eligible_for_release
    assert result.blockers == ()
    assert "released" not in type(result).model_fields


@pytest.mark.parametrize("check_id", sorted({n for c in POLICY.artifacts for n in c.checks}
    | set(POLICY.package_checks)))
@pytest.mark.parametrize("status", ["fail", "not_run", "unsupported", "not_applicable"])
def test_every_mandatory_failure_blocks(package, check_id, status):
    manifest, checks, reviews = package
    changed = tuple(c.model_copy(update={"status": status, "reason": "synthetic injected error"})
        if c.check_id == check_id else c for c in checks)
    assert not assess((manifest, changed, reviews)).eligible_for_release


def test_unknown_coverage_cannot_pass(package):
    manifest, checks, reviews = package
    changed = (checks[0].model_copy(update={"coverage_complete": False}), *checks[1:])
    assert not assess((manifest, changed, reviews)).eligible_for_release


def test_missing_and_duplicate_checks_block(package):
    manifest, checks, reviews = package
    assert not assess((manifest, checks[1:], reviews)).eligible_for_release
    assert not assess((manifest, (*checks, checks[0]), reviews)).eligible_for_release


def test_full_package_cannot_silently_omit_workbook(package):
    manifest, checks, reviews = package
    changed = manifest.model_copy(update={"files": tuple(f for f in manifest.files if f.format != "xlsx")})
    assert "missing_file:financial_projection:xlsx" in assess((changed, checks, reviews)).blockers


def test_core_materials_can_be_assessed_without_projection(package):
    manifest, checks, reviews = package
    files = tuple(file for file in manifest.files if file.kind != "financial_projection")
    core = manifest.model_copy(update={"requested": REQUIRED_MATERIAL_KINDS, "files": files})
    core_checks = tuple(check.model_copy(update={"manifest_digest": core.digest()})
        for check in checks if check.target == "package" or
        check.target in {file.artifact_id for file in files})
    core_reviews = tuple(review.model_copy(update={"manifest_digest": core.digest()})
        for review in reviews)
    result = assess((core, core_checks, core_reviews), observed_hashes={
        file.artifact_id: file.sha256 for file in files})
    assert result.eligible_for_release


def test_pitch_and_memo_cannot_be_omitted_from_requested_materials(package):
    manifest, checks, reviews = package
    changed = manifest.model_copy(update={"requested": ("intro_deck",)})
    blockers = assess((changed, checks, reviews)).blockers
    assert "missing_required_kind:pitch_deck" in blockers
    assert "missing_required_kind:investment_memorandum" in blockers


def test_distribution_pdf_is_required(package):
    manifest, checks, reviews = package
    changed = manifest.model_copy(update={"files": tuple(f for f in manifest.files
        if not (f.kind == "intro_deck" and f.format == "pdf"))})
    assert any(b.startswith("missing_file:") for b in assess((changed, checks, reviews)).blockers)


def test_modified_export_cannot_reuse_passing_manifest(package):
    manifest, _, _ = package
    hashes = {f.artifact_id: f.sha256 for f in manifest.files}
    hashes[manifest.files[0].artifact_id] = digest("modified exported bytes")
    assert not assess(package, observed_hashes=hashes).eligible_for_release


@pytest.mark.parametrize("field", ["evidence_revision", "model_revision", "assumption_revision", "material_revision"])
def test_new_revision_invalidates_all_checks_and_reviews(package, field):
    manifest, checks, reviews = package
    changed = manifest.model_copy(update={field: digest("new revision")})
    result = assess((changed, checks, reviews))
    assert not result.eligible_for_release
    assert "invalid_review:financial" in result.blockers
    assert any(b.startswith("stale_check:") for b in result.blockers)


def test_review_grants_are_required_and_revocable(package):
    assert not assess(package, authorized_reviewers={}).eligible_for_release
    assert not assess(package, authorized_reviewers={"financial": {"synthetic-financial"}}).eligible_for_release


def test_rejected_and_ambiguous_reviews_block(package):
    manifest, checks, reviews = package
    assert not assess((manifest, checks, reviews[:1])).eligible_for_release
    assert not assess((manifest, checks, (*reviews, reviews[0]))).eligible_for_release
    assert not assess((manifest, checks, (reviews[0].model_copy(update={"decision": "rejected"}), reviews[1]))).eligible_for_release


def test_policy_and_observed_file_set_must_match(package):
    manifest, checks, reviews = package
    changed = manifest.model_copy(update={"policy_version": "obsolete-policy"})
    assert "policy_version_mismatch" in assess((changed, checks, reviews)).blockers
    assert not assess(package, observed_hashes={}).eligible_for_release


def test_digest_is_order_independent_and_scope_bound(package):
    manifest, _, _ = package
    assert manifest.digest() == manifest.model_copy(update={"files": tuple(reversed(manifest.files)),
        "requested": tuple(reversed(manifest.requested))}).digest()
    for field in ("tenant_id", "workspace_id", "audience", "template_version", "renderer_version", "calculation_version"):
        assert manifest.digest() != manifest.model_copy(update={field: "changed"}).digest()


def test_duplicate_files_and_unknown_formats_rejected(package):
    manifest, _, _ = package
    payload = manifest.model_dump()
    payload["files"] = (*manifest.files, manifest.files[0])
    with pytest.raises(ValidationError):
        ArtifactManifest.model_validate(payload)
    payload = manifest.files[0].model_dump()
    payload["format"] = "md"
    with pytest.raises(ValidationError):
        ArtifactFile.model_validate(payload)


def test_contracts_export_as_json_schema():
    assert ArtifactManifest.model_json_schema()["additionalProperties"] is False
    assert len(POLICY.model_dump(mode="json")["artifacts"]) == 4
