"""Private draft registry and exact-hash gateway support. No client supplied paths."""
from __future__ import annotations
import json
import os
import secrets
import hashlib
from pathlib import Path

from delivery.inspection import inspect_bytes, summarize_report
from delivery.storage import read_bytes, store_bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS room_artifacts (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 kind TEXT NOT NULL, format TEXT NOT NULL, sha256 TEXT NOT NULL,
 input_revision TEXT NOT NULL, state TEXT NOT NULL, inspection TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS artifact_revision_slot ON room_artifacts(tenant_id,workspace_id,kind,format,input_revision);
CREATE TABLE IF NOT EXISTS room_packages (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 manifest TEXT NOT NULL, checks TEXT NOT NULL, reviews TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'blocked');
"""


def artifact_root():
    return Path(os.environ.get("PRIVATE_ARTIFACT_ROOT", str(Path(__file__).resolve().parents[1] / "private_artifacts")))


def register_draft(conn, tenant, room, kind, fmt, revision, content, *, job=None):
    from delivery.contracts import POLICY
    release_formats = {contract.kind: contract.formats for contract in POLICY.artifacts}
    # Pre-review previews are deliberately distinct slots. A later repaired,
    # reviewed draft can occupy the investor-material slot for this revision.
    preview_formats = {'research_brief': ('pdf',),
                       'intro_deck_preview': ('pptx', 'pdf'),
                       'pitch_deck_preview': ('pptx', 'pdf'),
                       'investment_memorandum_preview': ('docx', 'pdf')}
    allowed_formats = release_formats.get(kind, preview_formats.get(kind))
    if allowed_formats is None or fmt not in allowed_formats:
        raise ValueError('Unsupported artifact kind or format')
    digest = hashlib.sha256(content).hexdigest()
    report = inspect_bytes(content, fmt)
    artifact_id = "artifact_" + secrets.token_hex(16)
    conn.execute('BEGIN IMMEDIATE')
    try:
        if job is not None:
            from security.identity import has_access
            import time
            active=conn.execute("SELECT id FROM room_jobs WHERE id=? AND state='running' AND lease_token=? AND lease_until>?",
                (job['id'],job['lease_token'],time.time())).fetchone()
            if not active or not has_access(conn,job['actor_id'],tenant):
                raise PermissionError('Job access or lease revoked')
            if (job['tenant_id'],job['workspace_id'],job['input_revision'])!=(tenant,room,revision):
                raise PermissionError('Artifact job scope mismatch')
        existing=conn.execute('SELECT id,sha256 FROM room_artifacts WHERE tenant_id=? AND workspace_id=? AND kind=? AND format=? AND input_revision=?',
            (tenant,room,kind,fmt,revision)).fetchone()
        if existing:
            if existing[1] != digest:
                raise ValueError('Artifact slot already contains different bytes; create a new input revision')
            store_bytes(artifact_root(), tenant, room, content)
            artifact_id=existing[0]
        else:
            store_bytes(artifact_root(), tenant, room, content)
            conn.execute("INSERT INTO room_artifacts VALUES (?,?,?,?,?,?,?,'draft',?)",
                (artifact_id,tenant,room,kind,fmt,digest,revision,json.dumps(summarize_report(report))))
        conn.commit()
        return artifact_id
    except Exception:
        conn.rollback();raise


def get_artifact(conn, tenant, artifact_id):
    row = conn.execute("SELECT id,workspace_id,kind,format,sha256,input_revision,state,inspection FROM room_artifacts WHERE tenant_id=? AND id=?",
        (tenant,artifact_id)).fetchone()
    if row is None:
        return None
    result = dict(zip(("id","workspace_id","kind","format","sha256","input_revision","state","inspection"),row))
    result["inspection"] = json.loads(result["inspection"])
    return result


def artifact_bytes(tenant, artifact):
    return read_bytes(artifact_root(),tenant,artifact["workspace_id"],artifact["sha256"])
