"""
Coverage for the pure decision-application functions introduced by the
Milestone 1 refactor (agents/review_checkpoint.py). This is the only
regression check available for these paths -- there's no prior test suite
and main.py's CLI behavior must not change, so these tests exist to catch
a future edit that silently breaks the logic a web API will depend on.
"""
from conftest import DEAL, TENANT, make_extraction_result

from agents.review_checkpoint import (
    apply_cap_table_decision,
    apply_field_decision,
    apply_finding_decision,
    apply_funding_history_decision,
    apply_lead_decision,
    is_ready_for_compilation,
    recompute_deal_review_status,
)
from schemas import (
    CapTableRow,
    DealStatus,
    FieldStatus,
    FundingRound,
    LeadStatus,
    ResearchFinding,
    SourcedLead,
)


# --- apply_field_decision -------------------------------------------------

def test_approve_sets_status_and_logs_audit():
    result = make_extraction_result()
    outcome = apply_field_decision(result, "arr", "alice", "approve")

    assert result.arr.status == FieldStatus.APPROVED
    assert result.arr.reviewer == "alice"
    assert outcome.resolved is True
    assert len(outcome.audit_events) == 1
    assert outcome.audit_events[0].action == "approve"
    assert outcome.audit_events[0].target_id == "arr"


def test_edit_sets_value_and_status():
    result = make_extraction_result()
    outcome = apply_field_decision(result, "arr", "alice", "edit", new_value="2500000", note="corrected")

    assert result.arr.value == 2_500_000.0
    assert result.arr.status == FieldStatus.EDITED
    assert result.arr.edit_note == "corrected"
    assert outcome.resolved is True


def test_edit_with_non_numeric_value_does_not_crash():
    """Regression test for the exact crash bug this refactor fixes: a
    reviewer typing a non-numeric edit value must never raise."""
    result = make_extraction_result()
    outcome = apply_field_decision(result, "arr", "alice", "edit", new_value="not-a-number")

    assert outcome.resolved is False
    assert "isn't a number" in outcome.message
    # Original value must be untouched -- a bad edit doesn't corrupt state.
    assert result.arr.value == 2_400_000
    assert result.arr.status != FieldStatus.EDITED


def test_edit_with_blank_value_sets_none():
    result = make_extraction_result()
    outcome = apply_field_decision(result, "arr", "alice", "edit", new_value="")
    assert result.arr.value is None
    assert outcome.resolved is True


def test_acknowledge_not_found():
    result = make_extraction_result()
    outcome = apply_field_decision(result, "mrr", "alice", "acknowledge")

    assert result.mrr.reviewer == "alice"
    assert result.mrr.reviewed_at is not None
    assert outcome.resolved is True
    assert outcome.audit_events[0].action == "acknowledge_not_found"


def test_reject_without_retry_fn_resolves_immediately_as_rejected():
    result = make_extraction_result()
    outcome = apply_field_decision(result, "arr", "alice", "reject", note="looks wrong")

    assert result.arr.status == FieldStatus.REJECTED
    assert outcome.resolved is True
    assert "manual input" in outcome.message


def test_reject_with_retry_fn_reruns_and_stays_unresolved():
    result = make_extraction_result()
    calls = []

    def fake_retry(document, note):
        calls.append(note)
        retried = make_extraction_result()
        retried.arr.value = 9_999_999  # a different value, proving the retry took effect
        return retried

    outcome = apply_field_decision(
        result, "arr", "alice", "reject", note="looks wrong",
        document=object(), retry_extraction=fake_retry,
    )

    assert calls == ["looks wrong"]
    assert result.arr.value == 9_999_999
    assert result.arr.retry_count == 1
    assert outcome.resolved is False
    assert outcome.retries_used == 1


def test_reject_retries_are_bounded_at_max_auto_retries():
    result = make_extraction_result()

    def fake_retry(document, note):
        retried = make_extraction_result()
        return retried

    outcome = None
    for _ in range(5):  # far more than MAX_AUTO_RETRIES=2
        outcome = apply_field_decision(
            result, "arr", "alice", "reject", note="still wrong",
            document=object(), retry_extraction=fake_retry,
        )
        if outcome.resolved:
            break

    assert outcome.resolved is True
    assert outcome.retries_used == 2
    assert "couldn't resolve after 2 retries" in outcome.message


def test_unknown_decision_raises():
    result = make_extraction_result()
    try:
        apply_field_decision(result, "arr", "alice", "not_a_real_decision")
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- apply_cap_table_decision / apply_funding_history_decision -----------

def test_cap_table_empty_auto_acknowledges_regardless_of_decision():
    result = make_extraction_result()
    assert result.cap_table == []

    outcome = apply_cap_table_decision(result, "alice", "approve")  # decision is ignored when empty

    assert result.cap_table_status == FieldStatus.NOT_FOUND
    assert outcome.resolved is True
    assert outcome.audit_events[0].action == "acknowledge_not_found"


def test_cap_table_approve_with_rows():
    result = make_extraction_result(cap_table=[CapTableRow(holder="Founders", pct=80)])
    outcome = apply_cap_table_decision(result, "alice", "approve")

    assert result.cap_table_status == FieldStatus.APPROVED
    assert outcome.resolved is True


def test_funding_history_reject_with_retry():
    result = make_extraction_result(
        funding_history=[FundingRound(round_name="Seed", amount=1_500_000, source_block_id="blk_3")],
    )

    def fake_retry(document, note):
        retried = make_extraction_result()
        retried.funding_history = [FundingRound(round_name="Seed (corrected)", amount=1_600_000, source_block_id="blk_3")]
        return retried

    outcome = apply_funding_history_decision(
        result, "alice", "reject", note="amount looks off",
        document=object(), retry_extraction=fake_retry,
    )

    assert result.funding_history[0].round_name == "Seed (corrected)"
    assert result.funding_history_retry_count == 1
    assert outcome.resolved is False


# --- apply_finding_decision / apply_lead_decision -------------------------

def test_apply_finding_decision_approve():
    finding = ResearchFinding(
        tenant_id=TENANT, deal_id=DEAL, topic="oss_traction", content="...",
        source_type="github",
    )
    event = apply_finding_decision(finding, "alice", "approve")
    assert finding.status == FieldStatus.APPROVED
    assert event.action == "approve"


def test_apply_lead_decision_dismiss():
    lead = SourcedLead(tenant_id=TENANT, company_name="Acme")
    event = apply_lead_decision(lead, "alice", "dismiss")
    assert lead.status == LeadStatus.DISMISSED
    assert event.action == "dismiss"
    assert event.deal_id == f"lead:{lead.id}"


# --- recompute_deal_review_status -----------------------------------------

def test_recompute_status_needs_manual_input_when_fields_unresolved():
    result = make_extraction_result()  # arr etc. still "proposed"
    assert recompute_deal_review_status(result) == DealStatus.NEEDS_MANUAL_INPUT


def test_recompute_status_reviewed_when_everything_resolved():
    result = make_extraction_result()
    for name in ("arr", "arr_prior_year", "burn_monthly", "cash_on_hand", "runway_months", "headcount"):
        apply_field_decision(result, name, "alice", "approve")
    apply_field_decision(result, "mrr", "alice", "acknowledge")
    apply_field_decision(result, "growth_rate_yoy", "alice", "acknowledge")
    apply_cap_table_decision(result, "alice", "approve")  # empty -> auto not_found
    apply_funding_history_decision(result, "alice", "approve")  # empty -> auto not_found

    assert is_ready_for_compilation(result) is True
    assert recompute_deal_review_status(result) == DealStatus.REVIEWED
