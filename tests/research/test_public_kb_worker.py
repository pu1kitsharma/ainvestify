import pytest
from datetime import date
import json

from public_kb.ingestion import PublicIngestion
from scripts.run_public_kb import run_pass, reindex_retained, backfill_indexed_claims
from tests.research.test_public_kb_ingestion import source


def test_worker_does_not_fetch_disabled_sources_or_overlap(tmp_path, monkeypatch):
    db, archive = tmp_path / "kb.sqlite", tmp_path / "archive"
    kb = PublicIngestion(db, archive)
    source(kb, enabled=False)
    monkeypatch.setattr("scripts.run_public_kb.collect_source", lambda *args: pytest.fail("disabled source fetched"))
    assert run_pass(kb)["collected"] == 0
    with kb.conn:
        kb.conn.execute("INSERT INTO worker_lease VALUES ('pilot','another-worker',9999999999)")
    assert run_pass(kb)["status"] == "leased"
    kb.close()


def test_worker_bounds_are_enforced(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    with pytest.raises(ValueError):
        run_pass(kb, max_documents=101)
    with pytest.raises(ValueError):
        run_pass(kb, duration=601)
    kb.close()


def test_replay_retained_versions_is_bounded_and_preserves_archives(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    source(kb)
    first = kb.stage('approved-feed', b'public version one')
    second = kb.stage('approved-feed', b'public version two')
    kb.publish_pending(lambda *_: None)
    seen = []
    page = reindex_retained(kb, lambda *args: seen.append(args), max_documents=1)
    assert page['reindexed'] == 1
    following = reindex_retained(kb, lambda *args: seen.append(args), after=page['next_after'])
    assert following['reindexed'] == 1
    assert {item[1] for item in seen} == {first, second}
    assert kb.conn.execute("SELECT count(*) FROM versions WHERE state='indexed'").fetchone()[0] == 2
    kb.close()


def _startupdb_source(kb, source_id, *, enabled=True):
    kb.register_source(source_id=source_id,
        url=f"https://startupdb.com/api/v1/startups/{source_id}",
        terms_url="https://startupdb.com/terms", reviewed_at=date.today().isoformat(),
        automated_access=True, retention=True, inference_processing=True,
        investor_reuse=True, enabled=enabled)


def _startupdb_version(kb, source_id, *, stage, event_date, status="completed"):
    content = json.dumps({"source_format": "startupdb_company_v1", "license": "CC BY 4.0",
        "attribution": "StartupDB (https://startupdb.com)",
        "company": {"name": "Synthetic Company", "domain": "synthetic.example"},
        "funding_history": [{"label": stage, "date": event_date, "status": status,
                             "amount": {"original": "1", "currency": "USD"}}]},
        sort_keys=True).encode()
    digest = kb.stage(source_id, content, content_type="application/json")
    kb.publish_pending(lambda *_: None)
    return digest


def test_claim_backfill_pages_are_idempotent_and_preserve_versions(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    _startupdb_source(kb, "synthetic-one")
    first = _startupdb_version(kb, "synthetic-one", stage="Seed", event_date="2024-01-01")
    second = _startupdb_version(kb, "synthetic-one", stage="Series A", event_date="2026-01-01")
    assert kb.conn.execute("SELECT name FROM sqlite_master WHERE name='public_funding_claim'").fetchone() is None
    page = backfill_indexed_claims(kb, max_documents=1)
    following = backfill_indexed_claims(kb, max_documents=1, after=page["next_after"])
    assert page["processed"] == following["processed"] == 1
    assert {page["next_after"], following["next_after"]} == {
        "synthetic-one:" + first, "synthetic-one:" + second}
    assert backfill_indexed_claims(kb)["processed"] == 2
    assert kb.conn.execute("SELECT count(*) FROM public_funding_claim").fetchone()[0] == 2
    assert kb.conn.execute("SELECT count(*) FROM versions WHERE state='indexed'").fetchone()[0] == 2
    assert kb.conn.execute("SELECT stage FROM public_company_projection").fetchone()[0] == "Series A"
    kb.close()


def test_claim_backfill_excludes_revoked_and_other_publishers(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    _startupdb_source(kb, "synthetic-one")
    digest = _startupdb_version(kb, "synthetic-one", stage="Seed", event_date="2024-01-01")
    _startupdb_source(kb, "synthetic-one", enabled=False)
    source(kb)
    kb.stage("approved-feed", b"unrelated public record")
    kb.publish_pending(lambda *_: None)
    assert backfill_indexed_claims(kb)["processed"] == 0
    assert kb.conn.execute("SELECT name FROM sqlite_master WHERE name='public_funding_claim'").fetchone() is None
    _startupdb_source(kb, "synthetic-one")
    assert backfill_indexed_claims(kb)["next_after"] == "synthetic-one:" + digest
    kb.close()


def test_claim_backfill_rejects_bad_archive_and_does_not_advance_cursor(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    _startupdb_source(kb, "synthetic-one")
    digest = _startupdb_version(kb, "synthetic-one", stage="Seed", event_date="2024-01-01")
    archive = tmp_path / "archive" / "synthetic-one" / digest
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        backfill_indexed_claims(kb)
    assert kb.conn.execute("SELECT name FROM sqlite_master WHERE name='public_funding_claim'").fetchone() is None
    assert kb.conn.execute("SELECT count(*) FROM worker_lease").fetchone()[0] == 0
    kb.close()


def test_claim_backfill_rejects_unreviewed_projection_format(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    _startupdb_source(kb, "synthetic-one")
    digest = kb.stage("synthetic-one", b'{"source_format":"startupdb_company_v1"}',
                      content_type="application/json")
    kb.publish_pending(lambda *_: None)
    with pytest.raises(ValueError, match="reviewed fact projection"):
        backfill_indexed_claims(kb)
    assert kb.conn.execute("SELECT name FROM sqlite_master WHERE name='public_funding_claim'").fetchone() is None
    assert kb.conn.execute("SELECT state FROM versions WHERE sha256=?", (digest,)).fetchone()[0] == "indexed"
    kb.close()


def test_claim_backfill_respects_worker_lease_and_bounds(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    with pytest.raises(ValueError):
        backfill_indexed_claims(kb, max_documents=101)
    with pytest.raises(ValueError):
        backfill_indexed_claims(kb, duration=601)
    with kb.conn:
        kb.conn.execute("INSERT INTO worker_lease VALUES ('pilot','another-worker',9999999999)")
    assert backfill_indexed_claims(kb)["status"] == "leased"
    kb.close()
