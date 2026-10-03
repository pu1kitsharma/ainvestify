import json

import pytest

from public_kb.extraction import extract


def test_structured_entity_keeps_exact_statement_paths_and_uncertainty():
    payload = {"entities": {"Q123": {"id": "Q123",
        "labels": {"en": {"value": "Synthetic India company"}},
        "descriptions": {"en": {"value": "Synthetic testing company"}},
        "claims": {"P17": [{"rank": "normal", "mainsnak": {"snaktype": "value",
            "datavalue": {"value": {"id": "Q668"}}}, "references": []}]}}}}
    result = extract(json.dumps(payload).encode(), "application/json", "https://www.wikidata.org/wiki/Special:EntityData/Q123.json")
    assert result["entity_id"] == "Q123"
    assert result["passages"] == ["Synthetic India company: Synthetic testing company"]
    assert result["statements"] == [{"property_id": "P17", "value": "Q668",
        "source_path": "entities.Q123.claims.P17[0].mainsnak.datavalue.value",
        "rank": "normal", "reference_count": 0}]


def test_json_requires_one_valid_entity():
    with pytest.raises(ValueError):
        extract(b'{"entities":{}}', "application/json", "https://www.wikidata.org/")


def test_startupdb_event_preserves_source_native_date_amount_and_status():
    payload = {"source_format": "startupdb_company_v1", "company": {"name": "Synthetic Labs", "slug": "synthetic-labs"},
        "funding_history": [{"label": "Seed", "date": "2026-04-01", "date_precision": "day",
            "status": "reported", "amount": {"original": "1000000", "currency": "USD"},
            "source_urls": ["https://publisher.example/event"]}]}
    result = extract(json.dumps(payload).encode(), "application/json", "https://startupdb.com/api/v1/startups/synthetic-labs")
    event = json.loads(result["passages"][-1])
    assert event["date"] == "2026-04-01"
    assert event["amount"] == {"original": "1000000", "currency": "USD"}
    assert event["status"] == "reported"
    assert {row["property_id"] for row in result["statements"]} == {
        "funding_round", "funding_date", "funding_status", "funding_amount_original", "funding_currency"}
