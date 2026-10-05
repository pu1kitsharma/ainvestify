# API reference


The FastAPI app (`api/main.py`) exposes current routes through OpenAPI. The
historical deal/lead route summary below documents existing endpoints, including
legacy workflows; it does not establish that every workflow is qualified for
local-model-only investor output. Prefer the live schema and
[`api/routers/rooms.py`](api/routers/rooms.py) for deal-room behavior.

- **[`/docs`](http://localhost:8000/docs)** (Swagger UI) — expand any endpoint, fill a real request, **Try it out** against the live local backend. `/redoc` gives a read-only narrative view of the same schema.
- **[`/openapi.json`](http://localhost:8000/openapi.json)** — the raw OpenAPI 3.1 spec.
- **[`api/postman_collection.json`](api/postman_collection.json)** — import into Postman/Insomnia for a ready request tree with example bodies. Regenerate after a schema change: `python3 scripts/export_postman_collection.py` (fetches `/openapi.json` live).

All routes are mounted under `/api`. `GET /api/health` returns `{"status": "ok"}` for a public liveness check. Business routes require a server-side session; writes require the session's CSRF token and exact configured Origin. Tenant/reviewer headers have no authority. The frontend uses the same-origin `/api` proxy.

## `rooms` — active deal-room workflow

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/rooms/from-lead/{lead_id}/activate` | Start or reuse a private room job from a lead |
| `POST` | `/api/rooms/from-public-kb/{source_id}/activate` | Import one public KB company into the user's private sandbox |
| `POST` | `/api/rooms` | Start a direct company room |
| `GET` | `/api/rooms/{room_id}` | Inspect job, checkpoints and artifacts |
| `POST` | `/api/rooms/{room_id}/jobs/{job_id}/cancel` | Cancel queued/running work |
| `GET` | `/api/rooms/{room_id}/artifacts/{artifact_id}/preview` | Authenticated draft preview |
| `GET` | `/api/rooms/{room_id}/artifacts/{artifact_id}/download` | Final download, gated by exact-version validation and review |
| `POST` | `/api/rooms/{room_id}/validate` | Validate a current private package |
| `POST` | `/api/rooms/{room_id}/packages/{package_id}/release` | Release only when required gates pass |

The following lead/deal/operations table records existing legacy routes. It is
not a statement that those workflows pass the current local-model-only release
contract.

## `leads` — Deal Sourcing Agent (§5.8)

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

## `deals` — Deal lifecycle writes

Create a deal, sign the mandate, upload a document (ingestion), run extraction, read the audit log. Read-only list/detail live under `dashboard`; review decisions live under `review`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/deals` | Create a deal directly (without going through sourcing/promotion) |
| `POST` | `/api/deals/{deal_id}/mandate` | Record the Origination-stage mandate (`sign_mandate`) before ingestion can proceed |
| `POST` | `/api/deals/{deal_id}/documents` | Upload a PDF/Excel — deterministic ingestion (`agents.core.ingestion_agent`) into cited `DocBlock`s, no LLM |
| `POST` | `/api/deals/{deal_id}/extract` | Run the Structured Extraction Agent against the deal's ingested documents |
| `GET` | `/api/deals/{deal_id}/source-documents` | Raw ingested documents with their `DocBlock`s, for citation lookup |
| `GET` | `/api/deals/{deal_id}/audit-log` | Full audit trail for the deal |

## `dashboard` — Read-only deal summaries

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/deals` | List deal summaries (`status` filter) |
| `GET` | `/api/deals/{deal_id}` | Full deal detail |

## `review` — Human Review Checkpoint (§5.5 / §12)

Per-field approve/edit/reject on an `ExtractionResult`, cap-table/funding-history block review, and the bounded 2-retry reject loop that re-invokes extraction with the reviewer's note.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/deals/{deal_id}/review` | Current review state for every extracted field |
| `POST` | `/api/deals/{deal_id}/review/fields/{field_name}` | Approve / edit / reject one scalar field |
| `POST` | `/api/deals/{deal_id}/review/cap-table` | Block-level review decision on the cap table |
| `POST` | `/api/deals/{deal_id}/review/funding-history` | Block-level review decision on funding history |

## `research` — Market Research Agent (§5.4)

Live external-signal lookups for a deal (GitHub, HN/Algolia, SEC EDGAR, Wikipedia, plus sector-notes RAG), each finding reviewed before it reaches a memo.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/deals/{deal_id}/research/run` | Run live external-signal lookups for the deal |
| `GET` | `/api/deals/{deal_id}/research` | List findings |
| `POST` | `/api/deals/{deal_id}/research/{finding_id}/decision` | Approve/reject one finding |
| `POST` | `/api/deals/{deal_id}/research/mark-reviewed` | Mark the research stage complete |

## `compilation` — Compilation Agent (§5.7)

Compile the CIM, the teaser's two-step draft + safe-to-send confirm, the pro-forma with an optional growth-rate override, rerun analytics, and fetch the resulting document suite. All hard-refuse (`CompilationBlockedError`) unless `is_ready_for_compilation()` is true.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/deals/{deal_id}/compile/cim` | Compile the full comprehensive memo (NDA-gated) |
| `POST` | `/api/deals/{deal_id}/compile/teaser/draft` | Draft the anonymized pre-NDA teaser |
| `POST` | `/api/deals/{deal_id}/compile/teaser/{memo_id}/confirm` | Explicit human sign-off that the teaser draft doesn't leak identity, before it's released |
| `POST` | `/api/deals/{deal_id}/compile/proforma` | Legacy pro-forma route; not qualified as a current investor projection |
| `POST` | `/api/deals/{deal_id}/analytics/rerun` | Re-render charts against currently approved fields |
| `GET` | `/api/deals/{deal_id}/documents` | List every version of every document type (`document_type` filter) |
| `GET` | `/api/deals/{deal_id}/documents/latest` | Latest version of one `document_type` |

## `investors` — Demand-book record-keeping (§5.9 Roadshow)

Pure record-keeping — never contacts an investor or sends anything.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/deals/{deal_id}/investors` | Add an investor contact to the demand book |
| `GET` | `/api/deals/{deal_id}/investors` | View the demand book |

## `operations` — Company operating workspaces

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

## `prompt` — Free-text directive classification

The API-native equivalent of `main.py`'s CLI prompt router.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/prompt/classify` | Classify a free-text request into `source_leads` / `screen_deal` |
| `POST` | `/api/deals/{deal_id}/directive/preview` | Classify a free-text revision directive into one of the deal's valid next actions, for human confirmation before executing |

