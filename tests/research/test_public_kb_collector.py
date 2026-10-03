import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from public_kb.collector import collect_source
from public_kb.ingestion import PublicIngestion
from tests.research.test_public_kb_ingestion import source


class FakeFetcher:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def _allowed(self, url, deadline):
        self.calls.append(("robots", url))

    def _request(self, url, deadline, request_headers=None):
        self.calls.append((url, request_headers))
        return next(self.responses)


def test_rights_conditional_noop_and_changed_version(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    fetcher = FakeFetcher([(200, {"Content-Type": "text/html", "ETag": '"a"'}, b"one"),
                           (304, {}, b""),
                           (200, {"Content-Type": "text/html", "ETag": '"b"'}, b"two")])
    with pytest.raises(PermissionError):
        collect_source(kb, "approved-feed", fetcher=fetcher)
    assert fetcher.calls == []
    source(kb)
    assert collect_source(kb, "approved-feed", fetcher=fetcher) == "staged"
    assert collect_source(kb, "approved-feed", fetcher=fetcher) == "unchanged"
    assert collect_source(kb, "approved-feed", fetcher=fetcher) == "staged"
    assert fetcher.calls[3][1] == {"If-None-Match": '"a"'}
    assert len(kb.pending()) == 2
    source(kb, enabled=False)
    with pytest.raises(PermissionError):
        collect_source(kb, "approved-feed", fetcher=fetcher)
    kb.close()


def test_bad_media_and_cross_host_redirect_do_not_archive(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    source(kb)
    for response in [(200, {"Content-Type": "application/octet-stream"}, b"secret"),
                     (302, {"Location": "https://other.example/file"}, b"")]:
        with pytest.raises(Exception):
            collect_source(kb, "approved-feed", fetcher=FakeFetcher([response]))
    assert kb.pending() == []
    kb.close()


def test_overlapping_collectors_use_one_source_lease(tmp_path):
    db, archive = tmp_path / "kb.sqlite", tmp_path / "archive"
    setup = PublicIngestion(db, archive)
    source(setup)
    setup.close()
    entered, release = Event(), Event()

    class Blocking(FakeFetcher):
        def _request(self, url, deadline, request_headers=None):
            entered.set()
            assert release.wait(5)
            return super()._request(url, deadline, request_headers)

    def first():
        kb = PublicIngestion(db, archive)
        try:
            return collect_source(kb, "approved-feed", fetcher=Blocking([(200, {"Content-Type": "text/plain"}, b"public")]))
        finally:
            kb.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(first)
        assert entered.wait(5)
        second = PublicIngestion(db, archive)
        try:
            assert collect_source(second, "approved-feed", fetcher=FakeFetcher([])) == "leased"
        finally:
            second.close()
        release.set()
        assert running.result(timeout=5) == "staged"
