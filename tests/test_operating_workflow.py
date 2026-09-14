import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from agents.datasets import SOURCE_BY_ID, dataset_query, fetch_wikidata, snapshot_profiles, parse_company_csv
from agents.operating_workflow import prepare_operating_drafts, reconcile_workspace
from api.main import app
import api.deps as deps
from schemas import CompanyEvidence, CompanyProfile, Deal, MemoVersion, SourcedLead
from store import Store
from workflow_schemas import DatasetRecord, DatasetSnapshot, DraftPack, OperationDraft, PlanTask, WorkspaceAttestation, AnalysisSection


def company(store, tenant="one"):
    p = CompanyProfile(tenant_id=tenant, name="Hotel Example", website="https://hotel.example/", evidence=[
        CompanyEvidence(field="name", value="Hotel Example", quote="Hotel Example", source_url="https://hotel.example/"),
        CompanyEvidence(field="offering", value="operates hotels", quote="Hotel Example operates hotels", source_url="https://hotel.example/"),
    ])
    lead = SourcedLead(tenant_id=tenant, company_id=p.id, company_name=p.name, company_profile=p)
    store.save_company(p)
    store.save_lead(lead)
    return lead


class DraftModel:
    name = "fixture"
    calls = 0
    def generate(self, instruction, evidence, schema):
        self.calls += 1
        data = json.loads(evidence)
        from tests.analysis_fixtures import analytical_fixture
        return analytical_fixture(schema,data['COMPANY']['evidence'][0]['id'])


def test_workspace_runs_internal_work_without_claiming_readiness_or_close(tmp_path):
    with Store(tmp_path / 'db') as store:
        lead = company(store)
        w = reconcile_workspace(store, lead, geography="India", thesis="Hotel operators")
        assert len(w.work_items) == 7
        assert not w.capabilities['external_sending']
        model = DraftModel()
        done = prepare_operating_drafts(store, lead, model)
        again = prepare_operating_drafts(store, lead, model)
        assert model.calls == 4
        assert len(done.drafts) == len(again.drafts) == 4
        assert next(t for t in done.work_items if t.id == 'diligence').status == 'completed'
        assert next(t for t in done.work_items if t.id == 'closing').status == 'blocked'
        assert next(t for t in done.work_items if t.id == 'release').status == 'blocked'
        assert store.get_workspace("two", workspace_id=w.id) is None
        assert store.list_workspaces("two") == []


def test_evidence_changes_invalidate_drafts_and_attestations(tmp_path):
    with Store(tmp_path / 'db') as store:
        lead = company(store)
        w = prepare_operating_drafts(store, lead, DraftModel())
        w.attestations.append(WorkspaceAttestation(kind="identity_review", note="Reviewed company identity in context",
            evidence_ids=[lead.company_profile.evidence[0].id], reviewer="analyst", basis_hash=w.basis_hash))
        store.save_workspace(w, expected_revision=w.revision)
        lead.company_profile.evidence.append(CompanyEvidence(field="location", value="India", quote="India", source_url=lead.company_profile.website))
        store.save_lead(lead)
        updated = reconcile_workspace(store, lead)
        assert updated.draft_status == 'stale'
        assert next(c for c in updated.controls if c.id == 'identity_review').status == 'needs_evidence'
        assert updated.basis_hash != w.basis_hash


def test_workspace_conflicts_do_not_lose_updates(tmp_path):
    with Store(tmp_path / 'db') as store:
        w = reconcile_workspace(store, company(store))
        other = store.get_workspace('one', workspace_id=w.id)
        store.save_workspace(w, expected_revision=w.revision)
        with pytest.raises(ValueError, match="changed"):
            store.save_workspace(other, expected_revision=other.revision)


def test_ambiguous_freshness_requires_review_instead_of_breaking_workspace(tmp_path):
    with Store(tmp_path / 'db') as store:
        lead = company(store)
        lead.company_profile.evidence[0].retrieved_at = '2026-09-13T10:00:00'
        w = reconcile_workspace(store, lead)
        assert next(c for c in w.controls if c.id == 'freshness').status == 'needs_review'


def test_invented_draft_citations_are_rejected(tmp_path):
    class Bad(DraftModel):
        def generate(self, *args):
            pack = super().generate(*args)
            pack.evidence_ids = ["invented"]
            return pack
    with Store(tmp_path / 'db') as store:
        lead = company(store)
        with pytest.raises(ValueError, match="unsupported"):
            prepare_operating_drafts(store, lead, Bad())
        assert not store.get_workspace('one', lead_id=lead.id).drafts


def test_aggregate_and_unlicensed_rows_cannot_become_company_evidence():
    row = DatasetRecord(key="1", values={"company_name": "Fake from totals", "company_website": "https://example.org/"}, source_url="https://dataful.in/datasets/15737/")
    s = DatasetSnapshot(tenant_id="one", source_id="dataful_counts", query="India", records=[row])
    assert snapshot_profiles(s, SOURCE_BY_ID['dataful_counts']) == []
    with pytest.raises(ValueError, match="metadata-only"):
        parse_company_csv("company_name,company_website\nExample,https://example.org/", SOURCE_BY_ID['dataful_startups'])


def test_open_dataset_rows_keep_provenance_and_unknown_dates():
    s = DatasetSnapshot(tenant_id="one", source_id="wikidata_companies", query="India", records=[DatasetRecord(
        key="Q1", values={"company_name": "Hotel Example", "company_website": "https://hotel.example/", "description": "hotel operator"}, source_url="https://www.wikidata.org/wiki/Q1")])
    p = snapshot_profiles(s, SOURCE_BY_ID['wikidata_companies'])[0]
    assert all(e.dataset_id == s.source_id and e.row_key == 'Q1' for e in p.evidence)
    assert all(e.observed_at is None for e in p.evidence)
    assert p.identity_status == 'dataset_reported_unverified'


def test_country_and_sector_constraints_are_not_invented():
    assert 'wd:Q668' in dataset_query('Hoteliers', 'India')
    with pytest.raises(Exception, match='geography'):
        dataset_query('Hotels', 'Atlantis')
    with pytest.raises(Exception, match='mapping'):
        dataset_query('Unspecified', 'India')


def test_dataset_connector_validates_structured_response():
    transport = Mock()
    transport._request.return_value = (200, {}, json.dumps({'results': {'bindings': [{
        'company': {'value': 'http://www.wikidata.org/entity/Q123'}, 'companyLabel': {'value': 'Hotel Example'},
        'website': {'value': 'https://hotel.example/'}, 'description': {'value': 'hotel company'}
    }]}}).encode())
    s = fetch_wikidata('one', 'Hotel companies', 'India', transport)
    assert len(s.records) == 1 and s.content_hash
    assert s.records[0].source_url.endswith('/wiki/Q123')
    global_snapshot = fetch_wikidata('one', 'Hotel companies', 'global', transport)
    assert global_snapshot.records[0].values['country'] == 'Not specified'


def test_api_rejects_cross_tenant_review_and_unauthorized_execution(tmp_path):
    path = tmp_path / 'db'
    with Store(path) as store:
        lead = company(store)
        w = reconcile_workspace(store, lead)
    def db():
        with Store(path) as s: yield s
    app.dependency_overrides[deps.get_store] = db
    app.dependency_overrides[deps.get_tenant_id] = lambda: 'one'
    try:
        client = TestClient(app)
        assert client.get('/api/operations/datasets').status_code == 200
        assert client.post(f'/api/operations/workspaces/{w.id}/execute/send').status_code == 409
        body = {'kind': 'funds_received', 'note': 'Funds confirmed from name alone', 'evidence_ids': [lead.company_profile.evidence[0].id], 'expected_revision': w.revision}
        assert client.post(f'/api/operations/workspaces/{w.id}/attestations', json=body).status_code == 422
        body['kind'] = 'identity_review'
        body['evidence_ids'] = ['other-tenant-evidence']
        assert client.post(f'/api/operations/workspaces/{w.id}/attestations', json=body).status_code == 422
        app.dependency_overrides[deps.get_tenant_id] = lambda: 'two'
        assert client.get('/api/operations/workspaces').json() == []
        assert client.post(f'/api/operations/workspaces/{w.id}/attestations', json=body).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_teaser_release_uses_current_workspace_and_cannot_cross_deals(tmp_path):
    path = tmp_path / 'db'
    with Store(path) as store:
        lead = company(store)
        deal = Deal(tenant_id='one', name=lead.company_name)
        store.save_deal(deal)
        lead.promoted_deal_id = deal.id
        store.save_lead(lead)
        w = prepare_operating_drafts(store, lead, DraftModel())
        memo = MemoVersion(tenant_id='one', deal_id=deal.id, version_number=1,
                           content_uri='unused.md', document_type='teaser')
        store.save_memo_version(memo)
        other = Deal(tenant_id='one', name='Other company')
        store.save_deal(other)

    def db():
        with Store(path) as s: yield s
    app.dependency_overrides[deps.get_store] = db
    app.dependency_overrides[deps.get_tenant_id] = lambda: 'one'
    app.dependency_overrides[deps.get_reviewer] = lambda: 'analyst'
    try:
        client = TestClient(app)
        confirm_url = f'/api/deals/{deal.id}/compile/teaser/{memo.id}/confirm'
        response = client.post(confirm_url, json={'confirmed': True})
        assert response.status_code == 409
        assert 'release checks' in response.json()['detail']
        assert client.post(f'/api/deals/{other.id}/compile/teaser/{memo.id}/confirm', json={'confirmed': True}).status_code == 404
        assert client.post(confirm_url, json={'confirmed': False}).status_code == 200

        # Simulate reviews already validated by the attestation boundary. The
        # release endpoint must accept satisfied dependencies, not block forever.
        with Store(path) as store:
            w = store.get_workspace('one', workspace_id=w.id)
            kinds = ['source_rights_review', 'identity_review', 'engagement_authority', 'regulatory_scope',
                     'privacy_basis', 'commercial_validation', 'financial_review', 'incubation_outcomes',
                     'release_approval']
            w.attestations = [WorkspaceAttestation(kind=kind, note='Supporting review recorded for this fixture',
                evidence_ids=[lead.company_profile.evidence[0].id], reviewer='analyst', basis_hash=w.basis_hash) for kind in kinds]
            store.save_workspace(w, expected_revision=w.revision)
        approved = client.post(confirm_url, json={'confirmed': True})
        assert approved.status_code == 200
        assert approved.json()['approved_by'] == 'analyst'
        assert approved.json()['approval_basis_hash'] == w.basis_hash
        latest_url = f'/api/deals/{deal.id}/documents/latest?document_type=teaser'
        assert client.get(latest_url).json()['approved_by'] == 'analyst'

        with Store(path) as store:
            lead.company_profile.evidence.append(CompanyEvidence(field='location', value='India', quote='India', source_url=lead.company_profile.website))
            store.save_lead(lead)
        assert client.get(latest_url).json()['approved_by'] is None
        assert client.get(f'/api/deals/{deal.id}/documents').json()[0]['approved_by'] is None
        assert client.post(confirm_url, json={'confirmed': True}).status_code == 409
        with Store(path) as store:
            assert store.get_memo_version('one', memo.id).approved_by == 'analyst'  # Historical review retained.
    finally:
        app.dependency_overrides.clear()


def test_background_ai_job_persists_progress_result_and_tenant_scope(tmp_path, monkeypatch):
    import api.routers.operations as routes
    import agents.operating_workflow as workflow
    path = tmp_path / 'jobs.db'
    with Store(path) as store:
        lead = company(store)
    def database():
        with Store(path) as store: yield store
    original = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_store] = database
    app.dependency_overrides[deps.get_tenant_id] = lambda: 'one'
    monkeypatch.setattr(routes, 'LocalModel', DraftModel)
    monkeypatch.setattr('agents.operating_research.research_company', lambda store, lead, model, **kwargs: lead)
    try:
        client = TestClient(app)
        response = client.post(f'/api/operations/leads/{lead.id}/prepare-jobs')
        assert response.status_code == 202
        assert response.json()['automation']['status'] == 'queued'
        workspace = client.get('/api/operations/workspaces').json()[0]
        assert workspace['automation']['status'] == 'completed'
        assert len(workspace['drafts']) == 4
        assert workspace['automation']['completed_at']
        assert not workspace['capabilities']['external_sending']
        assert routes.MODEL_JOB_SLOT.acquire(blocking=False)
        routes.MODEL_JOB_SLOT.release()
        # A repeated request with current evidence reuses the completed work.
        again = client.post(f'/api/operations/leads/{lead.id}/prepare-jobs')
        assert again.json()['automation']['id'] == workspace['automation']['id']
        app.dependency_overrides[deps.get_tenant_id] = lambda: 'two'
        assert client.post(f'/api/operations/leads/{lead.id}/prepare-jobs').status_code == 404
        assert client.get('/api/operations/workspaces').json() == []
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


def test_background_ai_failure_and_restart_are_visible_and_retryable(tmp_path, monkeypatch):
    import api.routers.operations as routes
    path = tmp_path / 'failure.db'
    with Store(path) as store:
        lead = company(store)
    def database():
        with Store(path) as store: yield store
    def fail(*args):
        raise ValueError('Draft evidence failed validation')
    original = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_store] = database
    app.dependency_overrides[deps.get_tenant_id] = lambda: 'one'
    monkeypatch.setattr(routes, 'prepare_operating_drafts', fail)
    monkeypatch.setattr('agents.operating_research.research_company', lambda store, lead, model, **kwargs: lead)
    try:
        client = TestClient(app)
        assert client.post(f'/api/operations/leads/{lead.id}/prepare-jobs').status_code == 202
        failed = client.get('/api/operations/workspaces').json()[0]
        assert failed['automation']['status'] == 'failed'
        assert failed['automation']['error'] == 'Draft evidence failed validation'
        assert failed['drafts'] == []
        assert client.post(f'/api/operations/leads/{lead.id}/prepare-jobs').status_code == 202
        with Store(path) as store:
            w = store.get_workspace('one', lead_id=lead.id)
            w.automation.status = 'running'
            w.automation.worker_id = 'previous-process'
            store.save_workspace(w, expected_revision=w.revision)
        assert client.get('/api/operations/workspaces').json()[0]['automation']['status'] == 'interrupted'
        assert routes.MODEL_JOB_SLOT.acquire(blocking=False)
        routes.MODEL_JOB_SLOT.release()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


def test_generic_tasks_cannot_replace_substantive_analysis(tmp_path):
    class Generic(DraftModel):
        def generate(self, instruction, evidence, schema):
            return OperationDraft(stage='diligence', title='Generic', actions=['Review this company'])
    with Store(tmp_path/'db') as store:
        lead=company(store)
        with pytest.raises(ValueError): prepare_operating_drafts(store,lead,Generic())
        assert not store.get_workspace('one',lead_id=lead.id).drafts


def test_legacy_plans_are_updated_to_actionable_task_format(tmp_path):
    with Store(tmp_path / 'db') as store:
        lead = company(store)
        old = prepare_operating_drafts(store, lead, DraftModel())
        old.draft_schema_version = 1
        for draft in old.drafts: draft.tasks = []
        store.save_workspace(old, expected_revision=old.revision)
        assert reconcile_workspace(store, lead).draft_status == 'stale'
        model = DraftModel()
        updated = prepare_operating_drafts(store, lead, model)
        assert model.calls == 4
        assert updated.draft_schema_version == 4
        assert all(d.tasks[0].deliverable and d.tasks[0].success_measure for d in updated.drafts)


def test_generation_contract_requires_business_answers_and_citations():
    from agents.business_analysis import analysis_schema
    from pydantic import ValidationError
    schema=analysis_schema('incubation',{'C2'})
    definition=schema.model_json_schema()
    assert 'primary_metric' in definition['required']
    assert 'user_and_budget_owner' in definition['required']
    assert definition['properties']['evidence_ids']['items']['const']=='C2'
    with pytest.raises(ValidationError): schema.model_validate({'evidence_ids':['C1']})


def test_failed_stage_keeps_valid_plans_and_retry_only_generates_missing_stages(tmp_path):
    class Partial(DraftModel):
        def generate(self, instruction, evidence, schema):
            if 'use_of_funds_question' in schema.model_fields:
                raise ValueError('simulated bad model output')
            return super().generate(instruction,evidence,schema)
    with Store(tmp_path / 'partial.db') as store:
        lead = company(store)
        with pytest.raises(ValueError, match='documents plan could not be validated'):
            prepare_operating_drafts(store,lead,Partial())
        partial = reconcile_workspace(store,lead)
        assert partial.draft_status == 'partial'
        assert [d.stage for d in partial.drafts] == ['diligence','incubation']
        original = [d.model_dump() for d in partial.drafts]
        retry = DraftModel()
        done = prepare_operating_drafts(store,lead,retry)
        assert retry.calls == 2
        assert [d.model_dump() for d in done.drafts[:2]] == original
        assert done.draft_status == 'draft'
        assert len(done.drafts) == 4


def test_queue_accepts_busy_model_deduplicates_and_reuses_current_packs(tmp_path):
    from fastapi import BackgroundTasks
    import api.routers.operations as routes
    with Store(tmp_path / 'queue.db') as store:
        lead = company(store)
        background = BackgroundTasks()
        assert routes.MODEL_JOB_SLOT.acquire(blocking=False)
        try:
            queued = routes.start_prepare(lead.id,background,store,'one')
            duplicate = routes.start_prepare(lead.id,background,store,'one')
            assert queued.automation.id == duplicate.automation.id
            assert queued.automation.status == 'queued'
            assert len(background.tasks)==1
        finally:
            routes.MODEL_JOB_SLOT.release()
        # Independent company with an already-current pack needs no model slot.
        current = company(store,'two')
        prepare_operating_drafts(store,current,DraftModel())
        assert routes.MODEL_JOB_SLOT.acquire(blocking=False)
        try:
            response = routes.start_prepare(current.id,BackgroundTasks(),store,'two')
            assert response.draft_status == 'draft'
        finally:
            routes.MODEL_JOB_SLOT.release()


def test_prompt_upgrade_replaces_all_stages_and_keeps_instructions_stage_specific(tmp_path):
    class Scoped(DraftModel):
        def generate(self,instruction,evidence,schema):
            if 'product_description' in schema.model_fields:
                assert 'investor narrative' in instruction
                assert 'Design ONE lean paid pilot' not in instruction
            return super().generate(instruction,evidence,schema)
    with Store(tmp_path / 'version.db') as store:
        lead = company(store)
        old = prepare_operating_drafts(store,lead,DraftModel())
        old.draft_schema_version = 2
        store.save_workspace(old,expected_revision=old.revision)
        model = Scoped()
        updated = prepare_operating_drafts(store,lead,model)
        assert model.calls==4
        assert updated.draft_schema_version==4
