"""
Persistence layer — backs architecture doc §6.1's aggregate entities.

Built now rather than deferred: the Planner Agent's interrupt/resume
mechanics (§5.5) aren't real if nothing survives a process restart. An
in-memory-only pipeline can pause on an `input()` call, but it can't
actually resume later, in a different process, the way §5.5 describes
("serializes state and waits"). SQLite is the whole story for Phase 0 --
single-process, local, zero-cost, zero-cloud, no server to run.

Every read is tenant-scoped by construction: each method takes `tenant_id`
and filters on it in the SQL WHERE clause itself, not just in the caller's
application logic. A caller that passes the wrong tenant_id for a real id
gets nothing back, not another tenant's data -- the same discipline
architecture doc §9 already requires of the FAISS index in §5.4.

Each entity is stored as one JSON blob (Pydantic's own serialization) per
row rather than normalized into columns -- pragmatic for Phase 0's
single-process, low-volume usage. Revisit if this becomes a real
concurrent-writer multi-tenant service.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Optional, Union

from schemas import (
    AuditEvent,
    ChartArtifact,
    Deal,
    DealSummary,
    Document,
    ExtractionResult,
    InvestorContact,
    MemoVersion,
    ResearchFinding,
    SourcedLead,
    CompanyProfile,
    WebSourcingRun,
)

DEFAULT_DB_PATH = Path(__file__).parent / "deal_automation.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, deal_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extraction_results (
    deal_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_findings (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, deal_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chart_artifacts (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, deal_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memo_versions (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, deal_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, deal_id TEXT NOT NULL,
    timestamp TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investor_contacts (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, deal_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sourced_leads (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_profiles (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, website TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id), UNIQUE (tenant_id, website)
);
CREATE TABLE IF NOT EXISTS dataset_snapshots (
    tenant_id TEXT NOT NULL, source_id TEXT NOT NULL, query TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source_id, query)
);
CREATE TABLE IF NOT EXISTS operating_workspaces (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, lead_id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id), UNIQUE (tenant_id, lead_id)
);
CREATE TABLE IF NOT EXISTS web_sourcing_runs (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
"""


class Store:
    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB_PATH):
        self.db_path = db_path
        # timeout=30: how long a connection waits for another connection's
        # write lock to clear before raising "database is locked" -- without
        # this, concurrent API requests (each opening their own Store, per
        # api/deps.get_store) hitting the same SQLite file can fail outright
        # under real concurrent load, not just run slowly.
        #
        # check_same_thread=False: found live under real concurrent load (a
        # ThreadPoolExecutor-driven test, not TestClient), not assumed --
        # FastAPI dispatches a sync generator dependency's setup (up to the
        # `yield`) and its teardown (after) as two separate
        # anyio.to_thread.run_sync jobs. Both land on *a* thread-pool worker,
        # but under concurrent load they are not guaranteed to be the *same*
        # worker, so a request can create this connection on one thread and
        # close() it on another. That's still safe here specifically because
        # each Store is used by exactly one request, strictly sequentially in
        # time (create -> use -> close, never two threads touching it at
        # once) -- sqlite3's default check_same_thread=True doesn't know
        # that, it just compares thread ids and raises unconditionally.
        self.conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=False)
        self.conn.executescript(_SCHEMA)
        # WAL: readers no longer block on a writer (and vice versa) the way
        # SQLite's default rollback-journal mode does -- the single biggest
        # lever for a multi-connection workload like concurrent API requests
        # against one local file. journal_mode is persisted in the database
        # file itself, so this is a one-time no-op after the first call.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def save_company(self, company: CompanyProfile) -> None:
        self.conn.execute(
            "INSERT INTO company_profiles (tenant_id, id, website, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(tenant_id, id) DO UPDATE SET website=excluded.website, data=excluded.data",
            (company.tenant_id, company.id, company.identity_key, company.model_dump_json()),
        )
        self.conn.commit()

    def get_company_by_website(self, tenant_id: str, website: str) -> Optional[CompanyProfile]:
        row = self.conn.execute(
            "SELECT data FROM company_profiles WHERE tenant_id=? AND website=?", (tenant_id, website)
        ).fetchone()
        return CompanyProfile.model_validate_json(row[0]) if row else None

    def save_web_run(self, run: WebSourcingRun) -> None:
        self.conn.execute(
            "INSERT INTO web_sourcing_runs (tenant_id, id, data) VALUES (?, ?, ?) "
            "ON CONFLICT(tenant_id, id) DO UPDATE SET data=CASE "
            "WHEN json_extract(web_sourcing_runs.data, '$.status')='cancel_requested' "
            "AND json_extract(excluded.data, '$.status')='running' "
            "THEN json_set(excluded.data, '$.status', 'cancel_requested') ELSE excluded.data END",
            (run.tenant_id, run.id, run.model_dump_json(exclude={"source_coverage"})),
        )
        self.conn.commit()

    def list_web_runs(self, tenant_id: str) -> list[WebSourcingRun]:
        rows = self.conn.execute(
            "SELECT data FROM web_sourcing_runs WHERE tenant_id=? ORDER BY rowid DESC LIMIT 20", (tenant_id,)
        ).fetchall()
        return [WebSourcingRun.model_validate_json(row[0]) for row in rows]

    def get_web_run(self, tenant_id: str, run_id: str) -> Optional[WebSourcingRun]:
        row = self.conn.execute(
            "SELECT data FROM web_sourcing_runs WHERE tenant_id=? AND id=?", (tenant_id, run_id)
        ).fetchone()
        return WebSourcingRun.model_validate_json(row[0]) if row else None

    # --- Deal ---------------------------------------------------------

    def save_deal(self, deal: Deal) -> None:
        self.conn.execute(
            "INSERT INTO deals (id, tenant_id, data) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (deal.id, deal.tenant_id, deal.model_dump_json()),
        )
        self.conn.commit()

    def get_deal(self, tenant_id: str, deal_id: str) -> Optional[Deal]:
        row = self.conn.execute(
            "SELECT data FROM deals WHERE id = ? AND tenant_id = ?", (deal_id, tenant_id)
        ).fetchone()
        return Deal.model_validate_json(row[0]) if row else None

    def list_deals(self, tenant_id: str) -> list[Deal]:
        rows = self.conn.execute(
            "SELECT data FROM deals WHERE tenant_id = ? ORDER BY id", (tenant_id,)
        ).fetchall()
        return [Deal.model_validate_json(r[0]) for r in rows]

    def list_deals_by_status(self, tenant_id: str, status: str) -> list[Deal]:
        return [d for d in self.list_deals(tenant_id) if d.status.value == status]

    def update_deal(self, tenant_id: str, deal_id: str, mutate: Callable[[Deal], None]) -> Optional[Deal]:
        """Atomic read-modify-write for a Deal: a plain get_deal() + mutate
        + save_deal() sequence is a real last-write-wins race under
        concurrent requests against the same deal -- two concurrent
        document uploads can each read document_ids=[], each locally append
        their own id, and whichever save_deal() commits second silently
        discards the first upload's id. BEGIN IMMEDIATE takes SQLite's write
        lock before the read, so a second concurrent caller blocks (up to
        the busy_timeout set in __init__) until this transaction commits,
        instead of interleaving with it. Used for the one call site
        (_run_ingest's document_ids.append) where a lost update is silent
        data loss rather than a merely-stale field a page refresh would
        fix -- see agents/planner_agent.py for why the other save_deal()
        call sites weren't converted to this (a documented, deliberate
        Phase 0 scope decision, not an oversight)."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT data FROM deals WHERE id = ? AND tenant_id = ?", (deal_id, tenant_id)
            ).fetchone()
            if row is None:
                self.conn.rollback()
                return None
            deal = Deal.model_validate_json(row[0])
            mutate(deal)
            self.conn.execute(
                "UPDATE deals SET data = ? WHERE id = ? AND tenant_id = ?",
                (deal.model_dump_json(), deal_id, tenant_id),
            )
            self.conn.commit()
            return deal
        except Exception:
            self.conn.rollback()
            raise

    # --- Document -------------------------------------------------------

    def save_document(self, document: Document) -> None:
        self.conn.execute(
            "INSERT INTO documents (id, tenant_id, deal_id, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (document.id, document.tenant_id, document.deal_id, document.model_dump_json()),
        )
        self.conn.commit()

    def get_document(self, tenant_id: str, document_id: str) -> Optional[Document]:
        row = self.conn.execute(
            "SELECT data FROM documents WHERE id = ? AND tenant_id = ?", (document_id, tenant_id)
        ).fetchone()
        return Document.model_validate_json(row[0]) if row else None

    def get_documents_for_deal(self, tenant_id: str, deal_id: str) -> list[Document]:
        rows = self.conn.execute(
            "SELECT data FROM documents WHERE deal_id = ? AND tenant_id = ?", (deal_id, tenant_id)
        ).fetchall()
        return [Document.model_validate_json(r[0]) for r in rows]

    # --- ExtractionResult (one live copy per deal) -----------------------

    def save_extraction_result(self, result: ExtractionResult) -> None:
        self.conn.execute(
            "INSERT INTO extraction_results (deal_id, tenant_id, data) VALUES (?, ?, ?) "
            "ON CONFLICT(deal_id) DO UPDATE SET data = excluded.data",
            (result.deal_id, result.tenant_id, result.model_dump_json()),
        )
        self.conn.commit()

    def get_extraction_result_with_raw(self, tenant_id: str, deal_id: str) -> tuple[Optional[ExtractionResult], Optional[str]]:
        """Same row get_extraction_result() returns, plus the exact raw JSON
        text read -- pass that text back into
        save_extraction_result_if_unchanged() as the compare-and-swap guard.
        Needed instead of a plain get+mutate+save because a review decision
        can trigger a real Ollama re-extraction call (apply_field_decision's
        reject branch) that takes a minute or more: holding a SQLite write
        lock for that whole duration (the BEGIN IMMEDIATE approach
        update_deal() uses) would block every other write in the database,
        not just this deal's -- WAL mode keeps readers unblocked, but a
        second writer would wait out the full busy_timeout and then fail.
        Optimistic concurrency never blocks a writer; it just detects, after
        the fact, whether the row changed underneath a slow caller."""
        row = self.conn.execute(
            "SELECT data FROM extraction_results WHERE deal_id = ? AND tenant_id = ?", (deal_id, tenant_id)
        ).fetchone()
        if row is None:
            return None, None
        return ExtractionResult.model_validate_json(row[0]), row[0]

    def save_extraction_result_if_unchanged(self, result: ExtractionResult, expected_raw: str) -> bool:
        """Compare-and-swap write: succeeds only if the row's JSON text is
        still exactly `expected_raw` (i.e. nothing else wrote to this deal's
        extraction result since the caller's get_extraction_result_with_raw
        call). Returns False on conflict -- the caller's mutation was
        computed against data that's no longer current, and must not be
        written over whatever the concurrent writer landed. See
        api/routers/review.py for how a False return becomes an HTTP 409
        rather than a silently discarded concurrent update."""
        cur = self.conn.execute(
            "UPDATE extraction_results SET data = ? WHERE deal_id = ? AND tenant_id = ? AND data = ?",
            (result.model_dump_json(), result.deal_id, result.tenant_id, expected_raw),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_extraction_result(self, tenant_id: str, deal_id: str) -> Optional[ExtractionResult]:
        row = self.conn.execute(
            "SELECT data FROM extraction_results WHERE deal_id = ? AND tenant_id = ?", (deal_id, tenant_id)
        ).fetchone()
        return ExtractionResult.model_validate_json(row[0]) if row else None

    # --- ResearchFinding --------------------------------------------------

    def save_research_findings(self, findings: list[ResearchFinding]) -> None:
        for f in findings:
            self.conn.execute(
                "INSERT INTO research_findings (id, tenant_id, deal_id, data) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (f.id, f.tenant_id, f.deal_id, f.model_dump_json()),
            )
        self.conn.commit()

    def get_research_findings(self, tenant_id: str, deal_id: str) -> list[ResearchFinding]:
        rows = self.conn.execute(
            "SELECT data FROM research_findings WHERE deal_id = ? AND tenant_id = ?", (deal_id, tenant_id)
        ).fetchall()
        return [ResearchFinding.model_validate_json(r[0]) for r in rows]

    # --- ChartArtifact ----------------------------------------------------

    def save_charts(self, charts: list[ChartArtifact]) -> None:
        for c in charts:
            self.conn.execute(
                "INSERT INTO chart_artifacts (id, tenant_id, deal_id, data) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (c.id, c.tenant_id, c.deal_id, c.model_dump_json()),
            )
        self.conn.commit()

    def get_charts(self, tenant_id: str, deal_id: str) -> list[ChartArtifact]:
        rows = self.conn.execute(
            "SELECT data FROM chart_artifacts WHERE deal_id = ? AND tenant_id = ?", (deal_id, tenant_id)
        ).fetchall()
        return [ChartArtifact.model_validate_json(r[0]) for r in rows]

    # --- MemoVersion ------------------------------------------------------

    def save_memo_version(self, memo: MemoVersion) -> None:
        self.conn.execute(
            "INSERT INTO memo_versions (id, tenant_id, deal_id, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (memo.id, memo.tenant_id, memo.deal_id, memo.model_dump_json()),
        )
        self.conn.commit()

    def get_memo_version(self, tenant_id: str, memo_id: str) -> Optional[MemoVersion]:
        """Single-row getter by id -- needed once a memo's draft and its
        safe-to-send confirmation become two separate calls (e.g. two
        separate API requests) instead of one in-memory object handed
        straight from generation to a same-process confirm prompt."""
        row = self.conn.execute(
            "SELECT data FROM memo_versions WHERE id = ? AND tenant_id = ?", (memo_id, tenant_id)
        ).fetchone()
        return MemoVersion.model_validate_json(row[0]) if row else None

    def get_memo_versions(self, tenant_id: str, deal_id: str) -> list[MemoVersion]:
        rows = self.conn.execute(
            "SELECT data FROM memo_versions WHERE deal_id = ? AND tenant_id = ? ORDER BY id",
            (deal_id, tenant_id),
        ).fetchall()
        return [MemoVersion.model_validate_json(r[0]) for r in rows]

    def list_memo_versions_by_type(self, tenant_id: str, deal_id: str, document_type: str) -> list[MemoVersion]:
        """Was a Python list-comprehension helper duplicated across three
        planner functions (compile_cim/generate_teaser_draft/apply_compile_
        proforma, each computing "existing versions of this type" to pick
        the next version_number) -- belongs here, not re-implemented per
        caller."""
        return [m for m in self.get_memo_versions(tenant_id, deal_id) if m.document_type == document_type]

    def get_latest_memo_version(self, tenant_id: str, deal_id: str, document_type: str) -> Optional[MemoVersion]:
        versions = self.list_memo_versions_by_type(tenant_id, deal_id, document_type)
        return max(versions, key=lambda m: m.version_number) if versions else None

    # --- AuditEvent -------------------------------------------------------

    def append_audit_events(self, events: list[AuditEvent]) -> None:
        for e in events:
            self.conn.execute(
                "INSERT INTO audit_log (id, tenant_id, deal_id, timestamp, data) VALUES (?, ?, ?, ?, ?)",
                (e.id, e.tenant_id, e.deal_id, e.timestamp, e.model_dump_json()),
            )
        self.conn.commit()

    def get_audit_log(self, tenant_id: str, deal_id: str) -> list[AuditEvent]:
        rows = self.conn.execute(
            "SELECT data FROM audit_log WHERE deal_id = ? AND tenant_id = ? ORDER BY timestamp",
            (deal_id, tenant_id),
        ).fetchall()
        return [AuditEvent.model_validate_json(r[0]) for r in rows]

    # --- SourcedLead ------------------------------------------------------

    def save_lead(self, lead: SourcedLead) -> None:
        self.conn.execute(
            "INSERT INTO sourced_leads (id, tenant_id, data) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (lead.id, lead.tenant_id, lead.model_dump_json()),
        )
        self.conn.commit()

    def get_lead(self, tenant_id: str, lead_id: str) -> Optional[SourcedLead]:
        row = self.conn.execute(
            "SELECT data FROM sourced_leads WHERE id = ? AND tenant_id = ?", (lead_id, tenant_id)
        ).fetchone()
        return SourcedLead.model_validate_json(row[0]) if row else None

    def list_leads(
        self, tenant_id: str, status: Optional[str] = None, web_run_only: bool = False
    ) -> list[SourcedLead]:
        rows = self.conn.execute(
            "SELECT data FROM sourced_leads WHERE tenant_id = ? ORDER BY id", (tenant_id,)
        ).fetchall()
        leads = [SourcedLead.model_validate_json(r[0]) for r in rows]
        if status is not None:
            leads = [l for l in leads if l.status.value == status]
        if web_run_only:
            # Found live: the older keyword-based discover_leads()/
            # discover_ib_targets() sourcing calls (still valid agent
            # capabilities, just no longer what the current Discover page
            # drives) leave leads with no web-sourcing-run association at
            # all. Repeated ad-hoc test searches during development left
            # ~200 such leads with no way to review them from the current
            # UI (it only ever shows one run's results, or the shortlist) --
            # inflating "awaiting review" counts with leads nobody has a
            # path to act on. Scope to leads a WebSourcingRun actually
            # produced, since that's what the current review workflow can
            # reach.
            run_lead_ids: set[str] = set()
            for run in self.list_web_runs(tenant_id):
                run_lead_ids.update(run.lead_ids)
            leads = [l for l in leads if l.id in run_lead_ids]
        return leads

    def get_lead_by_promoted_deal_id(self, tenant_id: str, deal_id: str) -> Optional[SourcedLead]:
        """The originating lead for a deal that was promoted from one, if
        any -- needed so research_deal's fresh public-web search isn't the
        only chance to surface a signal: the lead's own discovery_signals
        (e.g. a specific GitHub repo) were already real and already the
        reason this company was sourced in the first place, and were
        otherwise being silently discarded at promotion time."""
        for lead in self.list_leads(tenant_id):
            if lead.promoted_deal_id == deal_id:
                return lead
        return None

    # --- InvestorContact (demand book, §5 Roadshow stage) ------------------

    def save_investor_contact(self, contact: InvestorContact) -> None:
        self.conn.execute(
            "INSERT INTO investor_contacts (id, tenant_id, deal_id, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (contact.id, contact.tenant_id, contact.deal_id, contact.model_dump_json()),
        )
        self.conn.commit()

    def get_investor_contacts(self, tenant_id: str, deal_id: str) -> list[InvestorContact]:
        rows = self.conn.execute(
            "SELECT data FROM investor_contacts WHERE deal_id = ? AND tenant_id = ? ORDER BY id",
            (deal_id, tenant_id),
        ).fetchall()
        return [InvestorContact.model_validate_json(r[0]) for r in rows]

    def get_investor_contact(self, tenant_id: str, deal_id: str, investor_id: str) -> Optional[InvestorContact]:
        row = self.conn.execute(
            "SELECT data FROM investor_contacts WHERE id = ? AND deal_id = ? AND tenant_id = ?",
            (investor_id, deal_id, tenant_id),
        ).fetchone()
        return InvestorContact.model_validate_json(row[0]) if row else None

    # --- Dashboard read-model ----------------------------------------------

    def list_deals_with_summary(self, tenant_id: str, status: Optional[str] = None) -> list[DealSummary]:
        """One row per deal with cheap COUNT(*) rollups across the deal's
        related tables -- built so the dashboard can render deal cards
        without the frontend doing an N+1 fetch per deal (plan §3)."""
        deals = self.list_deals(tenant_id)
        if status is not None:
            deals = [d for d in deals if d.status.value == status]

        summaries = []
        for deal in deals:
            document_count = self.conn.execute(
                "SELECT COUNT(*) FROM documents WHERE deal_id = ? AND tenant_id = ?", (deal.id, tenant_id)
            ).fetchone()[0]
            research_finding_count = self.conn.execute(
                "SELECT COUNT(*) FROM research_findings WHERE deal_id = ? AND tenant_id = ?", (deal.id, tenant_id)
            ).fetchone()[0]
            memo_version_count = self.conn.execute(
                "SELECT COUNT(*) FROM memo_versions WHERE deal_id = ? AND tenant_id = ?", (deal.id, tenant_id)
            ).fetchone()[0]
            investor_count = self.conn.execute(
                "SELECT COUNT(*) FROM investor_contacts WHERE deal_id = ? AND tenant_id = ?", (deal.id, tenant_id)
            ).fetchone()[0]
            summaries.append(
                DealSummary(
                    deal=deal,
                    document_count=document_count,
                    research_finding_count=research_finding_count,
                    memo_version_count=memo_version_count,
                    investor_count=investor_count,
                )
            )
        return summaries


    def save_dataset_snapshot(self, snapshot):
        self.conn.execute("INSERT INTO dataset_snapshots VALUES (?, ?, ?, ?) ON CONFLICT(tenant_id, source_id, query) DO UPDATE SET data=excluded.data",
                          (snapshot.tenant_id, snapshot.source_id, snapshot.query, snapshot.model_dump_json()))
        self.conn.commit()

    def get_dataset_snapshot(self, tenant_id, source_id, query):
        from workflow_schemas import DatasetSnapshot
        row = self.conn.execute("SELECT data FROM dataset_snapshots WHERE tenant_id=? AND source_id=? AND query=?",
                                (tenant_id, source_id, query)).fetchone()
        return DatasetSnapshot.model_validate_json(row[0]) if row else None

    def list_dataset_snapshots(self, tenant_id):
        from workflow_schemas import DatasetSnapshot
        return [DatasetSnapshot.model_validate_json(r[0]) for r in self.conn.execute(
            "SELECT data FROM dataset_snapshots WHERE tenant_id=?", (tenant_id,)).fetchall()]

    def get_workspace(self, tenant_id, workspace_id=None, lead_id=None):
        from workflow_schemas import OperatingWorkspace
        column, value = ("id", workspace_id) if workspace_id else ("lead_id", lead_id)
        row = self.conn.execute(f"SELECT data FROM operating_workspaces WHERE tenant_id=? AND {column}=?",
                                (tenant_id, value)).fetchone()
        return OperatingWorkspace.model_validate_json(row[0]) if row else None

    def list_workspaces(self, tenant_id):
        from workflow_schemas import OperatingWorkspace
        return [OperatingWorkspace.model_validate_json(r[0]) for r in self.conn.execute(
            "SELECT data FROM operating_workspaces WHERE tenant_id=? ORDER BY id", (tenant_id,)).fetchall()]

    def save_workspace(self, workspace, expected_revision=None):
        next_revision = workspace.revision + 1
        data = workspace.model_copy(update={"revision": next_revision}).model_dump_json()
        if expected_revision is None:
            self.conn.execute("INSERT INTO operating_workspaces VALUES (?, ?, ?, ?, ?)",
                              (workspace.tenant_id, workspace.id, workspace.lead_id, next_revision, data))
        else:
            cursor = self.conn.execute("UPDATE operating_workspaces SET data=?, revision=? WHERE tenant_id=? AND id=? AND revision=?",
                                      (data, next_revision, workspace.tenant_id, workspace.id, expected_revision))
            if cursor.rowcount != 1:
                self.conn.rollback()
                raise ValueError("Workspace changed; reload before applying this action.")
        self.conn.commit()
        workspace.revision = next_revision
