"""Single-host durable queue: idempotency, lease fencing, checkpoints and revocation."""
from __future__ import annotations
import json
import secrets
import time

from security.identity import has_access

SCHEMA = """
CREATE TABLE IF NOT EXISTS room_jobs (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 actor_id TEXT NOT NULL, work_key TEXT NOT NULL UNIQUE, input_revision TEXT NOT NULL,
 state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
 phase TEXT NOT NULL DEFAULT 'legacy', phase_attempt INTEGER NOT NULL DEFAULT 0,
 lease_token TEXT, lease_until REAL, checkpoint TEXT NOT NULL DEFAULT '{}',
 error TEXT, created REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_room_job ON room_jobs(tenant_id,workspace_id)
 WHERE state IN ('queued','running');
"""
PHASE_CAPS = {"source_selection": 3, "financial_analysis": 9, "draft": 6, "correction": 3,
              "ledger": 5, "review": 2, "material_draft": 6, "material_review": 2,
              "material_remediation": 1, "material_re_review": 2, "render": 1,
              "analysis": 3, "legacy": 3}
PHASES = ("source_selection", "financial_analysis", "draft", "correction", "ledger", "review", "material_draft", "material_review", "material_remediation", "material_re_review", "render")
COLUMNS = "id,tenant_id,workspace_id,actor_id,work_key,input_revision,state,attempt,phase,phase_attempt,lease_token,lease_until,checkpoint,error,created".split(",")
SELECT_COLUMNS = ",".join(COLUMNS)


def _ensure_phase_columns(conn):
    """Keep pre-phase jobs on their original three-pass limit."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(room_jobs)")}
    if "phase" not in columns:
        conn.execute("ALTER TABLE room_jobs ADD COLUMN phase TEXT NOT NULL DEFAULT 'legacy'")
    if "phase_attempt" not in columns:
        conn.execute("ALTER TABLE room_jobs ADD COLUMN phase_attempt INTEGER NOT NULL DEFAULT 0")


def _phase_cap(job):
    if job["phase"] not in PHASE_CAPS:
        raise ValueError("Unknown room job phase")
    return PHASE_CAPS[job["phase"]]


def _next_phase(job, requested):
    current = job["phase"]
    if requested is None or requested == current:
        return current, job["phase_attempt"]
    if current == "legacy" or current == "render":
        raise ValueError("Room job phase cannot advance")
    # Jobs already in the former combined analysis phase keep their original
    # three-pass bound and can only finish at rendering.
    if current == "analysis":
        if requested != "render":
            raise ValueError("Room job phases must advance in order")
        return requested, 0
    if current == "material_review" and requested == "render":
        return requested, 0
    if requested != PHASES[PHASES.index(current) + 1]:
        raise ValueError("Room job phases must advance in order")
    return requested, 0


def record(row):
    if not row:
        return None
    result = dict(zip(COLUMNS, row))
    result["checkpoint"] = json.loads(result["checkpoint"])
    return result


def enqueue(conn, event):
    conn.execute("BEGIN IMMEDIATE")
    try:
        _ensure_phase_columns(conn)
        if not has_access(conn, event.actor_id, event.tenant_id):
            raise PermissionError("Room access revoked")
        row = conn.execute(f"SELECT {SELECT_COLUMNS} FROM room_jobs WHERE work_key=?", (event.idempotency_key(),)).fetchone()
        if not row:
            running = conn.execute("SELECT id FROM room_jobs WHERE tenant_id=? AND workspace_id=? AND state IN ('queued','running')",
                (event.tenant_id, event.workspace_id)).fetchone()
            pending=conn.execute("SELECT count(*) FROM room_jobs WHERE tenant_id=? AND state IN ('queued','running')",
                (event.tenant_id,)).fetchone()[0]
            if pending-int(bool(running))>=3:raise ValueError('Three room jobs are already active in this sandbox')
            if running:
                conn.execute("UPDATE room_jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,error='inputs_superseded' WHERE id=?",
                    (running[0],))
            job_id = "job_" + secrets.token_hex(16)
            conn.execute("""INSERT INTO room_jobs(id,tenant_id,workspace_id,actor_id,work_key,input_revision,state,phase,created)
                VALUES (?,?,?,?,?,?,'queued','source_selection',?)""", (job_id,event.tenant_id,event.workspace_id,
                event.actor_id,event.idempotency_key(),event.input_revision,time.time()))
            row = conn.execute(f"SELECT {SELECT_COLUMNS} FROM room_jobs WHERE id=?", (job_id,)).fetchone()
        conn.commit()
        return record(row)
    except Exception:
        conn.rollback()
        raise


def claim(conn, *, now=None, lease_seconds=150):
    now = time.time() if now is None else now
    conn.execute("BEGIN IMMEDIATE")
    try:
        _ensure_phase_columns(conn)
        conn.execute("""UPDATE room_jobs SET state=CASE WHEN phase_attempt>=CASE phase
                WHEN 'source_selection' THEN 3 WHEN 'financial_analysis' THEN 9 WHEN 'draft' THEN 6
                WHEN 'correction' THEN 3 WHEN 'ledger' THEN 5 WHEN 'review' THEN 2
                WHEN 'material_draft' THEN 6 WHEN 'material_review' THEN 2
                WHEN 'material_remediation' THEN 1 WHEN 'material_re_review' THEN 2
                WHEN 'render' THEN 1 ELSE 3 END
                OR (phase='legacy' AND attempt>=3)
                THEN 'failed' ELSE 'queued' END,
            lease_token=NULL,lease_until=NULL,error='worker_lease_expired'
            WHERE state='running' AND lease_until<=?""", (now,))
        rows = conn.execute(f"SELECT {SELECT_COLUMNS} FROM room_jobs WHERE state='queued' ORDER BY created,id").fetchall()
        for row in rows:
            job = record(row)
            if job["phase_attempt"] >= _phase_cap(job) or (job["phase"] == "legacy" and job["attempt"] >= 3):
                conn.execute("UPDATE room_jobs SET state='failed',error='phase_attempt_limit' WHERE id=?", (job["id"],))
                continue
            if not has_access(conn, job["actor_id"], job["tenant_id"]):
                conn.execute("UPDATE room_jobs SET state='cancelled',error='access_revoked' WHERE id=?", (job["id"],))
                continue
            lease = secrets.token_hex(24)
            conn.execute("UPDATE room_jobs SET state='running',attempt=attempt+1,phase_attempt=phase_attempt+1,lease_token=?,lease_until=? WHERE id=?",
                (lease,now+lease_seconds,job["id"]))
            row = conn.execute(f"SELECT {SELECT_COLUMNS} FROM room_jobs WHERE id=?", (job["id"],)).fetchone()
            conn.commit()
            return record(row)
        conn.commit()
        return None
    except Exception:
        conn.rollback()
        raise


def checkpoint(conn, job, data, *, state="running", error=None, now=None, phase=None):
    if state not in {"running", "queued", "completed", "awaiting_input", "blocked", "failed"}:
        raise ValueError("Unsupported job transition")
    if phase is not None and state != "queued":
        raise ValueError("Room job phase changes require a queued checkpoint")
    next_phase, next_phase_attempt = _next_phase(job, phase)
    if state == "queued" and next_phase_attempt >= PHASE_CAPS[next_phase]:
        if next_phase == "legacy":
            raise ValueError("A room job cannot exceed three bounded passes")
        raise ValueError(f"A room job cannot exceed {PHASE_CAPS[next_phase]} bounded {next_phase} passes")
    if state == "queued" and next_phase == "legacy" and job["attempt"] >= 3:
        raise ValueError("A room job cannot exceed three bounded passes")
    now = time.time() if now is None else now
    conn.execute("BEGIN IMMEDIATE")
    try:
        _ensure_phase_columns(conn)
        if not has_access(conn, job["actor_id"], job["tenant_id"]):
            raise PermissionError("Room access revoked")
        count = conn.execute("""UPDATE room_jobs SET checkpoint=?,state=?,error=?,phase=?,phase_attempt=?,
            lease_token=CASE WHEN ?='queued' THEN NULL ELSE lease_token END,
            lease_until=CASE WHEN ?='queued' THEN NULL ELSE lease_until END
            WHERE id=? AND tenant_id=? AND state='running' AND lease_token=? AND lease_until>?""",
            (json.dumps(data, sort_keys=True),state,error,next_phase,next_phase_attempt,state,state,
             job["id"],job["tenant_id"],job["lease_token"],now)).rowcount
        if count != 1:
            raise ValueError("Job cancelled, expired or claimed by another worker")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def cancel(conn, tenant, job_id):
    conn.execute("UPDATE room_jobs SET state='cancelled',lease_token=NULL,lease_until=NULL WHERE tenant_id=? AND id=? AND state IN ('queued','running')",
        (tenant,job_id))
    conn.commit()


def list_jobs(conn, tenant, workspace):
    _ensure_phase_columns(conn)
    return [record(row) for row in conn.execute(f"SELECT {SELECT_COLUMNS} FROM room_jobs WHERE tenant_id=? AND workspace_id=? ORDER BY created DESC",
        (tenant,workspace)).fetchall()]


def public_job(job):
    return {k: v for k, v in job.items() if k not in {"lease_token", "work_key", "actor_id"}}
