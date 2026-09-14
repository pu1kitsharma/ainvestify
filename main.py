"""
Top-level entry point — the "prompt the agent" interface. Run as:

    python3 main.py "find companies in fintech worth incubating right now"
    python3 main.py "screen this deal: sample_docs/acme_robotics_fact_sheet.pdf"
    python3 main.py   # interactive prompt

Business framing (see CLAUDE.md): this isn't a fund screening deals for its
own book -- it's selecting and incubating companies, then producing the
same cited, human-reviewed memo to help them raise from institutional
investors, the way a boutique bank packages a raise. That's why sourcing
and screening are one connected flow through the Planner (agents/planner_
agent.py owns both halves), not two disconnected scripts.

This is deliberately a thin router, not a general assistant: it classifies
a free-text request into "find candidates" or "screen a specific deal", or
"unknown" if it's neither, and dispatches to the Planner either way. It
does not claim capabilities that don't exist: sourcing always prints an
explicit scope note that it doesn't provide fundraising/advisory execution
(the actual raise, term sheets, investor introductions) -- that remains a
human-led process this system supports with cited data, not one it runs.
"""
from __future__ import annotations

import sys
from typing import Optional

import ollama
from pydantic import BaseModel

from agents.planner_agent import handle_directive, promote_lead_to_deal, start_deal
from agents.review_checkpoint import review_leads
from schemas import LeadStatus, WebSourcingRun
from agents.company_sourcing import source_companies
from store import Store

ROUTER_MODEL = "llama3.2:3b"
# Not the same model as the Planner's fixed-action routing (llama3.2:1b,
# which only ever picks from a short valid-actions list given a known
# state -- 1b handles that reliably). This router's job is open-ended
# keyword/geography extraction from arbitrary text, which is a genuinely
# harder task: confirmed live that 1b consistently returned no keyword at
# all for a real test prompt ("find potential companies... tech industry
# right now...") where 3b correctly extracted "tech" -- §8's "right-sized
# model per task" cuts both ways, this task needed the larger one.

_NON_GEO_LOCATION_WORDS = {
    "now", "right now", "currently", "today", "recently", "these days",
    "the world", "worldwide", "global", "globally", "anywhere",
}

# Found live through the frontend's prompt bar (not a synthetic test): the
# router extracted location_filter="the" from "...in the robotics space
# worth incubating" -- "the" passes the existing substring check (it's a
# real word in the prompt) and isn't in _NON_GEO_LOCATION_WORDS (which only
# covers specific observed temporal/scope phrases), so it slipped through
# uncaught. That's a different failure shape: not a fabrication, not a
# temporal phrase, just a bare function word the model mistook for a place
# name. A real geography is never one of these regardless of prompt
# wording, so this check is structural rather than another one-off phrase
# to add to the blocklist above.
_ENGLISH_STOPWORDS = {
    "the", "a", "an", "in", "at", "on", "for", "with", "of", "to", "from",
    "by", "and", "or", "this", "that", "these", "those", "it", "its",
}

SOURCING_SCOPE_NOTE = (
    "\n[Note] Public web research produces cited candidate profiles and proposed "
    "incubation steps. Coverage can be incomplete; assessments need validation. "
    "Promoting a lead starts the existing deal preparation workflow."
)


class RouterDecision(BaseModel):
    action: str  # "source_leads" | "screen_deal" | "unknown"
    sector_keyword: Optional[str] = None
    location_filter: Optional[str] = None
    reasoning: str


def classify_prompt(prompt: str) -> RouterDecision:
    instructions = f"""You are the top-level router for a system that sources and incubates
early-stage companies, then screens them for helping them raise institutional
funding. Classify the user's request into exactly one action:

- "source_leads": they want to find/discover NEW candidate companies nobody
  has submitted anything for yet (e.g. "find startups in X", "who should we
  incubate", "source companies in Y sector", "companies to invest in right now").
- "screen_deal": they want to ingest/extract/review a memo for a SPECIFIC
  company/deal they already have documents for or have named.
- "unknown": neither of the above, or too vague to act on.

If action is "source_leads": extract the single best search theme/keyword
into sector_keyword -- never leave this hardcoded to any one industry,
infer it fresh from what they actually said. Also set location_filter to a
geography ONLY if a specific country, region, or city is explicitly named
somewhere in the user's own request text below -- copy that exact word
from their request. location_filter must be a PLACE (a country, region, or
city), never a time reference ("now", "right now", "currently", "today")
and never a scope word ("global", "worldwide", "any country") -- those are
NOT geographies and location_filter MUST be null for all of them. If no
specific place is named anywhere in their request, location_filter MUST be
null. Do not guess, assume, or default to any geography.

User request: "{prompt}"

Give a one-sentence reasoning. Return only the JSON object."""

    response = ollama.chat(
        model=ROUTER_MODEL,
        messages=[{"role": "user", "content": instructions}],
        format=RouterDecision.model_json_schema(),
        options={"temperature": 0},
    )
    decision = RouterDecision.model_validate_json(response["message"]["content"])

    # Defense in depth, same principle as the citation-enforcement pattern
    # used throughout this project: never trust a model's structured claim
    # without checking it against the actual source. Two distinct failure
    # modes confirmed live, so two distinct checks:
    #  1. Fabrication: llama3.2:1b once echoed "europe" -- a word from this
    #     prompt's own instruction *example* text -- for a request that
    #     never mentioned any geography at all. Reject anything that isn't
    #     literally a substring of the user's own text.
    #  2. Misclassification: llama3.2:3b correctly avoids fabricating, but
    #     labeled "right now" (real prompt text) as a geography when it's a
    #     time reference. A substring check alone doesn't catch this --
    #     also reject known non-geographic phrases even when they're real
    #     substrings of the prompt.
    #  3. Bare function words: labeled "the" (real prompt text, from "...in
    #     the robotics space...") as a geography -- neither a fabrication
    #     nor a known temporal/scope phrase, just a stopword. Reject those
    #     structurally rather than one at a time.
    #  4. Sector/geography confusion: for "...in the fintech space...",
    #     llama3.2:3b consistently (confirmed over repeated calls, not a
    #     one-off) returns location_filter="fintech" -- the exact same
    #     string as sector_keyword. A sector is never also a geography, so
    #     this is a structural check, not another word to blocklist.
    if decision.location_filter:
        loc = decision.location_filter.strip().lower()
        same_as_sector = bool(decision.sector_keyword) and loc == decision.sector_keyword.strip().lower()
        if loc not in prompt.lower() or loc in _NON_GEO_LOCATION_WORDS or loc in _ENGLISH_STOPWORDS or same_as_sector:
            decision.location_filter = None

    return decision


def run_sourcing(
    store: Store, tenant_id: str, reviewer: str,
    sector_keyword: str, location_filter: Optional[str],
) -> None:
    scope = f"'{sector_keyword}'" + (f" in '{location_filter}'" if location_filter else " (global)")
    print(f"\n[Router] Searching for candidate companies matching {scope}...")
    run = source_companies(store, WebSourcingRun(
        tenant_id=tenant_id, thesis=sector_keyword, geography=location_filter, model="local"), prepare_workflow=True)
    print(f"[Router] Research {run.status}: {len(run.discovered_urls)} discovered pages.")
    for warning in run.warnings:
        print(f"[Coverage] {warning}")
    if run.error:
        print(f"[Research] {run.error}")
    leads = [store.get_lead(tenant_id, lead_id) for lead_id in run.lead_ids]
    leads = [lead for lead in leads if lead is not None]
    if not leads:
        print("[Router] No candidate leads found for this theme right now.")
        print(SOURCING_SCOPE_NOTE)
        return

    reviewed, audit = review_leads(leads, reviewer)
    for lead in reviewed:
        store.save_lead(lead)
    store.append_audit_events(audit)

    kept = [l for l in reviewed if l.status == LeadStatus.REVIEWED]
    print(f"\n[Router] {len(kept)} of {len(reviewed)} lead(s) kept for follow-up.")

    for lead in kept:
        choice = input(
            f"  Promote '{lead.company_name}' to an actual deal now? [y]es / [n]o: "
        ).strip().lower()
        if choice != "y":
            continue
        deal = promote_lead_to_deal(store, lead)
        print(f"  -> Promoted to deal {deal.id} (status={deal.status.value}).")

        mandate_choice = input("     Record the engagement mandate now? [y]es / [n]o: ").strip().lower()
        if mandate_choice != "y":
            continue
        deal = handle_directive(store, deal, "continue", reviewer=reviewer, auto_confirm=True)

        doc_choice = input("     Ingest a document for it now? [y]es / [n]o: ").strip().lower()
        if doc_choice == "y":
            document_path = input("     Path to the document: ").strip()
            deal = handle_directive(
                store, deal, "continue", reviewer=reviewer,
                document_path=document_path, auto_confirm=True,
            )
            print(f"     Deal {deal.id} now status={deal.status.value}.")

    print(SOURCING_SCOPE_NOTE)


def run_screen_deal(store: Store, tenant_id: str, reviewer: str) -> None:
    print("\n[Router] This looks like a request to screen a specific deal.")
    name = input("  Company name for this deal: ").strip()
    document_path = input("  Path to the document to ingest: ").strip()

    deal = start_deal(store, tenant_id=tenant_id, name=name)
    deal = handle_directive(store, deal, "continue", reviewer=reviewer, auto_confirm=True)  # sign_mandate
    deal = handle_directive(
        store, deal, "continue", reviewer=reviewer,
        document_path=document_path, auto_confirm=True,
    )
    print(f"\n[Router] Deal {deal.id} created, status={deal.status.value}.")
    print("[Router] Continue it later via the planner (handle_directive), "
          "e.g. a future 'continue deal <id>' router action.")


def main() -> None:
    prompt = " ".join(sys.argv[1:]).strip() or input("What would you like the system to do? ").strip()
    tenant_id = "default_tenant"  # Phase 0 is single-user; a real multi-user CLI would take this as an arg
    reviewer = "cli_user"

    decision = classify_prompt(prompt)
    print(f"\n[Router] Classified as: {decision.action}")
    print(f"[Router] Reasoning: {decision.reasoning}")

    store = Store()
    try:
        if decision.action == "source_leads":
            run_sourcing(store, tenant_id, reviewer, prompt, decision.location_filter)
        elif decision.action == "screen_deal":
            run_screen_deal(store, tenant_id, reviewer)
        else:
            print(
                "[Router] Could not classify this request into a supported action.\n"
                "Try something like 'find companies in fintech' or "
                "'screen this deal, I have the pitch deck at <path>'."
            )
    finally:
        store.close()


if __name__ == "__main__":
    main()
