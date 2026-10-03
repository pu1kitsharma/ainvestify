import json
from datetime import date

import pytest

from public_kb.ingestion import PublicIngestion
from public_kb.source_candidates import stage_indexed_company_links


def _indexed_kb(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    kb.register_source(
        source_id="public_example",
        url="https://publisher.example/api/company/example",
        terms_url="https://publisher.example/terms",
        reviewed_at=date.today().isoformat(),
        automated_access=True, retention=True, inference_processing=True,
        investor_reuse=True, enabled=True,
    )
    record = {
        "source_format": "startupdb_company_v1",
        "company": {"website_url": "https://company.example/"},
        "funding_history": [{"source_urls": [
            "https://announcements.example/round", "https://announcements.example/round#story",
            "http://unsafe.example/page", "https://127.0.0.1/hidden",
        ]}],
    }
    digest = kb.stage("public_example", json.dumps(record).encode(), content_type="application/json")
    with kb.conn:
        kb.conn.execute("UPDATE versions SET state='indexed' WHERE source_id='public_example'")
        kb.conn.execute("INSERT INTO fetch_state(source_id,last_sha256) VALUES (?,?)",
                        ("public_example", digest))
    return kb, digest


def test_stages_bounded_navigation_only_without_source_approval(tmp_path):
    kb, digest = _indexed_kb(tmp_path)
    try:
        first = stage_indexed_company_links(kb, "public_example", digest)
        second = stage_indexed_company_links(kb, "public_example", digest)
        assert first == second
        assert {item["url"] for item in first} == {
            "https://company.example/", "https://announcements.example/round"}
        assert all(item["review_status"] == "pending_rights_review" for item in first)
        assert all(item["source_sha256"] == digest for item in first)
        assert kb.conn.execute("SELECT count(*) FROM source_candidates").fetchone()[0] == 2
        assert kb.conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
    finally:
        kb.close()
    reopened = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    try:
        assert reopened.conn.execute("SELECT count(*) FROM source_candidates").fetchone()[0] == 2
    finally:
        reopened.close()


def test_requires_current_indexed_rights_approved_hash_verified_source(tmp_path):
    kb, digest = _indexed_kb(tmp_path)
    try:
        with pytest.raises(ValueError, match="stale or unindexed"):
            stage_indexed_company_links(kb, "public_example", "0" * 64)
        with kb.conn:
            kb.conn.execute("UPDATE sources SET enabled=0 WHERE id='public_example'")
        with pytest.raises(PermissionError):
            stage_indexed_company_links(kb, "public_example", digest)
        with kb.conn:
            kb.conn.execute("UPDATE sources SET enabled=1 WHERE id='public_example'")
        (kb.archive_root / "public_example" / digest).write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="hash mismatch"):
            stage_indexed_company_links(kb, "public_example", digest)
    finally:
        kb.close()
