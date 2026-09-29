# Public research repair — 25 September 2026

This checkpoint follows the user's rejection of the prior nine-section packs and
request to fix discovery breadth, vague analysis, missed material facts and
unreadable output. These are engineering and content observations, not a certified
investment-quality score or a golden company template.

## Implemented

- Production discovery now uses the approved Claude Pro subscription for public
  navigation and batched company assessment. The isolated CLI exposes only
  WebSearch during navigation; drafting exposes no file, shell or browser tools.
- Search link objects, not generated search summaries, establish observed URLs.
  Local retrieval still checks public addresses, redirects, robots and deadlines.
- Up to six pages are fetched concurrently and up to five distinct companies can
  be selected, including multiple entries from the same directory.
- Exact source claims use complete paragraph/sentence blocks, replacing the
  600-character boundaries that rejected genuine quoted claims. Unsupported
  names/quotes can receive one model-authored correction; original responses and
  patch provenance are retained. Failed binding still excludes a candidate.
- Company preparation now researches official product/customer pages and current
  ownership/news, including companies whose website was previously unresolved.
  An identifiable official company page and another collected page are required.
- Public evidence expires after 24 hours. Fresh passages are interleaved across
  source URLs within a 24,000-character budget; sources and dates reach the model.
  Historical records are retained. Failed collection cannot masquerade as a fresh
  successful cache. Drafts still require their existing source and review checks.
- Drafting/review now prioritise specific customer/business decisions, material
  ownership changes and distinct useful work. Financial safeguards apply when a
  financial method is actually chosen; the prompt no longer prescribes fee audits.
- Discovery cards show the recorded rationale and an open question without an
  expansion click. No company prose was manually inserted.
- Native StructuredOutput was tested for typed generation, with the original
  model tool object and CLI result checked for equality. Formatting failures are
  retained as schema failures for a bounded model correction, not reported as a
  subscription outage. One model response per drafting invocation is enforced.
  Native tool validation does NOT guarantee first-pass correctness: the live
  diagnostics exposed both a long field and an incorrectly wrapped review object.
- A dedicated model shortening task handles length-only failures. Consecutive
  inline workstream labels `(1)` and `(2)` are ignored only by numeric validation;
  the actual displayed model prose remains unchanged and financial numbers remain
  checked. Qualitative pricing documents no longer invite a signed-contract role.

## Fresh discovery evidence

| Run suffix | Retained companies | Elapsed seconds | Outcome |
| --- | ---: | ---: | --- |
| b202f1bef952 | 0 | 14.373 | CLI turn-count mismatch; failed, preserved |
| 3b5affb7db6d | 1 | 62.254 | Four real quotes crossed artificial source boundaries |
| 1367b782ddcf | 2 | 90.810 | Three candidates had literal name/quote defects |
| 817434530ea1 | 4 | 79.437 | AGCO, Molagri, Brumby, AGRIVI; one rejected candidate |

All four run JSON files are preserved. The four-result run used three logical
model calls/five reserved or consumed main-model requests, including navigation
and one source correction. It has three evidence publishers and is still marked
partial: official identity is unresolved for these discovery candidates, and
source claims have not been independently verified. It is a comparative starting
point, not four approved investments. Browser inspection confirmed the four cards
with their distinct offering, rationale and open question.

## Preparation evidence and limits

Fresh GoCardless collection retrieved its homepage/about page and official
completed-acquisition disclosures, fixing the previously missed ownership change.
Two third-party pages were unavailable; no access control was bypassed.
CropX collection retrieved its official homepage, about, hardware and news pages,
plus AgFunder reporting. Its draft now discusses acquired versus organic growth
and integration instead of treating a directory rating as an outreach hook.

The first refreshed jobs did not finish reliably: GoCardless exhausted requests
after review annotation repair; CropX stopped on the inline-list-number false
positive. Later reviews exposed actual ARR comparison and cohort-timing defects,
as well as length/format failures. Those failures must not be labelled successes.
Final deployed preparation snapshots and their final status belong alongside this
file after verification; earlier failures remain in the recorded attempt/history
objects. Source improvements do not establish error-free financial reasoning.

Verification so far: a broad 330-test suite passed before the final format fixes;
subsequent focused suites passed (138, then 52 after native-error recovery and the
shortening task). Frontend production build and lint passed. Re-running a company
uses a separate 120-second job with six logical calls/six main requests; discovery
has its own bounded budget. Main-request accounting includes navigation turns;
CLI usage also records auxiliary model usage. No paid API or AWS path was added.


## Final generation transport and recovery

Native StructuredOutput is **disabled in production** after repeated invalid tool
wrappers and incomplete arguments. The final adapter requests one tool-free JSON
response and verifies it against the actual recorded assistant text, then applies
schema/source/provenance checks. Native-mode tests retain the experimental failure
cases. Strict formatting remains a validation contract, not a first-pass guarantee.

A connection closed mid-response now receives one recorded retry inside the same
call, request and time limits. Authentication, quota and ordinary validation errors
do not receive this transport retry. Both single-phase and combined substantive
method corrections can rewrite the entire affected plan to reconcile records,
action and output. A failed patch cannot poison every later resume: its original
response stays recorded while the candidate pointer returns to the last
reconstructable model-authored version. A new prose defect in a correction can use
one more bounded model correction; unsupported figures still prevent publication.

| Additional discovery run | Companies | Seconds | Outcome |
| --- | ---: | ---: | --- |
| `source_run_8709197230ff` | 0 | 35.917 | Provider connection closed mid-response; before transport recovery |
| `source_run_f5c1bec2b143` | 0 | 120.542 | Native-format attempt exhausted the bounded job |
| `source_run_e9bc7930c9a7` | 4 | 58.948 | Direct JSON; CropX, Cropin, Trace AgTech, AGCO Corporation |

The final search used three logical calls/five main requests and four discovery
publishers. It is explicitly partial: one unavailable source, missing commercial
figures, and four supported candidates rather than an invented fifth. It selected
four official company pages. Some discovery claims came from pages with unrendered
numeric counters; those limits are explicitly recorded. Broad agrotech includes a
large incumbent; the output is a research shortlist, not verified investment fit.
Browser inspection confirmed four visible cards with offering, rationale and open
question. The discovery/preparation concurrency guard correctly stopped CropX when
newly discovered evidence changed its inputs; it was resumed after discovery ended.

`checkpoint-*.json` preserves intermediate public-only packs and unique prior
public model attempts. Runtime SQLite retains all original histories. Committed
exports omit CLI system events and encrypted thinking/signature fields, but retain
actual response text, response hashes, inputs, schemas, model answers and failures.
No private workspace notes, uploads, financial records or credentials are exported.

Final focused/regression verification: **233 passed, 15 warnings, 19.20 seconds**.
Earlier broad 330-test evidence preceded late format/recovery changes; do not imply
it tested the final contract. Frontend build and lint passed earlier in this repair;
no frontend edits followed those checks. Deterministic tests measure implementation,
not the accuracy or investment quality of generated prose.


### Final deployed verification — 26 September IST

Both workspaces have nine complete model-authored draft sections and three “Draft
available” stages. These are initial public-evidence research and proposed-work
outputs, not completed diligence or a certification of investment accuracy.

| Company | Final job | Operation | Measured budget | Saved request |
| --- | --- | --- | --- | --- |
| GoCardless | `automation_d15342d01f23` | Retained-draft correction and review | 42.211 s; 2 calls / 2 requests | 90.59 ms; zero inference |
| CropX | `automation_36baba8d8d12` | Fresh collection, fresh draft and review with annotation repair | 79.004 s; 4 calls / 6 requests | 107.86 ms; zero inference |

CropX's final fresh pack contains three drafting/review response records; the fourth
logical call was public navigation in the collection record. Its two main tasks
now cover an acquisition-adjusted recurring-revenue comparison and integration
milestones against the stated future profitability target. GoCardless explicitly
recognizes its completed acquisition and defers treating it as an independent
fundraising prospect. These replace the old directory-only/generic-fee-audit output.
Both still have partial source coverage and require company records for proposed
financial work. The plans retain terms such as ARR and EBITDA and are not a fully
typed executable financial model. Further plain-language quality and first-pass
reliability across unrelated companies remain unestablished.

The final agrotech search is `source_run_e9bc7930c9a7`: CropX, Cropin, Trace AgTech and
AGCO Corporation in 58.948 seconds. It is marked partial rather than claiming a fifth
result or verified investment suitability. GoCardless research, CropX readiness and
all four discovery cards were inspected in the real browser. The generated prose
and source links are displayed; neither company has the incomplete-preparation
banner. Zero-inference cache checks compared identical saved job IDs and full model
attempt records before/after POSTs, rather than assuming a fast response was cached.

`deployed-gocardless.json`, `deployed-cropx.json` and `deployed-check.json` preserve
final public output, source collection, exact responses, budget and cache evidence.
The preceding checkpoint files preserve failed intermediate work. A cache-check
script initially assumed internal attempts were exposed by the public API and
raised KeyError; the corrected check uses read-only SQLite for provenance and the
API for the actual request. That was a verification-script error, not another
preparation failure.

Final focused/regression suite: **233 passed, 15 warnings, 19.20 seconds**. Frontend
build/lint passed; no frontend changes followed that check. The stable API is
PID24389/tool session27840 on127.0.0.1:8000, with Vite on5173. Recheck liveness and
active jobs rather than trusting these historical IDs. No unattended model jobs
remain at this checkpoint. Changes remain uncommitted; no push was made this turn.
