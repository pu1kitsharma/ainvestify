"""Query-driven discovery using public search; no keys or paid services.

Search results supply destinations only, never verified company evidence. The
HTML search surface is best-effort: challenges and rate limits stop search,
without proxies, CAPTCHA solving, or retrying around access controls.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol
from urllib.parse import parse_qs, urlencode, urlsplit

from pydantic import BaseModel, Field

from agents.local_models import StructuredModel, generate_task
from agents.web_sources import PublicWebFetcher, SourceError, normalize_url
from agents.public_directories import industry_terms, startup_directory_urls
from schemas import WebSourceOutcome, WebSourcingRun
from agents.geography import matches_location, WORLD, aliases


class SearchPlan(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)


@dataclass
class SearchHit:
    url: str
    title: str


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 6) -> list[SearchHit]: ...


def clean_destination(url: str) -> Optional[str]:
    try:
        p = urlsplit(url)
        if p.hostname and (p.hostname == "duckduckgo.com" or p.hostname.endswith(".duckduckgo.com")):
            url = parse_qs(p.query).get("uddg", [""])[0]
        url = normalize_url(url)
        host = urlsplit(url).hostname or ""
        if (host == "duckduckgo.com" or host.endswith(".duckduckgo.com")
                or host in {"localhost", "127.0.0.1", "::1"}):
            return None
        if re.search(r"\.(zip|png|jpg|jpeg|mp4)(?:\?|$)", url, re.I):
            return None
        return url
    except SourceError:
        return None


class DuckDuckGoSearch:
    name = "duckduckgo_html"

    def query_url(self, query: str) -> str:
        return "https://html.duckduckgo.com/html/?" + urlencode({"q": query})

    def __init__(self, fetcher=None):
        self.fetcher = fetcher or PublicWebFetcher()

    def search(self, query: str, limit: int = 6) -> list[SearchHit]:
        url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
        page = self.fetcher.fetch(url)
        if any(phrase in page.text.casefold() for phrase in (
            "unfortunately, bots", "confirm this search was made by a human", "select all squares", "anomaly detected",
        )):
            raise SourceError("blocked", "Search provider requested human verification; automatic search paused.")
        hits = []
        seen = set()
        for link in page.links:
            # The collector preserves result-anchor metadata. Navigation,
            # advertising and account links cannot become candidate sources.
            if link.get("kind") != "search_result":
                continue
            destination = clean_destination(link["url"])
            if destination and destination not in seen:
                hits.append(SearchHit(destination, link["label"]))
                seen.add(destination)
        if not hits and "no results" not in page.text.casefold():
            raise SourceError("partial", "Search returned no recognizable result links; provider markup may have changed.")
        return hits[:limit]


class MwmblSearch:
    """Documented unauthenticated v1 API; no key, billing or Super Search.

    API contract: github.com/mwmbl/mwmbl, mwmbl/tinysearchengine/search.py.
    Its independent index is smaller than commercial search indexes.
    """
    name = "mwmbl"

    def __init__(self, fetcher=None):
        self.fetcher = fetcher or PublicWebFetcher(read_timeout=10)

    def query_url(self, query: str) -> str:
        return "https://api.mwmbl.org/api/v1/search/?" + urlencode({"s": query})

    def search(self, query: str, limit: int = 6) -> list[SearchHit]:
        # This fixed public API explicitly permits unauthenticated search.
        # Reuse bounded, IP-validated transport; never follow API redirects.
        status, headers, body = self.fetcher._request(self.query_url(query), time.monotonic() + 25)
        if status != 200:
            raise SourceError("rate_limited" if status == 429 else "failed", f"Mwmbl search returned HTTP {status}.")
        try:
            data = json.loads(body)
            if not isinstance(data, list):
                raise ValueError("Expected result list")
            hits = []
            for item in data[:30]:
                url = clean_destination(item["url"])
                title = "".join(segment["value"] for segment in item["title"])
                if url:
                    hits.append(SearchHit(url, title[:200]))
            return diversified_hits(hits)[:limit]
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError("failed", "Mwmbl returned an invalid search response.") from exc


# Operator-maintained discovery sources, not company recommendations. They are
# selected by geography and always fetched/assessed afresh. No India fallback is
# silently applied to a different named geography.
SOURCE_CATALOG = [
    {"url": "https://villgro.org/companies/", "regions": {"india"}, "label": "Indian impact-incubator portfolio"},
    {"url": "https://www.startupindia.gov.in/content/sih/en/startup_india_showcase.html", "regions": {"india"}, "label": "Startup India showcase"},
    {"url": "https://www.techstars.com/portfolio", "regions": {"global"}, "label": "International accelerator portfolio"},
]


def catalog_urls(geography: Optional[str]) -> list[str]:
    region = (geography or "global").casefold().strip()
    if region in {"anywhere", "worldwide", "any region"}:
        region = "global"
    return [source["url"] for source in SOURCE_CATALOG if region in source["regions"] or 'global' in source['regions']]


def diversified_hits(hits: list[SearchHit]) -> list[SearchHit]:
    seen = set()
    domains: dict[str, int] = {}
    output = []
    # Sites requiring accounts tend to consume the fetch budget without
    # providing business evidence. Prefer accessible original pages instead.
    deferred = []
    for hit in hits:
        url = clean_destination(hit.url)
        if not url or url in seen:
            continue
        host = (urlsplit(url).hostname or "").removeprefix("www.")
        if domains.get(host, 0) >= 2:
            continue
        seen.add(url)
        domains[host] = domains.get(host, 0) + 1
        target = deferred if any(host == d or host.endswith("." + d) for d in ("linkedin.com", "facebook.com", "instagram.com")) else output
        target.append(SearchHit(url, hit.title))
    return output + deferred


def relevant_hits(hits: list[SearchHit], brief: str, geography: Optional[str]) -> list[SearchHit]:
    """Drop obvious search noise before it consumes page/model budgets."""
    ranked = []
    terms = industry_terms(brief)
    for hit in hits:
        path = urlsplit(hit.url).path.casefold()
        text = (hit.title + " " + hit.url).casefold().replace("-", " ")
        if re.search(r"/(tag|category|author|wp-content)/", path) or "getty images" in text:
            continue
        if geography and not matches_location(geography, text):
            foreign = {"africa", "united states", "usa", "england", "united kingdom", "canada", "india", "australia", "singapore"}
            foreign.difference_update(aliases(geography))
            if any(re.search(r"\b" + re.escape(region) + r"\b", text) for region in foreign):
                continue
        overlap = sum(bool(re.search(r"\b" + re.escape(term.removesuffix("s")), text)) for term in terms)
        if terms and not overlap and path not in {"", "/"} and "/companies/" not in path:
            continue
        score = overlap + (2 if geography and geography.casefold() in text else 0)
        ranked.append((score, hit))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return diversified_hits([hit for _, hit in ranked])


def discovery_queries(brief, geography, proposed):
    """Keep useful LLM terms; replace diligence questions with discovery searches."""
    scope = '' if (geography or '').strip().casefold() in WORLD else geography.strip()
    original = f'{brief[:160]} {scope}'.strip()
    valid = [q.strip()[:220] for q in proposed if 3 <= len(q.strip()) <= 220
             and not re.search(r'\?|https?://|^(what|how|does|is|are|can|who)\b|\bthe company\b', q.strip(), re.I)]
    # Source classes, not named company results. New publishers are discovered
    # from the open web on each run; the adapter catalog is supplementary.
    source_queries = [f'{brief[:120]} {scope} {kind}'.strip() for kind in (
        'companies accelerator investor portfolio', 'companies industry association members',
        'university spinouts grants companies')]
    queries = list(dict.fromkeys([original] + valid[:2] + source_queries))
    return [q if not scope or matches_location(scope, q) else f'{q} {scope}' for q in queries]


def discover_pages(run: WebSourcingRun, model: StructuredModel, provider: Optional[SearchProvider],
                   checkpoint: Callable[[], bool]) -> list[str]:
    run.phase = "planning_search"
    if not checkpoint():
        return []
    try:
        if run.research_plan.get('queries'):
            plan = SearchPlan(queries=run.research_plan['queries'][:3])
        else:
            plan = None
        plan = plan or generate_task(model, 'sourcing_plan',
            "Create up to 3 concise public web search queries for discovering real companies matching the user's brief. "
            "Preserve named sectors, stages and geography. If no sector is specified, search cross-sector startup/incubator portfolios. "
            "Include a concise original-brief query and a relevant company/startup-directory query. "
            "Incubation/fundraising are our services, not the target company category. Do not narrow broad technology "
            "to software, fintech or ecommerce unless the user requested that. Do not invent company names, "
            "websites or geographies. Use only public search terms, not operational instructions. Return queries, not results.",
            json.dumps({"brief": run.thesis, "geography": run.geography}), SearchPlan,
        )
        queries = [q.strip()[:220] for q in plan.queries if len(q.strip()) >= 3 and "http" not in q.casefold()]
        if not queries:
            raise ValueError("No usable queries")
    except Exception:
        # A local-model outage must not prevent basic web discovery.
        queries = [f"{run.thesis[:160]} {run.geography or ''} companies".strip()]
        run.warnings.append("Search planning used the original brief because local-model planning was unavailable.")
    # Preserve the user's actual words even when the planner drifts.
    queries = discovery_queries(run.thesis, run.geography, queries)
    run.search_queries = queries
    run.phase = "searching_web"
    session = provider if isinstance(provider, SearchSession) else SearchSession([provider] if provider else None)
    hits = session.search_queries(queries, run, checkpoint)
    discovered = relevant_hits(hits, run.thesis, run.geography)
    directories = startup_directory_urls("startups" if run.research_plan else run.thesis, run.geography)
    run.discovered_urls = list(dict.fromkeys(directories + [h.url for h in discovered]))
    removed = len(hits) - len(discovered)
    if removed:
        run.sources.append(WebSourceOutcome(url=run.sources[-1].url if run.sources else "https://html.duckduckgo.com/", status="filtered",
            detail=f"Excluded {removed} irrelevant/archive/geography-conflicting search destinations before research."))
    if not run.discovered_urls:
        fallbacks = catalog_urls(run.geography)
        if fallbacks:
            run.warnings.append("Automatic search yielded no usable pages. Research is using the regional source catalog; coverage is limited.")
            run.discovered_urls = fallbacks
        else:
            run.warnings.append("Automatic search yielded no usable pages, and no catalog fallback covers this geography. Retry later; no matching-company conclusion can be drawn.")
    checkpoint()
    return list(run.discovered_urls)


class SearchSession:
    """Bounded multi-provider search with failure memory for the entire job."""
    name = "search_session"

    def __init__(self, providers=None):
        self.providers = providers if providers is not None else [DuckDuckGoSearch(), MwmblSearch()]
        self.disabled = set()
        self.cache = {}

    def search_queries(self, queries, run, checkpoint):
        hits = []
        for engine in self.providers:
            if engine.name in self.disabled:
                continue
            for query in queries:
                if not checkpoint():
                    return diversified_hits(hits)
                if query not in run.search_queries:
                    run.search_queries.append(query)
                key = (engine.name, query)
                query_url = (engine.query_url(query) if hasattr(engine, "query_url") else
                             "https://html.duckduckgo.com/html/?" + urlencode({"q": query}))
                try:
                    if key not in self.cache:
                        self.cache[key] = engine.search(query, limit=6)
                        results = self.cache[key]
                        run.sources.append(WebSourceOutcome(url=query_url, kind="search", status="ok" if results else "no_results",
                            detail=f"{engine.name}: {len(results)} discovery links; original pages require verification."))
                    hits.extend(self.cache[key])
                except Exception as exc:
                    status = exc.status if isinstance(exc, SourceError) else "failed"
                    detail = str(exc) if isinstance(exc, SourceError) else f"Search unavailable ({type(exc).__name__})."
                    run.sources.append(WebSourceOutcome(url=query_url, kind="search", status=status, detail=detail))
                    # Respect access blocks and rate limits. A transport
                    # failure for one query must not discard a different
                    # already-planned query; never retry the failed query.
                    if status in {'blocked','rate_limited'}:
                        self.disabled.add(engine.name)
                        break
            # A single weak link must not suppress the independent provider.
            if len(diversified_hits(hits)) >= 6:
                break
        return diversified_hits(hits)
