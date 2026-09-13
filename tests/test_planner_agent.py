"""
Coverage for the pure stage-runner functions introduced by the Milestone 1
refactor (agents/planner_agent.py). LLM-dependent paths (classify_directive,
extraction, research, the CIM's narrative paragraph) are deliberately not
re-tested here -- they're unchanged logic already validated live multiple
times this session, and pytest coverage for them would need a live Ollama
model, not a fast regression check. This file covers what's new: mandate
signing, investor tracking, the teaser's two-step draft/confirm split, and
the pro-forma's growth-rate override.
"""
import shutil
from pathlib import Path

from conftest import make_extraction_result

from agents.compilation_agent import CompilationBlockedError
from agents.planner_agent import (
    _run_compile,
    _run_research,
    apply_add_investor,
    apply_compile_proforma,
    apply_sign_mandate,
    confirm_teaser_safe_to_send,
    generate_teaser_draft,
    mark_research_reviewed,
    promote_lead_to_deal,
    start_deal,
)
from schemas import DealStatus, DiscoverySignal, FieldStatus, SourcedLead

MEMO_OUTPUT_ROOT = Path(__file__).parent.parent / "memo_output"


def _cleanup_memo_output(deal_id: str) -> None:
    shutil.rmtree(MEMO_OUTPUT_ROOT / deal_id, ignore_errors=True)


def _fully_approved_result(deal):
    result = make_extraction_result(tenant_id=deal.tenant_id, deal_id=deal.id)
    for name in ("arr", "arr_prior_year", "burn_monthly", "cash_on_hand", "runway_months", "headcount"):
        getattr(result, name).status = FieldStatus.APPROVED
    for name in ("mrr", "growth_rate_yoy"):
        ev = getattr(result, name)
        ev.status = FieldStatus.NOT_FOUND
        ev.reviewed_at = "2026-01-01T00:00:00"
    result.cap_table_status = FieldStatus.NOT_FOUND
    result.cap_table_reviewed_at = "2026-01-01T00:00:00"
    result.funding_history_status = FieldStatus.NOT_FOUND
    result.funding_history_reviewed_at = "2026-01-01T00:00:00"
    return result


def test_apply_sign_mandate(store):
    deal = start_deal(store, "tenant_test", "Acme Robotics")
    updated = apply_sign_mandate(store, deal, "sell_side_advisory", "2% fee, 90-day exclusivity")

    assert updated.status == DealStatus.MANDATE_SIGNED
    assert updated.mandate_type == "sell_side_advisory"
    assert updated.mandate_signed_at is not None

    persisted = store.get_deal(deal.tenant_id, deal.id)
    assert persisted.status == DealStatus.MANDATE_SIGNED


def test_apply_add_investor(store):
    deal = start_deal(store, "tenant_test", "Acme Robotics")
    contact = apply_add_investor(
        store, deal, "Jane Doe", firm="Example Capital", nda_status="sent", interest_level="warm",
    )

    assert contact.investor_name == "Jane Doe"
    persisted = store.get_investor_contacts(deal.tenant_id, deal.id)
    assert len(persisted) == 1
    assert persisted[0].firm == "Example Capital"


def test_mark_research_reviewed(store):
    deal = start_deal(store, "tenant_test", "Acme Robotics")
    updated = mark_research_reviewed(store, deal)
    assert updated.status == DealStatus.RESEARCH_REVIEWED


def test_run_research_folds_in_promoted_leads_discovery_signals(store, monkeypatch):
    """Real user feedback: research findings feel thin for early-stage
    private companies, where a fresh public-web search often turns up
    little (a documented, honest limitation). But a lead's own
    discovery_signals were already real and already the specific reason
    this company was sourced -- they were being silently discarded at
    promotion time instead of carried into the deal's research findings.
    Monkeypatches research_deal (real network calls) with a fixed list so
    this stays a fast, deterministic test of just the carry-forward logic."""
    lead = SourcedLead(
        tenant_id="tenant_test", company_name="Acme Robotics", sector_tag="robotics",
        discovery_signals=[
            DiscoverySignal(
                content="GitHub repo acme/robotics-core: 40 stars, created last week",
                source_url="https://github.com/acme/robotics-core",
                source_type="github",
            ),
        ],
    )
    store.save_lead(lead)
    deal = promote_lead_to_deal(store, lead)

    import agents.planner_agent as planner_module

    def fake_research_deal(tenant_id, deal_id, company_name, sector_query=None, sector_index=None):
        return []  # simulates the documented "honest gap" -- fresh search finds nothing

    monkeypatch.setattr(planner_module, "research_deal", fake_research_deal)

    findings = _run_research(store, deal, "Acme Robotics", None, None)

    assert len(findings) == 1
    assert findings[0].topic == "sourcing_signal"
    assert findings[0].source_url == "https://github.com/acme/robotics-core"
    assert findings[0].source_type == "github"


def test_run_research_dedupes_lead_signal_against_fresh_search_result(store, monkeypatch):
    lead = SourcedLead(
        tenant_id="tenant_test", company_name="Acme Robotics", sector_tag="robotics",
        discovery_signals=[
            DiscoverySignal(
                content="GitHub repo acme/robotics-core: 40 stars",
                source_url="https://github.com/acme/robotics-core",
                source_type="github",
            ),
        ],
    )
    store.save_lead(lead)
    deal = promote_lead_to_deal(store, lead)

    import agents.planner_agent as planner_module
    from schemas import ResearchFinding

    def fake_research_deal(tenant_id, deal_id, company_name, sector_query=None, sector_index=None):
        return [ResearchFinding(
            tenant_id=tenant_id, deal_id=deal_id, topic="oss_traction",
            content="GitHub repo acme/robotics-core: 41 stars (re-fetched)",
            source_url="https://github.com/acme/robotics-core", source_type="github",
        )]

    monkeypatch.setattr(planner_module, "research_deal", fake_research_deal)

    findings = _run_research(store, deal, "Acme Robotics", None, None)

    # The fresh search already found this exact URL -- the lead's own copy
    # must not be appended a second time.
    assert len(findings) == 1
    assert findings[0].topic == "oss_traction"


def test_teaser_draft_then_confirm_two_step_flow(store):
    deal = start_deal(store, "tenant_test", "Acme Robotics")
    result = _fully_approved_result(deal)
    store.save_extraction_result(result)

    try:
        memo = generate_teaser_draft(store, deal, "A robotics platform for warehouse operators.")
        assert memo.document_type == "teaser"
        assert memo.approved_by is None  # draft only -- not yet confirmed safe to send

        confirmed = confirm_teaser_safe_to_send(store, deal, memo.id, "alice", confirmed=True)
        assert confirmed.approved_by == "alice"

        # Re-fetching from the store proves this is real cross-call state,
        # not just the in-memory object -- the point of splitting this into
        # two functions in the first place (a future API calls these as two
        # separate HTTP requests).
        persisted = store.get_memo_version(deal.tenant_id, memo.id)
        assert persisted.approved_by == "alice"

        # Declining leaves approved_by unset (or clears a prior confirm).
        declined = confirm_teaser_safe_to_send(store, deal, memo.id, "alice", confirmed=False)
        assert declined.approved_by is None
    finally:
        _cleanup_memo_output(deal.id)


def test_run_compile_blocked_before_review_writes_no_chart_files(store, tmp_path):
    """Regression test: _run_compile used to generate and persist chart
    artifacts before compile_cim's own review-gate check ran, so a blocked
    compile still left memo_output/{deal_id}/charts/ on disk and
    ChartArtifact rows in the store. Caught live while testing the
    Milestone 4 compilation API (a 409 response still left a stray
    directory behind)."""
    deal = start_deal(store, "tenant_test", "Acme Robotics")
    result = make_extraction_result(tenant_id=deal.tenant_id, deal_id=deal.id)  # not reviewed
    store.save_extraction_result(result)

    try:
        try:
            _run_compile(store, deal)
            assert False, "expected CompilationBlockedError"
        except CompilationBlockedError:
            pass

        assert store.get_charts(deal.tenant_id, deal.id) == []
        assert not (MEMO_OUTPUT_ROOT / deal.id).exists()
    finally:
        _cleanup_memo_output(deal.id)


def test_apply_compile_proforma_with_override(store):
    deal = start_deal(store, "tenant_test", "Acme Robotics")
    result = _fully_approved_result(deal)
    store.save_extraction_result(result)

    try:
        memo = apply_compile_proforma(store, deal, "alice", growth_rate_override=50.0)
        assert memo.document_type == "proforma"
        assert memo.approved_by == "alice"
        assert Path(memo.content_uri).exists()
    finally:
        _cleanup_memo_output(deal.id)
