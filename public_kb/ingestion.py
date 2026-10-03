"""Durable public source-version staging and resumable index outbox.

Only an operator-approved source registry can submit content. The caller must
prove bytes came from that public source; this offline module cannot classify
arbitrary content. Network collection, claim extraction and ES indexing are
separate components. Room data must never be passed to this module.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

SOURCE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
MAX_PUBLIC_BYTES = 5 * 1024 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, terms_url TEXT NOT NULL,
 reviewed_at TEXT NOT NULL, automated_access INTEGER NOT NULL,
 retention INTEGER NOT NULL, inference_processing INTEGER NOT NULL,
 investor_reuse INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS versions (
 source_id TEXT NOT NULL REFERENCES sources(id), sha256 TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('staged','indexing','indexed')),
 fetched_at REAL NOT NULL, indexed_at REAL, lease_owner TEXT, lease_until REAL,
 PRIMARY KEY(source_id,sha256)
);
CREATE TABLE IF NOT EXISTS fetch_state (
 source_id TEXT PRIMARY KEY REFERENCES sources(id), etag TEXT, last_modified TEXT,
 last_checked REAL, last_status INTEGER, last_sha256 TEXT,
 lease_owner TEXT, lease_until REAL
);
CREATE TABLE IF NOT EXISTS version_metadata (
 source_id TEXT NOT NULL, sha256 TEXT NOT NULL, source_url TEXT NOT NULL,
 terms_url TEXT NOT NULL, reviewed_at TEXT NOT NULL, content_type TEXT NOT NULL,
 PRIMARY KEY(source_id,sha256),
 FOREIGN KEY(source_id,sha256) REFERENCES versions(source_id,sha256)
);
CREATE TABLE IF NOT EXISTS worker_lease (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, lease_until REAL NOT NULL
);
"""


class PublicIngestion:
    def __init__(self, db_path: Path, archive_root: Path):
        self.db_path = Path(db_path)
        self.archive_root = Path(archive_root)
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def approved_source(self, source_id):
        row = self.conn.execute("""SELECT url,enabled,automated_access,retention,
            inference_processing,investor_reuse,reviewed_at FROM sources WHERE id=?""", (source_id,)).fetchone()
        if not row or not all(row[1:6]) or not 0 <= (date.today() - date.fromisoformat(row[6])).days <= 180:
            raise PermissionError("Public source is disabled or lacks reviewed rights")
        return row[0]

    def register_source(self, *, source_id, url, terms_url, reviewed_at,
                        automated_access=False, retention=False,
                        inference_processing=False, investor_reuse=False,
                        enabled=False):
        if not SOURCE_ID.fullmatch(source_id):
            raise ValueError("Invalid public source ID")
        from urllib.parse import urlsplit
        for address in (url, terms_url):
            parsed = urlsplit(address)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("Public source URLs require HTTPS")
        if enabled and not all((automated_access, retention, inference_processing, investor_reuse, reviewed_at)):
            raise ValueError("All four source permissions and a review date are required")
        if enabled:
            try:
                age = (date.today() - date.fromisoformat(reviewed_at)).days
            except (TypeError, ValueError) as exc:
                raise ValueError("An ISO rights review date is required") from exc
            if not 0 <= age <= 180:
                raise ValueError("Public source rights review must be current")
        existing = self.conn.execute("SELECT url FROM sources WHERE id=?", (source_id,)).fetchone()
        if existing and existing[0] != url:
            raise ValueError("A public source URL is immutable; register a new source ID")
        with self.conn:
            self.conn.execute("""INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET url=excluded.url,terms_url=excluded.terms_url,
                reviewed_at=excluded.reviewed_at,automated_access=excluded.automated_access,
                retention=excluded.retention,inference_processing=excluded.inference_processing,
                investor_reuse=excluded.investor_reuse,enabled=excluded.enabled""",
                (source_id,url,terms_url,reviewed_at,int(automated_access),int(retention),
                 int(inference_processing),int(investor_reuse),int(enabled)))

    def stage(self, source_id: str, content: bytes, *, source_url=None, content_type='text/plain'):
        """Stage bytes fetched independently from an approved public source."""
        if not isinstance(content, bytes) or not content or len(content) > MAX_PUBLIC_BYTES:
            raise ValueError("Public source content is empty or exceeds the limit")
        digest = hashlib.sha256(content).hexdigest()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT enabled,automated_access,retention,inference_processing,investor_reuse,url,terms_url,reviewed_at FROM sources WHERE id=?",
                                    (source_id,)).fetchone()
            if not row or not all(row[:5]) or not 0 <= (date.today() - date.fromisoformat(row[7])).days <= 180:
                raise PermissionError("Public source is disabled or lacks reviewed rights")
            from urllib.parse import urlsplit
            if source_url:
                parsed = urlsplit(source_url)
                registered = urlsplit(row[5])
                if parsed.scheme != 'https' or parsed.hostname != registered.hostname or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None,443):
                    raise ValueError("Public version URL must remain on its approved HTTPS host")
            if content_type not in {'text/plain','text/html','application/xhtml+xml','application/json'}:
                raise ValueError("Unsupported public source media type")
            directory = self.archive_root / source_id
            if directory.is_symlink():
                raise ValueError("Public archive path is a symlink")
            directory.mkdir(exist_ok=True)
            destination = directory / digest
            if destination.is_symlink():
                raise ValueError("Public archive path is a symlink")
            if not destination.exists():
                fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    destination.unlink(missing_ok=True)
                    raise
            elif hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError("Public archive hash mismatch")
            self.conn.execute("INSERT OR IGNORE INTO versions(source_id,sha256,state,fetched_at) VALUES (?,?,'staged',?)",
                              (source_id,digest,time.time()))
            self.conn.execute("""INSERT OR IGNORE INTO version_metadata
                (source_id,sha256,source_url,terms_url,reviewed_at,content_type)
                VALUES (?,?,?,?,?,?)""", (source_id,digest,source_url or row[5],row[6],row[7],content_type))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return digest

    def pending(self):
        today = date.today()
        return self.conn.execute("""SELECT v.source_id,v.sha256 FROM versions v
            JOIN sources s ON s.id=v.source_id WHERE v.state='staged' AND s.enabled=1
            AND s.automated_access=1 AND s.retention=1 AND s.inference_processing=1
            AND s.investor_reuse=1 AND date(s.reviewed_at) BETWEEN ? AND ?
            ORDER BY v.fetched_at,v.source_id""",
            ((today-timedelta(days=180)).isoformat(),today.isoformat())).fetchall()

    def _claim(self):
        owner = uuid.uuid4().hex
        now = time.time()
        today = date.today()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("""SELECT v.source_id,v.sha256 FROM versions v
                JOIN sources s ON s.id=v.source_id
                WHERE (v.state='staged' OR (v.state='indexing' AND v.lease_until<?))
                AND s.enabled=1 AND s.automated_access=1 AND s.retention=1
                AND s.inference_processing=1 AND s.investor_reuse=1
                AND date(s.reviewed_at) BETWEEN ? AND ?
                ORDER BY v.fetched_at,v.source_id LIMIT 1""",
                (now,(today-timedelta(days=180)).isoformat(),today.isoformat())).fetchone()
            if row:
                self.conn.execute("""UPDATE versions SET state='indexing',lease_owner=?,lease_until=?
                    WHERE source_id=? AND sha256=?""",(owner,now+120,*row))
            self.conn.commit()
            return (*row,owner) if row else None
        except Exception:
            self.conn.rollback()
            raise

    def publish_pending(self, sink, *, max_documents=100, deadline=None):
        """Index retained versions; a failing sink leaves its version pending.

        The sink must use (source_id, hash) as an idempotent document key. A
        network/ES implementation must be separately qualified before scheduling.
        """
        if not 1 <= max_documents <= 100:
            raise ValueError("Public indexing batch must be bounded")
        for _ in range(max_documents):
            if deadline is not None and time.monotonic() >= deadline:
                break
            claim = self._claim()
            if not claim:
                break
            source_id,digest,owner = claim
            try:
                content = (self.archive_root / source_id / digest).read_bytes()
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError("Public archive hash mismatch")
                sink(source_id,digest,content)
                with self.conn:
                    self.conn.execute("""UPDATE versions SET state='indexed',indexed_at=?,lease_owner=NULL,lease_until=NULL
                        WHERE source_id=? AND sha256=? AND state='indexing' AND lease_owner=?""",
                        (time.time(),source_id,digest,owner))
            except Exception:
                with self.conn:
                    self.conn.execute("""UPDATE versions SET state='staged',lease_owner=NULL,lease_until=NULL
                        WHERE source_id=? AND sha256=? AND state='indexing' AND lease_owner=?""",
                        (source_id,digest,owner))
                raise
