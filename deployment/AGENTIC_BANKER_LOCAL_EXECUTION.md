# Local agentic banker implementation — 15 October 2026

User request: start the supplied external plan, keep execution local, use multiple
agents and VS Code with Claude Code. This is a development checkpoint. It does
not establish financial-model capability, training or investor acceptance.

The reference plan remains at the user-supplied local path; confidential deal
findings and expected private numbers are deliberately absent from this file.

## Architecture and implementation

Installed local agents must choose model structure, assumptions, numbers, every
formula and substantive prose. Deterministic tools expose file observations,
spreadsheet operations, calculation, rendering and validation. They do not
invent an investment conclusion or repair failed prose. Forward-looking cells
and slides require `company_projection`, scenario and vintage metadata before
any production integration; this metadata gate is not implemented in this slice.

| Workstream | Implemented locally | Still open |
| --- | --- | --- |
| A tools | `tools/v1`; explicit schemas and pre-effect validation; sandbox-bound XLSX authoring, read/trace and bounded arithmetic; read-only PDF/PPTX/XLSX observations with hashes; literal native chart/PPTX and DOCX draft tools; atomic draft pack directories with manifests and replay | General formula engine; qualified LibreOffice final recalculation; rendered previews, text fit, numerical chart binding validation and matching PDFs |
| B runtime | Injected and concrete loopback HTTP transport; eight role prompts/allowlists; bounded six-call/120-second passes; checkpoints, parsed-response JSONL, exact HTTP body receipts and task ledger; truncated/wrong-model response rejection | Full multi-role orchestration, durable room hook, hard process cancellation and real-model qualification |
| C/F evaluation | E1–E7 supplied-observation score contracts; public split/leakage checks; offline scorer CLI; explicitly mocked expert-iteration dry run | Artifact-derived independent scoring, rights-cleared filings, adjudicated gold, real sampling, MLX/QLoRA training and held-out evaluation |
| H coordination | Three isolated worktrees; VS Code workspace; loopback-only Claude reviewer launcher and preflight | Actual Claude task requires permission to start Mac inference, as the supplied plan requires |

`PackTools` optionally checks references against exact local workbook bytes and
nonempty cells. It does not verify that prose or supplied chart/table values
agree with those cells. Exports and diagnostic calculations remain blocked for
release. Source originals are never recalculated or rewritten. Failed staging
directories remain evidence. A post-publication audit-log failure returns an
error but can leave an immutable draft directory; filesystem publication is not
rolled back or promoted to acceptance.

Training source registry entries are disabled pending rights review. No public
filings or private references were collected or used in training. The existing
private reference cases remain held-out acceptance inputs; resolving conflicting
training clauses in the external plan is unnecessary for this synthetic slice.

## Local VS Code workflow

Open `local-agent-team.code-workspace`. Coordinator and WS-A/B/C folders are
separate local Git worktrees based on the existing development branch. No
commits or pushes are part of this work.

Run the task `Claude Code: local preflight (no inference)` to inspect the existing
Ollama inventory. The explicit reviewer task invokes Claude Code against an
installed loopback model with no tools, MCP servers, project context, cloud
credentials or inherited proxy settings. It uses a temporary home/config and
macOS network confinement. It supplies a generic software-review prompt only.
This is a deliberately narrow collaborator, not a hosted Claude agent with
access to the deal room. The interactive extension's default route is not used.

The launcher is not qualified until an actual bounded local invocation and
network-boundary test succeed. Preflight alone does not prove model execution.

## Next gates

1. Tool registration/schema mapping and a synthetic workbook + two-slide session
   are now exercised end-to-end, including failures, immutable output manifests
   and replay. See `evals/agentic_banker/CHECKPOINT_2.md`. This scripted tool gate
   does not establish a real-model baseline or complete agent orchestration.
2. Add a supported formula engine and isolated final LibreOffice recalculation;
   validate exported bytes, hidden cells, dependencies and chart source bindings.
3. Wire the real role team behind the existing private review/job contracts only
   after local runtime and cancellation gates pass.
4. Approve training-source rights and adjudicate split-isolated public gold.
   Implement artifact-derived scoring before treating rewards as training truth.
5. Implement actual small-model sampling/training only with download/inference
   authorization and measured memory. Mock dry runs prove plumbing only.
6. G-READY remains blocked until real local training, complete regression checks,
   corpus findings, reviewed GPU scripts and zero-spend kill-switch checks pass.
   Deployment and GPU spend remain deferred.

Existing human approval, financial/compliance review and six-file release checks
remain mandatory. Software test passes do not waive them.

The default test run skips explicitly marked live model/network/server checks.
Use `--run-live` only with separately authorized local test services and inputs.
The native isolation test independently probes Seatbelt application and reports
only its exact enclosing-sandbox capability denial as mandatory UNRUN. Neither
skip category may be counted as a passed release check.
