import json
from unittest.mock import Mock

from agents.company_enrichment import enrich_profiles
from agents.company_sourcing import Candidate, PageCandidates, QuotedFact
from agents.web_discovery import SearchHit, SearchSession
from agents.web_sources import Page, PublicWebFetcher, parse_pdf
from schemas import CompanyEvidence, CompanyProfile, WebSourcingRun


def test_targeted_enrichment_resolves_linked_company_and_adds_evidence():
    profile = CompanyProfile(tenant_id="t", name="Farm Works", website="", evidence=[CompanyEvidence(
        field="name", value="Farm Works", quote="Farm Works", source_url="https://portfolio.example/")])
    run = WebSourcingRun(tenant_id="t", thesis="Farming", model="fixture")
    page = Page("https://farm.example/", "Farm Works", "Farm Works makes solar dryers in India.")
    model = Mock()
    model.generate.return_value = PageCandidates(companies=[Candidate(name="Farm Works", name_block_id="b1",
        website=page.url, facts=[QuotedFact(field="offering", value="solar dryers", source_block_id="b1")])])
    search = Mock()
    search.search_queries.return_value = [SearchHit(page.url, page.title)]
    fetcher = Mock()
    fetcher.fetch.return_value = page
    enrich_profiles({"unresolved": profile}, run, model, fetcher, search, lambda: True, 3,
                    {profile.id: {page.url}})
    assert profile.website == page.url
    assert any(e.field == "offering" for e in profile.evidence)
    assert run.search_queries == []  # Reading an observed link is not a search query.
    search.search_queries.assert_not_called()


def test_name_match_alone_cannot_merge_unrelated_company():
    profile = CompanyProfile(tenant_id="t", name="Farm Works", website="", evidence=[CompanyEvidence(
        field="name", value="Farm Works", quote="Farm Works", source_url="https://portfolio.example/")])
    run = WebSourcingRun(tenant_id="t", thesis="Farming", model="fixture")
    model = Mock()
    model.generate.return_value = PageCandidates(companies=[Candidate(name="Farm Works", name_block_id="b1",
        website="https://unrelated.example/", facts=[])])
    search = Mock()
    search.search_queries.return_value = [SearchHit("https://unrelated.example/", "Farm Works")]
    fetcher = Mock()
    fetcher.fetch.return_value = Page("https://unrelated.example/", "Farm Works", "Farm Works sells something else.")
    enrich_profiles({"unresolved": profile}, run, model, fetcher, search, lambda: True, 3)
    assert not profile.website
    assert len(profile.evidence) == 1
    assert any("identity linkage" in source.detail for source in run.sources)


def test_search_tries_second_provider_for_sparse_results_and_caches():
    first, second = Mock(), Mock()
    first.name, second.name = "one", "two"
    first.query_url.return_value = second.query_url.return_value = "https://search.example/"
    first.search.return_value = [SearchHit("https://one.example/", "One")]
    second.search.return_value = [SearchHit("https://two.example/", "Two")]
    session = SearchSession([first, second])
    run = WebSourcingRun(tenant_id="t", thesis="Hotels", model="fixture")
    for _ in range(2):
        hits = session.search_queries(["Hotels India"], run, lambda: True)
        assert len(hits) == 2
    first.search.assert_called_once()
    second.search.assert_called_once()


def test_robots_redirect_is_followed_before_page_collection(monkeypatch):
    fetcher = PublicWebFetcher()
    request = Mock(side_effect=[(301, {"Location": "https://example.org/robots-final.txt"}, b""),
                                (200, {}, b"User-agent: *\nAllow: /"),
                                (200, {"Content-Type": "text/html"}, b"<p>" + b"Company information " * 20 + b"</p>")])
    monkeypatch.setattr(fetcher, "_request", request)
    assert fetcher.fetch("https://example.org/").text
    assert request.call_args_list[1].args[0] == "https://example.org/robots-final.txt"


def test_public_pdf_text_has_page_markers():
    from pathlib import Path
    body = (Path(__file__).resolve().parents[1] / "sample_docs/acme_robotics_fact_sheet.pdf").read_bytes()
    page = parse_pdf("https://company.example/report.pdf", body)
    assert "[PDF page 1]" in page.text
    assert "Acme" in page.text


def test_identity_only_profile_never_gets_speculative_business_assessment(tmp_path):
    from agents.company_sourcing import source_companies
    from store import Store
    class IdentityOnly:
        name = "fixture"
        def generate(self, instruction, payload, schema):
            assert schema is PageCandidates, "Do not ask the model to invent a business assessment"
            return PageCandidates(companies=[Candidate(name="Example", name_block_id="b1")])
    fetcher = Mock()
    fetcher.fetch.return_value = Page("https://example.org/", "Example", "Example in India.")
    with Store(tmp_path / "sparse.db") as store:
        run = source_companies(store, WebSourcingRun(tenant_id="t", thesis="Hotels", model="fixture",
            seed_urls=["https://example.org/"]), model=IdentityOnly(), fetcher=fetcher)
        assessment = store.list_leads("t")[0].company_profile.assessment
        assert assessment.status == "needs_review"
        assert assessment.rationale == "Insufficient evidence for selection."
        assert run.status == "partial"


def test_short_crawl_delay_is_honored(monkeypatch):
    from urllib.robotparser import RobotFileParser
    fetcher = PublicWebFetcher()
    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Crawl-delay: 1", "Allow: /"])
    fetcher.robots["https://example.org"] = parser
    fetcher.last_request["example.org"] = 100
    monkeypatch.setattr("agents.web_sources.time.monotonic", lambda: 100.25)
    sleep = Mock()
    monkeypatch.setattr("agents.web_sources.time.sleep", sleep)
    fetcher._allowed("https://example.org/", 125)
    sleep.assert_called_once_with(0.75)


def test_growth_request_searches_metrics_even_when_company_site_is_known():
    p = CompanyProfile(tenant_id='t',name='Payments Example',website='https://company.example/',evidence=[
        CompanyEvidence(field=field,value=value,quote=value,source_url='https://company.example/') for field,value in
        [('offering','Payment processing'),('location','India'),('team','Founder'),('traction','500 customers')]])
    run = WebSourcingRun(tenant_id='t',thesis='rapidly growing fintech companies',geography='India',model='fixture')
    run.research_plan = {'criteria':[{'dimension':'growth','requirement':'rapid growth'}]}
    search = Mock()
    search.search_queries.return_value = [SearchHit('https://company.example/results','Company results')]
    fetcher = Mock()
    fetcher.fetch.return_value = Page('https://company.example/results','Results','No new evidence')
    model = Mock();model.name='fixture';model.generate.return_value=PageCandidates()
    enrich_profiles({'p':p},run,model,fetcher,search,lambda:True,1,{p.id:{p.website}})
    assert search.search_queries.call_args.args[0] == ['"Payments Example" revenue customer growth']
    assert fetcher.fetch.call_args.args[0]=='https://company.example/results'
    assert any(d['step']=='Research evidence gap' for d in run.reasoning_log)


def test_named_search_rejects_generic_growth_articles_before_fetching():
    from agents.company_enrichment import company_search_hits
    p = CompanyProfile(tenant_id='t',name='Payments Example',website='https://company.example/',evidence=[])
    hits = [SearchHit('https://shopify.example/customer-segments','Customer segments to grow revenue'),
            SearchHit('https://news.example/payments-example-results','Payments Example annual results'),
            SearchHit('https://company.example/report','Annual report')]
    assert company_search_hits(hits,p) == hits[1:]
