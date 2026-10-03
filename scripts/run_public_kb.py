"""Run one bounded rights-cleared public KB pass; invoke from an external timer later."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_kb.collector import collect_source
from public_kb.elasticsearch import ElasticsearchPublicKB
from public_kb.ingestion import PublicIngestion
from public_kb.schedule import claim_due, finish, set_policy, status as refresh_status
from public_kb.traversal import record_links, record_target_outcome
from public_kb.claims import ingest_indexed


def backfill_indexed_claims(kb, *, max_documents=100, duration=600, after=None):
    """Project retained StartupDB facts into the append-only claim ledger.

    This is an explicit offline migration. It never fetches or publishes and
    uses the same worker lease as collection/reindexing. A continuation cursor
    refers to the last successfully processed version; rerun from the start
    after a rights change so newly eligible earlier versions are not missed.
    """
    if not 1 <= max_documents <= 100 or not 1 <= duration <= 600:
        raise ValueError("Public claim backfill exceeds pilot bounds")
    if after is not None and not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}:[0-9a-f]{64}", after):
        raise ValueError("Invalid public claim backfill cursor")
    owner, now = secrets.token_hex(16), time.time()
    kb.conn.execute("BEGIN IMMEDIATE")
    try:
        row = kb.conn.execute("SELECT lease_until FROM worker_lease WHERE id='pilot'").fetchone()
        if row and row[0] > now:
            kb.conn.commit()
            return {"status": "leased", "processed": 0, "next_after": after}
        kb.conn.execute("""INSERT INTO worker_lease VALUES ('pilot',?,?) ON CONFLICT(id)
            DO UPDATE SET owner=excluded.owner,lease_until=excluded.lease_until""",
            (owner, now + duration + 30))
        kb.conn.commit()
    except Exception:
        kb.conn.rollback()
        raise
    processed, scanned, cursor = 0, 0, after
    deadline = time.monotonic() + duration
    try:
        today = date.today()
        rows = kb.conn.execute("""SELECT v.source_id,v.sha256
            FROM versions v JOIN sources s ON s.id=v.source_id
            WHERE v.state='indexed' AND s.url LIKE 'https://startupdb.com/api/v1/startups/%'
            AND s.enabled=1 AND s.automated_access=1 AND s.retention=1
            AND s.inference_processing=1 AND s.investor_reuse=1
            AND date(s.reviewed_at) BETWEEN ? AND ?
            AND (v.source_id || ':' || v.sha256)>?
            ORDER BY v.source_id,v.sha256 LIMIT ?""",
            ((today - timedelta(days=180)).isoformat(), today.isoformat(),
             after or "", max_documents + 1)).fetchall()
        for source_id, digest in rows:
            key = source_id + ":" + digest
            if scanned >= max_documents or time.monotonic() >= deadline:
                break
            scanned += 1
            cursor = key
            try:
                kb.approved_source(source_id)
            except PermissionError:
                # Revoked sources are excluded. A fresh no-cursor replay can
                # pick them up if an operator renews rights later.
                continue
            content = (kb.archive_root / source_id / digest).read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("Public claim archive hash mismatch during backfill")
            payload = json.loads(content)
            if (not isinstance(payload, dict) or
                payload.get("source_format") != "startupdb_company_v1" or
                payload.get("license") != "CC BY 4.0" or
                payload.get("attribution") != "StartupDB (https://startupdb.com)"):
                raise ValueError("Retained StartupDB record lacks reviewed fact projection")
            ingest_indexed(kb, source_id, digest)
            processed += 1
        return {"status": "partial" if scanned < len(rows) else "completed",
                "processed": processed, "next_after": cursor}
    finally:
        with kb.conn:
            kb.conn.execute("DELETE FROM worker_lease WHERE id='pilot' AND owner=?", (owner,))


def reindex_retained(kb, sink, *, max_documents=100, duration=600, after=None):
    """Replay archived, still-permitted versions after an extractor change.

    ES document IDs are stable, so replay replaces each projection without
    altering source bytes or SQLite version history. The cursor permits a
    bounded manual continuation across a larger archive.
    """
    if not 1 <= max_documents <= 100 or not 1 <= duration <= 600:
        raise ValueError("Public KB replay exceeds pilot bounds")
    owner, now = secrets.token_hex(16), time.time()
    kb.conn.execute("BEGIN IMMEDIATE")
    try:
        row = kb.conn.execute("SELECT lease_until FROM worker_lease WHERE id='pilot'").fetchone()
        if row and row[0] > now:
            kb.conn.commit()
            return {"status": "leased", "reindexed": 0, "next_after": after}
        kb.conn.execute("""INSERT INTO worker_lease VALUES ('pilot',?,?) ON CONFLICT(id)
            DO UPDATE SET owner=excluded.owner,lease_until=excluded.lease_until""",
            (owner, now + duration + 30))
        kb.conn.commit()
    except Exception:
        kb.conn.rollback()
        raise
    count, cursor = 0, after
    deadline = time.monotonic() + duration
    try:
        rows = kb.conn.execute("""SELECT v.source_id,v.sha256 FROM versions v
            JOIN sources s ON s.id=v.source_id WHERE v.state='indexed'
            ORDER BY v.source_id,v.sha256""").fetchall()
        for source_id, digest in rows:
            key = source_id + ":" + digest
            if after and key <= after:
                continue
            if count >= max_documents or time.monotonic() >= deadline:
                break
            try:
                kb.approved_source(source_id)
            except PermissionError:
                cursor = key
                continue
            content = (kb.archive_root / source_id / digest).read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("Public archive hash mismatch during replay")
            sink(source_id, digest, content)
            count += 1
            cursor = key
        return {"status": "completed", "reindexed": count, "next_after": cursor}
    finally:
        with kb.conn:
            kb.conn.execute("DELETE FROM worker_lease WHERE id='pilot' AND owner=?", (owner,))


def run_pass(kb, *, max_documents=100, duration=600):
    if not 1 <= max_documents <= 100 or not 1 <= duration <= 600:
        raise ValueError("Public KB pass exceeds pilot bounds")
    owner = secrets.token_hex(16)
    now = time.time()
    kb.conn.execute("BEGIN IMMEDIATE")
    try:
        row = kb.conn.execute("SELECT lease_until FROM worker_lease WHERE id='pilot'").fetchone()
        if row and row[0] > now:
            kb.conn.commit()
            return {"status": "leased", "collected": 0, "errors": 0}
        kb.conn.execute("""INSERT INTO worker_lease VALUES ('pilot',?,?) ON CONFLICT(id)
            DO UPDATE SET owner=excluded.owner,lease_until=excluded.lease_until""", (owner, now + duration + 30))
        kb.conn.commit()
    except Exception:
        kb.conn.rollback()
        raise
    deadline = time.monotonic() + duration
    collected = errors = 0
    try:
        # Existing reviewed StartupDB detail records are company profiles.
        # Other publishers require an explicit class policy before scheduling.
        for source_id, url in kb.conn.execute("SELECT id,url FROM sources WHERE enabled=1").fetchall():
            if url.startswith("https://startupdb.com/api/v1/startups/"):
                try:
                    set_policy(kb, source_id, "profile")
                except PermissionError:
                    pass
        for _ in range(max_documents):
            if time.monotonic() + 90 >= deadline:
                break
            claim = claim_due(kb)
            if not claim:
                break
            job_id, source_id, job_owner = claim
            try:
                result = collect_source(kb, source_id)
                if result == "leased":
                    raise RuntimeError("Source collection lease is held by another worker")
                if kb.pending():
                    kb.publish_pending(ElasticsearchPublicKB(kb).publish,
                                       max_documents=max_documents, deadline=deadline)
                row = kb.conn.execute("SELECT last_sha256 FROM fetch_state WHERE source_id=?",
                                      (source_id,)).fetchone()
                digest = row[0] if row else None
                indexed = kb.conn.execute("SELECT state FROM versions WHERE source_id=? AND sha256=?",
                                          (source_id, digest)).fetchone()
                if not indexed or indexed[0] != "indexed":
                    raise RuntimeError("Source refresh has not completed indexing")
                record_links(kb, source_id, digest)
                ingest_indexed(kb, source_id, digest)
                record_target_outcome(kb, source_id, outcome="fetched",
                                      reason="indexed_refresh_completed", digest=digest)
                finish(kb, job_id, job_owner, digest=digest)
                collected += int(result == "staged")
            except Exception as exc:
                try:
                    record_target_outcome(kb, source_id, outcome="failed", reason=str(exc))
                except Exception as link_exc:
                    exc = RuntimeError(f"Refresh failed; link outcome update also failed: {link_exc}")
                finish(kb, job_id, job_owner, error=exc)
                errors += 1
        if kb.pending() and time.monotonic() < deadline:
            kb.publish_pending(ElasticsearchPublicKB(kb).publish,
                               max_documents=max_documents, deadline=deadline)
        return {"status": "completed" if not errors else "partial", "collected": collected,
                "errors": errors, "refresh": refresh_status(kb)}
    finally:
        with kb.conn:
            kb.conn.execute("DELETE FROM worker_lease WHERE id='pilot' AND owner=?", (owner,))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reindex-retained", action="store_true")
    mode.add_argument("--backfill-claims", action="store_true")
    parser.add_argument("--after", help="Last source_id:sha256 returned by a prior replay")
    parser.add_argument("--max-documents", type=int, default=100)
    parser.add_argument("--duration", type=int, default=600)
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error("An existing, operator-reviewed public KB registry is required")
    kb = PublicIngestion(args.db, args.archive)
    try:
        if args.reindex_retained:
            print(reindex_retained(kb, ElasticsearchPublicKB(kb).publish,
                                   max_documents=args.max_documents,
                                   duration=args.duration, after=args.after))
        elif args.backfill_claims:
            print(backfill_indexed_claims(kb, max_documents=args.max_documents,
                                          duration=args.duration, after=args.after))
        else:
            if args.after:
                parser.error("--after requires a replay mode")
            print(run_pass(kb, max_documents=args.max_documents, duration=args.duration))
    finally:
        kb.close()


if __name__ == "__main__":
    main()
