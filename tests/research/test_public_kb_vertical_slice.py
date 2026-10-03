"""Synthetic, rights-approved public sources only; no private acceptance inputs."""
from datetime import date
import json

import pytest

from public_kb.claims import ingest_indexed
from public_kb.collector import collect_source
from public_kb.ingestion import PublicIngestion
from public_kb.schedule import claim_due, finish, set_policy, status
from public_kb.traversal import record_links, record_target_outcome
from scripts.run_public_kb import run_pass


def approved(kb, source_id, url):
    kb.register_source(source_id=source_id, url=url, terms_url="https://terms.example/license",
        reviewed_at=date.today().isoformat(), automated_access=True, retention=True,
        inference_processing=True, investor_reuse=True, enabled=True)


def indexed(kb, source_id, content, media="application/json"):
    digest = kb.stage(source_id, content, content_type=media)
    kb.publish_pending(lambda *_: None)
    return digest


def company(stage, when, domain="example.org", amount="20", currency="USD"):
    return json.dumps({"source_format": "startupdb_company_v1",
        "company": {"name": "Example", "domain": domain, "website_url": "https://example.org"},
        "funding_history": [{"label": stage, "date": when, "status": "completed",
            "amount": {"original": amount, "currency": currency},
            "source_urls": []}]}, sort_keys=True).encode()


def test_two_identical_ticks_and_six_twelve_hour_cadence(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "news", "https://news.example/item")
    approved(kb, "profile", "https://profile.example/company")
    set_policy(kb, "news", "announcement")
    set_policy(kb, "profile", "profile")
    first = claim_due(kb, now=1000)
    second = claim_due(kb, now=1000)
    assert first and second[1] != first[1]
    assert claim_due(kb, now=1000) is None
    finish(kb, first[0], first[2], digest="hash", now=1000)
    finish(kb, second[0], second[2], digest="hash", now=1000)
    assert claim_due(kb, now=1000) is None
    assert status(kb, now=1000)[0]["next_due"] == 22600
    assert claim_due(kb, now=22599) is None
    assert claim_due(kb, now=22600)[1] == "news"
    kb.close()


def test_failure_does_not_advance_cursor_and_lease_recovers(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "news", "https://news.example/item")
    set_policy(kb, "news", "announcement")
    job = claim_due(kb, now=1000)
    finish(kb, job[0], job[2], error=RuntimeError("ES unavailable"), now=1001)
    assert status(kb, now=1002)[0]["next_due"] == 0
    assert claim_due(kb, now=1060) is None
    retried = claim_due(kb, now=1061)
    assert retried[0] == job[0]
    assert claim_due(kb, now=1062) is None
    recovered = claim_due(kb, now=1182)
    assert recovered[0] == job[0] and recovered[2] != retried[2]
    finish(kb, recovered[0], recovered[2], digest="hash", now=1183)
    assert status(kb, now=1183)[0]["last_success"] == 1183
    assert kb.conn.execute("SELECT count(*) FROM refresh_job").fetchone()[0] == 1
    kb.close()


def test_link_outcomes_are_durable_and_require_separate_rights(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "directory", "https://directory.example/list")
    approved(kb, "profile", "https://directory.example/company")
    set_policy(kb, "directory", "directory")
    set_policy(kb, "profile", "profile", active=False)
    assert next(x for x in status(kb) if x["source_id"] == "profile")["active"] is False
    html = (b'<a href="/company">Profile</a><a href="https://unknown.example/news">News</a>'
            b'<a href="http://127.0.0.1/private">Bad</a>')
    digest = indexed(kb, "directory", html, "text/html")
    assert record_links(kb, "directory", digest) == 3
    assert next(x for x in status(kb) if x["source_id"] == "profile")["active"] is True
    assert record_links(kb, "directory", digest) == 3
    rows = kb.conn.execute("SELECT outcome,reason FROM observed_link ORDER BY ordinal").fetchall()
    assert rows == [("queued", "separately_rights_approved"),
                    ("blocked", "target_rights_or_policy_missing"),
                    ("blocked", "invalid_or_nonpublic_url")]
    assert kb.conn.execute("SELECT count(*) FROM collection_event WHERE phase='link'").fetchone()[0] == 3
    assert record_target_outcome(kb, "profile", outcome="failed", reason="HTTP 503") == 1
    assert kb.conn.execute("SELECT outcome,reason FROM observed_link WHERE ordinal=0").fetchone() == ("failed", "HTTP 503")
    assert record_target_outcome(kb, "profile", outcome="fetched",
                                 reason="indexed_refresh_completed", digest="abc") == 1
    assert kb.conn.execute("SELECT outcome FROM observed_link WHERE ordinal=0").fetchone()[0] == "fetched"
    assert kb.conn.execute("SELECT count(*) FROM collection_event WHERE phase='link'").fetchone()[0] == 5
    kb.close()


def test_newer_round_supersedes_old_seed_without_erasing_claims(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "directory", "https://directory.example/company")
    approved(kb, "announcement", "https://announcement.example/story")
    old = indexed(kb, "directory", company("Seed", "2024-01-01"))
    first = ingest_indexed(kb, "directory", old)[0]
    assert first["stage"] == "Seed"
    new = indexed(kb, "announcement", company("Series A", "2026-08-25"))
    current = ingest_indexed(kb, "announcement", new)[0]
    assert current["stage"] == "Series A"
    assert current["revision"] != first["revision"]
    assert len(current["supporting_claim_ids"]) == 1
    assert len(current["opposing_claim_ids"]) == 1
    assert kb.conn.execute("SELECT count(*) FROM public_funding_claim").fetchone()[0] == 2
    assert ingest_indexed(kb, "announcement", new)[0] == current
    kb.close()


def test_same_date_conflict_and_distinct_domain_do_not_merge(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "one", "https://one.example/company")
    approved(kb, "two", "https://two.example/company")
    approved(kb, "three", "https://three.example/company")
    for source_id, stage, domain in [("one", "Seed", "example.org"),
                                     ("two", "Series A", "example.org"),
                                     ("three", "Series B", "other.org")]:
        ingest_indexed(kb, source_id, indexed(kb, source_id,
                       company(stage, "2026-01-01", domain)))
    row = kb.conn.execute("SELECT status,stage FROM public_company_projection WHERE entity_key='domain:example.org'").fetchone()
    assert row == ("conflicted", None)
    assert kb.conn.execute("SELECT count(*) FROM public_company_projection").fetchone()[0] == 2
    kb.close()


def test_open_or_unspecified_round_cannot_be_projected_as_current_stage(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "profile", "https://profile.example/company")
    record = json.loads(company("Seed", "2026-01-01"))
    record["funding_history"][0]["status"] = "open"
    first = ingest_indexed(kb, "profile", indexed(kb, "profile", json.dumps(record).encode()))[0]
    assert first["stage"] is None and first["status"] == "unknown_completion"
    assert len(first["supporting_claim_ids"]) == 1
    assert kb.conn.execute("SELECT event_status FROM public_funding_claim").fetchone()[0] == "open"
    record["funding_history"][0].pop("status")
    second = ingest_indexed(kb, "profile", indexed(kb, "profile", json.dumps(record).encode()))[0]
    assert second["stage"] is None and second["status"] == "unknown_completion"
    assert second["revision"] != first["revision"]
    assert kb.conn.execute("SELECT count(*) FROM public_funding_claim").fetchone()[0] == 2
    kb.close()


def test_future_dated_completed_entry_is_not_current_company_stage(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "profile", "https://profile.example/company")
    result = ingest_indexed(kb, "profile", indexed(kb, "profile",
        company("Series A", "2099-01-01")))[0]
    assert result["status"] == "future_dated" and result["stage"] is None
    assert len(result["supporting_claim_ids"]) == 1
    kb.close()


@pytest.mark.parametrize("reported_date,precision", [
    ("2026-06", "month"), ("2025", "year"), ("2026-06-15", "day")])
def test_source_date_precision_is_retained_without_inventing_a_day(tmp_path, reported_date, precision):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "profile", "https://profile.example/company")
    record = json.loads(company("Seed", "2026-01-01"))
    record["funding_history"][0].update({"date": reported_date,
                                          "date_precision": precision})
    row = ingest_indexed(kb, "profile", indexed(kb, "profile",
        json.dumps(record).encode()))[0]
    assert row["event_date"] == reported_date
    assert kb.conn.execute("SELECT event_date,event_date_precision FROM public_funding_claim").fetchone() == (reported_date, precision)
    kb.close()


def test_overlapping_partial_dates_do_not_invent_a_current_stage(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "month", "https://month.example/company")
    approved(kb, "day", "https://day.example/company")
    month = json.loads(company("Seed", "2025-01-01"))
    month["funding_history"][0].update({"date": "2025-01", "date_precision": "month"})
    ingest_indexed(kb, "month", indexed(kb, "month", json.dumps(month).encode()))
    result = ingest_indexed(kb, "day", indexed(kb, "day",
        company("Series A", "2025-01-31")))[0]
    assert result["status"] == "conflicted" and result["stage"] is None
    assert len(result["supporting_claim_ids"]) == 2
    kb.close()


def test_future_partial_date_cannot_project_a_current_stage(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "profile", "https://profile.example/company")
    record = json.loads(company("Seed", "2025-01-01"))
    record["funding_history"][0].update({"date": "2099", "date_precision": "year"})
    result = ingest_indexed(kb, "profile", indexed(kb, "profile",
        json.dumps(record).encode()))[0]
    assert result["status"] == "future_dated" and result["stage"] is None
    kb.close()


@pytest.mark.parametrize("reported_date,precision", [
    ("2026-13", "month"), ("2026-06-01", "month"), ("2026", "day"),
    ("0000", "year"), ("0000-01", "month")])
def test_invalid_or_mismatched_source_date_precision_is_excluded(tmp_path, reported_date, precision):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "profile", "https://profile.example/company")
    record = json.loads(company("Seed", "2026-01-01"))
    record["funding_history"][0].update({"date": reported_date,
                                          "date_precision": precision})
    row = ingest_indexed(kb, "profile", indexed(kb, "profile",
        json.dumps(record).encode()))[0]
    assert row["status"] == "unknown_no_current_claim"
    assert kb.conn.execute("SELECT count(*) FROM public_funding_claim").fetchone()[0] == 0
    kb.close()


def test_existing_claim_ledger_adds_completion_status_without_reset(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "profile", "https://profile.example/company")
    kb.conn.execute("""CREATE TABLE public_funding_claim (
        id TEXT PRIMARY KEY, entity_key TEXT NOT NULL, source_id TEXT NOT NULL,
        source_sha256 TEXT NOT NULL, source_path TEXT NOT NULL,
        event_date TEXT NOT NULL, stage TEXT NOT NULL, amount TEXT,
        currency TEXT, amount_semantics TEXT NOT NULL,
        evidence_status TEXT NOT NULL DEFAULT 'source_reported',
        UNIQUE(source_id,source_sha256,source_path))""")
    digest = indexed(kb, "profile", company("Seed", "2026-01-01"))
    row = ingest_indexed(kb, "profile", digest)[0]
    assert row["stage"] == "Seed"
    assert kb.conn.execute("SELECT event_status FROM public_funding_claim").fetchone()[0] == "completed"
    assert ingest_indexed(kb, "profile", digest)[0] == row
    kb.close()


def test_source_correction_removes_old_stage_from_current_projection(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "directory", "https://directory.example/company")
    original = indexed(kb, "directory", company("Seed", "2025-01-01"))
    assert ingest_indexed(kb, "directory", original)[0]["stage"] == "Seed"
    correction = json.dumps({"source_format": "startupdb_company_v1",
        "company": {"name": "Example", "domain": "example.org"},
        "funding_history": []}, sort_keys=True).encode()
    replacement = indexed(kb, "directory", correction)
    assert replacement != original
    current = ingest_indexed(kb, "directory", replacement)[0]
    assert current["status"] == "unknown_no_current_claim"
    assert current["stage"] is None
    assert len(current["opposing_claim_ids"]) == 1
    assert kb.conn.execute("SELECT count(*) FROM public_funding_claim").fetchone()[0] == 1
    kb.close()


def test_corrected_identity_invalidates_old_domain_projection(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "directory", "https://directory.example/company")
    first = indexed(kb, "directory", company("Seed", "2025-01-01", "old.example"))
    ingest_indexed(kb, "directory", first)
    second = indexed(kb, "directory", company("Series A", "2026-01-01", "new.example"))
    changed = ingest_indexed(kb, "directory", second)
    assert {row["entity_key"] for row in changed} == {"domain:old.example", "domain:new.example"}
    old = kb.conn.execute("SELECT stage,status FROM public_company_projection WHERE entity_key='domain:old.example'").fetchone()
    assert old == (None, "unknown_no_current_claim")
    new = kb.conn.execute("SELECT stage,status FROM public_company_projection WHERE entity_key='domain:new.example'").fetchone()
    assert new == ("Series A", "current_source_reported")
    assert kb.conn.execute("SELECT count(*) FROM public_funding_claim").fetchone()[0] == 2
    kb.close()


def test_304_requires_intact_archive(tmp_path):
    class Fetcher:
        def _allowed(self, *args):
            pass
        def _request(self, *args, **kwargs):
            return 304, {}, b""
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "source", "https://source.example/page")
    with kb.conn:
        kb.conn.execute("INSERT INTO fetch_state(source_id,last_sha256) VALUES (?,?)", ("source", "absent"))
    with pytest.raises(Exception, match="intact archived version"):
        collect_source(kb, "source", fetcher=Fetcher())
    assert kb.conn.execute("SELECT last_checked FROM fetch_state WHERE source_id='source'").fetchone()[0] is None
    kb.close()


def test_worker_tick_indexes_once_and_does_not_repeat_unchanged_work(tmp_path, monkeypatch):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    approved(kb, "directory", "https://directory.example/list")
    set_policy(kb, "directory", "directory")
    calls = []

    def collect(kb, source_id):
        calls.append(source_id)
        digest = kb.stage(source_id, b'<a href="/profile">Profile</a>',
                          content_type="text/html")
        with kb.conn:
            kb.conn.execute("""INSERT INTO fetch_state(source_id,last_sha256)
                VALUES (?,?) ON CONFLICT(source_id) DO UPDATE SET
                last_sha256=excluded.last_sha256""", (source_id, digest))
        return "staged"

    class Sink:
        def __init__(self, kb):
            self.publish = lambda *_: None

    monkeypatch.setattr("scripts.run_public_kb.collect_source", collect)
    monkeypatch.setattr("scripts.run_public_kb.ElasticsearchPublicKB", Sink)
    first = run_pass(kb)
    second = run_pass(kb)
    assert first["collected"] == 1 and first["errors"] == 0
    assert second["collected"] == 0 and second["errors"] == 0
    assert calls == ["directory"]
    assert kb.conn.execute("SELECT state FROM versions").fetchone()[0] == "indexed"
    assert kb.conn.execute("SELECT outcome FROM observed_link").fetchone()[0] == "blocked"
    kb.close()
