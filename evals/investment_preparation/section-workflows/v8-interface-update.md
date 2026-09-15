# Preparation v8 — interface fixes and bounded results

15 September 2026. **Implemented, but not MVP-ready.** The source and calculation interfaces have deterministic regression coverage. A complete, usable company pack within two minutes has not been demonstrated. Neither a schema pass nor a model review is a confidence percentage.

## Changes

- Source selection now returns stable passage IDs and classification hints. Code retains the entire bounded source record, including the plan name, subject and qualifications. The legacy quoted-span binder also restores enclosing source context. Classification remains a fallible model annotation, not verified company information.
- Source acquisition retains adjacent blocks and both opening and closing page contexts within the eight-record-per-URL limit. Collector cache version is 2. Records larger than the selection limit are omitted explicitly rather than silently truncated. This is bounded collection, not a guarantee that every necessary qualification on the web was retrieved.
- Unchanged source selections are cached by content-bound IDs and the selection contract. Unchanged sections are reused only after their input and review hashes match. Changed evidence is archived; historical sections are kept out of the current view while their new inputs are checked. Duplicate contexts are supplied once per section.
- The existing `measurement_plan.py` now supplies the active v8 request contract. Quantities declare economic role, entity, service, population, window, exposure, stock/flow basis, units and revenue presentation. Plans declare operation, output meaning, population relation, partner-charge treatment and intended decision use. Supported quantitative purposes are contribution, fee yield, cash reconciliation, cohort rates/comparisons, operating comparisons, unit costs and contribution margin. Qualitative record review is separately represented.
- Code rejects the tested fees-versus-assets adverse comparator, money-versus-rate comparison, incompatible entities/plans/periods/currencies, repeated cost deduction, revenue/volume substituted for contribution inputs, and unequal exposure windows. A fee-yield ratio is allowed with matched periods, an average balance and an agreement record; it cannot by itself justify an adverse profitability conclusion.
- Requests contain the AI-proposed plan. Record requests, decisions and paired readiness actions are rendered from that same reviewed plan. Missing records leave the decision unresolved. Readiness actions no longer require separate writer/reviewer calls that can substitute another calculation. This does not validate the truth of model-assigned labels or execute any financial analysis.
- New preparation defaults to the user's **120-second limit**, with 24 logical tasks and 32 HTTP requests including thinking continuations. Queue waiting shares the deadline; in-flight local HTTP requests are cancelled on expiry. API source collection shares the remaining budget through its existing bounded transport. Source DNS/transport and persistence overhead are not a hard real-time SLA. No automatic restart is scheduled. A validated candidate is saved before its review so an explicit resume can reuse it.
- Initial agenda selection no longer forces extended thinking when the profile's explicit `thinking` setting is false. Explicit thinking, substantive analytical sections and repairs retain their supported reasoning path. This is a routing change, not a promoted model profile.

The older generic `MeasurementPlan` remains available to legacy callers. Unsupported financial methods, FX conversion, contractual fee accrual and arbitrary multi-step financial models have not become executable through this change. Input records still require reconciliation. Source labels, questions and prose can still be wrong.

## Verification

The final focused suite passed **301 tests** across the preparation, evidence, routing, budget, metrics, operating workflow and supporting discovery modules. New tests include the exact retained Apex fragment, rejection of the original failed request/action, typed economic counterexamples, candidate preservation on budget expiry, async cancellation and queue release, cached zero-call resume, and selective invalidation after evidence changes. These tests use isolated stores and fixtures; they do not certify investment judgment.

Frontend build and lint passed. The isolated browser journey passed three-step navigation, stop/resume, partial/stale states, source links, linked request/actions, exports and mobile layout. It mocks APIs and invokes no model. The idle local API was restarted using `scripts/serve_local.py`, without auto reload. The live database and original evaluation outputs were preserved.

### Complete-workflow attempt: failed the completion gate

Raw result: [v8-120s-paasa.json](v8-120s-paasa.json). This used the same frozen, curated source-checked paraphrases and installed Qwen3.5:9b profile, with a fast reviewer. The reference answer was only hashed, never passed to the model. The run started with no loaded model and used a temporary SQLite store.

| Measure | Observed |
| --- | --- |
| Elapsed pipeline time | 119.77 seconds |
| Logical model tasks | 8 |
| HTTP inference requests | 9, including continuation |
| Reviewed sections saved | 2 of 9: business and economics |
| Complete documents | 0 |
| Stop | Production time limit cancelled the next analytical call |
| Live data writes | None |

The selected record retained Access and Apex separately, the Apex plan subject, separate brokerage, and the no-markup qualification. The two saved paragraphs are materially better on those distinctions than the retained earlier failure. Business claims remain attributed. Economics distinguishes the plans and says retained income is unknown. The economics paragraph could state the remaining entity/cost questions more fully; attached evidence retains the detailed qualifications.

The run **did not reach the new typed diligence request**, so it does not demonstrate that this model can consistently populate the semantic plan contract. The investment decision, founder offer and readiness package were not completed or accepted. Do not count the independent reference as filling those gaps.

### Targeted planning timing probe: faster, not content acceptance

The full run spent 59.12 seconds and 1,152 generated tokens on the initial agenda. After that observation, automatic initial-agenda thinking was removed and duplicate evidence contexts were omitted. One additional task was tested under a **20-second, one-call, one-request limit**, reusing the complete code-bound evidence from the prior run.

Raw result: [v8-agenda-probe.json](v8-agenda-probe.json). It completed in **11.517 seconds**, with 182 generated tokens and no thinking. It passed the implemented agenda schema and citation checks. The unit-economics question still ambiguously describes a percentage of assets retained from fees; this is not proof of correct financial reasoning or of an acceptable downstream calculation plan. The questions are not production-approved deliverables.

This was a warm-model, single-task observation with changed input deduplication and nondeterministic sampling. It is not a controlled quality A/B test or a new complete-workflow pass. The final code includes this routing change; the earlier 120-second full run predates it. No further model runs or profile promotion followed.

### Cached path

[v8-cache-timing.json](v8-cache-timing.json) records three offline fixture resumes: **20.45, 21.32 and 20.13 ms**, all with zero model tasks. The median was 20.45 ms. The fixture's fresh workflow uses 16 model tasks rather than the prior 20 because its two actions are derived from reviewed plans. These timings exclude real model inference, network collection, process startup and a large production database. They establish the cheap cache path, not instant fresh generation.

## Remaining decision

The current local configuration has not met the complete-pack quality or latency target. The next substantive acceptance test must assess a model-authored typed request and the derived action, especially correct economic labels, record sufficiency and the match between the agenda question and calculation purpose. Do not restart the full sweep, train on these outputs, or claim universal financial correctness from the whitelisted methods. Stronger or paid inference remains a separate explicit access/cost decision.
