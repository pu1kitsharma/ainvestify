# Local multi-agent execution log

15 October 2026. User explicitly requested multiple agents and local VS Code /
Claude Code work. Coordinator read the external plan and current repository
handoffs. Baseline branch `codex/frontend-release-readiness-2026-10-04`, commit
`c469ff3`; the initial checkout was clean.

| Agent | Isolated worktree / branch | Owned scope |
| --- | --- | --- |
| WS-A | `.worktrees/ws-a`, `ws-a/analyst-workbook` | Workbook/document tools, `tools/v1` envelope, synthetic tests |
| WS-B | `.worktrees/ws-b`, `ws-b/agent-runtime` | Runtime, concrete local HTTP transport, role prompts, task ledger and tests |
| WS-C | `.worktrees/ws-c`, `ws-c/training-environments` | Offline reward/split contracts, scorer, mock expert iteration and tests |
| Coordinator | Original checkout | Endpoint policy, draft pack tools, VS Code and local Claude launcher, integration and documentation |

Tool observations are frozen as `{version:'tools/v1', ok:bool, tool:str,
result:object, errors:list}`. Errors report unsupported/unrun features rather
than replacing agent content. Coordinator integrated owned source files by
copy; no workstream commits or branch merges were performed.

Initial integration exposed missing document-tool copy and a nonfinite-input
log error; both were fixed. Independent WS-B review found redirect handling,
mutable bindings and duplicate tool-call risks. Redirects are rejected, pack
bindings copied, and runtime duplicate IDs reserved before effects. Partial
multi-file export recovery and hard subprocess cancellation remain open.

Live SQLite was queried read-only: 22 awaiting-input, three blocked, four
cancelled and two queued jobs; zero active leases. No service restart, worker,
model download, real training, cloud action, commit or push was performed.
Ollama preflight observed installed models and zero loaded models. VS Code was
opened with the multi-worktree workspace; the Claude extension was already
installed. An explicit inference question was sent because the supplied plan
requires asking before starting Mac inference. No answer is inferred from time.

Focused evidence is under `evals/agentic_banker/ws-{a,b,c}/`; these contain
synthetic software checks only. Private gold, references, trajectories and
adapters remain outside Git. Read the execution document for open gates.

Final focused checks passed 86 tests. Wider regression: 3,450 passed, 27 failed,
seven skipped; the green-suite gate remains open. Four selected failures were
reproduced on unchanged baseline; an additional failure passed in isolated
baseline and integrated reruns. Remaining failures are not all baseline-classified.
See `evals/agentic_banker/LOCAL_CHECKPOINT.md` for exact scope and caveats.

## 16 October — checkpoint 2

User requested the next checkpoint. Existing WS-A/B/C worktrees were reused.
WS-A supplied 21 explicit schema registrations; WS-B added raw HTTP body
receipts, terminal/model/content validation and pre-effect schema checks;
WS-C repaired stale/authenticated test fixtures, isolated audited live tests,
and reproduced the source-byte timestamp regression deterministically.
Coordinator added atomic draft-pack export, source-identity checks, immutable
manifest replay and the scripted role session. Independent review identified
unbounded verification reads and missing root trajectory bindings; both were
corrected before the final session-003 exercise.

The synthetic session uses six scripted responses and zero real model calls.
Its workbook, two-slide deck, embedded chart and memo are diagnostic artifacts
only. Exact byte replay succeeds without rerendering or new tool effects.
All earlier evidence is preserved. Qualified Office recalculation, visual parity,
private native isolation, real-model team behavior and training remain open.
See `evals/agentic_banker/CHECKPOINT_2.md` for artifact hashes and validation.

Final offline suite after all code/test fixes: 3,513 passed, 20 skipped, zero
failures (167.23 seconds). The 20 unrun live/native/Office checks still block
their release gates. Focused checks: 127 passed. No actual model invocation,
training, download, private-reference processing, cloud spend, restart, commit
or push occurred. Final room counts and queued jobs matched baseline.

## 20 October — Phase A completion round

User authorized local Mac inference and asked to complete Phase A. Seven agents ran
in the main checkout with disjoint file ownership (worktrees lack the uncommitted
work): D1 baseline inference, F1/F2 gold sets, D3 training pipeline, C1 public-data
factory, G1 GPU controls, A2 tool-layer gaps, then B2 harness repair. Gold sets
(Toffee, GSI, BlueStone) are git-ignored and unadjudicated. First real inference:
qwen3.5:9b, qwen3:14b, qwen3.5:4b on the fictional North Quay case scored 0/310;
after B2's repair protocol and block ledger, 35–44/310, one of seven blocks done.
One free tiny-model download (Qwen2.5-0.5B-4bit, 290 MB, hash recorded) was used
for the MLX LoRA dry run. No cloud action, spend, commit or push. Coordinator fixed
the workbook rollback defect (deepcopy → serialised snapshot) with a regression test.
Full suite: 3,734 passed, 19 skipped, 0 failed. See `G_READY.md`: gate NOT MET.
