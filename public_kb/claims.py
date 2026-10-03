"""Append-only, source-reported company funding claims and current projection.

Only indexed, hash-checked structured public records enter this ledger. A
shared evidenced domain identifies an entity; company names never merge rows.
"""
from __future__ import annotations

from datetime import date
from calendar import monthrange
import hashlib
import json
import re
from urllib.parse import urlsplit

from public_kb.ingestion import PublicIngestion

SCHEMA = """
CREATE TABLE IF NOT EXISTS public_funding_claim (
 id TEXT PRIMARY KEY, entity_key TEXT NOT NULL, source_id TEXT NOT NULL,
 source_sha256 TEXT NOT NULL, source_path TEXT NOT NULL,
 event_date TEXT NOT NULL, event_date_precision TEXT NOT NULL DEFAULT 'day',
 stage TEXT NOT NULL, amount TEXT,
 currency TEXT, amount_semantics TEXT NOT NULL,
 evidence_status TEXT NOT NULL DEFAULT 'source_reported',
 event_status TEXT NOT NULL DEFAULT '',
 UNIQUE(source_id,source_sha256,source_path),
 FOREIGN KEY(source_id,source_sha256) REFERENCES versions(source_id,sha256)
);
CREATE TABLE IF NOT EXISTS public_company_projection (
 entity_key TEXT PRIMARY KEY, stage TEXT, status TEXT NOT NULL,
 event_date TEXT, supporting_claim_ids TEXT NOT NULL,
 opposing_claim_ids TEXT NOT NULL, revision TEXT NOT NULL
);
"""


def _entity_key(company):
    domain = company.get("domain") or urlsplit(company.get("website_url") or "").hostname
    if not isinstance(domain, str):
        return None
    domain = domain.lower().strip().removeprefix("www.").rstrip(".")
    if not domain or "." not in domain or any(char.isspace() for char in domain):
        return None
    return "domain:" + domain


def _source_date(value, precision):
    """Keep the publisher's date granularity; never invent a day or month."""
    if not isinstance(value, str) or not isinstance(precision, str):
        return None
    if precision == "day":
        try:
            return value if date.fromisoformat(value).isoformat() == value else None
        except ValueError:
            return None
    if precision == "month" and re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", value):
        try:
            date.fromisoformat(value + "-01")
        except ValueError:
            return None
        return value
    if precision == "year" and re.fullmatch(r"\d{4}", value):
        try:
            date.fromisoformat(value + "-01-01")
        except ValueError:
            return None
        return value
    return None


def _date_interval(value, precision):
    """Represent an imprecise publisher date without choosing a false day."""
    if precision == "year":
        return date(int(value), 1, 1), date(int(value), 12, 31)
    if precision == "month":
        year, month = map(int, value.split("-"))
        return date(year, month, 1), date(year, month, monthrange(year, month)[1])
    day = date.fromisoformat(value)
    return day, day


def reconcile(kb: PublicIngestion, entity_key: str):
    rows = kb.conn.execute("""SELECT c.id,c.event_date,c.stage,c.event_status,c.event_date_precision FROM public_funding_claim c
        JOIN versions v ON v.source_id=c.source_id AND v.sha256=c.source_sha256
        WHERE c.entity_key=? AND v.state='indexed' AND c.source_sha256=(
          SELECT newest.sha256 FROM versions newest WHERE newest.source_id=c.source_id
          AND newest.state='indexed' ORDER BY newest.fetched_at DESC,newest.rowid DESC LIMIT 1)
        ORDER BY c.event_date DESC,c.id""", (entity_key,)).fetchall()
    if not rows:
        historical = sorted(row[0] for row in kb.conn.execute(
            "SELECT id FROM public_funding_claim WHERE entity_key=?", (entity_key,)))
        status = "unknown_no_current_claim"
        revision = hashlib.sha256(json.dumps([status, historical], sort_keys=True).encode()).hexdigest()
        with kb.conn:
            kb.conn.execute("""INSERT INTO public_company_projection VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(entity_key) DO UPDATE SET stage=NULL,status=excluded.status,
                event_date=NULL,supporting_claim_ids=excluded.supporting_claim_ids,
                opposing_claim_ids=excluded.opposing_claim_ids,revision=excluded.revision""",
                (entity_key, None, status, None, "[]", json.dumps(historical), revision))
        return dict(entity_key=entity_key, stage=None, status=status, event_date=None,
                    supporting_claim_ids=[], opposing_claim_ids=historical, revision=revision)
    intervals = {row[0]: _date_interval(row[1], row[4]) for row in rows}
    latest_start = max(bounds[0] for bounds in intervals.values())
    latest = [row for row in rows if intervals[row[0]][1] >= latest_start]
    latest_date = max(row[1] for row in latest)
    stages = {row[2] for row in latest}
    # A dated listing is not proof that financing closed. Preserve the claim,
    # but do not project an open, planned or unspecified event as current stage.
    completed = {"completed", "closed", "funded"}
    closed_latest = [row for row in latest if row[3].strip().lower() in completed]
    closed_stages = {row[2] for row in closed_latest}
    today = date.today()
    if any(intervals[row[0]][0] > today for row in latest):
        status, stage = "future_dated", None
    elif any(intervals[row[0]][1] > today for row in latest):
        status, stage = "ambiguous_event_date", None
    elif len(stages) > 1:
        status, stage = "conflicted", None
    elif len(closed_stages) == 1 and len(closed_latest) == len(latest):
        status, stage = "current_source_reported", next(iter(closed_stages))
    else:
        status, stage = "unknown_completion", None
    supporting = sorted(row[0] for row in latest)
    opposing = sorted(row[0] for row in rows if row not in latest)
    revision = hashlib.sha256(json.dumps([status, stage, supporting, opposing,
                                         [(row[0], row[3]) for row in latest]],
                                      sort_keys=True).encode()).hexdigest()
    with kb.conn:
        kb.conn.execute("""INSERT INTO public_company_projection VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(entity_key) DO UPDATE SET stage=excluded.stage,status=excluded.status,
            event_date=excluded.event_date,supporting_claim_ids=excluded.supporting_claim_ids,
            opposing_claim_ids=excluded.opposing_claim_ids,revision=excluded.revision""",
            (entity_key, stage, status, latest_date, json.dumps(supporting),
             json.dumps(opposing), revision))
    return dict(entity_key=entity_key, stage=stage, status=status,
                event_date=latest_date, supporting_claim_ids=supporting,
                opposing_claim_ids=opposing, revision=revision)


def ingest_indexed(kb: PublicIngestion, source_id: str, digest: str):
    kb.conn.executescript(SCHEMA)
    columns = {row[1] for row in kb.conn.execute("PRAGMA table_info(public_funding_claim)")}
    if "event_status" not in columns:
        with kb.conn:
            kb.conn.execute("ALTER TABLE public_funding_claim ADD COLUMN event_status TEXT NOT NULL DEFAULT ''")
    if "event_date_precision" not in columns:
        with kb.conn:
            kb.conn.execute("ALTER TABLE public_funding_claim ADD COLUMN event_date_precision TEXT NOT NULL DEFAULT 'day'")
    kb.approved_source(source_id)
    row = kb.conn.execute("SELECT state FROM versions WHERE source_id=? AND sha256=?",
                          (source_id, digest)).fetchone()
    if not row or row[0] != "indexed":
        raise ValueError("Claims require an indexed source version")
    content = (kb.archive_root / source_id / digest).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Public claim archive hash mismatch")
    affected = {row[0] for row in kb.conn.execute(
        "SELECT DISTINCT entity_key FROM public_funding_claim WHERE source_id=?", (source_id,))}
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return [reconcile(kb, key) for key in sorted(affected)]
    if not isinstance(payload, dict) or payload.get("source_format") != "startupdb_company_v1":
        return [reconcile(kb, key) for key in sorted(affected)]
    company = payload.get("company") or {}
    entity_key = _entity_key(company)
    if not entity_key:
        return [reconcile(kb, key) for key in sorted(affected)]
    affected.add(entity_key)
    for index, item in enumerate(payload.get("funding_history", [])):
        if not isinstance(item, dict):
            continue
        stage, when = item.get("label"), item.get("date")
        precision = item.get("date_precision") or "day"
        if _source_date(when, precision) is None:
            continue
        if not isinstance(stage, str) or not stage.strip():
            continue
        path = f"funding_history[{index}]"
        claim_id = hashlib.sha256(f"{source_id}:{digest}:{path}".encode()).hexdigest()
        amount = item.get("amount") or {}
        with kb.conn:
            kb.conn.execute("""INSERT OR IGNORE INTO public_funding_claim
                (id,entity_key,source_id,source_sha256,source_path,event_date,
                 event_date_precision,stage,amount,currency,amount_semantics,event_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (claim_id, entity_key, source_id, digest, path, when, precision, stage.strip(),
                 amount.get("original"), amount.get("currency"), "unspecified",
                 str(item.get("status") or "")[:60]))
    return [reconcile(kb, key) for key in sorted(affected)]
