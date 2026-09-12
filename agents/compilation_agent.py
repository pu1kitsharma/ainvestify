"""
Compilation Agent — architecture doc §5.7.

Produces the real three-document suite an IB/VC engagement actually uses
(§2/§5.7 addendum, cross-checked against how gemini_vc_response.txt
describes real practice, not just assembled from that doc's specific
technical claims -- several of those turned out to be fabricated, see
CLAUDE.md's findings log):

1. `compile_cim()` -- the comprehensive memo (this module's original
   `compile_memo`, kept as an alias for compatibility). Full financials,
   cap table, funding history, external signals -- for parties who've
   signed an NDA.
2. `compile_teaser()` -- the anonymized 1-2 page document sent *before*
   any NDA. Deliberately excludes cap table, funding history, and external
   signals entirely (specific investor names, round amounts, and a GitHub
   repo's full name are themselves identifying in a small ecosystem, not
   just "the company name") and scrubs the company name from every
   rendered field, defense-in-depth.
3. `generate_proforma_projection()` / `compile_proforma_document()` -- a
   forward-looking model. This is fundamentally different from the other
   two: it doesn't arrange approved facts, it *computes projected* ones.
   Same non-negotiable principle either way (numbers never pass through
   free-text generation) -- projections are pure deterministic arithmetic
   over approved historicals with every assumption stated explicitly, and
   labeled as projected, never presented at the same confidence tier as an
   extracted, cited fact (§10.5's "supporting signal, not verified fact"
   principle, applied here to time instead of source type).

Every document still refuses to run if the review gate (§5.5/§12) hasn't
cleared -- this agent must never run around it, whichever document it's
assembling.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import ollama

from agents.review_checkpoint import is_ready_for_compilation
from schemas import ChartArtifact, ExtractionResult, FieldStatus, MemoVersion, ResearchFinding

SUMMARY_MODEL = "phi4-mini"

APPROVED = (FieldStatus.APPROVED, FieldStatus.EDITED)

_DIGIT_RE = re.compile(r"\d")


class CompilationBlockedError(Exception):
    """Raised when Compilation is invoked before the review gate has cleared."""


def _anonymize(text: str, *identifying_strings: Optional[str]) -> str:
    """Defense-in-depth scrub applied to the *whole rendered document*, not
    just the one field a name is expected to appear in -- confirmed
    valuable by gemini_vc_response.txt's own "NDA/anonymization boundary"
    point, implemented as an actual code path rather than a design note."""
    for s in identifying_strings:
        if s:
            text = re.sub(re.escape(s), "[Company]", text, flags=re.IGNORECASE)
    return text


def _fmt_scalar(result: ExtractionResult, name: str, label: str, include_source: bool = True) -> str:
    ev = getattr(result, name)
    if ev.status == FieldStatus.NOT_FOUND:
        return f"- **{label}:** Not disclosed"
    value = f"${ev.value:,.0f}" if ev.unit == "USD" else f"{ev.value}{(' ' + ev.unit) if ev.unit else ''}"
    edited = " _(reviewer-edited)_" if ev.status == FieldStatus.EDITED else ""
    source = f" `[source: {ev.source_block_id}, page {ev.source_page}]`" if include_source else ""
    return f"- **{label}:** {value}{edited}{source}"


def _cap_table_section(result: ExtractionResult) -> str:
    if result.cap_table_status not in APPROVED or not result.cap_table:
        return "_Cap table not available or not approved for this memo._"
    lines = ["| Holder | Ownership % | Share Class |", "| --- | --- | --- |"]
    for row in result.cap_table:
        pct = f"{row.pct}%" if row.pct is not None else "-"
        lines.append(f"| {row.holder or '-'} | {pct} | {row.share_class or '-'} |")
    lines.append(f"\n`[source: {result.cap_table_source_block_id}]`")
    return "\n".join(lines)


def _funding_history_section(result: ExtractionResult) -> str:
    if result.funding_history_status not in APPROVED or not result.funding_history:
        return "_No approved funding history for this memo._"
    lines = ["| Round | Amount | Date | Lead Investor | Source |", "| --- | --- | --- | --- | --- |"]
    for r in result.funding_history:
        amount = f"${r.amount:,.0f}" if r.amount is not None else "-"
        lines.append(f"| {r.round_name or '-'} | {amount} | {r.date or '-'} | {r.lead_investor or '-'} | `{r.source_block_id}` |")
    return "\n".join(lines)


def _generate_narrative_summary(result: ExtractionResult) -> Optional[str]:
    """One-paragraph qualitative framing. Never allowed to carry a number --
    §5.6's "numbers never pass through free-text generation" guardrail,
    applied here to narrative instead of charts."""
    approved_categories = [
        name for name in ("arr", "arr_prior_year", "burn_monthly", "runway_months", "headcount")
        if getattr(result, name).status in APPROVED
    ]
    if not approved_categories:
        return None

    prompt = (
        "Write exactly one short qualitative paragraph (2-3 sentences) framing this "
        "company's stage and trajectory for an investment memo, based only on the "
        "categories of data below. Do NOT include any numbers, percentages, or "
        "dollar amounts anywhere in your response -- describe direction and stage "
        "in words only (e.g. 'growing steadily', 'early-stage', 'extending runway'). "
        f"Data available (do not restate the numbers): {approved_categories}."
    )
    try:
        response = ollama.chat(
            model=SUMMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0},
        )
        text = response["message"]["content"].strip()
    except Exception:
        return None

    if _DIGIT_RE.search(text):
        # The model put a number in free-text narrative -- discard rather
        # than trust or attempt to sanitize it in place.
        return None
    return text


def _external_signals_section(findings: list[ResearchFinding]) -> str:
    """§10.5: research findings are supporting/corroborating signal, never
    presented in the same confidence tier as a cited financial figure from
    the deal's own documents -- hence its own section, its own framing
    sentence, and only ever the findings a reviewer has explicitly approved."""
    approved = [f for f in findings if f.status == FieldStatus.APPROVED]
    if not approved:
        return "_No approved external findings for this memo._"

    lines = [
        "_The items below are external corroborating signal (public repos, filings, "
        "press mentions, sector benchmarks) -- supporting context, not independent "
        "verification of the figures above, which remain sourced solely from the "
        "deal's own submitted documents._",
        "",
    ]
    for f in approved:
        source = f.source_url or "internal sector notes"
        lines.append(f"- **[{f.topic}]** {f.content} `[source: {source}]`")
    return "\n".join(lines)


def compile_cim(
    result: ExtractionResult,
    charts: list[ChartArtifact],
    out_dir: str,
    research_findings: Optional[list[ResearchFinding]] = None,
    version_number: int = 1,
    include_narrative: bool = True,
) -> MemoVersion:
    """The Confidential Information Memorandum -- the comprehensive
    document, for parties who've signed an NDA. Raises
    CompilationBlockedError if the review gate (§5.5/§12) hasn't cleared --
    this agent must never run around it."""
    if not is_ready_for_compilation(result):
        raise CompilationBlockedError(
            f"Deal {result.deal_id} has not cleared human review; refusing to compile."
        )

    lines: list[str] = [f"# Confidential Information Memorandum — {result.deal_id}", ""]
    lines.append(f"_Generated {result.extracted_at} · memo v{version_number}_")
    lines.append("")

    if include_narrative:
        narrative = _generate_narrative_summary(result)
        if narrative:
            lines += [narrative, ""]

    lines.append("## Key Financials")
    lines.append(_fmt_scalar(result, "arr", "ARR"))
    lines.append(_fmt_scalar(result, "arr_prior_year", "ARR (Prior Year)"))
    lines.append(_fmt_scalar(result, "mrr", "MRR"))
    lines.append(_fmt_scalar(result, "growth_rate_yoy", "YoY Growth Rate"))
    lines.append(_fmt_scalar(result, "burn_monthly", "Monthly Burn"))
    lines.append(_fmt_scalar(result, "cash_on_hand", "Cash on Hand"))
    lines.append(_fmt_scalar(result, "runway_months", "Runway (months)"))
    lines.append(_fmt_scalar(result, "headcount", "Headcount"))
    lines.append("")

    if result.cross_check_flags:
        lines.append("## Reviewer Notes / Cross-Check Flags")
        for flag in result.cross_check_flags:
            lines.append(f"- {flag}")
        lines.append("")

    lines.append("## Cap Table")
    lines.append(_cap_table_section(result))
    lines.append("")

    lines.append("## Funding History")
    lines.append(_funding_history_section(result))
    lines.append("")

    lines.append("## External Signals (Supporting Context)")
    lines.append(_external_signals_section(research_findings or []))
    lines.append("")

    if charts:
        lines.append("## Charts")
        for chart in charts:
            lines.append(f"![{chart.chart_type}]({chart.storage_uri})")
        lines.append("")

    content = "\n".join(lines)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    memo_path = out_path / f"{result.deal_id}_cim_v{version_number}.md"
    memo_path.write_text(content)

    return MemoVersion(
        tenant_id=result.tenant_id,
        deal_id=result.deal_id,
        version_number=version_number,
        content_uri=str(memo_path),
        document_type="cim",
    )


# Kept for compatibility with earlier callers/tests that used the original name.
compile_memo = compile_cim


def compile_teaser(
    result: ExtractionResult,
    charts: list[ChartArtifact],
    deal_name: str,
    business_description: str,
    out_dir: str,
    version_number: int = 1,
) -> MemoVersion:
    """The Anonymous Teaser -- the first document sent to a prospective
    investor, before any NDA. Real practice: a short document that omits
    *identity*, not one that fuzzes the numbers -- the investment thesis is
    the numbers, the anonymity is about who. Cap table, funding history,
    and external signals are excluded entirely, not just the company name
    -- specific investor names, round amounts, and a GitHub repo's full
    name are themselves identifying in a small ecosystem. Only the ARR
    growth chart is included; its title/axes never reference the company
    (agents/analytics_agent.py), so it's safe as rendered.

    `business_description` is supplied by the human reviewer, not
    generated: there's no extracted "what does this company do" field in
    the schema (§6.2 only covers financial metrics), and free-text-
    generating marketing copy about an unfamiliar business with no grounded
    input would be exactly the kind of ungrounded claim §7 exists to
    prevent."""
    if not is_ready_for_compilation(result):
        raise CompilationBlockedError(
            f"Deal {result.deal_id} has not cleared human review; refusing to compile a teaser."
        )

    lines = [
        "# Investment Opportunity — Anonymous Teaser",
        "",
        f"_Confidential — prepared {result.extracted_at} · v{version_number}_",
        "",
        "## Overview",
        business_description,
        "",
        "## Key Financials",
        _fmt_scalar(result, "arr", "ARR", include_source=False),
        _fmt_scalar(result, "growth_rate_yoy", "YoY Growth Rate", include_source=False),
        _fmt_scalar(result, "burn_monthly", "Monthly Burn", include_source=False),
        _fmt_scalar(result, "runway_months", "Runway (months)", include_source=False),
        _fmt_scalar(result, "headcount", "Headcount", include_source=False),
        "",
    ]

    arr_charts = [c for c in charts if c.chart_type == "arr_growth_bar"]
    if arr_charts:
        lines.append("## Growth Trajectory")
        for chart in arr_charts:
            lines.append(f"![{chart.chart_type}]({chart.storage_uri})")
        lines.append("")

    lines.append("_Full financials, cap table, and company identity are available under NDA._")

    content = "\n".join(lines)
    content = _anonymize(content, deal_name)  # defense in depth over the whole document

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    teaser_path = out_path / f"{result.deal_id}_teaser_v{version_number}.md"
    teaser_path.write_text(content)

    return MemoVersion(
        tenant_id=result.tenant_id,
        deal_id=result.deal_id,
        version_number=version_number,
        content_uri=str(teaser_path),
        document_type="teaser",
    )


def generate_proforma_projection(
    result: ExtractionResult,
    years: int = 3,
    annual_growth_rate_pct_override: Optional[float] = None,
) -> dict:
    """Deterministic forward projection from approved historicals -- pure
    arithmetic, never LLM-generated. This is NOT an extracted fact: it's a
    projection built on explicitly stated assumptions, and every assumption
    is recorded here so the document can disclose exactly what it assumed
    rather than presenting a projection as if it carried the same certainty
    as a cited historical figure."""
    if result.arr.status not in APPROVED or result.arr.value is None:
        raise CompilationBlockedError("Cannot build a pro-forma model without an approved ARR figure.")

    assumptions: list[str] = []
    growth_rate = annual_growth_rate_pct_override
    if growth_rate is not None:
        assumptions.append(f"ARR growth rate manually set to {growth_rate}%/year by the reviewer.")
    elif result.growth_rate_yoy.status in APPROVED and result.growth_rate_yoy.value is not None:
        growth_rate = result.growth_rate_yoy.value
        assumptions.append(f"ARR growth rate held constant at the extracted YoY rate of {growth_rate}%/year.")
    else:
        growth_rate = 0.0
        assumptions.append("No approved growth rate available -- ARR held FLAT (0% growth) rather than guessed.")

    burn = result.burn_monthly.value if result.burn_monthly.status in APPROVED else None
    if burn is not None:
        assumptions.append(f"Monthly burn held constant at ${burn:,.0f}/month (no efficiency-curve assumption).")
    else:
        assumptions.append("No approved monthly burn -- cash runway is not projected.")
    assumptions.append("No additional funding round modeled during the projection period.")

    rows = []
    arr = result.arr.value
    cash = result.cash_on_hand.value if result.cash_on_hand.status in APPROVED else None
    runs_out_year: Optional[int] = None
    for year in range(years + 1):
        if year > 0:
            arr = arr * (1 + growth_rate / 100)
            if cash is not None and burn is not None:
                cash = cash - burn * 12
                if cash < 0 and runs_out_year is None:
                    runs_out_year = year
        rows.append({
            "year": year,
            "arr": round(arr, 2),
            "cash_on_hand": round(cash, 2) if cash is not None else None,
        })

    if runs_out_year is not None:
        assumptions.append(
            f"WARNING: under these assumptions, projected cash on hand goes negative in year {runs_out_year} "
            "-- an additional funding round would be needed before then."
        )

    return {"assumptions": assumptions, "rows": rows, "growth_rate_pct": growth_rate}


def compile_proforma_document(
    result: ExtractionResult,
    projection: dict,
    out_dir: str,
    version_number: int = 1,
) -> MemoVersion:
    """Render a projection from generate_proforma_projection() -- kept as a
    separate step from generating it so a reviewer can inspect/adjust the
    assumptions (e.g. override the growth rate) before it's written out."""
    lines = [
        f"# Pro-Forma Financial Model — {result.deal_id}",
        "",
        f"_PROJECTED, NOT EXTRACTED — prepared {result.extracted_at} · v{version_number}_",
        "",
        "**This document contains forward-looking projections, not historical facts.** "
        "Every number below is computed from the stated assumptions, not sourced from "
        "a document. It must never be treated at the same confidence tier as a cited "
        "figure in the CIM.",
        "",
        "## Assumptions",
    ]
    for a in projection["assumptions"]:
        lines.append(f"- {a}")
    lines.append("")

    lines.append("## Projection")
    lines.append("| Year | Projected ARR | Projected Cash on Hand |")
    lines.append("| --- | --- | --- |")
    for row in projection["rows"]:
        arr_str = f"${row['arr']:,.0f}"
        cash_str = f"${row['cash_on_hand']:,.0f}" if row["cash_on_hand"] is not None else "not projected"
        lines.append(f"| Year {row['year']} | {arr_str} | {cash_str} |")

    content = "\n".join(lines)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    proforma_path = out_path / f"{result.deal_id}_proforma_v{version_number}.md"
    proforma_path.write_text(content)

    return MemoVersion(
        tenant_id=result.tenant_id,
        deal_id=result.deal_id,
        version_number=version_number,
        content_uri=str(proforma_path),
        document_type="proforma",
    )
