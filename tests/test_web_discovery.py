"""The default product path must work from a brief, without user URLs."""
import json

import pytest

from agents.company_sourcing import (AssessmentDraft, Candidate, PageCandidates, QuotedFact,
                                    accepted_candidate, page_blocks, source_companies)
from agents.web_discovery import (DuckDuckGoSearch, SearchHit, SearchPlan, catalog_urls,
                                 clean_destination, discover_pages, diversified_hits)
from agents.web_sources import Page, SourceError, parse_page
from schemas import WebSourcingRun
from store import Store
from agents.research_reasoning import ResearchPlan, Screening


def test_company_questions_are_replaced_with_diverse_discovery_queries():
    from agents.web_discovery import discovery_queries
    queries=discovery_queries('AI & Robotics','United States',["What is the company's primary product?",'AI robotics companies'])
    assert all('?' not in q and 'the company' not in q for q in queries)
    assert all('United States' in q for q in queries)
    assert any('association' in q for q in queries)
    assert any('spinouts' in q for q in queries)
    assert not any('India' in q for q in queries)


class Model:
    name = "offline-model"

    def generate(self, instruction, evidence, schema):
        if schema is ResearchPlan:
            return ResearchPlan(interpretation='Agricultural businesses in the requested geography', sector_terms=['agriculture', 'farming'],
                criteria=[dict(dimension='sector',requirement='Agriculture',evidence_needed='Agricultural offering')],
                queries=['agricultural companies solar dryers'],follow_up_terms=['customers'])
        if issubclass(schema, Screening):
            data = json.loads(evidence)
            return Screening(candidates=[dict(candidate_id=p['candidate_id'],priority=1,reason='Agricultural offering evidenced',criteria=[
                dict(dimension=c['dimension'],status='supported',reason='Company source supports this criterion',evidence_ids=[next(e['id'] for e in p['evidence'] if e['field']==('location' if c['dimension']=='geography' else 'offering'))])
                for c in data['plan']['criteria']]) for p in data['candidates']])
        if schema is SearchPlan:
            return SearchPlan(queries=["agricultural companies solar dryers"])
        if schema is PageCandidates:
            return PageCandidates(companies=[Candidate(
                name="Farm Works", name_block_id="b1", website="https://farm.example/", facts=[
                    QuotedFact(field="offering", value="solar dryers", source_block_id="b1"),
                    QuotedFact(field="location", value="India", source_block_id="b1"),
                ],
            )])
        company = json.loads(evidence)["COMPANY"]
        return AssessmentDraft(recommendation="invite_to_discussion", rationale="Validate demand for the dryers.",
                               evidence_ids=[e["id"] for e in company["evidence"]])


class Search:
    name = "fixture_search"

    def __init__(self):
        self.queries = []

    def search(self, query, limit=6):
        self.queries.append(query)
        return [SearchHit("https://farm.example/", "Farm Works")]


class Fetcher:
    def __init__(self):
        self.visited = []

    def fetch(self, url):
        self.visited.append(url)
        if url != 'https://farm.example/':
            raise SourceError('blocked', 'Fixture has no company evidence for this source')
        return Page("https://farm.example/", "Farm Works", "Farm Works makes solar dryers for farmers in India.", [])


def test_brief_only_run_searches_then_fetches_and_persists(tmp_path, monkeypatch):
    # This test isolates web search; directory selection is covered independently.
    monkeypatch.setattr('agents.company_sourcing.startup_directory_urls', lambda *args: [])
    monkeypatch.setattr('agents.web_discovery.startup_directory_urls', lambda *args: [])
    search, fetcher = Search(), Fetcher()
    with Store(tmp_path / "discover.db") as store:
        run = WebSourcingRun(tenant_id="one", thesis="Agricultural businesses", geography="India", model="local")
        run = source_companies(store, run, model=Model(), fetcher=fetcher, search_provider=search)
        assert run.status == "partial"
        assert any('Only one discovery publisher' in warning for warning in run.warnings)
        assert run.seed_urls == []
        assert search.queries[0] == "Agricultural businesses India"
        assert "agricultural companies solar dryers India" in search.queries
        assert set(fetcher.visited) == {"https://farm.example/"}
        assert run.discovered_urls == ["https://farm.example/"]
        assert len(run.company_ids) == 1
        lead = store.list_leads("one")[0]
        assert lead.company_profile.evidence[1].value == "solar dryers"
        assert lead.company_profile.assessment.recommendation == "invite_to_discussion"
        assert store.get_web_run("one", run.id).phase == "finished"


def test_search_html_only_uses_result_links_and_decodes_destinations():
    page = parse_page("https://html.duckduckgo.com/html/?q=farming", """
    <title>Search</title><a href='https://duckduckgo.com/settings'>Settings</a>
    <a class='result__a' href='//duckduckgo.com/l/?uddg=https%3A%2F%2Ffarm.example%2F&amp;rut=123'>Farm Works</a>
    <a class='result__a' href='https://farm.example/'>Duplicate</a>
    <a class='result__a' href='javascript:alert(1)'>Bad</a>
    <a href='https://advertiser.example/'>Advertisement</a>
    """)
    class SearchFetcher:
        def fetch(self, url):
            return page
    hits = DuckDuckGoSearch(SearchFetcher()).search("farm companies")
    assert hits == [SearchHit("https://farm.example/", "Farm Works")]


def test_challenge_is_failure_not_zero_results():
    class ChallengeFetcher:
        def fetch(self, url):
            return Page(url, "Search", "Unfortunately, bots use DuckDuckGo too. Confirm this search was made by a human.")
    with pytest.raises(SourceError, match="verification"):
        DuckDuckGoSearch(ChallengeFetcher()).search("farm companies")


def test_search_failure_uses_catalog_without_asking_for_urls():
    class BlockedSearch(Search):
        def search(self, query, limit=6):
            self.queries.append(query)
            raise SourceError("rate_limited", "Search rate limit")
    run = WebSourcingRun(tenant_id="one", thesis="Any sector", geography="India", model="local")
    provider = BlockedSearch()
    urls = discover_pages(run, Model(), provider, lambda: True)
    assert urls == catalog_urls("India")
    assert urls
    assert run.sources[0].status == "rate_limited"
    assert run.warnings
    assert len(provider.queries) == 1
    assert catalog_urls("Canada")  # Global sources cover named regions too.
    assert not any('india' in u or 'villgro' in u for u in catalog_urls('Canada'))


def test_unknown_region_search_outage_does_not_claim_no_matching_companies(tmp_path):
    class Broken(Search):
        def search(self, query, limit=6):
            raise SourceError("failed", "Search unavailable")
    with Store(tmp_path / "discover.db") as store:
        run = source_companies(store, WebSourcingRun(tenant_id="one", thesis="Manufacturing", geography="Canada", model="local"),
                               model=Model(), fetcher=Fetcher(), search_provider=Broken())
        assert run.status == "partial"
        assert run.error
        assert run.company_ids == []
        assert any(s.status == 'failed' for s in run.sources)


def test_manual_urls_remain_optional_override(tmp_path):
    class NoSearch(Search):
        def search(self, query, limit=6):
            pytest.fail("Explicit source override should not search")
    with Store(tmp_path / "discover.db") as store:
        run = source_companies(store, WebSourcingRun(tenant_id="one", thesis="Farms", seed_urls=["https://farm.example/"], model="local"),
                               model=Model(), fetcher=Fetcher(), search_provider=NoSearch())
        assert len(run.company_ids) == 1


def test_block_citations_attach_original_passages_and_reject_invented_ids():
    page = Fetcher().fetch("https://farm.example/")
    candidate = Model().generate("", "", PageCandidates).companies[0]
    profile = accepted_candidate(candidate, page)
    assert profile.evidence[1].quote == page_blocks(page)["b1"]
    candidate.facts[0].source_block_id = "b999"
    profile = accepted_candidate(candidate, page)
    assert not any(e.field == "offering" for e in profile.evidence)
    candidate.name_block_id = "b999"
    assert accepted_candidate(candidate, page) is None


def test_non_company_publishers_are_rejected():
    page = Fetcher().fetch("https://farm.example/")
    candidate = Candidate(name="Farm Works", name_block_id="b1", entity_type="publisher")
    assert accepted_candidate(candidate, page) is None


def test_about_and_product_pages_use_one_company_identity():
    page = Fetcher().fetch("https://farm.example/")
    page.url = "https://farm.example/products"
    candidate = Candidate(name="Farm Works", name_block_id="b1", website=page.url)
    assert accepted_candidate(candidate, page).website == "https://farm.example/"


def test_geography_mismatch_cannot_become_invitation(tmp_path):
    with Store(tmp_path / "discover.db") as store:
        run = source_companies(store, WebSourcingRun(tenant_id="one", thesis="Farms", geography="Canada", seed_urls=["https://farm.example/"], model="local"),
                               model=Model(), fetcher=Fetcher())
        assessment = store.list_leads("one")[0].company_profile.assessment
        assert assessment.recommendation == "investigate"
        assert any("Canada" in item for item in assessment.missing_information)


def test_search_diversity_and_unsafe_destinations():
    hits = diversified_hits([SearchHit("https://one.example/a", "A"), SearchHit("https://one.example/b", "B"),
                             SearchHit("https://one.example/c", "C"), SearchHit("https://two.example/", "D")])
    assert len(hits) == 3
    assert clean_destination("file:///etc/passwd") is None
    assert clean_destination("http://127.0.0.1/") is None


def test_api_accepts_brief_without_urls(tmp_path, monkeypatch):
    import api.deps as deps
    import api.routers.leads as routes
    from api.main import app
    from fastapi.testclient import TestClient
    def get_store():
        with Store(tmp_path / "api.db") as store:
            yield store
    def worker(store, run, **kwargs):
        return source_companies(store, run, model=Model(), fetcher=Fetcher(), search_provider=Search(), **kwargs)
    monkeypatch.setattr(routes, "source_companies", worker)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_store] = get_store
    try:
        with TestClient(app) as client:
            response = client.post("/api/leads/web-runs", json={"thesis": "Find agricultural companies", "geography": "India"})
            assert response.status_code == 202
            result = client.get(f"/api/leads/web-runs/{response.json()['id']}").json()
            assert result["seed_urls"] == []
            assert result["search_queries"]
            assert len(result["company_ids"]) == 1
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


def test_independent_provider_fallback_retains_failed_attempt(monkeypatch):
    import agents.web_discovery as discovery
    class Blocked(Search):
        name = "blocked_fixture"
        def search(self, query, limit=6):
            raise SourceError("blocked", "Human verification requested")
    fallback = Search()
    monkeypatch.setattr(discovery, "DuckDuckGoSearch", Blocked)
    monkeypatch.setattr(discovery, "MwmblSearch", lambda: fallback)
    run = WebSourcingRun(tenant_id="one", thesis="Farming", geography="India", model="local")
    urls = discover_pages(run, Model(), None, lambda: True)
    assert urls == ["https://farm.example/"]
    assert run.sources[0].status == "blocked"
    assert run.sources[1].status == "ok"
    assert not run.warnings
    urls.clear()
    assert run.discovered_urls == ["https://farm.example/"]


def test_mwmbl_parses_api_results_without_using_snippets_as_evidence():
    from agents.web_discovery import MwmblSearch
    class Transport:
        def _request(self, url, deadline):
            assert url.startswith("https://api.mwmbl.org/api/v1/search/?s=")
            return 200, {}, json.dumps([{"url": "https://farm.example/", "title": [{"value": "Farm Works"}],
                                       "extract": [{"value": "Unverified sales figures"}]}]).encode()
    assert MwmblSearch(Transport()).search("farm India") == [SearchHit("https://farm.example/", "Farm Works")]


def test_unusable_search_pages_expand_to_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr('agents.company_sourcing.startup_directory_urls', lambda *args: [])
    monkeypatch.setattr('agents.web_discovery.startup_directory_urls', lambda *args: [])
    class ExpandingFetcher(Fetcher):
        def fetch(self, url):
            self.visited.append(url)
            if url == "https://farm.example/":
                raise SourceError("blocked", "Source unavailable")
            return Page(url, "Farm Works", "Farm Works makes solar dryers for farmers in India.", [{"url": "https://farm.example/", "label": "Farm Works"}])
    fetcher = ExpandingFetcher()
    with Store(tmp_path / "expand.db") as store:
        run = WebSourcingRun(tenant_id="one", thesis="Farming", geography="India", model="local")
        result = source_companies(store, run, model=Model(), fetcher=fetcher, search_provider=Search(), max_pages=2)
        assert "https://villgro.org/companies/" in fetcher.visited
        assert result.company_ids
        assert any("Expanding" in warning for warning in result.warnings)
        assert result.status == "partial"
