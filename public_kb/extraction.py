"""Deterministic extraction of permitted public source observations.

The output records source passages and source-native statement IDs. It never
promotes a publisher statement to a verified company fact or funding stage.
"""
from __future__ import annotations

import json
import re

from agents.discovery.web_sources import parse_page

ENTITY_ID = re.compile(r"^Q[1-9][0-9]*$")


def extract(content: bytes, content_type: str, url: str):
    decoded = content.decode("utf-8", errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"}:
        page = parse_page(url, decoded)
        return {"title": page.title[:200], "passages": [p[:2000] for p in page.content_blocks if p.strip()][:100],
                "entity_id": None, "statements": []}
    if content_type == "text/plain":
        return {"title": url, "passages": [" ".join(decoded.split())[:2000]],
                "entity_id": None, "statements": []}
    if content_type != "application/json":
        raise ValueError("Unsupported public extraction format")
    payload = json.loads(decoded)
    if isinstance(payload, dict) and payload.get("source_format") == "startupdb_company_v1":
        company = payload["company"]
        passages = [company["name"], "Source credit: StartupDB (https://startupdb.com), CC BY 4.0."]
        statements = []
        for field in ("headquarters_location", "founded_year", "operating_status"):
            if company.get(field):
                passages.append(f"{company['name']}: {field.replace('_', ' ')} {company[field]} (StartupDB source-reported)")
                statements.append({"property_id": field, "value": company[field],
                    "source_path": f"company.{field}", "rank": "reported", "reference_count": 1})
        for index, row in enumerate(payload.get("funding_history", [])):
            label, when = row.get("label", ""), row.get("date", "")
            if not label or not when or not row.get("source_urls"):
                continue
            fields = {"company": company["name"], "label": label, "date": when,
                      "date_precision": row.get("date_precision", ""),
                      "status": row.get("status", ""),
                      "amount": row.get("amount") or {},
                      "evidence_status": "StartupDB source-reported"}
            passages.append(json.dumps(fields, sort_keys=True, ensure_ascii=False)[:2000])
            for property_id, value, path in (
                ("funding_round", label, "label"),
                ("funding_date", when, "date"),
                ("funding_status", row.get("status", ""), "status"),
                ("funding_amount_original", (row.get("amount") or {}).get("original", ""), "amount.original"),
                ("funding_currency", (row.get("amount") or {}).get("currency", ""), "amount.currency")):
                if value:
                    statements.append({"property_id": property_id, "value": str(value),
                        "source_path": f"funding_history[{index}].{path}", "rank": "reported",
                        "reference_count": len(row["source_urls"])})
        return {"title": company["name"], "passages": passages[:100],
                "entity_id": company["slug"], "statements": statements[:500]}
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, dict) or len(entities) != 1:
        raise ValueError("JSON source is not one structured entity")
    entity_id, entity = next(iter(entities.items()))
    if not ENTITY_ID.fullmatch(entity_id) or not isinstance(entity, dict) or entity.get("id") != entity_id:
        raise ValueError("Structured entity ID is invalid")
    label = (entity.get("labels", {}).get("en") or {}).get("value", "")
    description = (entity.get("descriptions", {}).get("en") or {}).get("value", "")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("Structured entity has no English label")
    if not isinstance(description, str):
        description = ""
    passages = [label.strip() + (": " + description.strip() if description.strip() else "")]
    statements = []
    for property_id, rows in sorted(entity.get("claims", {}).items()):
        if not re.fullmatch(r"P[1-9][0-9]*", property_id) or not isinstance(rows, list):
            continue
        for index, row in enumerate(rows[:30]):
            if not isinstance(row, dict):
                continue
            snak = row.get("mainsnak", {})
            if snak.get("snaktype") != "value":
                continue
            value = snak.get("datavalue", {}).get("value")
            if isinstance(value, dict):
                value = value.get("id") or value.get("text") or value.get("time") or value.get("amount")
            if not isinstance(value, (str, int, float)):
                continue
            path = f"entities.{entity_id}.claims.{property_id}[{index}].mainsnak.datavalue.value"
            statements.append({"property_id": property_id, "value": str(value)[:500],
                               "source_path": path, "rank": str(row.get("rank", "normal")),
                               "reference_count": len(row.get("references") or [])})
    return {"title": label[:200], "passages": passages, "entity_id": entity_id,
            "statements": statements[:500]}
