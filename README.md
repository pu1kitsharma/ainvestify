# ainvestify

**Evidence-bound deal sourcing, diligence and investor-material generation, run on local models.**

## 1. Problem and scope

Advisors and funds screen far more companies than they can read, and the
materials a company needs to raise (intro deck, pitch deck, investment memo,
optionally a projection model) are written by hand, inconsistently, without an
audit trail. ainvestify automates the grunt work: it sources candidates, reconciles
evidence about them, and drafts cited materials that a person reviews and releases.

Non-goals: investing the operator's own capital, contacting founders or
investors, negotiating, signing, or moving money. The system produces reviewable
work product only.

## 2. Design invariants

These are enforced in code and take precedence over features.

1. **Provenance.** Every number or factual claim carries a source reference
   (document + page/block, or URL + version) or is explicitly `missing` /
   `illustrative`. Typical values are never inferred into facts.
2. **Separation of authorship and verification.** Local LLMs author all
   company-specific content. Deterministic code retrieves, binds citations,
   calculates, validates and renders. Code never writes company prose.
3. **Human release gate.** Approval is bound to an exact artifact version and the
   validation result for it. A failed or unrun mandatory check blocks release.
4. **Tenant isolation.** Identity is derived server-side (OIDC session). Rooms,
   files, jobs and caches are per user. Only the public knowledge base is shared,
   and private data never flows back into it.
5. **Local inference.** Private documents are processed on local models behind a
   sandbox; no hosted-LLM fallback exists on the product path.
6. **Reproducibility.** Every model call is recorded (prompt, schema, model digest,
   raw response). Results are projections of recorded responses and replay
   without inference. Contracts are versioned; old versions keep replaying.

## 3. Architecture

```
 public sources ──► collector ──► staging ──► public KB (ES) ──┐
                    (rights-gated, leased, 6h/12h refresh)     │
                                                               ▼
 user brief ─► discovery ─► lead ─► reconcile ─► diligence ─► deal room (private)
                                    identity,     evidence        │
                                    funding,      bundle          │ durable phased job
                                    status                        ▼
 uploads ─► ingestion ─► source units ─► memo ─► deck drafts ─► review ─► render
 (PDF/XLSX)  (sandbox)   [S1..Sn]       author   source-bound    local     PPTX/DOCX
                                        +repair  slot selection  reviewer  + PDF
                                                                    │         │
                                                                    ▼         ▼
                                                              human sign-off ─► release
```

| Layer | Responsibility | Where |
|---|---|---|
| Discovery & KB | Rights-gated collection, identity and funding-history reconciliation | `agents/discovery`, `agents/research` |
| Ingestion | Private PDF/PPTX/XLSX inventories and local OCR; native structure and exact source lineage | `agents/core`, `agents/research/*manifest*`, `scripts/private_*_worker.py` |
| Memo | Staged authoring over exact evidence spans, typed evidence ledger, causal/field review, content repair | `agents/research/*memo*` |
| Materials | One bounded call per slide slot; model selects exact memo sentences, software binds citations | `agents/research/material_*` |
| Reference document flow | Opt-in local planning, page writing and separate review over immutable document evidence | `agents/research/document_generation.py`, `delivery/document_generation_*` |
| Delivery | Render, inspect exported files (text/page/formula checks), release gates | `delivery/` |
| Model plumbing | Local Ollama adapter, recorded calls, budgets, routing | `agents/inference` |
| API / UI | FastAPI, durable room worker, React frontend | `api/`, `frontend/` |

## 4. Key mechanisms

- **Bounded, replayable generation.** Each phase has a hard cap on calls and wall
  time. State is recomputed from recorded attempts, so a restart never repeats a
  call or extends a cap. A failed call is data, not an exception to retry blindly.
- **Bounded reasoning qualification.** An opt-in local Qwen transport allocates
  reasoning and a grammar-bound final answer within one shared budget. Both
  requests bind model identity, full evidence, schema, sampling and token counts.
  Replay recomputes known input hashes; foreign receipts cannot satisfy them.
  Intermediate thoughts stay in memory, so their hashes record provenance rather
  than reconstructible reasoning. This mode is undergoing fictional qualification;
  it is not enabled in private room generation or established as investor quality.
  The latest separated 14B reasoning profile also failed: it treated contact
  details as substantive identity evidence (one of two executed cases matched;
  eight were unrun). Exact transport replay passed; source interpretation did
  not. No weights have been trained.
- **Typed evidence ledger.** Prose and claim rows are labelled by the model against
  exact source key/values; software compares labels with facts and forces a
  model rewrite on conflict (for example "reported" vs "verified" funding).
- **Review/repair loop.** A local model first characterizes sources without seeing the memo, binding
  historical and projected basis to exact evidence IDs. A reviewer then judges
  every rationale sentence against
  enumerated exact evidence spans, separating truthful evidence gaps from unanswered
  diligence. A blocked field gets fresh source-only local-model prose and exact re-review;
  rejected draft wording and reviewer criticism are excluded from generation.
  The room gate and deck options replay the same revised memo; missing financials
  and independent approval still block release. Historical responses stay intact.
- **Complete deck assertions (`purpose_v18`).** The local model selects whole
  reviewed statements; conditions and requested records remain attached. Financial
  targets retain exact dated source context. The model selects the source period
  and its temporal classification; software displays those recorded choices with
  neutral labels and unchanged excerpts. Slot/function/chronology review
  (`semantic_v20`) is mandatory, with small bounded local calls and exact
  model pins. Frozen older contracts keep their original prompts and replay.
- **Isolation.** Workers run under a deny-by-default sandbox profile; network is
  closed except loopback to the model runtime.
- **Complete source assessment.** Fresh rooms use `room-v62-explicit-topic-status`
  (FLOW10, coverage18). Five direct local-model assessments read every complete
  source group, followed by one evidence selector. Earlier classifier answers
  are excluded. The model explicitly marks each category as absent or selects
  its exact supporting excerpt. Headings/contact pages have no substantive
  categories. Funding options require an explicit capital label in that same
  evidence window. Software projects the recorded choices; it adds no topics.
  Each unique passage receives one judgment, projected to exact duplicate members
  through their own verified source versions and evidence coordinates.
  Assessment uses the frozen author role; selection uses the challenge role.
  Core author13/reviewer12 require the pinned memo-cards-v13 profile. Changed
  roles, raw responses, evidence, context receipts or sampling options block replay.
  This replaces the earlier classifier-and-patch workflow with six source calls;
  FLOW10 has 21 checkpoints. Historical FLOW7/8/9 retain their 26 checkpoints and
  eight-changed-source correction limit; historical FLOW6/5 retain 22/21.
  Inventory above 25 sources, duplicate groups above five members, incomplete
  grouping or context/output capacity failures block explicitly. No source text
  is dropped. Tables and workbook cells retain structure and lineage; chart
  interpretation, financial reconciliation and qualified recalculation remain
  separate requirements.
- **Plain language.** Core author v13 selects a visible source-status label and
  separates the source premise from conditional or requested checks. The displayed
  text is an exact projection of model components, including the label, within
  the existing 48-word/280-character limits. Reviewer v12 checks each component and
  complete statement for factual support, clear wording, repetition and
  unsupported comparisons alongside the financial and section-function gates. Named financial measures bind to the chosen exact quote. Failed wording is
  never replaced with hand-written company prose.
- **Private workbook index.** A separate isolated stage retains all nonempty
  cells, formulas/caches, hidden structure and dependency findings, with bounded
  exact range retrieval. The original supplied workbook parser check retained
  3,596 cells without changing its bytes. The opt-in room bridge excludes
  flattened workbook rows from narrative sources and freezes unassessed financial
  scope. Retention does not establish interpretation, reconciliation or approval.
  See [financial index](deployment/PRIVATE_FINANCIAL_EVIDENCE.md).
- **Separated source tasks.** An explicit diagnostic flow records quote/topic
  extraction and kind classification as two actual local-model responses, bound
  to the full source and each other. Its 41 durable checkpoints prevent failed
  or unknown calls from being repeated. It remains outside the production room
  default because fast and reasoning profiles failed clear semantic controls.
- **Structured reference reading and rendering.** Private PDF/PPTX manifests
  retain tables, chart caches/XML, notes, geometry and source hashes. Local Apple
  Vision adds separate, unreviewed OCR observations without replacing originals.
  Numeric assertions supported only by OCR are blocked. An opt-in generation
  flow lets local models choose source units, author pages and review them, with
  exact-cell tables and native editable PPTX/DOCX exports plus PDFs. Supported
  PPTX charts preserve original caches; external dependencies remain blocked.
  Complete-page reading now precedes planning, replacing the opening-snippet
  approach. Source-ID bindings pass on substantive pages; semantic omissions
  remain under review. This flow is not the production room default.
  See [reference generation and limits](deployment/REFERENCE_GENERATION.md).
- **India regulatory scope.** Private fundraising/internal diligence release
  requires declared transaction scope, a complete reviewed rule matrix and a
  qualified human decision against the exact package. See
  [India review requirements](deployment/INDIA_PRIVATE_MATERIALS_COMPLIANCE.md).
  Official-source pointers do not establish legal approval.

## 5. Status and known gaps

Local component pipelines are implemented; complete production room acceptance
and investment quality remain open. No investor material is approved.

**14 October checkpoint:** all four supplied references were parsed privately,
both PDFs received local OCR, and structured tables/charts passed synthetic
render checks. Earlier plans failed or timed out. An independent audit found
that planning had seen only 40 of 1,394 source units. The complete-page reader
then exposed further semantic omissions after its ID grammar was fixed. The
separate 14B coverage critic made incorrect topic promotions and timed out.
The new explicit diagnostic gives the local planner all original document
literals and native table grids directly, with mandatory page author/review
afterward. It refuses oversized evidence instead of clipping. Its first 9B
full-literal plan timed out with empty output; a lossless compact encoding now
reduces metadata overhead. A further source audit recovered 1,504 original Unicode
text records inside financial vector images and 26 SmartArt strings. A lossless
encoding now fits the entire enriched inventory. Streaming exposed an unbounded
page-ID field. The finite 16K plan hit the overflow cutoff; the explicit 32K
plan completed with full input but failed source selection and topic coverage.
The selected-source path completed all 27 original page reads using 9B at 32K.
A separate 4B produced a valid eight-page outline. The first 9B-authored page
failed local scope review, including after its one model-only repair. The visual
matrix failed spatial review; its bounded repair timed out. No complete new
company memo/deck or financial/regulatory approval is
established. No weights were trained. Production defaults remain held, with results
and required next inputs in [NEXT_AGENT.md](NEXT_AGENT.md).

| Gap | Impact | Direction |
|---|---|---|
| Rationale quality and review calibration | New sentence/evidence gate fixes gap-vs-answer conflation; broad content quality remains unqualified | Held-out multi-company evaluation, reviewed training labels if adaptation is justified |
| Financial PDF reading | Local OCR now retains text but can miss decimals; cell mapping and chart semantics remain unqualified | Exact provenance, independent numeric corroboration and reviewed financial reading |
| Full-document planning | Preliminary topic maps omitted facts; the new bounded path exposes all native literals directly | Local plan, author and review over unchanged originals; live qualification pending |
| No tuned model; 9B LoRA exceeds 16 GB | Cannot improve weights locally | Train on a larger GPU host (see [models/](models/README.md)) |
| Workbook reconciliation incomplete | No validated projection | Dependency analysis + recalculation qualification |

The historical 9 October memo review completed fifteen bounded checkpoints with
unchanged attempt caps. That private run used the installed 9B for source stages
and 14B for core writing/review, completing all checkpoints and exact replay. Independent
inspection found no blocking source error in that memo or its rendered sections.
The subsequent private run completed all ten deck author calls and ten fresh
material review batches, covering nineteen complete statements with exact replay.
Intro/pitch/memo editable and PDF files now pass both direct and isolated Office
text checks; all pages were inspected. The renderer fixes preserve long question
headings, source identifiers and complete paragraphs. These remain qualitative
drafts below the supplied benchmark in depth/design. Full room, financial and
independent investor acceptance remain open. No weights were trained. Current
results and operating instructions:
[NEXT_AGENT.md](NEXT_AGENT.md).

## 6. Operating it

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ollama serve                                # models are never auto-downloaded
.venv/bin/python scripts/serve_local.py     # API :8000, no reload
cd frontend && npm install && npm run dev   # UI :5173
```

Sign-in, configuration and tests: [docs/SETUP.md](docs/SETUP.md). HTTP surface:
[docs/API.md](docs/API.md). Fine-tuning artifacts and recipe: [models/README.md](models/README.md).

## 7. Further reading

[AGENTS.md](AGENTS.md) (working rules) · [release plan](LOCAL_TO_CLOUD_RELEASE_PLAN.md) ·
[financial projections](FINANCIAL_PROJECTIONS_PLAN.md) · [public KB plan](deployment/PUBLIC_KNOWLEDGE_BASE_PLAN.md)
