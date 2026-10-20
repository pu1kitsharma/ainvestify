# G-READY gate — status at 20 October 2026

G-READY is the gate that must pass before any GPU is provisioned or any GPU spend
occurs (plan: "Phase A: no GPU spend until code and weight-training pipeline are
built and proven locally"). **Status: NOT MET.** Four of seven criteria are open.
Nothing here is a quality claim about any model; all scores are plumbing or
floor measurements. Evidence for each line is cited; absence of evidence is stated.

| # | Criterion | Status | Evidence / gap |
| --- | --- | --- | --- |
| 1 | Full training loop proven end to end locally on a tiny model | **PASS (plumbing only)** | `evals/agentic_banker/d3-training/README.md`: Qwen2.5-0.5B-4bit, sample→score→filter→LoRA→held-out→adapter→memorisation probe, 62 s, 559 MB peak. One seed on copyable tasks; first attempt collapsed (kept). CUDA QLoRA path unit-tested only, never run. |
| 2 | Full test suite green, no new failures | **PASS** | `pytest tests -q -p no:cacheprovider`: 3,734 passed, 19 skipped, 0 failed (210 s), 20 Oct. Skips are opt-in live/native/Office checks, **unrun, not passed**. |
| 3 | Gold set + scorer reproduce every corpus finding from hand-written answers | **OPEN** | Gold built and git-ignored: Toffee 35 findings/14 traps, GSI 27/12, BlueStone 16/15 (no human adjudication). Scorer `scripts/evaluate_agentic_banker.py` exists. **Not done:** adapter from gold `expected_findings.json` to the scorer's key format, and a run proving a hand-written perfect answer scores 100% and a trap-flagging answer is penalised. |
| 4 | GPU bring-up scripts reviewed | **OPEN** | `deploy/gcp/` written, only `bash -n` checked. gcloud flags, image family, SKU and zone names, vLLM version/flags unverified against current docs. |
| 5 | Kill switch tested on a ~zero test budget | **OPEN** | Function logic tested locally with synthetic Pub/Sub messages only. Needs a real GCP project and a near-zero test budget. |
| 6 | Written GPU run plan approved | **OPEN** | `deployment/GPU_RUN_PLAN_TEMPLATE.md` exists; no plan filled in. Rates in `deploy/gcp/gpu_rates.json` are unverified estimates (`verify_before_use: true`; the ledger refuses real reservations until a human verifies them). |
| 7 | Dry run uses no private data in Git; storage rules enforced | **PASS** | Gold/private/runtime paths git-ignored (`git check-ignore`); private-trained adapters restricted to ignored paths in code and tests; live job counts unchanged (22 awaiting-input, 3 blocked, 4 cancelled, 2 queued, 0 leases). |

## Measured capability floor (not a gate, but decides Phase B)

Local `qwen3.5:9b` on this 16 GB Mac (North Quay, fictional, 310 key figures):

| Harness | Result |
| --- | --- |
| D1, original (6 runs) | 0/310; no run completed the first modelling pass |
| B2, repair protocol + 7 blocks (2 runs) | 35 and 44/310; 1 of 7 blocks completed; writer pass never started |

Binding limit is time (11–21 tok/s, swap pressure), plus real model errors on
forecast construction (constant growth instead of driver references, ragged
rows). A faster machine or a trained model could change this; not shown.
The bake-off on a real GPU is the first fair test.

## Other open items that block Phase B quality

- Public training data: **0 real, rights-approved companies** (gate needs ≥20
  companies, ≥50 evidence families, ≥3 sectors). Needs `RESEARCH_AGENT_CONTACT`,
  enabling `sec_edgar_companyfacts`, and a human terms review of SEC use.
- The vLLM/OpenAI-compatible client for the `selfhosted:` route is not wired into
  the model client; held-out/probe generator for the GPU path is MLX-only.
- GGUF/Ollama serving of trained adapters is unverified.
- E3 scenario modelling and E6 section writing have no automatic key (score 0).
- Defect fixed 20 Oct: workbook rollback used `deepcopy`, which fails once a cell
  comment exists and poisoned later blocks; now snapshots by serialisation
  (regression test added). Host-side reload workaround in `banker_session` can be removed.

## Human actions that unblock progress

1. Set `RESEARCH_AGENT_CONTACT='Org contact@email'`; review SEC terms; enable source.
2. Upgrade GCP billing, create the dedicated project, file the quota requests in
   `deployment/GPU_QUOTA_REQUEST.md`; verify rates; fill and approve a run plan.
3. Decide how gold is adjudicated (a human banker pass on the three gold sets).
