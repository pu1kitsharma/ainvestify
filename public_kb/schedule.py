"""Durable, rights-gated source refresh jobs for the single-node public KB.

The external hourly timer calls claim_due; no background timer lives in the API.
Jobs are leases, and a successful cursor moves only after collection and indexing.
"""
from __future__ import annotations

import json
import time
import uuid

from public_kb.ingestion import PublicIngestion

CADENCE = {"announcement": 21600, "directory": 43200,
           "profile": 43200, "official": 43200}
SCHEMA = """
CREATE TABLE IF NOT EXISTS refresh_policy (
 source_id TEXT PRIMARY KEY REFERENCES sources(id), kind TEXT NOT NULL,
 cadence_seconds INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 next_due REAL NOT NULL DEFAULT 0,
 last_success REAL, last_error TEXT
);
CREATE TABLE IF NOT EXISTS refresh_job (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 due_at REAL NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 retry_at REAL, owner TEXT, lease_until REAL, result_sha256 TEXT,
 created_at REAL NOT NULL, finished_at REAL,
 UNIQUE(source_id,due_at)
);
CREATE TABLE IF NOT EXISTS collection_event (
 id INTEGER PRIMARY KEY, at REAL NOT NULL, job_id TEXT, source_id TEXT NOT NULL,
 phase TEXT NOT NULL, outcome TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}'
);
"""


def ensure_schema(kb: PublicIngestion):
    kb.conn.executescript(SCHEMA)


def set_policy(kb: PublicIngestion, source_id: str, kind: str, *, cadence_seconds=None,
               active=True):
    """Only an already reviewed, enabled source can enter the due queue."""
    ensure_schema(kb)
    kb.approved_source(source_id)
    if kind not in CADENCE:
        raise ValueError("Unsupported public source class")
    cadence = cadence_seconds or CADENCE[kind]
    if cadence < CADENCE[kind]:
        raise ValueError("Source cadence cannot be faster than its class policy")
    with kb.conn:
        kb.conn.execute("""INSERT INTO refresh_policy(source_id,kind,cadence_seconds,active)
            VALUES (?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
            kind=excluded.kind,cadence_seconds=excluded.cadence_seconds,
            active=MAX(active,excluded.active)""",
            (source_id, kind, cadence, int(active)))


def _event(kb, source_id, phase, outcome, *, job_id=None, now=None, **detail):
    kb.conn.execute("""INSERT INTO collection_event(at,job_id,source_id,phase,outcome,detail)
        VALUES (?,?,?,?,?,?)""", (time.time() if now is None else now, job_id,
        source_id, phase, outcome, json.dumps(detail, sort_keys=True)))


def claim_due(kb: PublicIngestion, *, now=None):
    """Atomically enqueue and lease one due job; two workers cannot claim it."""
    ensure_schema(kb)
    now = time.time() if now is None else now
    owner = uuid.uuid4().hex
    kb.conn.execute("BEGIN IMMEDIATE")
    try:
        for source_id, due_at in kb.conn.execute("""SELECT source_id,next_due FROM refresh_policy
            WHERE active=1 AND next_due<=? ORDER BY next_due,source_id""", (now,)).fetchall():
            try:
                kb.approved_source(source_id)
            except PermissionError:
                _event(kb, source_id, "schedule", "blocked_rights", now=now)
                continue
            active = kb.conn.execute("""SELECT 1 FROM refresh_job WHERE source_id=?
                AND state IN ('pending','running','failed') LIMIT 1""", (source_id,)).fetchone()
            if not active:
                job_id = uuid.uuid4().hex
                kb.conn.execute("""INSERT OR IGNORE INTO refresh_job
                    (id,source_id,due_at,state,created_at) VALUES (?,?,?,'pending',?)""",
                    (job_id, source_id, due_at, now))
                if kb.conn.execute("SELECT changes()").fetchone()[0]:
                    _event(kb, source_id, "schedule", "enqueued", job_id=job_id, now=now,
                           due_at=due_at)
        row = kb.conn.execute("""SELECT j.id,j.source_id,j.attempts FROM refresh_job j
            JOIN refresh_policy p ON p.source_id=j.source_id
            JOIN sources s ON s.id=j.source_id
            WHERE (j.state='pending' OR (j.state='failed' AND j.retry_at<=?)
               OR (j.state='running' AND j.lease_until<=?))
              AND p.active=1
              AND s.enabled=1 AND s.automated_access=1 AND s.retention=1
              AND s.inference_processing=1 AND s.investor_reuse=1
            ORDER BY j.due_at,j.created_at LIMIT 1""", (now, now)).fetchone()
        if row:
            job_id, source_id, attempts = row
            try:
                kb.approved_source(source_id)
            except PermissionError:
                row = None
            else:
                kb.conn.execute("""UPDATE refresh_job SET state='running',owner=?,
                    lease_until=?,attempts=attempts+1 WHERE id=?""", (owner, now+120, job_id))
                _event(kb, source_id, "fetch", "started", job_id=job_id, now=now,
                       attempt=attempts+1)
        kb.conn.commit()
        return (row[0], row[1], owner) if row else None
    except Exception:
        kb.conn.rollback()
        raise


def finish(kb: PublicIngestion, job_id: str, owner: str, *, digest=None, error=None, now=None):
    """Advance next_due only for a fully indexed successful source refresh."""
    now = time.time() if now is None else now
    kb.conn.execute("BEGIN IMMEDIATE")
    try:
        row = kb.conn.execute("""SELECT j.source_id,j.attempts,p.cadence_seconds
            FROM refresh_job j JOIN refresh_policy p ON p.source_id=j.source_id
            WHERE j.id=? AND j.state='running' AND j.owner=?""", (job_id, owner)).fetchone()
        if not row:
            raise ValueError("Refresh job lease was lost")
        source_id, attempts, cadence = row
        if error is None:
            kb.conn.execute("""UPDATE refresh_job SET state='done',owner=NULL,
                lease_until=NULL,result_sha256=?,finished_at=? WHERE id=?""",
                (digest, now, job_id))
            kb.conn.execute("""UPDATE refresh_policy SET last_success=?,next_due=?,
                last_error=NULL WHERE source_id=?""", (now, now+cadence, source_id))
            _event(kb, source_id, "refresh", "completed", job_id=job_id, now=now,
                   source_version=digest)
        else:
            retry = now + min(3600, 60 * 2 ** min(attempts-1, 6))
            kb.conn.execute("""UPDATE refresh_job SET state='failed',owner=NULL,
                lease_until=NULL,retry_at=? WHERE id=?""", (retry, job_id))
            kb.conn.execute("UPDATE refresh_policy SET last_error=? WHERE source_id=?",
                            (str(error)[:300], source_id))
            _event(kb, source_id, "refresh", "failed", job_id=job_id, now=now,
                   error=str(error)[:300], retry_at=retry)
        kb.conn.commit()
    except Exception:
        kb.conn.rollback()
        raise


def status(kb: PublicIngestion, *, now=None):
    ensure_schema(kb)
    now = time.time() if now is None else now
    rows = kb.conn.execute("""SELECT p.source_id,p.kind,p.next_due,p.last_success,
        p.last_error,j.state,j.retry_at,p.active FROM refresh_policy p LEFT JOIN refresh_job j
        ON j.source_id=p.source_id AND j.state IN ('pending','running','failed')
        ORDER BY p.source_id""").fetchall()
    return [dict(source_id=r[0], kind=r[1], next_due=r[2], last_success=r[3],
                 last_error=r[4], job_state=r[5], retry_at=r[6], active=bool(r[7]),
                 overdue=bool(r[7] and r[2] <= now and r[5] != 'running')) for r in rows]
