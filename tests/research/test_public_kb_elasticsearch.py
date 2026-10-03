import pytest

from public_kb.elasticsearch import ElasticsearchPublicKB, VERSIONS, CURRENT
from public_kb.ingestion import PublicIngestion
from tests.research.test_public_kb_ingestion import source


class Response:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self.content = b"{}"
        self.data = data or {}

    def json(self):
        return self.data


class Session:
    def __init__(self):
        self.calls = []
        self.trust_env = True
        self.headers = {}
        self.fail_current = False
        self.results = []

    def request(self, method, url, json=None, **kwargs):
        self.calls.append((method, url, json))
        if self.fail_current and f"/{CURRENT}/_doc/" in url:
            return Response(503)
        if url.endswith("/_search"):
            return Response(data={"hits": {"hits": [{"_source": row} for row in self.results]}})
        return Response()


def test_sink_retry_retains_version_and_search_honors_rights(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.sqlite", tmp_path / "archive")
    source(kb)
    digest = kb.stage("approved-feed", b"A public company announcement")
    session = Session()
    es = ElasticsearchPublicKB(kb, url="http://127.0.0.1:9200", session=session)
    session.fail_current = True
    with pytest.raises(RuntimeError):
        kb.publish_pending(es.publish)
    assert kb.pending() == [("approved-feed", digest)]
    session.fail_current = False
    kb.publish_pending(es.publish)
    assert kb.pending() == []
    version_writes = [call for call in session.calls if f"/{VERSIONS}/_doc/" in call[1]]
    assert len(version_writes) == 2
    assert version_writes[0][2] == version_writes[1][2]
    session.results = [version_writes[0][2]]
    assert es.search("company") == session.results
    with kb.conn:
        kb.conn.execute("INSERT INTO fetch_state(source_id,last_sha256) VALUES (?,?)",
                        ("approved-feed", "newer-version-awaiting-index"))
    assert es.search("company") == []
    source(kb, enabled=False)
    assert es.search("company") == []
    kb.close()
