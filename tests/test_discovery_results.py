from unittest.mock import Mock

from fastapi.testclient import TestClient

import api.deps as deps
from api.main import app
from agents.company_sourcing import bind_run_result, source_companies
from agents.public_directories import directory_profiles, matches_business, startup_directory_urls
from agents.web_discovery import relevant_hits, SearchHit
from agents.web_sources import Page, parse_page
from schemas import CompanyEvidence, CompanyProfile, SourcedLead, WebSourcingRun
from store import Store


def card(name, status='Active', batch='W2026', offering='Software for warehouse automation'):
    return f'''<li><a href="/companies/{name.casefold()}"><span class="text-2xl">{name}</span></a>
        <div class="yc-tw-Pill">{batch}</div><span class="text-gray-700">{status}</span>
        <span class="text-gray-700">8 employees</span><span class="text-gray-700">Bengaluru, India</span>
        <div class="line-clamp-3">{offering}</div><div class="yc-tw-Pill">software</div></li>'''


def test_directory_uses_actual_cards_filters_stage_and_preserves_provenance():
    # Global multi-region portfolios (Antler/SOSV/Seedcamp) are now prepended
    # ahead of the region-specific YC URL, so index [0] is no longer reliably
    # the YC page -- pick it out explicitly instead.
    url = next(u for u in startup_directory_urls('tech startups', 'India') if 'ycombinator' in u)
    page = parse_page(url, card('Older', batch='S2015') + card('Newer') + card('Listed', status='Public') +
                      card('Bought', status='Acquired'))
    profiles = directory_profiles(page, 'tenant', 'tech startups')
    assert [p.name for p in profiles] == ['Newer', 'Older']
    assert all(p.website == '' for p in profiles)  # Directory != official website.
    assert all(e.source_url == url for p in profiles for e in p.evidence)
    assert profiles[0].evidence[1].value == 'Software for warehouse automation'
    assert directory_profiles(parse_page(url, card('Different')), 'tenant', 'tech startups')[0].name == 'Different'
    assert parse_page('https://untrusted.example/', card('Impersonator')).directory_entries == []


def test_sector_filter_does_not_turn_hotels_into_tech_startups():
    assert not matches_business('tech startups', 'Indian hotel chain operating luxury hotels')
    assert matches_business('tech startups', 'AI software for warehouse operators')
    assert matches_business('agricultural companies', 'Solar dryers for farmers')
    assert not matches_business('fintech financial technology digital banking fintech startups', 'Drone technology for crop monitoring')
    assert matches_business('fintech financial technology digital banking fintech startups', 'Digital payments platform')
    assert any('canada' in u for u in startup_directory_urls('robotics startups', 'Canada') if 'ycombinator' in u)
    assert startup_directory_urls('Hotel operators', 'India') == []


def test_india_only_directories_are_not_queried_for_other_geographies():
    """Found live: a real 'AI & Robotics' / United States search still
    returned Indian companies, because blume.vc/startups (an India-only VC
    portfolio -- every listed company operates in India) had no geography
    gate at all and was queried for every search regardless of region.
    Villgro already had the correct gate; this is the same fix applied to
    Blume."""
    us_urls = startup_directory_urls('tech startups', 'United States')
    assert not any('blume.vc' in u or 'villgro.org' in u for u in us_urls)
    assert any('united-states' in u for u in us_urls)

    india_urls = startup_directory_urls('tech startups', 'India')
    assert any('blume.vc' in u for u in india_urls)
    assert any('villgro.org' in u for u in india_urls)

    global_urls = startup_directory_urls('tech startups', None)
    assert not any('blume.vc' in u or 'villgro.org' in u for u in global_urls)


def test_identity_resolution_replaces_the_card_instead_of_adding_a_duplicate():
    old = CompanyProfile(tenant_id='one', name='Same Company', website='', evidence=[])
    resolved = old.model_copy(update={'id':'canonical-company', 'website':'https://resolved.example/'})
    lead = SourcedLead(tenant_id='one', company_id=resolved.id, company_name=resolved.name, company_profile=resolved)
    run = WebSourcingRun(tenant_id='one', thesis='tech startups', model='test',
        company_ids=[old.id], lead_ids=['temporary-lead'], company_profiles=[old])
    bind_run_result(run, lead, resolved, old.id)
    bind_run_result(run, lead, resolved, resolved.id)
    assert run.company_ids == [resolved.id]
    assert run.lead_ids == [lead.id]
    assert [p.id for p in run.company_profiles] == [resolved.id]


def test_irrelevant_pages_do_not_consume_research_budget():
    hits = [SearchHit('https://news.example/tag/getty-images/', 'Getty Images'),
            SearchHit('https://news.example/funding-rounds-in-africa-2021/', 'Tech startup funding in Africa'),
            SearchHit('https://directory.example/india-tech-startups/', 'Tech startups India')]
    assert relevant_hits(hits, 'tech startups', 'India') == [hits[2]]


def test_run_results_exclude_history_and_keep_evidence_snapshot(tmp_path):
    path = tmp_path / 'db'
    with Store(path) as store:
        old = CompanyProfile(tenant_id='one', name='Old Hotel', website='https://hotel.example/', evidence=[])
        tech = CompanyProfile(tenant_id='one', name='Tech Example', website='https://tech.example/', evidence=[
            CompanyEvidence(field='offering', value='AI software', quote='AI software', source_url='https://tech.example/')])
        old_lead = SourcedLead(tenant_id='one', company_id=old.id, company_name=old.name, company_profile=old)
        tech_lead = SourcedLead(tenant_id='one', company_id=tech.id, company_name=tech.name, company_profile=tech)
        store.save_lead(old_lead); store.save_lead(tech_lead)
        run = WebSourcingRun(tenant_id='one', thesis='tech startups', model='test', lead_ids=[tech_lead.id],
                            company_ids=[tech.id], company_profiles=[tech.model_copy(deep=True)])
        store.save_web_run(run)
        tech_lead.company_profile.evidence[0].value = 'Changed after the search'
        store.save_lead(tech_lead)
        empty = WebSourcingRun(tenant_id='one', thesis='No supported results yet', model='test')
        store.save_web_run(empty)
    def db():
        with Store(path) as store: yield store
    original = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_store] = db
    app.dependency_overrides[deps.get_tenant_id] = lambda: 'one'
    try:
        client = TestClient(app)
        response = client.get(f'/api/leads/web-runs/{run.id}/leads')
        assert response.status_code == 200
        assert [l['company_name'] for l in response.json()] == ['Tech Example']
        assert response.json()[0]['company_profile']['evidence'][0]['value'] == 'AI software'
        assert client.get(f'/api/leads/web-runs/{empty.id}/leads').json() == []
        assert all('company_profiles' not in item for item in client.get('/api/leads/web-runs').json())
        app.dependency_overrides[deps.get_tenant_id] = lambda: 'other'
        assert client.get(f'/api/leads/web-runs/{run.id}/leads').status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


def test_candidates_are_published_before_model_work_and_survive_model_failure(tmp_path):
    with Store(tmp_path / 'db') as store:
        run = WebSourcingRun(tenant_id='one', thesis='tech startups', geography='India', model='test')
        class Model:
            name = 'test'
            def generate(self, instruction, evidence, schema):
                # Public records must already be visible when planning starts.
                saved = store.get_web_run('one', run.id)
                assert len(saved.lead_ids) == 1
                assert saved.company_profiles[0].name == 'Candidate'
                assert store.get_workspace('one', lead_id=saved.lead_ids[0])
                raise RuntimeError('Local model unavailable')
        fetcher = Mock()
        fetcher.fetch.side_effect = lambda url: parse_page(url, card('Candidate')) if '/location/' in url else Page(url, 'Unavailable', '')
        class Search:
            name = 'fixture'
            def search(self, query, limit=6):
                return []
        search = Search()
        # India now resolves 6 directory URLs (3 global portfolios + YC +
        # blume.vc + villgro.org), not just the 1 YC page this test cares
        # about -- max_pages must cover all of them so the real card is
        # still reached regardless of fetch order.
        done = source_companies(store, run, model=Model(), fetcher=fetcher, search_provider=search, max_companies=1, max_pages=10)
        assert done.status == 'partial'
        assert len(done.lead_ids) == 1
        assert done.company_profiles[0].name == 'Candidate'
        first_id = done.company_ids[0]
        lead = store.get_lead('one', done.lead_ids[0])
        lead.company_profile.website = 'https://resolved.example/'
        store.save_company(lead.company_profile)
        store.save_lead(lead)
        second = WebSourcingRun(tenant_id='one', thesis='tech startups', geography='India', model='test')
        done_again = source_companies(store, second, model=Model(), fetcher=fetcher, search_provider=search, max_companies=1, max_pages=10)
        assert done_again.company_ids == [first_id]
        assert len(store.list_leads('one')) == 1
