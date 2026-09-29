from agents.discovery.company_identity import same_company,unique_leads,unique_run
from schemas import CompanyProfile,CompanyEvidence,SourcedLead,WebSourcingRun


def profile(name,website='',source='https://directory.example/list',tenant='one'):
    return CompanyProfile(tenant_id=tenant,name=name,website=website,evidence=[CompanyEvidence(field='name',value=name,quote=name+' operates hotels.',source_url=source)])


def test_legal_variants_need_shared_evidence_or_official_host():
    a=profile('Example Corporation',website='https://www.example.test/about')
    b=profile('Example',website='http://example.test/')
    assert same_company(a,b)
    b.website='https://another.test/'
    assert not same_company(a,b)
    b.website=''
    assert same_company(a,b)
    b.evidence[0].source_url='https://other-directory.test/list'
    assert not same_company(a,b)
    assert not same_company(a,profile('Example Holdings',website=a.website))
    assert not same_company(a,profile('Example',website=a.website,tenant='other'))


def test_unresolved_record_cannot_bridge_two_conflicting_namesakes():
    leads=[SourcedLead(tenant_id='one',company_name=p.name,company_id=p.id,company_profile=p) for p in [profile('Example'),profile('Example Inc',website='https://one.test/'),profile('Example Ltd',website='https://two.test/')]]
    assert len(unique_leads(leads))==2
    assert len(leads)==3


def test_historical_duplicate_views_retain_records_and_canonical_references():
    a,b=profile('Example'),profile('Example Corporation',website='https://example.test/')
    leads=[SourcedLead(tenant_id='one',company_name=p.name,company_id=p.id,company_profile=p) for p in (a,b)]
    result=unique_leads(leads)
    assert len(result)==1 and result[0].id==leads[1].id
    assert result[0].related_lead_ids==[leads[0].id]
    run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test',company_ids=[a.id,b.id],lead_ids=[l.id for l in leads],company_profiles=[a,b])
    projected=unique_run(run)
    assert len(projected.lead_ids)==len(projected.company_profiles)==1
    assert len(run.lead_ids)==len(run.company_profiles)==2
    assert all(not l.related_lead_ids for l in leads)


def test_api_deduplicates_historical_batches_without_deleting_originals(tmp_path):
    from api.routers.leads import list_leads,web_run_leads,get_web_run
    from store import Store
    with Store(tmp_path/'db') as store:
        profiles=[profile('Example'),profile('Example Corporation',website='https://example.test/')]
        runs=[]
        for p in profiles:
            lead=SourcedLead(tenant_id='one',company_name=p.name,company_id=p.id,company_profile=p)
            store.save_company(p);store.save_lead(lead)
            run=WebSourcingRun(tenant_id='one',thesis='Hotels',model='test',status='completed',company_ids=[p.id],lead_ids=[lead.id],company_profiles=[p],generation_config={'continuation_of':runs[-1].id} if runs else {})
            store.save_web_run(run);runs.append(run)
        assert len(list_leads(store=store,tenant_id='one'))==1
        combined=web_run_leads(runs[-1].id,store=store,tenant_id='one',include_previous=True)
        assert len(combined)==1 and len(combined[0].related_lead_ids)==1
        assert len(store.list_leads('one'))==2
        assert get_web_run(runs[0].id,store=store,tenant_id='one').lead_ids==runs[0].lead_ids


def test_model_identity_resolution_cites_public_evidence_and_preserves_namesakes(tmp_path):
    import json
    from agents.discovery.company_identity import resolve_profile_identity
    from agents.preparation.preparation_budget import preparation_budget,PreparationBudget
    a=profile('Example',source='https://first.example/list')
    b=profile('Example',source='https://second.example/list')
    for p in (a,b):p.evidence.append(CompanyEvidence(field='offering',value='microbial crop treatments',quote='Example sells microbial crop treatments.',source_url=p.evidence[0].source_url))
    a.evidence.append(CompanyEvidence(field='traction',value='PRIVATE_SENTINEL',quote='PRIVATE_SENTINEL',source_url='local://private',origin='user_upload'))
    class Model:
        name='test';last_route={}
        def approve(self,*args):pass
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            assert 'PRIVATE_SENTINEL' not in evidence
            self.last_response_text=json.dumps({'existing_company_id':b.id,'reason':'Both source records describe the same named microbial crop-treatment business.','candidate_evidence_ids':[a.evidence[1].id],'existing_evidence_ids':[b.evidence[1].id]})
            return schema.model_validate_json(self.last_response_text)
    assert not same_company(a,b)
    with preparation_budget(PreparationBudget(10)):
        found,proof=resolve_profile_identity(a,[b],Model(),[],lambda:None)
    assert found.id==b.id
    a.provenance['identity_resolution']=proof
    assert same_company(a,b)
    proof['attempts'][0]['raw_response']='changed'
    assert not same_company(a,b)
