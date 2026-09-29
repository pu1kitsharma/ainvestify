# Executing analysis workflow — 26 September 2026

The user rejected four-result discovery, provider implementation banners, generic
founder exports and a readiness page consisting of proposed advisory work. They
then clarified that human intervention must not mean asking them to do the
research or fill in every metric. A concurrent session is adding Anthropic API
and deployment support; the user explicitly requested compatibility.

## Observed result

- Discovery continuation `source_run_9d225ce15412` returned four additional
  candidates in **67.401 seconds**, three calls/five requests. Arable, Instacrops,
  OneSoil and Green Collar Agritech Solutions join the original four in the
  continued search view. The real browser showed **eight companies**. Source
  coverage is partial; these are candidates, not verified investment targets.
- CropX analysis job `automation_4445f087ab5e` completed **retained-draft
  correction and review** in **97.765 seconds**, two new calls/requests. It
  published seven source-bound observations, findings, three conditional
  outlooks, one private-record request and two system-owned public research gaps.
  This is not a fresh first-pass success. Its reviewer alone took 85.632 seconds.
- Analysis download returned HTTP 200, `cropx-analysis.md`, about 9.3 KB in
  125 ms with no inference. Founder download uses `cropx-founder.md` and appends
  the metrics/analysis, but the legacy founder sections remain unavailable after
  the later review failure described below.
- The browser showed findings, metrics and outlooks **before** the input area.
  Public lookup gaps have a research action rather than response forms. One
  focused private-account request is shown. Source, private-record and manual
  growth-assumption forms are optional collapsed controls.

## Implementation and actual limits

`agents/company_analysis.py` runs a bounded collection → model analysis →
source/financial review → targeted model correction workflow. Company narrative
is reconstructed exactly from recorded draft and patch responses; code supplies
literal numeric/date candidates, binds passages, normalizes values and calculates.
It never fills in a company answer or a missing financial amount. Patches can
replace existing text or source-ID arrays, not insert arbitrary fields. Their
base answer and final reviewed answer are checked during every display/export.

Review objections must quote an actual answer field and an actual supplied source
passage. Prior exact rejections can be reused to avoid paying for the same review
again. Draft, correction and review use medium reasoning on Pro. Review payloads
retain all source passages but omit unselected numeric/date candidates and avoid
duplicating whole source quotations for every token. These changes do **not**
establish broad financial reasoning quality or first-pass reliability.

Source retrieval uses model-selected observed URLs, the existing protected public
fetcher and retained evidence. The CropX run retrieved its official Series C page
and homepage. Crunchbase/Bloomberg returned 403; D&B and the Israeli registrar
timed out. **No government financial filing was successfully retrieved in this
live check.** There is no new comprehensive worldwide register adapter or verified
accounts dataset. Public requests remain research tasks; `research_gaps=true`
builds a targeted model search from those tasks and fetches observed destinations.
Its ownership/privacy/collection loop is fixture-tested, not another completed
live follow-up search at this checkpoint.

Private updates remain local. Existing local extraction supplies monthly figures
and deterministic calculations; it does not silently send private accounts to
Pro/API. Public forecasts are conditional narrative. The optional numeric growth
calculator requires an exact dated revenue/ARR baseline and explicitly approved
growth assumptions. CropX's “approaching” ARR is **not** eligible as an exact
baseline. No live numerical forecast or completed financial diligence is claimed.

Validated older analysis remains visible during a new attempt, labeled as the
last completed version. This retention is regression-tested. Public/identity gaps
belong to the system; private records/approval decisions belong to the user.
Saving a note does not establish an actual metric or complete diligence.

## Failures are retained

See [attempt index](attempt-index.json), [timing table](attempt-table.md), and
`cropx-attempt-01.json` through `cropx-attempt-10.json`. Public inputs, raw model
answers, instructions, schemas and response hashes are retained. Private answers
and scenario records are excluded from these exports, as are provider transcript
metadata and opaque routing details. Full original runtime records remain local.

The sequence includes an unobserved URL selection; copied quote/value failures;
incorrect bounds; ungrounded reviewer objections; non-literal dates; extra schema
fields; misclassification of staff/devices/users as customers; overlong prose;
incomplete Markdown fencing; an encoded source-ID array; and timeouts. These
required multiple explicit development runs, cumulatively **over thirteen minutes
of analysis inference**, not one two-minute result. Do not describe this as a
reliable instant-generation fix.

Attempt 03 also exposed mutable recorded input dictionaries: subsequent repairs
changed earlier input metadata. Raw answers are retained, but that attempt's
input metadata is not a pristine prompt audit. `recorded_call` now snapshots
inputs with `deepcopy`, covered by a regression test.

Attempt 07 is a historical interrupted snapshot, not an active job. A concurrent
CropX job (`automation_89f061619417`) started before a restart; the agent batched
the job check and restart and failed to honor the active-job result. The job was
interrupted and its partial report retained. The user was told. Subsequent
restarts perform an immediate job check and refuse to stop an active worker.

The fenced-response parser accepts a sole opening fence only if the remaining
text is already complete, parseable JSON. It does not repair JSON, drop extra
fields, clip text or extract an object from surrounding commentary.

## Legacy preparation remains unresolved

Provider/parser contract changes correctly required new validation of the old
nine-section packs. The CropX revalidation job `automation_e754962b8c2f` failed
after about 52 seconds: method review assigned a cost-record role to a request
span not accepted by the current matcher. See
[saved status](latest-preparation-status.json). Research/founder tabs retain
“Needs attention”; the independently reviewed analysis is available. The failure
is shown on the relevant legacy tabs rather than incorrectly blocking analysis.
The founder export contains its unavailable-section notices plus the new analysis
appendix. Do not claim the founder proposal is repaired or hide that limitation.

## Validation and compatibility

228 focused regression tests passed across analysis, public research, Pro/API
transport, authored preparation, local models, operating workflow, metric
extraction/calculation, and web discovery. After the final cancellation/export
adjustments, 40 affected tests passed. Frontend build, lint and `git diff --check`
passed. These are engineering checks, not an investment-quality evaluation.

The new analysis adapter inherits the concurrent public-research provider routing.
The Anthropic transport compatibility test was updated for period candidates and
passes. No provider configuration, credential, API key or deployment file was
replaced; all live checks in this work used the already authorized Pro path.
No external messages, fund transfers, investment execution or new cloud deployment
were performed. Changes were not committed or pushed in this task.
