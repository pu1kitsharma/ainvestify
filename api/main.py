"""
FastAPI app entry point (plan §2). Local-only for this phase -- no auth,
no deployment config, CORS opened for a local Vite dev server only.

Run with: uvicorn api.main:app --reload
"""
from contextlib import asynccontextmanager
from pathlib import Path

import anyio.to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import compilation, dashboard, deals, investors, leads, operations, prompt, research, review

# agents/analytics_agent.py writes chart PNGs to memo_output/{deal_id}/charts/
# and stores that relative path as ChartArtifact.storage_uri (and inside a
# compiled document's structured_data). Until this mount, that path was a
# real file on disk with no HTTP route to it at all -- the Documents tab's
# <img src="/memo_output/..."> would have silently 404'd forever.
MEMO_OUTPUT_ROOT = Path(__file__).parent.parent / "memo_output"

# Every sync `def` endpoint/dependency in this app (all of them -- see
# api/deps.get_store's own docstring on why sqlite3 needs that) runs via
# Starlette's run_in_threadpool, which is anyio.to_thread.run_sync under a
# shared CapacityLimiter. 40 matches anyio's own default; set explicitly
# rather than left implicit so a real concurrent workload (several analysts,
# or one analyst with several browser tabs open on different deals) has a
# documented, intentional ceiling to tune instead of an unexamined default.
# Concurrency-critical work under this pool: SQLite access (WAL mode +
# busy_timeout in store.py, so concurrent requests wait/retry instead of
# erroring), PDF/Excel ingestion, matplotlib chart rendering, and network
# calls to Ollama/GitHub/HN/SEC EDGAR/Wikipedia.
THREAD_POOL_SIZE = 40


@asynccontextmanager
async def lifespan(app: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = THREAD_POOL_SIZE
    yield


TAGS_METADATA = [
    {"name": "leads", "description": "Deal Sourcing Agent (§5.8): discover candidate companies, "
        "human keep/dismiss review, promote a kept lead into a real Deal. A lead never touches "
        "ExtractionResult until promoted."},
    {"name": "deals", "description": "Deal lifecycle writes: create a deal, sign the mandate, "
        "upload a document (ingestion), run extraction, read the audit log. GET list/detail live "
        "under `dashboard`; review decisions live under `review`."},
    {"name": "dashboard", "description": "Read-only deal summaries for the dashboard view."},
    {"name": "review", "description": "Human Review Checkpoint (§5.5): per-field approve/edit/"
        "reject on an ExtractionResult, cap-table/funding-history block review, and the bounded "
        "2-retry reject loop that re-invokes extraction with the reviewer's note."},
    {"name": "research", "description": "Market Research Agent (§5.4): run live external-signal "
        "lookups for a deal, list findings, per-finding approve/reject, mark-reviewed."},
    {"name": "compilation", "description": "Compilation Agent (§5.7): compile the CIM, the "
        "teaser's two-step draft + safe-to-send confirm, the pro-forma with an optional growth-"
        "rate override, rerun analytics, and fetch the resulting document suite."},
    {"name": "investors", "description": "Investor / demand-book record-keeping (§5.9 Roadshow "
        "stage). Pure record-keeping only -- this never contacts an investor or sends anything."},
    {"name": "operations", "description": "Local operating workspaces for a shortlisted company: "
        "AI-prepared research/pitch/readiness drafts and evidence-backed reviews. No external "
        "sending, signing, or money movement."},
    {"name": "prompt", "description": "Free-text directive classification -- the API-native "
        "equivalent of `main.py`'s CLI prompt router."},
]

app = FastAPI(
    title="AInvestify API",
    description=(
        "AI-driven sourcing, incubation, and fundraising-support pipeline for early-stage "
        "companies -- boutique-IB-style document packaging, not a fund screening deals for its "
        "own book. Lifecycle: **source** candidate companies -> a human **promotes** a lead into "
        "a deal -> **ingest** documents -> **extract** structured metrics with mandatory source "
        "citations -> **human review** -> **research** external corroboration -> **compile** a "
        "cited, reviewable document suite (CIM / teaser / pro-forma).\n\n"
        "Every extracted numeric field carries a source citation or stays `null` -- never "
        "inferred from a typical value. Human review/sign-off is mandatory before any document "
        "is finalized. This system does not itself contact investors, negotiate terms, or run "
        "a raise -- that stays a human-led activity.\n\n"
        "Phase 0: local-only, no auth, CORS open only to the local Vite dev server."
    ),
    version="0.1.0",
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(deals.router)
app.include_router(review.router)
app.include_router(research.router)
app.include_router(investors.router)
app.include_router(leads.router)
app.include_router(operations.router)
app.include_router(prompt.router)
app.include_router(compilation.router)

# check_dir=False: memo_output/ is created lazily by the first chart/memo
# compile, not guaranteed to exist at app startup (e.g. right after `rm -rf
# memo_output` during test cleanup) -- StaticFiles would otherwise refuse to
# mount at all until the directory existed.
app.mount("/memo_output", StaticFiles(directory=str(MEMO_OUTPUT_ROOT), check_dir=False), name="memo_output")


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}
