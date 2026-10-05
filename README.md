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
| Ingestion | Deterministic PDF/XLSX parsing into cited source units, run in a macOS sandbox | `agents/core`, `scripts/private_*_worker.py` |
| Memo | Staged authoring over exact evidence spans, typed evidence ledger, causal/field review, content repair | `agents/research/*memo*` |
| Materials | One bounded call per slide slot; model selects exact memo sentences, software binds citations | `agents/research/material_*` |
| Delivery | Render, inspect exported files (text/page/formula checks), release gates | `delivery/` |
| Model plumbing | Local Ollama adapter, recorded calls, budgets, routing | `agents/inference` |
| API / UI | FastAPI, durable room worker, React frontend | `api/`, `frontend/` |

## 4. Key mechanisms

- **Bounded, replayable generation.** Each phase has a hard cap on calls and wall
  time. State is recomputed from recorded attempts, so a restart never repeats a
  call or extends a cap. A failed call is data, not an exception to retry blindly.
- **Typed evidence ledger.** Prose and claim rows are labelled by the model against
  exact source key/values; software compares labels with facts and forces a
  model rewrite on conflict (for example "reported" vs "verified" funding).
- **Review/repair loop.** A reviewer judges each rationale against retained
  passages; a blocked field gets a bounded model rewrite with validation feedback,
  then an exact re-review. Reviewer disagreement is surfaced, never overridden.
- **Distinct deck slots (`purpose_v14`).** Each slide is offered only memo
  sentences earlier slides did not use; repeated headings are rejected.
- **Isolation.** Workers run under a deny-by-default sandbox profile; network is
  closed except loopback to the model runtime.

## 5. Status and known gaps

Components run end to end; **output quality is the open problem**. No investor
material is approved.

| Gap | Impact | Direction |
|---|---|---|
| Reviewer inconsistency (9B and 14B both) | Memo claims do not settle | Calibration data + fine-tuning; stronger reviewer |
| Lossy PDF ingestion (image charts/tables, interleaved columns) | Model never sees much slide content | Layout/vision-aware parse |
| Fixed slide plan vs real founder decks | No traction/team/cap-table/table slides | Role-based slide plan, table renderer |
| No tuned model; 9B LoRA exceeds 16 GB | Cannot improve weights locally | Train on a larger GPU host (see [models/](models/README.md)) |
| Workbook reconciliation incomplete | No validated projection | Dependency analysis + recalculation qualification |

Execution detail and live results: [NEXT_AGENT.md](NEXT_AGENT.md).

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
