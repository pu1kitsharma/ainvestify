# ainvestify

An AI-driven, multi-agent system for sourcing and incubating early-stage companies, then helping them raise institutional funding — the way a boutique investment bank packages a raise, not a fund screening deals for its own book.

Lifecycle: **source** candidate companies → a human **promotes** a lead into a deal → **ingest** the company's own documents → **extract** structured metrics with mandatory citations → **human review** → **research** external corroboration → **compile** a cited, reviewable document suite (CIM / teaser / pro-forma). A parallel **operations** track takes a sourced-but-not-yet-promoted lead through AI-prepared research, founder outreach and investment-readiness drafts, all evidence-cited and human-reviewed.

Every extracted numeric field carries a source citation or stays `null` — never inferred from a "typical" value. Human review/sign-off is mandatory before any document is finalized. This system does not itself contact investors, negotiate terms, or run a raise — that stays a human-led activity.

**Status:** Phase 0 — local, CPU-only validation, zero cloud spend. **[CLAUDE.md](CLAUDE.md)** carries the current, dated status log (what's built, what's validated, what's known-broken) and is the source of truth for "is X working right now" — it is not duplicated here because a second copy of that log would just drift out of sync. Read it, and [SESSION_HANDOFF.md](SESSION_HANDOFF.md) for full session-by-session detail, before assuming any feature described below is production-quality.

## Setup

1. Install [Ollama](https://ollama.com/download) and confirm `ollama serve` is running. Pull the models you intend to route to (see **Model configuration** below) — nothing is downloaded automatically.
2. `pip install -r requirements.txt` (add `-r requirements-dev.txt` for `pytest`/`httpx` to run the test suite).
3. Backend: `python3 scripts/serve_local.py` — starts the FastAPI app on `http://localhost:8000` **without auto-reload** (a live background job can otherwise be silently interrupted by a reload; restart the process after backend edits instead).
4. Frontend: `cd frontend && npm install && npm run dev` — Vite dev server on `http://localhost:5173`, the only origin the API's CORS policy allows in Phase 0.
5. CLI entry point (bypasses the web UI entirely): `python3 main.py "<what you want to do>"` — e.g. `"find promising fintech companies to incubate"` or `"screen this deal, I have the pitch deck ready"`.

### Model configuration

All inference is local via Ollama unless a specific env var opts a path into the (currently user-approved, bounded) Anthropic path — see [CLAUDE.md](CLAUDE.md) for the current approval scope. No paid API, automatic model download, or silent downgrade happens without one of these being set explicitly.

| Variable | Purpose | Default |
|---|---|---|
| `SOURCING_MODEL` | Short extraction / classification tasks (lead routing, directive classification) | `phi4-mini` |
| `REASONING_MODEL` | Analytical work, screening, retries, review — thinking enabled | `qwen3:8b` (`qwen3:14b` auto-selected on machines with ≥24GB RAM) |
| `PREPARATION_MODEL` | Fast preparation route for operations drafts | see `agents/inference/local_models.py` |
| `REVIEW_MODEL` / `ESCALATION_MODEL` | Alternate thinking models for review/escalation stages | falls back to `REASONING_MODEL` |
| `RESEARCH_AGENT_CONTACT` | Real `"YourOrg contact@email.com"` — SEC EDGAR and Wikipedia both hard-require an identifying User-Agent per their published policies (Wikipedia 403s without one) | placeholder, must be set before relying on either beyond local smoke-testing |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY_FILE` | Server-side key for the bounded public-evidence Anthropic path (`agents/inference/anthropic_api.py`) | unset — that path raises rather than silently falling back |
| `ANTHROPIC_MODEL` / `PREPARATION_PROVIDER` / `PREPARATION_MAX_SECONDS` | Provider/model selection and time budget for the preparation path | see `agents/inference/local_models.py` |
| `DISCOVERY_PLAYWRIGHT_MODULE` | Path to an installed Playwright module, for the browser regression scripts only (`scripts/check_discovery_ui.cjs`, `scripts/check_operations_ui.cjs`) | none |

`scripts/configure_api_key.py` prompts for and privately stores an Anthropic key under `deployment/.secrets/` (gitignored, `0600`) — it never makes an API call itself.

## Package layout

`agents/` and `tests/` are organized into subpackages by concern (reorganized 2026-09-30 from a flat ~50-file directory in each — see the note at [CLAUDE.md §"Files in this project"](CLAUDE.md)):

| Subpackage | Contains | Examples |
|---|---|---|
| `agents/core/` | The original §5.1–§5.8 pipeline: planner/state-machine, ingestion, extraction, human review checkpoint, analytics, compilation, market research, deal sourcing | `planner_agent.py`, `extraction_agent.py`, `compilation_agent.py` |
| `agents/discovery/` | Finding and sourcing companies: web/public-directory discovery, company identity resolution, licensed dataset connectors | `web_discovery.py`, `public_directories.py`, `company_sourcing.py` |
| `agents/research/` | Evidence gathering and reasoning over collected pages | `research_reasoning.py`, `research_evidence.py`, `public_research.py` |
| `agents/preparation/` | Deliverable/document generation — model-authored discovery & preparation, company briefs, investment cases | `authored_preparation.py`, `company_brief.py`, `investment_case.py` |
| `agents/analysis/` | Company/financial analysis on reviewed operating data | `company_analysis.py`, `company_metrics.py`, `growth_analysis.py` |
| `agents/inference/` | Model/transport plumbing — the local vs. hosted model boundary, provenance, routing | `local_models.py`, `anthropic_api.py`, `model_routing.py` |

`tests/` mirrors this layout (`tests/core/`, `tests/discovery/`, etc.) plus `tests/api/` for FastAPI router tests. Top-level modules (`schemas.py`, `store.py`, `main.py`, `workflow_schemas.py`) are unchanged. This was a structural/import-path change only — the offline test suite was verified against the pre-reorg baseline with zero behavior change.

## API reference

The FastAPI app (`api/main.py`) is self-documenting and this table is generated from its actual route table, but the interactive/raw forms are the ones that can never drift from the code:

- **[`/docs`](http://localhost:8000/docs)** (Swagger UI) — expand any endpoint, fill a real request, **Try it out** against the live local backend. `/redoc` gives a read-only narrative view of the same schema.
- **[`/openapi.json`](http://localhost:8000/openapi.json)** — the raw OpenAPI 3.1 spec.
- **[`api/postman_collection.json`](api/postman_collection.json)** — import into Postman/Insomnia for a ready request tree with example bodies. Regenerate after a schema change: `python3 scripts/export_postman_collection.py` (fetches `/openapi.json` live).

All routes are mounted under `/api`. `GET /api/health` returns `{"status": "ok"}` for a liveness check. No auth in Phase 0 — `tenant_id`/`reviewer` are supplied via request dependencies (`api/deps.py`), not a session. CORS is open only to `http://localhost:5173`.

### `leads` — Deal Sourcing Agent (§5.8)

Discover candidate companies, human keep/dismiss review, promote a kept lead into a real `Deal`. A lead never touches `ExtractionResult` until promoted.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/leads/web-runs` | Start a background web-sourcing run from a free-text `thesis` + optional `geography` (`seed_urls` optional) — local model plans search queries, public search discovers pages, the collector researches original company pages |
| `GET` | `/api/leads/web-runs` | List web-sourcing runs for the tenant |
| `GET` | `/api/leads/web-runs/{run_id}` | Poll one run's phase/status/coverage |
| `POST` | `/api/leads/web-runs/{run_id}/cancel` | Stop an in-progress run |
| `GET` | `/api/leads/web-runs/{run_id}/leads` | That run's saved lead/evidence snapshots (`include_previous` to include superseded ones) |
| `POST` | `/api/leads/source` | VC-style sourcing (`agents.core.sourcing_agent.discover_leads`) — early-stage, GitHub-by-creation-date + HN Show HN |
| `POST` | `/api/leads/source-ib` | IB-style sourcing (`discover_ib_targets`) — mature/public companies via SEC EDGAR M&A-process language |
| `GET` | `/api/leads` | List leads (`status`, `web_run_only` filters) |
| `GET` | `/api/leads/{lead_id}` | Get one lead |
| `POST` | `/api/leads/{lead_id}/decision` | Human keep/dismiss decision on a sourced lead |
| `POST` | `/api/leads/{lead_id}/promote` | Promote a kept lead into a real `Deal` (`promoted_deal_id` links back) |

### `deals` — Deal lifecycle writes

Create a deal, sign the mandate, upload a document (ingestion), run extraction, read the audit log. Read-only list/detail live under `dashboard`; review decisions live under `review`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/deals` | Create a deal directly (without going through sourcing/promotion) |
| `POST` | `/api/deals/{deal_id}/mandate` | Record the Origination-stage mandate (`sign_mandate`) before ingestion can proceed |
| `POST` | `/api/deals/{deal_id}/documents` | Upload a PDF/Excel — deterministic ingestion (`agents.core.ingestion_agent`) into cited `DocBlock`s, no LLM |
| `POST` | `/api/deals/{deal_id}/extract` | Run the Structured Extraction Agent against the deal's ingested documents |
| `GET` | `/api/deals/{deal_id}/source-documents` | Raw ingested documents with their `DocBlock`s, for citation lookup |
| `GET` | `/api/deals/{deal_id}/audit-log` | Full audit trail for the deal |

### `dashboard` — Read-only deal summaries

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/deals` | List deal summaries (`status` filter) |
| `GET` | `/api/deals/{deal_id}` | Full deal detail |

### `review` — Human Review Checkpoint (§5.5 / §12)

Per-field approve/edit/reject on an `ExtractionResult`, cap-table/funding-history block review, and the bounded 2-retry reject loop that re-invokes extraction with the reviewer's note.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/deals/{deal_id}/review` | Current review state for every extracted field |
| `POST` | `/api/deals/{deal_id}/review/fields/{field_name}` | Approve / edit / reject one scalar field |
| `POST` | `/api/deals/{deal_id}/review/cap-table` | Block-level review decision on the cap table |
| `POST` | `/api/deals/{deal_id}/review/funding-history` | Block-level review decision on funding history |

### `research` — Market Research Agent (§5.4)

Live external-signal lookups for a deal (GitHub, HN/Algolia, SEC EDGAR, Wikipedia, plus sector-notes RAG), each finding reviewed before it reaches a memo.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/deals/{deal_id}/research/run` | Run live external-signal lookups for the deal |
| `GET` | `/api/deals/{deal_id}/research` | List findings |
| `POST` | `/api/deals/{deal_id}/research/{finding_id}/decision` | Approve/reject one finding |
| `POST` | `/api/deals/{deal_id}/research/mark-reviewed` | Mark the research stage complete |

### `compilation` — Compilation Agent (§5.7)

Compile the CIM, the teaser's two-step draft + safe-to-send confirm, the pro-forma with an optional growth-rate override, rerun analytics, and fetch the resulting document suite. All hard-refuse (`CompilationBlockedError`) unless `is_ready_for_compilation()` is true.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/deals/{deal_id}/compile/cim` | Compile the full comprehensive memo (NDA-gated) |
| `POST` | `/api/deals/{deal_id}/compile/teaser/draft` | Draft the anonymized pre-NDA teaser |
| `POST` | `/api/deals/{deal_id}/compile/teaser/{memo_id}/confirm` | Explicit human sign-off that the teaser draft doesn't leak identity, before it's released |
| `POST` | `/api/deals/{deal_id}/compile/proforma` | Generate the forward projection (optional growth-rate override; defaults to holding ARR flat if none approved) |
| `POST` | `/api/deals/{deal_id}/analytics/rerun` | Re-render charts against currently approved fields |
| `GET` | `/api/deals/{deal_id}/documents` | List every version of every document type (`document_type` filter) |
| `GET` | `/api/deals/{deal_id}/documents/latest` | Latest version of one `document_type` |

### `investors` — Demand-book record-keeping (§5.9 Roadshow)

Pure record-keeping — never contacts an investor or sends anything.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/deals/{deal_id}/investors` | Add an investor contact to the demand book |
| `GET` | `/api/deals/{deal_id}/investors` | View the demand book |

### `operations` — Company operating workspaces

AI-prepared research/pitch/readiness drafts and evidence-backed reviews for a shortlisted (not-yet-promoted) company. No external sending, signing, or money movement.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/operations/datasets` | Licensed/metadata-only source registry (Dataful, CC0 Wikidata, etc.) |
| `GET` | `/api/operations/workspaces` | List workspaces (`summary`, `lead_id` filters) |
| `POST` | `/api/operations/leads/{lead_id}/evaluate` | AI engagement-suitability assessment (`proceed` / `clarify` / `do_not_pursue`) |
| `POST` | `/api/operations/leads/{lead_id}/prepare` | Legacy: run the four-stage preparation pipeline synchronously |
| `POST` | `/api/operations/leads/{lead_id}/prepare-jobs` | Legacy four-stage preparation as a background job — poll via `GET /workspaces` |
| `POST` | `/api/operations/leads/{lead_id}/brief-jobs` | Current path: AI-authored research brief, founder email, readiness priorities (`refresh` to force regeneration) |
| `GET` | `/api/operations/workspaces/{workspace_id}/company-brief` | Export the current completed brief |
| `POST` | `/api/operations/leads/{lead_id}/readiness-jobs` | Suitability decision → decision memo / commercial validation doc / investor narrative |
| `GET` | `/api/operations/workspaces/{workspace_id}/investment-case` | Export current completed investment-case sections |
| `POST` | `/api/operations/leads/{lead_id}/preparation-jobs` | Current analyst-pack path (research memo / founder proposal / diligence request / readiness plan), with model/thinking overrides |
| `POST` | `/api/operations/workspaces/{workspace_id}/preparation-jobs/{job_id}/stop` | Stop a running preparation job |
| `GET` | `/api/operations/workspaces/{workspace_id}/preparation-pack` | Export current completed analyst-pack sections (`document` filter) |
| `POST` | `/api/operations/leads/{lead_id}/analysis-jobs` | Start company financial/scenario analysis |
| `POST` | `/api/operations/workspaces/{workspace_id}/analysis-inputs` | Supply analysis inputs the model requested |
| `POST` | `/api/operations/workspaces/{workspace_id}/analysis-scenarios` | Save scenario parameters for analysis |
| `GET` | `/api/operations/workspaces/{workspace_id}/analysis-report` | Export the current analysis report |
| `GET` | `/api/operations/workspaces/{workspace_id}/internal-brief` | Internal Markdown brief export |
| `GET` | `/api/operations/workspaces/{workspace_id}/data-request` | Tenant-scoped record-request document (specific asks, not evidence of a close) |
| `GET` | `/api/operations/workspaces/{workspace_id}/metrics` | Read dated company-reported operating figures |
| `POST` | `/api/operations/workspaces/{workspace_id}/metrics` | Manually save/correct a dated operating figure |
| `POST` | `/api/operations/workspaces/{workspace_id}/metric-imports` | Queue AI extraction of a pasted founder/finance update → source-block selection → validated figures → recalculated metrics → regenerated brief |
| `POST` | `/api/operations/workspaces/{workspace_id}/attestations` | Version-checked evidence/authority review sign-off (not a legal compliance certificate) |
| `POST` | `/api/operations/workspaces/{workspace_id}/execute/{action}` | Gated `send` / `sign` / `transfer` action stub — external execution stays disabled in Phase 0 |

### `prompt` — Free-text directive classification

The API-native equivalent of `main.py`'s CLI prompt router.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/prompt/classify` | Classify a free-text request into `source_leads` / `screen_deal` |
| `POST` | `/api/deals/{deal_id}/directive/preview` | Classify a free-text revision directive into one of the deal's valid next actions, for human confirmation before executing |

## Testing

```
python3 -m pytest -q                                    # full offline suite
python3 -m pytest tests/discovery/ -q                    # one subpackage
python3 -m pytest --ignore=tests/api/test_api_leads_live.py --ignore=tests/api/test_api_review_retry_live.py -q   # skip network-dependent live tests
```

Live/manual checks (need Ollama running, hit real networks — not part of the offline suite):

```
python3 scripts/smoke_web_sourcing.py --brief "Agricultural companies making solar dryers" --geography India --max-pages 2
python3 scripts/smoke_operations.py
node scripts/check_discovery_ui.cjs      # needs Playwright; set DISCOVERY_PLAYWRIGHT_MODULE if not on the default path
node scripts/check_operations_ui.cjs
```

## Further reading

- **[CLAUDE.md](CLAUDE.md)** — project context, locked-in decisions, conventions, and the current dated status log. Read this first, every session.
- **[deal_automation_architecture.md](deal_automation_architecture.md)** — full design doc: agent flow, data model, guardrails, model/infra tiering, zero-budget data stack, roadmap.
- **[SESSION_HANDOFF.md](SESSION_HANDOFF.md)** — detailed session-by-session build/validation log.
- **[AGENTS.md](AGENTS.md)** — instructions for AI agents working in this repo.
- **[evals/investment_preparation/](evals/investment_preparation/)** — practitioner-method sources, response evaluations, and preserved live-run evidence (including failures — several are regression fixtures, not to be "cleaned up").
