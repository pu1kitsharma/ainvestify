# Research reliability and financial evidence checks

The user asked to address moderate confidence in research drafts and low confidence in autonomous investment handling. This work fixes demonstrated source-selection, service-event and financial-qualification failures. It does not establish autonomous investment accuracy or practitioner acceptance.

## Changes

- Research and founder openings now use concise, code-bound excerpts selected from supplied product records or the opening homepage context. Exact parent records remain available in source details and exports. Explicit adjacent qualifications are retained, and the reviewer compares the excerpt with its complete source. Economics still retains complete commercial contexts rather than clipped fee descriptions.
- Combined review now checks business relevance, commercial-source coverage and the founder opening. An exact but irrelevant pricing-footer quotation is no longer assumed useful. Shared sources/methods appear once in the review input instead of being repeated for every passage.
- Unsupported order events are excluded from the initial schema when supplied sources contain no ordering activity. The existing citation-specific guard still applies. A new generic plan-heading/description check prevents managed/advisory activation from borrowing order-execution support from a neighboring trading plan.
- Contribution calculations are deferred when source wording says delivery costs were already deducted, or supplied variable costs include overhead/financing/tax costs. Cash coverage is deferred for explicitly included restricted/customer funds. These necessary wording checks do not verify arbitrary accounting definitions.
- Full financial source quotes and deferred-calculation reasons now survive into the model evidence. Complete recent financial facts receive a bounded allocation within the same 14,000-character evidence limit; omitted records are declared. The app and metrics export expose calculation blockers rather than emitting an invalid result.

## Verification

| Check | Result | Meaning |
| --- | --- | --- |
| Focused backend tests | 200 passed | Includes retained failures, synthetic counterexamples, evidence preservation, arithmetic and pipeline checks |
| Frontend build/lint | Passed | Final implementation |
| Isolated browser regression | Passed | Concise excerpt, retained full context, existing stop/resume and stale-screen recovery |
| [Resend development retest](resend/resend_research.audit.json) | 70.16 seconds, four calls | Corrected the pricing-footer opening; initial unsupported order choice required one repair |
| [First live Paasa check](live-paasa.audit.json) | **Content acceptance failed**, 58.451 seconds, three calls | Model reviewer passed an unsuitable order-based activation measure for managed advice; original output retained |
| [Final live Paasa check](final/live-paasa.audit.json) | 60.55 seconds, four calls, nine sections | New guard rejected that event and a targeted correction selected enrollment |
| [Final live browser](final/browser-check.json) | Passed; saved GET 57.517 ms | All stages, concise source excerpt, complete context, enrollment request, no failure banner, mobile width; zero new inference |

Eleven actual local model calls across three bounded runs. No model sweep, download, paid service, fresh source fetch, outreach or financial execution. Each generation run remained under the existing two-minute limit. The Resend report predates the final financial-context budget, event-schema exclusion and managed-plan changes; its original output is preserved and its exact limits are recorded in its separate audit. The final Paasa run exercises the final implementation. These are development checks, not unseen evaluation or a measured accuracy percentage.

Source evidence remains unchanged and the original nine-section content remains in live history. Current live workspace revision: **1239**; job: **automation_cb42d54b1df3**. Stable API: PID **527**, `scripts/serve_local.py`, no reload. Recheck runtime identifiers before using them.

## Remaining evidence gaps

Company records must establish the eligible registration population, enrollment event, accounting definitions and actual results. The economics section remains verbose; complete market/competition research, valuation, portfolio decisions and execution are outside this demonstrated initial pack. A model review pass still cannot establish investment quality, as the retained Paasa failure demonstrates. Verified records, broader frozen evaluation and independent investment-practitioner review remain necessary.

Exact implementation hashes and checks: [verification.json](verification.json). Preserve this entire directory: `tests/test_research_evidence.py` directly reads the failed `live-paasa.json`.
