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
              "ledger": 5, "review": 2, "material_draft": 6, "material_preview": 2,
              "material_review": 2,
              "material_remediation": 1, "material_re_review": 2, "render": 1,
              "analysis": 3, "legacy": 3}
EVIDENCE_PACKET_DRAFT_PASS_CAP = 8  # Eight source batches, then six bounded section calls.
SOURCE_LOCAL_MEMO_DRAFT_PASS_CAP = 30  # Up to 27 distinct v8 tasks and three no-call yields.
CAUSAL_MEMO_REVIEW_PASS_CAP = 14  # Up to twelve three-sentence calls plus two no-call yields.
PURPOSE_GROUPED_MATERIAL_PASS_CAP = 12
PURPOSE_SINGLE_SLOT_PASS_CAP = 15  # Twelve model calls plus three no-call yields.
SEMANTIC_BATCH_REVIEW_PASS_CAP = 15  # Twelve review calls plus three no-call yields.
PHASES = ("source_selection", "financial_analysis", "draft", "correction", "ledger", "review", "material_draft", "material_preview", "material_review", "material_remediation", "material_re_review", "render")
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
    if (job['phase'] == 'review' and
            job.get('checkpoint', {}).get('memo_draft_contract') == 'memo-cards-v13' and
            job.get('checkpoint', {}).get('memo_causal_review_contract') ==
            'memo-causal-v2' and
            job.get('checkpoint', {}).get('memo_revision') in
            {'causal_v2', 'causal_v3', 'causal_v4', 'causal_v5', 'field_v1'}):
        # Two substantive source-local repairs at most, with versioned shape
        # correction and exact-raw citation replay; never a general retry cap.
        return 28
    if (job['phase'] == 'review' and
            job.get('checkpoint', {}).get('memo_draft_contract') == 'memo-cards-v13' and
            job.get('checkpoint', {}).get('memo_causal_review_contract') ==
            'memo-causal-v3' and
            job.get('checkpoint', {}).get('memo_revision') in
            {'stable_v1', 'field_v2'}):
        # Stable-row replay and changed-row judgments precede six field calls.
        # This is a finite branch pass ceiling, not a per-answer retry budget.
        return 28
    if (job['phase'] == 'review' and
            job.get('checkpoint', {}).get('memo_draft_contract') == 'memo-cards-v13' and
            job.get('checkpoint', {}).get('memo_final_review_contract') in
            {'field_v1', 'field_v2', 'field_v3', 'field_v4'}):
        # Eight causal batches and six distinct field reviews, with two
        # bounded no-call yields. These are not retries of a failed answer.
        return 16
    if (job["phase"] == "draft" and
            job.get("checkpoint", {}).get("memo_draft_contract") in
            {"memo-cards-v8", "memo-cards-v9", "memo-cards-v10",
             "memo-cards-v11", "memo-cards-v12", "memo-cards-v13"}):
        return SOURCE_LOCAL_MEMO_DRAFT_PASS_CAP
    if (job["phase"] == "draft" and
            job.get("checkpoint", {}).get("memo_draft_contract") in
            {"memo-cards-v1", "memo-cards-v2", "memo-cards-v3", "memo-cards-v4",
             "memo-cards-v5", "memo-cards-v6", "memo-cards-v7"}):
        return EVIDENCE_PACKET_DRAFT_PASS_CAP
    if (job["phase"] == "review" and
            job.get("checkpoint", {}).get("memo_draft_contract") in
            {"memo-cards-v3", "memo-cards-v4", "memo-cards-v5", "memo-cards-v6",
             "memo-cards-v7", "memo-cards-v8", "memo-cards-v9",
             "memo-cards-v10", "memo-cards-v11", "memo-cards-v12",
             "memo-cards-v13"} and
            job.get("checkpoint", {}).get("memo_causal_review_contract") in
            {"memo-causal-v1", "memo-causal-v2"}):
        return CAUSAL_MEMO_REVIEW_PASS_CAP
    if (job["phase"] == "material_draft" and
            job.get("checkpoint", {}).get("material_draft_contract") in
            {"purpose_v7", "purpose_v8", "purpose_v9", "purpose_v10",
             "purpose_v11", "purpose_v12", "purpose_v13"}):
        return PURPOSE_SINGLE_SLOT_PASS_CAP
    if (job["phase"] in {"material_review", "material_re_review"} and
            job.get("checkpoint", {}).get("material_review_contract") == "semantic_v12"):
        return SEMANTIC_BATCH_REVIEW_PASS_CAP
    if (job["phase"] == "material_draft" and
            job.get("checkpoint", {}).get("material_draft_contract") in
            {"purpose_v3", "purpose_v4", "purpose_v5", "purpose_v6"}):
        return PURPOSE_GROUPED_MATERIAL_PASS_CAP
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
                WHEN 'source_selection' THEN 3 WHEN 'financial_analysis' THEN 9
                WHEN 'draft' THEN CASE WHEN json_extract(checkpoint,
                    '$.memo_draft_contract') IN ('memo-cards-v8','memo-cards-v9','memo-cards-v10','memo-cards-v11','memo-cards-v12','memo-cards-v13') THEN 30
                    WHEN json_extract(checkpoint,
                    '$.memo_draft_contract') IN ('memo-cards-v1','memo-cards-v2','memo-cards-v3','memo-cards-v4','memo-cards-v5','memo-cards-v6','memo-cards-v7')
                    THEN 8 ELSE 6 END
                WHEN 'correction' THEN 3 WHEN 'ledger' THEN 5
                WHEN 'review' THEN CASE WHEN json_extract(checkpoint,
                    '$.memo_draft_contract')='memo-cards-v13' AND
                    json_extract(checkpoint,'$.memo_causal_review_contract')='memo-causal-v2' AND
                    json_extract(checkpoint,'$.memo_revision') IN
                    ('causal_v2','causal_v3','causal_v4','causal_v5','field_v1')
                    THEN 28 WHEN json_extract(checkpoint,
                    '$.memo_draft_contract')='memo-cards-v13' AND
                    json_extract(checkpoint,'$.memo_causal_review_contract')='memo-causal-v3' AND
                    json_extract(checkpoint,'$.memo_revision') IN ('stable_v1','field_v2')
                    THEN 28 WHEN json_extract(checkpoint,
                    '$.memo_draft_contract')='memo-cards-v13' AND
                    json_extract(checkpoint,'$.memo_final_review_contract')
                    IN ('field_v1','field_v2','field_v3','field_v4')
                    THEN 16 WHEN json_extract(checkpoint,
                    '$.memo_draft_contract') IN ('memo-cards-v3','memo-cards-v4','memo-cards-v5','memo-cards-v6','memo-cards-v7','memo-cards-v8','memo-cards-v9','memo-cards-v10','memo-cards-v11','memo-cards-v12','memo-cards-v13') AND
                    json_extract(checkpoint,'$.memo_causal_review_contract')
                    IN ('memo-causal-v1','memo-causal-v2')
                    THEN 14 ELSE 2 END
                WHEN 'material_draft' THEN CASE
                    WHEN json_extract(checkpoint,'$.material_draft_contract')
                        IN ('purpose_v7','purpose_v8','purpose_v9','purpose_v10','purpose_v11','purpose_v12','purpose_v13')
                        THEN 15
                    WHEN json_extract(checkpoint,'$.material_draft_contract')
                        IN ('purpose_v3','purpose_v4','purpose_v5','purpose_v6')
                        THEN 12 ELSE 6 END
                WHEN 'material_preview' THEN 2
                WHEN 'material_review' THEN CASE WHEN json_extract(checkpoint,
                    '$.material_review_contract')='semantic_v12' THEN 15 ELSE 2 END
                WHEN 'material_remediation' THEN 1
                WHEN 'material_re_review' THEN CASE WHEN json_extract(checkpoint,
                    '$.material_review_contract')='semantic_v12' THEN 15 ELSE 2 END
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
    next_cap = _phase_cap({"phase": next_phase, "checkpoint": data})
    if state == "queued" and next_phase_attempt >= next_cap:
        if next_phase == "legacy":
            raise ValueError("A room job cannot exceed three bounded passes")
        raise ValueError(f"A room job cannot exceed {next_cap} bounded {next_phase} passes")
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
