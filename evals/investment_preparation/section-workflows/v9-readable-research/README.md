# Waybill recovery and readable research — 15 September 2026

The user reported a live Waybill failure (`business: Cite the selected excerpt parent fact_id`) and an unreadable Paasa economics card containing complete pricing pages. Both are product defects. Completion and a model review pass alone do not establish usable research.

## Changes

- The business-selection inference schema requests only an excerpt ID. Code resolves its parent citation, research text and founder-opening citation. The original Waybill answer selected a valid S1 excerpt but supplied S6/S7 as redundant parent IDs; that unchanged answer now passes this interface offline.
- The shared analysis writes a concise economics explanation within the existing call. Code adds its source-attribution label; the main card shows the explanation and unresolved economics. Complete prices, qualifications, citations and source URLs remain in expandable details and the export appendix. Legacy quoted economics no longer dumps a full price page into the main card.
- Source checks reject the demonstrated conversion of supplier-settlement money into a consolidated company fee and loss of an explicitly annual-fee/monthly-collection distinction. These are narrow guards, not a general accounting or semantic proof.
- Economic repairs receive complete relevant sources and correction requirements without the rejected prose. Two real attempts had copied the rejected assertion verbatim. Independent service/event and economics defects are now gathered into one targeted correction call. Successful fields are retained. The 120-second, six-logical-call budget remains unchanged.

## Preserved failures

- `waybill-before.json` and `paasa-before.json`: original live workspaces and leads. The former is a direct regression fixture for the parent-citation error.
- `live-waybill.json` and `waybill-first-attempt.json`: first correction run, 51.0 seconds observed / two local calls; blocked because the writer omitted a redundant attribution label, and inspection also found a payment-as-fee error. Attribution is now code-owned. The second file retains the full raw workspace and is a regression fixture.
- `waybill-final.json`: despite its historical filename, this is a **failed** intermediate run, 47.04 seconds observed / two calls. The supplier-payment guard rejected the invented consolidated company fee; the old repair copied it unchanged.
- `final/paasa.json`: **failed content acceptance**, despite nine completed sections and model review passing. It took 84.31 seconds observed / four calls. The text described an annual deduction and omitted monthly collection. This unchanged result is a direct billing-period regression fixture.
- `implementation.json`: implementation snapshot before the billing guard and batched corrections; `implementation-verified.json` records the later implementation.

Do not delete or rewrite these artifacts. Tests load the failed original outputs directly. No original model answer was edited into a passing result.

## Scope

This is assisted preparation using retained public-source claims. It does not verify the company's actual income, costs, customer activity, legal status or investment merit. Exact commercial figures remain source claims. No company ledgers or customer cohorts were supplied or reconciled, and no investment decision or execution was performed. Neither a model pass nor these development cases justify a calibrated accuracy percentage or autonomous investment confidence.

The source coverage warning remains because collection/context coverage is incomplete. No source refresh, download, paid service, model sweep, outreach or transaction was used. The original live evidence and draft history are retained.

Further preserved content failures:

- `verified/paasa.json`: 59.51 seconds / four calls. The billing correction passed, but an unsupported custody-fee settlement was introduced and model review passed it. The artifact is a direct custody-fee regression fixture.
- `accepted/paasa.json`: despite its historical directory name, this is **not accepted as published economics**. The saved-candidate repair took 25.67 seconds / two calls and removed the custody-fee assertion, but added an unsupported statement about recognized company revenue. The original remains a regression fixture.

The commercial-summary renderer now omits whole sentences asserting accounting recognition/results from this charging-terms field. It does not turn those assertions into alternative claims or alter the stored original. Income recognition remains a separate unresolved question. The remaining text passes source/billing validation, and combined review sees the actual rendered explanation. This narrow boundary does not prove every possible paraphrase correct.

On a validation-contract update, an unchanged company, source record and model configuration can reuse saved analysis/founder text as candidates. They must pass current validation and the current combined review before publication. Changed source data do not qualify for reuse. A correction that introduces a further semantic defect can receive one additional targeted correction, still inside the same 120-second/six-call/ten-request limit.

## Fresh workflow proof

`fresh-current-paasa.json` started with an empty temporary workspace, the same retained source facts and no saved candidates or prior review. It completed nine sections in **88.061 seconds / five local model calls**, including two targeted corrections, founder writing and final review. No collection or live-database mutation occurred in this check. The final readable economics paragraph is 389 characters including code attribution; it distinguishes Access, Apex, the annual fee basis, monthly collection and trading charges, with complete cited source context available separately. It makes no claim that company revenue was recognized.

This is a development regression on the reported company, not an unseen-case or practitioner acceptance result. `implementation-final.json` records the implementation used for this fresh run and final live publication.

## Final live verification

Both exact user-reported company links now show **Drafts prepared**, all three stages available and nine complete sections, with no preparation-failure banner. The live browser checked the displayed summaries, expanded complete source passages, source links, successful research exports, founder/readiness views and mobile overflow. It made zero generation requests. Screenshots and exported Markdown are saved beside `browser-check.json`.

| Company | Final revision | Summary characters | Economics card height | Saved GET | Final review calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Waybill | 318 | 528 | 362 px | 29.639 ms | 1 |
| Paasa | 1306 | 389 | 334 px | 45.725 ms | 1 |

Final live packs: `live/waybill.json` and `live/paasa.json`. Waybill's validated content stayed unchanged while its current review was refreshed; Paasa's rendered explanation omits the unsupported accounting assertion retained in its original shared answer. The final live reviews used one local call each, with no rewriting. Warm review latency is not fresh generation latency. Original source facts, original raw model responses and original section content remain in history. No active jobs remained.

Validation: **213 focused backend tests**, frontend build/lint, isolated UI regression, actual live browser checks and final implementation hashes passed. `verification.json` records every run and its budget: **25 local calls across nine purposeful bounded runs** in this correction sequence, including the preserved failures, one fresh empty-workspace proof and two final review-only publications. No paid inference, download or sweep occurred.

Stable API: PID **7895**, tool session **36854**, `PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/private/tmp/deal-document-matplotlib python3 scripts/serve_local.py`, without reload. Recheck PIDs/jobs before future restarts. Vite and Ollama were not restarted.
