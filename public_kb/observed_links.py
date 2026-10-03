"""Public destinations already observed in an indexed, rights-cleared company record.

Links are navigation candidates only. Their URL text is not article evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from agents.discovery.web_sources import SourceError, normalize_url
from public_kb.ingestion import PublicIngestion


def company_links(profile):
    provenance = profile.provenance
    if provenance.get("origin") != "public_kb":
        return []
    db_name, archive_name = os.environ.get("PUBLIC_KB_DB"), os.environ.get("PUBLIC_KB_ARCHIVE")
    if not db_name or not archive_name:
        raise RuntimeError("Public KB paths are required for bound company research")
    kb = PublicIngestion(Path(db_name), Path(archive_name))
    try:
        source_id, digest = provenance["source_id"], provenance["source_version"]
        source_url = kb.approved_source(source_id)
        current = kb.conn.execute("""SELECT v.state FROM versions v JOIN fetch_state f
            ON f.source_id=v.source_id AND f.last_sha256=v.sha256
            WHERE v.source_id=? AND v.sha256=?""", (source_id, digest)).fetchone()
        if not current or current[0] != "indexed":
            raise ValueError("Bound public KB source is stale or unindexed")
        content = (kb.archive_root / source_id / digest).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Bound public KB archive hash mismatch")
        record = json.loads(content)
        if record.get("source_format") != "startupdb_company_v1":
            raise ValueError("Unsupported public company source")
        website = record.get("company", {}).get("website_url")
        links = ([{"url": website, "label": "publisher-reported company website",
                   "from_url": source_url}] if isinstance(website, str) else [])
        for round_ in record.get("funding_history", []):
            for url in round_.get("source_urls", []):
                links.append({"url": url, "label": "publisher-listed funding source", "from_url": source_url})
        unique = {}
        for item in links:
            try:
                url = normalize_url(item["url"])
            except (KeyError, AttributeError, SourceError):
                continue
            unique.setdefault(url, {**item, "url": url})
        return list(unique.values())[:80]
    finally:
        kb.close()
