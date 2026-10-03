import json
from urllib.parse import urlsplit

import pytest

from public_kb.ingestion import PublicIngestion
from public_kb.startupdb_tool import StartupDBTool


class Fetcher:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def _allowed(self, url, deadline):
        assert url.startswith("https://startupdb.com/api/v1/startups")

    def _request(self, url, deadline, request_headers=None):
        self.urls.append(url)
        return self.responses[urlsplit(url).path]


def response(data, *, license="CC BY 4.0"):
    return 200, {"Content-Type": "application/json"}, json.dumps({
        "license": license,
        "attribution": "StartupDB (https://startupdb.com)",
        "data": data,
    }).encode()


def kb_at(tmp_path):
    return PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")


def test_search_is_bounded_ephemeral_and_excludes_third_party_text(tmp_path):
    kb = kb_at(tmp_path)
    fetcher = Fetcher({"/api/v1/startups": response([
        {"slug": "example-one", "name": "Example One", "description": "DO NOT RETAIN",
         "logoUrl": "https://elsewhere.test/logo.png"},
        {"slug": "../../other", "name": "Bad"},
    ])})
    try:
        result = StartupDBTool(kb, fetcher=fetcher).search_startups("Indian fintech", limit=2)
        assert result["matches"] == [{"slug": "example-one", "name": "Example One"}]
        assert "DO NOT RETAIN" not in json.dumps(result)
        assert not kb.conn.execute("SELECT 1 FROM versions").fetchone()
        assert len(fetcher.urls) == 1
    finally:
        kb.close()


def test_detail_retains_only_rights_scoped_projection_with_version(tmp_path):
    kb = kb_at(tmp_path)
    detail = {"slug": "example-one", "name": "Example One", "description": "DO NOT RETAIN",
              "websiteUrl": "https://127.0.0.1/private",
              "logoUrl": "https://elsewhere.test/logo.png", "fundingHistory": [{
                  "eventId": "round-1", "roundLabel": "Seed", "eventDate": "2026-01-01",
                  "sourceUrls": ["https://investor.test/announcement", "https://127.0.0.1/private"],
                  "summary": "DO NOT RETAIN",
              }]}
    fetcher = Fetcher({"/api/v1/startups/example-one": response(detail)})
    try:
        tool = StartupDBTool(kb, fetcher=fetcher)
        result = tool.get_startup("example-one")
        assert result["source_url"] == "https://startupdb.com/api/v1/startups/example-one"
        assert result["source_version_id"].startswith("startupdb_example_one:")
        assert result["record"]["funding_history"][0]["source_urls"] == [
            "https://investor.test/announcement"]
        assert result["record"]["company"]["website_url"] == ""
        retained = next((tmp_path / "archive" / "startupdb_example_one").iterdir()).read_bytes()
        assert b"DO NOT RETAIN" not in retained and b"logo" not in retained
        assert tool.get_startup("example-one")["source_version_id"] == result["source_version_id"]
        assert kb.conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 1
    finally:
        kb.close()


def test_changed_rights_or_disabled_registration_blocks_retention(tmp_path):
    kb = kb_at(tmp_path)
    fetcher = Fetcher({"/api/v1/startups/example-one": response(
        {"slug": "example-one", "name": "Example"}, license="All rights reserved")})
    try:
        with pytest.raises(ValueError, match="rights"):
            StartupDBTool(kb, fetcher=fetcher).get_startup("example-one")
        assert not kb.conn.execute("SELECT 1 FROM sources").fetchone()

        kb.register_source(source_id="startupdb_example_one",
                           url="https://startupdb.com/api/v1/startups/example-one",
                           terms_url="https://startupdb.com/legal", reviewed_at="2026-10-01")
        fetcher.responses["/api/v1/startups/example-one"] = response(
            {"slug": "example-one", "name": "Example"})
        with pytest.raises(PermissionError):
            StartupDBTool(kb, fetcher=fetcher).get_startup("example-one")
        assert not kb.conn.execute("SELECT 1 FROM versions").fetchone()
    finally:
        kb.close()


@pytest.mark.parametrize("query", ["private diligence", "name@example.org", "https://site.test",
                                     "1234567890", "x" * 81])
def test_private_or_unbounded_search_input_rejected_before_network(tmp_path, query):
    kb = kb_at(tmp_path)
    fetcher = Fetcher({})
    try:
        with pytest.raises(ValueError):
            StartupDBTool(kb, fetcher=fetcher).search_startups(query)
        assert fetcher.urls == []
    finally:
        kb.close()


def test_call_budget_and_slug_validation(tmp_path):
    kb = kb_at(tmp_path)
    fetcher = Fetcher({"/api/v1/startups": response([])})
    try:
        tool = StartupDBTool(kb, fetcher=fetcher, max_calls=1)
        tool.search_startups("fintech")
        with pytest.raises(Exception, match="budget"):
            tool.search_startups("healthtech")
        with pytest.raises(ValueError, match="slug"):
            tool.get_startup("../private")
        assert len(fetcher.urls) == 1
    finally:
        kb.close()


def test_expired_rights_review_blocks_network(tmp_path):
    kb = kb_at(tmp_path)
    fetcher = Fetcher({})
    try:
        with pytest.raises(PermissionError, match="expired"):
            StartupDBTool(kb, fetcher=fetcher, reviewed_at="2020-01-01").search_startups("fintech")
        assert fetcher.urls == []
    finally:
        kb.close()
