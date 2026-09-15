# Compact diligence capability result

**Failed: 0 of 2 plans accepted.** One local Qwen3.5:9b fast call completed in **45.657 seconds**, including cold inference startup, with **758 generated tokens**, 2,504 prompt tokens and one HTTP request. It stopped normally rather than exhausting the 60-second cap. This was a capability test on curated evidence, not a complete preparation workflow or live company update.

The user authorized the smaller typed-plan approach after the two-minute v8 full run produced only 2/9 sections. The conditional plan was to prove the financial reasoning first and integrate a smaller shared-analysis workflow only if it passed. That condition did not pass.

## Artifacts

- [Frozen contract](frozen-contract.md): written before inference, preserved afterward from `/private/tmp/compact-gate-note.md`.
- [Original report](paasa_reference_test.json): full input, instruction, schema, route, raw answer, error and budget. No content was repaired or replaced.
- [Separate audit](audit.json): coding-session content inspection, tied to the original report hash. This is not a model self-review or external practitioner assessment.

The runtime had no active preparation/search jobs and no loaded model before the call. Nothing was preloaded. No reference answer, public crawler, live Store, reviewer, correction, retry, download or paid service participated.

## What failed

The first plan selected `contribution_margin` while subtracting variable costs from recognized revenue. That produces a contribution amount, not a margin. It simultaneously declared gross revenue, already-deducted variable costs and already-deducted partner charges without consistent deduction metadata. The full canonical validator rejected it. Its requested records were also insufficient to reconcile recognized revenue, partner pass-throughs and advisory/support delivery costs, and the selected investment entity was unconfirmed.

The second plan compared transaction counts against customer counts while selecting a cohort-rate method. Both time bases were invalid. Even after those mechanical issues, transfer execution would not establish resolution of customer-reported remittance friction. The records lacked the eligibility, unique-customer linkage and follow-up needed for the proposed claim. The entity was again selected without confirmation.

The compact JSON shape was valid. Both original plans failed the existing economic validators independently; no request/action was accepted or published. Shape compliance and short output therefore did not establish useful reasoning.

## Code and limits

`CompactMeasurementPlan` declares common scope once, retains the model's operand roles, units, time bases and records, then expands into the existing `DecisionMeasurementPlan`. Code supplies only method constants and shared definitions. It does not fix incorrect economic labels or infer new company facts. `expand_compact_requests` also runs the existing citation, distinct-dimension and section checks. The compact contract currently supports the existing narrow quantitative methods with a shared window; it does not replace qualitative reviews or arbitrary multi-step finance.

The existing evaluator now exposes `--compact-diligence-only`: one explicit local model, one frozen case, at most 60 seconds, one task/request, no retries, no profile promotion. Its output directory must be new, preserving previous observations. Regression tests exercise valid expansion, citations and unsupported figures, bounded execution, the original rejected model plans and all supported method families.

The production orchestration remains v8. The proposed fewer-call workflow was not integrated. No stronger-model evaluation or further-company run followed. A materially different inference approach needs its own bounded capability test and any required access/cost/privacy decision; this result neither guarantees another model's success nor proves all local models incapable. The two-minute complete-pack target and MVP acceptance remain unmet.

Verification: 139 focused regression tests passed. After adding CLI preflight checks, the 34 compact/evaluation tests passed again, including rejection before inference when a reference is missing or the output directory already exists. `git diff --check`, original-report hash verification and new documentation links passed. The stable API returned HTTP 200; live Paasa remained version 7, revision 1092, with no active preparation/search jobs. No service restart was needed for the isolated capability work.

Reproduction command (do not rerun automatically; use a new output directory):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_analyst_workflows.py \
  --cases evals/investment_preparation/section-workflows/paasa-reference-input.json \
  --output /private/tmp/new-compact-capability-result \
  --model qwen3.5:9b --compact-diligence-only \
  --context 8192 --tokens 2000 --max-seconds 60 \
  --reference evals/investment_preparation/section-workflows/paasa-reference.md
```
