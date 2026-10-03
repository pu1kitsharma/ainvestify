import hashlib
import json
from datetime import date

import pytest

from public_kb.ingestion import PublicIngestion
from public_kb.room_seed import profile_from_indexed_source, lead_from_indexed_source
from schemas import SelectionAssessment
from store import Store


def test_indexed_source_projects_only_public_funding_facts(tmp_path):
    kb = PublicIngestion(tmp_path / "kb.db", tmp_path / "archive")
    try:
        kb.register_source(source_id="startupdb-example", url="https://startupdb.com/api/v1/startups/example",
            terms_url="https://startupdb.com/legal", reviewed_at=date.today().isoformat(),
            automated_access=True, retention=True, inference_processing=True,
            investor_reuse=True, enabled=True)
        record = {"source_format": "startupdb_company_v1", "license": "CC BY 4.0",
            "attribution": "StartupDB (https://startupdb.com)",
            "company": {"slug": "example", "name": "Example Company", "domain": "example.com",
                        "website_url": "https://example.com"},
            "funding_history": [{"label": "Seed", "date": "2026-06", "date_precision": "month",
                "status": "reported", "amount": {"original": "100000", "currency": "USD"},
                "participants": [{"name": "Example Investor", "role": "lead"}],
                "source_urls": ["https://example.org/announcement"]}]}
        content = json.dumps(record).encode()
        digest = kb.stage("startupdb-example", content, content_type="application/json")
        with kb.conn:
            kb.conn.execute("UPDATE versions SET state='indexed' WHERE source_id='startupdb-example'")
            kb.conn.execute("INSERT INTO fetch_state(source_id,last_sha256) VALUES (?,?)", ("startupdb-example", digest))
        profile = profile_from_indexed_source(kb, "startupdb-example", "private-tenant")
        assert profile.website == "https://example.com"
        assert profile.identity_status == "source_supported_unverified"
        assert profile.evidence[0].value == "Seed"
        assert profile.evidence[0].row_key.startswith(digest)
        assert "private-tenant" not in profile.evidence[0].quote
        with Store(tmp_path / "room.db") as store:
            first = lead_from_indexed_source(store, kb, "startupdb-example", "private-tenant")
            first.company_profile.assessment = SelectionAssessment(model="local-test", rationale="Review pending")
            store.save_company(first.company_profile)
            store.save_lead(first)
            repeated = lead_from_indexed_source(store, kb, "startupdb-example", "private-tenant")
            assert repeated.id == first.id
            assert repeated.company_profile.evidence[0].id == first.company_profile.evidence[0].id
            assert repeated.company_profile.assessment.model == "local-test"
        with kb.conn:
            kb.conn.execute("UPDATE sources SET enabled=0 WHERE id='startupdb-example'")
        with pytest.raises(PermissionError):
            profile_from_indexed_source(kb, "startupdb-example", "private-tenant")
    finally:
        kb.close()
