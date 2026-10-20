# D1 baseline: installed local models on the fictional North Quay case

20 October 2026. First real inference against `fixtures/local_capability/input.txt`
(fictional North Quay Workflow Ltd; no private data). Local Ollama on 127.0.0.1 only,
native `/api/chat`, temperature 0, `think:false`, `num_ctx` 12288, one model resident at a time,
`OLLAMA_KEEP_ALIVE=0`. The model saw only the input text (wrapped as `case.json`);
`answer_key/` was never given to inference. Raw trajectories, receipts and workbooks are in the
git-ignored `runtime_qualification/agentic_banker/2026-10-20-baseline/`.
Scoring: `scripts/score_north_quay_baseline.py` (label-blind value-presence against the 310
key figures, tolerance USD0.005k; generous upper bound). Harness: `scripts/evaluate_local_banker.py`.
No retries within a run; each row is a separate recorded run.

## Runs

| Run | Model / scope / passes | Result | Calls | Seconds | Tokens | Terminal cause |
|---|---|---|---|---|---|---|
| r1 | qwen3.5:9b full, 1 | modeling_failed | 2 | 67.4 | 6,211 | `$.values: invalid JSON type` on the 2nd call |
| r2 | qwen3.5:9b full, 3 | modeling_failed | 2 | 81.0 | 6,211 | identical to r1 (temp 0 is deterministic) |
| r5 | qwen3.5:9b full, 3 (resample) | modeling_failed | 2 | 120.0 | 2,547 | 120 s pass budget hit during call 2 |
| r6 | qwen3.5:9b pnl, 3 | modeling_failed | 2 | 50.1 | 2,653 | `native model mismatch`: Ollama returned an empty frame (`model:""`, `done:false`) |
| r3 | qwen3:14b full, 3 | modeling_failed | 1 | 120.0 | 0 | first call exceeded the 120 s budget (no response) |
| r4 | qwen3.5:4b full, 3 | modeling_failed | 2 | 120.0 | 2,540 | 120 s budget hit during call 2 |

Scorer result for ALL six runs: 0 numeric cells, 0 formula cells, 0 of 310 key figures found, no
statements, no FY2025 balance, no funded balance sheets, no cash-floor or scenario output,
no memo, no export (`status` never reached the writer pass). The only workbook output is
empty named sheets (e.g. Assumptions, History, Scenarios, Cash_Need, Balance_Sheet, Memorandum).
Scorer `workbook_exported: true` in `scores.json` means the scratch `model.xlsx` exists, NOT that a
draft pack was exported.

## What actually happened

- Every run died in the first modeling pass at call 1-2 of a 6-call allowance. The model's first
  call (qwen3.5:9b, 4b) is a batch of `wb.add_sheet` calls; the second tries to write the whole
  assumptions grid in one `wb.write_block`.
- r1/r2 failure mode: the model emitted `values` as a JSON-encoded STRING containing a
  non-JSON expression (`1/12`, `1/6`) instead of a nested array of literals. The strict harness
  correctly failed closed. Also visible in the rejected call: revenue per customer entered as
  12000 although the case unit is USD thousands (12), and FY2025 / historical status labels
  applied to assumption values (Capex, tax rate labelled "historical").
- Speed: qwen3.5:9b generates about 21 tokens/s (830 tokens in 39.6 s) with about 5 s to evaluate
  a 2.4k-token prompt. The 120 s per-pass bound therefore allows roughly 2,000 generated tokens
  including prompt processing and model load (3-4 s), far less than a 3-scenario, 3-year model
  with notes requires. qwen3.5:4b was no faster in the measured first call (164 tokens in 8.5 s).
  qwen3:14b (10 GB resident) did not return one response within 120 s.
- Memory: the Mac was already under pressure (swap about 5.5 of 7 GB used before and after, about
  70 MB free pages, compressor over 700k pages in every trace). Resident model sizes: 9b 5.8-5.9 GB,
  14b 10 GB, 4b 3.5 GB, all 100% GPU, 12k context. No crash, `ollama stop` honoured every time.
  The 14b timeout is likely partly memory-pressure related; this was not isolated.
- Run-to-run: temp 0 reproduced r1 exactly in r2 (same tokens), but r5 (same model/params)
  diverged and timed out, so latency is not stable even when decoding is.

## Capability verdict

None of the installed models (qwen3.5:9b, qwen3:14b, qwen3.5:4b) can currently complete even the
modeling pass for this case under the present harness bounds (6 calls, 120 s, 2,200 output
tokens per call). Measured capability on the objective key is 0/310. This is a floor measurement
of "model plus harness as configured", not a proof that a longer-budget or fine-tuned model could
not do it. Not an investor-acceptance or quality claim; the qwen3:8b, phi4-mini and llama 3.2 models were not
attempted (smaller/older, not in the ordered list).

## Top failure modes (feed training task design)

1. Tool-argument well-formedness: nested JSON passed as a stringified value; arithmetic
   expressions (`1/12`) inside JSON literals. Needs formulas as `=` strings and plain numbers.
2. Over-large single writes: whole workbook in one `wb.write_block` against a 2,200 output token cap;
   need decomposition into small blocks per sheet/section.
3. Wall-clock budget: about 2,000 tokens per pass at about 21 tok/s; model must plan terse, formula-driven
   sheets (fill-right/down patterns) rather than hardcoded values.
4. Unit and status discipline: USD thousands vs dollars (12000 vs 12), historical vs
   illustrative labelling of assumptions.
5. No evidence of recovery behaviour: after a tool error the harness ends the pass, so
   error-correction is untested. Observation-driven repair needs training and a harness that returns
   tool errors to the model instead of terminating (harness change, not owned here).
6. Server-side anomaly: empty native response frame (r6) terminated a run; needs transport-level
   classification (retryable infra fault vs model failure) while keeping the no-blind-retry rule.
7. Not exercised at all: formula wiring across sheets, balance-sheet tie-out without plug, equity
   injection solve, scenario switch, memo binding, source citations.

## Implied training environments (E1-E7)

- E1 Tool-call syntax: valid `wb.*` arguments only (nested arrays, literals, `=` formulas), reward
  on schema validity, no stringified JSON or inline arithmetic.
- E2 Units and provenance: thousands scaling, status labels (historical / company_projection /
  illustrative), source ID comments per input cell.
- E3 Small-block workbook construction: build one sheet per call within a token cap, with
  fill-right year formulas referencing an assumptions sheet.
- E4 Historical statements: P&L, cash flow and FY2025 balance sheet reconciliation without plugs
  (cash 207.5, equity 277.5 style tie-outs scored by the independent key).
- E5 Forecast + scenario engine: three-scenario drivers, debt/interest/tax/working capital,
  unfunded cash path, then equity-injection solve and funded balance sheet check.
- E6 Error recovery: tool returns errors/diagnostics (findings from `wb.recalc`), model fixes
  specific cells within the call budget.
- E7 Memo writing from workbook cells: numeric bindings to cells, uncertainty and diligence
  requests, no unsupported claims.

## Needed from others (not edited here)

- Harness/session owner: consider a post-error repair turn, a larger per-pass token/time budget
  for diagnostic runs, and an infra-fault classification for empty native frames.
- Memory: close other apps before 14b-class runs; swap was heavily used throughout.

## Ollama state left

Server started by this task was stopped (`pkill -f "ollama serve"`); `ollama ps` was empty before
stopping and no ollama process remains. No model downloaded, nothing committed, DB untouched.

## Re-baseline after repair protocol

20 October 2026, agent B2. Same fictional North Quay case, same model (qwen3.5:9b, native Ollama
`/api/chat`, loopback only, temperature 0, `think:false`, `num_ctx` 12288, `OLLAMA_KEEP_ALIVE=0`,
one model resident, Ollama server started and stopped by this task). Answer key never shown to the model.
Scoring: `scripts/score_north_quay_baseline.py` (label-blind value presence; a generous upper bound).
Runs are in the git-ignored `runtime_qualification/agentic_banker/2026-10-20-baseline/b2-r7-*` and `b2-r8-*`
(full trajectories, raw receipts for every call including repairs, per-block diagnostics, `report.json`).

Harness changes used (see `evals/agentic_banker/ws-b/BANKER_HARNESS.md`): bounded repair protocol (model-visible
tools/v1 errors, each repair a new counted model call, 2 consecutive / 6 total), fault classes in the report,
one labelled infra resume, small-block ledger (7 blocks: historical IS, historical BS/cash flow, drivers, base
forecast, two further scenarios, funding), improved tool examples (stringified array, arithmetic literal,
ragged rows, units). **Explicit diagnostic profile, not the default**: 240 s and 10 calls per block, 200 s per
model call, 2,200 output tokens per call, 1,800 s session cap (defaults of 120 s / 6 calls are unchanged).

| Run | Harness state | Status | Calls | Seconds | Tokens | Blocks completed | Figures found (of 310) | Formula cells |
|---|---|---|---|---|---|---|---|---|
| D1 r1-r6 | single pass, no repair | modeling_failed | 1-2 | 50-120 | 0-6,211 | 0 | 0 | 0 |
| b2-r7 | blocks + repair (before workbook-recovery fix) | modeling_failed | 23 | 775 | 77,694 | 1 of 7 | 35 | 8 |
| b2-r8 | blocks + repair + workbook recovery | modeling_failed | 20 | 1,454 | 64,727 | 1 of 7 | 44 (18 by formula) | 114 (98 recalc findings) |

Neither run produced a funded balance sheet, a FY2025 balance tie-out, any scenario equity solve, a memo or an
export; the writer pass never started (fewer than half of the blocks completed). 44/310 is value presence only
(coincidental matches possible, no check of labels or wiring). It is progress over 0/310, not a capability pass.

### What the new protocol demonstrated

- Only block `hist_is` (historical income statement, 69 cells) finished cleanly in both runs, in 99-101 s with
  4-5 calls. This is the first real run that reached a completed modelling block.
- Repair worked as designed where it fired: b2-r8 `alt_forecast_2` received a structured error and issued a
  corrected call (1 repair call). In b2-r7 three repairs per block reached the cap on a tool defect, below.
- The D1 failure mode (stringified `values` with `1/12`) did not recur in either run; the first-call argument
  shape was valid in all blocks. This is a small sample, not evidence it is solved.

### Defect found in agents/tools (not owned here, reported, NOT edited)

`WorkbookTools` rolls back a failed mutating call with `self.book = original` where `original = deepcopy(self.book)`.
After any cell comment exists, the deep-copied workbook cannot be deep-copied again, so every later mutating call
(`wb.add_sheet`, `wb.write_block`, ...) fails with `TypeError: __init__() missing 1 required positional argument:
'worksheet'`. Minimal reproduction: add sheet, `write_block` with a `comment`, one ragged `write_block`, then `add_sheet`.
In b2-r7 this poisoned blocks 4-7 (12 failed tool calls, each ending in `repair_cap_reached`), so those four
blocks are not a model measurement. The harness now reloads the last saved workbook file after a failed mutation
(`workbook_reloads` in the report); b2-r8 used that, and the blocks after it were no longer poisoned. The upstream fix
belongs to the tools owner (rollback by reloading the saved file instead of deepcopy).

### Remaining failures in b2-r8, and what they are

- Wall clock is the binding limit. Generation was 11-14 tokens/s here (memory pressure, swap about 4.3 of 5 GB
  at start), below D1's 21 tok/s; one full 2,200-token call is 160-200 s. `hist_bs` ended `budget_exhausted` at
  240 s after 4 calls (it had written 3 cells), and `drivers` produced one response that hit the 2,200-token
  output cap with no tool call (`model_error`, 211 s).
- Four of the five calls recorded as `infra_fault` in `report.json` were socket timeouts at the explicit 200 s
  per-call cap. That is a latency/budget limit, not a server fault; the classifier has since been corrected so a
  timeout at the call cap is `budget_exhausted` (unit test added). The `report.json` files are left unaltered, so
  the corrected b2-r8 split is: model_error 1, budget_exhausted 6 (of which 5 reclassified), true infra faults 0.
  The one infra resume used (hist_bs) was a timeout, so it did not test the empty-frame case on a recurring fault.
- b2-r7 did record the empty Ollama frame (`{"model":"","done":false}`) twice on the same request in `hist_bs`:
  once, and again on the single labelled resume. Identical requests at temperature 0 reproduced it, so it is a
  deterministic server-side failure for that request, not transient, and a resume cannot cure it. The Ollama log does
  not state a cause (it may be an upstream tool-call parse failure). It is now classified `infra_fault` and is not
  counted as model capability, and the report flags `infra_resume_reproduced` when a resume repeats it.
- Content quality of what was written is poor: b2-r8 left 98 recalc findings; forecast formulas in b2-r7 were
  structurally wrong (e.g. gross profit as `=B4`, constant `*1.2` growth rather than driver references, ragged rows),
  and the historical balance sheet and funded solve were never built. The block ledger gives a 12-14 tok/s model
  room to start, not the ability to finish; no block beyond the historical income statement completed.

### Verdict

The harness no longer ends a pass on the first argument error, separates fault classes, and can drive the model
block by block with receipts for every call. With that, qwen3.5:9b moved from 0/310 to 35-44/310 figures and one
completed block. It still did not complete the first full modelling pass (1 of 7 blocks, no funded balance sheet,
no memo): under the measured generation speed the block budgets, plus real model errors on forecast construction,
stop it. This is a floor for qwen3.5:9b plus this harness on this Mac under memory pressure. It supports no claim
about banker capability, a faster machine, or a trained model. Two real sessions were used (the permitted maximum).
