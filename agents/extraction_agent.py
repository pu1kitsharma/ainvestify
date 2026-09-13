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

import re
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
    #
    # value/source_block_id/source_page have NO default (`= None`)
    # deliberately, even though their type is Optional -- a field with a
    # default isn't marked "required" in the generated JSON schema, and
    # found live on a second, differently-worded test document: phi4-mini's
    # grammar-constrained decoder sometimes omits the "value" key from its
    # JSON output *entirely* for a field it struggled with, rather than
    # writing `"value": null`. Pydantic then silently defaults the missing
    # key to None, which _to_extracted_value can't distinguish from a
    # genuine "not stated in the document" -- it silently misclassifies a
    # decoding failure as a confident not-found result. Making these three
    # fields required-but-nullable forces "required" into the schema, so
    # the model must emit the key (with an explicit null if it has nothing)
    # rather than being able to skip it.
    value: Optional[float]
    source_block_id: Optional[str]
    source_page: Optional[int]
    confidence: Optional[float] = None
    reason: Optional[str] = None


class LLMCapTableRow(BaseModel):
    holder: Optional[str] = None
    # No default, same reasoning as LLMValue.value above -- pct is the
    # numeric field a dropped-key decoding failure would otherwise silently
    # misreport as "not stated."
    pct: Optional[float]
    share_class: Optional[str] = None


class LLMFundingRound(BaseModel):
    round_name: Optional[str] = None
    # No default: same reasoning as LLMValue -- amount/source_block_id/
    # source_page are exactly what funding_history's own guardrail below
    # checks for presence of, so a silently-defaulted None here would slip
    # straight past that check instead of being caught by it.
    amount: Optional[float]
    date: Optional[str] = None
    lead_investor: Optional[str] = None
    source_block_id: Optional[str]
    source_page: Optional[int]


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
- arr (Annual Recurring Revenue) and mrr (Monthly Recurring Revenue) are
  DIFFERENT metrics stated under different labels -- never copy one's value
  into the other, and never multiply/divide between them yourself. If the
  document states MRR but never separately states ARR under an "ARR" or
  "Annual Recurring Revenue" label, arr must be null/not_found, even though
  a human could compute ARR ≈ MRR × 12 -- that computation is for the human
  reviewer to make deliberately, not something you infer silently. The same
  independence applies to arr_prior_year vs mrr's own prior-year figure.
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


def _cross_check_arr_mrr_conflation(result: ExtractionResult) -> None:
    """Flag arr/mrr (and their prior-year counterparts) sharing the same
    cited block AND the same value -- a real, reproduced-live failure mode
    where phi4-mini copies a stated MRR figure straight into arr (or vice
    versa) despite an explicit prompt instruction not to. ARR and MRR are
    different metrics on different time scales; the only way they'd
    legitimately be numerically identical is if the shared value were 0.
    Consistent with every other cross-check in this file: flag for the
    human reviewer, don't silently null the value -- prompting alone
    couldn't be trusted to prevent this, but code can at least surface it
    rather than let it pass as a normal-looking pair of extracted fields."""
    for annual_field, monthly_field, label in (
        ("arr", "mrr", "arr/mrr"),
        ("arr_prior_year", "mrr", "arr_prior_year/mrr"),
    ):
        annual = getattr(result, annual_field)
        monthly = getattr(result, monthly_field)
        if (
            annual.value is not None
            and annual.value != 0
            and annual.value == monthly.value
            and annual.source_block_id == monthly.source_block_id
        ):
            result.cross_check_flags.append(
                f"{label} share the same value ({annual.value}) and source block -- "
                "the model may have copied a monthly figure into the annual field "
                "(or vice versa) instead of treating them as distinct metrics"
            )


CONTEXT_WINDOW_BUCKETS = [4096, 8192, 16384, 32768, 65536]
GENERATION_HEADROOM_TOKENS = 1024  # room for the JSON extraction output itself


def _estimate_num_ctx(prompt: str) -> int:
    """Pick a context window large enough for this specific document's
    full-document-context prompt, rounded up to a fixed bucket.

    Found live on a real, dense multi-page SEC filing: the fixed 4096
    default (fine for the small synthetic fixture docs this was originally
    validated against) was smaller than the prompt itself, silently
    triggering llama.cpp's --context-shift fallback -- which discards early
    context and re-processes on overflow, at wall-clock costs an order of
    magnitude worse than just requesting a correctly-sized window up front.
    A ~4 chars/token estimate is intentionally rough; bucketing (rather than
    sizing exactly) keeps Ollama from having to reload the model on every
    slightly-different document.
    """
    estimated_tokens = len(prompt) // 4 + GENERATION_HEADROOM_TOKENS
    for bucket in CONTEXT_WINDOW_BUCKETS:
        if estimated_tokens <= bucket:
            return bucket
    return CONTEXT_WINDOW_BUCKETS[-1]


_NUMBER_PATTERN = re.compile(r"\(?-?\$?\s?\d[\d,]*\.?\d*\)?")
_CITATION_CHECK_SCALES = (1, 1000, 0.001, 100, 0.01)
_CITATION_CHECK_RELATIVE_TOLERANCE = 1e-6


def _numbers_in_block(document: Document, block_id: str) -> set[float]:
    """Every plain number that literally appears in one block's rendered
    content, parsed from '$1,125,000'/'(2,229)'-style formatting."""
    block = next((b for b in document.blocks if b.id == block_id), None)
    if block is None:
        return set()
    if block.block_type == BlockType.TABLE:
        if isinstance(block.content, dict):
            content_str = ", ".join(f"{ref}={val}" for ref, val in block.content.items())
        else:
            content_str = "\n".join(
                " | ".join("" if cell is None else str(cell) for cell in row)
                for row in block.content
            )
    else:
        content_str = str(block.content)

    numbers = set()
    for match in _NUMBER_PATTERN.finditer(content_str):
        token = match.group().strip()
        is_negative = token.startswith("(") and token.endswith(")")
        token = token.strip("()").replace("$", "").replace(",", "").strip()
        if not token or token == ".":
            continue
        try:
            value = float(token)
        except ValueError:
            continue
        numbers.add(-value if is_negative else value)
    return numbers


def _cross_check_citations_supported_by_content(result: ExtractionResult, document: Document) -> None:
    """Flag a field whose cited block doesn't actually contain its value.

    Found live on a real SEC filing: the mandatory-provenance guardrail
    (_to_extracted_value) only checks that source_block_id is a real block
    in this document -- it was never checked that the block's own content
    backs up the number attached to it. On DigitalOcean's real 10-Q,
    phi4-mini cited cash_on_hand and headcount to blocks that are pure
    boilerplate text containing no numbers at all -- the *values* it
    reported happened to be correct (pulled from elsewhere in the document),
    but a reviewer clicking the citation to verify would find nothing there.
    This is a heuristic, not a hard rejection (scale conversions like
    "$1,125 million" -> 1,125,000 in thousands-of-dollars are legitimate and
    shouldn't be flagged as unsupported) -- checked at common scale factors
    (x1/x1000/x100 and their inverses) before flagging, and always flags
    rather than nulls the value, consistent with every other cross-check
    here: surface it for the human reviewer, don't decide on their behalf.
    """
    fields = [
        ("arr", result.arr),
        ("arr_prior_year", result.arr_prior_year),
        ("mrr", result.mrr),
        ("burn_monthly", result.burn_monthly),
        ("cash_on_hand", result.cash_on_hand),
        ("runway_months", result.runway_months),
        ("headcount", result.headcount),
    ]
    for field_name, extracted in fields:
        if extracted.value is None or not extracted.source_block_id:
            continue
        block_numbers = _numbers_in_block(document, extracted.source_block_id)
        if not block_numbers:
            result.cross_check_flags.append(
                f"{field_name}={extracted.value} cites block {extracted.source_block_id}, "
                "but that block contains no numbers at all -- citation is likely fabricated "
                "or misattributed; verify manually before trusting this value"
            )
            continue
        supported = any(
            abs(extracted.value * scale - n) <= max(abs(n) * _CITATION_CHECK_RELATIVE_TOLERANCE, 1e-6)
            for scale in _CITATION_CHECK_SCALES
            for n in block_numbers
        )
        if not supported:
            result.cross_check_flags.append(
                f"{field_name}={extracted.value} cites block {extracted.source_block_id}, but no "
                "number in that block's content matches this value at common unit scales "
                "(x1/x1000/x100) -- citation may be fabricated or misattributed; verify manually "
                "before trusting this value"
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
        options={"temperature": 0, "num_ctx": _estimate_num_ctx(prompt)},
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
    _cross_check_arr_mrr_conflation(result)
    _cross_check_citations_supported_by_content(result, document)
    return result
