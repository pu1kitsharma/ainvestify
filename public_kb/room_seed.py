"""Bind one indexed, rights-cleared StartupDB record to a private room lead."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from public_kb.ingestion import PublicIngestion
from schemas import CompanyEvidence, CompanyProfile, SourcedLead


def profile_from_indexed_source(kb: PublicIngestion, source_id: str, tenant_id: str):
    url = kb.approved_source(source_id)
    if urlsplit(url).hostname != "startupdb.com" or not urlsplit(url).path.startswith("/api/v1/startups/"):
        raise ValueError("A StartupDB company detail source is required")
    row = kb.conn.execute("""SELECT v.sha256 FROM versions v JOIN fetch_state f
        ON f.source_id=v.source_id AND f.last_sha256=v.sha256
        WHERE v.source_id=? AND v.state='indexed' ORDER BY v.fetched_at DESC LIMIT 1""",
        (source_id,)).fetchone()
    if row is None:
        raise ValueError("No current indexed public source version")
    digest = row[0]
    content = (kb.archive_root / source_id / digest).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Public source archive hash mismatch")
    record = json.loads(content)
    if record.get("source_format") != "startupdb_company_v1" or record.get("license") != "CC BY 4.0":
        raise ValueError("Unsupported public company record")
    company = record["company"]
    if company["slug"] != urlsplit(url).path.rsplit("/", 1)[-1]:
        raise ValueError("Public source identity mismatch")
    website = company.get("website_url") or ""
    parsed = urlsplit(website)
    if parsed.scheme != "https" or parsed.hostname != company.get("domain") or parsed.username or parsed.password:
        raise ValueError("Public company website is unresolved")
    evidence = []
    for field in ("headquarters_location", "founded_year", "operating_status"):
        if company.get(field):
            evidence.append(CompanyEvidence(field=field, value=company[field],
                quote=json.dumps({field: company[field], "name": company["name"]},
                                 sort_keys=True, ensure_ascii=False), source_url=url,
                origin="public_page_claim", dataset_id=source_id,
                row_key=f"{digest}:company.{field}"))
    for index, round_ in enumerate(record.get("funding_history", [])):
        if not round_.get("source_urls") or not round_.get("label") or not round_.get("date"):
            continue
        # Preserve source-native facts, rather than writing an analyst conclusion.
        fact = {key: round_.get(key) for key in ("label", "date", "date_precision", "status", "amount", "participants")}
        evidence.append(CompanyEvidence(field="funding_round", value=round_["label"],
            quote=json.dumps(fact, sort_keys=True, ensure_ascii=False), source_url=url,
            origin="public_page_claim", dataset_id=source_id,
            row_key=f"{digest}:funding_history[{index}]", observed_at=round_["date"]))
    profile = CompanyProfile(tenant_id=tenant_id, name=company["name"], website=website,
        discovery_source_url=url, evidence=evidence, identity_status="source_supported_unverified",
        provenance={"origin": "public_kb", "source_id": source_id, "source_version": digest,
                    "license": record["license"], "attribution": record["attribution"]})
    return profile


def lead_from_indexed_source(store, kb: PublicIngestion, source_id: str, tenant_id: str):
    incoming = profile_from_indexed_source(kb, source_id, tenant_id)
    existing = store.get_company_by_website(tenant_id, incoming.website)
    if existing:
        if existing.provenance.get("origin") != "public_kb" or existing.provenance.get("source_id") != source_id:
            raise ValueError("Company identity needs reconciliation before KB import")
        incoming.id = existing.id
    leads = [lead for lead in store.list_leads(tenant_id) if lead.company_id == incoming.id]
    if len(leads) > 1:
        raise ValueError("Multiple leads need reconciliation")
    if existing and existing.provenance.get("source_version") == incoming.provenance["source_version"]:
        if leads:
            return leads[0]
        incoming = existing
    elif existing and existing.assessment:
        incoming.provenance["prior_assessments"] = [
            *existing.provenance.get("prior_assessments", []), existing.assessment.model_dump()]
    lead = leads[0] if leads else SourcedLead(tenant_id=tenant_id, company_name=incoming.name,
                                              company_id=incoming.id)
    lead.company_profile = incoming
    store.save_company(incoming)
    store.save_lead(lead)
    return lead
