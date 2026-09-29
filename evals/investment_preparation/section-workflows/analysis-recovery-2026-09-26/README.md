# Shared analysis recovery — 26 September 2026

The user asked to fix Arable's unpublished analysis and reliability across companies.
The fixes are shared code, with no company-specific runtime answers or selection lists.
Arable and CropX currently publish reviewed analyses; GoCardless is unpublished.
This is **not** a demonstrated universal/first-pass reliability or investment-accuracy claim.

## Changes

- Analysis writing, review and corrections use bounded low reasoning effort. The previous
  medium review consumed 50–100 seconds. Low effort still varied and is not an SLA.
- Replaced accumulated writer instructions with one explicit schema, metric and scenario
  contract; review understands future estimates, bounds, range endpoints and jointly
  supporting citations. Reviews can return up to 12 material issues rather than three.
- Exact short enum quotations and actual citation-array members are valid review targets.
  Nonexistent fields, citations and source quotations remain rejected.
- Correct invalid fields rather than rewriting a schema-valid whole report. More than
  one correction/review pair can finish inside the same six-call/eight-request/120-second
  budget; reserve observed review time before starting another pair. No automatic new job.
- Formatting repair is itself model-authored and recorded. For schema-forbidden extra
  keys the model lists dotted paths; code verifies each is actually forbidden, then
  removes only those keys. Required content cannot be removed by that operation.
  Syntax edits require exact substring counts. Original raw writer output, each edit,
  subsequent field patches and the approving review are all retained and replayed.
  Strict final schema, numerical guards, source binding and independent review still apply.
- Saved drafts survive a review-policy change. Applied corrections clear stale objections
  so a timed-out re-review does not apply the old criticism to the new answer again.
- Fixed numeric extraction of forms such as `5+ billion`: retains the literal scale and
  normalizes to 5,000,000,000 instead of displaying 5. Candidate order stays stable.
- Claude Pro quota errors now raise a non-retriable error with the reset time. They must
  not enter JSON-format, content-correction or review retry loops. No paid fallback.
- Added `scripts/evaluate_company_analysis.py`: fresh writer/review in an isolated
  temporary database using public sources only; `--fresh-research` includes search/fetch.
  Default isolated tests below reused source collection, **not** old answers.

## Results and failures

Earlier diagnostics and failed designs are intentionally retained. They are development
iterations, not independent unbiased benchmark cases. Successful resumes are not fresh
first-pass results. Public source collection can still be incomplete.

| Artifact | Seconds | Outcome |
| --- | ---: | --- |
| [arable-fresh-draft-v3.json](arable-fresh-draft-v3.json) | 27.666 | needs_attention; published=False |
| [arable-fresh-draft-v4.json](arable-fresh-draft-v4.json) | 65.639 | needs_attention; published=False |
| [arable-fresh-draft-v5.json](arable-fresh-draft-v5.json) | 4.383 | needs_attention; published=False |
| [arable-fresh-draft.json](arable-fresh-draft.json) | 48.218 | needs_attention; published=False |
| [arable-live-recovery.json](arable-live-recovery.json) | 87.07 | waiting_for_input |
| [arable-live-v3.json](arable-live-v3.json) | 117.551 | waiting_for_input |
| [cropx-fresh-draft-v2.json](cropx-fresh-draft-v2.json) | 120.489 | needs_attention; published=False |
| [cropx-fresh-draft-v3.json](cropx-fresh-draft-v3.json) | 117.641 | waiting_for_input; published=True |
| [cropx-fresh-draft.json](cropx-fresh-draft.json) | 119.358 | needs_review; published=False |
| [cropx-live-v3.json](cropx-live-v3.json) | 24.051 | waiting_for_input |
| [gocardless-citation-binding-failure.json](gocardless-citation-binding-failure.json) | 104.463 | needs_attention |
| [gocardless-live-first-failure.json](gocardless-live-first-failure.json) | 120.626 | needs_attention |
| [gocardless-live-v3.json](gocardless-live-v3.json) | 102.135 | needs_review |
| [gocardless-quota-blocked.json](gocardless-quota-blocked.json) | 6.032 | needs_attention |
| [review-funding-as-revenue-negative.json](review-funding-as-revenue-negative.json) | 6.047 | review diagnostic |
| [review-known-defects.json](review-known-defects.json) | 8.379 | error |
| [review-retained-candidate.json](review-retained-candidate.json) | 57.97 | review diagnostic |

Arable recovery `automation_e1fe267d1fdd` published eight metrics/three outlooks in
87.070 seconds. After the scale fix, `automation_d4807bbaa1a1` revalidated/corrected
its source scope in 117.551 seconds. CropX revalidation `automation_db0c14f13c74`
completed in 24.051 seconds. Its isolated fresh draft (`cropx-fresh-draft-v3.json`)
completed in 117.641 seconds/four calls, including an ARR-bound correction.

Fresh Arable evaluations exposed syntax/schema defects, then ambiguous string repairs.
The final schema-aware path was blocked by provider quota before it could be exercised
live. It passes regression tests; **fresh Arable success is not demonstrated**.

GoCardless first ran fresh public navigation and failed while rewriting invalid JSON.
Its later retained-source draft and multiple corrections did not reach an approved
analysis. A legitimate source-list objection was rejected by the old string-only
validator; that shared bug is fixed. Final resume was blocked by Claude Pro's limit.

The provider explicitly returned `You've hit your session limit · resets 6:20pm
(Asia/Calcutta)` on 26 September. No further inference was started after observing
this. Earlier generic quota errors incorrectly triggered retries; final code/tests
stop after the first quota failure. No paid API fallback was used.

## Verification and next work

146 regression tests passed across analysis, provider/API compatibility, subscription,
source research, founder review/preparation and shared preparation. These tests establish
workflow/provenance behavior, not financial accuracy. Backend-only changes did not need
a new frontend build. `verification.json` records current API/export responses and cached
latency. Arable analysis was checked in the browser. No active jobs were left running.

After the subscription reset and a user-authorized continuation: first exercise the
final format-repair path on one fresh Arable evaluation, then resume the retained
GoCardless corrections. Do not repeat full writers to repair individual fields or
start many benchmark jobs. Preserve all original failed responses. A wider multi-sector
MVP-quality evaluation is still outstanding. The sources and model judgments still need
expert evaluation; publication is not evidence of verified company finances.
