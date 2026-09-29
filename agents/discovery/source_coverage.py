"""Derive coverage from run snapshots and fetch outcomes, never log text counts."""
from urllib.parse import urlsplit

PUBLISHERS = {
    "antler.co": ("Antler", "Company directories"),
    "sosv.com": ("SOSV", "Company directories"),
    "seedcamp.com": ("Seedcamp", "Company directories"),
    "ycombinator.com": ("Y Combinator", "Company directories"),
    "blume.vc": ("Blume Ventures", "Company directories"),
    "villgro.org": ("Villgro", "Company directories"),
    "html.duckduckgo.com": ("DuckDuckGo", "Web search"),
    "api.mwmbl.org": ("Mwmbl", "Web search"),
    "query.wikidata.org": ("Wikidata", "Datasets"),
}


def summarize_coverage(run):
    rows = {}
    def row(url):
        host = (urlsplit(url).hostname or "unknown").removeprefix("www.")
        if host not in rows:
            name, category = PUBLISHERS.get(host, (host, "Research pages"))
            rows[host] = dict(host=host, name=name, category=category, url=url,
                outcomes=[], discovered=set(), supported=set(), claims=set(), records_read=0, matches=0)
        return rows[host]
    for outcome in run.sources:
        target = row(outcome.url)
        target["outcomes"].append(outcome.model_dump())
        target["records_read"] += outcome.records_read or 0
        target["matches"] += outcome.matches or 0
    for profile in run.company_profiles:
        discovery_url = profile.discovery_source_url or next((e.source_url for e in profile.evidence if e.field == "directory_profile"), None)
        if discovery_url:
            row(discovery_url)["discovered"].add(profile.id)
        for evidence in profile.evidence:
            target = row(evidence.source_url)
            target["claims"].add((profile.id, evidence.field, evidence.value, evidence.source_url))
            target["supported"].add(profile.id)
    result = []
    for target in rows.values():
        outcomes = target.pop("outcomes")
        failed = [o for o in outcomes if o["status"] in {"failed", "blocked", "rate_limited"}]
        discovered = len(target.pop("discovered"))
        supported = len(target.pop("supported"))
        claims = len(target.pop("claims"))
        status = "Contributed companies" if discovered else "Supporting evidence" if supported else "Search links only" if target["category"] == "Web search" and any(o["status"] == "ok" for o in outcomes) else "Unavailable" if failed else "No selected matches"
        result.append({**target, "discovered_companies": discovered, "supported_companies": supported,
            "cited_claims": claims, "status": status, "issues": len(failed), "outcomes": outcomes})
    return result
