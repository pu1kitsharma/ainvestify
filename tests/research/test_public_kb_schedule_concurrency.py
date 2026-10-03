"""Two-connection scheduler checks against a synthetic SQLite file.

The knowledge base object is a minimal stand-in exposing only what the scheduler
uses (`conn` and `approved_source`), so no runtime database or network is touched.
"""
import sqlite3
import threading

import pytest

from public_kb import schedule

SOURCES = """
CREATE TABLE sources (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 automated_access INTEGER NOT NULL DEFAULT 1, retention INTEGER NOT NULL DEFAULT 1,
 inference_processing INTEGER NOT NULL DEFAULT 1, investor_reuse INTEGER NOT NULL DEFAULT 1
);
"""
CADENCE = schedule.CADENCE["directory"]


class SyntheticKB:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), timeout=10)

    def approved_source(self, source_id):
        row = self.conn.execute("""SELECT enabled,automated_access,retention,
            inference_processing,investor_reuse FROM sources WHERE id=?""",
            (source_id,)).fetchone()
        if not row or not all(row):
            raise PermissionError("Source is not approved")


@pytest.fixture
def workers(tmp_path):
    path = tmp_path / "schedule.sqlite"
    first = SyntheticKB(path)
    first.conn.executescript(SOURCES)
    with first.conn:
        first.conn.execute("INSERT INTO sources(id,url) VALUES (?,?)",
                           ("src-a", "https://example.invalid/directory"))
    schedule.set_policy(first, "src-a", "directory")
    second = SyntheticKB(path)
    yield first, second, path
    first.conn.close()
    second.conn.close()


def _policy(kb):
    return kb.conn.execute("""SELECT next_due,last_success,last_error
        FROM refresh_policy WHERE source_id='src-a'""").fetchone()


def _jobs(kb):
    return kb.conn.execute("""SELECT id,state,attempts,owner,lease_until,retry_at
        FROM refresh_job ORDER BY created_at""").fetchall()


def test_due_job_is_claimed_by_only_one_connection(workers):
    first, second, _ = workers
    claim = schedule.claim_due(first, now=1000)
    assert claim and claim[1] == "src-a"
    assert schedule.claim_due(second, now=1000) is None
    assert schedule.claim_due(second, now=1119) is None
    assert schedule.claim_due(first, now=1119) is None
    jobs = _jobs(second)
    assert len(jobs) == 1
    assert jobs[0][:4] == (claim[0], "running", 1, claim[2])
    started = second.conn.execute("""SELECT COUNT(*) FROM collection_event
        WHERE phase='fetch' AND outcome='started'""").fetchone()[0]
    assert started == 1


def test_simultaneous_claims_yield_one_lease(workers):
    _, _, path = workers
    barrier = threading.Barrier(2)
    claims, errors = [], []

    def worker():
        kb = SyntheticKB(path)
        try:
            barrier.wait(timeout=10)
            claims.append(schedule.claim_due(kb, now=1000))
        except Exception as exc:  # surfaced below; a thread must not fail silently
            errors.append(exc)
        finally:
            kb.conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors
    assert len(claims) == 2
    assert len([claim for claim in claims if claim]) == 1


def test_two_due_sources_go_to_different_connections(workers):
    first, second, _ = workers
    with first.conn:
        first.conn.execute("INSERT INTO sources(id,url) VALUES (?,?)",
                           ("src-b", "https://example.com/announcements"))
    schedule.set_policy(first, "src-b", "announcement")
    one = schedule.claim_due(first, now=1000)
    two = schedule.claim_due(second, now=1000)
    assert {one[1], two[1]} == {"src-a", "src-b"}
    assert one[0] != two[0] and one[2] != two[2]
    assert schedule.claim_due(first, now=1000) is None
    assert schedule.claim_due(second, now=1000) is None


def test_expired_lease_resumes_on_other_connection(workers):
    first, second, _ = workers
    abandoned = schedule.claim_due(first, now=1000)
    assert schedule.claim_due(second, now=1119) is None
    resumed = schedule.claim_due(second, now=1120)
    assert resumed[:2] == abandoned[:2]
    assert resumed[2] != abandoned[2]
    job = _jobs(first)
    assert len(job) == 1
    assert job[0][1:5] == ("running", 2, resumed[2], 1240)
    assert _policy(first)[0] == 0

    with pytest.raises(ValueError):
        schedule.finish(first, abandoned[0], abandoned[2], digest="a" * 64, now=1130)
    assert _policy(second) == (0, None, None)
    assert _jobs(second)[0][1] == "running"
    # The losing connection must not be left inside a write transaction.
    assert not first.conn.in_transaction

    schedule.finish(second, resumed[0], resumed[2], digest="b" * 64, now=1140)
    assert _policy(first) == (1140 + CADENCE, 1140, None)
    assert _jobs(first)[0][1] == "done"
    assert schedule.claim_due(first, now=1141) is None
    assert len(_jobs(first)) == 1


def test_failed_index_refresh_keeps_next_due(workers):
    first, second, _ = workers
    claim = schedule.claim_due(first, now=1000)
    schedule.finish(first, claim[0], claim[2], error="index refresh failed", now=1010)
    assert _policy(second) == (0, None, "index refresh failed")
    job = _jobs(second)
    assert len(job) == 1
    assert job[0][1:] == ("failed", 1, None, None, 1070)
    assert [row for row in schedule.status(second, now=1010)
            if row["source_id"] == "src-a"][0]["overdue"] is True

    # Still due, but neither connection may duplicate or retry it before retry_at.
    assert schedule.claim_due(second, now=1069) is None
    assert schedule.claim_due(first, now=1069) is None
    assert len(_jobs(first)) == 1

    retry = schedule.claim_due(second, now=1070)
    assert retry[:2] == claim[:2]
    assert schedule.claim_due(first, now=1070) is None
    schedule.finish(second, retry[0], retry[2], error="index refresh failed", now=1080)
    assert _policy(first)[0] == 0
    assert _jobs(first)[0][1:3] == ("failed", 2)
    assert _jobs(first)[0][5] == 1080 + 120

    final = schedule.claim_due(first, now=1200)
    schedule.finish(first, final[0], final[2], digest="c" * 64, now=1210)
    assert _policy(second) == (1210 + CADENCE, 1210, None)
    assert schedule.claim_due(second, now=1211) is None
    assert len(_jobs(second)) == 1


def test_unfinished_refresh_never_advances_next_due(workers):
    first, second, _ = workers
    schedule.claim_due(first, now=1000)
    for now in (1120, 1240, 1360):
        assert schedule.claim_due(second, now=now) is not None
        assert _policy(second) == (0, None, None)
    assert len(_jobs(first)) == 1
    assert _jobs(first)[0][2] == 4
