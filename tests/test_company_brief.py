import json
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from agents.company_brief import prepare_company_brief, brief_current
from agents.operating_workflow import reconcile_workspace
from tests.test_operating_workflow import company
from store import Store


class BriefModel:
    name = 'fixture'
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail
    def generate(self, instruction, payload, schema):
        data = json.loads(payload)
        if 'grounding' in schema.model_fields:
            from tests.test_preparation_quality import passing_review
            return passing_review(schema,data['draft_fields'])
        self.calls.append(data)
        fields = schema.model_fields
        if 'business' in fields:
            result = dict(business='The company operates hotels serving business travelers.', reason_to_meet='Repeat business stays could be an attractive demand segment to test.', main_risk='Room servicing costs may exceed receipts when occupancy falls.', first_question='Can we examine booking records, repeat stays and room servicing costs?')
        elif 'subject' in fields:
            if self.fail == 'pitch':
                raise ValueError('Bad output')
            result = dict(subject='Testing repeat business stays together', observation='Your company describes operating hotels for travelers.', proposed_help='We could help test repeat business stays and prepare a cohort report showing paid repeat bookings and delivery costs.', meeting_ask='Would you be open to discussing whether this would be useful?')
        else:
            result = dict(priorities=[dict(title=['Validate hotel demand','Examine delivery costs','Explain the funding milestone'][i], why_now='The hotel service claim does not establish repeat paid demand.', required_input='Dated company booking and receipt records.', investor_question='Do business travelers pay for repeat stays?', action='Ask the founder for a dated booking cohort and match repeat stays to collected receipts and direct servicing costs.', output='Paid booking cohort report', done_when='Report repeat demand and cancellations, including an unfavorable result if repeat stays are weak.') for i in range(3)])
        return schema(**result,evidence_ids=[data['evidence'][0]['id']])


def test_brief_creates_real_deliverables_and_reuses_current_results(tmp_path):
    with Store(tmp_path/'db') as store:
        lead = company(store)
        model = BriefModel()
        w = prepare_company_brief(store,lead,model)
        assert brief_current(w)
        assert len(model.calls) == 3
        assert 'We could help' in w.company_brief['pitch']['proposed_help']
        assert w.company_brief['research']['evidence_ids'][0] in {e.id for e in lead.company_profile.evidence}
        assert w.capabilities['external_sending'] is False
        prepare_company_brief(store,lead,model)
        assert len(model.calls) == 3
        assert 'financial_workpaper' in model.calls[0] and 'financial_workpaper' in model.calls[2]
        assert 'research_context' in model.calls[1]
        assert all('source_url' in e and 'retrieved_at' in e and 'origin' in e for e in model.calls[0]['evidence'])
        assert 'team' in model.calls[0]['missing_evidence_categories']
        assert w.company_brief['readiness']['priorities'][0]['title']=='Validate hotel demand'
        assert w.company_brief['readiness']['priorities'][0]['done_when'].startswith('Report repeat demand')
        assert all(w.company_brief[stage]['generation']['input_sha256'] for stage in ['research','pitch','readiness'])


def test_failed_pitch_retains_research_and_retry_resumes(tmp_path):
    with Store(tmp_path/'db') as store:
        lead = company(store)
        with pytest.raises(ValueError):
            prepare_company_brief(store,lead,BriefModel(fail='pitch'))
        w = store.get_workspace('one',lead_id=lead.id)
        assert w.company_brief['research']
        assert not brief_current(w)
        retry = BriefModel()
        w = prepare_company_brief(store,lead,retry)
        assert len(retry.calls) == 2
        assert brief_current(w)


def test_evidence_changes_invalidate_download_and_force_new_brief(tmp_path):
    from api.routers.operations import export_company_brief
    from schemas import CompanyEvidence
    with Store(tmp_path/'db') as store:
        lead = company(store)
        w = prepare_company_brief(store,lead,BriefModel())
        response = export_company_brief(w.id,store,'one')
        assert response.status_code == 200
        assert 'Subject:' in response.body.decode()
        assert 'Source passages' in response.body.decode()
        with pytest.raises(HTTPException) as wrong:
            export_company_brief(w.id,store,'two')
        assert wrong.value.status_code == 404
        lead.company_profile.evidence.append(CompanyEvidence(field='product',value='Hotels',quote='Business hotels',source_url='https://hotel.example/'))
        store.save_lead(lead)
        assert not brief_current(reconcile_workspace(store,lead))
        with pytest.raises(HTTPException) as stale:
            export_company_brief(w.id,store,'one')
        assert stale.value.status_code == 409
        model = BriefModel()
        prepare_company_brief(store,lead,model)
        assert len(model.calls) == 3


def test_unrelated_source_id_is_rejected(tmp_path):
    with Store(tmp_path/'db') as store:
        lead = company(store)
        model = Mock(name='invalid')
        model.name = 'invalid'
        model.generate.return_value = Mock(evidence_ids=['unknown'])
        with pytest.raises(ValueError):
            prepare_company_brief(store,lead,model)
        assert not store.get_workspace('one',lead_id=lead.id).company_brief


def test_known_bad_promotional_and_invented_target_outputs_are_rejected():
    from agents.company_brief import FounderPitch, ResearchBrief, ReadinessPlan, validate_deliverable
    pitch = FounderPitch(subject='Exploring partnership opportunities', observation='The company describes hotel operations for travelers.', proposed_help='We could create a case study showcasing efficiency gains for your customers.', meeting_ask='Would you be open to discussing this proposal?')
    with pytest.raises(ValueError):
        validate_deliverable(pitch,'pitch')
    research = ResearchBrief(business='The company runs a procurement service for hardware teams.', reason_to_meet='A repeated purchase workflow could produce recurring demand.', main_risk='Technology is unproven in a real-world setting and may delay revenue.', first_question='Can we inspect completed purchase records?')
    with pytest.raises(ValueError):
        validate_deliverable(research,'research')
    priority = dict(title='Prove customer demand',investor_question='Will customers pay for repeat service?',action='Examine customer receipts and service costs in company records.',output='A documented cohort and cost report',done_when='The report shows at least 100 customers and 20% growth.')
    with pytest.raises(ValueError):
        validate_deliverable(ReadinessPlan(priorities=[priority]*3),'readiness')


def test_prior_template_contract_is_archived_and_regenerated_by_model(tmp_path):
    from agents.company_brief import VERSION
    with Store(tmp_path/'db') as store:
        lead = company(store)
        w = prepare_company_brief(store,lead,BriefModel())
        w.company_brief['version'] = 2
        store.save_workspace(w,expected_revision=w.revision)
        model = BriefModel()
        done = prepare_company_brief(store,lead,model)
        assert len(model.calls) == 3
        assert done.company_brief_history[-1]['version'] == 2
        assert done.company_brief['version'] == VERSION
        assert brief_current(store.get_workspace('one',lead_id=lead.id))


def test_new_brief_job_does_not_return_old_four_stage_pack(tmp_path):
    from fastapi import BackgroundTasks
    from api.routers.operations import start_brief
    from agents.operating_workflow import prepare_operating_drafts
    from tests.test_operating_workflow import DraftModel
    with Store(tmp_path/'db') as store:
        lead = company(store)
        old = prepare_operating_drafts(store,lead,DraftModel())
        assert old.draft_status == 'draft'
        tasks = BackgroundTasks()
        queued = start_brief(lead.id,tasks,store,'one')
        assert queued.automation.status == 'queued'
        assert len(tasks.tasks)==1
        assert tasks.tasks[0].args[-1] is True
        again = start_brief(lead.id,tasks,store,'one')
        assert again.automation.id == queued.automation.id
        assert len(tasks.tasks)==1


def test_explicit_founder_request_produces_relevant_pitch_without_selling_own_product(tmp_path):
    from schemas import CompanyEvidence
    with Store(tmp_path/'db') as store:
        lead=company(store)
        lead.company_profile.evidence.append(CompanyEvidence(field='founder_ask',value='Intros to corporate travel managers.',quote='Asks: Intros to corporate travel managers. We would love a connect.',source_url='https://hotel.example/'))
        store.save_lead(lead)
        model=BriefModel();workspace=prepare_company_brief(store,lead,model)
        assert len(model.calls)==3
        pitch=workspace.company_brief['pitch']
        assert any(e['field']=='founder_ask' and 'corporate travel managers' in e['passage'] for e in model.calls[1]['evidence'])
        assert pitch['proposed_help'] == 'We could help test repeat business stays and prepare a cohort report showing paid repeat bookings and delivery costs.'
        assert pitch['generation']['kind']=='model_generated'
        assert pitch['meeting_ask']=='Would you be open to discussing whether this would be useful?'


def test_context_covers_categories_deduplicates_and_keeps_prior_employer_scope():
    from agents.company_brief import select_context_facts
    from schemas import CompanyEvidence
    facts=[CompanyEvidence(field='product',value='product',quote='Unique product passage '+str(i),source_url='https://example.test/') for i in range(25)]
    biography=CompanyEvidence(field='customer',value='past experience',quote='Previously built a service for another employer with many customers.',source_url='https://example.test/team')
    facts += [biography,biography.model_copy(update={'field':'team'}),CompanyEvidence(field='market',value='market',quote='Market evidence from another source.',source_url='https://source.test/')]
    chosen=select_context_facts(facts)
    assert any(e.field=='market' for e in chosen)
    assert len([e for e in chosen if e.quote==biography.quote])==1
    assert next(e for e in chosen if e.quote==biography.quote).field=='team'


def test_generic_categories_and_collecting_documents_are_not_completed_analysis():
    from agents.company_brief import ReadinessPlan,validate_deliverable
    base=dict(title='Reconcile delivery costs',why_now='Delivery fees may not cover the work involved.',required_input='Invoices and order-level delivery cost records',investor_question='Do delivery fees cover direct costs?',action='Reconcile order invoices against direct costs and cash receipts.',output='An order-level contribution and collection table',done_when='Company financial statements are available')
    with pytest.raises(ValueError):validate_deliverable(ReadinessPlan(priorities=[base]),'readiness')
    base.update(title='Financials',done_when='Show contribution and unpaid balances, including negative results.')
    with pytest.raises(ValueError):validate_deliverable(ReadinessPlan(priorities=[base]),'readiness')
