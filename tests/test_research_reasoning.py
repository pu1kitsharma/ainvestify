"""Semantic query interpretation and evidence requirements, independent of retrieval."""
import json
from unittest.mock import Mock
from schemas import CompanyEvidence, CompanyProfile, WebSourcingRun
from agents.research_reasoning import ResearchPlan, Screening, interpret_brief, screen_candidates

BRIEF = 'find companies in the fintech space in india which are rapidly growing'


def profile(name='Payments Example', location='India'):
    return CompanyProfile(tenant_id='one', name=name, website='', evidence=[
        CompanyEvidence(field=field, value=value, quote=value, source_url='https://company.example/')
        for field,value in [('offering','Digital payments platform'),('location',location),('funding','Raised $10 million in 2026')]])


def plan(run):
    model = Mock(name='model')
    model.name = 'fixture'
    model.generate.return_value = ResearchPlan(interpretation='Indian fintech companies with rapid operating growth',
        sector_terms=['fintech','payments','lending'], criteria=[dict(dimension='sector',requirement='Fintech',evidence_needed='Financial technology offering')],
        queries=['Indian fintech companies'],follow_up_terms=['revenue growth'])
    interpret_brief(run,model)
    return model


def test_natural_request_preserves_growth_and_geography_even_if_model_omits_them():
    run = WebSourcingRun(tenant_id='one',thesis=BRIEF,geography='India',model='fixture')
    model = plan(run)
    assert run.research_plan['status'] == 'model_interpreted'
    assert {c['dimension'] for c in run.research_plan['criteria']} == {'sector','geography','growth'}
    assert json.loads(model.generate.call_args.args[1])['request'] == BRIEF
    assert 'payments' in run.research_plan['sector_terms']


def test_screening_rejects_foreign_geography_and_does_not_turn_funding_into_growth():
    run = WebSourcingRun(tenant_id='one',thesis=BRIEF,geography='India',model='fixture')
    model = plan(run)
    def verdicts(instruction,payload,schema):
        data=json.loads(payload)
        return Screening(candidates=[dict(candidate_id=p['candidate_id'],priority=1,reason='Payment offering merits research',criteria=[
            dict(dimension=c['dimension'],status='supported',reason='Proposed match',evidence_ids=[{'sector':'E1','geography':'E2','growth':'E3'}[c['dimension']]])
            for c in data['plan']['criteria']]) for p in data['candidates']])
    model.generate.side_effect = verdicts
    indian, foreign = profile(), profile('Foreign Payments','England, United Kingdom')
    assert screen_candidates([indian,foreign],run,model) == [indian]
    assert next(c for c in indian.criteria_review if c['dimension']=='growth')['status']=='unknown'
    assert next(c for c in foreign.criteria_review if c['dimension']=='geography')['status']=='mismatch'
    assert any(d.get('decision')=='excluded' for d in run.reasoning_log)


def test_model_sector_screen_and_priority_affect_selection():
    run = WebSourcingRun(tenant_id='one',thesis=BRIEF,geography='India',model='fixture')
    model = plan(run)
    model.generate.side_effect = [Screening(candidates=[dict(candidate_id='P1',priority=3,reason='Offering belongs to logistics',criteria=[
        dict(dimension='sector',status='mismatch',reason='Not financial technology',evidence_ids=['E1'])])]),
        Screening(candidates=[dict(candidate_id='P1',priority=1,reason='Payment business evidenced',criteria=[dict(dimension='sector',status='supported',reason='Payments',evidence_ids=['E1'])])])] 
    wrong, right = profile('Freight Example'), profile()
    wrong.evidence[0].value = wrong.evidence[0].quote = 'Road freight company'
    assert screen_candidates([wrong,right],run,model)==[right]
    assert right.criteria_review[0]['evidence_ids']==[right.evidence[0].id]


def test_unknown_sector_verdict_with_offtopic_offering_is_treated_as_mismatch():
    """Found live on a real 'robotics in India' search: the model wrote
    'AlgoTest is in fintech, not robotics' as its reason but still returned
    status='unknown' instead of 'mismatch' for the sector criterion, and
    cited the trivial `name` field (E2) rather than the real offering (E1)
    it was clearly reasoning about -- an off-sector fintech company then
    survived screening and was returned as a robotics result. This checks
    the candidate's own offering evidence directly (not just what the model
    cited), so it should exclude the company even though the model neither
    said 'mismatch' nor cited the offering evidence itself."""
    run = WebSourcingRun(tenant_id='one',thesis=BRIEF,geography='India',model='fixture')
    model = plan(run)
    model.generate.side_effect = [Screening(candidates=[dict(candidate_id='P1',priority=3,
        reason='AlgoTest is in fintech, not robotics',criteria=[
        dict(dimension='sector',status='unknown',reason='AlgoTest is in fintech, not robotics',evidence_ids=['E2'])])])]
    off_sector = profile('AlgoTest')
    off_sector.evidence[0].value = off_sector.evidence[0].quote = 'Algorithmic options trading platform for retail traders'
    assert screen_candidates([off_sector],run,model) == []
    assert off_sector.criteria_review[0]['status'] == 'mismatch'


def test_unknown_sector_verdict_with_no_offering_evidence_stays_unknown():
    """A genuinely evidence-free candidate must not be swept into the same
    mismatch reclassification -- 'retain unknowns as unknowns' still holds
    when there's no real offering/sector/business_model evidence to judge
    the company's actual business against the requested sector at all."""
    run = WebSourcingRun(tenant_id='one',thesis=BRIEF,geography='India',model='fixture')
    model = plan(run)
    model.generate.side_effect = [Screening(candidates=[dict(candidate_id='P1',priority=3,
        reason='No evidence available',criteria=[
        dict(dimension='sector',status='unknown',reason='No evidence available',evidence_ids=['E2'])])])]
    unknown = profile('Cherries')
    unknown.evidence[0].field = 'other'  # no offering/sector/business_model evidence at all
    assert screen_candidates([unknown],run,model) == [unknown]
    assert unknown.criteria_review[0]['status'] == 'unknown'


def test_failed_batch_preserves_prior_screening_and_reports_unknowns():
    run = WebSourcingRun(tenant_id='one',thesis=BRIEF,geography='India',model='fixture')
    model = plan(run)
    first = Screening(candidates=[dict(candidate_id='P1',priority=1,reason='Payments',criteria=[dict(dimension='sector',status='supported',reason='Payment platform',evidence_ids=['E1'])])])
    model.generate.side_effect = [first,ValueError('invalid output')]
    candidates = [profile(str(i)) for i in range(2)]
    screen_candidates(candidates,run,model)
    assert candidates[0].criteria_review[0]['status']=='supported'
    assert candidates[1].criteria_review[0]['status']=='unknown'
    assert any(d.get('status')=='unavailable' for d in run.reasoning_log)


def test_screening_contract_requires_each_company_criteria_and_observed_citations():
    from agents.research_reasoning import screening_schema
    from pydantic import ValidationError
    import pytest
    schema = screening_schema(['P1'],{'E1','E2'},['sector','geography','growth'])
    with pytest.raises(ValidationError):
        schema.model_validate({'candidates':[]})
    verdict = dict(candidate_id='P1',priority=1,reason='Proposed match',criteria=[dict(dimension=c,status='supported',reason='Source supports',evidence_ids=['invented']) for c in ['sector','geography','growth']])
    with pytest.raises(ValidationError):
        schema.model_validate({'candidates':[verdict]})
    for item in verdict['criteria']: item['evidence_ids']=['E1']
    assert schema.model_validate({'candidates':[verdict]}).candidates[0].candidate_id=='P1'


def test_growth_requires_recent_measured_comparison_not_forecast_or_absolute_count():
    from datetime import datetime, timezone
    from agents.research_reasoning import dated_growth_evidence
    year = datetime.now(timezone.utc).year-1
    def evidence(value):
        return CompanyEvidence(field='traction',value=value,quote=value,source_url='https://company.example/report')
    assert dated_growth_evidence(evidence(f'Revenue grew 40% year-over-year in {year}'))
    assert dated_growth_evidence(evidence(f'Customers grew from 100 to 200 in {year}'))
    assert not dated_growth_evidence(evidence(f'Growth business with 500 customers in {year}'))
    assert not dated_growth_evidence(evidence(f'We target revenue growth of 40% in {year}'))
    assert not dated_growth_evidence(evidence('Revenue grew 40% in 2016'))


def test_assessment_uses_only_its_own_citation_namespace():
    from agents.company_sourcing import AssessmentDraft, assess_profile
    p = profile()
    p.criteria_review=[dict(dimension='sector',requirement='Fintech',status='supported',reason='Payment product',evidence_ids=[p.evidence[0].id])]
    model = Mock(); model.name='fixture'
    def generate(instruction,payload,schema):
        data=json.loads(payload)
        assert 'criteria_review' not in data['COMPANY']
        assert all(e['id'].startswith('C') for e in data['COMPANY']['evidence'])
        assert p.evidence[0].id not in payload
        return schema.model_validate(dict(recommendation='investigate',rationale='Validate operating metrics',evidence_ids=['C1']))
    model.generate.side_effect=generate
    assess_profile(p,BRIEF,'India',model)
    assert p.assessment.evidence_ids==[p.evidence[0].id]
    assert p.assessment.status=='model_proposed'


def test_explicit_source_fields_survive_model_omissions():
    run=WebSourcingRun(tenant_id='one',thesis=BRIEF,geography='India',model='fixture')
    model=plan(run)
    model.generate.return_value=Screening(candidates=[])
    p=profile()
    p.evidence.append(CompanyEvidence(field='sector',value='consumer, fintech, investing',quote='consumer, fintech, investing',source_url='https://company.example/'))
    screen_candidates([p],run,model)
    assert next(c for c in p.criteria_review if c['dimension']=='sector')['status']=='supported'
    geography=next(c for c in p.criteria_review if c['dimension']=='geography')
    assert geography['status']=='supported'
    assert geography['method']=='source_field_check'
    assert geography['evidence_ids']==[p.evidence[1].id]


def test_model_cannot_establish_india_from_name_only_citations():
    run=WebSourcingRun(tenant_id='one',thesis=BRIEF,geography='India',model='fixture')
    model=plan(run)
    model.generate.return_value=Screening(candidates=[dict(candidate_id='P1',priority=1,reason='Proposed match',criteria=[dict(dimension='geography',status='supported',reason='Indian business',evidence_ids=['E1'])])])
    p=profile(location='Location not reported')
    screen_candidates([p],run,model)
    assert next(c for c in p.criteria_review if c['dimension']=='geography')['status']=='unknown'
