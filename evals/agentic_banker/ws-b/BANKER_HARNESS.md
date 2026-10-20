# Bounded local banker capability harness — 16 October 2026

New opt-in CLI: `python scripts/evaluate_local_banker.py --case INPUT.json
--output NEW_PRIVATE_DIRECTORY --model qwen3.5:9b --run`.
Without --run it validates local input only, with no model/network calls and no
claim that the model is installed. Root operator performs installed-model preflight.

Modeling Analyst chooses workbook content and returns JSON metrics, calculated
ranges and assumptions; IM Writer authors native memo sections and explicit
bindings. Host code inventories the generated workbook, runs diagnostic arithmetic,
exports exact model-written memo content and retains outputs. Answer keys are
excluded from model-visible case objects. No company-specific outputs/defaults.
One Modeling Analyst pass plus one IM Writer pass by default, each capped at six
calls/120 seconds/8192 accounted tokens. `--passes 2|3` permits only bounded
modeling correction passes driven by observed diagnostic findings; failed or
exhausted model calls are never retried. Cumulative calls/tokens/time are reported.
No production hookup, downloads, training, cloud or hosted inference.

Native Ollama /api/chat uses explicit think:false, stream:false, temperature:0,
num_ctx:12288, num_predict:2200 and presence_penalty:0. Native request/response body
bytes are captured through runtime receipts. Adapter normalization discloses
synthetic protocol call IDs and uses actual native usage counters only. Missing
usage, nonterminal results, model mismatches and malformed calls fail closed.
Socket operations remain cooperative and do not establish hard cancellation.

11 lightweight offline tests passed, including fake-socket native adapter checks,
failed-call no-retry, answer-key rejection and a fully scripted workbook+native
DOCX plumbing test. Scripted results prove plumbing only. No installed model was
called for this workstream checkpoint; actual model capability remains unproven.

## Repair protocol, fault classes and block ledger — 20 October 2026 (agent B2)

- `AgentRuntime(repair=RepairPolicy(max_consecutive=2, max_total=6))`: a tool call that fails argument parse,
  schema validation or the role allowlist is NOT executed; the model receives a tools/v1 error (`code`, `path`,
  `expected_schema` snippet, `hint`) and may send a corrected call. Later calls in the same batch are reported
  `SkippedAfterFailure`. A tool that executes and returns `ok:false` counts toward the caps. Every repair is a new
  counted model call (budgets, receipts, trajectory `tool_failure` events with the raw arguments). An identical
  validation-failed call is refused (`IdenticalFailedCall`) and a request byte-identical to an earlier one raises
  `identical model request replay forbidden`. Cap exceeded ends the pass as `repair_cap_reached` (model_error).
  Without `repair` the original fail-closed behaviour is unchanged.
- Fault classes (`fault_class`, `faults`, report `fault_summary`): `model_error` (invalid content, output cap hit,
  repair cap), `infra_fault` (empty native frame, HTTP 5xx, connection errors, timeouts that are not at a deadline),
  `budget_exhausted` (pass/call/token/step limits and timeouts at a deadline or per-call cap), `harness_error`.
  `resume_after_infra_fault()` permits ONE labelled resume of the same session state (the identical request may be
  re-sent once; logged as `infra_resume`); a session allows one in total and never for model errors.
- `--mode blocks`: seven generic blocks (historical IS, historical BS/cash flow, drivers, base forecast, two more
  scenarios, funding), each its own runtime directory, budget, receipts and a read-only diagnostic
  (`wb.recalc` findings plus the `agents.tools.formula_engine` summary). Later blocks see a capped cell digest of
  the workbook and the previous block's diagnostic. Final per-block JSON specs are merged unvalidated.
- Budgets: defaults unchanged (120 s, 6 calls, 2,200 output tokens). `--profile diagnostic` is an explicit labelled
  profile (up to 600 s / 24 calls per runtime; the report records `budget_profile`). Flags: `--block-seconds`,
  `--block-calls`, `--block-tokens`, `--output-tokens`, `--call-seconds`, `--session-seconds`, `--repair-consecutive`,
  `--repair-total`, `--no-repair`, `--infra-resume`, `--blocks`, `--stop-on-block-failure`.
- Host workbook recovery: after a failed mutating workbook call the session reloads the saved workbook, because the
  current `agents/tools` rollback (deepcopy) leaves a workbook that has comments unusable. Remove this once the tools
  owner fixes rollback. No argument is coerced anywhere; examples in the role prompt and `block_ledger.TOOL_EXAMPLES`
  show the shape (arrays not strings, formulas as `=` strings, rectangular rows, no rescaling of units).
- Tests: `tests/runtime/test_repair_blocks.py` (offline, fake transports). Real-model evidence: d1-baseline README.
