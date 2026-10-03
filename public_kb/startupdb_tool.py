"""Bounded, rights-scoped StartupDB discovery tools for a local model.

Only public search terms may be passed here. Private room text must never be
used to form a query. Search results are ephemeral; only a validated, filtered
company detail response is retained in the shared public KB.
"""
from __future__ import annotations

from datetime import date
import ipaddress
import json
import re
import time
from urllib.parse import quote, urlencode, urlsplit

from agents.discovery.web_sources import PublicWebFetcher, SourceError
from public_kb.ingestion import PublicIngestion
from public_kb.startupdb import project_company

API_ORIGIN = "https://startupdb.com"
TERMS_URL = "https://startupdb.com/legal"
ATTRIBUTION = "StartupDB (https://startupdb.com)"
LICENSE = "CC BY 4.0"
# Rights were reviewed against the publisher's official API/data terms on this
# date. Do not roll this date forward automatically; re-review the terms.
RIGHTS_REVIEWED_AT = "2026-10-01"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PUBLIC_TERM = re.compile(r"[\w .&/-]{2,80}\Z", re.UNICODE)
MAX_CALLS = 12


def _notice(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("license") != LICENSE or payload.get("attribution") != ATTRIBUTION:
        raise ValueError("StartupDB rights notice changed; response rejected")
    return payload


def _text(value: object, size: int) -> str:
    if not isinstance(value, str):
        return ""
    return value[:size]


def _public_reference(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def _search_projection(raw: bytes, source_url: str) -> dict:
    """Keep only identifiers needed for a later detail call, not descriptions."""
    payload = _notice(json.loads(raw))
    data = payload.get("data")
    if isinstance(data, dict):
        data = data.get("startups") or data.get("items")
    if not isinstance(data, list):
        raise ValueError("Unexpected StartupDB search schema")
    matches = []
    for row in data[:20]:
        if not isinstance(row, dict):
            continue
        slug = row.get("slug")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            continue
        matches.append({"slug": slug, "name": _text(row.get("name"), 160)})
    return {"matches": matches, "source_url": source_url,
            "license": LICENSE, "attribution": ATTRIBUTION,
            "scope": "Search identifiers only; inspect each detail record before claiming a fact."}


class StartupDBTool:
    """Expose fixed API operations; never accept model-supplied URLs.

    New detail URLs are registered under this reviewed StartupDB API policy.
    Existing disabled registrations remain disabled and cannot be promoted by a
    model call. The caller must keep all query input public.
    """

    def __init__(self, kb: PublicIngestion, *, fetcher=None, max_calls=MAX_CALLS,
                 max_seconds=90, reviewed_at=None):
        if not 1 <= max_calls <= MAX_CALLS or not 1 <= max_seconds <= 120:
            raise ValueError("StartupDB tool limits exceed the bounded policy")
        self.kb = kb
        self.fetcher = fetcher or PublicWebFetcher(min_interval=5)
        self.max_calls = max_calls
        self.deadline = time.monotonic() + max_seconds
        self.calls = 0
        self.reviewed_at = reviewed_at or RIGHTS_REVIEWED_AT

    def _get(self, path: str, query: dict[str, object] | None = None) -> tuple[bytes, str]:
        if not 0 <= (date.today() - date.fromisoformat(self.reviewed_at)).days <= 180:
            raise PermissionError("StartupDB API rights review has expired")
        if self.calls >= self.max_calls or time.monotonic() >= self.deadline:
            raise SourceError("partial", "StartupDB tool budget exhausted")
        url = API_ORIGIN + path + ("?" + urlencode(query) if query else "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "startupdb.com" or not (
            parsed.path == "/api/v1/startups" or
            re.fullmatch(r"/api/v1/startups/[a-z0-9]+(?:-[a-z0-9]+)*", parsed.path)
        ):
            raise ValueError("Unsupported StartupDB API path")
        self.calls += 1
        self.fetcher._allowed(url, self.deadline)
        status, headers, body = self.fetcher._request(
            url, self.deadline, request_headers={"Accept": "application/json"})
        if status != 200:
            raise SourceError("rate_limited" if status == 429 else "failed",
                              f"StartupDB API returned HTTP {status}")
        media = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
        encoding = next((v for k, v in headers.items() if k.lower() == "content-encoding"), "")
        if media.split(";", 1)[0].strip().lower() != "application/json" or encoding.lower() not in ("", "identity"):
            raise SourceError("blocked", "Unexpected StartupDB response media type")
        if not body or len(body) > 3_000_000:
            raise SourceError("blocked", "StartupDB response size is invalid")
        return body, url

    def search_startups(self, query: str, *, limit: int = 5, offset: int = 0) -> dict:
        if not isinstance(query, str):
            raise ValueError("A short public search term is required")
        term = query.strip()
        if (not PUBLIC_TERM.fullmatch(term) or "@" in term or "//" in term or
                re.search(r"\d{7,}", term) or
                re.search(r"\b(?:confidential|private|secret|password|token)\b", term, re.I)):
            raise ValueError("Only short public search terms are permitted")
        if not isinstance(limit, int) or not 1 <= limit <= 20 or not isinstance(offset, int) or not 0 <= offset <= 100:
            raise ValueError("StartupDB search pagination exceeds bounds")
        raw, url = self._get("/api/v1/startups", {"q": term, "limit": limit, "offset": offset})
        return _search_projection(raw, url)

    def get_startup(self, slug: str) -> dict:
        if not isinstance(slug, str) or len(slug) > 50 or not SLUG.fullmatch(slug):
            raise ValueError("Invalid StartupDB company slug")
        raw, url = self._get("/api/v1/startups/" + quote(slug))
        projected = project_company(raw)
        record = json.loads(projected)
        if record["company"]["slug"] != slug:
            raise ValueError("StartupDB response identity does not match request")
        website = record["company"].get("website_url", "")
        if website and not _public_reference(website):
            record["company"]["website_url"] = ""
        for round_item in record["funding_history"]:
            round_item["source_urls"] = [source_url for source_url in round_item["source_urls"]
                                         if _public_reference(source_url)]
        projected = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        source_id = "startupdb_" + slug.replace("-", "_")
        existing = self.kb.conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone()
        if existing:
            if self.kb.approved_source(source_id) != url:
                raise PermissionError("StartupDB source registration URL does not match")
        else:
            self.kb.register_source(
                source_id=source_id, url=url, terms_url=TERMS_URL,
                reviewed_at=self.reviewed_at, automated_access=True, retention=True,
                inference_processing=True, investor_reuse=True, enabled=True)
        digest = self.kb.stage(source_id, projected, source_url=url,
                               content_type="application/json")
        return {"record": record, "source_url": url, "source_id": source_id,
                "source_version_id": f"{source_id}:{digest}", "license": LICENSE,
                "attribution": ATTRIBUTION}
