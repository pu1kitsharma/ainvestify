> **Latest, 30 October:** read [DEAL_DOCUMENTS_V2_PLAN.md](DEAL_DOCUMENTS_V2_PLAN.md) before any deal-documents work. The Toffee memo run was stopped on purpose, with finished steps saved; do not resume it. Milestone 1 and the company page are done. Milestone 2 (thesis, exhibits, code-computed readings) is next. Private documents on AWS still need the owner's explicit decision.

# Next agent: local diligence and investor materials

## Latest: 28 October — tracked runs, typed meaning checks, compliance gate

The deal-documents workflow is now stateful and visible in the room UI.
`delivery/deal_documents/runs.py` keeps one run per room in the app database
(`deal_document_runs`): phases, steps with start/finish times, measured-time
ETA, events, approvals bound to the output SHA-256. `pipeline.py` runs each
phase as tracked steps whose outputs are cached under `RUN/steps/<phase>/`, so a
restarted phase resumes after the last finished step. `scripts/deal_documents_worker.py`
claims queued phases (lease + heartbeat; an expired lease re-queues, three
interruptions fail the phase). API: `api/routers/deal_documents.py`
(`/api/rooms/{room}/deal-documents` status, `{phase}/start|cancel|approve`,
`memo` review view, `memo/compliance-signoff`, whitelisted draft `files/{name}`).
UI: `frontend/src/components/DealDocuments.tsx` in the room materials view,
plus a one-line `DocumentProgress` on each My companies card.
`scripts/deal_documents.py register` attached the existing Toffee run1 (facts
phase approved as "claude-initial-review (operator to confirm)").

Meaning errors were the main quality failure (e.g. "Revenue rose from USD 1.46 Mn
in FY22 to USD 1.16 Mn in Q1-FY23", "73.33% annualized growth" for a year vs a
quarter). `semantics.py` now owns meaning in code: typed calculations
(growth/multiple/cagr need the same metric, segment, unit and period length,
later after earlier; share/ratio/difference one period; sum one period or
consecutive quarters; convert needs an exchange-rate fact). Code labels each
result and fills `{c1}` placeholders, so the model never types a computed
number. Sentence checks reject change words on single-period ratios, "annual"
on non-annual changes, literal quarter-vs-year comparisons, projections/targets/
run rates stated without a projection word in the sentence, third-party figures
without attribution and swapped metrics (premium/revenue, policies/customers).
Run over the old run1 draft they found 21 such errors that had passed.

`compliance.py` is a code gate (not legal advice): assurance and public-offer
language, unresolved validation problems, information age (>12 months fails),
an ICDR-heading disclosure checklist (use of proceeds, litigation, related
parties have no source facts → fail until supplied or waived) and questions for
counsel (Companies Act s.42/PAS-4, sector licensing, FEMA, DPDP, preparer
registration). Front notices (confidentiality/no public offer, basis and date of
information, forward-looking statements, no advice/conflicts) are rendered into
the memo. Memo approval needs the owner AND a compliance sign-off from an
operator-provisioned `auth_reviewer_qualifications` compliance reviewer (India);
an `approved` sign-off must waive every failing check with a reason.

Live-run corrections (28 Oct, Toffee run1): sentences that still fail a hard
check are pruned (recorded in `removed_sentences`, shown in the UI) instead of
shipping; rejections name comparable periods ("compare Q1-FY23 with Q4-FY22");
a ratio/share/growth placeholder cannot sit in a money phrase ("USD {c1} Mn");
ratios/shares must be one segment (or a segment's share of its total); a rate
word (margin, take rate, share) on an "x" ratio is flagged; fact/calc ids in any
bracket form, ranges and bare ids are stripped; mentions of reviewers/notes/the
fact base are flagged; a number typed next to its own placeholder is flagged;
thin sections (<55% of budget) and mostly one-sentence paragraphs go to
revision; units around placeholders are not doubled. `memo.revalidate` re-checks
cached drafts and revisions under current rules at assembly. Reviewer changes
that propose a figure found in no fact or calculation are not passed to the
writer (`unverified_number`; one fact-checker "corrected" INR 1,000 Mn/75 to
USD 133.3 Mn). Critic and compliance retry once without thinking if the
reasoning call degenerates; a second compliance review runs on the final memo
and its areas/findings join the gate as counsel items. First drafts have no
repair call; the single revision pass (with one repair) handles code problems
and reviewer notes together. Revision prompts list narrative facts plus only
the tables the section cites or covers.

Memo attempt 2 (28 Oct, backed up in `run1/attempt2/`) was not approvable. Errors
it shipped, now caught in code and pruned: "USD 4.20 Mn in Q1-FY23, up from
USD 0.61 Mn in FY22" (the earlier figure was uncited, so same-series facts are now
looked up in the index); "USD 5.08 Mn [12 months] exceeding USD 1.73 Mn [Q1]"
(comparison words `COMPARE_WORDS`; a table "Total" column over consecutive quarter
columns is now the span it covers, `semantics.fact_period`); "FY23" naming the
12 months to Sep-23 (`_fiscal_label_problems`); a Margin/Revenue share called
"EBITDA/gross/net margin" (`NAMED_MEASURE`); "USD 17.94 Mn is understated" with
the direction wrong (over/understated needs a convert or difference calculation);
"70.02 INR/USD INR/USD"; drafting instructions copied from reviewer fixes ("The IM
should clarify…", "Flag FEMA…"); a model-written disclaimer asserting "no conflict
of interest" (notices are code-owned; the compliance reviewer now sees them);
repeated sentences; "(TID-p14.1 says '…')" residue; filler words inside quotes
from the company. The fact-checker had overruled verified human findings (rotated
segment labels) and the writer applied it: the fact-checker and critic now get the
human notes and the revision prompt says human findings win. Human-note list
numbers ("13.", "16.") no longer count as allowed figures. Attempt 3 reuses the
cached first drafts (the write-step key excludes the system prompt).

Memo attempt 3 (backed up in `run1/attempt3/`) fixed those classes but was not
approvable either. New misses, now caught in code: a revision typed a calc's value
("net margin of 0.30x") instead of `{c2}`, which skipped every per-calculation check
(`semantics.restore_placeholders` now puts placeholders back before checking); a
sum called "the remaining 29.35%" (`REMAINDER_WORDS` needs a difference calc);
+190% growth from Q3-FY22 to Q1-FY23 skipping Q4-FY22 (+58.9%) (growth whose gap
is neither one period nor 12 months must state its span, `SPAN_WORDS`); "Reviewer
findings note…" / "The reconciliation notes…" (META_REFERENCE); a phrase from the
human notes quoted as the deck's words (`memo.unsourced_quotes`: quoted phrases of
2+ words must appear in some fact); "The sum of these…" after its antecedent was
pruned (POINTS_BACK); "{cites:,,-notes.5}" residue (CITE_MARKUP). Not caught in
code, left for human review: "PhonePe" called a direct digital insurer, "MGA/faculty
model", "dated October 2022" vs "undated" elsewhere, repeated stale-date sentences
across sections.

Architecture change after attempt 3 (pipeline `deal-documents-v4-code-written-evidence`):
detect-and-prune had become whack-a-mole, so evidence is now written by code. Every
period figure and calculation reaches the memo only as a placeholder-only sentence;
`semantics.compute` returns `sentence`, a complete evidence sentence built from the
facts' own metric names, periods (`_when`: "in the 12 months to Sep-23"), basis verbs
("is projected at") and code-computed direction ("fell", "USD 1.20 Mn more than the
conversion"). New kind `figure` states period figures. The model selects evidence and
writes interpretation sentences without period figures
(`memo.evidence_form_problems`); `strip_ids` inserts the full stop in "{c1} {c2} Text".
The step cache key now includes the model. `DEAL_DOCUMENTS_PARALLEL` (default 1)
runs section drafts, fact-checks, critic+compliance and revisions in a thread pool;
`OLLAMA_NUM_PARALLEL` must be raised with it and each slot needs its own context
cache. `DEAL_DOCUMENTS_CALL_TIMEOUT` (default 900 s between streamed chunks) must be
raised for dense models on CPU. Model candidates on this host (24 GB RAM, 6 GB VRAM):
`qwen3.8:latest` is a dense 27.3B with hybrid attention and fits the 40k context;
dense `qwen3:32b` does not (full-attention KV cache ~10 GB at 40k on top of ~20 GB
weights). Decode on CPU is memory-bandwidth bound (~40 GB/s): expect ~2 tok/s for 27B.

Run-time measurements (28 Oct, qwen3.8 27B on this host): prompt reading ~84 tok/s, generation
1.25 tok/s (87% of call time; MTP speculative decoding is already on, ~85-90% acceptance).
Hybrid/recurrent models cannot reuse a partial prompt prefix ("forcing full prompt
re-processing"), only an exact extension, so the repair prompt extends the revision prompt.
The fast 35B MoE failed the code-written-evidence contract in a five-section A/B (projections
kept 39 words, historical 24) and is not used for writing. Speed changes kept: revisions and
repairs return edits only (`memo.apply_patch`); writer prompts use short ids (`memo.Aliases`,
mapped back before validation, map stored in each call record); `DEAL_DOCUMENTS_NUM_GPU=14`
(Ollama's fit put 3/66 layers on the 6 GB GPU; 14 measured +15% with identical weights); the
check profile uses the writers' num_ctx so Ollama does not reload the model between steps.
Rankings are code-written (`rank` kind; `memo.RANK_WORDS`/`COMPARE_FIGURES` stop the model
ranking figures itself) after the 27B mis-ranked segment margins. A memo rerun moves old
outputs to `superseded/<time>/` and rewrites memo.md after each section as an IN PROGRESS view.
Single-stream speed is hardware bound: more RAM adds parallel slots (DEAL_DOCUMENTS_PARALLEL
with OLLAMA_NUM_PARALLEL) and larger models; only GPU VRAM makes a dense model fast.

The host shut down unexpectedly at about 01:10 IST on 29 Oct (Kernel-Power 41, no bugcheck, cause
unknown) with 17 of 30 memo steps saved; the worker was restarted on 30 Oct and resumed from them.
A worker started from a session's background shell ends with that session.

Decks were rebuilt on 30 Oct and are NOT yet staged or run with the model: stage them only after the
memo is approved, then restart the worker (it holds the old modules). `decks.py` writes each slide
alone from the approved memo sections it summarises, under the memo's checks (`validate_section(...,
shape=False)` plus `slide_problems`), with two repairs. Code draws charts and tables from source
cells; `fact_chart` plots one period kind only, so totals and run rates stay out of a trend. The
intro deck is a subset of the reviewed pitch slides. Slides are shaped like memo sections so
`fact_check`, `compliance` and `compliance.assess` read them unchanged; `review.deck_critic` is the
banker/VC reviewer. `deck_render.py` replaces the generic renderer for these decks: PowerPoint first,
PDF converted from that file by soffice, Calibri/Carlito. Check rendered slides as images
(`pdftoppm`): tests passed while real slides still showed fact ids in table cells.

First drafts on 30 Oct read as a diligence critique, not an IM, so every section now gets a full
revision held to `memo.voice_problems` (`[voice]` in the notes forces the rewrite; `REVISION_BRIEF`
replaces the summary brief, because `SECTIONS` text keys the saved drafts). `question` paragraphs
leave the investor documents and go to `open_items.md`, for the company to answer before release.
Stage deck-rebuild-v7 is live in the worker; decks have still not run on the model. The API needs a
root restart before `open_items.md`, `decks.md` and `deck_compliance.md` appear in the room.

Added 30 Oct, tested with fake models only until the run reaches them. `questions.py`: code collects
what to ask (failed calculations, stale data, missing disclosures, review notes, analyst findings,
writer gaps) and an asking agent merges them; confidence comes from `EVIDENCE`, never from a model.
Answers become `ANS-p*` company-statement facts and revision notes. `questions.readiness` is the
code-computed meter, capped by open blockers and the missing compliance sign-off. `climb.py`: rounds
of rewrite, fact-check and investor score (`DEAL_DOCUMENTS_CLIMB_PASSES`, default 2; target 85);
a candidate is kept only if better, accuracy before score. `DEAL_DOCUMENTS_REVIEW_MODEL` gives the
checking agents their own model (`qwen3.6:35b-a3b` here). The 30 Oct phase-1 observation "shareholding
sums to 60.69%" is wrong (the listed holdings sum to 100.00%), which is why analyst findings are
capped at 70. Timer: saved steps keep their seconds, elapsed counts worked time, the range widens
with possible rounds. On one Ollama slot the agents take turns; they run at once only with
`DEAL_DOCUMENTS_PARALLEL` above 1 and `OLLAMA_NUM_PARALLEL` or `DEAL_DOCUMENTS_ROUTES` to match.

Measured on this host (qwen3.6:35b-a3b, 6 GB RTX 2060): section draft ~4–7 min
(prefill ~130–190 s for 15–24k tokens, decode ~9–11 tok/s); fact-check
10–90 s (was ~5 min each with thinking); critic ~8 min; revision ~4 min plus a
repair that reuses the prompt cache (~26 s prefill). A full memo phase is about
2.5–3 hours on this GPU, versus 5+ hours before; the floor is decode speed.

Speed: compact prompts (table rows on one line), fact-check without thinking
(`check` profile; every old fact-check hit the 12k-char thinking cap), review
thinking budget 8k chars, revision only of flagged sections (reviewer notes plus
remaining code problems). The worker's systemd unit is
`deployment/local/investify-deal-documents.service`; installing it needs root
(not done by the agent — the worker ran as a session background task).

## 27–28 October phased deal-documents workflow (Toffee live run)

The room pipeline cannot take a real data room: `delivery/worker.py` blocks any
room with more than 25 source passages (`complete_diligence_inventory_exceeds_local_capacity`);
Toffee's deck, intro and workbook produce 497. A new operator workflow,
`delivery/deal_documents/` + `scripts/deal_documents.py`, runs on a room's
ingested documents in three human-gated phases (each approval binds the exact
output hash; a changed output must be re-approved):

1. `facts` — position-preserving PDF text (pdfplumber layout) + local OCR +
   page image to the vision model `qwen3.6:35b-a3b`; code detects numeric
   tables (side-by-side tables split by indentation) and transcribes every cell;
   the model only interprets column periods/basis/units and row metric/segment.
   Workbook summary cells are transcribed by code. Every model fact must quote a
   value printed in its block (scaled k/Mn/Bn and ranges allowed) or have most
   content words present; wrong-block citations are corrected to the supporting
   block and OCR-only support is flagged. Typed cross-checks (same_value,
   conversion, components_sum, difference, ratio_view) are proposed by the model
   and computed by code with printed-decimal rounding tolerance; code also checks
   table segments vs totals and shareholdings = 100%. `recheck`, `reevaluate`
   redo validation/checks without re-extraction.
2. `memo` — 12 IB sections; each paragraph cites facts with a quoted phrase
   that code verifies; every number must be a cited value or a code-computed
   calculation; banned filler words and word budgets enforced; one repair call.
   Reviewers: per-section fact checker, IC critic, India compliance reviewer
   (dated public reference notes, framed as questions for counsel); one revision.
3. `decks` — pitch and intro decks from the approved memo; table cells come
   from phase-1 table facts.

Model client (`llm.py`): streaming with repetition-loop stop and JSON salvage,
thinking budget with a bounded non-thinking finish, every request/response
recorded under `RUN/calls/`. Measured: ~1.5–4 min per page with vision.

Live Toffee run: `/home/investify/private/deal_documents/toffee/run1/`
(private). Room `workspace_eeba2e3041b0` / `deal_e98ff1e8aff7` in the owner
sandbox (created via an operator-approved temporary session). Phase 1: 488
verified facts, 43 rejected, 365 workbook cells; checks found the cap-table USD
figures converted at ~70 not the stated 75 INR/USD, an EV TAM unit error,
revenue above gross premium in FY22 quarters, and "no direct competitors" vs
named competitors. Claude's initial review (`phase1_review_claude.md`) adds the
2022 information date, premium-based ARR, rotated segment labels between intro
and workbook, and corrects false model observations. Phase 1 approval is
recorded as "claude-initial-review (operator to confirm)".
Failures fixed during the run (kept in the call records): an empty answer on a
230-cell table, a 6,000-token repetition loop on a title slide, chart labels
mapped to the wrong axis without the page image, arbitrary citations, and the
whole-findings list hijacking the company overview. 21 offline tests in
`tests/deal_documents/`.

## Latest: 27 October user decisions — 30B-class local author, 15-minute steps

User decisions this session (they supersede conflicting rules below):

- **Fully local.** Private documents stay on this machine. The author must be a
  local model of at least 30B, using GPU VRAM and system RAM together. The user
  said Claude will review generated artifacts; whether that includes private
  figures is unconfirmed, so don't send private material to Claude until they
  confirm.
- **The seven supplied references may be used as examples/training material.**
  They therefore no longer count as unseen acceptance tests; measuring
  improvement needs a fresh, untouched deal.
- **Private document steps may run up to 15 minutes.** Interactive discovery and
  preparation keep 120 seconds.

What changed on the machine:

- `%USERPROFILE%\.wslconfig`: memory 8→16 GB, processors 6→10, swap 8 GB,
  `autoMemoryReclaim=dropCache` (backup `.wslconfig.bak-20261027`). WSL now
  sees 15 GiB / 10 CPUs. WSL was restarted with zero running jobs/leases after a
  verified SQLite backup (`/home/investify/private/backups/app-20261027T182901Z-pre-wsl-resize.db`,
  quick_check ok, 24 tables). Both supervisors were relaunched with their
  Startup-shortcut arguments; local and public health returned 200.
- New Ollama models: `qwen3:30b-a3b` (18.6 GB) and `qwen3.6:35b-a3b` (22.6 GB),
  both mixture-of-experts with ~3B active parameters. A synthetic 8K-token
  benchmark (no private data) measured:

  | Model | Load | Prompt | Output | Placement |
  | --- | --- | --- | --- | --- |
  | qwen3:30b-a3b | 62 s | 260 tok/s | 10.3 tok/s | 21% GPU / 79% CPU |
  | qwen3.6:35b-a3b | 55 s | 137 tok/s | 11.7 tok/s | 13% GPU / 87% CPU |

  A dense 32B would be ~1–2 tok/s here. `qwen3.6` needs `LocalModel` prefix
  support (≈19 `qwen3:`/`qwen3.5:` checks) before use; `qwen3:30b-a3b` works
  with existing code. These are latency numbers, not quality acceptance.
- `server.env` (backup `server.env.bak-20261027T190610Z`): `DOCUMENT_STEP_SECONDS=900`;
  `LOCAL_MEMO_{AUTHOR,REVIEW,DRAFT,PART_B,CHALLENGE}_MODEL` and
  `LOCAL_MATERIAL_DRAFT_MODEL` = `qwen3:30b-a3b`. Preparation/discovery models
  are unchanged. API and room worker restarted at 19:06 UTC with zero active jobs.
- Code: `document_step_seconds()` / `document_model_seconds()` and
  `PreparationBudget(..., document_step=True)` in
  `agents/preparation/preparation_budget.py`. The room worker pass, job lease,
  model IPC relay, isolation, memo/content/source-unit/material/review/repair/
  financial stages and their private workers follow the configured step.
  Defaults remain 120/105 s when the variable is unset. Frozen diagnostic
  contracts (reference-generation 105 s, relation review, compare workers) and
  Office inspection (≤120 s) are intentionally unchanged. Staged 21 files with
  previous-manifest checks and backups:
  `/home/investify/runtime/code-stage-document-step-900-20261027T185421Z-cbf5c83d/receipt.json`.
  WSL suites: 3,350 passed; the failures were environment-specific (Apple
  Vision OCR, sandbox font policy on `/mnt/c`, a CRLF-checkout fixture hash,
  and a 20 ms timing test that passes on native disk).
- Training runtime: `/home/investify/train-venv` (torch 2.8.0+cu126,
  transformers/peft/trl/bitsandbytes/datasets/accelerate). CUDA and an NF4
  4-bit layer run on the RTX 2060; freeze at `/home/investify/train-venv-freeze-20261028.txt`.
  No base checkpoint was downloaded and no training ran.

Still open: no room contains the supplied references (the live DB has four
synthetic documents), so no end-to-end generation with the new author has run.
The 6 GB GPU cannot QLoRA-train the 30B author; a 4–8B QLoRA is possible but
seven documents teach format, not judgment. OCR table reconstruction, workbook
reconciliation, reviewer reliability and visual parity remain as described below.

## Latest: 27 October public preliminary discovery — three matches, partial run

The repaired preliminary finder is now live and verified through the actual
Chrome owner Google sign-in and Retry search on the original unmodified brief.
It created `source_run_ead46f340149` from `source_run_d148153f58fe` and displayed
**CRED, Lentra and Paytm**. This is **three preliminary matches, not the requested
20**: the run is explicitly partial after **120.033 seconds and six model calls**.
The sixth additional-page call was cancelled at its remaining 20.987-second
allocation. Preserve the original failed run; its raw-row SHA remains unchanged.

The live evidence audit verified literal spans, parent source hashes, each
company's own evidence, company-bound title/country proof, role-specific evidence
IDs and publication dates. `assessment=None`, current status `not_verified` and
financial assessment `not_performed` remain explicit. Historical 2023/2022/2021
source vintages are visible, not presented as current operations or financial
periods. Evidence:
`/home/investify/runtime/public-discovery-evidence-audit-20261026T224357Z-9b03d28e/report.json`.

Discovery's V3 `OWN_GEOGRAPHY` source-match branch passed **164 native tests**.
The new isolated V3 integration passed **361 tests, one explicit Office skip,
40.803 seconds**. The branch
requires a new recorded local-model match response with exact company/product/
geography and explicit-criterion evidence. It performs no financial assessment
and must not rescue old rejected assessment fields. The earlier V2 isolated
integration passed **359 tests, one Office skip**; that older result is not the
V3 qualification. The coordinator staged 31 repair files into 1,183 manifest files
with previous-file/manifest checks and backups. Pre-final-documentation manifest:
`469468772c64ec5c468883799d495bf2622a384df2649ee3704f9d191610b28b`.
Receipt:
`/home/investify/runtime/repair-code-stage-20261026T223911Z-6cfd4797/receipt.json`.
Final documentation staging will have a later receipt/hash; do not treat the
pre-documentation hash as self-referential proof of these updated files.

Frontend build/lint passed and live asset `index-CkV2puP3.js` was verified. Both
API/room-worker services are active. Before the coordinated restart, the online
backup's 24-table checks and SQLite quick-check passed with zero active jobs.
Eight anonymous public routing checks passed. The separate 8B review branch is
**outside this 31-file runtime snapshot**: `agents/research/document_generation.py`,
new `agents/research/bounded_material_review.py` and
`tests/research/test_bounded_material_review.py`. Its 140 native regression
tests passed with zero skips, including 16 new tests. The one authorized actual
probe failed at its shared **105.01-second** budget (**107.115 seconds total**),
using one logical call/two transport requests. Phase one retained the full 6,628
input tokens and generated its bounded 256 reasoning tokens; `done_reason=length`
was allowed for that phase. The final phase's 900-token allocation produced no
terminal response, token counts or answer body before the deadline. No valid
review/`REVISE` or patch was accepted. The full 78-unit/four-page evidence and
exact 1,185-character draft were preserved; 27 API security properties and 11 live
file hashes remained unchanged. The model used context 8,192, 28 GPU layers and
batch 128, with 4,746,641,407 bytes of observed VRAM, and was unloaded afterward.
Private evidence directory: `review8b-thinking-b195bdaa3e`. No further probes are
authorized in this checkpoint; the branch is not a deployed or qualified critic.

Material hardening passed **111 tests, one skip**. A single 1,185-character IM
section completed its author step; same-model, non-independent review returned
`REVISE`, and a contradicted-support check failed. No complete or accepted intro
deck, pitch deck, investment memorandum or matching PDF package exists. An actual
14B full-context review produced no response in **105.113 seconds** while GPU
utilization reached 96% and observed use was 5.274 GB. This is a bounded capacity
observation, not a semantic quality verdict or an accepted independent review.

Corrected-profile confined OCR transcribed the 37-page reference in **22.686
seconds**, with **21 native OCR/manifest checks**; evidence remains at
`/home/investify/private/ocr_qualification/2026-10-27-b5d4d05441`.
The earlier 19.443-second output is retained as historical raw evidence, not
adopted under the corrected pins. OCR remains proposed/unreviewed and establishes
neither financial accuracy nor table/claim reconciliation. The actual workbook
audit was `blocked_before_office`: 104 stored errors, 22 broken formula references
and two broken defined names, plus the separately recorded missing/unsupported
reference findings. No actual recalculation or forecast validation occurred.
Metadata: `/home/investify/private/workbook_qualification/2026-10-27-7db511acce/report.json`.

New source-use permission is recorded, but all seven supplied references overlap
three existing acceptance families (five byte-identical originals and two
declaration-only versions). The immutable family ledger/review packets are at
`/home/investify/private/training_preparation/2026-10-27-seven-v1/`; no independent
new training family or adjudicated training target was established. **Zero rows
are weight-update eligible; no weights were updated.** Training checks passed 62
tests. Actual hardware remains 6 GiB GPU VRAM, approximately 24 GiB Windows RAM
and 7.76 GiB visible to WSL training. No 32B model is installed; larger local
diagnostics and packed-MLX compatibility limitations remain recorded privately.
Two Claude Code reviews covered sanitized code/task designs only; private source
text, gold, model responses and financial answers were not sent to Claude.

## Verified hosting baseline: 27 October authenticated public workflows

**https://investify.fyi now serves authenticated private workflows.** This
supersedes the older auth-only/503 and disabled-worker observations below and in
handoff section 82. See [section 83](SESSION_HANDOFF.md#83-27-october-authenticated-public-workflows-and-final-host-qualification).
At that verified checkpoint the WSL API was active (observed PID 7030), and
`investify-room-worker.service` was active and enabled. The outbound supervisor used `-Mode private-workflows` and
the full `Caddyfile.tunnel`; its backed-up Startup shortcut has that mode verified.
Reboot remains untested. Inspect actual jobs/leases before any restart.

Checks passed: 513 backend tests, 47 live loopback privacy checks, ten anonymous
public smokes, 35 authenticated public checks, and 15 frontend session tests plus
build/clean lint. HTTP acceptance used temporary production-factory sessions for
existing Google-verified users; a separate fresh Chrome Google callback reached
the final bundle and logout restored Continue with Google. Preserve real users,
sessions and labelled synthetic fixtures. Public HTTP evidence:
`/home/investify/runtime/public-http-isolation-20261026T192851Z-67184ee2dc/report.json`.

The actual isolated 9B extraction canary passed in 20.111 seconds. One bounded
room source-selection pass took 2.181 seconds, used zero model calls/IP egress
and indexed six synthetic passages; its fixture job was then cancelled before
further work. Missing formula caches still block financial computation. These
checks do **not** establish final financial/material/model-quality qualification.
Training remains unqualified with zero eligible rows and no weight updates.

Cloudflare remains authoritative (`grace`/`salvador`). To bridge stale ISP
delegation caches, the old Porkbun apex now points to Cloudflare edges
104.21.31.42 / 172.67.174.243, preserving mail. Cloudflare terminates public TLS;
router ingress was not required. The recorded Linux manifest before the final
final documentation/source stage is
`1ecaa8c951984e9ef5d2e07e7053873e00d941aa66acb7a70100cca1c5adbba0`.
The final coordinator stage includes these handoffs and
`scripts/qualify_live_http_isolation.py` / `scripts/qualify_public_http_isolation.py`;
inspect `/home/investify/runtime/code-stage-final-handoff-*/receipt.json` for
the resulting manifest and snapshot freshness.

## Historical: 26 October public sign-in, GPU and PDF recovery

This continuation supersedes the earlier checkpoints below; see
[SESSION_HANDOFF section 82](SESSION_HANDOFF.md#82-26-october-gpu-inference-pdf-export-and-outbound-route-continuation).
The API remains WSL `investify-api.service`, loopback 8000, without a room worker.
Windows Caddy serves `http://127.0.0.1:8080`; API health and frontend HTTP 200
passed after checked PDF/GPU staging and zero-active-job restarts. Preserve the
private database, uploads and all original/failure evidence. No trainer or
collector was started. **https://investify.fyi now serves the frontend and Google
sign-in publicly**, through an outbound tunnel. Private API routes remain 503;
full private workflow/two-user isolation acceptance and investor release remain
unfinished. Do not equate successful sign-in with completed product qualification.

The actual GPU is an RTX 2060 with **6 GB VRAM**, with approximately 24 GB system
RAM. Ollama 0.40.11's default qwen3.5:9b placement loaded 19/34 CUDA layers and the
multimodal projector; one diagnostic spent 58.22 seconds loading and 32.70 seconds
prefilling only 20 tokens. Explicit, measured placement materially improved speed:
the same 503-token structured control fell from 21.02 to 8.92 seconds. The active
opt-in `LOCAL_OLLAMA_HARDWARE_PROFILE=rtx2060-qwen35-9b-v1` applies only to this
model: batch 128, 33 GPU layers through 2,048 context and 31 through 16,384;
larger contexts fail closed. Existing model roles/defaults and the 120-second /
six-call budget remain. A real LocalModel/bubblewrap/Unix-socket streaming canary
processed 5,786 prompt tokens plus 30 output tokens in 16.88 seconds, with normal
stop and exact boundary markers. A separate 14,438-token stress prompt completed
in 35.42 seconds but produced a wrong sum/unfinished prose. Preserve that failure;
latency recovery is not financial or semantic qualification. Models were unloaded
after testing. Staged inference tests: 132 passed, one skipped. Evidence paths
and Windows/platform-specific failures are in section 82.

LibreOffice 24.2.7's initial-page `/OpenAction` caused the PDF rejection. The
exporter now omits it at generation using explicit static PDF options, retains
accessibility tags and disables embedded originals/forms. The validator is
unchanged and still rejects `/OpenAction`. Isolated intro/pitch/memo PDF pairs
pass structural, text and page checks. Old/fixed intro and memo rasters are
pixel-identical. A five-page memo preserves all 20 bounded paragraphs, and
visible/hidden XLSX formulas recalculate correctly. Focused staged tests: 22
passed. Broader delivery suite: 662 passed, eight skipped, four failed on existing
Apple Vision/macOS sandbox assumptions; full Office/OCR, visual review and
exact-file investor acceptance remain open.

The expanded private training audit supersedes the original eight-file/532-row
inventory: **74 JSONL files / 1,552 rows** contain 156 memo candidates, 376
exclusions, 152 scorer keys, 152 synthetic fixtures, 470 trajectories, 180
protocol events, 65 unqualified chat/text rows and one reward record. All 156
memo candidates pass runtime/source/schema checks but are explicitly test-only
and pending adjudication; 494 duplicate rows are recorded across the inventory.
**Zero rows are eligible for weight updates.** Do not train on holdouts or promote
scorer keys, failed responses or tool traces into answers. Outside-Git storage,
audit and training policy fixes were staged with 57 passing native tests;
`code-stage-training-8c5f8bb3a5b3` holds the staging receipt. No training or adapter
activation occurred. Review/rights, corpus splits and compatible base/runtime
qualification remain required.

The operator-owned Cloudflare route works without router administration. Normal
OS DNS, without overrides, verified public HTTPS frontend/assets 200, API health
200/exact `ok`, auth config 200, anonymous auth/me 401, private API 503 and secret/
upload/model paths 404. HTTP redirects 301 to HTTPS preserving the path; the
certificate verifies and CF-Ray is present. All ten smoke requests passed;
receipt: private `hosting/network/public-domain-smoke.json`. Cloudflare Universal
certificate is Active, Always Use HTTPS is enabled, minimum TLS is 1.2. Cloudflare
now provides authoritative DNS; the old parking A records were replaced with the
proxied named-tunnel CNAME. MX/SPF/DKIM/Google verification were preserved against
direct authoritative answers. Cloudflare terminates TLS; private uploads are
not publicly enabled. Direct router ingress remains unverified; do not repeat
rejected credentials or reset the router.

The named supervisor owns Caddy 8081, cloudflared and its own WSL keepalive, and
fails closed after three failed API health checks at ten-second intervals.
Both local-preview and outbound Startup shortcuts exist; reboot is untested.
Two real Google accounts signed in through Chrome, provisioning two distinct
owners/sandboxes and two memberships, with zero foreign memberships or reviewer
qualifications. Both accounts logged out: two sessions revoked, zero active.
Receipt: `/home/investify/runtime/public-oidc-acceptance.json`. Full private room/
file/job isolation is not accepted; routes remain 503 and the worker stays off.

User-requested Claude Code 2.1.310 was signature-checked, authenticated with the
existing Pro account, and completed a sanitized generic engineering review in
29.54 seconds. Tools, MCP, skills and hooks were disabled for that invocation;
no private company inputs or training/evaluation content were supplied. Its
receipt is outside Git in private `hosting/claude-code/generic-review` storage.

## Historical: 26 October Windows hosting and archive-import checkpoint

Latest continuation supersedes the installation checkpoint below: Windows has
restarted; Ubuntu 24.04 (`Investify`) is installed in the restricted private VHD.
The active API is now `investify-api.service` in WSL, loopback 8000, with no room
worker. Windows Caddy serves `http://127.0.0.1:8080`; supervisor
`deployment/local/start_local_host.ps1` keeps WSL alive. A current-user Startup
shortcut is installed; its next-login execution is not reboot-qualified.
The active DB is `/home/investify/private/app.db` (0600), with uploads/artifacts
outside the code tree. All 24 original tables were checked during backup/cutover;
Windows originals and checked backups remain. Do not resume the old Windows API
against its historical database; the explicit configured launch paths refuse it.

Implemented opt-in `PRIVATE_MODEL_IPC=unix-ollama-v1`: per-job socket, six-request /
120-second maximum, exact loopback Ollama operations, no management endpoints,
credentials or redirects, cancellation closes upstream even before model output.
Bubblewrap retains --unshare-all and no host network. Final focused Linux suite
passed 263 tests (plus the Windows-specific guard checked separately); 18 native
socket/storage checks passed under the full service restriction set. These are
transport/software results, not full room or investor acceptance. Directory
literals fail closed on Linux to prevent descendant disclosure. LibreOffice
conversion and hidden-cell synthetic recalculation now execute, but PDF output
fails the existing active/embedded-content gate. Preserve that failure.

One explicit synthetic qwen3.5:9b request timed out at 100 seconds. Its request
reached Ollama 0.40.11 (POST /api/chat, HTTP 500); separate isolated metadata
GET tags / POST show passed. No generation retry, model substitution or training.
No model remains loaded. Evidence: `/home/investify/runtime/model-canary-e29c44cb1899/`.
All 532 imported candidate rows remain rejected/held out as appropriate.

The user also cannot sign into the router. IPv4 changed to 101.0.63.189 after
restart; public IPv6 is present but external ingress remains unverified. A
bounded synthetic IPv6 canary used temporary address/port-specific firewall
rules; both were removed, and no public 80/443 listener remains. The external
checker denied programmatic access; do not infer ISP blocking or bypass that
denial. DNS remains Porkbun parking. No public deployment, live two-user OIDC,
worker/collector, cloud spend, commit or push. See handoff section 81 and the
current runbook before resuming.

Earlier installation checkpoint: the loopback preview was running at `http://127.0.0.1:8080`
with no room worker. Google Web OAuth client registration is complete; the API
reports configured=true. Credentials are in ACL-restricted, ignored
`deployment/.env`; the downloaded JSON is outside Git under
`C:/Users/gaura/AInvestifyPrivate/hosting/google-oauth/`. Never print either file.
No live Google callback or two-user acceptance has passed. Microsoft-signed WSL
3.0.3 was installed and VirtualMachinePlatform enabled without an automatic
reboot. Its private installation receipt reports reboot_required=true; no Linux
distribution was installed at that checkpoint. That restart/setup is now complete.

Porkbun's authenticated DNS drawer showed an apex parking ALIAS to
`pixie.porkbun.com`, plus unrelated mail records; no DNS edits were made.
The router login is reachable, but a single attempt with user-supplied credentials
did not establish an authenticated session. The page requests the default
password. Do not guess credentials or repeat the same attempt. WAN IPv4, CGNAT,
inbound reachability and forwarding remain unverified. A fresh checked SQLite
backup is under `runtime_backups/local-hosting/20261026T132832Z-a03066a5/`.
No jobs/leases were active. Inspect actual listeners/jobs after restart; the
preview has no boot task and must be resumed explicitly. See handoff section 80.

The current machine is Windows 11 with approximately 24 GB RAM and an RTX 2060
(6 GB VRAM), not the historical Mac runtime below. See
[local hosting audit/runbook](deployment/LOCAL_MACHINE_HOSTING.md).

Caddy routing and an explicit loopback-only API/UI preview passed; frontend
build/lint passed. Final focused hosting/import/auth/routing selection: 63 passed.
A broader selection passed 67 and failed two existing room tests because private
storage requires POSIX file-handle flags. Private process isolation also has no
Windows backend; Linux bubblewrap still refuses local_model=True. Public release
is blocked by those ports, native Office/KB qualification, live Google sign-in,
router/WAN/CGNAT and live two-user acceptance. DNS/firewall/router were not changed.

Both operator-supplied tar files were verified and imported outside Git under
`C:/Users/gaura/AInvestifyPrivate/imports/2026-10-26/`, with restricted Windows ACLs.
Seven Ollama tags and 23 blobs were added; existing matching files were reused;
zero conflicts or overwrites. The production default models are now installed.
At import time no model was loaded or generated, no new weights were trained, and recovered
adapters were not activated. The private training-assets.json records 532 candidate
rows, all rejected by current gold intake; 156 are explicit validation/test rows,
with zero explicit train rows or two-reviewer adjudications. Keep evaluations and
acceptance inputs held out. Historical repo-local private-training path rules
need reconciliation with the controlling outside-Git storage rule before training.

The earlier bounded preview backed up SQLite and stopped cleanly. The continuation
above supersedes that service-state observation. No public deployment, model
download, training, cloud spend, data reset, commit or push occurred.

## 16 October local software checkpoint

The agentic banker Phase A tool/runtime scaffold is implemented locally with
isolated workstreams. The second checkpoint registers explicit schemas and
executes a fully scripted synthetic workbook → two-slide deck → memo session,
with immutable draft manifests and exact-byte replay. No real model authored
this fixture and no weights were trained. All prior private-material failures
below remain unresolved; no investor release or production room integration
is established. See `evals/agentic_banker/CHECKPOINT_2.md` and
`deployment/AGENTIC_BANKER_LOCAL_EXECUTION.md` for current scope and next gates.

Default pytest now keeps audited live-model/network/server checks opt-in and
reports native sandbox capability denial as mandatory unrun. Offline test results
never establish private isolation or full release acceptance. Do not run live
inference, private inputs, downloads or cloud work from a test command implicitly.

## Current truth — 14 October 2026

**Cloud provider correction:** the user has moved to GCP because AWS was not
approving cost. GCP is the selected private compute/deployment provider; older
AWS proposals are historical. This correction does not establish provisioned
resources, GPU quota, project access or a spend cap. Verify actual GCP state
before scheduling evaluation/training. No cloud resources were started here.

**The end-to-end goal is unmet.** All four new references are retained in private
native manifests; both PDFs have local OCR. Original financial vector text was
recovered without correcting values. Editable table/chart rendering is implemented.

**Live progress:** the 9B completed all 27 original page reads. The smaller local
4B produced a valid eight-page outline in 50.652 seconds. The 9B authored its
first page in 20.235 seconds, but local review rejected two scope claims. No
complete new memo/deck or investor acceptance exists. A source-bound 17×10 visual
matrix also failed spatial review; its bounded repair subsequently timed out.

**Final live result:** V21 reused 29 exact source/plan/author records with zero
new extraction calls. Corrected-scope review rejected two claims. The 9B's one
repair passed binding, but re-review rejected the same two scope issues. This
branch is terminal. Vision V4 also timed out at 105 seconds with no terminal
response. No new investor material was accepted and no weights were trained.

**Stopped at the user's request:** all diagnostic models are unloaded; agents
and tests stopped. Backend/UI remain running. Production defaults are unchanged.
Source-local financial tables and reliable semantic drafting/review remain open.
The new visual literal codec is prepared but untested and unintegrated. Do not
run more prompt variants automatically. Preserve all failed branches and raw records.

Scope: India private startup fundraising documents and internal diligence is the
first regulatory pilot; the product remains worldwide. All company judgments and
prose must come from recorded installed-local-model responses. Codex and Claude
Code implement and audit software; neither supplies company answers. Private
inputs stay local. Documents are data, not instructions. Read AGENTS.md and its
controlling release, financial and public KB plans.

## New reference-generation slice

- `document_evidence_manifest.py` retains original PDF glyph/geometry and PPTX
  text, native tables, chart XML/cache, notes, hidden slides, embedded-payload
  hashes and unfetched external relationships. Original sources are immutable;
  company inventories remain separate. Complete literal retention does not mean
  complete visual understanding. All 22 charts in one supplied PPTX depend on
  external relationships and remain blocked for chart projection.
- `document_ocr.py` uses local Apple Vision with automatic language correction
  disabled, behind a network-denied boundary. Both complete PDFs were read:
  37 pages/881 observations and 35 pages/714 observations. Raw OCR, full rasters,
  source and executable hashes remain private. OCR can lose decimal points even
  at confidence 1. Numeric claims supported only by OCR are now blocked;
  transcription never establishes financial accuracy or reconstructed cells.
- `document_generation.py` and the private stage freeze all source handles,
  choose a model-authored plan, author each page over selected complete evidence
  and run a separate local review. Twelve diligence topics need explicit status;
  prose/quotes/periods/table coordinates must replay exactly. Original cells are
  copied literally, including blanks; code never repairs company answers.
  Intent journals allow one new call per advance, 105 seconds/six HTTP requests;
  failed or unresolved calls remain terminal.
- The explicit mapped catalog traverses every physical page and complete literal
  before planning, retaining image-only pages as visually unassessed. Its fixed
  twelve-topic source-ID selector avoids model-composed quotes; software retrieves
  complete unchanged originals. Per-map profiles and bounds are frozen. Verified
  unchanged successful prefixes can be adopted byte for byte with explicit parent
  provenance and zero new calls; failed rows are excluded. Exact literal read
  capabilities permit lineage replay without granting parent-directory contents.
  Mapping is a proposal, never financial or content approval.
- `complete-page-context-v1` adds a separately pinned local coverage critic,
  recorded topic corrections and exact mapper/critic provenance before planning.
  The planner sees complete original table coordinates and safe context-capacity
  hints; writers/reviewers receive whole same-page literals once. Export displays
  recorded claim basis. Main page-author/reviewer pins remain unchanged. These
  changes remain live-unqualified. Its completed 27-map run omitted substantive
  evidence; the separately pinned 14B critic then failed. Preserve that branch.
- `complete-document-literals-v1` with `complete-literal-context-v2` exposes
  all original literals and two-dimensional native tables directly to planning,
  then retains mandatory page authorship and review. No mapper or coverage critic
  runs. All 780 available literals, 505 native cells and 27 physical pages of the
  fresh reference fit a 37,856-character catalog. Oversized sources explicitly
  refuse; nothing is clipped. Literal exposure does not establish semantic reading
  or financial approval. Old frozen requests stay unchanged.
- Opt-in `native-pptx-visual-text-v1` adds 1,504 original EMF Unicode text
  records and 26 separately tagged SmartArt data/cache strings to the original
  780-unit reference inventory. Raw bytes, fonts, clipping and transform state
  retain exact source bindings; legacy binary documents remain unparsed. No OCR
  guesses or table/financial interpretations are introduced. The new CLI
  reconstructs this derivative from the unchanged native manifest/original.
- `complete-document-literals-v3` uses exact contiguous kind/handle runs and
  numeric cell-handle matrices. Its full 2,310-unit catalog is 44,744 characters,
  below the unchanged 48K bound. All 27 complete page contexts also fit after
  lossless geometry palettes; final combined request limits remain mandatory.
- Optional planner/writer separation uses installed 4B for planning and 9B for
  writing/review, with independent frozen pins. `local-stream-observation-v1`
  retains exact partial output and timings without fabricating terminal counts.
  `compact-anchor-pages-v2` has finite page IDs, bounded evidence handles and
  multiple model-authored topics per page. Writers receive the whole original
  context for every selected page. All versions preserve previous failed bytes.
- Native editable PPTX/DOCX tables and matching searchable PDFs replace the
  previous prose-only layout for this explicit renderer. Supported native PPTX
  charts preserve original caches and an embedded workbook; chart PDF companions
  retain the literal data. DOCX charts are images with editable data tables.
  Synthetic Office exports were visually inspected, including negative bars.
  Financial, embedded-workbook and independent visual qualification remain open.
- `evaluate_reference_generation.py` verifies original/manifest/OCR provenance
  before isolated continuation/export. Exports are explicitly draft-only and
  bind exact bytes and model records. No actual company export was reached.
  This is an opt-in diagnostic; fresh room defaults remain unchanged.
- Claude Code contributed generic journal/orchestration, export-receipt and
  source-ID selector/compiler and complete-page coverage/context implementations
  binary parsing, streaming and compact-plan implementations in ten authenticated coding
  sessions. Codex agents handled
  parsing, rendering and independent acceptance audit. No private source content,
  company answers or gold labels went to Claude or any hosted model.

Details and commands: [reference generation](deployment/REFERENCE_GENERATION.md).

### Fresh reference live results

| Branch | Actual result |
| --- | --- |
| Native PPTX, 9B, catalog V1 | Context integrity failed; output cannot be accepted |
| Same PPTX, 9B, catalog V2 | Full context recorded; plan omitted product status and used header rows as data |
| Same PPTX, 14B, catalog V2 | Cancelled at 105 seconds; empty output, semantic quality unassessed |
| Second company's PPTX, 14B, catalog V2 | Cancelled at 105 seconds; empty output, semantic quality unassessed |
| Second company's PPTX, 9B, complete-page quoted reader | First two maps passed; third exhausted 900 tokens and copied nonliteral joined cell quotes |
| Same source, 9B, fixed source-ID reader | Thirteen maps bind; fourteenth selects blank cells. Two adopted responses plus twelve new calls, no plan/export |
| Same source, bounded reader + separate 14B coverage critic + complete context | All 27 maps completed but omitted facts. First critic made incorrect topic promotions; second cancelled at 105 seconds. 29 records: 13 adopted plus 16 new calls; no plan/export |
| Same source, direct complete-literal plan | Full catalog retained; 9B cancelled at 105 seconds with empty output. One call; no plan/pages/export |
| Same source, lossless compact full-literal plan | Original frames/table navigation roundtrip exactly; 30,326 compact characters. 9B cancelled at 105 seconds with empty output; no plan/export |
| Same source, separate 4B planner / 9B writer and reviewer | Explicit roles frozen; cancelled at 105 seconds with empty output. No plan/export |
| Same source, streaming capacity diagnostic | First output at 42 seconds; 1,979 partial characters/839 chunks at cancellation. No terminal receipt or accepted plan |
| Enriched 2,310-unit source, compact plan V1 | Ended at 43 seconds without a terminal frame. Malformed output stayed in the unbounded page-ID field; no plan/pages/export |
| Same complete enriched source, finite compact plan V2 / 16K | Normal stop, eight pages, 68.38s; prompt count 8,194 matches the overflow cutoff. Blocked before source acceptance |
| Same source, finite compact plan V2 / explicit 32K | Normal stop, 60.98s, 18,278 input / 805 output tokens. Topic coverage contradicts itself; invalid sequential unit IDs and table coordinates. No pages/export |
| Same source, finite physical plan V3 / 32K | Normal stop, 90.25s, 23,099 input / 1,264 output tokens. Repeated tables, headers used as body and every topic assigned to every page. No pages/export |
| Native financial page, 4B vision / 16K | Runtime refused 18,167 required tokens; empty output |
| Same full financial page, 4B vision / explicit 32K | Normal stop, 58.03s, 18,184 input / 163 output tokens. Partial header and contradictory unassessed status; no accepted matrix |

V2 removes duplicated handle/hash metadata, with each original handle retained
exactly once. It is an explicit frozen encoding; V1 historical bytes are unchanged.
The two 14B attempts establish a bounded capacity failure, not a semantic verdict.
The 9B V2 planner saw only 40 of 1,394 source units; its errors do not establish
model capability after complete source traversal. All failed branches and raw
receipts remain intact. No author/reviewer/export stage followed a failed plan.
Independent review of the new reader found financial qualifier and omitted amount
issues. Downstream authors/reviewers receive originals and must judge them;
valid bindings alone cannot resolve those semantic issues.
Independent audit and supplemental audit are in the ignored private directory
`runtime_qualification/private_acceptance/2026-10-14-reference-independent-audit-v1/`.

## Runtime qualification scope

The parser/OCR boundary, contracts and synthetic renderer were checked separately
from the failed live plans. Exact results and final process/byte checks are in
[SESSION_HANDOFF §76](SESSION_HANDOFF.md#76-14-october-private-reference-ingestion-and-evidence-document-generation).
The API has not been reloaded with this slice; the new private CLI uses fresh
code. No room worker, new jobs, model download, training, paid action, commit,
push or data reset was performed. Check actual processes before any restart;
preserve the two queued jobs and all concurrent uncommitted work.

## Earlier implementation, with defaults held

- `financial_evidence_manifest.py` and the isolated financial stage retain every
  nonempty workbook cell, formulas/caches, dates, hidden structure, names and
  dependency findings. Exact range/dependency retrieval fails rather than
  clipping. Proposed local-model annotations cannot author values or approve
  forecasts. Cached reopens verify bytes and room/job/revision without reparsing.
- The original supplied workbook passed the read-only parser check: **3,596
  cells, 3,008 formulas, 14 sheets (five hidden), 786 richer packets**. Originals
  remained unchanged. Dependency coverage is partial; semantics unassessed,
  reconciliation unresolved and recalculation unperformed. This is retention,
  not complete financial understanding. The earlier 314-packet archive is intact.
- The opt-in `room-v63-source-quotes` bridge builds private workbook sidecars
  before text selection, excludes flattened spreadsheet rows from narrative
  sources, freezes financial scope in source/profile/replay hashes, and blocks
  missing or changed indexes. It remains FLOW11/coverage19 with 21 checkpoints
  and fixed source interpretation v3. **This failed profile is not enabled by
  default.** Initial memo-cards-v13 remains narrative-only; later coverage/core
  stages receive the supplied-workbook/unassessed scope.
- Separate source tasks now record a local-model quote/topic response followed
  by a local-model kind response bound to the first raw answer and full source.
  Coverage20/FLOW12 has 25 fixed pair checkpoints, one selector and 15 core
  checkpoints: **41 total**, at most 50 assessment model calls plus the selector.
  Each pair stays within 105 seconds/six HTTP requests. Intent journals prevent
  unknown/failed calls from being repeated. Only a crash after a committed first
  response can resume the unread second task within the unused cumulative budget.
- Pair1 is the frozen fast default for this explicit diagnostic contract. Pair2
  uses genuine bounded thinking only for extraction (1,024 reasoning + 700 final
  tokens) and fast kind selection (700 tokens); both stage settings are frozen.
  Client-format argument receipts and native transport bindings replay exactly.
  These receipts do not attest serialized HTTP bytes or server grammar behavior.
- **Fresh production rooms still default to `room-v62-explicit-topic-status`,
  FLOW10/coverage18, 21 checkpoints. No room-v64 or FLOW12 production default is
  enabled.** Historical prompts, options, raw failures and replay remain intact.
- Frontend supports workbook retention/pending-interpretation status and optional
  41-phase progress. It never presents retained cells or model checks as approval.

Implementation/retrieval detail: [private financial index](deployment/PRIVATE_FINANCIAL_EVIDENCE.md).

## 13 October source-reading regression — failed

All fresh profiles used the same frozen ten fictional cases, with gold outside
inference. They are now known regression cases, not unseen-company proof.

| Configuration | Matches / executed | Result |
| --- | --- | --- |
| 9B atomic source quotes v2 | 2 / 3 | Omitted explicit product evidence; seven unrun |
| 14B atomic v2 and wording v3 | 9 / 10 each | Misread an explicit evidence-limitation question |
| 14B evidence-first v4 | 9 / 10 | Extracted the question but still labelled it heading-only |
| 14B consistency grammar v5 | 2 / 3 | Omitted product evidence; seven unrun |
| 14B separated fast Pair1 | 2 / 3 | Omitted product evidence; seven unrun |
| 14B separated thinking Pair2 | **1 / 2** | Tagged contact address as substantive identity; eight unrun |

The final Pair2 independent audit confirmed exact source/proposal/schema/pin,
actual format receipts, four model calls/six HTTP requests and normal stops.
Its two bounded passes took 46.388 and 57.684 seconds. The failure is semantic,
not an established truncation, timeout or evidence-substitution failure.
No further model variants or private inference followed.

Final ignored evidence directory:
`runtime_qualification/local_semantic_canary/2026-10-13-separated-thinking-14b-v2/`.
Audit SHA256: `f55ac22c4457e65cc3dfc1131ef81870c80e11f6fa93ea430f80ae17daa62efd`.

Private v64/v65/v66 diagnostic branches were **prepared but never inferred**.
Only v64 retained eight exact replayed old source-unit prerequisites, with a
separate provenance record; no old classifier/selector/core answers were copied.
Historical V43 memo/V22 exports remain drafts below the benchmark. No fresh
company prose, deck, chart, projection or financial/regulatory signoff exists.

## 13 October verified code and runtime (historical)

Separate software results: source interpretation 42 checks; paired contracts ten;
workbook manifest/stage 20; inference transport/context 77; earlier room integration
190 plus a financial-scope guard; FLOW12 orchestration three plus a Pair2 metadata
case. Counts overlap and must not be added. Frontend build/lint passed. Signed-in
browser/PDF viewer acceptance remains unrun. Final focused compatibility and
runtime results are in SESSION_HANDOFF §75.

The final combined compatibility selection passed **27 checks, 43 deselected**
in 30.96 seconds. `git diff --check` passed. The updated API was loaded after a
consistent SQLite backup: PID75183, API/UI HTTP200 at 01:01:27 UTC. Job counts
remain 22 awaiting input, three blocked, four cancelled, two queued, zero running
and zero active leases. Ollama has no loaded models and no task inference,
training, tests or room worker remains active. Runtime/backup receipts are in
SESSION_HANDOFF §75; inspect current processes before acting on these old PIDs.

Before inference stop competing models/tests/builds. Before any API restart check
active jobs and back up SQLite. Preserve both queued jobs; run
`scripts/serve_local.py --local-dev --without-worker` without reload. Task models
were unloaded after the final failed profile. No model download, training, cloud
spend, commit or push occurred. Preserve all shared uncommitted work and failures.
Claude Code was authenticated and contributed generic coding/orchestration across
multiple sessions; it did not receive private company material or gold answers.

## Next action and required inputs

Change the capability/adaptation plan before more prompt/schema experimentation.
The tested installed configurations have not met even the source-reading gate.
Build an independently adjudicated multi-company corpus for memo writing, evidence
selection and review; source approval alone does not establish gold labels. Keep
these known canaries and private acceptance cases out of training. A stronger
private local model or fine-tuning requires a measured capacity plan; the earlier
9B LoRA attempt exceeded this 16 GB Mac. No larger model is downloaded and no
training is running. Cloud compute requires a user-provided spend cap.
A spend-cap question was sent previously; no answer or paid action is recorded.

India financial and legal/compliance owners still need named professional roles.
There is no complete reviewed current rule matrix, real qualification grant or
exact-file signoff. Regulatory sources remain unreviewed/incomplete. No new MCA
company dataset or public KB source was enabled this turn. Do not imply India
regulatory approval or broad discovery coverage from the pilot source registry.

Details: [SESSION_HANDOFF §75](SESSION_HANDOFF.md#75-13-october-complete-workbook-index-and-separated-source-tasks).
Review requirements: [India compliance](deployment/INDIA_PRIVATE_MATERIALS_COMPLIANCE.md).
The original 1,074-line handoff remains byte-for-byte in
`runtime_backups/2026-10-10-concise-handoff/`.
