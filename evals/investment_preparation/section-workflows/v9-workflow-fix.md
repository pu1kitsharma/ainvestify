# Shared preparation v9 — implementation and measured results

The default API now uses one shared analysis, one AI-written founder proposal and one focused combined review. The final checks are recorded in [v9-service-binding](v9-service-binding/frozen-contract.md), including a real Paasa API job and fresh SunCulture/Notpla generation. The result table below separates model completion from content acceptance.

## What changed

- The model selects source passages, services, registered observable customer events, the customer method and risk focus. It writes the founder offer, explicit customer-record request and invitation. Code quotes the chosen opening source and assembles those AI-written sentences; no company-specific answer or authored reference is installed as production content.
- Complete source excerpts and explicit offering/pricing metadata survive selection. Descriptions quote the supplied records with attribution, including source qualifications. They do not turn source-reported promises into verified outcomes. Paasa's compact input is source-checked paraphrase material, not a verbatim website scrape.
- The initial pack fixes contribution and first-action activation as its two methods. Registered methods own the economic quantities, operations, entity confirmation, matched periods/populations, required underlying records, gross/net treatment and conditional decisions. Assets cannot become revenue and an event count cannot become a unique-customer denominator. Missing records stay unresolved. These are proposed analyses, not calculated company results. The default initial test asks whether customers complete a first action; it does not require repeat purchase of durable goods. Repeat-use/retention helpers remain available for explicit future work, outside this initial-pack contract.
- Financial conditions and risk wording are compiled from those methods. The model cannot reintroduce arbitrary financial arithmetic in these passages. Observable customer event choices exclude satisfaction, problem resolution, loyalty and guaranteed returns. The customer-record request has its own required AI-written field, preventing an accounting-only proposal from silently omitting the second work package. A reported product label is bound to its complete source by normalized whole-word matching, so its model number does not require an LLM citation repair. Derived founder questions carry their underlying request citations.
- Review uses different evidence for different assertions. Exact source equality protects the opening; an offer is compared with the actual intended work contract. This fixes the repeated category error that treated a request for a missing ledger as an unsupported assertion that the ledger had already been analyzed. No final draft is accepted while a material review objection remains.
- Default fresh work uses the installed Qwen3.5:9b, context 8192, fast generation with temperature0 and no presence penalty. A normal complete run uses 3 model calls. The shared path caps each run at 120 seconds, 6 logical calls and 10 HTTP requests, including queues/continuations. Repairs target failed fields. Explicit resume reuses saved candidates; unchanged complete work uses no model calls.
- API migration no longer restores the old long-thinking profile from v7/v8 work. Current shared-profile resumes retain explicit choices. The polling response excludes internal candidates and model attempts. Frontend protocol is9; the three existing product steps and linked exports remain.

An additional runtime bug was fixed for explicitly enabled Qwen3.5 reasoning: native nonthinking chat continuation discarded the tagged reasoning prefix. Raw text completion now retains it while keeping the answer under structured decoding. Cancellation and request limits apply to both transports. Private reasoning is never saved in reports. This correction follows the [installed Ollama renderer](https://github.com/ollama/ollama/blob/v0.33.3/model/renderers/qwen35.go) and [raw generate interface](https://docs.ollama.com/api/generate). Default v9 does not require a reasoning continuation.

## Results and limits

The [final same-implementation result](v9-service-binding/README.md) is:

| Company | Input | Seconds | Sections / calls / repairs |
| --- | --- | ---: | ---: |
| Paasa | Actual API with source collection | 51.449 | 9 / 3 / 0 |
| SunCulture | Stored collected public excerpts | 43.11 | 9 / 3 / 0 |
| Notpla | Stored collected public excerpts | 41.56 | 9 / 3 / 0 |

Cached API requests returned in **21.8–94.3 ms**, with zero additional model calls and the same completed job. The old v7 content is unchanged in history and the before snapshot. Validation: **350 focused tests**, frontend build/lint, isolated browser journey and actual live pages/mobile layout passed. The API is running the tested code without auto reload.

Separate JSON audits bind original report hashes and distinguish content inspection from model review. Passing development examples do not establish the ten-company/practitioner MVP gates, independently verified source claims, arbitrary financial analysis, automatic execution or fundraising outcomes. The workflow currently supplies an initial contribution/customer-activation preparation plan; further sector-specific diligence remains necessary.

## Preserved development failures

These original outputs were not rewritten or relabeled as successes. Each fresh run used an isolated Store and a 120-second maximum. They are interface debugging runs, not a claim of production reliability or a hidden model sweep.

| Original report | Seconds | Calls | Observation |
| --- | ---: | ---: | --- |
| [v9-shared-paasa](v9-shared-paasa/paasa_reference_test.json) | 39.23 | 2 | Founder field length stopped a valid-sized proposal. |
| [v9-validated-methods](v9-validated-methods/paasa_reference_test.json) | 65.55 | 3 | Verbose reviewer output failed its length contract and conflated proposals with results. |
| [v9-bounded-reasoning](v9-bounded-reasoning/paasa_reference_test.json) | 78.99 | 2 | Native chat continuation dropped the reasoning prefix; repeated attribution rejection. |
| [v9-retained-reasoning](v9-retained-reasoning/paasa_reference_test.json) | 119.76 | 4 | Incomplete under120 seconds; observation/record wording false failures. |
| [v9-linked-pack](v9-linked-pack/paasa_reference_test.json) | 119.76 | 2 | Thinking continuation omitted a required method field; repair expired. |
| [v9-raw-continuation](v9-raw-continuation/paasa_reference_test.json) | 119.76 | 3 | Writers finished but verbose review expired. |
| [v9-compact-review](v9-compact-review/paasa_reference_test.json) | 87.14 | 3 | Free prose reintroduced an invalid assets/cost comparison; founder record request failed. |
| [v9-source-method-selection](v9-source-method-selection/paasa_reference_test.json) | 107.36 | 5 | Reviewer codes lacked actionable explanations and generated false objections. |
| [v9-bound-review](v9-bound-review/paasa_reference_test.json) | 79.81 | 3 | Reviewer explanation exceeded its limit and conflated missing records with an invalid proposal. |
| [v9-focused-review](v9-focused-review/paasa_reference_test.json) | 70.75 | 5 | Undifferentiated review evidence again rejected attributed claims and requests. |
| [v9-typed-review-bases](v9-typed-review-bases/paasa_reference_test.json) | 33.89 | 3 | First complete useful Paasa pack:33.89 seconds,3 calls; separate audit retained. |

The [first cross-sector check](v9-cross-sector/frozen-contract.md) completed Notpla in 33.17 seconds/3 calls. SunCulture stopped at 78.11 seconds/4 calls because the founder omitted customer input records even after a targeted repair. It also needed a product label shortened to the old 60-character cap. The final interface makes the customer-record sentence required and allows 100-character service labels.

The [small reviewer probe](v9-review-capability/result.json) used one installed phi4-mini call, 6.263 seconds. It correctly rejected invented outcomes but wrongly rejected a proposed record request, so that reviewer was not adopted. The [production-review negative control](v9-negative-control.json), 24.081 seconds, rejected invented guaranteed returns and a claim that analysis/fundraising had already happened. It missed satisfaction being proposed as an event; registered event enums now reject that choice in code. These observations are retained because a reviewer pass alone is insufficient.


Later preserved checks closed further concrete failures:

- `v9-final`: Paasa completed in 55.98 seconds. SunCulture stopped on a derived-question citation bug (the product number was supported by the request's source but not the founder opening's citations). Notpla completed in 80.46 seconds, but the content audit found a false statement that Food Containers were entirely edible. That was **not an accepted output**, despite the automatic review pass. Its original text is a regression fixture.
- `v9-qualified-output`: exact source quotation fixed the Notpla opening and all three runs completed in 37.09–55.09 seconds. SunCulture still chose repeat delivery for a durable pump, an unsuitable initial test. This drove the explicit initial-activation contract, rather than declaring completion sufficient.
- `v9-initial-preparation`: Paasa and Notpla completed in 34.65/55.23 seconds. SunCulture stopped at 25.97 seconds because the model cited a delivery passage without the product number. Whole-word service/source binding now supplies the relevant complete product source without changing the service or accepting invented figures.

All original JSON reports, raw final model responses, frozen inputs and contracts remain. No failed report was overwritten to manufacture an acceptance pass.
