"""Licensed dataset discovery; tabular rows never pass through LLM extraction."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from agents.web_sources import PublicWebFetcher, SourceError, normalize_url
from schemas import CompanyEvidence, CompanyProfile, WebSourceOutcome
from workflow_schemas import DatasetRecord, DatasetSnapshot, DatasetSource

CHECKED = "2026-09-13"
SOURCES = [
    DatasetSource(id="dataful_startups", name="DPIIT company register via Dataful", url="https://dataful.in/datasets/20873/",
        publisher="DPIIT / Dataful", granularity="company", geography="India", license_name="Dataful subscription terms",
        terms_url="https://dataful.in/terms-and-conditions/", access="metadata_only", checked_at=CHECKED,
        attribution="DPIIT Startup India, compiled by Dataful", limitation="Full download entitlement is not configured. Public preview is not the complete register; bulk ingestion is disabled. Company status is a reported startup stage, not MCA legal standing."),
    DatasetSource(id="dataful_counts", name="DPIIT startup counts by year, state and industry", url="https://dataful.in/datasets/15737/",
        publisher="DPIIT / Dataful", granularity="aggregate", geography="India", license_name="Dataful source-specific terms",
        terms_url="https://dataful.in/terms-and-conditions/", access="metadata_only", checked_at=CHECKED,
        attribution="DPIIT Startup India, compiled by Dataful", limitation="Listed as Free; download/access entitlement must be configured. Aggregate counts are market context only, never company traction or an investability signal."),
    DatasetSource(id="wikidata_companies", name="Wikidata company identities", url="https://query.wikidata.org/",
        publisher="Wikidata contributors", granularity="company", geography="Global", license_name="CC0",
        terms_url="https://www.wikidata.org/wiki/Wikidata:Licensing", access="open", checked_at=CHECKED,
        attribution="Wikidata contributors, CC0; entity URL and retrieval time retained", limitation="Community-maintained, incomplete and biased toward notable companies. Neither a startup census nor official legal-entity verification."),
]
SOURCE_BY_ID = {s.id: s for s in SOURCES}
COUNTRIES = {"india": "Q668", "united states": "Q30", "usa": "Q30", "united kingdom": "Q145", "uk": "Q145",
             "singapore": "Q334", "canada": "Q16", "australia": "Q408", "germany": "Q183", "france": "Q142"}
SECTOR_TERMS = {"hotel": ("hotel", "hospitality", "hotelier"), "agricultur": ("agri", "farm", "agricultur"),
                "energy": ("energy", "solar", "renewable"), "health": ("health", "medical", "biotech"),
                "food": ("food", "beverage"), "software": ("software", "saas"), "manufactur": ("manufactur", "industrial")}


def dataset_query(thesis, geography):
    country = COUNTRIES.get((geography or "").casefold().strip())
    if geography and not country and geography.casefold().strip() not in {"global", "any region", "worldwide"}:
        raise SourceError("partial", "Dataset connector does not yet resolve this geography; web discovery remains available.")
    terms = [key for key, aliases in SECTOR_TERMS.items() if any(re.search(r"\b" + re.escape(a), thesis.casefold()) for a in aliases)]
    if not terms:
        raise SourceError("partial", "No dataset industry mapping for this brief yet; web discovery remains available.")
    if terms == ["hotel"]:
        # Class IDs resolved from Wikidata labels on 2026-09-13: hotel chain / hotel group.
        # Indexed class lookup avoids a slow global description scan and excludes individual properties.
        location = f"?company wdt:P17 wd:{country}." if country else ""
        return f'''SELECT DISTINCT ?company ?companyLabel ?website ?description WHERE {{
          VALUES ?type {{ wd:Q1631129 wd:Q3117865 }} ?company wdt:P31 ?type; wdt:P856 ?website.
          {location} OPTIONAL {{ ?company schema:description ?description. FILTER(LANG(?description)="en") }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }} LIMIT 40'''
    condition = " || ".join(f'CONTAINS(LCASE(?description), {json.dumps(term)})' for term in terms[:3])
    location = f"?company wdt:P17 wd:{country}." if country else ""
    return f'''SELECT DISTINCT ?company ?companyLabel ?website ?description WHERE {{
      {location} ?company wdt:P856 ?website; schema:description ?description.
      FILTER(LANG(?description) = "en") FILTER({condition})
      FILTER NOT EXISTS {{ ?company wdt:P31 wd:Q5 }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 40'''


def fetch_wikidata(tenant_id, thesis, geography, fetcher=None):
    query = dataset_query(thesis, geography)
    url = "https://query.wikidata.org/sparql?" + urlencode({"query": query, "format": "json"})
    transport = fetcher or PublicWebFetcher()
    status, _, body = transport._request(url, time.monotonic() + 25)
    if status != 200:
        raise SourceError("rate_limited" if status == 429 else "failed", f"Wikidata query returned HTTP {status}.")
    try:
        bindings = json.loads(body)["results"]["bindings"]
        if not isinstance(bindings, list):
            raise ValueError("Bad result format")
        records = []
        for row in bindings[:40]:
            uri = row["company"]["value"]
            if not re.fullmatch(r"https?://www.wikidata.org/entity/Q\d+", uri):
                continue
            name = row["companyLabel"]["value"]
            if re.fullmatch(r"Q\d+", name):
                continue
            website = normalize_url(row["website"]["value"])
            # Ignore media/assets and platform profile URLs as official company websites.
            if urlsplit(website).hostname in {"www.facebook.com", "www.linkedin.com", "twitter.com"}:
                continue
            records.append(DatasetRecord(key=uri.rsplit('/', 1)[-1], source_url=uri.replace("/entity/", "/wiki/"),
                values={"company_name": name, "company_website": website,
                        "description": row.get("description", {}).get("value", ""),
                        "country": geography if COUNTRIES.get((geography or "").casefold().strip()) else "Not specified"}))
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError("failed", "Dataset response did not match the documented schema.") from exc
    return DatasetSnapshot(tenant_id=tenant_id, source_id="wikidata_companies", query=query, records=records,
                           content_hash=hashlib.sha256(body).hexdigest(), detail="Bounded CC0 query; no startup-stage or legal-standing verification.")


def snapshot_profiles(snapshot, source):
    if source.granularity != "company" or source.access != "open":
        return []
    profiles = []
    for row in snapshot.records:
        name = row.values.get("company_name", "").strip()
        if not name:
            continue
        website = row.values.get("company_website", "")
        if website:
            try: website = normalize_url(website)
            except SourceError: website = ""
        evidence = []
        for column, field in [("company_name", "name"), ("legal_name", "legal_name"), ("cin", "reported_registration_id"),
                              ("country", "location"), ("description", "offering"), ("focus_industry", "sector"),
                              ("services_provided", "business_model"), ("company_status", "reported_stage")]:
            value = row.values.get(column, "")
            if value and value != "Not specified":
                evidence.append(CompanyEvidence(field=field, value=value, quote=f"{column}: {value}",
                    source_url=row.source_url, origin="dataset_record", dataset_id=source.id, row_key=row.key,
                    observed_at=row.observed_at, retrieved_at=snapshot.retrieved_at))
        profiles.append(CompanyProfile(tenant_id=snapshot.tenant_id, name=name, website=website, evidence=evidence,
            identity_status="dataset_reported_unverified"))
    return profiles


def discover_dataset_companies(store, run, fetcher=None):
    """Dataset failures cannot disable the remaining discovery sources."""
    source = SOURCE_BY_ID["wikidata_companies"]
    try:
        query = dataset_query(run.thesis, run.geography)
        old = store.get_dataset_snapshot(run.tenant_id, source.id, query)
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(old.retrieved_at)).total_seconds() if old else float('inf')
        snapshot = old if old and 0 <= age < source.refresh_days * 86400 else fetch_wikidata(run.tenant_id, run.thesis, run.geography, fetcher)
        store.save_dataset_snapshot(snapshot)
        run.sources.append(WebSourceOutcome(url=source.url, status="ok" if snapshot.records else "no_results",
            detail=f"{len(snapshot.records)} dataset entities, CC0. Coverage: {snapshot.coverage}; official websites need corroboration."))
        return snapshot_profiles(snapshot, source)
    except Exception as exc:
        run.sources.append(WebSourceOutcome(url=source.url, status=exc.status if isinstance(exc, SourceError) else "failed",
            detail=str(exc) if isinstance(exc, SourceError) else "Dataset discovery unavailable; continuing web research."))
        return []


def parse_company_csv(text, source):
    """Adapter for later permitted open/licensed exports; no LLM field invention."""
    if source.access not in {"open", "authorized_import"}:
        raise ValueError("Dataset access is metadata-only. A permitted download entitlement is required.")
    if source.granularity != "company":
        raise ValueError("Aggregate data cannot be imported as company identities.")
    reader = csv.DictReader(io.StringIO(text))
    if not {"company_name", "company_website"}.issubset(reader.fieldnames or []):
        raise ValueError("Required company columns are missing.")
    records, seen = [], set()
    allowed = {"data_as_on", "state", "city", "company_name", "legal_name", "cin", "company_website",
               "company_status", "focus_industry", "focus_sector", "services_provided"}
    for index, row in enumerate(reader, 1):
        if index > 5000: raise ValueError("Import exceeds the pilot 5000-row limit.")
        values = {k: str(v or '').strip()[:2000] for k, v in row.items() if k in allowed}
        if not values.get("company_name"): continue
        cin = values.get("cin", "")
        # Some exports label non-CIN identifiers as CIN; preserve, never certify.
        identity = cin if re.fullmatch(r"[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}", cin) else values['company_name'].casefold()
        if identity in seen: raise ValueError("Duplicate identity in dataset; reconcile before import.")
        seen.add(identity)
        records.append(DatasetRecord(key=str(index), values=values, source_url=source.url,
                                     observed_at=values.get("data_as_on") or None))
    return records
