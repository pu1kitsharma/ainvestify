# Next agent: execute the research pipeline

## 4 October repository cleanup checkpoint

The tracked checkout contained 817 files; 279 historical evaluation JSON files
accounted for about 66 MiB. We archived 143 unlinked, non-fixture raw JSON
snapshots (41.91 MiB) into a verified 7.99 MiB tarball with a path/size/SHA-256
manifest. All original bytes were also copied to ignored
`runtime_backups/repo-cleanup-2026-10-04/eval-raw/` before removal from the
tracked checkout. Test-referenced JSON, Markdown-linked JSON and reports under
`final/`, `accepted/` or `verified/` remain at their old paths. See
`evals/investment_preparation/section-workflows/ARCHIVE.md` for verification
and extraction. The 1.6 GiB Elasticsearch distribution and frontend
`node_modules` are already ignored local installations, not Git content. This
cleanup does not rewrite historical Git objects or claim a live model result.

## 4 October frontend and source-scoped review checkpoint

**Tested code:** The frontend room panel now exposes durable workflow stages,
public KB binding and rights status, local semantic findings, release blockers,
and preview links limited to the latest job's input revision. The older Documents
view is marked historical and read-only; its retired compiler actions and false
send-ready/financial-data language were removed. The README, frontend README,
AGENTS actual state and Git ignore rules were updated. Generated `output/`,
scratch `tmp/` and a machine-specific failed launchd draft remain on disk but
are excluded from source control; private originals, runtime evidence and
fixtures were preserved. The backend still lacks a concise package/reviewer
release summary and citation-level review findings in the room API, so the UI
cannot show an exact accepted-package drilldown.

Claude Code, through the signed-in VS Code extension, implemented the
`semantic_v8` source-scoped material-review request and synthetic regressions;
Codex wired fresh production and diagnostic requests to that version while
preserving recorded v1–v7 replay. The model still selects the slide sentence,
decides whether a defect exists, and authors the finding. Software offers only
memo spans sharing that sentence's cited source IDs and rejects other choices.
The focused review/room test set passed **39 tests**. The combined research,
delivery, room, financial and KB candidate suite passed **695 tests, 5 skipped**;
frontend `npm run build` and `npm run lint` passed; `git diff --check` passed.
An optional whole-repository run was **not green**: 1368 passed, 5 skipped,
24 failed. The failures span retired legacy compilation endpoints, live API
model/service tests, concurrency and old preparation expectations; do not
represent them as release-qualified. No company data was manually altered.

**Live acceptance:** One fresh, bounded synthetic local 9B review under
`runtime_qualification/local_material_review_harness/2026-10-04-v16-source-scoped-9b-v9/`
blocked after two responses with `bounded_material_review_validation_exhausted`.
The model selected `body_sentence_index: 4` on a four-sentence slide (valid
indices 0–3) and repeated the invalid answer after exact validation feedback.
The source filter rejected acceptance; it did not establish semantic accuracy.
No investor material, private Toffee case or visual layout passed acceptance.

**Next action:** Replace the model's unbounded sentence-index selection with a
typed, enumerated slide-sentence choice in a new versioned contract, then run a
finite synthetic defect/control review and model-authored repair/re-review.
Preserve the v9 raw attempts and every historical version. After source-binding
passes, independent content and visual review and financial reconciliation
still gate any real investor package. Extend the room API with exact package,
reviewer and finding details only when the backend has an authoritative version
to expose.

## 4 October latest checkpoint: indexed semantic review, live block

**Tested code:** Fresh material-review requests now use `semantic_v7`. The
installed local model selects a deck, slide, exact slide-sentence index and
frozen memo-evidence index, and authors the issue and explanation. Software
inserts the selected exact quotes, validates same-source binding, and keeps
the review/repair/re-review phases finite. A blocking raw finding cannot be
silently retracted as a passing retry. `semantic_v7` makes terminal invalid
reviews replay to the same result after restart. Earlier versioned requests
retain their recorded schemas/instructions and raw attempts. The signed-in
Claude Code VS Code extension implemented the versioned block-withdrawal guard
and its ten synthetic tests; the separate CLI remains logged out. Codex
implemented source-span/sentence indexing, version propagation, focused tests
and live diagnostics. The combined research, delivery, room, financial and KB
candidate suite passed **676 tests, 5 skipped**; `git diff --check` is clean.
No private Toffee data was changed or sent to hosted inference.

**Live acceptance:** A fresh clean synthetic memo passed local 9B checks under
`runtime_qualification/local_memo_harness/2026-10-04-process-leak-gate-9b-v2/`
(19 recorded responses, 10 passes, independent review pending). The next
synthetic material run at
`runtime_qualification/local_material_harness/2026-10-04-layout-fallback-9b-v16/`
passed local editable/PDF text-pair checks for intro (5 pages), pitch (6 pages)
and memo (7 pages) in six 9B responses. Visual inspection still found sparse
slides, small funding text and a dense memo with raw JSON/awkward pagination;
`content_layout_status: not_run`, `investor_material_accepted: false`.
Four finite semantic-review diagnostics on that frozen v16 material remain
blocked: v4 found debatable defects, v5/v6 failed quote/source binding, and
v7 at `runtime_qualification/local_material_review_harness/2026-10-04-v16-span-index-9b-v7/`
failed span-index/slide-quote validation. V8 at
`runtime_qualification/local_material_review_harness/2026-10-04-v16-dual-span-index-9b-v8/`
removed transcription errors but twice paired a product slide sentence citing
`[S1]` with funding evidence citing `[S3]`; it blocked after two calls. V8 used
`semantic_v6`; current `semantic_v7` changes terminal replay only and has code
tests but no fresh live run. A prior repair diagnostic under
`runtime_qualification/local_material_repair_harness/2026-10-04-v16-review-v4-repair-9b-v3/`
also blocked after a model-authored dispute and re-review. No investor material
or private Toffee acceptance has passed.

**Next vertical slice:** constrain the model's memo-evidence choices to spans
whose source IDs intersect the selected slide sentence, in the typed review
request, then validate source binding and exact replay. The model must still
choose whether there is a substantive defect and author its explanation.
Run one finite synthetic 9B review on frozen v16. A quote-bound block should
feed one model-authored slide repair and frozen re-review; a clean pass still
requires independent content and visual review. Do not rewrite the saved v16
or old raw attempts to claim acceptance. The public KB currently uses six
rights-approved StartupDB detail sources; its 23 observed funding events have
unknown completion. MCA OGD identity import and startups.gallery scheduled
collection remain disabled pending exact dataset/source rights qualification.

## 4 October checkpoint: bounded material review, private Office conversion

**Tested code:** Investor decks now have a separate finite local-model semantic
review after source-bound material drafting. A passing response is replayed
against the exact memo, deck, model digest/options and quoted slide/source
spans before render. A quote-bound block can trigger one model-authored
structured slide replacement and one frozen re-review; these have distinct
durable phase caps and raw attempt files. Invalid or timed-out outputs block
release. The combined research, delivery, room, financial and KB candidate
suite passed 651 tests, 5 skipped, with `git diff --check` clean. This is
software qualification, not an independent investment review.

Private LibreOffice 26.8 conversion now uses a short 0700 job directory and
job-local Unix IPC socket without relaxing the isolation policy. Synthetic
intro and pitch PPTX-to-PDF text/page checks pass at five pages each. The
revised synthetic memo DOCX and LibreOffice PDF pass exact text checks at
seven pages each; visual parity remains pending and pagination differs.
Privacy canaries for sibling files, TCP outbound/bind and sibling Unix sockets
pass. An independent PDF text extractor resolves a verified kerning extraction
artifact on two slides without discarding arbitrary spaces. The original v10
five-page memo still mismatches LibreOffice's seven pages and stays historical.

The public KB funding projector now compares partial year/month/day dates as
intervals, so overlapping source dates cannot establish a false current
stage by string ordering. The public KB suite passed 64 tests. The live
StartupDB ledger still contains 23 append-only observations across six
company projections, all with unknown completion; MCA remains disabled.

**Live acceptance:** The local 9B produced a quote-bound *block* on a v10
synthetic pitch during the new semantic review. Its two findings are model
assessments and at least partly overstate what the slides claim. V10 fails
the strengthened same-sentence financial disclosure rule and cannot be
promoted. Fresh v11 ended at the three-call intro cap because the model twice
returned a one-based index instead of the requested zero-based slide index;
raw results are under `runtime_qualification/local_material_harness/2026-10-04-structured-semantic-9b-v11/`.
The versioned `structured_v2` contract removes slide index from model output;
software routes the model-authored replacement to the frozen target. Fresh
v12 proved that repair, then blocked at the intro cap when the model repeated
an internal numeric-validation phrase from the previously accepted synthetic
memo. Raw v12 is under
`runtime_qualification/local_material_harness/2026-10-04-routed-structured-9b-v12/`.
The memo validator now rejects this exact process-language family before a
new memo can be accepted. V11 and v12 reached neither pitch nor the new
review/repair/re-review chain; those later phases have code tests only.
Rebuild a fresh synthetic memo under the strengthened validator before the
next live material diagnostic; never alter the old accepted memo or raw
responses. No Toffee-level investor material, actual financial forecast,
visual layout, independent review or production release has passed.

## 3 October current checkpoint: finite local memo pass and material run

**Immediate state:** The installed `qwen3.5:9b` completed the synthetic
stage-order memo diagnostic at
`runtime_qualification/local_memo_harness/2026-10-03-stage-order-finite-phases-9b-v2/`.
The exact replay of the prior blocked v1 run reused draft/correction responses,
then completed typed ledger, local review and renderer checks in four finite
phase passes. `result.json` records `workflow_state: accepted`,
`render_validation: pass`, `review_status: pass`,
`acceptance_scope: local_model_checks_only`, and
`independent_review: pending`. This is a synthetic diagnostic, not an accepted
investor memorandum or investment recommendation. The v1 failure remains
preserved. The first local-material diagnostic at
`runtime_qualification/local_material_harness/2026-10-03-stage-order-materials-9b-v1/`
blocked at the intro deck after three model responses repeated an uncited
numeric/date sentence. It produced no deck pair. The generic slide instruction
and validation feedback now require a citation in the same sentence and name
the exact offending slide/sentence on retry. The fresh v2 diagnostic under
the matching `...-materials-9b-v2/` directory also blocked after three intro
responses repeated an uncited numeric/date sentence, despite targeted feedback.
No deck pair was produced. A bounded model-authored single-slide correction
with exact replay was implemented. Its v3 synthetic run repaired one slide,
then blocked on a second uncited date sentence at the finite cap. V4 cleared
the intro deck through model-authored slide patches, then blocked on the pitch
deck when a slide patch omitted missing-financials disclosure. An explicit
pitch-patch instruction and regression were added. V5 again cleared intro in
three responses, but pitch response 6 repeated a risk slide and omitted the
required missing-financials disclosure despite that instruction. It blocked
at the finite cap with no exported pair. An exact intro-response replay and
a more focused pitch patch over the relevant memo sections are being built
for a new diagnostic. V6 exactly replayed the accepted V5 intro with no new
intro model call. Its three new pitch calls still blocked: two spent the budget
on citation placement and the third exposed missing-financials disclosure.
No deck pair was produced. The next refactor is model-authored structured
sentences with typed source IDs and a required model-authored financial-evidence
pitch slide. The first structured v7 run blocked at intro after three attempts:
the formatter initially rejected normal terminal punctuation, and exact replay
under the corrected formatter still failed per-selected-source numeric/date
binding. The punctuation formatter now inserts only citation labels; a fresh
v8 structured diagnostic was blocked by source-specific numeric evidence in
a split memo section; v9's targeted patch repeated the wrong section indices.
The structured contract now lets the model author each sentence and select
source IDs while software binds them to intact supporting memo passages.
V10 at `runtime_qualification/local_material_harness/2026-10-03-structured-source-9b-v10/`
completed both decks in four local 9B responses (intro two, pitch two). Exact
no-inference replay and all three editable/PDF pair checks passed, producing
six diagnostic files (five intro pages, five pitch pages, five memo pages).
`content_layout_status` remains `not_run`; `investor_material_accepted=false`.
Visual review found sparse slides and a tiny/dense memo with uneven pagination.
Further semantic review found a pitch heading/body mismatch and a weak
financial-data disclosure. The structured gate has since tightened, so V10
would now fail that check; keep its original result as historical evidence.
A new finite local-model material review phase and memo layout improvements
are underway. Preserve all v1–v10 raw attempts and caps.

**Tested code:** Durable phases are now `source_selection`,
`financial_analysis`, `draft`, `correction`, `ledger`, `review`,
`material_draft`, `render` with finite caps 3/9/6/3/5/2/6/1. The financial
phase processes at most three explicit tenant-scoped XLSX uploads and records
partial or blocked evidence; it cannot validate financials. Missing or blocked
financial evidence advances the core memo/materials with disclosure. Local
model-authored intro/pitch slide specs replay into editable PPTX and matching
PDF; the memo replays into DOCX and PDF. A synthetic renderer canary and a
combined research/delivery/room/financial/discovery suite passed 631 tests,
5 skipped after the material checkpoint audit, slide-level repair, renderer,
KB date precision and financial uncertainty fix; `git diff --check` clean.
The render boundary now rechecks the accepted memo digest and exact recorded
slide response projection before artifact registration; the research/delivery
audit suite passed 519 tests, 5 skipped. The broad release suite, real company
quality, workbook reconciliation and exact investor-material reviews remain
open. Claude Code contributed the generic financial reconciliation and private
worker code through its VS Code extension, using synthetic-only fixtures.

**Financial live diagnostic:** A synthetic hidden-input workbook was processed
by the installed 9B. Its original run
`runtime_qualification/workbook_reconciliation/2026-10-03-private-worker-9b-v1/`
blocked after three responses because the validator treated a model question
about *whether* results were actual as a positive actual-results claim. A
narrow uncertainty-clause fix passed 82 financial tests, and an exact copy of
the saved raw responses replayed without inference under `...-v2-exact-replay/`
to `partial_evidence`. It still records `financial_validation: not_established`,
`workbook_recalculation: not_performed`, and independent review pending. This
does not reconcile or validate the private Toffee workbook.

**Public KB live pilot:** An explicit offline backfill processed 11 retained,
rights-approved StartupDB versions. After accepting source year/month date
precision, a read-only check found 23 funding observations across six company
projections. All event completion statuses are unknown, so all six current-stage
projections stay `unknown_completion` and none establishes a completed round.
MCA Company Master Data remains a disabled, rights-gated import candidate.

**Next actions:** Finish and test separately capped local-model material review
before artifact registration, then run a fresh bounded synthetic material
diagnostic under the stronger gate. Inspect exact six exports and semantic
content. The renderer now has improved 16:9 visual hierarchy
for four layouts, but LibreOffice editable-PPTX conversion and Toffee-level
visual parity remain unqualified. Continue private financial acceptance only
through isolated local processing. Do not relabel synthetic local checks as
Toffee-level quality or independent acceptance.

## Latest 3 October bounded room phase slice

**Next action:** split the finite analysis work into correction (at most three
passes) and separate bounded typed-ledger/review phases. The v6 case shows
that six model-authored field repairs plus four mapping batches cannot reliably
fit a shared three-pass analysis clock. Keep every cited assertion in the
ledger, preserve exact source replay and cap each new phase. Then run a fresh
synthetic stage-order case through ledger, review and renderer replay. Do not
continue a failed diagnostic past its recorded cap. Independently review any
eventual local pass before investor material acceptance.

**Tested code:** Room jobs now have finite, lease-fenced source-selection,
draft, analysis and render phases with caps of 3/6/3/1 passes. Each pass keeps
the 120-second room bound and five-call private-model budget; analysis still
has at most three correction passes. The total attempt number remains a
monotonic audit counter, and migrated legacy jobs retain the old three-total-
pass cap. Draft-only memo execution saves Part A/B responses against exact
company, source set and as-of date; analysis-only preflights those saved raw
responses and cannot call a draft model. The worker advances through durable
phase checkpoints without redrafting after resume. The acceptance role check
now accepts the frozen challenge model. The synthetic evaluation harness can
exercise separate draft and analysis caps. Research, delivery and room tests:
487 passed, 5 skipped after compact draft replay, retry binding, bounded
component-call scheduling, and expansion from 16 to 32 fully mapped
structured-cited assertions. `git diff --check` is clean. No data was altered
to create an answer.

**Live acceptance:** A fresh all-9B synthetic stage-order run at
`runtime_qualification/local_memo_harness/2026-10-03-stage-order-phase-split-9b-v1/`
saved draft parts in two passes and reached the analysis phase, but blocked
after five total passes. The model repeated an unchanged Diligence Plan
timeline patch three times; typed ledger, review and renderer were not
reached. A generic repair prompt was broadened so any section without both
disputed sources may omit the financing narrative and keep supported claims.
The fresh v2 run in the matching `...-v2/` directory did not test that prompt:
Part A took 97 seconds, and Part B timed out in each of its two remaining
draft passes. It ended `awaiting_input` at the finite draft cap. Both runs
remain diagnostic, with raw attempts preserved and no investor material
accepted. This phase split fixed the previous whole-job budget collision, but
the installed model has not cleared full live memo acceptance. A v3 run with
an 8K Part B context did not reach Part B: Part A timed out twice at 105
seconds and the saved-attempt retry cap blocked the third pass. The raw v3
output is in the matching `...-v3/` directory. Current refactor work is
splitting the model-authored draft by section with exact response replay. The
v4 compact run saved all Part A sections but spent short-window timeouts on
following sections and ended at its then-three-pass draft cap. The v5 compact
run, with a start-time guard and six finite draft passes, saved all six
model-authored sections and entered analysis. It blocked at
`challenge_coverage_incomplete` before mapping because 26 cited assertions
exceeded the old 16-assertion batch cap. That cap was raised to 32 with all
assertions still required. No investor material has been accepted. The v6 run
finished `awaiting_input` at the third analysis
pass with `challenge_pending`: it saved all six draft sections, six short
field repairs, one timeline patch and two mapping responses (one further
mapping attempt timed out). It did not complete the typed ledger, review or
renderer replay. Raw v6 attempts and pass budgets are preserved under
`runtime_qualification/local_memo_harness/2026-10-03-stage-order-compact-9b-v6/`.

## Latest 3 October full-draft checkpoint

**Tested code:** The complete-record quote rule now asks the local model to
quote the full structured JSON record for a numeric or dated claim when that
record fits the claim field; validation and the model-authored claim patch
enforce it. A chronology field repair now asks the model to cite each
conflicting entry in its own clause, or remove financing discussion from a
product, market or execution section whose claims do not cover the pair.
`.venv/bin/python -m pytest -q tests/research tests/delivery -p no:cacheprovider`
passed 463 tests, 5 skipped, and `git diff --check` passed. These are code
checks, not document acceptance.

**Live acceptance:** A fourth fresh synthetic structured full-draft run at
`runtime_qualification/local_memo_harness/2026-10-03-full-draft-stage-order-conflict-9b-ledger-v7-run4/`
still ended `needs_resume` after the third 105-second pass, at
`timeline_patch_pending`. The first model-authored chronology patch did cite
the two conflicting entries separately and had no recorded semantic rejection,
but other chronology targets, typed-ledger challenge, review and renderer were
not reached. No memo or investor material was accepted. The saved raw attempts
and blocked result must remain intact. The run's two draft calls took about
66 and 94 seconds; it also needed three short prose repairs. The current
whole-memo three-pass envelope is insufficient for this structured case even
after claim-quote repairs were eliminated. Next implementation slice: split
durable draft preparation from the bounded correction/challenge/review budget
with an explicit finite stage cap, while preserving exact response replay and
the room's no-repeat-on-reopen behavior. Do not relabel run4 as accepted or
extend a failed run beyond its cap.

## 3 October battle-test checkpoint: tested code versus live acceptance (latest)

This section is newer than the one below. Nothing here is an accepted memo, a
quality sign-off or a promoted artifact; every live result is a software-scored
diagnostic on synthetic sources with `independent_review: pending`.

**Tested code (project `.venv`, research + delivery suites: 463 passed, 5
skipped; `git diff --check` clean).**

- `agents/research/evidence_ledger.py` (contract `evidence-ledger-v7`): typed
  key/value facts with exact spans and source hashes; the model labels each
  cited prose span, the prose after a field's last citation, and each
  structured claim row with a field and a polarity (`not_reported`, `reported`,
  `unverified`, `verified`, `current`, `ambiguous`); software compares labels
  with the facts. Direct conflicts: a reported value called absent; financing
  called verified, closed or received while the record's own status is unknown;
  a stage called the present stage on a record dated before the as-of month or
  undated. Everything else is an explicit `unresolved_*` or reviewer-required
  row. A record must name the company (or carry a validated binding, which
  `Source` does not yet have) to prove a conflict.
- Dated stage history: typed events from structured records, plus events the
  model extracts from prose, kept only with an exact excerpt holding the stage
  label and a real calendar date, an entity inside the excerpt, and completion
  only where the excerpt affirms it. An empty or unavailable history is not
  proof and cannot let a present-stage claim through.
- `agents/research/staged_memo.py`: conflicting prose and claim rows are
  rewritten by the local model through bounded recorded tasks, then re-labelled
  and re-compared; a surviving conflict or incomplete coverage returns
  `blocked` before review. Review contract `source-review-v4` separates
  blocking findings (must bind to exact memo and source text; an unbound one
  gets one retry, then `blocked`) from advisory notes (diagnostic only, never
  rendered). Invalid or twice-timed-out reviews block. Calls that cannot finish
  in the remaining pass time are not started (mapping, review, claim patch).
- `agents/research/investment_memo.py`: `renderable_sections` now replays
  claim patches (it never did, so any accepted memo that needed one could not
  be rendered), the ledger binding and the stage history. `validate_memo`
  rejects claim assertions carrying `[S#]` markers and memo text that refers to
  drafts, corrections, "fields" or a "source set". Prose may state a number
  that sits in a typed fact inside the cited claim's exact quote of a
  structured record.
- Drafting contract: for a structured JSON record that fits in a quote, a claim
  whose assertion states any number or date must quote the complete record.
  This is in the draft prompts, the `Claim.quote` description and
  `validate_memo`; a truncated quote is repaired through the existing claim
  patch, whose only choice for a structured record is the whole record. Number
  validation is unchanged. The draft prompts also require a citation in every
  prose field, placed at the end of its clause and not stacked.
- Timeline and claim patches, like mapping and review, are not started when the
  pass cannot finish them, so a cancelled call no longer uses up an attempt.
- Harnesses: `scripts/evaluate_local_memo_harness.py` (true full draft) now
  records model options, replays the renderer, requires a complete conflict-free
  ledger record, and cannot report a review of an invalid memo as a pass.
  `evals/local_model_battle/` runs paired synthetic cases; its `memo_flow`
  suite injects the fixture memo as the draft (labelled
  `fixture_injected_stimulus_not_model_generated`) and then runs the real
  `run_stage` for up to three passes.

**Live `qwen3.5:9b` results (all under ignored `runtime_qualification/`).**

Injected-draft stage runs (`local_model_battle/2026-10-03-stage-*`), one pair
each. These are not full generation.

| Pair | Latest run | Result |
| --- | --- | --- |
| reported vs verified amount | `stage-verified-amount-9b-v6` | 9/9; overclaim removed by ledger rewrite |
| reversed chronology | `stage-chronology-9b-v6-run2` | 9/9; removed by timeline patch on its third and last attempt |
| stale listing vs newer notice | `stage-stale-listing-9b-v8` | 13/13; `stage: current` on a 2023-05 listing corrected to dated wording. v6 and v7 failed and are preserved |
| reported amount called absent (prose, claim) | `ledger-absent-amount*-9b-v4*` | passed under ledger v4 only; not rerun on v7 |
| distinct entities, missing finances, contradictory source | not run | no live result |

True full-draft runs (`local_memo_harness/2026-10-03-full-draft-*`):

- `sparse-conflict-9b-ledger-v5`: stage accepted in three passes; original
  `result.json` says render failed (the claim-patch replay bug) and is left as
  written. `render_replay_after_fix.json` records a model-free replay to 8
  sections. All three sources are prose, so no typed fact was reconciled.
- `stage-order-conflict-9b-ledger-v7`: did not reach the reviewer. All 15
  drafted claim assertions carried `[S#]`; the repair needed two long claim
  patches and two calls timed out.
- `stage-order-conflict-9b-ledger-v7-run2` (after the draft prompt forbids
  markers in claim assertions): zero markers, no timeouts, still
  `needs_resume` after three passes. Drafts took 53 s and 79 s; pass three
  spent its five calls on one claim patch and four prose rewrites. Every
  structured claim quoted a 63-67 character prefix of its record.
- `stage-order-conflict-9b-ledger-v7-run3` (complete-record quote contract):
  8 of 8 structured claims quoted the complete record and no claim patch was
  needed. Still not reviewed: three prose fields pooled dates from two sources
  before one citation and were rewritten, then the timeline patch was blocked
  (`retry limit exhausted`): one call started with eight seconds left and was
  cancelled, and two answers were identical and rejected for
  `investment_thesis`. The time guard was added after this run and has not
  been exercised live.

**Not established.** No model-generated memo over structured sources has
reached review within three passes. The 9B event extraction returned an empty
list for a plain dated notice in two runs. The draft still pools numbers from
two sources before a single citation, which forces per-field prose rewrites,
and the timeline patch repeats a rejected answer at temperature 0.
Review-driven field revision has run only against scripted doubles. Reviewer
advisory notes are often wrong. New profiles written by
`delivery/investment_memo_stage.py` freeze a `challenge` role; an older saved
profile that omits it falls back to the review model by design.

## 3 October reconciliation refactor: tested code and bounded live result

The option-number memo challenge was replaced by a versioned typed evidence
ledger. The installed local model maps each cited prose sentence and each
reader-visible structured claim assertion to a field and reporting polarity;
software compares that mapping with exact, hashed source key/value spans.
Direct conflicts trigger bounded, saved local-model rewrites of the prose or
claim assertion, followed by re-mapping, re-comparison and a compact review
of the exact final memo. The renderer replays the response and ledger binding.
Malformed, unbound or timed-out blocking review output cannot pass. Drafting
process language in final prose is rejected. No real company conclusion was
written by Codex or Claude Code; source values were not altered.

**Tested code:** `.venv/bin/python -m pytest -q tests/research tests/delivery
-p no:cacheprovider` passed 425 tests, 5 skipped; `git diff --check` passed.
The claim-row regression verifies that a false assertion remains in the saved
raw draft but cannot appear in rendered accepted text. This is a focused suite,
not the full release suite.

**Live synthetic acceptance for this slice:** the installed `qwen3.5:9b`
passed three fresh bounded defect/control runs. The claim-assertion pair at
`runtime_qualification/local_model_battle/2026-10-03-ledger-absent-amount-claim-9b-v4/`
passed 1/1 pair and 15/15 checks: the model changed the false rendered claim
to an exact source-reported amount and left the control unchanged. The
prose-assertion pair at `2026-10-03-ledger-absent-amount-9b-v4/` and its
independent repeat `2026-10-03-ledger-absent-amount-9b-v4-run2/` each passed
1/1 pair and 15/15 checks. Earlier v1/v2 failures and the v3 passing score
with a reader-quality leak remain preserved as counterexamples. All scorecards
say `independent_review: pending` and `diagnostic_only_no_promotion`.

**Still open:** broader company-disjoint and multi-sector live evaluation,
complete local draft-to-render acceptance, private financial reconciliation,
reviewed investor materials, and independent human review. The active public
KB still has only six rights-reviewed StartupDB records/11 versions; MCA and
other candidate feeds are not enabled. No model weights were changed. Do not
interpret these three synthetic pairs as investor-material or release
qualification.

**Additional production-path trials:** `memo_flow` injects a fixed synthetic
draft, then runs the production local challenge, corrections, review and
re-review through the bounded passes. It is explicitly recorded as
`fixture_injected_stimulus_not_model_generated`. The reported-versus-verified
defect/control pair at
`runtime_qualification/local_model_battle/2026-10-03-stage-verified-amount-9b-v5-run2/`
passed 1/1 pair and 9/9 checks; the earlier v5 trial failed because the 9B
repeated a too-short correction. The chronology pair at
`runtime_qualification/local_model_battle/2026-10-03-stage-chronology-9b-v6-run2/`
passed 1/1 pair and 9/9 checks after the earlier v6 result's "timeline field"
workflow language was rejected. These are local-model trials on synthetic
drafts, with independent review still pending; full model-drafted company
materials and other defect classes remain unqualified.
The accepted chronology rewrite used its third and final allowed attempt.
Review-driven field revision passed scripted tests but has not run live; the
passing verification case was repaired earlier by the ledger challenge.
Stale listings, distinct entities, missing financials and conflicting sources
remain untested live under this contract. The earlier amount pairs were run
under ledger v4, before the current v5 verification/chronology changes.

## 3 October focused local-model challenge: tested code versus live acceptance

Claude Code implemented and Codex reviewed a production memo challenge that
judges every cited prose assertion in at most two bounded local-model batches.
The memo blocks with an explicit coverage record before review when any cited
assertion lacks a valid judgment; the renderer replays that coverage and the
exact saved response binding. A generic option-consistency check now rejects
and retries a defect reason that quotes or names a different evidence option
than the one the model selected. Software never supplies a replacement verdict
or option. The versioned diagnostic harness is in `evals/local_model_battle/`.
`.venv/bin/python -m pytest -q tests/research tests/delivery -p no:cacheprovider`
passed 372 tests with 5 skipped; `git diff --check` passed. These establish
tested code only.

The one live synthetic `qwen3.5:9b` defect/control pair is retained at
`runtime_qualification/local_model_battle/2026-10-03-focused-absent-amount-9b-v1/`.
It failed: 0/1 pairs and 7/11 checks. On the defect, the model said
`contradicted` but selected the status option while its reason quoted the
amount option; the software-bound evidence was wrong. On the control with no
amount field, the model falsely called the correct uncertainty statement
`contradicted`, after two overlong rejected answers. The new consistency
check was added after this run and has offline regression coverage; its live
recovery behavior is untested. A full draft-to-review run under the three
pass limit has not yet been accepted. Neither Codex nor Claude Code authored
company conclusions or investor material. No Toffee data or model weights
were changed. Weight adaptation remains an option only after a reviewed,
company-disjoint corpus and a measured baseline justify it.

A fresh bounded pair under
`runtime_qualification/local_model_battle/2026-10-03-focused-absent-amount-9b-v3/`
also failed: 0/1 pairs, 5/8 checks, one answered defect case and one blocked
control. The new check rejected the first defect response for quoting the
amount option while selecting status. Its retry mentioned only the quoted
amount value and still selected status, exposing a narrower binding gap. Codex
added generic structured-scalar consistency validation and a regression after
this run; 30 focused tests pass. The control exhausted three saved attempts
(two overlong responses, one timeout) and blocked with incomplete coverage.
The scalar check itself has no fresh live acceptance yet.

## 3 October local-model battle-test checkpoint

The user explicitly permits weight adaptation if evidence shows it is needed;
Codex and Claude Code must not author any company discovery or investor-material
content. The Mac is an M5 with 16 GB unified memory; installed `qwen3.5:9b` is
a 6.6 GB Q4_K_M Ollama inference GGUF. MLX/PyTorch/PEFT/TRL/Transformers and a
compatible training checkpoint are absent. The current training seed has only
8 synthetic train and 2 validation examples and is unreviewed, so no LoRA or
model download has run. First establish a company-disjoint reviewed baseline.

An isolated local 9B challenge probe on the previous synthetic false-pass memo
is retained at `runtime_qualification/local_memo_challenge_probe/2026-10-03-false-pass-v1/`.
It returned five mostly broad omissions, missed the direct within-source
reported-amount contradiction, and targeted an unrepairable claim field. A
new `evals/local_model_battle/` harness with synthetic counterfactual pairs
was coded by Claude Code; its first 9B case under
`runtime_qualification/local_model_battle/2026-10-03-challenge-9b-v1/` failed
schema after a verbose answer and also over-flagged supported uncertainty.
The 14-case background run was stopped after that one recorded case. The
focused implementation and paired trial are described in the checkpoint above.

## 3 October challenge orchestration checkpoint

The live public KB registry contains six enabled rights-reviewed StartupDB
company-detail records and 11 indexed versions; one Wikidata record is
disabled. The live SQLite registry has no refresh-policy/job rows yet and ES
was not listening in this environment. MCA Company Master Data, Startup India,
startups.gallery and announcements are candidates, not active KB feeds.
Product discovery has a conditional KB search, but the new reconciled
`compare_public_candidates` gate is currently called only by tests.

Claude Code in VS Code implemented a distinct local-model memo challenge role
in the production worker and diagnostic harness. It checks complete retained
passages against the exact source-bound draft, records field-specific issues,
replays bounded model-authored field revisions and binds the challenge to the
final review and renderer replay. Codex reviewed the wiring and added a frozen
challenge model profile for new memo jobs; old profiles retain their saved
roles. This is role separation, not a second trained model by default. The
project environment passed 353 research/delivery tests (5 skipped).

A fresh three-pass synthetic 9B trial is retained at
`runtime_qualification/local_memo_harness/2026-10-03-stage-order-challenge-v1/`.
It ended `needs_resume` at `timeline_patch_pending`: draft/claim repairs used
the bounded passes, so neither challenge nor final review ran. No live model
quality or human acceptance is established, and no artifact was promoted.

## 3 October implementation checkpoint (current turn)

The public KB now has per-source 6/12-hour leased refresh policies, durable
jobs/events, rights-gated observed-link outcomes, a hash-checked 304 guard,
append-only structured StartupDB funding claims, and a source-reported current
stage projection. The focused public KB/candidate suite passed 45 tests;
the broader investment-memo plus KB/candidate/harness suite passed 129 tests. Claude
Code in VS Code authored six synthetic two-connection scheduler tests; the
shell CLI had no separate login. No source beyond the prior rights-reviewed
StartupDB records was enabled and no live source-traversal acceptance ran.

A fresh synthetic `stage_order_conflict` local 9B memo trial used its three
bounded passes and ended `needs_resume` after reviewer `revise`. Source binding
passed, but the local draft's unknowns called source-reported financing order
"chronologically impossible". The timeline validator missed it because it
searched an entire two-sentence unknown as one span. This validator now catches
that false resolution; the regression test passed. No fourth pass was run, no
memo was accepted, and the diagnostic remains ignored under
`runtime_qualification/local_memo_harness/2026-10-03-stage-order-slice/`.
The Toffee originals were not changed or sent to hosted inference. Its
historical workbook reconciliation is not the current work target.

Two subsequent fresh synthetic 9B trials tested the prompt/timeline and
reviewer-contract changes. The last trial got a local reviewer `pass` and
source-bound harness result, but independent agent inspection rejected its
exact memo: it described a reported amount as missing, inferred capital
activity from unverified listings, and exposed renderer/fixture language.
The raw accepted diagnostic remains intact. A separate ignored
`independent_review.json` records rejection and the exact memo digest. New
generic validators block absent-amount contradictions and internal workflow
language; the saved memo now fails validation. A fresh bounded synthetic trial
under `runtime_qualification/local_memo_harness/2026-10-03-stage-order-validation-v3/`
also received a harness `accepted` and local reviewer `pass`, but independent
inspection rejected the exact memo: S3 reports an amount, while the memo says
that source does not establish the amount. Its ignored `independent_review.json`
records the exact memo digest and rejection. The validator now checks structured
and string-valued reported amounts, so this saved memo fails validation. The
generic draft prompt also distinguishes a reported amount from verified closing
or cash receipt. These final changes passed the 129-test focused suite; no
new live trial has qualified them. No investor artifact was released.

Public KB corrections that remove a funding entry or change the publisher's
reported domain now demote the old current projection while retaining history.
An inactive approved link target waits for an observed parent link before its
first scheduled fetch; failed/fetched link outcomes append events. Elasticsearch
was not listening during this turn, so no live collector traversal was run.

Next: make all admitted structured/HTML announcement evidence source-bound,
resolve identity and claim semantics across publishers, integrate complete
bundles and stale/overdue state into both discovery and rooms, then run a new
bounded local-model acceptance after the reviewer-field correction path can
handle unknowns and claim defects. The current scheduler has no active
unattended timer; local 9B and private artifact release remain unaccepted.

Read `AGENTS.md` first for privacy and working rules. Section 0 of
`LOCAL_TO_CLOUD_RELEASE_PLAN.md` is the detailed contract. Use
`SESSION_HANDOFF.md` only when investigating prior failures; its older scope
statements are historical.

## Product and current truth

The product researches startups worldwide, performs company due diligence
before evidence-backed investment suggestions, and prepares investor materials
for fundraising. The user's brief sets geography, sector and stage. India
pre-seed/seed is a pilot regression case, not the product scope. A discovery
shortlist is a lead queue, not an investment recommendation.

New web runs now accept any geography or none and use
`global_research_v1`; the India policy remains for saved pilot runs. This
scope plumbing passed 115 focused tests and the frontend build. Live worldwide
discovery, reconciled company history, investment-quality diligence and the
six-file investor package have **not** passed acceptance.

## Do the next vertical slice

1. Inspect uncommitted changes, retained failed reports, live jobs and data
   before editing. Preserve originals, SQLite, archived responses and failures.
2. Implement rights-approved, bounded directory → company profile → official
   site → announcement traversal. Persist every observed link and decision,
   including blocked/skipped/failing links, parent version and reason.
3. Make the 6-hour announcement and 12-hour directory/profile/official refresh
   a durable leased schedule. Show overdue/failed status. A failed fetch or
   search-index outage must not advance a successful cursor.
4. Persist append-only, source-bound identity and dated funding/status claims;
   reconcile conflicting reports and amount semantics into a current projection.
   A newer Series A must supersede an old Seed listing without deleting history.
5. Wire discovery to the complete reconciled company bundle, applying only
   the user's restrictions. Keep unknown/conflicted candidates unresolved.
   Then build the reviewed diligence dossier gate before any positive
   investment suggestion. The dossier needs identity, funding/status history,
   product, market, team, finances, risks, opposing evidence and unknowns.

Use synthetic permitted-source fixtures first, then one rights-approved live
publisher. `startups.gallery` remains a candidate source pending rights review;
LinkedIn is an observed-link lead unless authorized access is established.
Codex and Claude Code CLI may collaborate on sanitized generic code and tests;
installed local models alone author company conclusions. No private inputs to
hosted inference. No model downloads, cloud spend, reset or commit.

**Acceptance:** two identical schedule ticks do no duplicate work; every link
has a durable outcome; newer evidence changes current status and invalidates
dependent bundles; outages retain history; a contradicted/evidence-thin case
cannot get a positive suggestion; exact citations and review revisions match.
Report tested code separately from live accepted behavior. Continue toward the
intro deck, pitch deck and investment memo (each editable plus PDF), with
projections only when supplied or explicitly requested with sufficient inputs.
