"""
Structured Extraction Agent — architecture doc §5.3.

Takes the Ingestion Agent's typed DocBlocks (not raw chunked text) and
extracts against the fixed schema in schemas.ExtractionResult, using
full-document-context prompting with schema-constrained JSON output.

Guardrails (architecture doc §7, CLAUDE.md) are enforced in code, not just
by asking the model nicely:
  1. Provenance is mandatory: any value the model returns without a
     source_block_id that actually exists in this document is rejected back
     to null/not_found — never trusted on the model's say-so alone.
  2. Independent cross-check pass: recomputes runway from cash_on_hand and
     burn_monthly, and growth_rate_yoy from arr and arr_prior_year, flagging
     disagreement with what the model extracted rather than silently
     picking one -- this is what catches a model conflating a growth
     MULTIPLE stated in prose ("grew 2.3x") with a percentage.
  3. Temperature=0 is used for reproducibility only, not as a hallucination
     guardrail — see (1) and (2) for the actual guardrails.
"""
from __future__ import annotations

from typing import Optional

import ollama
from pydantic import BaseModel

from schemas import (
    BlockType,
    CapTableRow,
    Document,
    ExtractedValue,
    ExtractionResult,
    FieldStatus,
    FundingRound,
)

DEFAULT_MODEL = "phi4-mini"

RUNWAY_CROSS_CHECK_TOLERANCE = 0.15  # 15% relative disagreement triggers a flag
GROWTH_RATE_CROSS_CHECK_TOLERANCE = 0.15


# --- LLM-facing schema -------------------------------------------------
# Deliberately narrower than schemas.ExtractionResult: this is exactly what
# we ask the model to produce. deal_id/document_id/extracted_at etc. are
# filled in by code afterward, never by the model.

class LLMValue(BaseModel):
    # value is numeric for every field this schema is used on (arr, mrr,
    # burn, cash, runway, headcount). A generic Optional[Any] here produces
    # an unconstrained `{}` branch in the JSON schema that Ollama's grammar-
    # constrained decoder collapsed to `null` almost every time on phi4-mini
    # -- pinning the type fixed it (verified against the sample doc).
    value: Optional[float] = None
    source_block_id: Optional[str] = None
    source_page: Optional[int] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None


class LLMCapTableRow(BaseModel):
    holder: Optional[str] = None
    pct: Optional[float] = None
    share_class: Optional[str] = None


class LLMFundingRound(BaseModel):
    round_name: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None
    lead_investor: Optional[str] = None
    source_block_id: Optional[str] = None
    source_page: Optional[int] = None


class LLMExtraction(BaseModel):
    arr: LLMValue
    arr_prior_year: LLMValue
    mrr: LLMValue
    growth_rate_yoy: LLMValue
    burn_monthly: LLMValue
    cash_on_hand: LLMValue
    runway_months: LLMValue
    headcount: LLMValue
    cap_table: list[LLMCapTableRow]
    cap_table_source_block_id: Optional[str] = None
    funding_history: list[LLMFundingRound]


EXTRACTION_INSTRUCTIONS = """You are the Structured Extraction Agent in a deal-screening pipeline.

You will be given a document broken into numbered BLOCKS, each with a stable
block id and page number. Extract these fields: arr, arr_prior_year, mrr,
growth_rate_yoy, burn_monthly, cash_on_hand, runway_months, headcount,
cap_table (list of holder/pct/share_class), funding_history (list of
round_name/amount/date/lead_investor).

Rules, no exceptions:
- Every value you extract MUST include the exact source_block_id and
  source_page of the block you took it from. Copy the block id exactly as
  written (e.g. "blk_abc123def456") -- do not invent, abbreviate, or
  renumber it.
- If a field is not stated in the document, set value to null and reason to
  "not_found_in_source". Do NOT guess, infer, or fill in a "typical" value
  for a company of this type.
- Numbers must be plain numbers (no "$" or "," or "%" characters) with the
  unit implied by the field name.
- growth_rate_yoy is a percentage (e.g. "grew 45% year over year" -> 45).
  A growth MULTIPLE stated in prose (e.g. "grew ARR 2.3x") is NOT the same
  number as a percentage -- if the document only states a multiple like
  that and does not separately state a percentage, treat growth_rate_yoy as
  not stated (null) rather than copying the multiple's digits into a
  percentage field. If both arr and arr_prior_year are extractable, prefer
  leaving growth_rate_yoy to be derived from those instead of guessing from
  prose.
- If cap_table has any rows, you MUST also set cap_table_source_block_id to
  the block id of the table those rows came from -- rows without it will be
  discarded.
- Every funding_history round MUST include its own source_block_id and
  source_page (a round can come from a different block than another round)
  -- rounds without a valid source_block_id will be discarded.
- Return only the JSON object -- no commentary.

BLOCKS:
{blocks}
"""


def _render_blocks(document: Document) -> str:
    rendered = []
    for block in document.blocks:
        header = f"[BLOCK {block.id} | page {block.page} | {block.block_type.value}]"
        if block.block_type == BlockType.TABLE:
            if isinstance(block.content, dict):  # excel row block: {cell_ref: value}
                body = ", ".join(f"{ref}={val}" for ref, val in block.content.items())
            else:  # pdf table block: list[list[str]]
                body = "\n".join(
                    " | ".join("" if cell is None else str(cell) for cell in row)
                    for row in block.content
                )
        else:
            body = str(block.content)
        rendered.append(f"{header}\n{body}")
    return "\n\n".join(rendered)


def _to_extracted_value(llm_value: LLMValue, valid_block_ids: set[str], unit: Optional[str]) -> ExtractedValue:
    """Map an LLM-reported value into ExtractedValue, enforcing the
    mandatory-provenance guardrail: no citation (or a fabricated one) means
    the value does not survive, regardless of what the model claimed."""
    if llm_value.value is not None and llm_value.source_block_id in valid_block_ids:
        return ExtractedValue(
            value=llm_value.value,
            unit=unit,
            source_block_id=llm_value.source_block_id,
            source_page=llm_value.source_page,
            confidence=llm_value.confidence,
            extraction_method=f"llm:{DEFAULT_MODEL}",
            status=FieldStatus.PROPOSED,
        )

    if llm_value.value is not None:
        # Model claimed a value but the citation is missing/invalid -- reject
        # it rather than trust an uncited number (architecture doc §7 rule 1).
        reason = "rejected_missing_or_invalid_citation"
    else:
        reason = llm_value.reason or "not_found_in_source"

    return ExtractedValue(
        value=None,
        unit=unit,
        source_block_id=None,
        source_page=None,
        confidence=None,
        extraction_method=f"llm:{DEFAULT_MODEL}",
        reason=reason,
        status=FieldStatus.NOT_FOUND,
    )


def _cross_check_runway(result: ExtractionResult) -> None:
    """Independent cross-check pass (§5.3, §7 rule 2): recompute runway from
    cash_on_hand / burn_monthly and flag disagreement instead of resolving
    it silently -- the human reviewer decides which number is right."""
    cash = result.cash_on_hand.value
    burn = result.burn_monthly.value
    runway = result.runway_months.value

    if cash is None or burn is None or runway is None:
        return
    if burn == 0:
        result.cross_check_flags.append(
            "runway_months cross-check skipped: burn_monthly is 0 (division by zero)"
        )
        return

    computed_runway = cash / burn
    if computed_runway == 0:
        return
    relative_error = abs(computed_runway - runway) / computed_runway
    if relative_error > RUNWAY_CROSS_CHECK_TOLERANCE:
        result.cross_check_flags.append(
            f"runway_months mismatch: extracted={runway}, "
            f"computed from cash_on_hand/burn_monthly={computed_runway:.1f} "
            f"({relative_error:.0%} relative disagreement)"
        )


def _cross_check_growth_rate(result: ExtractionResult) -> None:
    """Recompute growth_rate_yoy from arr / arr_prior_year and flag
    disagreement (§7 rule 2's "growth rate consistency across periods"
    example) rather than trusting the model's own arithmetic on prose --
    this is what catches a model conflating a stated growth MULTIPLE
    ("grew 2.3x") with a percentage, which happened during Phase 0
    validation on the sample document."""
    arr = result.arr.value
    arr_prior = result.arr_prior_year.value
    growth_rate = result.growth_rate_yoy.value

    if arr is None or arr_prior is None:
        return
    if arr_prior == 0:
        result.cross_check_flags.append(
            "growth_rate_yoy cross-check skipped: arr_prior_year is 0 (division by zero)"
        )
        return

    computed_growth_rate = (arr - arr_prior) / arr_prior * 100

    if growth_rate is None:
        result.cross_check_flags.append(
            f"growth_rate_yoy not extracted, but derivable from arr/arr_prior_year: "
            f"{computed_growth_rate:.1f}%"
        )
        return

    if computed_growth_rate == 0:
        return
    relative_error = abs(computed_growth_rate - growth_rate) / abs(computed_growth_rate)
    if relative_error > GROWTH_RATE_CROSS_CHECK_TOLERANCE:
        result.cross_check_flags.append(
            f"growth_rate_yoy mismatch: extracted={growth_rate}%, "
            f"computed from arr/arr_prior_year={computed_growth_rate:.1f}% "
            f"({relative_error:.0%} relative disagreement) -- model may have conflated "
            f"a growth MULTIPLE stated in prose with a percentage"
        )


def extract(document: Document, model: str = DEFAULT_MODEL, reviewer_feedback: Optional[str] = None) -> ExtractionResult:
    """Run the Structured Extraction Agent against one ingested document.

    `reviewer_feedback` is used for the bounded reject-retry loop in the
    human review checkpoint (§5.5): a rejected field is re-extracted with
    the reviewer's note folded into the prompt, rather than blindly re-run.
    """
    prompt = EXTRACTION_INSTRUCTIONS.format(blocks=_render_blocks(document))
    if reviewer_feedback:
        prompt += f"\n\nA human reviewer rejected a previous extraction attempt with this note -- take it into account: {reviewer_feedback}"

    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format=LLMExtraction.model_json_schema(),
        options={"temperature": 0},
    )
    llm_extraction = LLMExtraction.model_validate_json(response["message"]["content"])

    valid_block_ids = {b.id for b in document.blocks}

    result = ExtractionResult(tenant_id=document.tenant_id, deal_id=document.deal_id, document_id=document.id)
    result.arr = _to_extracted_value(llm_extraction.arr, valid_block_ids, "USD")
    result.arr_prior_year = _to_extracted_value(llm_extraction.arr_prior_year, valid_block_ids, "USD")
    result.mrr = _to_extracted_value(llm_extraction.mrr, valid_block_ids, "USD")
    result.growth_rate_yoy = _to_extracted_value(llm_extraction.growth_rate_yoy, valid_block_ids, "%")
    result.burn_monthly = _to_extracted_value(llm_extraction.burn_monthly, valid_block_ids, "USD")
    result.cash_on_hand = _to_extracted_value(llm_extraction.cash_on_hand, valid_block_ids, "USD")
    result.runway_months = _to_extracted_value(llm_extraction.runway_months, valid_block_ids, "months")
    result.headcount = _to_extracted_value(llm_extraction.headcount, valid_block_ids, None)

    if llm_extraction.cap_table_source_block_id in valid_block_ids:
        result.cap_table = [
            CapTableRow(holder=r.holder, pct=r.pct, share_class=r.share_class)
            for r in llm_extraction.cap_table
        ]
        result.cap_table_source_block_id = llm_extraction.cap_table_source_block_id
    elif llm_extraction.cap_table:
        result.cross_check_flags.append(
            "cap_table rejected: model returned rows without a valid cap_table_source_block_id"
        )

    result.funding_history = []
    for r in llm_extraction.funding_history:
        if r.amount is not None and r.source_block_id not in valid_block_ids:
            result.cross_check_flags.append(
                f"funding round rejected (round_name={r.round_name!r}): "
                "no valid source_block_id for its amount"
            )
            continue
        result.funding_history.append(FundingRound(
            round_name=r.round_name, amount=r.amount, date=r.date,
            lead_investor=r.lead_investor, source_block_id=r.source_block_id,
            source_page=r.source_page,
        ))

    _cross_check_runway(result)
    _cross_check_growth_rate(result)
    return result
