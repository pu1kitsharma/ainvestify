# Private reference reading and document generation

## Status — 14 October 2026

The four supplied references are private acceptance inputs. Their structure
informed generic engineering; their text is untrusted evidence, never instructions
or automatically approved training labels. No private content enters Claude Code,
hosted inference or the public KB.

**Implemented:** complete source inventories, local PDF OCR, evidence-led planning
and page author/review journals, exact-cell editable tables, supported native PPTX
charts and matching PDF rendering. Complete-page maps exposed semantic omissions
even after finite ID decoding was added. The separate coverage critic then made
incorrect topic promotions and timed out. The new explicit full-literal flow
gives the planner every available original paragraph and native table cell
directly, without that preliminary semantic filter. Its first 9B plan timed out;
the new positional-frame encoding reduces metadata overhead losslessly.
Binding checks do not establish content quality. No complete new company memo/deck or investor approval has been
established. No weights were trained.

Fresh rooms retain `room-v62-explicit-topic-status`. This reference flow is an
explicit diagnostic CLI, not a frontend feature or a qualified release route.
The running API was not restarted for this slice.

## Source boundary

`agents/research/document_evidence_manifest.py` and
`scripts/private_document_manifest_worker.py` retain:

- PDF native text with geometry, detected table cells, page and visual inventory.
- PPTX paragraphs, group/shape coordinates, native table cells and merge flags,
  complete chart XML and cached literals/formulas, notes and hidden slides.
- Embedded-payload hashes and external relationships, without executing payloads
  or fetching dependencies.
- Tenant/deal/document binding, original SHA256 and immutable unit/table IDs.

Retrieval returns complete requested literal units within explicit bounds or
fails. Unpacketized/unsupported units are reported. Retained native text excludes
unreadable image content; a detected empty table is not a populated financial
table. Geometry and chart retention do not establish interpretation.

An isolated manifest job contains `source.pdf` or `source.pptx` plus `request.json`:

```json
{"source":"source.pptx","binding":{"tenant_id":"PRIVATE_TENANT","deal_id":"PRIVATE_DEAL","document_id":"PRIVATE_DOCUMENT","source_sha256":"ORIGINAL_SHA256","format":"pptx"}}
```

The canonical directory is mode 0700 and files mode 0600. Run the worker through
`delivery.isolation.run_private`, with network disabled. It writes
`document_evidence_manifest.json` and `document_manifest_receipt.json`. References
from different companies need separate deal IDs and must not share an inventory.
The CLI accepts these isolated receipts, not arbitrary pasted manifests.

## Local OCR and numeric integrity

`delivery/document_ocr.py` compiles generic Swift code before any private input
is supplied. Private processing then runs two sequential, network-denied passes:
complete PDF rasterization and CPU-only Apple Vision recognition. Automatic
language correction is disabled. Neither worker receives broader source access.

Each run retains the original, full-page rasters, image inventory, native request,
raw observations and executable/request/output hashes. Reopen validates and
replays them without recognition. `replay_document_ocr` independently reconstructs
page observations from the raw output and checked raster inventory. Derived OCR
manifests are new immutable files; native manifests are never overwritten.

Independent inspection found dropped decimal points even at confidence 1. OCR is
`source_transcription_unreviewed`; it does not reconstruct qualified table cells.
Generation blocks numbers/dates supported only by OCR unless quoted non-OCR
evidence independently covers them. It preserves the erroneous raw transcription
for review and never guesses a correction. Financial accuracy remains unestablished.

Actual private reading retained 37 pages/881 observations and 35 pages/714
observations. All four source originals remained unchanged. Full receipts and
private findings stay under ignored `runtime_qualification/private_acceptance/`.

## Native text inside vector images and SmartArt

Explicit `native-pptx-visual-text-v1` preserves native EMF Unicode text records,
original record offsets, fonts, transform state and clipping, plus separately
tagged SmartArt data and drawing caches. Glyph indexes and unresolved encodings
stay unsupported; legacy binary Office embeddings are retained, not executed.
This does not reconstruct financial tables or establish rendered visibility.
Microsoft's [EMF specification](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-emf/)
and [SmartArt relationship specification](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/66cc6c59-45c6-438e-82ba-7d67de771f68)
guide the native parser.

The isolated worker preserves its original manifest and appends
`document_evidence_manifest_visual_text.json` with a matching immutable receipt.
CLI reopen checks the native/original/parser hashes and independently reconstructs
the derivative. The private canary recovered 1,504 EMF records and 26 SmartArt
strings: 2,310 units total. Original bytes and the default 780-unit manifest remain
identical. Complete inventory, not bounded packets, is the generation input.

The enriched catalog originally exceeded 48K characters. Additive
`complete-document-literals-v3` encodes contiguous kind/handle runs and numeric
cell handles with explicit decoding headers. All original strings, locations,
physical pages and table grids/geometry remain bound. It fits at 44,744 characters;
reconstruction verifies all 2,310 IDs/literals. Lossless font/transform/rectangle
palettes also retain all 1,504 original EMF placements within complete page
contexts. Group fit does not waive the final combined request or token limits.

## Compact planning and exact streaming diagnostics

`--planning-schema-profile compact-anchor-pages-v2` supports multiple local-model
topics per page and at most four evidence anchors per page. Writers/reviewers
receive all original literals on every anchored physical page, including qualifiers
outside those anchors. Software projects recorded compact field names into the
canonical plan; it never substitutes company text or a raw model record.
Finite page IDs and native table IDs plus bounded source handles prevent the
unbounded identifier failure found in the preceding V1 live run. Old V1/default
schemas and failed records remain unchanged.

`--streaming-transport-contract local-stream-observation-v1` preserves exact partial
output, first-content timing, observed chunks, EOF/error diagnostics and actual
terminal metadata. Partial output is always blocked. Prompt/generated-token
counts require a real terminal frame; no count or completion is invented after
cancellation. The generic two-token runtime canary verified normal terminal
delivery only, not private source or document acceptance.

The current explicit full-source run uses dense V3, compact-plan V2 and separately
pinned 4B planning/9B writing and review. Its acceptance is pending. No weights
were trained and no complete new investor package is approved.

## Durable local model flow

1. Freeze the complete source-handle inventory and installed author/reviewer
   digests. Twelve diligence topics require explicit supported, limited or missing
   status; company-specific headings and judgments remain local-model authored.
2. In explicit `complete-source-maps-v1`, a local reader examines every complete
   available literal unit on every physical page first. It records exact source-ID
   selections (or legacy literal quotes), accounts for all twelve topics, and keeps unread visual
   objects explicit. The local planner then selects mapped source handles and exact
   table coordinates for each page. Titles and limited planning excerpts are not proof of substantive facts;
   the writer receives the selected complete evidence.
   Optional `complete-page-context-v1` adds a local coverage critic for every
   complete source page before planning. It records only changed topic selectors;
   software projects those recorded patches over the original model map, binding
   both actual raw records. Unassessed coverage blocks planning. Its local review
   does not grant professional financial or legal acceptance.
   The newer `complete-document-literals-v1` with
   `complete-literal-context-v2` instead sends the entire original literal catalog
   directly to the local planner. Every physical page and all native table grids
   remain present, with no mapper, adoption or coverage-critic calls. It refuses
   catalogs above 48K characters rather than clipping. Reconstruction from the
   original inventory validates literal closure, locators, cell matrices and
   provenance. Chart/visual/OCR semantics stay explicitly unassessed. Source
   mapping and coverage review are `not_performed`, not invented passes.
3. The local writer authors page prose, column labels and captions. Each factual
   claim binds its own exact source quote and reported/projected/planned/inference
   basis. Software copies selected original table cells literally. A blank is
   displayed as `Blank in source`, never imputed as zero.
4. A separate local review checks the recorded page against its frozen evidence.
   Failed or absent review cannot establish independent acceptance.
5. Export only an exactly replayed, contiguous authored prefix, with explicit
   partial/review status and exact editable/PDF byte receipts. Financial,
   regulatory and investor approval remain `not_established`.

Each advance permits one new model call, 105 seconds and six physical requests;
the private wrapper has a 118-second cap. Append-only intent/budget/raw/checkpoint
journals prevent repeated failed or unknown calls. Maximum document size is eight
intro pages, 32 pitch pages or 40 memo pages. Oversized evidence/tables must be
split explicitly; no truncation or extra retries are added. The mapped profile
allows at most 120 physical-page maps and a lifetime bound of map count + 81 calls.
A missing, changed, failed or unresolved map prevents planning; maps cannot export
as authored pages. Every source-map receipt is bound into the actual plan and
exact export chain. Historical-source user scope reaches both author and reviewer.
The context profile allows a finite `2 × map count + 81` calls, with unchanged
per-pass limits. All maps precede all coverage reviews, then the real plan.
A separately installed/pinned source critic may differ from the page reviewer.
Successful mapper adoption does not invent coverage reviews or their budgets.
The direct full-literal profile has a finite lifetime of 81 calls, beginning with
the actual global plan. An eight-page intro requires at most seventeen actual
calls. Page authorship and review, original table-value checks and all professional
release gates are unchanged. Whole same-page literal context remains available
  to each writer and reviewer; no company prose is supplied by the orchestration.
The additive `complete-document-literals-v2` encoding uses a shared `page_columns`
header and positional page frames. Every original frame field, literal and table
remains present. The first source's compact catalog decreases from 35,119 to
30,326 characters; read-only reconstruction proves all original frames and native
tables roundtrip exactly. V1 frozen catalog/request bytes remain unchanged.
An explicit optional `--planner` is supported only with the compact full-literal
encoding. It freezes a separate installed planner digest and records the original
author as `page_author_pin`. Planning, writing and review validate the actual
selected role's installed pin before inference. Defaults remain unchanged; the
planner cannot silently become the page author. Export receipts expose all three
roles. This is a capacity option, not proof that a smaller planner is capable.

The V1 catalog is unchanged. Explicit V2 retains every source handle once while
removing repeated hashes and duplicate unseen-handle lists. Full original XML and
ledger hashes stay in the frozen private inventory. The server's actual context
receipt still decides validity; tokenizer estimates alone do not pass that gate.

Example with an already-created isolated manifest; replace placeholders with
local private paths and choose a **new** ignored directory:

```bash
.venv/bin/python scripts/evaluate_reference_generation.py \
  --phase prepare \
  --manifest runtime_qualification/private_acceptance/PRIVATE_SOURCE/document_evidence_manifest.json \
  --output runtime_qualification/private_acceptance/NEW_PRIVATE_RUN \
  --kind intro_deck --author qwen3.5:9b --reviewer qwen3.5:9b \
  --catalog-encoding complete-document-literals-v1 \
  --qualification-context-profile complete-literal-context-v2

.venv/bin/python scripts/evaluate_reference_generation.py \
  --phase advance --output runtime_qualification/private_acceptance/NEW_PRIVATE_RUN

.venv/bin/python scripts/evaluate_reference_generation.py \
  --phase verify --output runtime_qualification/private_acceptance/NEW_PRIVATE_RUN

.venv/bin/python scripts/evaluate_reference_generation.py \
  --phase export --output runtime_qualification/private_acceptance/NEW_PRIVATE_RUN
```

For an explicit installed-model role comparison add
`--planner qwen3.5:4b` and use `--catalog-encoding complete-document-literals-v2`
at preparation. Author/reviewer defaults remain 9B. No model is downloaded.

Advance returns one phase/checkpoint. Continue only a `needs_call` run; a blocked
run is terminal. Verify performs no inference. Failed planning has no authored
page and cannot export. The CLI cannot create rooms, approve artifacts or mutate
saved company data. Do not automatically run the examples as another model trial.

## Source-ID reader and unchanged prefix reuse

The first complete-page run passed its two heading/agenda pages, then exhausted
900 output tokens on the first substantive page. Its partial response also joined
separate table cells into nonliteral quotes and repeated a topic. That failed raw
response remains terminal and was not adopted.

The explicit `unit-ids-v2` reader replaces free quotation copying with twelve
fixed topic fields. The local model chooses status, basis, original unit IDs and
native table IDs. Software carries the whole original strings into a deduplicated
planning pool. It does not join source cells, fix values or author judgments.
Own-page/table/blank/OCR checks remain mandatory. A wrong own-page selection can
still be semantically wrong; binding never establishes financial qualification.

The additive `unit-ids-bound-v3` profile constrains the actual decoding schema to
the page's own nonblank unit IDs and original table IDs. All blank originals remain
in the read view, but cannot be selected as evidence. A shared schema definition
keeps the finite choice set compact. Empty visual pages permit no IDs. This fixes
the concrete blank/foreign-ID boundary; it does not choose relevant evidence for
the model. Historical quoted and unconstrained source-ID requests stay exact.

Per-page profile/token vectors are frozen. Old quoted requests retain their exact
schema/options; selector requests use a bounded output allowance of 1,600 tokens
within the same 105-second pass. The historical all-quoted/default profile is
unchanged. A new branch may reuse only a complete successful prefix whose frozen
requests, source inventory, pins, kind and mandate are exactly identical. Raw
files are copied byte for byte; failed records remain in their parent branch.
Reuse receipts contain parent request/raw/intent/source hashes and state zero new
calls or physical requests. No fake budget records are created. Reopen checks the
parent chain again and blocks missing, altered, mismatched or cyclic provenance.

An isolated worker receives only literal read capabilities for verified lineage
files and source proofs. A parent-directory literal permits listing, without
allowing its descendants; writes stay inside the current job. The actual initial
boundary failure was preserved before that capability was fixed, with no model
call or intent at the failed phase.

For a new selector run, add `--source-map-profile unit-ids-v2` and
`--source-map-output-tokens 1600` to prepare. To reuse verified unchanged maps,
add `--reuse-source-map-prefix runtime_qualification/private_acceptance/PARENT_RUN`.
The CLI derives the successful count, checks source provenance, and preserves the
old per-page profiles/budgets for adopted rows. It never copies the failed row or
manufactures an answer. Do not start another profile solely to repeat a failed
model call without a concrete code/capacity correction.

For the structurally constrained reader use `--source-map-profile unit-ids-bound-v3`.
The new coverage/context route adds:

```text
--qualification-context-profile complete-page-context-v1
--source-coverage-reviewer qwen3:14b
```

These are opt-in preparation settings, not live-acceptance claims. The installed
source critic is frozen separately; page author/reviewer pins remain unchanged.
Planning receives complete original table rows and cell coordinates, with exact
binding checks. Table navigation cannot expand permitted narrative evidence or
assign financial meaning. Writers and page reviewers receive complete surrounding
literal context. The renderer shows recorded claim basis as concise status labels
while preserving all company prose exactly. No local review establishes investment,
financial or regulatory approval.

The complete-page/coverage route is preserved for replay. Its latest 27-map run
did not establish content quality: substantive source facts were omitted, the
first critic incorrectly promoted cover metadata, and the second timed out with
empty output. No plan or material was exported. The direct full-literal flow is
the current diagnostic approach; do not restart terminal failed branches.

## Renderer qualification

`render_evidence_document` is additive to historical render contracts. It handles
source-bound rectangular tables with bounded readable rows/columns and refuses
overflow. PPTX/DOCX tables are editable; their PDFs retain searchable cell text.
EvidenceChart supports bounded clustered/stacked columns, bars, lines and pies
from complete original native caches. It rejects external dependencies, unsupported
axes/combinations and incomplete/nonfinite caches. Numeric literals/categories
are checked against both exported native chart XML and the embedded workbook.

PPTX charts are native/editable. DOCX charts are images plus editable literal
tables. PDF charts include a literal companion table; this is not independent
visual qualification. Generic embedded-workbook audience/release checks remain
blocked. All 22 native charts in the supplied 20-slide PPTX were rejected because
of external relationships. No company chart was fabricated or silently repaired.

Synthetic editable/PDF exports were converted with isolated LibreOffice and
inspected visually. A real negative-bar inversion was found and fixed. The new
generation plan schema currently selects prose/tables; the chart renderer is not
an enabled local-model chart-selection phase.

## Tested code versus live acceptance

Focused parser, OCR, journal/replay, export, numeric guards and renderer checks
passed. Synthetic Office tables/charts passed bounded file and visual inspection.
These checks do not demonstrate company content quality, financial diligence,
India legal compliance or investor approval.

| Private live branch | Outcome |
| --- | --- |
| Native20-slide PPTX / 9B / V1 | Context integrity failure |
| Same source / 9B / V2 | Full context recorded; required product topic omitted and header rows selected as data |
| Same source / 14B / V2 | 105-second cancellation; empty output |
| Separate27-slide PPTX / 14B / V2 | 105-second cancellation; empty output |
| Separate 27-slide PPTX / 9B / complete-page quoted reader | Two maps passed; third response exhausted 900 tokens and contained nonliteral joined quotes |
| Same source / 9B / source-ID reader | Thirteen maps bind; fourteenth selects blank literals and is blocked. Two responses adopted unchanged, twelve new calls; no plan or page export |

No page-author, page-review or company export stage followed the failed plans.
The 14B attempts establish bounded capacity failure, not a semantic score.
The earlier 9B normal-stop failure also selected headings or mismatched evidence for
substantive topics. A later audit found that its planner had seen only 40 of 1,394
source units; that run cannot establish capability after complete source reading.
The old unit-only topology also omitted image-only physical pages. The new mapped
profile freezes all physical pages, including unread visuals, and traverses all
available literals before planning. No failed response was repaired or accepted.

The source-ID reader passes binding on substantive pages, but independent spot
review found mixed financial qualifiers and incomplete label/amount selections.
Its maps remain unreviewed navigation proposals. The planner/writer/reviewer must
preserve original qualifiers rather than treating a reader label as verified fact.

Three authenticated Claude Code sessions contributed generic journal, export and
source-ID selector/compiler code. They received sanitized code/specifications;
no private source text, model response or company answer went to Claude.

Codex agents independently audited receipts and private page readings. Claude
Code contributed coding/orchestration in authenticated sessions
`ccef5285-1a42-4c78-a08c-4bc7d18ee53e` and
`17d6ff02-ff3c-4b0f-859b-7bcdfce78e7e`, using generic sanitized specifications only.

Next capacity/adaptation work needs independently adjudicated multi-company
labels, held-out private acceptance and measured hardware feasibility. The prior
9B LoRA run exceeded this 16 GB Mac; no new training was attempted here. No cloud
spend or larger download is authorized by this document. India's financial and
legal acceptance owners, complete reviewed rule matrix and exact-package grants
remain outstanding. See [NEXT_AGENT.md](../NEXT_AGENT.md) and
[handoff §76](../SESSION_HANDOFF.md#76-14-october-private-reference-ingestion-and-evidence-document-generation).

## 32K terminal evidence and next source-selection refactor

The complete enriched source contains 2,310 original literals. The finite compact
V2 plan at 16K completed normally but returned the runtime overflow count8,194,
so it was blocked. Opt-in `complete-local-32k-v1` planning then completed normally
in60.98s with18,278 input /805 output tokens. It failed contradictory topic
coverage, invalid source handles and invalid native-table coordinates. No author
or export followed. The time/call caps and16K writer/reviewer context are unchanged.

The next explicit `finite-physical-plan-v3` profile selects finite original
physical groups and records one ordered topic-disposition matrix. Signed compact
author/reviewer capacity is checked before inference. Original literal, image,
table, qualifier and approval checks remain mandatory. This profile is being
integrated and has no live acceptance yet.

Installed Qwen3.5 models report vision capability. The original PPTX was rendered
inside the existing network-denied Office boundary with macros and link updates
disabled; original bytes remain unchanged. Complete private rasters retain
original/PDF/image/engine hashes. An additive local visual-table reader will
propose cells by exact non-OCR original IDs, retaining null as unbound rather than
zero or confirmed blank. Vision is source reading, never financial verification.
No private input is sent to Claude Code or another hosted model.

## Recorded source reuse and separate planning roles

`selected-physical-plan-v5` reads each complete original page locally and records
1–3 finite, nonblank source IDs. Software retrieves those whole unchanged source
strings. It writes no synopsis and assigns no company facts. The explicit
`complete-local-source-32k-v1` context completed all 27 enriched source reads;
one source required 17,797 input tokens, demonstrating the earlier 16K limit.

`bound-selected-refs-v2` removes repeated metadata while preserving exact selected
strings, native table grids and request/raw/source bindings. Rehydration checks
against the frozen original inventory. Nothing is clipped. The actual inventory's
worst-case index is 32,938 characters, below the unchanged 48K bound.

Optional `--source-reader` separates the source pin from `--planner`. The source
seed stays byte-identical; the separate pin applies to the future global plan.
`--material-context-profile complete-local-materials-32k-v1` allocates 32K context
to future author/reviewer calls, retaining 2,200 output tokens and all time/call
bounds. Existing requests and defaults are unchanged.

`--reuse-document-prefix` adopts only successful source/plan raw records whose
source requests, originals and actual call/budget proofs match exactly. Failed
records stay in the parent branch. An unchanged failed or unresolved next request
cannot be retried through adoption. Child intents identify adopted records;
no child physical budgets or model invocations are fabricated. Exact file read
permissions expose required lineage receipts without granting a private subtree.

Live V18 reused all 27 successful 9B source rows with zero extraction calls. Its
4B global plan completed in 66.758 seconds but assigned all twelve topics to
every page and failed validation. No company page or export was accepted.
The next optional `--planning-assignment-profile page-topics-v1` moves topic
choices onto each planned page to reduce the model's cross-reference burden;
source-reader requests remain unchanged. Record its actual live result before
claiming planning quality.

## Final live checkpoint

`single-source-outline-v2` produced a valid eight-page outline. Its first
9B-authored page passed binding but failed scope review. The explicit
`scope-feedback-once-v1` flow reused 29 exact records, corrected reviewer scope,
allowed one recorded model-only repair and required fresh review. Re-review
still rejected two scope issues; the branch is terminal. No complete new
investor material was accepted. Financial vision repair timed out at 105 seconds.

Exact source/plan/first-author reuse uses receipt v2 only for the explicit intro
repair profile. It verifies actual ancestral budgets, creates no budgets or
inference calls and excludes the previous rejected review. The final focused
CLI safety check passed; all diagnostic models and agent work are stopped.
The visual literal codec is untested/unintegrated. No weights were trained.
