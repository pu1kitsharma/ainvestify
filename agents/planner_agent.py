"""
Planner / Supervisor Agent — architecture doc §5.1.

Owns the per-deal state machine (Deal.status, schemas.DealStatus) and
decides which specialist agent runs next. Two distinct routing modes:

1. Happy-path progression is deterministic. The pipeline stages (ingest ->
   extract -> review -> research -> review_research -> compile) have one
   obvious next step given the current DealStatus -- routing that through
   an LLM would be theater, not intelligence.
2. A free-text directive ("the burn number looks wrong, re-check it") is
   genuinely ambiguous. That's where the small/fast model earns its place
   (§8: the Planner "needs low latency far more than deep reasoning...
   intent classification and routing, not financial analysis") --
   classifying the directive into one of the *valid* actions for the
   deal's current state, never inventing a transition that doesn't exist.

Either way, the planner's own routing decision is shown to the human and
confirmed before it executes -- not just the specialist agents' outputs.
A planner that silently re-routes a deal on its own guess is the same
"review gate doesn't mean anything" failure mode §5.7 already guards
against for Compilation, applied here to the planner's control flow.

Every state change goes through store.py so a deal can genuinely be
resumed in a later process (§5.5's "serializes state and waits"), not just
paused mid-input() within one still-running process.

The planner also owns the pre-deal half of the lifecycle now: sourcing a
candidate (§5.8) and promoting a reviewed lead into an actual Deal. A
SourcedLead has no DealStatus of its own (no Deal exists yet), so this
doesn't extend the state machine above -- it's the on-ramp into it.
Business framing (see CLAUDE.md): this system's job isn't a fund screening
deals for its own book -- it's selecting and incubating companies, then
producing the same cited, human-reviewed memo to help them raise from
institutional investors, the way a boutique bank would package a raise.
That's exactly why sourcing -> promotion -> screening has to be one
connected flow owned by one module, not three disconnected scripts.
"""
from __future__ import annotations

from typing import Optional

import ollama
from pydantic import BaseModel

from agents.analytics_agent import generate_charts
from agents.compilation_agent import (
    CompilationBlockedError,
    compile_cim,
    compile_proforma_document,
    compile_teaser,
    generate_proforma_projection,
)
from agents.extraction_agent import extract
from agents.ingestion_agent import ingest_document
from agents.research_agent import SectorNotesIndex, research_deal
from agents.review_checkpoint import (
    is_ready_for_compilation,
    recompute_deal_review_status,
    review_extraction,
    review_research_findings,
)
from agents.sourcing_agent import discover_ib_targets, discover_leads
from schemas import (
    ChartArtifact,
    Deal,
    DealStatus,
    ExtractionResult,
    InvestorContact,
    LeadStatus,
    MemoVersion,
    ResearchFinding,
    SourcedLead,
    utcnow,
)
from store import Store

# Not the fastest model (1b, 90.6 tok/s) -- confirmed live that 1b
# misclassifies free-text directives once the valid-action set grows past a
# couple of options (it picked "rerun_extraction" for "generate the
# anonymous teaser" from a state where "compile_teaser" was a valid,
# correctly-named option; 3b got it right). Same lesson as main.py's
# router: §8's "small/fast model" framing is right for the deterministic
# continue-path (which never calls this model at all) but this classifier
# genuinely needs more capacity once there are more than ~2 real choices.
PLANNER_MODEL = "llama3.2:3b"

EXTRACTION_SCHEMA_FIELDS = [
    "arr", "arr_prior_year", "mrr", "growth_rate_yoy", "burn_monthly",
    "cash_on_hand", "runway_months", "headcount", "cap_table", "funding_history",
]

# The planner's LLM call must pick from this set for the deal's current
# state -- it cannot invent a transition that doesn't exist.
VALID_ACTIONS: dict[DealStatus, list[str]] = {
    # Origination (§5.1 addendum): a real engagement needs a signed
    # mandate/term sheet before the shop acts on a company's confidential
    # documents -- ingest is deliberately not reachable from NEW directly.
    DealStatus.NEW: ["sign_mandate"],
    DealStatus.MANDATE_SIGNED: ["ingest"],
    DealStatus.INGESTED: ["extract"],
    DealStatus.EXTRACTED: ["review"],
    # Teaser and pro-forma only need approved financials (is_ready_for_
    # compilation()), not research -- real practice sends the teaser well
    # before a full CIM is even assembled, so both are valid as soon as the
    # deal is REVIEWED, not gated behind "compile" (the CIM) first. Investor
    # tracking (Roadshow, §5 Stage 5) is likewise valid once there's
    # something worth tracking outreach for.
    DealStatus.REVIEWED: [
        "research", "compile", "compile_teaser", "compile_proforma",
        "add_investor", "view_demand_book", "rerun_extraction",
    ],
    DealStatus.NEEDS_MANUAL_INPUT: ["review", "rerun_extraction"],
    DealStatus.RESEARCHED: ["review_research"],
    DealStatus.RESEARCH_REVIEWED: [
        "compile", "compile_teaser", "compile_proforma",
        "add_investor", "view_demand_book", "rerun_research", "rerun_extraction",
    ],
    # A compiled deal is exactly where §5.1's own example directive lands
    # ("redo the ARR chart with quarterly granularity") -- a revision
    # request about a *finished* memo is the normal case, not an edge case,
    # so COMPILED must allow routing back to any earlier specialist, and to
    # the other two documents in the suite (§5.7 addendum).
    DealStatus.COMPILED: [
        "recompile", "compile_teaser", "compile_proforma",
        "add_investor", "view_demand_book",
        "rerun_analytics", "rerun_extraction", "rerun_research", "done",
    ],
}

DEFAULT_ACTION: dict[DealStatus, str] = {
    DealStatus.NEW: "sign_mandate",
    DealStatus.MANDATE_SIGNED: "ingest",
    DealStatus.INGESTED: "extract",
    DealStatus.EXTRACTED: "review",
    DealStatus.REVIEWED: "research",
    DealStatus.NEEDS_MANUAL_INPUT: "review",
    DealStatus.RESEARCHED: "review_research",
    DealStatus.RESEARCH_REVIEWED: "compile",
    DealStatus.COMPILED: "done",
}

CONTINUE_WORDS = {"", "continue", "proceed", "next", "go", "ok", "okay"}


class PlannerDecision(BaseModel):
    action: str
    reasoning: str
    target_field: Optional[str] = None  # e.g. "burn_monthly" for a targeted re-extraction


# --- Routing -------------------------------------------------------------

def classify_directive(deal: Deal, directive: str) -> PlannerDecision:
    """Already fully non-interactive (no input()/print()) -- public so a
    future API's "preview what the planner would do" endpoint can call it
    directly, the same function the CLI's confirm step is built on."""
    valid = VALID_ACTIONS[deal.status]
    prompt = f"""You are the routing component of a deal-screening pipeline. A deal is
currently in state "{deal.status.value}". The valid next actions from this
state are: {valid}.

The analyst said: "{directive}"

Pick exactly one action from the valid list above that best matches what
they want. If they're asking to revise/recheck/fix a specific extracted
field (e.g. "the burn number looks wrong"), pick "rerun_extraction" and
name that field in target_field using its schema name: {EXTRACTION_SCHEMA_FIELDS}.
If they just want to proceed normally, pick the most natural next step.
Give a one-sentence reasoning. Return only the JSON object."""

    response = ollama.chat(
        model=PLANNER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=PlannerDecision.model_json_schema(),
        options={"temperature": 0},
    )
    decision = PlannerDecision.model_validate_json(response["message"]["content"])

    if decision.action not in valid:
        # Small model picked outside the allowed set -- fall back to the
        # deterministic default rather than executing an invalid transition.
        return PlannerDecision(
            action=DEFAULT_ACTION[deal.status],
            reasoning=f"Model proposed invalid action {decision.action!r} for state "
                      f"{deal.status.value!r}; falling back to the default next step.",
        )
    return decision


def _confirm_with_human(deal: Deal, decision: PlannerDecision) -> PlannerDecision:
    """HITL verification of the planner's own routing decision -- not just
    of extracted data. Mirrors the same principle as the review checkpoint:
    the planner's guess about what to do next doesn't execute unchecked."""
    print(f"\n[Planner] Deal '{deal.name}' is in state: {deal.status.value}")
    print(f"[Planner] Proposed action: {decision.action}")
    print(f"[Planner] Reasoning: {decision.reasoning}")
    if decision.target_field:
        print(f"[Planner] Target field: {decision.target_field}")

    choice = input("[Planner] Proceed with this action? [y]es / [n]o, choose manually: ").strip().lower()
    if choice == "y":
        return decision

    valid = VALID_ACTIONS[deal.status]
    print(f"[Planner] Valid actions from this state: {valid}")
    manual_action = input("[Planner] Enter action manually: ").strip()
    return PlannerDecision(action=manual_action, reasoning="Manually overridden by reviewer.")


# --- Stage runners ---------------------------------------------------------

def start_deal(store: Store, tenant_id: str, name: str, stage: Optional[str] = None) -> Deal:
    deal = Deal(tenant_id=tenant_id, name=name, stage=stage)
    store.save_deal(deal)
    return deal


# --- Sourcing / promotion (pre-deal half of the lifecycle, §5.8) -----------

def source_leads(
    store: Store,
    tenant_id: str,
    sector_keyword: str,
    location_filter: Optional[str] = None,
) -> list[SourcedLead]:
    """Discover candidates and persist them as NEW -- review is a separate
    step (agents/review_checkpoint.review_leads), same separation-of-
    concerns as extraction vs. review elsewhere in this pipeline."""
    leads = discover_leads(tenant_id, sector_keyword, location_filter=location_filter)
    for lead in leads:
        store.save_lead(lead)
    return leads


def source_ib_targets(store: Store, tenant_id: str, sector_keyword: str) -> list[SourcedLead]:
    """IB-style sourcing (§2/§5.1): mature/public companies signaling an
    approaching transaction window via their own SEC filings, not
    early-stage incubation candidates -- a genuinely different signal from
    source_leads() above, kept as a separate entrypoint rather than a mode
    flag so it's never accidentally blended with early-stage discovery."""
    leads = discover_ib_targets(tenant_id, sector_keyword)
    for lead in leads:
        store.save_lead(lead)
    return leads


def promote_lead_to_deal(store: Store, lead: SourcedLead, name: Optional[str] = None) -> Deal:
    """The actual on-ramp from "a company worth looking at" to "a deal
    going through the real pipeline." Only a REVIEWED lead should be
    promoted (an analyst decided it, not just discovered it) -- not
    enforced here as a hard error, since a human deliberately promoting a
    NEW lead is a judgment call this function shouldn't block, but the
    caller (main.py) only offers promotion for REVIEWED leads."""
    deal = start_deal(store, tenant_id=lead.tenant_id, name=name or lead.company_name, stage=lead.sector_tag)
    lead.status = LeadStatus.PROMOTED_TO_DEAL
    lead.promoted_deal_id = deal.id
    store.save_lead(lead)
    return deal


def apply_sign_mandate(store: Store, deal: Deal, mandate_type: str, terms_summary: str) -> Deal:
    """Origination (§5.1 addendum, §2's Stage 2): the pitch-to-founder /
    RFP outcome. Purely a record of what was agreed -- this function does
    not pitch anyone or negotiate anything, it captures the terms a human
    already agreed to, the same way generate_teaser_draft captures a
    human's business description rather than generating one. Pure: no
    input()/print(), callable directly by a future API."""
    deal.mandate_type = mandate_type
    deal.mandate_terms_summary = terms_summary
    deal.mandate_signed_at = utcnow()
    deal.status = DealStatus.MANDATE_SIGNED
    store.save_deal(deal)
    return deal


def _run_sign_mandate(store: Store, deal: Deal, reviewer: str) -> None:
    print(f"\n[Planner] Recording the engagement mandate for '{deal.name}'.")
    mandate_type = input(
        "  Mandate type -- 'sell_side_advisory' (IB-style, helping them raise/exit) "
        "or 'vc_incubation' (equity stake + hands-on support): "
    ).strip() or "sell_side_advisory"
    terms = input("  One-line terms summary (fee %, exclusivity period, etc.): ").strip()

    apply_sign_mandate(store, deal, mandate_type, terms)
    print(f"[Planner] Mandate signed ({mandate_type}). Deal can now proceed to ingestion.")


def apply_add_investor(
    store: Store, deal: Deal, investor_name: str, *,
    firm: Optional[str] = None, nda_status: str = "not_sent",
    interest_level: str = "new", notes: Optional[str] = None,
) -> InvestorContact:
    """Roadshow tracking (§5 Stage 5): pure record-keeping for a human-led
    process. This never contacts anyone -- it records that a human already
    reached out, the same boundary main.py's SOURCING_SCOPE_NOTE states
    explicitly for sourcing. Pure: no input()/print()."""
    contact = InvestorContact(
        tenant_id=deal.tenant_id, deal_id=deal.id, investor_name=investor_name, firm=firm,
        nda_status=nda_status, interest_level=interest_level, notes=notes,
    )
    store.save_investor_contact(contact)
    return contact


def _run_add_investor(store: Store, deal: Deal) -> None:
    name = input("  Investor name: ").strip()
    firm = input("  Firm: ").strip() or None
    nda_status = input("  NDA status ('not_sent' / 'sent' / 'signed', blank = not_sent): ").strip() or "not_sent"
    interest = input("  Interest level ('cold'/'warm'/'hot'/'passed'/'committed', blank = new): ").strip() or "new"
    notes = input("  Notes (optional): ").strip() or None

    contact = apply_add_investor(
        store, deal, name, firm=firm, nda_status=nda_status, interest_level=interest, notes=notes,
    )
    print(f"[Planner] Tracked {contact.investor_name} ({contact.firm or 'no firm given'}) "
          f"-- {contact.interest_level}/{contact.nda_status}.")


def _run_view_demand_book(store: Store, deal: Deal) -> None:
    contacts = store.get_investor_contacts(deal.tenant_id, deal.id)
    if not contacts:
        print("[Planner] No investors tracked for this deal yet.")
        return
    print(f"\n=== Demand Book — {deal.name} ({len(contacts)} contact(s)) ===")
    for c in contacts:
        print(f"  {c.investor_name} ({c.firm or '-'}): NDA={c.nda_status}, interest={c.interest_level}"
              f"{', note: ' + c.notes if c.notes else ''}")


def _run_ingest(store: Store, deal: Deal, document_path: str) -> None:
    document = ingest_document(document_path, deal.tenant_id, deal.id)
    store.save_document(document)

    def _append_document(d: Deal) -> None:
        d.document_ids.append(document.id)
        d.status = DealStatus.INGESTED

    # Atomic read-modify-write (store.update_deal), not get_deal()+save_deal():
    # two concurrent uploads for the same deal would otherwise both read
    # document_ids=[], each append their own id locally, and whichever
    # save_deal() lands second silently discards the other's upload.
    updated = store.update_deal(deal.tenant_id, deal.id, _append_document)
    deal.document_ids = updated.document_ids
    deal.status = updated.status
    print(f"[Planner] Ingested {document.filename}: {len(document.blocks)} blocks.")


def _run_extract(store: Store, deal: Deal, model: str, reviewer_feedback: Optional[str] = None) -> ExtractionResult:
    documents = store.get_documents_for_deal(deal.tenant_id, deal.id)
    if not documents:
        raise RuntimeError("No documents ingested for this deal yet.")
    result = extract(documents[0], model=model, reviewer_feedback=reviewer_feedback)  # Phase 0: single-document deals
    store.save_extraction_result(result)
    deal.status = DealStatus.EXTRACTED
    store.save_deal(deal)
    print(f"[Planner] Extraction complete. Cross-check flags: {result.cross_check_flags or 'none'}")
    return result


def _run_review(store: Store, deal: Deal, reviewer: str, model: str) -> None:
    result = store.get_extraction_result(deal.tenant_id, deal.id)
    documents = store.get_documents_for_deal(deal.tenant_id, deal.id)
    document = documents[0] if documents else None

    def retry_fn(doc, note):
        return extract(doc, model=model, reviewer_feedback=note)

    reviewed, audit = review_extraction(result, reviewer, document=document, retry_extraction=retry_fn)
    store.save_extraction_result(reviewed)
    store.append_audit_events(audit)

    deal.status = recompute_deal_review_status(reviewed)
    store.save_deal(deal)
    print(f"[Planner] Review complete. Deal status: {deal.status.value}")


def _run_research(
    store: Store, deal: Deal, company_name: str,
    sector_query: Optional[str], sector_index: Optional[SectorNotesIndex],
) -> list[ResearchFinding]:
    findings = research_deal(
        deal.tenant_id, deal.id, company_name, sector_query=sector_query, sector_index=sector_index,
    )

    # Fold in the originating lead's own discovery signals, if this deal was
    # promoted from one -- real feedback that research findings feel thin/
    # generic for early-stage private companies, where a fresh public-web
    # search often turns up little to nothing (§10.5's documented "honest
    # gap"). But a lead's discovery_signals were already real and already
    # the specific reason this company got sourced in the first place --
    # they were being silently discarded at promotion time instead of
    # carried forward, so a fuzzy name re-search here had to independently
    # rediscover the same signal (or miss it) rather than just reusing it.
    # Deduped by source_url against what the fresh search already found.
    lead = store.get_lead_by_promoted_deal_id(deal.tenant_id, deal.id)
    if lead:
        already_seen = {f.source_url for f in findings if f.source_url}
        for signal in lead.discovery_signals:
            if signal.source_url and signal.source_url in already_seen:
                continue
            findings.append(ResearchFinding(
                tenant_id=deal.tenant_id, deal_id=deal.id,
                topic="sourcing_signal",
                content=signal.content,
                source_url=signal.source_url,
                source_type=signal.source_type,
            ))

    store.save_research_findings(findings)
    deal.status = DealStatus.RESEARCHED
    store.save_deal(deal)
    print(f"[Planner] Research complete. {len(findings)} finding(s).")
    return findings


def mark_research_reviewed(store: Store, deal: Deal) -> Deal:
    """Decoupled from any single finding decision -- research review is
    "look at everything, then explicitly say you're done," not implicitly
    finished when the last finding gets a decision (unlike field review,
    where completeness is computable from is_ready_for_compilation()).
    Pure: no input()/print()."""
    deal.status = DealStatus.RESEARCH_REVIEWED
    store.save_deal(deal)
    return deal


def _run_review_research(store: Store, deal: Deal, reviewer: str) -> None:
    findings = store.get_research_findings(deal.tenant_id, deal.id)
    reviewed, audit = review_research_findings(findings, reviewer)
    store.save_research_findings(reviewed)
    store.append_audit_events(audit)
    mark_research_reviewed(store, deal)


def _run_compile(store: Store, deal: Deal) -> MemoVersion:
    """The CIM -- the comprehensive, NDA-gated document. This is the only
    one of the three document types that flips Deal.status to COMPILED;
    generating a teaser or pro-forma alongside/instead of it doesn't change
    what COMPILED means."""
    result = store.get_extraction_result(deal.tenant_id, deal.id)
    if not is_ready_for_compilation(result):
        # compile_cim() enforces this same gate, but only after generating
        # and persisting chart artifacts below -- checking here too means a
        # blocked compile attempt never writes a single chart file or
        # ChartArtifact row for data that was never approved (caught live
        # while testing the Milestone 4 compilation API: a 409 still left a
        # memo_output/{deal_id}/charts/ directory behind).
        raise CompilationBlockedError(
            f"Deal {result.deal_id} has not cleared human review; refusing to compile."
        )
    findings = store.get_research_findings(deal.tenant_id, deal.id)
    charts = generate_charts(result, out_dir=f"memo_output/{deal.id}/charts")
    store.save_charts(charts)

    existing = store.list_memo_versions_by_type(deal.tenant_id, deal.id, "cim")
    memo = compile_cim(
        result, charts, out_dir=f"memo_output/{deal.id}",
        research_findings=findings, version_number=len(existing) + 1,
    )
    store.save_memo_version(memo)
    deal.status = DealStatus.COMPILED
    store.save_deal(deal)
    print(f"[Planner] CIM compiled: {memo.content_uri}")
    return memo


def generate_teaser_draft(store: Store, deal: Deal, business_description: str) -> MemoVersion:
    """The Anonymous Teaser's first of two human decisions: the reviewer
    supplies the one-line business description (never generated -- see
    compile_teaser's own docstring). Persists the draft with
    approved_by=None; the second decision (confirm_teaser_safe_to_send)
    is a genuinely separate call, matching the frontend's two-step flow
    1:1. Pure: no input()/print()."""
    result = store.get_extraction_result(deal.tenant_id, deal.id)
    if not is_ready_for_compilation(result):
        # Same reasoning as _run_compile's identical check: compile_teaser()
        # enforces this gate too, but only after charts are generated/
        # persisted below -- check first so a blocked draft never writes
        # chart artifacts for data that was never approved.
        raise CompilationBlockedError(
            f"Deal {result.deal_id} has not cleared human review; refusing to compile a teaser."
        )
    charts = store.get_charts(deal.tenant_id, deal.id) or generate_charts(
        result, out_dir=f"memo_output/{deal.id}/charts",
    )
    if charts:
        store.save_charts(charts)

    existing = store.list_memo_versions_by_type(deal.tenant_id, deal.id, "teaser")
    memo = compile_teaser(
        result, charts, deal_name=deal.name, business_description=business_description,
        out_dir=f"memo_output/{deal.id}", version_number=len(existing) + 1,
    )
    store.save_memo_version(memo)
    return memo


def confirm_teaser_safe_to_send(store: Store, deal: Deal, memo_id: str, reviewer: str, confirmed: bool) -> MemoVersion:
    """The Anonymous Teaser's second human decision, and the concrete
    implementation of gemini_vc_response.txt's "NDA/anonymization
    boundary" point, not just a design note: only this function may set
    `MemoVersion.approved_by`, and only on an explicit `confirmed=True`.
    Pure: no input()/print()."""
    memo = store.get_memo_version(deal.tenant_id, memo_id)
    if memo is None:
        raise ValueError(f"No memo {memo_id!r} found for deal {deal.id!r}.")
    memo.approved_by = reviewer if confirmed else None
    store.save_memo_version(memo)
    return memo


def _run_compile_teaser(store: Store, deal: Deal, reviewer: str) -> None:
    description = input("  One-line anonymized business description (no company name): ").strip()
    memo = generate_teaser_draft(store, deal, description)

    with open(memo.content_uri) as f:
        content = f.read()
    print(f"\n--- Draft teaser ({memo.content_uri}) ---\n{content}\n---")
    confirm = input(
        "  Confirm this does NOT leak the company's identity -- safe to send externally? [y]es / [n]o: "
    ).strip().lower()

    memo = confirm_teaser_safe_to_send(store, deal, memo.id, reviewer, confirmed=(confirm == "y"))
    if memo.approved_by is None:
        print("  -> Saved as a draft, NOT marked safe to send. Revise the description and regenerate.")
    print(f"[Planner] Teaser saved: {memo.content_uri} (approved_by={memo.approved_by})")


def apply_compile_proforma(
    store: Store, deal: Deal, reviewer: str, growth_rate_override: Optional[float] = None,
) -> MemoVersion:
    """The Pro-Forma Model. `growth_rate_override`, when given, is the
    reviewer directly challenging the assumption driving the projection --
    since this document computes projected numbers rather than arranging
    extracted ones, that's the point where a human should intervene, not
    an approve/reject of the output after the fact (hence no separate
    leak-check step the way the teaser has one). Pure: no input()/print()."""
    result = store.get_extraction_result(deal.tenant_id, deal.id)
    projection = generate_proforma_projection(result, years=3, annual_growth_rate_pct_override=growth_rate_override)

    existing = store.list_memo_versions_by_type(deal.tenant_id, deal.id, "proforma")
    memo = compile_proforma_document(
        result, projection, out_dir=f"memo_output/{deal.id}", version_number=len(existing) + 1,
    )
    memo.approved_by = reviewer
    store.save_memo_version(memo)
    return memo


def _run_compile_proforma(store: Store, deal: Deal, reviewer: str) -> None:
    override_raw = input(
        "  Override the annual ARR growth-rate assumption? (%, blank = use extracted YoY rate): "
    ).strip()
    override = None
    if override_raw:
        try:
            override = float(override_raw)
        except ValueError:
            print(f"  '{override_raw}' isn't a number -- ignoring, using the extracted YoY rate instead.")

    memo = apply_compile_proforma(store, deal, reviewer, growth_rate_override=override)
    print("\n--- Pro-forma assumptions ---")
    # Re-read from the saved document's structured content isn't available yet
    # (that's the Milestone 4 structured-data split) -- regenerate the
    # projection once more here purely to print it, since apply_compile_
    # proforma doesn't return the intermediate dict, only the persisted memo.
    result = store.get_extraction_result(deal.tenant_id, deal.id)
    projection = generate_proforma_projection(result, years=3, annual_growth_rate_pct_override=override)
    for a in projection["assumptions"]:
        print(f"  - {a}")
    print(f"[Planner] Pro-forma model saved: {memo.content_uri}")


def _run_rerun_analytics(store: Store, deal: Deal) -> list[ChartArtifact]:
    result = store.get_extraction_result(deal.tenant_id, deal.id)
    charts = generate_charts(result, out_dir=f"memo_output/{deal.id}/charts")
    store.save_charts(charts)
    print(f"[Planner] Re-rendered {len(charts)} chart(s).")
    return charts


# --- Single entrypoint -----------------------------------------------------

def handle_directive(
    store: Store,
    deal: Deal,
    directive: str,
    reviewer: str,
    *,
    document_path: Optional[str] = None,
    company_name: Optional[str] = None,
    sector_query: Optional[str] = None,
    extraction_model: str = "phi4-mini",
    sector_index: Optional[SectorNotesIndex] = None,
    auto_confirm: bool = False,
) -> Deal:
    """Classify the directive (or use the deterministic default for a plain
    "continue"), confirm with the human (unless auto_confirm, for
    scripted/tested happy-path runs), execute, persist, return the
    refreshed Deal."""
    if directive.strip().lower() in CONTINUE_WORDS:
        decision = PlannerDecision(
            action=DEFAULT_ACTION[deal.status],
            reasoning="Plain continue -- using the deterministic next step for this state.",
        )
    else:
        decision = classify_directive(deal, directive)

    if not auto_confirm:
        decision = _confirm_with_human(deal, decision)
    else:
        print(f"\n[Planner] (auto-confirmed) action={decision.action}: {decision.reasoning}")

    action = decision.action
    if action == "sign_mandate":
        _run_sign_mandate(store, deal, reviewer)
    elif action == "ingest":
        if not document_path:
            raise ValueError("document_path required to ingest.")
        _run_ingest(store, deal, document_path)
    elif action == "extract":
        _run_extract(store, deal, extraction_model)
    elif action == "rerun_extraction":
        note = f"Reviewer directive: {directive}" if decision.target_field is None else (
            f"Reviewer directive about '{decision.target_field}': {directive}"
        )
        _run_extract(store, deal, extraction_model, reviewer_feedback=note)
    elif action == "review":
        _run_review(store, deal, reviewer, extraction_model)
    elif action in ("research", "rerun_research"):
        if not company_name:
            raise ValueError("company_name required to research.")
        _run_research(store, deal, company_name, sector_query, sector_index)
    elif action == "review_research":
        _run_review_research(store, deal, reviewer)
    elif action in ("compile", "recompile"):
        _run_compile(store, deal)
    elif action == "compile_teaser":
        _run_compile_teaser(store, deal, reviewer)
    elif action == "compile_proforma":
        _run_compile_proforma(store, deal, reviewer)
    elif action == "add_investor":
        _run_add_investor(store, deal)
    elif action == "view_demand_book":
        _run_view_demand_book(store, deal)
    elif action == "rerun_analytics":
        _run_rerun_analytics(store, deal)
    elif action == "done":
        print("[Planner] Deal already compiled; nothing to do.")
    else:
        print(f"[Planner] Unknown action {action!r} -- no-op. Nothing executed.")

    return store.get_deal(deal.tenant_id, deal.id)
