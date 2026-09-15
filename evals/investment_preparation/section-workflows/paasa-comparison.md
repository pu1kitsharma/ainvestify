# Paasa reference comparison — failed

15 September 2026 (India). The [reference pack](paasa-reference.md) contains the proposed research memo, founder approach and two diligence/readiness work packages. It is a separately authored evaluation reference; it was not inserted into the application or supplied to the tested model.

## What was tested

The unchanged production preparation pipeline received a compact packet of source-checked paraphrases. Qwen3.5:9b wrote the sections, using the existing bounded reasoning for complex work and fast automatic review. A separate development audit compared actual content against the reference. This is not practitioner certification or a model-training run.

The run was stopped after a material financial error passed review and propagated into the next action. One targeted correction was then attempted through the existing model adapter and checked with the production schema, citation normalizer and validator. It received the precise objection, not the reference answer. Original outputs remain intact in [the recorded result](paasa_reference_test.json).

Total evaluation elapsed time: **472.34 seconds (7.9 minutes)**, including the stop and correction. There were 16 model tasks: 15 in the pipeline, including the interrupted task, and one targeted correction. Five sections had completed generation before the stop; four later sections were not assessed. The 20-minute and 24-call limits were not exhausted. No live company records, default model or production prompts changed.

## Where the result diverged

| Requirement | Observed output | Judgment |
| --- | --- | --- |
| Preserve applicable plan and fee qualifications | Extraction dropped the Apex plan name from its fee statement and omitted its no-brokerage-markup qualification. Economics then blurred the two plans. | Evidence handling failed before reasoning. |
| Distinguish a published charging mechanism from actual revenue composition | The investment argument called AUM charges the primary revenue source without a revenue breakdown. | Unsupported inference; model review passed it. |
| Request records supporting a financially meaningful decision | The diligence request proposed a negative recommendation when collected fees were substantially below customer AUM. | Wrong comparator: service fees are expected to be smaller than the assets used to price them. |
| Specify executable analysis | The readiness action compared currency fee amounts with percentage tariffs and pass-through charges with volume without a defined calculation. | The proposed analytical method was not valid as written. |
| Correct the observed defect once | The correction removed the direct fee/AUM comparison, but left an unspecified expected-fee baseline. It also added internal source identifiers to the prose. | Partial reasoning improvement; unchanged production validation rejected the response. The full section remained unusable. |

The original request also asked a billing ledger to supply expense allocations and an already calculated cost-to-income ratio. The reference instead identifies the separate billing, settlement and cost records and makes the calculation the proposed work. These differences affect whether an adviser could actually execute the request.

## Decision

**Do not advance this configuration to more companies or declare an autonomous MVP.** A self-review pass did not establish a usable analytical method. No further model sweep or automatic retry was started.

This result identifies both pipeline and model defects; it does not establish that all free/local models are incapable. The input was curated, not automatically discovered. Fast review differed from the earlier reasoning-review run. Consequently, this is a bounded capability failure, not a clean causal estimate of the benefit of one configuration change.

The next engineering decision should address two concrete interfaces before another full-pack test:

1. Preserve complete source statements and their qualifications through selection. A summarizer should not replace a source statement with an unbound pronoun or discard the applicable plan. Missing evidence should trigger retrieval or an explicit gap, not a claim that the company has not disclosed it.
2. Represent proposed financial analysis as a calculation plan with typed quantities, records, periods and currency/percentage/asset units. Code must reject invalid comparisons before prose is published. The AI can select and explain the analysis; another prose reviewer alone did not provide this protection.

A stronger-model comparison may be useful after these interfaces are controlled, but switching models is not proven to solve the problem. No paid inference was used or authorized by this test. The reference pack is useful for reviewing the intended output; it is not evidence that the application can yet produce it autonomously.
