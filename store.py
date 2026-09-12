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
from typing import Optional, Union

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
"""


class Store:
    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB_PATH):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

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

    def list_leads(self, tenant_id: str, status: Optional[str] = None) -> list[SourcedLead]:
        rows = self.conn.execute(
            "SELECT data FROM sourced_leads WHERE tenant_id = ? ORDER BY id", (tenant_id,)
        ).fetchall()
        leads = [SourcedLead.model_validate_json(r[0]) for r in rows]
        if status is not None:
            leads = [l for l in leads if l.status.value == status]
        return leads

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
