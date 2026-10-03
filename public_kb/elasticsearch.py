"""Idempotent local Elasticsearch sink for retained, rights-cleared passages.

These are source observations, not validated company claims. A source revision is
kept separately from the current searchable copy. No private room data enters
this module.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests

from public_kb.extraction import extract
from public_kb.ingestion import PublicIngestion

VERSIONS = "ainvestify-kb-source-versions-v1"
CURRENT = "ainvestify-kb-sources-v1"
MAPPING = {"settings": {"number_of_replicas": 0},
           "mappings": {"dynamic": "strict", "properties": {
    "source_id": {"type": "keyword"}, "sha256": {"type": "keyword"},
    "url": {"type": "keyword"}, "terms_url": {"type": "keyword"},
    "license": {"type": "keyword"}, "attribution": {"type": "keyword"},
    "reviewed_at": {"type": "date"}, "fetched_at": {"type": "date", "format": "epoch_second"},
    "title": {"type": "text"}, "text": {"type": "text"},
    "passages": {"type": "text"}, "evidence_status": {"type": "keyword"},
    "entity_id": {"type": "keyword"},
    "statements": {"type": "nested", "properties": {
        "property_id": {"type": "keyword"}, "value": {"type": "keyword", "ignore_above": 512},
        "source_path": {"type": "keyword"}, "rank": {"type": "keyword"},
        "reference_count": {"type": "integer"}}}
}}}


class ElasticsearchPublicKB:
    def __init__(self, kb: PublicIngestion, *, url=None, session=None):
        self.kb = kb
        self.url = (url or os.environ.get("ELASTICSEARCH_URL", "")).rstrip("/")
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("Public KB Elasticsearch must be a loopback endpoint")
        self.session = session or requests.Session()
        self.session.trust_env = False
        if os.environ.get("ELASTICSEARCH_CA_FILE"):
            self.session.verify = os.environ["ELASTICSEARCH_CA_FILE"]
        key = os.environ.get("ELASTICSEARCH_API_KEY")
        if not key and os.environ.get("ELASTICSEARCH_API_KEY_FILE"):
            key = Path(os.environ["ELASTICSEARCH_API_KEY_FILE"]).read_text().strip()
        if key:
            self.session.headers["Authorization"] = "ApiKey " + key

    def _request(self, method, path, body=None, *, expected=(200, 201)):
        try:
            response = self.session.request(method, self.url + path, json=body, timeout=5, allow_redirects=False)
        except requests.RequestException as exc:
            raise RuntimeError("Local public KB Elasticsearch is unavailable") from exc
        if response.status_code not in expected:
            raise RuntimeError(f"Local public KB Elasticsearch returned HTTP {response.status_code}")
        return response.json() if response.content else {}

    def ensure_indices(self):
        for name in (VERSIONS, CURRENT):
            # A concurrent creator can win after HEAD. The mapping must then be
            # checked by an operator before enabling publication.
            result = self.session.request("HEAD", self.url + "/" + name, timeout=5, allow_redirects=False)
            if result.status_code == 404:
                self._request("PUT", "/" + name, MAPPING)
            elif result.status_code != 200:
                raise RuntimeError("Local public KB index check failed")

    def publish(self, source_id, digest, content):
        self.kb.approved_source(source_id)
        row = self.kb.conn.execute("""SELECT m.source_url,m.terms_url,m.reviewed_at,v.fetched_at,m.content_type
            FROM version_metadata m JOIN versions v ON v.source_id=m.source_id AND v.sha256=m.sha256
            WHERE m.source_id=? AND m.sha256=?""", (source_id, digest)).fetchone()
        if not row:
            raise ValueError("Unstaged public source version")
        url, terms_url, reviewed_at, fetched_at, content_type = row
        extracted = extract(content, content_type, url)
        title, passages = extracted["title"], extracted["passages"]
        license_name = attribution = None
        if content_type == "application/json":
            import json
            projected = json.loads(content)
            if projected.get("source_format") == "startupdb_company_v1":
                license_name, attribution = projected["license"], projected["attribution"]
        document = {"source_id": source_id, "sha256": digest, "url": url,
                    "terms_url": terms_url, "license": license_name,
                    "attribution": attribution, "reviewed_at": reviewed_at,
                    "fetched_at": fetched_at, "title": title[:200],
                    "text": "\n".join(passages)[:50000], "passages": passages,
                    "evidence_status": "source_reported",
                    "entity_id": extracted["entity_id"],
                    "statements": extracted["statements"]}
        self.ensure_indices()
        version_key = quote(source_id + ":" + digest, safe="")
        self._request("PUT", f"/{VERSIONS}/_doc/{version_key}?refresh=wait_for", document)
        # A late worker may archive an older revision after the newer one. It
        # must not replace the current searchable source copy.
        state = self.kb.conn.execute("SELECT last_sha256 FROM fetch_state WHERE source_id=?", (source_id,)).fetchone()
        latest = self.kb.conn.execute(
            "SELECT sha256 FROM versions WHERE source_id=? ORDER BY fetched_at DESC, rowid DESC LIMIT 1",
            (source_id,)).fetchone()
        if latest and latest[0] == digest and state and state[0] not in (None, digest):
            raise RuntimeError("A newer public source fetch has not committed its version checkpoint")
        if latest and latest[0] == digest and (not state or state[0] in (None, digest)):
            self._request("PUT", f"/{CURRENT}/_doc/{quote(source_id, safe='')}?refresh=wait_for", document)

    def search(self, public_query: str, *, limit=10, max_age_seconds=86400):
        if not isinstance(public_query, str) or not 2 <= len(public_query.strip()) <= 160 or not 1 <= limit <= 20:
            raise ValueError("Bounded public KB query required")
        result = self._request("POST", f"/{CURRENT}/_search", {
            "size": limit, "query": {"multi_match": {"query": public_query,
                "fields": ["title^3", "text"]}}, "sort": ["_score"]})
        evidence = []
        for hit in result.get("hits", {}).get("hits", []):
            item = hit.get("_source", {})
            state = self.kb.conn.execute("SELECT last_checked,last_sha256 FROM fetch_state WHERE source_id=?",
                                         (item.get("source_id"),)).fetchone()
            if state and state[1] and state[1] != item.get("sha256"):
                continue
            checked_at = state[0] if state and state[1] == item.get("sha256") else item.get("fetched_at")
            if not isinstance(checked_at, (int, float)) or not 0 <= time.time() - checked_at <= max_age_seconds:
                continue
            try:
                self.kb.approved_source(item["source_id"])
            except (KeyError, PermissionError):
                continue
            if self.kb.conn.execute("SELECT 1 FROM versions WHERE source_id=? AND sha256=?", (item["source_id"], item.get("sha256"))).fetchone():
                evidence.append(item)
        return evidence
