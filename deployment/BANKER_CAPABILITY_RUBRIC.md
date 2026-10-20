# Local banker capability diagnostic rubric

Status: proposed synthetic diagnostic, independent human review UNRUN. No investor
acceptance, training approval or release qualification is implied. The fixture is
fictional North Quay Workflow Ltd; no private reference numbers were used.

## Evaluation boundary

Give inference only `evals/agentic_banker/fixtures/local_capability/input.txt`.
Never include the sibling `answer_key/`, scorer findings, expected values or this
rubric's quantitative key references in an inference request. Freeze the input
SHA256, model/adapter pin, prompt, tool observations, raw responses and exported
artifact hashes before scoring. If the model has seen this fixture or its key,
label the run known-case regression rather than held-out evidence. Keep this case
out of training. Code may inspect and calculate; company interpretation, model
structure, formulas, assumptions and memorandum prose must be recorded model work.

The key's standalone stdlib Decimal calculator is a separate evaluation instrument,
not the product model or a replacement answer. Decimal numbers are JSON strings
to preserve precision. Compare economic values after currency/scale normalization;
tolerance is USD0.005 thousand (USD5) per financial cell, not a tolerance for wrong
periods, units, unexplained assumptions or unsupported claims. The key specifies
end-year funding adequacy only, never intra-year liquidity.

## Mandatory objective gates

All must be passed for a complete synthetic diagnostic. Missing, unrun or
unsupported checks block completion; do not average them out of a score.

- Exported XLSX contains the agent's live formulas, evidence-linked historical
  inputs, explicit illustrative assumptions, all three scenarios and connected
  P&L/cash flow/funded balance sheet. Independently recalculate exported bytes;
  zero formula errors, circularities, hidden unsupported hardcodes or plug balances.
- FY2024/FY2025 history, each forecast period, working capital, debt interest and
  repayments, equity issuance, cash need and ask comparison match the separate
  objective key. Every funded balance sheet balances through named movements.
- History is reported synthetic; each forward-looking financial claim and chart
  is illustrative/company_projection. No forecast is called validated. Missing
  FY2024 cash-flow data stay missing; no actual ARR, TAM, churn or valuation is invented.
- Every numerical memorandum assertion binds to an exact exported workbook cell,
  period, unit and scenario; 100% agreement after display rounding. Percentage
  comparisons have the correct denominator/direction. Rounded prose must not hide
  the downside financing deficit or unfunded cash shortfalls.
- IM DOCX/PDF contain substantive business/evidence scope, historical MD&A,
  operating-driver/scenario interpretation, cash conversion and funding discussion,
  capital policy/ask comparison, downside risks, unknowns and prioritized diligence.
  Inspect exported files for readable tables, layout and editable content.

## Human banker judgment (score each 1–5)

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Connected modelling logic | Disconnected or materially wrong | Mostly linked, important unresolved movement | Clear independently reconciled IS/CF/BS, no unexplained plugs |
| Assumption defensibility | Invents/obscures assumptions | Repeats parameters with limited discussion | Separates evidence from illustration, explains sensitivities and limitations |
| MD&A and cash reasoning | Lists figures or draws wrong conclusions | Correct trends with incomplete causal discussion | Explains growth, operating leverage, working-capital cash conversion, capex/debt and scenario financing implications |
| Action titles and tables | Generic, misleading or unreadable | Correct but descriptive | Concise conclusions supported by exact workbook facts, with useful comparison tables |
| Risk and diligence judgment | Omits material shortfalls/unknowns | Lists generic risks and missing data | Prioritizes financing, execution and evidence gaps with concrete questions and release conditions |
| Storyline and usability | Incoherent or promotional | Usable internal draft with substantial edits | Coherent banker memorandum with sourced claims, restrained language and clear decision path |
| Would I send this internally? | Unsafe/inaccurate | Needs substantial review | Ready for qualified internal human review, with scope/unknowns explicit |

Scores 2 and 4 are intermediate. Record reviewer identity, model independence,
artifact hashes, dimension scores and evidence-based comments. A target of at
least 4 on every dimension is proposed; objective gates still apply. A synthetic
pass proves only this case. A separate unseen multi-company evaluation, private
reference qualification, visual checks and authorized human review remain required
before real investor use. No synthetic case score grants external release.
