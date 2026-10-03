"""Content readiness for draft materials, separate from exact-file release checks.

This module checks a *recorded* model result and a proposed deck plan. It does
not authenticate response IDs or decide whether a factual claim is true. The
caller must replay the IDs against retained local responses before rendering.
"""
from __future__ import annotations

from collections.abc import Mapping


def memo_blockers(memo: Mapping, coverage: Mapping) -> tuple[str, ...]:
    """Require accepted, reviewed, fully adjudicated research for a memo draft.

    Financial projections are a separate requested artifact, not a prerequisite
    for a research memo that identifies missing financial evidence explicitly.
    """
    blockers = []
    if coverage.get("coverage_complete") is not True or coverage.get("omitted_passages") != 0:
        blockers.append("source_coverage_incomplete")
    if memo.get("state") != "accepted":
        blockers.append("memo_not_accepted")
    if not memo.get("review_response_id"):
        blockers.append("memo_review_missing")
    if not memo.get("source_hash"):
        blockers.append("memo_source_version_missing")
    sections = memo.get("sections")
    if not isinstance(sections, (list, tuple)) or not sections:
        blockers.append("memo_sections_missing")
    return tuple(blockers)


def deck_blockers(
    plan: Mapping | None,
    *,
    memo: Mapping,
    source_statuses: Mapping[str, str],
) -> tuple[str, ...]:
    """Check a separately recorded slide plan before an intro deck draft.

    ``source_statuses`` is a trusted, revision-bound adjudication map supplied
    by the caller. A source marked unresolved or contradicted cannot support a
    slide marked supported. Unknown slides may describe missing evidence.
    """
    if not isinstance(plan, Mapping):
        return ("deck_plan_missing",)
    blockers = []
    if not plan.get("model_response_id") or plan.get("model_response_id") in {
        memo.get("review_response_id"), memo.get("part_a_response_id"),
        memo.get("part_b_response_id")
    }:
        blockers.append("deck_plan_response_missing_or_reused")
    if (not plan.get("source_hash") or plan.get("source_hash") != memo.get("source_hash")
            or plan.get("memo_review_response_id") != memo.get("review_response_id")):
        blockers.append("deck_plan_provenance_mismatch")
    slides = plan.get("slides")
    if not isinstance(slides, (list, tuple)) or not slides:
        return tuple(blockers + ["deck_slides_missing"])
    ids = set()
    for index, slide in enumerate(slides):
        prefix = f"slide_{index}"
        if not isinstance(slide, Mapping):
            blockers.append(f"{prefix}_invalid")
            continue
        slide_id = slide.get("slide_id")
        if not isinstance(slide_id, str) or not slide_id.strip() or slide_id in ids:
            blockers.append(f"{prefix}_id_missing_or_duplicate")
        else:
            ids.add(slide_id)
        if not isinstance(slide.get("title"), str) or not slide["title"].strip():
            blockers.append(f"{prefix}_title_missing")
        message = slide.get("message")
        if not isinstance(message, str) or not 15 <= len(message.strip()) <= 240:
            blockers.append(f"{prefix}_message_out_of_bounds")
        status = slide.get("evidence_status")
        if status not in {"supported", "unresolved", "missing"}:
            blockers.append(f"{prefix}_evidence_status_invalid")
            continue
        source_ids = slide.get("source_ids")
        if (not isinstance(source_ids, (list, tuple)) or
                any(not isinstance(item, str) or not item for item in source_ids) or
                len(source_ids) != len(set(source_ids))):
            blockers.append(f"{prefix}_source_ids_invalid")
            continue
        if status == "missing":
            if source_ids:
                blockers.append(f"{prefix}_missing_claim_has_sources")
            continue
        if not source_ids:
            blockers.append(f"{prefix}_sources_missing")
            continue
        if any(source_id not in source_statuses for source_id in source_ids):
            blockers.append(f"{prefix}_source_unknown")
        if status == "supported" and any(
            source_statuses.get(source_id) != "supported" for source_id in source_ids
        ):
            blockers.append(f"{prefix}_unsupported_as_supported")
    return tuple(blockers)
