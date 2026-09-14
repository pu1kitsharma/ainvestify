from pathlib import Path
from agents.web_sources import parse_page
from agents.public_directories import startup_directory_urls, directory_profiles
from agents.research_reasoning import geography_conflict

FIXTURES=Path(__file__).parent/'fixtures'/'public_portfolios'


def test_us_and_worldwide_source_sets_are_not_confined_to_yc_or_india():
    for region in ('United States', 'Canada', 'Kenya', None):
        urls=startup_directory_urls('robotics startups',region)
        assert any('antler' in u for u in urls)
        assert any('seedcamp' in u for u in urls)
        assert any('sosv' in u for u in urls)
        assert not any('blume' in u or 'villgro' in u for u in urls)


def test_actual_public_layouts_supply_company_evidence_not_assumed_locations():
    for host in ('www.antler.co','seedcamp.com','sosv.com'):
        page=parse_page('https://'+host+'/',(FIXTURES/(host+'.html')).read_text())
        assert len(page.directory_entries)==3
        profiles=directory_profiles(page,'test','companies')
        assert len(profiles)==3
        assert all(any(e.field=='offering' and e.value in e.quote for e in p.evidence) for p in profiles)
        assert all(any(e.field=='directory_profile' for e in p.evidence) for p in profiles)
        if host=='seedcamp.com':
            assert not any(e.field=='location' for p in profiles for e in p.evidence)


def test_us_alias_keeps_observed_us_cards_and_excludes_uk_cards():
    page=parse_page('https://www.antler.co/portfolio',(FIXTURES/'www.antler.co.html').read_text())
    profiles=directory_profiles(page,'test','companies','United States')
    assert profiles
    for profile in profiles:
        assert next(e.value for e in profile.evidence if e.field=='location')=='US'
        assert not geography_conflict(profile,'United States')


def test_robotics_request_does_not_become_generic_software_automation():
    from agents.public_directories import matches_business
    assert not matches_business('robotics automation artificial intelligence','AI-first automation for Real Estate, starting with Title.')
    assert not matches_business('robotics','Robotic process automation for invoice software')
    assert matches_business('robotics','Autonomous mobile robots for warehouse picking')
    assert matches_business('technology companies','AI-first automation for Real Estate')
