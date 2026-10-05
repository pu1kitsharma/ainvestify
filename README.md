# ainvestify

An AI system that finds early-stage companies worth backing, does the due
diligence, and prepares the investor materials a company needs to raise money.
Think boutique investment bank plus incubator, with a local AI doing the grunt work.
It is not a fund investing its own capital, and it never contacts investors.

## Who it is for

- **Funds and boutique banks / accelerators** that want to screen far more companies
  than staff can read, and produce consistent, cited diligence.
- **Companies preparing a raise** that need a clear pitch, memo and financial story.

The intent is to sell it to funds and advisory shops, so every company's data is
isolated per user (multi-tenant) from day one.

## How it works

1. **Discover.** Describe the kind of company you want (sector, stage, geography;
   worldwide by default). The system searches permitted public sources and a
   shared public knowledge base and returns candidates. A candidate is a lead, not
   a recommendation.
2. **Diligence.** For a chosen company it reconciles identity, funding history,
   product, market, team, finances and risks across sources, and flags conflicts and
   unknowns instead of guessing.
3. **Deal room.** Opening a company starts a private room that collects evidence,
   analyses the financials the company supplies, and drafts the materials.
4. **Materials.** An intro deck, a pitch deck and an investment memo, each as an
   editable file plus a matching PDF. A projection spreadsheet is produced only if
   the company supplies a model or you ask for one with enough reviewed inputs.
5. **Review and release.** A person reviews the exact version before anything is
   released. Missing financials are stated openly; nothing is invented.

## Rules the product is built on

- **Every claim traces to evidence.** A number or fact either cites its source or
  stays marked missing or illustrative. A "typical" value never becomes a company fact.
- **The AI writes, software checks.** Local models write all company analysis.
  Code only retrieves, links evidence, calculates, validates and lays out documents.
- **Human sign-off is mandatory** before a document is released.
- **Private data stays private.** Company documents are processed locally and never
  sent to hosted AI or fed back into the shared public knowledge base.
- **No outreach.** The system does not email founders or investors, negotiate or sign.

## Status

Not production-ready, and no investor material is approved yet. Discovery, rooms,
sign-in and the document pipeline run; the output quality is the open problem:

- The memo reviewer is inconsistent, so memo claims are not reliably settled.
- PDF ingestion drops content from image-based slides (charts, tables).
- Decks do not yet follow the structure of real founder decks (traction, team, cap table).
- No fine-tuned model exists; training needs more memory than this Mac has.

Details and the exact next steps: [NEXT_AGENT.md](NEXT_AGENT.md).

## Run it

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ollama serve                                   # models are never auto-downloaded
.venv/bin/python scripts/serve_local.py        # API on :8000
cd frontend && npm install && npm run dev      # UI on :5173
```

## Where things are

| Path | What |
|---|---|
| `agents/` | Discovery, research, memo and deck generation, analysis, model plumbing |
| `api/` | FastAPI backend ([routes](docs/API.md)) |
| `frontend/` | React UI |
| `delivery/` | PPTX / DOCX / PDF rendering and checks |
| `models/` | Pinned base model and fine-tuning recipe ([details](models/README.md)) |
| `docs/` | [API](docs/API.md), [setup, sign-in and tests](docs/SETUP.md) |

Plans and history: [AGENTS.md](AGENTS.md), [release plan](LOCAL_TO_CLOUD_RELEASE_PLAN.md),
[financial projections](FINANCIAL_PROJECTIONS_PLAN.md), [public knowledge base](deployment/PUBLIC_KNOWLEDGE_BASE_PLAN.md).
