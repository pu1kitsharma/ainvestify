# Shared founder-review and source-recovery fixes — 26 September 2026

The user asked to fix the remaining founder-proposal validation failure and
establish whether the workflow applies beyond CropX. These are shared code changes,
not company-specific handlers or manually authored production answers.

## Root causes and changes

- The review classified a consolidated profit-and-loss statement first as a
  revenue ledger, then as underlying cost records. Both annotations failed the
  exact-span validator. The record-role schema now distinguishes summary
  `financial_statements` from underlying ledgers and cost records. Summary accounts
  do not satisfy contribution-analysis input requirements.
- The reviewer also classified an ARR acquisition/growth bridge as a customer
  cohort comparison. The method contract now explicitly distinguishes them;
  aggregate annotation feedback prevents adding unnecessary cohort records merely
  to satisfy a mistaken review label.
- Review issues can name only actual company-content fields. Review metadata
  such as `method_inputs.second` cannot be sent to the company prose writer as an
  alleged draft defect. Original invalid reviews remain recorded; the model must
  correct them. No failed audit is silently changed to a pass.
- Preparation downloads now return HTTP 409 when the requested document lacks a
  current passing review, instead of downloading unavailable-section notices.
- Arable's initial search selected deleted pages. A new bounded recovery lets the
  model choose up to three alternatives from actual links on fetched pages or
  unused structured search results. Destinations absent from those observations
  are rejected. There is no company URL catalogue or code-written company answer.
- Six task calls remain the limit. Up to eight inference requests account for
  a search task's two additional tool turns, within the original 120-second
  deadline. This applies to preparation and analysis; neither resets the clock.
  The former six-request limit exhausted review capacity with time remaining.
- Preparation review fingerprints no longer hash unrelated navigation/provider
  transport files. Writing, provenance and evidence-validation contracts remain
  checked; source inputs and model configuration remain part of cache identity.
- The analysis component is keyed by workspace so optional form state resets when
  changing company. It is not restricted to CropX. A failed analysis attempt no
  longer displays an incomplete-preparation warning above a completed founder pack.
- New metric corrections must include both the observation label and explanation.
  The model previously corrected water-metric scope in the explanation while
  leaving an inconsistent headline. The guard rejects that incomplete correction
  before another expensive review. Old independently reviewed patches still
  replay unchanged; their content is never rewritten by this validation.
- A rejected analysis patch is now included verbatim in the next correction's
  feedback, along with its validation error and unchanged original base. Before
  this fix the model saw the error but not the overlong/malformed replacement it
  was being asked to repair. Up to three patch attempts still share the same
  overall six-call, eight-request and 120-second limits.

## Observed results and failures

- CropX recovery `automation_f52abd46e4f4`: complete, one new review call,
  17.853 seconds. The existing model-authored proposal was retained. After the
  final contract changes, `automation_67d344380d73` revalidated it again; see
  `cropx-founder-final.json` for its 16.762-second budget and original responses.
- Arable `automation_04d72450da12`: failed after 16.46 seconds because all selected
  secondary pages were unavailable. No draft was generated. The source failure is
  preserved in `arable-source-failure-01.json`.
- Arable `automation_16d2caabad34`: source recovery fetched its observed
  `company.html` and a Mississippi State University project announcement. The
  model wrote a full pack, then corrected section citations. The review was
  denied before invocation at the six-request cap after 68.425 seconds. See
  `arable-request-limit-02.json`; this was not a completed first-pass run.
- Arable `automation_5b2ab7229abd`: completed the retained draft's review in
  14.728 seconds and one new call under the corrected budget. All nine sections
  passed. `arable-founder-final.json` retains the exact draft, correction, review
  and public source collection.
- Both founder endpoints returned HTTP 200 with company-specific filenames and
  zero unavailable-section notices. The corresponding Markdown exports are
  retained here. Both proposals were visibly verified in the running browser.
- Arable analysis `automation_7be1f9d08b4d`: first fresh attempt reached the
  120-second deadline during review after correcting extra/missing JSON fields.
  A valid source-bound candidate remained saved. Its original failure and all
  prompts/responses are in `arable-analysis-timeout-01.json`.
- Arable analysis `automation_89fd3e1ded55`: resumed the saved candidate and
  corrected a funding amount's qualification. A second review then identified a
  water metric description attached to a passage with different wording/scope.
  The run ended with `needs_review` at 115.7 seconds/three new calls; no unreviewed
  findings were published. See `arable-analysis-review-02.json`. This is further
  evidence that bounded per-job recovery does not establish first-pass reliability.
- Arable analysis `automation_26e190b85740`: changed the water metric explanation
  but left the original headline. Its reviewer returned an overlong correction,
  then corrected the review format; the run ended `needs_review` after 107.334
  seconds/three new calls. See `arable-analysis-label-03.json`. This triggered the
  paired-field correction guard above, rather than hand-editing the metric.
- Arable analysis `automation_6f13205425e5`: failed after 16.602 seconds/two calls.
  The first paired correction exceeded a field length limit; the next contained
  an unrequested `value2` key. Both were retained and rejected, not normalized into
  a success. See `arable-analysis-patch-format-04.json`. This led to complete
  rejected-patch feedback and the bounded format-repair change.
- Arable analysis `automation_a1ef05b2b109`: the paired patch validated, but the
  next review flagged a projected-acreage headline and the scope of one attached
  citation. The run ended `needs_review` at 111.49 seconds/two calls. See
  `arable-analysis-scope-05.json`. Medium-effort review latency remained high;
  no validation guard or character limit was relaxed to publish the draft.
- Final Arable analysis `automation_60a69ad7e8c3`: corrections for the target label
  and citation scope were saved, but review again reached the deadline. Final
  state is `needs_attention`, 120.630 seconds/three calls, in
  `arable-analysis-timeout-06.json`. **Arable's full analysis is NOT published.**
  Its founder/research pack remains complete and downloadable. Six analysis jobs
  consumed about 592 seconds cumulatively; they were development attempts, not
  six independent first-pass cases. No further model retry was started at this
  checkpoint. This remaining review latency/reliability failure is material.

289 regression tests passed before the last budget alignment; 68 affected tests
then passed, followed by 17 analysis tests and 28 analysis/API tests after the
paired-field correction guard, then 29 analysis/API tests after rejected-patch
feedback. Frontend build, lint and whitespace
checks passed. Tests cover summary versus underlying accounts, false cohort
classification, review-metadata repair, export rejection, observed-link recovery,
invented-URL rejection, accounting for search turns, source isolation, provenance
and Anthropic API compatibility.

## Boundaries

This is not proof of universal first-pass generation or investment accuracy.
Arable required development corrections, and source coverage remains partial.
Unprepared companies use the same workflow but need a first run; merely opening
them does not generate all deliverables or trigger paid/background sweeps.
No private records or notes were transmitted or included in these evidence
snapshots. No company output was manually edited. No external founder messages,
fundraising actions or investment execution occurred. Concurrent provider and
deployment work was preserved. No commit or push was made during this task.

The first live POST was rejected by automatic approval review over possible
private-data egress. A read-only provenance check established that all 14 CropX
facts and all seven retained prompts used matching public sources, no private
notes/uploads, and intact recorded model answers. The same action was then
approved on that evidence; no alternate egress path was used.
