from unittest.mock import Mock

from agents.company_sourcing import source_companies
from agents.public_directories import directory_profiles
from agents.web_sources import Page, SourceError, parse_page
from schemas import CompanyEvidence, CompanyProfile, WebSourcingRun, WebSourceOutcome
from store import Store


def yc(name):
    return f'<li><a href="/companies/{name.lower()}"><span class="text-2xl">{name}</span></a><span class="text-gray-700">Active</span><span class="text-gray-700">3</span><span class="text-gray-700">India</span><div class="line-clamp-3">AI software for retail</div><div class="yc-tw-Pill">W2026</div></li>'


def blume(name, location='India', status='Active'):
    return f'<div id="{name}"><a href="/{name}">Profile</a><div data-highlight-term="{name}"><div class="richtext">{name} builds robotics for farms.</div></div><dl><span title="Investment Status">{status}</span><span title="Locations">{location}</span></dl></div>'


def villgro(name):
    return f'<div class="e-parent"><div><h3><a href="https://{name.lower()}.example/">{name}</a></h3></div><div class="elementor-widget-text-editor">Drone technology for crop monitoring.</div></div>'


def test_independent_portfolio_parsers_keep_geography_and_status_honest():
    url = 'https://blume.vc/startups'
    page = parse_page(url, blume('Indigo') + blume('Foreign', 'USA') + blume('Exited', status='Exited'))
    profiles = directory_profiles(page, 'one', 'tech startups', 'India')
    assert [p.name for p in profiles] == ['Indigo']
    assert {e.field for e in profiles[0].evidence} >= {'name', 'offering', 'location', 'portfolio_status'}
    assert not any(e.field == 'reported_status' for e in profiles[0].evidence)
    assert all(e.source_url == url for e in profiles[0].evidence)
    page = parse_page('https://villgro.org/companies/', villgro('Fieldtech'))
    profile = directory_profiles(page, 'one', 'tech startups', 'India')[0]
    assert profile.name == 'Fieldtech'
    assert not any(e.field in {'location', 'reported_status'} for e in profile.evidence)
    assert profile.website == ''
    assert not parse_page('https://impostor.example/', blume('Wrong')).directory_entries


class NoModel:
    name = 'offline-test'
    def generate(self, *args):
        raise RuntimeError('No model in this retrieval test')


class NoSearch:
    name = 'offline-search'
    def search(self, *args, **kwargs):
        return []


def test_first_directory_cannot_consume_all_candidate_slots(tmp_path):
    def fetch(url):
        html = ''.join(yc('Yc'+str(i)) for i in range(8)) if '/location/' in url else ''.join(blume('Blume'+str(i)) for i in range(4)) if 'blume.vc/startups' in url else villgro('Fieldtech') if 'villgro.org/companies' in url else ''
        return parse_page(url, html) if html else Page(url, '', '')
    with Store(tmp_path / 'db') as store:
        run = source_companies(store, WebSourcingRun(tenant_id='one', thesis='tech startups', geography='India', model='test'),
            model=NoModel(), fetcher=Mock(fetch=Mock(side_effect=fetch)), search_provider=NoSearch(), max_pages=8, max_companies=5)
        assert len(run.company_profiles) == 5
        counts = {r['host']: r['discovered_companies'] for r in run.source_coverage}
        assert counts['ycombinator.com'] == counts['blume.vc'] == 2
        assert counts['villgro.org'] == 1
        assert store.get_web_run('one', run.id).source_coverage == run.source_coverage


def test_thin_yc_directory_read_is_marked_incomplete_not_no_results(tmp_path):
    """Found live: YC's own location page fully renders ~50 cards for a
    normal-sized region (India, or a single city) but only 1-2 for the
    'united-states' aggregate -- the rest needs client-side JS this pipeline
    can't execute. Without this check, a thin read is indistinguishable from
    a genuinely small, fully-covered market, which produced a real, misleading
    'no matching companies' result for a real US search."""
    def fetch(url):
        if 'ycombinator.com/companies/location' in url:
            return parse_page(url, yc('Waypoint') + yc('FontAwesome'))  # only 2 cards, like the real bug
        return Page(url, '', '')
    with Store(tmp_path / 'db') as store:
        run = source_companies(store, WebSourcingRun(tenant_id='one', thesis='tech startups', geography='United States', model='test'),
            model=NoModel(), fetcher=Mock(fetch=Mock(side_effect=fetch)), search_provider=NoSearch(), max_companies=5)
        outcome = next(o for o in run.sources if o.kind == 'directory' and 'ycombinator.com' in o.url)
        assert outcome.status == 'incomplete'
        assert 'JavaScript' in outcome.detail
        assert outcome.records_read == 2


def test_unavailable_sources_backfill_but_do_not_claim_diversity(tmp_path):
    def fetch(url):
        if 'ycombinator.com/companies/location' in url:
            return parse_page(url, ''.join(yc('Company'+str(i)) for i in range(7)))
        raise SourceError('blocked', 'Provider unavailable')
    with Store(tmp_path / 'db') as store:
        run = source_companies(store, WebSourcingRun(tenant_id='one', thesis='tech startups', geography='India', model='test'),
            model=NoModel(), fetcher=Mock(fetch=Mock(side_effect=fetch)), search_provider=NoSearch(), max_companies=5)
        assert len(run.company_profiles) == 5
        assert len([r for r in run.source_coverage if r['discovered_companies']]) == 1
        assert any('Only one discovery publisher' in w for w in run.warnings)
        assert next(r for r in run.source_coverage if r['host']=='blume.vc')['status']=='Unavailable'


def test_search_links_are_not_company_evidence_or_new_discoveries():
    profile = CompanyProfile(tenant_id='one', name='Example', website='', discovery_source_url='https://blume.vc/startups',
        evidence=[CompanyEvidence(field='offering', value='Robotics', quote='Robotics', source_url='https://blume.vc/startups')])
    run = WebSourcingRun(tenant_id='one', thesis='tech', model='test', company_profiles=[profile], sources=[
        WebSourceOutcome(url='https://api.mwmbl.org/api/v1/search/', status='ok', detail='99 companies claimed in log text'),
        WebSourceOutcome(url='https://blume.vc/startups', status='ok', detail='Fetched', records_read=20, matches=4)])
    coverage = {r['host']:r for r in run.source_coverage}
    assert coverage['api.mwmbl.org']['cited_claims'] == coverage['api.mwmbl.org']['discovered_companies'] == 0
    assert coverage['blume.vc']['discovered_companies'] == 1
    assert coverage['blume.vc']['cited_claims'] == 1


def test_natural_fintech_brief_uses_directories_and_stable_claim_ids(tmp_path):
    brief = 'find companies in the fintech space in india which are rapidly growing'
    def fetch(url):
        if 'ycombinator.com/companies/location' in url:
            return parse_page(url, yc('PaymentExample').replace('AI software for retail','Digital payments platform') + yc('UnrelatedTech'))
        raise SourceError('blocked','Unavailable fixture source')
    with Store(tmp_path / 'db') as store:
        def execute():
            return source_companies(store,WebSourcingRun(tenant_id='one',thesis=brief,geography='India',model='test'),
                model=NoModel(),fetcher=Mock(fetch=Mock(side_effect=fetch)),search_provider=NoSearch(),max_companies=2)
        first = execute()
        assert [p.name for p in first.company_profiles] == ['PaymentExample']
        second = execute()
        assert first.lead_ids == second.lead_ids
        assert [e.id for e in first.company_profiles[0].evidence] == [e.id for e in second.company_profiles[0].evidence]
        assert next(c for c in second.company_profiles[0].criteria_review if c['dimension']=='growth')['status']=='unknown'
