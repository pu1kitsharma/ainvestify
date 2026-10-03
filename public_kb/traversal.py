"""Record public navigation edges without granting collection rights to targets."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from urllib.parse import urljoin

from public_kb.ingestion import PublicIngestion
from public_kb.schedule import _event, ensure_schema
from public_kb.source_candidates import _public_https_url

MAX_LINKS = 80
SCHEMA = """
CREATE TABLE IF NOT EXISTS observed_link (
 parent_source_id TEXT NOT NULL, parent_sha256 TEXT NOT NULL,
 ordinal INTEGER NOT NULL, raw_href TEXT NOT NULL, target_url TEXT,
 link_text TEXT NOT NULL, outcome TEXT NOT NULL, reason TEXT NOT NULL,
 target_source_id TEXT,
 PRIMARY KEY(parent_source_id,parent_sha256,ordinal),
 FOREIGN KEY(parent_source_id,parent_sha256) REFERENCES versions(source_id,sha256)
);
"""


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = [dict(attrs).get("href", ""), ""]

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] = (self.current[1] + data)[:200]

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append(tuple(self.current))
            self.current = None


def record_links(kb: PublicIngestion, source_id: str, digest: str):
    """Record every bounded observed edge and why it can or cannot be followed.

    Only exact, separately registered destination URLs are eligible. The
    scheduler fetches those destinations under their own rights and cadence.
    """
    ensure_schema(kb)
    kb.conn.executescript(SCHEMA)
    parent = kb.conn.execute("""SELECT m.source_url,m.content_type FROM version_metadata m
        JOIN versions v ON v.source_id=m.source_id AND v.sha256=m.sha256
        WHERE m.source_id=? AND m.sha256=? AND v.state='indexed'""",
        (source_id, digest)).fetchone()
    if not parent:
        raise ValueError("Only indexed source versions can create link edges")
    content = (kb.archive_root / source_id / digest).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Public source archive hash mismatch")
    if parent[1] in ("text/html", "application/xhtml+xml"):
        parser = _Links()
        parser.feed(content.decode("utf-8", errors="replace"))
        links = parser.links
    elif parent[1] == "application/json":
        import json
        payload = json.loads(content)
        if payload.get("source_format") != "startupdb_company_v1":
            links = []
        else:
            links = [(payload.get("company", {}).get("website_url", ""), "company website")]
            for row in payload.get("funding_history", []):
                links.extend((url, "funding source") for url in row.get("source_urls", []))
    else:
        links = []
    with kb.conn:
        for ordinal, (raw, label) in enumerate(links):
            target = _public_https_url(urljoin(parent[0], raw)) if raw else None
            target_id = None
            if target and ordinal < MAX_LINKS:
                row = kb.conn.execute("SELECT id FROM sources WHERE url=?", (target,)).fetchone()
                if row:
                    try:
                        kb.approved_source(row[0])
                        policy = kb.conn.execute("SELECT 1 FROM refresh_policy WHERE source_id=?",
                                                 (row[0],)).fetchone()
                        target_id = row[0] if policy else None
                    except PermissionError:
                        pass
            outcome = "queued" if target_id else ("skipped" if ordinal >= MAX_LINKS else "blocked")
            reason = "separately_rights_approved" if target_id else (
                "page_link_limit" if ordinal >= MAX_LINKS else
                "invalid_or_nonpublic_url" if not target else "target_rights_or_policy_missing")
            kb.conn.execute("""INSERT OR IGNORE INTO observed_link
                (parent_source_id,parent_sha256,ordinal,raw_href,target_url,link_text,
                 outcome,reason,target_source_id) VALUES (?,?,?,?,?,?,?,?,?)""",
                (source_id,digest,ordinal,str(raw)[:2048],target,label[:200],outcome,reason,target_id))
            inserted = kb.conn.execute("SELECT changes()").fetchone()[0]
            if target_id:
                kb.conn.execute("UPDATE refresh_policy SET active=1 WHERE source_id=?",
                                (target_id,))
            if inserted:
                _event(kb, source_id, "link", outcome, parent_version=digest,
                       target_url=target, reason=reason, ordinal=ordinal)
    return len(links)


def record_target_outcome(kb: PublicIngestion, target_source_id: str, *,
                          outcome: str, reason: str, digest: str | None = None):
    """Propagate a separately approved target's fetch result to all observed edges.

    The append-only collection events retain earlier outcomes when a later
    refresh fails. A link edge itself shows the most recent target state.
    """
    if outcome not in {"fetched", "failed"}:
        raise ValueError("Unsupported target outcome")
    ensure_schema(kb)
    kb.conn.executescript(SCHEMA)
    with kb.conn:
        rows = kb.conn.execute("""SELECT parent_source_id,parent_sha256,ordinal
            FROM observed_link WHERE target_source_id=?""", (target_source_id,)).fetchall()
        for parent_id, parent_digest, ordinal in rows:
            kb.conn.execute("""UPDATE observed_link SET outcome=?,reason=?
                WHERE parent_source_id=? AND parent_sha256=? AND ordinal=?""",
                (outcome, reason[:300], parent_id, parent_digest, ordinal))
            _event(kb, parent_id, "link", outcome, parent_version=parent_digest,
                   ordinal=ordinal, target_source_id=target_source_id,
                   target_version=digest, reason=reason[:300])
    return len(rows)
