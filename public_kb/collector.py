"""Single-source, rights-gated public collection. No room input enters this API."""
from __future__ import annotations

import secrets
import hashlib
import time
from urllib.parse import urljoin, urlsplit

from agents.discovery.web_sources import PublicWebFetcher, SourceError, normalize_url
from public_kb.ingestion import MAX_PUBLIC_BYTES, PublicIngestion

SUPPORTED_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/json")


def _header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name), "")


def collect_source(kb: PublicIngestion, source_id: str, *, fetcher=None):
    """Fetch one approved URL; a second worker skips its live lease.

    A publisher's rights must already be recorded by an operator. This method
    never accepts an arbitrary URL or private research query from a caller.
    """
    url = kb.approved_source(source_id)
    fetcher = fetcher or PublicWebFetcher(min_interval=5)
    owner = secrets.token_hex(16)
    now = time.time()
    kb.conn.execute("BEGIN IMMEDIATE")
    try:
        state = kb.conn.execute("SELECT etag,last_modified,lease_until,last_sha256 FROM fetch_state WHERE source_id=?", (source_id,)).fetchone()
        if state and state[2] and state[2] > now:
            kb.conn.commit()
            return "leased"
        kb.conn.execute("""INSERT INTO fetch_state(source_id,lease_owner,lease_until) VALUES (?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET lease_owner=excluded.lease_owner,
            lease_until=excluded.lease_until""", (source_id, owner, now + 120))
        kb.conn.commit()
    except Exception:
        kb.conn.rollback()
        raise
    try:
        headers = {}
        if urlsplit(url).hostname == "startupdb.com" and urlsplit(url).path.startswith("/api/"):
            headers["Accept"] = "application/json"
        if state and state[0]:
            headers["If-None-Match"] = state[0]
        if state and state[1]:
            headers["If-Modified-Since"] = state[1]
        deadline = time.monotonic() + 90
        origin_host = urlsplit(normalize_url(url)).hostname
        for _ in range(4):
            fetcher._allowed(url, deadline)
            status, response_headers, body = fetcher._request(url, deadline, request_headers=headers)
            if status not in {301, 302, 303, 307, 308}:
                break
            location = _header(response_headers, "location")
            if not location:
                raise SourceError("blocked", "Redirect has no destination")
            next_url = normalize_url(urljoin(url, location))
            if urlsplit(next_url).scheme != "https" or urlsplit(next_url).hostname != origin_host:
                raise SourceError("blocked", "A registered source cannot redirect to another host")
            url = next_url
        else:
            raise SourceError("blocked", "Too many public source redirects")
        if status == 304:
            previous = state[3] if state else None
            archived = kb.archive_root / source_id / previous if previous else None
            if not archived or not archived.is_file() or hashlib.sha256(archived.read_bytes()).hexdigest() != previous:
                raise SourceError("blocked", "HTTP 304 has no intact archived version")
            result, digest = "unchanged", None
        elif status == 200:
            media_type = _header(response_headers, "content-type").split(";", 1)[0].lower().strip()
            if media_type not in SUPPORTED_TYPES or _header(response_headers, "content-encoding").lower() not in ("", "identity"):
                raise SourceError("blocked", "Unsupported public source media type or encoding")
            if not body or len(body) > MAX_PUBLIC_BYTES:
                raise SourceError("blocked", "Public source is empty or exceeds archive limit")
            if urlsplit(url).hostname == "startupdb.com" and urlsplit(url).path.startswith("/api/v1/startups/"):
                from public_kb.startupdb import project_company
                body = project_company(body)
                import json
                if urlsplit(url).path.rsplit("/", 1)[-1] != json.loads(body)["company"]["slug"]:
                    raise SourceError("blocked", "StartupDB response identity does not match registered source")
            # Recheck rights after network I/O, before retaining any bytes.
            kb.approved_source(source_id)
            digest = kb.stage(source_id, body, source_url=url, content_type=media_type)
            result = "unchanged" if state and state[3] == digest else "staged"
        else:
            raise SourceError("rate_limited" if status == 429 else "failed", f"Public source returned HTTP {status}")
        with kb.conn:
            kb.conn.execute("""UPDATE fetch_state SET etag=?,last_modified=?,last_checked=?,
                last_status=?,last_sha256=COALESCE(?,last_sha256),lease_owner=NULL,lease_until=NULL
                WHERE source_id=? AND lease_owner=?""", (
                _header(response_headers, "etag") or (state[0] if state else None),
                _header(response_headers, "last-modified") or (state[1] if state else None),
                time.time(), status, digest, source_id, owner))
        return result
    except Exception:
        with kb.conn:
            kb.conn.execute("UPDATE fetch_state SET lease_owner=NULL,lease_until=NULL WHERE source_id=? AND lease_owner=?", (source_id, owner))
        raise
