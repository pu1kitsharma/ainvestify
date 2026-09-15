# Company preparation acceptance

Latest: [source cleanup and three unseen checks](v9-unseen-source-cleanup/README.md). All first runs finished under 69 seconds, but Resend failed the content audit. Original failures, corrective checks and development retests are retained; confidence remains limited to assisted initial preparation.

Latest result: [v9 shared initial preparation](v9-service-binding/README.md) completed all nine sections in 41.6–51.4 seconds across three development checks, including the actual Paasa API, with three local calls per company and no retries. The source-bound contribution/activation scope and limits are explicit. [The full fix/failure record](v9-workflow-fix.md) preserves every prior failed output; older sections below are historical and do not describe the current default. Full MVP/practitioner acceptance remains unproven.

Keep one reusable full-workflow evaluator, one cross-sector source set, one audit rubric, and one honest baseline. Repeated diagnostic snapshots and standalone reviewer probes were removed during MVP cleanup.

- `live-workflow-cases.json`: public evidence for Paasa (India/fintech), Notpla (UK/materials) and SunCulture (Kenya/solar irrigation). These are evaluation inputs, never production company answers.
- `paasa-v6-live.json`: the retained protocol-v6 baseline, including actual outputs and failed attempts.
- `paasa-v6-audit.json`: that run failed acceptance: economics validation failure, generic founder proposal, overlapping diligence requests and unreliable review.
- `audit-rubric.md`: content acceptance criteria; completion and valid JSON alone are insufficient.
- `acceptance-latest.json`: the latest protocol-v7 application run, including the job, actual sections and failed attempts. A completed job is not an independent content-quality pass.

Use `scripts/evaluate_analyst_workflows.py` for deliberate whole-workflow evaluation. No model has qualified for promotion, and no weights have been trained. No benchmark runs are started by the cleanup or interface design work.

The MVP scope and build order are maintained in `deal_automation_architecture.md`, section 16.29.

Latest application acceptance (2026-09-14 UTC): Qwen3.5:9b with bounded reasoning for complex sections and review completed 7/9 sections in 1,840.4 seconds (21 calls; four correction calls). Request B failed selected-source figure validation and readiness B remained blocked. The development content audit found only 2/9 sections usable with minor edits: a self-review pass did not establish usable financial reasoning. The first-company milestone and model-promotion gate remain failed. `acceptance-latest.json` preserves the original generated text and reviewer verdicts alongside the separate audit; these outputs were not hand-rewritten to pass. Its cumulative attempt metrics include earlier retries, while `current_run_*` metrics describe this final consistent-profile run only.

## Bounded reference comparison

`paasa-reference.md` is a separately authored reference, not an application output or production template. `paasa-reference-input.json` contains compact paraphrases checked against published sources; it is deliberately curated to test preparation with less retrieval noise. Claims remain source-reported, not independently verified performance. Extracted quotations in this evaluation refer to the paraphrased input packet, not verbatim website text. The reference answer is hashed for the report but never passed to the model.

The single profile uses Qwen3.5:9b for writing and fast review, with the existing task-specific reasoning for complex writing. Fast self-review is not the acceptance judge. This configuration differs from the preceding reasoning-review baseline, so this is a capability comparison against a content reference, not a controlled attribution of changes to one variable. No production code or model defaults change.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_analyst_workflows.py \
  --cases evals/investment_preparation/section-workflows/paasa-reference-input.json \
  --output evals/investment_preparation/section-workflows \
  --model qwen3.5:9b --review-model qwen3.5:9b --no-review-thinking \
  --context 8192 --tokens 1800 --max-corrections 1 --max-calls 24 --max-seconds 1200 \
  --reference evals/investment_preparation/section-workflows/paasa-reference.md
```

Limits apply in the evaluation adapter only: one correction per writing/extraction/planning stage, 24 actual inference calls, and 20 minutes total. Reviews and validation remain the production implementation. Denied correction attempts are recorded separately from actual inference. A deadline or call limit stops the test and preserves partial work. Only a fully usable result advances to other companies; a failed result does not automatically start another run. Model digest: `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`; Ollama `0.33.3`. Sampling is not deterministic; the report records actual outputs, input hash and configuration rather than promising byte-identical reruns.

Result: **failed**, stopped after a material financial error passed automatic review. Five generated sections were inspected; subsequent sections were not completed. One external audit-directed field correction removed the direct fee/AUM comparison but failed the unchanged output validator and did not make the full request usable. Total elapsed time including correction was 472.34 seconds, with 16 model tasks. The report retains this correction separately from the original pipeline result. See `paasa-comparison.md` for the content comparison and decision; `paasa_reference_test.json` contains the evidence record, original answers, review verdicts and correction. The external feedback is recorded for inspection, not automatically supplied by the reproduction command above. No additional company test or model promotion followed.
