# ainvestify

An AI-driven, multi-agent system for worldwide startup discovery, company research and due diligence, evidence-backed investment suggestions, and preparation of investor materials for fundraising. It supports both investors evaluating opportunities and companies preparing a raise.

Lifecycle: **discover** candidates → **follow** permitted company and announcement sources → **reconcile** identity, funding and status history → **perform due diligence** on market, product, team, finances and risks → **review** an evidence-backed investment suggestion → **promote** a company into a deal room → **prepare** cited, reviewable investor materials. The existing discovery and room workflows implement only parts of this lifecycle; the full diligence and recommendation gate is not accepted.

Every substantive numeric claim must carry traceable evidence or remain explicitly
missing/illustrative; a typical value cannot become a company fact. Human
review/sign-off is mandatory before a document is released. This system does
not contact investors, negotiate terms or run a raise.

**Status (4 October 2026): not production-ready.** Start with [AGENTS.md](AGENTS.md),
then [NEXT_AGENT.md](NEXT_AGENT.md) for the latest tested-code/live-acceptance split.
Historical success notices do not establish current investment quality.

The installed local `qwen3.5:9b` produced synthetic intro and pitch PPTX/PDF pairs
and an IM DOCX/PDF pair that passed structural and text-pair checks. The last completed live
semantic material review remains blocked by wrong-source selections, and visual
inspection found sparse slides and a dense memo. These are diagnostic outputs,
not accepted investor materials. Code tests, PDF text parity and a passing
model self-review cannot replace independent content, financial and visual review.

## Current plans

- [Local-to-cloud release plan](LOCAL_TO_CLOUD_RELEASE_PLAN.md): controlling product,
  architecture, milestones, mandatory artifact validation and later private AWS.
- [Financial projections](FINANCIAL_PROJECTIONS_PLAN.md): supplied models, formulas,
  recalculation, estimates and scenario XLSX.
- [Public knowledge base](deployment/PUBLIC_KNOWLEDGE_BASE_PLAN.md): source rights,
  incremental collection, Elasticsearch and evidence reuse.

The active public KB is a narrow rights-approved pilot: six StartupDB company
detail sources with 23 publisher-reported funding observations, all with unknown
round-completion status. Its source registry, collection, immutable staging,
structured claim projection and Elasticsearch passage sink are implemented.
MCA Company Master Data/OGD identity import, startups.gallery scheduling and
broad worldwide coverage are not enabled. A discovery lead or historical funding
observation is preliminary, never a diligence-complete investment suggestion.

Product scope is worldwide and follows the user's investment brief. India
pre-seed/seed remains a pilot regression case. The required material set is an
editable intro deck, pitch deck and investment memorandum, each with a matching
PDF. A projection XLSX is conditional on a supplied company model or an explicit
request backed by sufficient reviewed inputs. Missing financials must be disclosed;
forecasts and financial charts cannot be invented. Implement locally first and
qualify private self-hosted cloud inference later. The runtime records exported-file
inspection and enforces exact-package release/download checks. Missing mandatory
validators block final release.

The target core experience is a deal room that automatically prepares evidence,
financials and materials upon activation. The public KB supports both discovery
and room research; private uploads stay isolated. Every substantive output must
have traceable evidence, calculations or explicitly supported forecast assumptions.
Google OIDC sign-in, opaque server sessions and private sandbox provisioning are
implemented. Client registration is still required for live login. Tenant/reviewer
headers no longer authenticate requests, and the public artifact mount is removed.
Legacy data is not assigned to the first registrant. See handoff §48 for the exact
implementation and qualification limits; full L1 acceptance is not claimed.

## Setup

Preparation now defaults to local inference without hosted fallback. The
[public research setup](deployment/PUBLIC_RESEARCH_SETUP.md) describes a
historical optional adapter, not the target self-hosted KB. No AWS deployment or
live investment-quality acceptance is implied.

For Google login, register a **Web application** OAuth client with Google and set
`OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` in the backend environment, outside source
control. The issuer defaults to `https://accounts.google.com`; only identity scopes
are requested. Never paste the secret into chat or commit it.

Set `APP_ORIGIN` to the exact frontend origin. The registered callback is always
`<APP_ORIGIN>/api/auth/callback`. Prefer trusted local HTTPS. For explicitly isolated
loopback development only, use `APP_ENV=development`, `ALLOW_LOOPBACK_HTTP=1` and
`APP_ORIGIN=http://127.0.0.1:5173` when using `--local-dev`, and register
`http://127.0.0.1:5173/api/auth/callback` with Google. Temporary local login
accepts either `127.0.0.1:5173` or `localhost:5173`; Google login uses the
canonical `127.0.0.1` callback. Non-loopback HTTP and relaxed production settings
are rejected. This is sign-in only, not Google Drive access.

Use the project environment: `source .venv/bin/activate` (or create it first with
`python3 -m venv .venv` and install requirements). `scripts/serve_local.py` now starts
one separate durable room worker; `--without-worker` is available when supervising
`scripts/run_room_worker.py --watch` separately. Access logging is disabled to keep
callback codes out of URL logs. The API remains on loopback without reload.
Do not run a worker against the live DB until ownership and local configuration
are intentional. New authenticated users start with empty sandboxes; no automatic
legacy ownership migration exists.
For the local Vite frontend, start the backend with
`.venv/bin/python scripts/serve_local.py --local-dev --without-worker` while
ownership is unverified. This sets only the explicit loopback development origin;
Google OAuth client credentials still need to be supplied securely in the backend
environment.

The `--local-dev` option also enables a **temporary user ID/password** sign-in
choice on the local login screen. It is restricted to loopback development and
is unavailable in production. Create a fresh isolated sandbox with
`APP_ENV=development ALLOW_LOOPBACK_HTTP=1 LOCAL_DEV_PASSWORD_LOGIN=1 APP_ORIGIN=http://127.0.0.1:5173 .venv/bin/python scripts/create_local_dev_user.py --user-id temporary`.
The script prints a mode-0600 local credential-file path; it never prints the
password to routine server logs. Keep that file private. Passwords are stored
as salted PBKDF2 verifiers and session/CSRF tokens only as hashes in SQLite.
This temporary login does not satisfy the OIDC release requirement or migrate
any legacy data into the new sandbox.

Room activation is exposed at `POST /api/rooms/from-lead/{lead_id}/activate`; direct
entry uses `POST /api/rooms`. The UI activates the room on opening. Unchanged work
reuses its job; changed inputs fence obsolete work. Inspect states with
`GET /api/rooms/{id}`. Artifact previews require authentication. Final downloads
recheck trusted package manifests, actual bytes, current inputs and reviewer grants.

The room UI now shows each durable checkpoint, public KB rights status, local
review findings and release blockers. It lists preview links only for artifacts
matching the latest job's input revision. The older Documents page is explicitly
historical and read-only: retired compilation actions and misleading approval
claims have been removed. The backend still needs a concise package-level
release/reviewer summary and citation-level semantic findings in the room API
before the frontend can show exact accepted-package status or a useful finding
drilldown. No current room draft is represented as ready to send.

Fresh semantic material reviews use a versioned `semantic_v8` request. For each
model-selected slide sentence, the request lists only memo spans sharing its
cited source IDs; software binds the selected exact span and rejects any other
index. The local model still decides whether a defect exists and authors the
finding. Historical review requests retain their recorded contracts and exact
replay. This is a source-binding improvement, not an independent assessment of
investment quality.

Private LibreOffice conversion now uses a short job-local 0700 directory and
Unix IPC socket. Synthetic intro/pitch and revised IM editable/PDF pairs passed
page and text checks, with privacy canaries for sibling files and socket/network
access. Visual parity and complete production Office qualification remain open.
The separate bundled UNO executable failed qualification; do not relax private
isolation to make it pass. See [NEXT_AGENT.md](NEXT_AGENT.md) and the retained
reports under ignored `runtime_qualification/` for exact scope.

1. Install [Ollama](https://ollama.com/download) and confirm `ollama serve` is running. Pull the models you intend to route to (see **Model configuration** below) — nothing is downloaded automatically.
2. `pip install -r requirements.txt` (add `-r requirements-dev.txt` for `pytest`/`httpx` to run the test suite).
3. Backend: `python3 scripts/serve_local.py` — starts the FastAPI app on `http://localhost:8000` **without auto-reload**. Check active jobs before restarting. For the temporary local account, use the `--local-dev --without-worker` form above.
4. Frontend: `cd frontend && npm install && npm run dev` — Vite dev server on `http://localhost:5173`, with `/api` proxied to the backend.
5. CLI entry point (bypasses the web UI entirely): `python3 main.py "<what you want to do>"` — e.g. `"find promising fintech companies to incubate"` or `"screen this deal, I have the pitch deck ready"`.

### Model configuration

Preparation defaults to local Ollama. Private room workers explicitly use local
inference. Product model selection rejects Claude Pro, Anthropic API and DeepSeek;
historical provider modules remain in the tree but are not approved response routes.
There is no automatic model download. Do not provide private room data to hosted
inference.

| Variable | Purpose | Default |
|---|---|---|
| `SOURCING_MODEL` | Short extraction / classification tasks (lead routing, directive classification) | `phi4-mini` |
| `REASONING_MODEL` | Analytical work, screening, retries, review — thinking enabled | `qwen3:8b` (`qwen3:14b` auto-selected on machines with ≥24GB RAM) |
| `PREPARATION_MODEL` | Fast preparation route for operations drafts | see `agents/inference/local_models.py` |
| `PREPARATION_PROVIDER` | Public reasoning provider; room-private workers always use local | `local` |
| `ELASTICSEARCH_URL` / `ELASTICSEARCH_API_KEY_FILE` / `ELASTICSEARCH_CA_FILE` | Controlled public KB/ES connection and TLS/authentication | unset |
| `REVIEW_MODEL` / `ESCALATION_MODEL` | Alternate thinking models for review/escalation stages | falls back to `REASONING_MODEL` |
| `RESEARCH_AGENT_CONTACT` | Real `"YourOrg contact@email.com"` — SEC EDGAR and Wikipedia both hard-require an identifying User-Agent per their published policies (Wikipedia 403s without one) | placeholder, must be set before relying on either beyond local smoke-testing |
| `PREPARATION_MAX_SECONDS` | Time budget for the preparation path | see `agents/inference/local_models.py` |
| `DISCOVERY_PLAYWRIGHT_MODULE` | Path to an installed Playwright module, for the browser regression scripts only (`scripts/check_discovery_ui.cjs`, `scripts/check_operations_ui.cjs`) | none |

Historical provider configuration remains for compatibility. It is not part of
the local-model product path or an instruction to configure hosted inference.

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

The FastAPI app (`api/main.py`) exposes current routes through OpenAPI. The
historical deal/lead route summary below documents existing endpoints, including
legacy workflows; it does not establish that every workflow is qualified for
local-model-only investor output. Prefer the live schema and
[`api/routers/rooms.py`](api/routers/rooms.py) for deal-room behavior.

- **[`/docs`](http://localhost:8000/docs)** (Swagger UI) — expand any endpoint, fill a real request, **Try it out** against the live local backend. `/redoc` gives a read-only narrative view of the same schema.
- **[`/openapi.json`](http://localhost:8000/openapi.json)** — the raw OpenAPI 3.1 spec.
- **[`api/postman_collection.json`](api/postman_collection.json)** — import into Postman/Insomnia for a ready request tree with example bodies. Regenerate after a schema change: `python3 scripts/export_postman_collection.py` (fetches `/openapi.json` live).

All routes are mounted under `/api`. `GET /api/health` returns `{"status": "ok"}` for a public liveness check. Business routes require a server-side session; writes require the session's CSRF token and exact configured Origin. Tenant/reviewer headers have no authority. The frontend uses the same-origin `/api` proxy.

### `rooms` — active deal-room workflow

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
| `POST` | `/api/deals/{deal_id}/compile/proforma` | Legacy pro-forma route; not qualified as a current investor projection |
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

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m pytest -q tests/research tests/delivery tests/api/test_rooms.py tests/api/test_room_financial_phase.py tests/analysis/test_workbook_reconciliation.py tests/analysis/test_private_financial_worker.py tests/discovery/test_kb_candidate.py -p no:cacheprovider
cd frontend && npm run build && npm run lint
```

The focused research/delivery/room/financial/KB suite most recently passed
676 tests with 5 skipped. That code result is separate from live model and
investor acceptance. Local model diagnostics require a running Ollama instance;
their raw responses and failure reports are retained under ignored
`runtime_qualification/`. Do not overwrite a failed run to claim success.

Live/manual checks (need Ollama running, hit real networks — not part of the offline suite):

```
python3 scripts/smoke_web_sourcing.py --brief "Agricultural companies making solar dryers" --geography India --max-pages 2
python3 scripts/smoke_operations.py
node scripts/check_discovery_ui.cjs      # needs Playwright; set DISCOVERY_PLAYWRIGHT_MODULE if not on the default path
node scripts/check_operations_ui.cjs
```

## Further reading

- [AGENTS.md](AGENTS.md): current repository instructions and reading order.
- [SESSION_HANDOFF.md](SESSION_HANDOFF.md): dated implementation, failures and validation history.
- [CLAUDE.md](CLAUDE.md) and [legacy architecture](deal_automation_architecture.md): historical module/design context; current plans take precedence.
- [evals/investment_preparation/](evals/investment_preparation/): retained practitioner references, evaluations and failure fixtures. Large unlinked historical JSON snapshots are preserved byte-for-byte in the [evaluation archive](evals/investment_preparation/section-workflows/ARCHIVE.md); test fixtures and linked reports remain directly readable.
