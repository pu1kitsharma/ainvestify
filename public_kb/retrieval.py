"""Read retained public passages for discovery and company research."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from agents.discovery.web_sources import Page
from public_kb.elasticsearch import ElasticsearchPublicKB
from public_kb.ingestion import PublicIngestion


def search_pages(public_query: str, *, limit=10) -> list[Page]:
    """Only a public search term belongs here; never pass room notes or uploads."""
    db_name = os.environ.get("PUBLIC_KB_DB")
    archive_name = os.environ.get("PUBLIC_KB_ARCHIVE")
    if not db_name or not archive_name:
        return []
    db, archive = Path(db_name), Path(archive_name)
    if not db.is_file() or not archive.is_dir():
        raise RuntimeError("Configured public KB archive is unavailable")
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as check:
        if not check.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sources'").fetchone():
            raise RuntimeError("Configured database is not a public KB registry")
    kb = PublicIngestion(db, archive)
    try:
        records = ElasticsearchPublicKB(kb).search(public_query, limit=limit)
        return [Page(url=row["url"], title=row["title"], text=row["text"],
                     content_blocks=row["passages"],
                     source_version_id=row["source_id"] + ":" + row["sha256"])
                for row in records]
    finally:
        kb.close()
