# Public-evidence subscription preparation — 24 September 2026

The user explicitly approved **“Use Claude Pro for public-evidence drafts”** as the application's working generation path. This supersedes the earlier local-only production decision. Private company records, notes, uploads and storage remain local. Discovery remains on its existing local/public-search path.

The official signed-in Claude CLI is the transport. Tools, project settings, extensions, browser access and conversation persistence are disabled; each invocation uses an empty temporary working directory. API/provider override environment variables are removed. The app does not configure an API key, paid fallback or AWS service. Pro usage limits still apply. CLI dollar figures are API-equivalent estimates, not invoices; application calls also do not include the CLI's reported auxiliary model usage.

## Evidence and iteration history

All runs are bounded to 120 seconds and six application calls/requests. Repairs consume the same budget. Time-limit cleanup can add a small process-termination overhead. These are development iterations under changing contracts, not independent benchmark samples or an accuracy percentage.

| Artifact | Result | Recorded time | Calls |
| --- | --- | ---: | ---: |
| `gocardless-complete-workflow/` | Mechanically complete; independent audit found missing method inputs and citation defects | 41.9 s | 3 |
| `gocardless-input-audit/` | High-effort review timed out | 120.6 s | 3 |
| `cropx-input-audit/` | Invalid extra review fields; nothing accepted | 77.8 s | 2 |
| `gocardless-bounded-review/` | Mechanically complete; transaction-record attribution remained too permissive | 118.9 s | 4 |
| `live-gocardless-first.json` | Correction exceeded record-request field limits | 79.9 s | 5 |
| `live-cropx-first.json` | Input review still failed; draft also mixed neighboring directory information | 107.5 s | 4 |
| `live-gocardless-attribution.json` | Review quoted credits separately from invoices; false-positive role rejection; outbound wording also needed correction | 117.5 s | 4 |
| `live-cropx-attribution.json` | Fresh complete pack with correct company scope and explicit financial unknowns | 102.0 s | 5 |
| `live-gocardless-final.json` | Saved draft repaired and reviewed under the next contract; **resume, not fresh generation** | 38.5 s | 2 new |
| `live-cropx-final.json` | Same model-written draft revalidated under the next contract; **review only** | 30.9 s | 1 new |
| `gocardless-final-fresh/` | Fresh attempt failed when its founder correction again exceeded 400 characters; prompted bounded correction-retry fix | 60.9 s | 2 |
| `gocardless-targeted-correction/` | Fresh complete pack with one combined correction and two reviews; independent inspection still found an arbitrary example fiscal year and imprecise payment-rail wording | 99.2 s | 4 |

The final fresh run demonstrates recovery and full-pack completion, not first-pass or universal semantic accuracy. Its `FY2025` example was not supplied evidence; “Pay by Bank/Direct Debit” also compresses distinct payment mechanisms. It was not imported over the live GoCardless draft. No further prompt experiment was started after this bounded verification. Final service verification is recorded separately and in handoff §29.

The first GoCardless public snapshot is linked from `../pro-subscription-diagnostic-2026-09-24/gocardless-public.json`. `cropx-public.json` is a deliberately thin, real directory excerpt: text before the CropX entry belongs to the preceding listing. One directory rating is not company growth. Raw passages are retained unchanged, including the mixed context, so this remains a useful attribution regression case.

## What the changes establish

- Model-generated content remains an exact projection of recorded original answers and targeted model corrections. No company answer was manually edited, imported from a reference, or supplied by a production template.
- Coordinated initial drafting avoids repeating the same context for three separate writing calls. Multi-phase repairs can share one recorded response while preserving field-level provenance.
- Schema-invalid corrections remain candidates and can receive a further bounded correction. Repair prompts explicitly replace whole-draft word targets with the correction schema's field limits.
- A structured method audit maps requested financial inputs to exact record-request spans. Missing pricing agreements, transactions, invoices/credits, recognition policy, revenue ledger or attributable cost records prevent the relevant method from passing. Separate invoice/credit mentions in the same request are accepted; merely mentioning a transaction set is insufficient.
- Original model-selected exact source claims now accompany full source context. Drafting/review instructions distinguish adjacent directory entries. A narrow payment-direction validator rejects describing outbound payments as collected.
- A review schema error receives a recorded model correction; extra fields are never silently stripped to make a response pass. Full validation still runs before publication and export.
- A final-round rejection is retained with content/contract hashes. Resume applies that recorded objection first, then reviews the correction, instead of spending another call rediscovering the defect. Matching older rejections can be reused; old passes cannot bypass a new contract.
- Tests check private-data exclusion, provider controls, deadline process cleanup, provenance/tamper rejection, corrections, job integration and cache reuse.

## Live display and quality limits

`browser-check.json` and six screenshots show research, founder proposal and readiness for both actual companies. All three stages display **Draft available** with no JavaScript errors or incomplete-preparation banner. The research and readiness screenshots were visually inspected. `export-check.json` records eight successful real downloads. The isolated browser regression also passed stop/resume, failure handling, source expansion, exports and mobile layout.

`cache-check.json` records 40.49 ms for GoCardless and 19.21 ms for CropX at that checkpoint. Both kept the same job and byte-equal attempt records: **zero new inference**. These are local request measurements, not a global latency SLA.

Independent inspection supports using the completed packs as initial, source-limited discussion drafts. CropX's charging model, customer volume, retention and financial results remain unknown. GoCardless's processed volume is kept separate from earned revenue, and its billing/recognition/cost records are requested rather than claimed to have been examined. Its public-tariff comparison is a reference comparison; negotiated agreements govern actual charges. Financial work remains proposed narrative analysis, not executed reconciliation or a validated typed calculation plan. The reviewer still has false positives and missed defects; the new guards are narrow, not universal semantic verification.

Two companies and several failures do **not** establish reliable first-pass generation across sectors, investment accuracy, complete source coverage, fundraising readiness or autonomous investment execution. Preserve failures and distinguish fresh generation, targeted correction, contract revalidation and cache reuse in any status report.

`contract-recheck-gocardless.json` preserves the later final-round payment-rail wording objection that exposed redundant review on resume. `contract-recheck-cropx.json` demonstrates recovery from invalid review JSON without rewriting the underlying accepted draft. `resume-recheck-gocardless.json` preserves a further false positive: a single quoted request explicitly named “revenue ledger with recognition policy,” but only one input role was counted. The validator now recognizes both explicitly requested inputs; “without recognition policy” still fails. `input-annotation-*.json` preserves the subsequent GoCardless pass and CropX reviewer-label error. Invalid review annotations now receive one bounded model-written review correction, retaining the strict exact-quote/role checks and leaving company prose untouched. These failures remain part of the evidence, even after a subsequent job completes. Final regression count: **321 passed**, 16 warnings.

Final deployed evidence is in `deployed-*.json` and `deployed-*.png`: both actual packs are complete, all six tabs load without browser errors, all eight exports succeed. The last operations were contract reviews (32.208 s / one call and 39.507 s / one call), not fresh generation. Final cache requests took 51.26 ms and 27.58 ms with unchanged job IDs and identical attempt records. Content inspection here was separate Codex inspection, not an external human financial audit. The full application/source-quality limits above still apply.
