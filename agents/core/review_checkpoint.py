"""
Human Review Checkpoint — architecture doc §5.5 / §12.

This is the interrupt/resume gate the planner is supposed to pause at once
Extraction (+ Research/Analytics, once built) has produced draft content.
Phase 0 has no web UI yet, so this is a CLI stand-in for the "single screen
per deal" described in §12 -- same rules, no polished frontend: approve /
edit / reject per field, cross-check mismatches can't be silently bulk-
approved, an edit becomes the new source of truth, and a reject gets a
bounded number of automatic re-extraction retries before falling back to
"needs manual input" (§5.5).

is_ready_for_compilation() is the actual enforcement point: the Compilation
Agent (§5.7) must never run against a result that hasn't cleared this gate,
per §12 ("enforced by the planner, not left as a convention").

Frontend-readiness refactor: every decision (approve/edit/reject/acknowledge
a field; approve/reject a cap table or funding history; approve/reject a
research finding; keep/dismiss a lead) is implemented as a pure
`apply_*`/`recompute_*` function with no `input()`/`print()` in it -- so a
future API layer can call the exact same decision logic a web request
drives, not a parallel reimplementation that could drift from the CLI's.
The CLI functions below (`_review_one_field`, `_review_cap_table`, etc.)
are now thin loops: gather input, call the pure function, print its
result, loop or return based on `resolved`. `main.py`'s behavior is
unchanged by this -- same prompts, same order, same printed output.
"""
from __future__ import annotations

from typing import Callable, Optional

from pydantic import BaseModel

from schemas import (
    AuditEvent,
    DealStatus,
    Document,
    ExtractedValue,
    ExtractionResult,
    FieldStatus,
    LeadStatus,
    ResearchFinding,
    SourcedLead,
    utcnow,
)

MAX_AUTO_RETRIES = 2

REQUIRED_SCALAR_FIELDS = [
    "arr", "arr_prior_year", "mrr", "growth_rate_yoy", "burn_monthly",
    "cash_on_hand", "runway_months", "headcount",
]

# (document, reviewer_feedback_note) -> a fresh ExtractionResult re-run with
# that feedback folded into the prompt. Injected rather than imported
# directly so this module doesn't have to know which model/agent produced
# the original result.
RetryFn = Callable[[Document, str], ExtractionResult]


class ReviewDecisionOutcome(BaseModel):
    """Result of applying one review decision. `resolved=False` doesn't mean
    an error -- it means the same field/unit needs another decision (a
    reject triggered a retry and the freshly re-extracted value needs a
    fresh look, or an edit's value couldn't be parsed and needs re-entry).
    The caller re-reads the mutated field/unit off the `ExtractionResult`
    it already has; this outcome only carries what a caller can't get from
    re-reading that object (whether more input is needed, how many retries
    have been used, and the audit trail this call produced)."""

    resolved: bool
    retries_used: int
    audit_events: list[AuditEvent]
    message: Optional[str] = None


def _fields_touched_by_flag(flag: str) -> set[str]:
    touched = set()
    if "runway_months" in flag:
        touched.update({"runway_months", "cash_on_hand", "burn_monthly"})
    if "growth_rate_yoy" in flag:
        touched.update({"growth_rate_yoy", "arr", "arr_prior_year"})
    if "cap_table" in flag:
        touched.add("cap_table")
    return touched


# --- Pure decision-application functions ------------------------------
# No input()/print() anywhere below this point until the CLI wrappers.

def apply_field_decision(
    result: ExtractionResult,
    field_name: str,
    reviewer: str,
    decision: str,  # "approve" | "edit" | "reject" | "acknowledge"
    *,
    new_value: Optional[str] = None,
    note: Optional[str] = None,
    document: Optional[Document] = None,
    retry_extraction: Optional[RetryFn] = None,
) -> ReviewDecisionOutcome:
    """Apply one decision to one scalar field, mutating `result` in place.
    `new_value` is the raw string a human typed (or a JSON number rendered
    as a string by an API caller) -- parsed here, not by the caller, so
    every caller gets the same graceful handling of a bad value instead of
    each needing its own try/except (this is the fix for the crash bug: a
    non-numeric edit value now returns resolved=False with a message,
    never raises)."""
    ev: ExtractedValue = getattr(result, field_name)

    if decision == "acknowledge":
        ev.reviewer = reviewer
        ev.reviewed_at = utcnow()
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer,
            action="acknowledge_not_found", target_id=field_name, before=None, after=None,
        )]
        return ReviewDecisionOutcome(resolved=True, retries_used=ev.retry_count, audit_events=audit)

    if decision == "approve":
        before = ev.status.value
        ev.status = FieldStatus.APPROVED
        ev.reviewer = reviewer
        ev.reviewed_at = utcnow()
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="approve",
            target_id=field_name, before=before, after=ev.status.value,
        )]
        return ReviewDecisionOutcome(resolved=True, retries_used=ev.retry_count, audit_events=audit)

    if decision == "edit":
        try:
            parsed = float(new_value) if new_value else None
        except (TypeError, ValueError):
            return ReviewDecisionOutcome(
                resolved=False, retries_used=ev.retry_count, audit_events=[],
                message=f"'{new_value}' isn't a number -- value not changed, try again.",
            )
        before = ev.value
        ev.value = parsed
        ev.status = FieldStatus.EDITED
        ev.reviewer = reviewer
        ev.reviewed_at = utcnow()
        ev.edit_note = note
        ev.source_block_id = ev.source_block_id or "manual_reviewer_input"
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="edit",
            target_id=field_name, before=before, after=ev.value,
        )]
        return ReviewDecisionOutcome(resolved=True, retries_used=ev.retry_count, audit_events=audit)

    if decision == "reject":
        ev.status = FieldStatus.REJECTED
        ev.edit_note = note
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="reject",
            target_id=field_name, before=ev.value, after=None,
        )]

        if ev.retry_count >= MAX_AUTO_RETRIES or not retry_extraction or not document:
            return ReviewDecisionOutcome(
                resolved=True, retries_used=ev.retry_count, audit_events=audit,
                message=f"couldn't resolve after {ev.retry_count} retries, needs manual input.",
            )

        next_retry = ev.retry_count + 1
        retried_result = retry_extraction(document, note or "")
        new_ev: ExtractedValue = getattr(retried_result, field_name)
        new_ev.retry_count = next_retry
        setattr(result, field_name, new_ev)
        return ReviewDecisionOutcome(
            resolved=False, retries_used=next_retry, audit_events=audit,
            message=f"re-ran extraction with reviewer's note (retry {next_retry}/{MAX_AUTO_RETRIES}).",
        )

    raise ValueError(f"unknown field decision {decision!r}")


def apply_cap_table_decision(
    result: ExtractionResult,
    reviewer: str,
    decision: str,  # "approve" | "reject" | "acknowledge"
    *,
    note: Optional[str] = None,
    document: Optional[Document] = None,
    retry_extraction: Optional[RetryFn] = None,
) -> ReviewDecisionOutcome:
    """cap_table is reviewed as one unit (all rows share one source
    citation, per the Extraction Agent's cap_table_source_block_id rule).
    An empty cap table is always auto-acknowledged as not-found, regardless
    of `decision` -- there's nothing for a human to approve/reject."""
    if not result.cap_table:
        result.cap_table_status = FieldStatus.NOT_FOUND
        result.cap_table_reviewer = reviewer
        result.cap_table_reviewed_at = utcnow()
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer,
            action="acknowledge_not_found", target_id="cap_table",
        )]
        return ReviewDecisionOutcome(resolved=True, retries_used=result.cap_table_retry_count, audit_events=audit)

    if decision == "approve":
        result.cap_table_status = FieldStatus.APPROVED
        result.cap_table_reviewer = reviewer
        result.cap_table_reviewed_at = utcnow()
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="approve",
            target_id="cap_table", before="proposed", after="approved",
        )]
        return ReviewDecisionOutcome(resolved=True, retries_used=result.cap_table_retry_count, audit_events=audit)

    if decision == "reject":
        result.cap_table_status = FieldStatus.REJECTED
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="reject",
            target_id="cap_table", before=len(result.cap_table), after=None,
        )]

        if result.cap_table_retry_count >= MAX_AUTO_RETRIES or not retry_extraction or not document:
            return ReviewDecisionOutcome(
                resolved=True, retries_used=result.cap_table_retry_count, audit_events=audit,
                message=f"couldn't resolve after {result.cap_table_retry_count} retries, needs manual input.",
            )

        next_retry = result.cap_table_retry_count + 1
        retried = retry_extraction(document, note or "")
        result.cap_table = retried.cap_table
        result.cap_table_source_block_id = retried.cap_table_source_block_id
        result.cap_table_retry_count = next_retry
        return ReviewDecisionOutcome(
            resolved=False, retries_used=next_retry, audit_events=audit,
            message=f"re-ran extraction with reviewer's note (retry {next_retry}/{MAX_AUTO_RETRIES}).",
        )

    raise ValueError(f"unknown cap_table decision {decision!r}")


def apply_funding_history_decision(
    result: ExtractionResult,
    reviewer: str,
    decision: str,  # "approve" | "reject" | "acknowledge"
    *,
    note: Optional[str] = None,
    document: Optional[Document] = None,
    retry_extraction: Optional[RetryFn] = None,
) -> ReviewDecisionOutcome:
    """funding_history is reviewed as one unit; each round still carries its
    own source_block_id for compilation-time citation (§7 rule 1)."""
    if not result.funding_history:
        result.funding_history_status = FieldStatus.NOT_FOUND
        result.funding_history_reviewer = reviewer
        result.funding_history_reviewed_at = utcnow()
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer,
            action="acknowledge_not_found", target_id="funding_history",
        )]
        return ReviewDecisionOutcome(resolved=True, retries_used=result.funding_history_retry_count, audit_events=audit)

    if decision == "approve":
        result.funding_history_status = FieldStatus.APPROVED
        result.funding_history_reviewer = reviewer
        result.funding_history_reviewed_at = utcnow()
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="approve",
            target_id="funding_history", before="proposed", after="approved",
        )]
        return ReviewDecisionOutcome(resolved=True, retries_used=result.funding_history_retry_count, audit_events=audit)

    if decision == "reject":
        result.funding_history_status = FieldStatus.REJECTED
        audit = [AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="reject",
            target_id="funding_history", before=len(result.funding_history), after=None,
        )]

        if result.funding_history_retry_count >= MAX_AUTO_RETRIES or not retry_extraction or not document:
            return ReviewDecisionOutcome(
                resolved=True, retries_used=result.funding_history_retry_count, audit_events=audit,
                message=f"couldn't resolve after {result.funding_history_retry_count} retries, needs manual input.",
            )

        next_retry = result.funding_history_retry_count + 1
        retried = retry_extraction(document, note or "")
        result.funding_history = retried.funding_history
        result.funding_history_retry_count = next_retry
        return ReviewDecisionOutcome(
            resolved=False, retries_used=next_retry, audit_events=audit,
            message=f"re-ran extraction with reviewer's note (retry {next_retry}/{MAX_AUTO_RETRIES}).",
        )

    raise ValueError(f"unknown funding_history decision {decision!r}")


def apply_finding_decision(finding: ResearchFinding, reviewer: str, decision: str) -> AuditEvent:
    """decision in {"approve", "reject"}."""
    finding.status = FieldStatus.APPROVED if decision == "approve" else FieldStatus.REJECTED
    return AuditEvent(
        tenant_id=finding.tenant_id, deal_id=finding.deal_id, actor=reviewer,
        action=decision, target_id=finding.id, before="proposed", after=finding.status.value,
    )


def apply_lead_decision(lead: SourcedLead, reviewer: str, decision: str) -> AuditEvent:
    """decision in {"keep", "dismiss"}."""
    lead.status = LeadStatus.REVIEWED if decision == "keep" else LeadStatus.DISMISSED
    return AuditEvent(
        tenant_id=lead.tenant_id,
        deal_id=f"lead:{lead.id}",  # no real Deal exists yet for a pre-promotion lead
        actor=reviewer,
        action=decision, target_id=lead.id, before="new", after=lead.status.value,
    )


def recompute_deal_review_status(result: ExtractionResult) -> DealStatus:
    """The REVIEWED-vs-NEEDS_MANUAL_INPUT decision, extracted so both the
    CLI (after a full batch) and every API decision endpoint (after each
    single field) can call it -- a frontend's "ready for compilation"
    banner can then update live as the reviewer works, not only at the end
    of a whole pass."""
    return DealStatus.REVIEWED if is_ready_for_compilation(result) else DealStatus.NEEDS_MANUAL_INPUT


# --- CLI-only wrappers --------------------------------------------------
# Thin input()/print() loops delegating every decision to the pure
# functions above. Behavior (prompts, order, printed output) is unchanged
# from before this refactor.

def _print_field(name: str, ev: ExtractedValue, flagged: bool) -> None:
    marker = "  [CROSS-CHECK MISMATCH]" if flagged else ""
    print(f"\n--- {name}{marker} ---")
    print(f"  value:            {ev.value}{(' ' + ev.unit) if ev.unit else ''}")
    print(f"  source_block_id:  {ev.source_block_id}")
    print(f"  source_page:      {ev.source_page}")
    print(f"  status:           {ev.status.value}")
    if ev.reason:
        print(f"  reason:           {ev.reason}")


def _review_one_field(
    result: ExtractionResult,
    name: str,
    reviewer: str,
    flagged: bool,
    document: Optional[Document],
    retry_extraction: Optional[RetryFn],
    audit: list[AuditEvent],
) -> None:
    while True:
        ev: ExtractedValue = getattr(result, name)
        _print_field(name, ev, flagged)

        not_found = ev.status == FieldStatus.NOT_FOUND
        if not_found:
            prompt = "  [k]acknowledge not-found / [e]dit to supply manually: "
            allowed = {"k": "acknowledge", "e": "edit"}
        else:
            prefix = "  (flagged -- approve individually) " if flagged else "  "
            prompt = prefix + "[a]pprove / [e]dit / [r]eject: "
            allowed = {"a": "approve", "e": "edit", "r": "reject"}

        choice = input(prompt).strip().lower()
        if choice not in allowed:
            print(f"  please enter one of: {', '.join(sorted(allowed))}")
            continue

        decision = allowed[choice]
        kwargs: dict = {}
        if decision == "edit":
            kwargs["new_value"] = input(f"  new value for {name}: ").strip()
            kwargs["note"] = input("  edit note: ").strip()
        elif decision == "reject":
            kwargs["note"] = input("  rejection note (what's wrong): ").strip()

        outcome = apply_field_decision(
            result, name, reviewer, decision,
            document=document, retry_extraction=retry_extraction, **kwargs,
        )
        audit.extend(outcome.audit_events)
        if outcome.message:
            print(f"  -> {outcome.message}")
        if outcome.resolved:
            return


def _review_cap_table(
    result: ExtractionResult,
    reviewer: str,
    document: Optional[Document],
    retry_extraction: Optional[RetryFn],
    audit: list[AuditEvent],
) -> None:
    while True:
        rows = result.cap_table
        if not rows:
            outcome = apply_cap_table_decision(
                result, reviewer, "acknowledge", document=document, retry_extraction=retry_extraction,
            )
            audit.extend(outcome.audit_events)
            return

        print(f"\n--- cap_table ({len(rows)} row(s)) source_block_id={result.cap_table_source_block_id} ---")
        for row in rows:
            print(f"  {row.holder}: {row.pct}% ({row.share_class or '-'})")

        choice = input("  [a]pprove / [r]eject: ").strip().lower()
        if choice not in {"a", "r"}:
            print("  please enter a or r")
            continue

        decision = "approve" if choice == "a" else "reject"
        note = input("  rejection note: ").strip() if decision == "reject" else None

        outcome = apply_cap_table_decision(
            result, reviewer, decision, note=note, document=document, retry_extraction=retry_extraction,
        )
        audit.extend(outcome.audit_events)
        if outcome.message:
            print(f"  -> {outcome.message}")
        if outcome.resolved:
            return


def _review_funding_history(
    result: ExtractionResult,
    reviewer: str,
    document: Optional[Document],
    retry_extraction: Optional[RetryFn],
    audit: list[AuditEvent],
) -> None:
    while True:
        rounds = result.funding_history
        if not rounds:
            outcome = apply_funding_history_decision(
                result, reviewer, "acknowledge", document=document, retry_extraction=retry_extraction,
            )
            audit.extend(outcome.audit_events)
            return

        print(f"\n--- funding_history ({len(rounds)} round(s)) ---")
        for r in rounds:
            print(f"  {r.round_name}: {r.amount} on {r.date}, led by {r.lead_investor} [source={r.source_block_id}]")

        choice = input("  [a]pprove / [r]eject: ").strip().lower()
        if choice not in {"a", "r"}:
            print("  please enter a or r")
            continue

        decision = "approve" if choice == "a" else "reject"
        note = input("  rejection note: ").strip() if decision == "reject" else None

        outcome = apply_funding_history_decision(
            result, reviewer, decision, note=note, document=document, retry_extraction=retry_extraction,
        )
        audit.extend(outcome.audit_events)
        if outcome.message:
            print(f"  -> {outcome.message}")
        if outcome.resolved:
            return


def review_extraction(
    result: ExtractionResult,
    reviewer: str,
    document: Optional[Document] = None,
    retry_extraction: Optional[RetryFn] = None,
) -> tuple[ExtractionResult, list[AuditEvent]]:
    """Interactive review pass over one ExtractionResult. Mutates and
    returns `result` plus the audit trail generated this session. Stays
    CLI-only (a stateful multi-step API conversation, not a single call --
    an API instead drives apply_field_decision/apply_cap_table_decision/
    apply_funding_history_decision directly, one HTTP request per
    decision)."""
    audit: list[AuditEvent] = []
    flagged_fields: set[str] = set()
    for flag in result.cross_check_flags:
        flagged_fields |= _fields_touched_by_flag(flag)

    print(f"\n=== Human Review — deal {result.deal_id} ===")
    if result.cross_check_flags:
        print("Cross-check flags:")
        for flag in result.cross_check_flags:
            print(f"  ! {flag}")

    for name in REQUIRED_SCALAR_FIELDS:
        _review_one_field(result, name, reviewer, name in flagged_fields, document, retry_extraction, audit)

    _review_cap_table(result, reviewer, document, retry_extraction, audit)
    _review_funding_history(result, reviewer, document, retry_extraction, audit)

    return result, audit


def review_research_findings(
    findings: list[ResearchFinding],
    reviewer: str,
) -> tuple[list[ResearchFinding], list[AuditEvent]]:
    """Research findings (§5.4) get the same explicit approve/reject
    discipline as extracted fields -- §10.5 is explicit that these are
    supporting/corroborating signal, never blended into the same confidence
    tier as a cited financial figure, so nothing here reaches the memo
    without a reviewer having looked at it (unlike extracted fields, an
    unreviewed finding is just left out of the memo rather than blocking
    compilation -- research is optional context, not a required field)."""
    audit: list[AuditEvent] = []
    if not findings:
        return findings, audit

    print(f"\n=== Research Findings Review ({len(findings)} finding(s)) ===")
    for finding in findings:
        print(f"\n--- [{finding.source_type}] {finding.topic} ---")
        print(f"  {finding.content}")
        print(f"  source_url: {finding.source_url}")
        choice = input("  [a]pprove / [r]eject: ").strip().lower()
        while choice not in {"a", "r"}:
            choice = input("  please enter a or r: ").strip().lower()

        decision = "approve" if choice == "a" else "reject"
        audit.append(apply_finding_decision(finding, reviewer, decision))

    return findings, audit


def review_leads(
    leads: list[SourcedLead],
    reviewer: str,
) -> tuple[list[SourcedLead], list[AuditEvent]]:
    """Sourced leads (§5.8) get the same explicit human-in-the-loop
    discipline as everything else in this pipeline: a lead is a reason to
    *look at* a company, not a claim about it, so nothing gets kept for
    follow-up without a reviewer having actually looked at the discovery
    signal behind it. Distinct from review_research_findings: a lead's
    outcome is keep-for-follow-up or dismiss, not approve/reject of a
    citation, since there's no extracted claim here to approve."""
    audit: list[AuditEvent] = []
    if not leads:
        return leads, audit

    print(f"\n=== Sourced Leads Review ({len(leads)} lead(s)) ===")
    for lead in leads:
        print(f"\n--- {lead.company_name} [{lead.sector_tag}] ---")
        for sig in lead.discovery_signals:
            print(f"  [{sig.source_type}] {sig.content}")
            print(f"  {sig.source_url}")

        choice = input("  [k]eep for follow-up / [d]ismiss: ").strip().lower()
        while choice not in {"k", "d"}:
            choice = input("  please enter k or d: ").strip().lower()

        decision = "keep" if choice == "k" else "dismiss"
        audit.append(apply_lead_decision(lead, reviewer, decision))

    return leads, audit


def is_ready_for_compilation(result: ExtractionResult) -> bool:
    """§12: Compilation can only be invoked once every required field is
    approved/edited, or not_found and reviewed (acknowledged) -- enforced
    here, not left as a convention for whatever calls this next."""
    for name in REQUIRED_SCALAR_FIELDS:
        ev: ExtractedValue = getattr(result, name)
        if ev.status in (FieldStatus.APPROVED, FieldStatus.EDITED):
            continue
        if ev.status == FieldStatus.NOT_FOUND and ev.reviewed_at is not None:
            continue
        return False

    for status_attr, reviewed_at_attr in (
        ("cap_table_status", "cap_table_reviewed_at"),
        ("funding_history_status", "funding_history_reviewed_at"),
    ):
        status = getattr(result, status_attr)
        if status in (FieldStatus.APPROVED, FieldStatus.EDITED):
            continue
        if status == FieldStatus.NOT_FOUND and getattr(result, reviewed_at_attr) is not None:
            continue
        return False

    return True
