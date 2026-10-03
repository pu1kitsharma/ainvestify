from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agents.discovery.eligibility import Eligibility, eligibility_issue, POLICY, observed_dates
from api.models import WebSourceRequest


def candidate(**updates):
    value={'country':'India','stage':'seed','maturity':'emerging','stage_as_of':'2026-09-01',
        'location_evidence':{'source_block_id':'b1','quote':'Based in India'},
        'stage_evidence':{'source_block_id':'b1','quote':'raised seed funding'},
        'date_evidence':{'source_block_id':'b1','quote':'September 1, 2026'},
        'rationale':'Recent source describes an emerging Indian seed company.'}
    return SimpleNamespace(eligibility=Eligibility.model_validate({**value,**updates}))


BLOCKS={'b1':'Based in India, SyntheticCo raised seed funding on September 1, 2026.'}


def test_only_source_bound_recent_seed_candidate_is_eligible():
    assert eligibility_issue(candidate(),BLOCKS,today=date(2026,9,30)) is None


@pytest.mark.parametrize('update',[{'country':'other'},{'stage':'later'},{'stage':'unknown'},
    {'maturity':'unicorn'},{'maturity':'established'},{'maturity':'listed'},{'maturity':'acquired'}])
def test_mismatched_or_unresolved_company_not_admitted(update):
    assert eligibility_issue(candidate(**update),BLOCKS,today=date(2026,9,30))


def test_date_and_quotes_must_bind_and_not_use_retrieval_date():
    assert eligibility_issue(candidate(stage_as_of='2026-09-30'),BLOCKS)
    assert eligibility_issue(candidate(),{'b1':'Unrelated company'})
    assert eligibility_issue(candidate(),BLOCKS,today=date(2028,9,30))
    assert eligibility_issue(candidate(),BLOCKS,today=date(2025,9,30))
    assert eligibility_issue(SimpleNamespace(),BLOCKS)


def test_later_round_in_stage_quote_cannot_be_labeled_seed():
    quote='raised seed funding before its Series B'
    c=candidate(stage_evidence={'source_block_id':'b2','quote':quote})
    assert eligibility_issue(c,{**BLOCKS,'b2':quote},today=date(2026,9,30))


def test_city_only_location_does_not_establish_indian_operating_base():
    c=candidate(location_evidence={'source_block_id':'b2','quote':'Bengaluru'})
    assert eligibility_issue(c,{**BLOCKS,'b2':'Headquarters: Bengaluru'},today=date(2026,9,30))


def test_dates_do_not_guess_month_or_day():
    assert observed_dates('2026')==set()
    assert observed_dates('1 September 2026')=={date(2026,9,1)}
    assert observed_dates('2026-09-01')=={date(2026,9,1)}


def test_api_scope_and_no_automatic_preparation():
    request=WebSourceRequest(thesis='Fintech')
    assert request.geography is None and request.prepare_workflow is False
    assert WebSourceRequest(thesis='Fintech',geography='Worldwide').geography is None
    assert WebSourceRequest(thesis='Fintech',geography='Brazil').geography=='Brazil'


def test_scoped_discovery_publishes_seed_only_and_records_other_decisions(tmp_path):
    import json
    from agents.discovery.subscription_discovery import source_public_companies
    from agents.discovery.web_sources import Page
    from schemas import WebSourcingRun
    from store import Store
    today=date.today().isoformat()
    page=Page('https://directory.example/','Synthetic portfolio',
        f'Based in India, SeedCo operates payment software and raised seed funding on {today}. '
        'GiantCo operates payment software. UnknownCo operates payment software.')
    class Model:
        name='synthetic-test';last_route={}
        def approve(self,*args):pass
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            assert 'PRE-SEED or SEED' in json.loads(evidence)['public_request']
            companies=[]
            for name,stage in [('SeedCo','seed'),('GiantCo','later'),('UnknownCo','unknown')]:
                eligibility=candidate(stage=stage,stage_as_of=today,
                    date_evidence={'source_block_id':'b1','quote':today}).eligibility.model_dump(mode='json')
                companies.append({'name':name,'page_id':'P1','name_block_id':'b1','entity_type':'company','website':None,
                    'facts':[{'field':'offering','value':'operates payment software','source_block_id':'b1'}],
                    'eligibility':eligibility,'assessment':{'recommendation':'investigate',
                    'rationale':'The source describes payment software. Commercial demand remains unknown.',
                    'strengths':[],'concerns':[],'missing_information':[],'incubation_actions':[],'evidence_ids':['E2']}})
            self.last_response_text=json.dumps({'companies':companies,'coverage_limits':[]})
            return schema.model_validate_json(self.last_response_text)
    with Store(tmp_path/'db') as store:
        run=WebSourcingRun(tenant_id='one',model='synthetic-test',thesis='Fintech',geography='India',seed_urls=[page.url],
            generation_config={'discovery_policy':POLICY})
        result=source_public_companies(store,run,model=Model(),fetcher=SimpleNamespace(fetch=lambda url:page))
        assert [p.name for p in result.company_profiles]==['SeedCo'],result.error
        assert {e['name'] for e in result.generation_config['eligibility_exclusions']}=={'GiantCo','UnknownCo'}
        assert result.company_profiles[0].provenance['eligibility']['stage']=='seed'
