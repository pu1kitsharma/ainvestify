# Discovery and preparation repair — 14 September 2026

## Failures reproduced

- The discovery API held `MODEL_JOB_SLOT` for a complete search. Company jobs
  waited up to twelve minutes before failing, even while discovery fetched pages.
- The US AI/robotics planner produced diligence questions about “the company”
  instead of discovery queries. YC rendered only one card for the US route.
- The form defaulted to India. Structured portfolio adapters covered YC, Blume
  and Villgro, with no comparable global adapters.
- Qwen3:14b with a 16,384-token context allocated about 12.3 GB on this 16 GB
  machine. The default model configuration left inadequate memory headroom.
- The reviewer could approve an entire draft after inspecting selected fields.
- Revision prompts did not include the rejected draft. Schema-invalid drafts
  were particularly prone to being regenerated from scratch.
- Empty UI financial templates, including missing ARR, were passed as company
  context. Paasa's failed draft requested generic ARR instead of source records.

## Changed behavior

Inference calls use a FIFO queue; network retrieval and whole workflows do not
hold it. Preparation and discovery can interleave. The workspace displays the
current inference task and waiting state. A smaller memory profile uses Phi4-mini
and Qwen3:8b with a 12,288-token context and 4,096-token reasoning budget; retries
can increase that budget. The larger profile enables 14B escalation. Explicit
configuration remains available. These are resource preferences, not accuracy
scores. Small preliminary sourcing classifications use the fast route; substantive
preparation and review still use reasoning.

Discovery defaults to worldwide and recognizes common country aliases. New
visible-card adapters read [Antler](https://www.antler.co/portfolio),
[SOSV](https://sosv.com/portfolio/) and
[Seedcamp](https://seedcamp.com/our-companies/). Live fetches exposed 50, 10 and 326
cards respectively. These are rendered-page counts, not total portfolio coverage.
Seedcamp cards do not establish geography; absent location remains unknown.
Existing YC/Blume/Villgro sources remain supplementary. Generated discovery
queries are checked for question drift and supplemented with searches for
industry associations and university spinouts. These searches can find publishers
outside the configured adapters. Search-provider availability still limits recall.

Review v4 requires checks for every prose field. A field failure cannot be
overridden by an overall pass. Overall criterion anchors have deterministic
defaults, avoiding rejection solely for omitted reviewer anchor metadata.
Investment case v8 and company brief v9 invalidate older incomplete reviews.

Investment documents additionally reject unqualified benefit assertions such as
“ensures inventory accuracy,” and reject inferring no revenue from absent records.
This is a conservative check for observed language patterns, not a complete
semantic proof system. Numeric citation and dimension checks remain in place.
The recorded previously accepted Waybill draft now fails the outcome guard before
the reviewer can approve it. An earlier exhaustive-review model replay failed its
anchor contract; that failure is retained in `exhaustive-review-regression.json`.
The subsequent anchor-default change is covered by code tests, not a claimed
investor-quality benchmark.

Retries receive the actual rejected final answer and field-specific feedback.
Invalid drafts are not company evidence. Empty financial templates are excluded
from model context. Valid stages survive same-evidence retries; independent
documents continue after another document fails. Errors remain attached to the
unfinished document, and the UI distinguishes partial work from completed work.

## Verification

189 relevant Python tests passed after these changes. Frontend build, lint and
the investment/operations browser regressions passed. Tests include FIFO fairness,
failed-call release, 16 GB defaults, real public-card layouts, country aliases,
discovery query drift, exhaustive review coverage, the recorded unsupported-benefit
failure, and resuming partial preparation with the rejected draft supplied.

The diagnostic US run read all three new publishers and saved an Antler candidate.
Its screening also had model validation failures; it is not a successful market
coverage benchmark. It was stopped during the final worker reload, retaining its
history and saved candidate. Paasa preparation was resumed from its saved
suitability decision. Generated investment materials require inspection of the
actual final job outcome; passing these tests does not certify investor quality.

The later live Qwen3:8b Paasa run still failed all three document contracts. Its individual errors and successful suitability decision were preserved; no rejected draft was published as completed work. A newer free Qwen3.5 4B checkpoint is being evaluated separately, without changing the runtime default.

The memo and funding narrative now exclude measurement plans; those belong to the commercial test. Unused numeric annotations are removed, and explicitly cited numeric sentences can be bound to their exact supplied source in code. Uncited numbers and wrong-metric source substitutions still fail. Additional regression tests cover this behavior.

The Qwen3.5 4B reasoning probe was rejected for company-role confusion and an unsound measurement plan; its slow second attempt was stopped. Direct structured generation took 33.26 seconds and its review 32.23 seconds, but both contained substantive errors, including treating founding date as evidence that operating metrics exist. Neither mode was promoted. The reports are `qwen35-real-evidence.json`, `qwen35-direct-memo.json` and `qwen35-direct-review.json`.

A final US robotics diagnostic exposed software automation and biotech candidates being incorrectly admitted. A physical-robotics evidence gate now uses the original request, independently of broadened LLM synonyms. That diagnostic was cancelled, retaining history. Bing RSS was also tested as a possible additional free provider; it returned general robotics definitions instead of matching companies, so it was not added. These observations do not establish adequate worldwide market recall.

Final validation: 189 relevant tests pass, frontend build/lint and browser checks pass. All application jobs were idle before the final API reload; no manual restart remains pending. Paasa’s last completed live run remains a failed preparation pack, with a saved suitability decision and document-specific errors. This work fixes infrastructure, coverage breadth, validation and recovery defects; it does not establish reliable investor-quality model reasoning.
