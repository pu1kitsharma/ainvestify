import json

import pytest

from public_kb.startupdb import project_company
from public_kb.extraction import extract


def payload():
    return {
        "license": "CC BY 4.0",
        "attribution": "StartupDB (https://startupdb.com)",
        "data": {
            "id": "1", "slug": "example", "name": "Example",
            "description": "UNLICENSED THIRD PARTY DESCRIPTION",
            "logoUrl": "https://example.org/logo.png",
            "fundingHistory": [{
                "eventId": "r1", "roundLabel": "Seed", "eventDate": "2026-01-01",
                "datePrecision": "day", "eventStatus": "announced",
                "amount": {"original": "1000000", "currency": "INR"},
                "participants": [{"name": "Investor", "role": "lead",
                                  "bio": "UNLICENSED INVESTOR TEXT"}],
                "sourceUrls": ["https://example.org/report", "http://example.org/no"],
                "summary": "UNLICENSED ROUND TEXT",
            }],
        },
    }


def test_projection_retains_facts_and_drops_unlicensed_text():
    projected_bytes = project_company(json.dumps(payload()).encode())
    assert b"UNLICENSED" not in projected_bytes
    assert b"logo" not in projected_bytes
    projected = json.loads(projected_bytes)
    assert projected["funding_history"][0]["source_urls"] == ["https://example.org/report"]
    extracted = extract(projected_bytes, "application/json", "https://startupdb.com/api/v1/startups/example")
    assert extracted["entity_id"] == "example"
    assert extracted["statements"][0]["source_path"] == "funding_history[0].label"


def test_rights_notice_change_blocks_retention():
    item = payload()
    item["license"] = "All rights reserved"
    with pytest.raises(ValueError, match="rights"):
        project_company(json.dumps(item).encode())
