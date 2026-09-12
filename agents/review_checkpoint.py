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
"""
from __future__ import annotations

from typing import Callable, Optional

from schemas import (
    AuditEvent,
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


def _fields_touched_by_flag(flag: str) -> set[str]:
    touched = set()
    if "runway_months" in flag:
        touched.update({"runway_months", "cash_on_hand", "burn_monthly"})
    if "growth_rate_yoy" in flag:
        touched.update({"growth_rate_yoy", "arr", "arr_prior_year"})
    if "cap_table" in flag:
        touched.add("cap_table")
    return touched


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
    retries = 0
    while True:
        ev: ExtractedValue = getattr(result, name)
        _print_field(name, ev, flagged)

        not_found = ev.status == FieldStatus.NOT_FOUND
        if not_found:
            prompt = "  [k]acknowledge not-found / [e]dit to supply manually: "
            allowed = {"k", "e"}
        else:
            prefix = "  (flagged -- approve individually) " if flagged else "  "
            prompt = prefix + "[a]pprove / [e]dit / [r]eject: "
            allowed = {"a", "e", "r"}

        choice = input(prompt).strip().lower()
        if choice not in allowed:
            print(f"  please enter one of: {', '.join(sorted(allowed))}")
            continue

        if choice == "k":
            ev.reviewer = reviewer
            ev.reviewed_at = utcnow()
            audit.append(AuditEvent(
                tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="acknowledge_not_found",
                target_id=name, before=None, after=None,
            ))
            return

        if choice == "a":
            before = ev.status.value
            ev.status = FieldStatus.APPROVED
            ev.reviewer = reviewer
            ev.reviewed_at = utcnow()
            audit.append(AuditEvent(
                tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="approve",
                target_id=name, before=before, after=ev.status.value,
            ))
            return

        if choice == "e":
            raw = input(f"  new value for {name}: ").strip()
            note = input("  edit note: ").strip()
            before = ev.value
            ev.value = float(raw) if raw else None
            ev.status = FieldStatus.EDITED
            ev.reviewer = reviewer
            ev.reviewed_at = utcnow()
            ev.edit_note = note
            ev.source_block_id = ev.source_block_id or "manual_reviewer_input"
            audit.append(AuditEvent(
                tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="edit",
                target_id=name, before=before, after=ev.value,
            ))
            return

        if choice == "r":
            note = input("  rejection note (what's wrong): ").strip()
            ev.status = FieldStatus.REJECTED
            ev.edit_note = note
            audit.append(AuditEvent(
                tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="reject",
                target_id=name, before=ev.value, after=None,
            ))

            if retries >= MAX_AUTO_RETRIES or not retry_extraction or not document:
                print(f"  -> couldn't resolve after {retries} retries, needs manual input.")
                return

            retries += 1
            print(f"  -> re-running extraction with reviewer's note (retry {retries}/{MAX_AUTO_RETRIES})...")
            retried_result = retry_extraction(document, note)
            setattr(result, name, getattr(retried_result, name))
            continue


def _review_cap_table(
    result: ExtractionResult,
    reviewer: str,
    document: Optional[Document],
    retry_extraction: Optional[RetryFn],
    audit: list[AuditEvent],
) -> None:
    """cap_table is reviewed as one unit (all rows share one source citation
    already, per the Extraction Agent's cap_table_source_block_id rule)."""
    retries = 0
    while True:
        rows = result.cap_table
        if not rows:
            result.cap_table_status = FieldStatus.NOT_FOUND
            result.cap_table_reviewer = reviewer
            result.cap_table_reviewed_at = utcnow()
            audit.append(AuditEvent(
                tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="acknowledge_not_found", target_id="cap_table",
            ))
            return

        print(f"\n--- cap_table ({len(rows)} row(s)) source_block_id={result.cap_table_source_block_id} ---")
        for row in rows:
            print(f"  {row.holder}: {row.pct}% ({row.share_class or '-'})")

        choice = input("  [a]pprove / [r]eject: ").strip().lower()
        if choice not in {"a", "r"}:
            print("  please enter a or r")
            continue

        if choice == "a":
            result.cap_table_status = FieldStatus.APPROVED
            result.cap_table_reviewer = reviewer
            result.cap_table_reviewed_at = utcnow()
            audit.append(AuditEvent(
                tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="approve",
                target_id="cap_table", before="proposed", after="approved",
            ))
            return

        note = input("  rejection note: ").strip()
        result.cap_table_status = FieldStatus.REJECTED
        audit.append(AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="reject",
            target_id="cap_table", before=len(rows), after=None,
        ))

        if retries >= MAX_AUTO_RETRIES or not retry_extraction or not document:
            print(f"  -> couldn't resolve after {retries} retries, needs manual input.")
            return

        retries += 1
        print(f"  -> re-running extraction with reviewer's note (retry {retries}/{MAX_AUTO_RETRIES})...")
        retried = retry_extraction(document, note)
        result.cap_table = retried.cap_table
        result.cap_table_source_block_id = retried.cap_table_source_block_id


def _review_funding_history(
    result: ExtractionResult,
    reviewer: str,
    document: Optional[Document],
    retry_extraction: Optional[RetryFn],
    audit: list[AuditEvent],
) -> None:
    """funding_history is reviewed as one unit; each round still carries its
    own source_block_id for compilation-time citation (§7 rule 1)."""
    retries = 0
    while True:
        rounds = result.funding_history
        if not rounds:
            result.funding_history_status = FieldStatus.NOT_FOUND
            result.funding_history_reviewer = reviewer
            result.funding_history_reviewed_at = utcnow()
            audit.append(AuditEvent(
                tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="acknowledge_not_found", target_id="funding_history",
            ))
            return

        print(f"\n--- funding_history ({len(rounds)} round(s)) ---")
        for r in rounds:
            print(f"  {r.round_name}: {r.amount} on {r.date}, led by {r.lead_investor} [source={r.source_block_id}]")

        choice = input("  [a]pprove / [r]eject: ").strip().lower()
        if choice not in {"a", "r"}:
            print("  please enter a or r")
            continue

        if choice == "a":
            result.funding_history_status = FieldStatus.APPROVED
            result.funding_history_reviewer = reviewer
            result.funding_history_reviewed_at = utcnow()
            audit.append(AuditEvent(
                tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="approve",
                target_id="funding_history", before="proposed", after="approved",
            ))
            return

        note = input("  rejection note: ").strip()
        result.funding_history_status = FieldStatus.REJECTED
        audit.append(AuditEvent(
            tenant_id=result.tenant_id, deal_id=result.deal_id, actor=reviewer, action="reject",
            target_id="funding_history", before=len(rounds), after=None,
        ))

        if retries >= MAX_AUTO_RETRIES or not retry_extraction or not document:
            print(f"  -> couldn't resolve after {retries} retries, needs manual input.")
            return

        retries += 1
        print(f"  -> re-running extraction with reviewer's note (retry {retries}/{MAX_AUTO_RETRIES})...")
        retried = retry_extraction(document, note)
        result.funding_history = retried.funding_history


def review_extraction(
    result: ExtractionResult,
    reviewer: str,
    document: Optional[Document] = None,
    retry_extraction: Optional[RetryFn] = None,
) -> tuple[ExtractionResult, list[AuditEvent]]:
    """Interactive review pass over one ExtractionResult. Mutates and
    returns `result` plus the audit trail generated this session."""
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

        finding.status = FieldStatus.APPROVED if choice == "a" else FieldStatus.REJECTED
        audit.append(AuditEvent(
            tenant_id=finding.tenant_id, deal_id=finding.deal_id, actor=reviewer,
            action="approve" if choice == "a" else "reject",
            target_id=finding.id, before="proposed", after=finding.status.value,
        ))

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

        lead.status = LeadStatus.REVIEWED if choice == "k" else LeadStatus.DISMISSED
        audit.append(AuditEvent(
            tenant_id=lead.tenant_id,
            deal_id=f"lead:{lead.id}",  # no real Deal exists yet for a pre-promotion lead
            actor=reviewer,
            action="keep" if choice == "k" else "dismiss",
            target_id=lead.id, before="new", after=lead.status.value,
        ))

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
