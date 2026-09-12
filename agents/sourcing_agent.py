"""
Deal Sourcing Agent — architecture doc §5.8.

Distinct from the Market Research Agent (agents/research_agent.py, §5.4):
that agent corroborates a deal already in the pipeline; this one surfaces
*candidate* companies nobody has submitted yet. Output is a SourcedLead,
not a Deal -- a lead never touches ExtractionResult until a human analyst
deliberately promotes it (see agents/planner_agent.py's promote_lead_to_deal),
at which point real documents exist for it and it goes through Ingestion ->
Extraction like any other deal (§5.2/§5.3).

Dynamic by design: no hardcoded sector keyword and no hardcoded geography.
Every call takes the theme as a parameter (extracted from the user's own
free-text request by main.py's router) and searches for genuinely NEW
activity -- GitHub repos *created* recently, HN "Show HN" launches -- which
is a much better proxy for "what's happening in this space right now" than
matching on last-updated timestamps or an all-time, unbounded search.

Phase 0's legitimate source coverage (§10.6) is still intentionally thin:
most of the obvious broader sourcing ideas (YC's undocumented directory
endpoint, Product Hunt, DuckDuckGo scraping, MCA/registrar scraping,
UpForge, campus incubator portals) either fail the same ToS-legitimacy bar
that already excluded Apollo/pytrends/Crunchbase, or need an actual
licensing conversation this codebase can't complete on its own. Read §10.6
before adding a new source here -- "it's free" is necessary, not sufficient.
"the caller wants broader coverage" doesn't change what a source's own ToS
allows.

The DPIIT aggregate dataset on data.gov.in (§10.1) is a real, legitimate
source but is NOT implemented here yet: api.data.gov.in requires a free
API key tied to a personal account, which isn't this codebase's to create
on a user's behalf. Register one at data.gov.in and wire it in as
DATA_GOV_IN_API_KEY when ready -- and note it's aggregate sector/state
statistics (§10.1's caveat), not individual company leads, so it belongs
in sourcing context/market-sizing, not in discover_github_leads()'s role.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import requests

from agents.research_agent import RESEARCH_AGENT_CONTACT
from schemas import DiscoverySignal, SourcedLead

# IB-style sourcing (§2/§5.1's Origination stage) is a genuinely different
# job from discover_leads() above: mature, typically public companies
# signaling an approaching transaction window (M&A, restructuring), not
# early-stage incubation candidates. Kept as a separate function rather
# than blended into discover_leads() -- conflating the two would misrepresent
# what a hit here actually means (§10.5's "don't blend confidence tiers"
# principle, applied to company *type* instead of data type).
#
# These are standard M&A-process phrases analysts already search SEC
# filings for by hand -- this is real practice on an already-legitimate
# source (§10.1's EDGAR entry), not a novel scraping technique.
IB_SIGNAL_PHRASES = [
    "exploring strategic alternatives",
    "review of strategic alternatives",
    "engaged a financial advisor",
]

HTTP_TIMEOUT = 8
DEFAULT_LOOKBACK_DAYS = 30


def _owner_location(username: str) -> str:
    """GitHub's repository-search endpoint has no `location:` qualifier --
    that only exists on user/org search (confirmed live: adding it to a
    repo-search query silently zeroes every result rather than erroring).
    Filtering by owner location for repo results means a second lookup per
    candidate against /users/{username}. Only called when a caller actually
    asks for a location filter -- Phase 0 initially hardcoded this check to
    "india" unconditionally, which was wrong for a general request; it's
    now opt-in per call."""
    try:
        resp = requests.get(
            f"https://api.github.com/users/{username}",
            headers={"Accept": "application/vnd.github+json"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("location") or ""
    except requests.RequestException:
        return ""


def discover_github_leads(
    tenant_id: str,
    sector_keyword: str,
    location_filter: Optional[str] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    candidate_pool: int = 15,
) -> list[SourcedLead]:
    """Repos *created* within the last `lookback_days` matching
    sector_keyword (§10.6) -- filtering on creation date rather than
    last-updated is what makes this a "what's new right now" signal instead
    of "what's still being maintained" (an old repo that got a commit
    yesterday isn't a new company). `location_filter` is optional and unset
    by default -- pass a substring (e.g. "india") only when the request
    actually named a geography; otherwise this searches globally. A real
    but narrow signal either way: one GitHub account can plausibly
    represent one company, and a company with no public repo, an org with
    no bio/location set, or a repo under a contributor's personal account
    won't surface here -- worth surfacing to the analyst reviewing leads,
    not hidden by the code."""
    since = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={
                "q": f"{sector_keyword} created:>{since}",
                "sort": "stars", "order": "desc", "per_page": candidate_pool,
            },
            headers={"Accept": "application/vnd.github+json"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except requests.RequestException:
        return []

    leads = []
    seen_repo_names: set[str] = set()
    for repo in items:
        # The same repo *name* recurring under many different owners in one
        # result set is the signature of a clone/star-farming spam network,
        # not several distinct new companies (confirmed live: a "fintech"
        # search returned the identical "Ghostfolio-Open-Source-Wealth-..."
        # repo name under 9 different throwaway-looking accounts). Sorted
        # by stars descending, keep only the first (highest-starred, most
        # likely genuine) occurrence of a given name.
        repo_name = repo.get("name", "").lower()
        if repo_name in seen_repo_names:
            continue
        seen_repo_names.add(repo_name)

        owner = repo.get("owner", {}).get("login") or "unknown"
        location = ""
        if location_filter:
            location = _owner_location(owner)
            if location_filter.lower() not in location.lower():
                continue

        location_note = f" Owner profile location: '{location}'." if location_filter else ""
        leads.append(SourcedLead(
            tenant_id=tenant_id,
            company_name=owner,
            sector_tag=sector_keyword,
            discovery_signals=[DiscoverySignal(
                content=(
                    f"GitHub repo {repo['full_name']} ({repo.get('stargazers_count', 0)} stars), "
                    f"created {repo.get('created_at', 'unknown')}, matching '{sector_keyword}'."
                    f"{location_note} {repo.get('description') or ''}".strip()
                ),
                source_url=repo.get("html_url"),
                source_type="github",
            )],
        ))
    return leads


def discover_hn_launches(
    tenant_id: str,
    sector_keyword: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    per_page: int = 10,
) -> list[SourcedLead]:
    """Recent "Show HN" launches matching sector_keyword -- a second,
    independent "what's new right now" signal from an already-legitimate
    source (§10.1, same Algolia API research_agent.py already uses), so a
    company with no public repo (e.g. a closed-source SaaS launch) can
    still surface here."""
    since_ts = int((datetime.utcnow() - timedelta(days=lookback_days)).timestamp())
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "tags": "show_hn",
                "query": sector_keyword,
                "hitsPerPage": per_page,
                "numericFilters": f"created_at_i>{since_ts}",
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except requests.RequestException:
        return []

    leads = []
    for hit in hits:
        title = hit.get("title") or ""
        # "Show HN: <name> -- <pitch>" -> take what follows "Show HN:" as
        # the project/company name; fall back to the raw title otherwise.
        name = title.split("Show HN:", 1)[-1].strip() or title
        leads.append(SourcedLead(
            tenant_id=tenant_id,
            company_name=name[:80],
            sector_tag=sector_keyword,
            discovery_signals=[DiscoverySignal(
                content=(
                    f'HN launch: "{title}" ({hit.get("points", 0)} points, '
                    f'{hit.get("num_comments", 0)} comments)'
                ),
                source_url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                source_type="hackernews",
            )],
        ))
    return leads


def discover_leads(
    tenant_id: str,
    sector_keyword: str,
    location_filter: Optional[str] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[SourcedLead]:
    """Run every discovery connector for one theme. No hardcoded keyword or
    geography -- both are parameters, resolved by whatever called this
    (main.py's router, or the Planner) from the actual request text."""
    leads: list[SourcedLead] = []
    leads += discover_github_leads(
        tenant_id, sector_keyword, location_filter=location_filter, lookback_days=lookback_days,
    )
    leads += discover_hn_launches(tenant_id, sector_keyword, lookback_days=lookback_days)
    return leads


def discover_ib_targets(
    tenant_id: str,
    sector_keyword: str,
    forms: str = "8-K,10-K",
    max_per_phrase: int = 5,
) -> list[SourcedLead]:
    """IB-style sourcing: mature/public companies whose own SEC filings
    contain standard M&A-process language, combined with a sector keyword.
    A hit here means "this company disclosed it's exploring a transaction"
    -- direct, first-party signal, not an inference from GitHub activity."""
    leads: list[SourcedLead] = []
    seen_names: set[str] = set()

    for phrase in IB_SIGNAL_PHRASES:
        try:
            resp = requests.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": f'"{phrase}" "{sector_keyword}"', "forms": forms},
                headers={"User-Agent": RESEARCH_AGENT_CONTACT},
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
        except (requests.RequestException, ValueError):
            continue

        for hit in hits[:max_per_phrase]:
            source = hit.get("_source", {})
            names = source.get("display_names", [])
            if not names:
                continue
            company_name = names[0]
            if company_name in seen_names:
                continue
            seen_names.add(company_name)

            leads.append(SourcedLead(
                tenant_id=tenant_id,
                company_name=company_name,
                sector_tag=sector_keyword,
                discovery_signals=[DiscoverySignal(
                    content=(
                        f'SEC filing ({", ".join(source.get("root_forms", []))}, filed '
                        f'{source.get("file_date")}) contains the phrase "{phrase}" -- a standard '
                        f"M&A-process disclosure -- alongside sector keyword '{sector_keyword}'."
                    ),
                    source_url=(
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{hit.get('_id', '').split(':')[0].lstrip('0') or '0'}"
                    ),
                    source_type="sec_edgar",
                )],
            ))

    return leads
