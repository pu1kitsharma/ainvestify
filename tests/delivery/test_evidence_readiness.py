from delivery.evidence_readiness import deck_blockers, memo_blockers


MEMO = {
    "state": "accepted", "review_response_id": "review-1", "source_hash": "source-v1",
    "part_a_response_id": "draft-1", "sections": [("Analysis", "Body", "[S1]")],
}
COVERAGE = {"coverage_complete": True, "omitted_passages": 0}


def plan(status="supported", sources=None):
    return {
        "model_response_id": "deck-1", "memo_review_response_id": "review-1",
        "source_hash": "source-v1", "slides": [{
            "slide_id": "slide-1", "title": "Offering",
            "message": "The cited material describes the offering.",
            "source_ids": ["S1"] if sources is None else sources,
            "evidence_status": status,
        }],
    }


def test_memo_draft_does_not_require_projection():
    assert memo_blockers(MEMO, COVERAGE) == ()


def test_memo_requires_review_and_full_coverage():
    assert memo_blockers({**MEMO, "review_response_id": None},
                         {**COVERAGE, "omitted_passages": 1}) == (
        "source_coverage_incomplete", "memo_review_missing")


def test_deck_requires_separate_recorded_plan():
    assert deck_blockers(None, memo=MEMO, source_statuses={"S1": "supported"}) == (
        "deck_plan_missing",)
    assert deck_blockers(plan(), memo=MEMO, source_statuses={"S1": "supported"}) == ()


def test_unresolved_source_cannot_be_presented_as_supported():
    assert "slide_0_unsupported_as_supported" in deck_blockers(
        plan(), memo=MEMO, source_statuses={"S1": "unresolved"})
    assert deck_blockers(plan(status="unresolved"), memo=MEMO,
                         source_statuses={"S1": "unresolved"}) == ()


def test_missing_evidence_can_be_shown_explicitly():
    assert deck_blockers(plan(status="missing", sources=[]), memo=MEMO,
                         source_statuses={}) == ()


def test_stale_or_reused_model_response_is_blocked():
    stale = {**plan(), "source_hash": "source-v0", "model_response_id": "draft-1"}
    assert deck_blockers(stale, memo=MEMO, source_statuses={"S1": "supported"}) == (
        "deck_plan_response_missing_or_reused", "deck_plan_provenance_mismatch")
