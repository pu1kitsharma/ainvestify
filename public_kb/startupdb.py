"""Rights-scoped projection of StartupDB's CC BY 4.0 API response.

Descriptions and other third-party text are deliberately discarded before
retention. The original response is never placed in the public archive.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit


def _fact(value, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("Unexpected StartupDB fact type; collection paused")
    return str(value)[:limit]


def project_company(content: bytes) -> bytes:
    payload = json.loads(content)
    if payload.get("license") != "CC BY 4.0" or payload.get("attribution") != "StartupDB (https://startupdb.com)":
        raise ValueError("StartupDB rights notice changed; collection paused")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("slug"), str) or not isinstance(data.get("name"), str):
        raise ValueError("Expected one StartupDB company record")
    rounds = []
    for item in (data.get("fundingHistory") or [])[:100]:
        if not isinstance(item, dict):
            continue
        sources = [url for url in item.get("sourceUrls", []) if isinstance(url, str)
                   and urlsplit(url).scheme == "https" and urlsplit(url).hostname][:20]
        participants = []
        for row in (item.get("participants") or [])[:30]:
            if isinstance(row, dict) and isinstance(row.get("name"), str):
                participants.append({"name": row["name"][:160],
                                     "role": _fact(row.get("role"), 50)})
        amount = item.get("amount")
        if not isinstance(amount, dict):
            amount = {}
        rounds.append({"event_id": _fact(item.get("eventId"), 100),
                       "label": _fact(item.get("roundLabel"), 100),
                       "date": _fact(item.get("eventDate"), 30),
                       "date_precision": _fact(item.get("datePrecision"), 40),
                       "status": _fact(item.get("eventStatus"), 60),
                       "amount": {"original": _fact(amount.get("original"), 80),
                                  "currency": _fact(amount.get("currency"), 10)},
                       "participants": participants, "source_urls": sources})
    projected = {"source_format": "startupdb_company_v1", "license": "CC BY 4.0",
                 "attribution": payload["attribution"],
                 "company": {"id": _fact(data.get("id"), 100),
                             "slug": data["slug"][:160], "name": data["name"][:160],
                             "domain": _fact(data.get("domain"), 160),
                             "website_url": _fact(data.get("websiteUrl"), 300),
                             "headquarters_location": _fact((data.get("profile") or {}).get("headquartersLocation"), 160),
                             "founded_year": _fact((data.get("profile") or {}).get("foundedYear"), 8),
                             "operating_status": _fact((data.get("profile") or {}).get("operatingStatus"), 60)},
                 "funding_history": rounds}
    return json.dumps(projected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
