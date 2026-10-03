"""Durable navigation candidates from an already indexed public company record.

These URLs are leads for a separate rights and identity review. Staging them
does not authorize collection, retention, inference, or factual claims about
the destination. No private room input or network access belongs here.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from urllib.parse import urlsplit

from agents.discovery.web_sources import SourceError, normalize_url
from public_kb.ingestion import PublicIngestion

MAX_CANDIDATES = 80

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_candidates (
 source_id TEXT NOT NULL,
 source_sha256 TEXT NOT NULL,
 target_url TEXT NOT NULL,
 source_url TEXT NOT NULL,
 link_kind TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'pending_rights_review'
   CHECK(review_status = 'pending_rights_review'),
 PRIMARY KEY (source_id, source_sha256, target_url),
 FOREIGN KEY (source_id, source_sha256) REFERENCES versions(source_id, sha256)
);
"""


def _public_https_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url = normalize_url(value)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            return None
        host = parsed.hostname or ""
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass  # DNS is checked by the separately authorized fetcher.
        return url
    except (SourceError, ValueError):
        return None


def stage_indexed_company_links(
    kb: PublicIngestion, source_id: str, source_sha256: str
) -> list[dict[str, str]]:
    """Persist up to 80 link candidates from the current indexed KB version.

    This only reads a rights-approved, hash-verified public KB snapshot. It
    never fetches a destination or registers it as an approved source.
    """
    registered_url = kb.approved_source(source_id)
    row = kb.conn.execute(
        """SELECT v.state, f.last_sha256 FROM versions v
           JOIN fetch_state f ON f.source_id=v.source_id
           WHERE v.source_id=? AND v.sha256=?""",
        (source_id, source_sha256),
    ).fetchone()
    if not row or row != ("indexed", source_sha256):
        raise ValueError("Public KB source version is stale or unindexed")
    content = (kb.archive_root / source_id / source_sha256).read_bytes()
    if hashlib.sha256(content).hexdigest() != source_sha256:
        raise ValueError("Public KB source archive hash mismatch")
    record = json.loads(content)
    if record.get("source_format") != "startupdb_company_v1":
        raise ValueError("Unsupported public company source format")

    raw_links = [(record.get("company", {}).get("website_url"), "company_website")]
    for funding in record.get("funding_history", [])[:MAX_CANDIDATES]:
        if isinstance(funding, dict):
            raw_links.extend((url, "funding_announcement") for url in funding.get("source_urls", [])[:MAX_CANDIDATES])
    candidates = {}
    for value, kind in raw_links:
        url = _public_https_url(value)
        if url:
            candidates.setdefault(url, kind)
        if len(candidates) >= MAX_CANDIDATES:
            break

    with kb.conn:
        kb.conn.execute(SCHEMA)
        kb.conn.executemany(
            """INSERT OR IGNORE INTO source_candidates
               (source_id,source_sha256,target_url,source_url,link_kind)
               VALUES (?,?,?,?,?)""",
            [(source_id, source_sha256, url, registered_url, kind)
             for url, kind in candidates.items()],
        )
    return [
        {"url": url, "link_kind": kind, "source_id": source_id,
         "source_sha256": source_sha256, "source_url": registered_url,
         "review_status": "pending_rights_review"}
        for url, kind in candidates.items()
    ]
