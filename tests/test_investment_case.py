import json
import pytest
from fastapi import HTTPException,BackgroundTasks
from store import Store
from tests.test_operating_workflow import company
from agents.investment_case import prepare_investment_case,case_current
from agents.operating_workflow import reconcile_workspace
from schemas import CompanyEvidence

class Model:
 name='fixture'
 def __init__(self,decision='proceed',fail=None):self.calls=[];self.decision=decision;self.fail=fail
 def generate(self,instruction,payload,schema):
  data=json.loads(payload)
  if 'grounding' in schema.model_fields:
   from tests.test_preparation_quality import passing_review
   return passing_review(schema,data['draft_fields'])
  self.calls.append(data)
  if 'maturity' in schema.model_fields and 'decision' not in schema.model_fields:
   return schema(maturity='early_business',evidence_ids=['E1'])
  if 'decision' in schema.model_fields:
   return schema(decision=self.decision,maturity="early_business",maturity_source_id="E1",support_request_id="not_observed",business_source_id='E1',rationale='The source describes the company business. An engagement should be based on its actual customer demand and operating economics.',next_action='Source other companies whose business and maturity fit the incubation engagement.' if self.decision=='do_not_pursue' else 'Confirm the engagement scope with the company before starting external outreach.',evidence_ids=['E1'])
  if self.fail and len(self.calls)>=self.fail:raise ValueError('model unavailable')
  return schema(decision_question='Do repeat paid stays cover servicing costs?',next_action='Request booking receipts and itemized servicing costs from the company.',completion_test='Compare receipts with servicing costs and report cancellations and loss-making stays.',title='Business hotel investment decision memo',purpose='Assess whether repeated business stays support a viable hotel operation.',sections=[dict(heading='Commercial hypothesis',content='The company describes operating hotels. Repeat business stays could support demand, but paid booking and customer cohort records are needed to test this hypothesis.'),dict(heading='Test the economics',content='Reconcile room receipts with the direct cost of servicing occupied rooms. The result should show loss-making stays and cancellations as well as repeat bookings.')],missing_inputs=[dict(record='Dated bookings, cancellations and receipts',why='These records distinguish paid repeat demand from a general description of hotel services.')],evidence_ids=['E1'])

def test_mismatch_stops_generation_before_incubation_and_keeps_legacy_drafts(tmp_path):
 with Store(tmp_path/'db') as s:
  lead=company(s);w=reconcile_workspace(s,lead);w.company_brief={'version':4,'readiness':{'priorities':['legacy']}};s.save_workspace(w,expected_revision=w.revision)
  m=Model('do_not_pursue');w=prepare_investment_case(s,lead,m)
  assert len(m.calls)==2
  assert w.investment_case['products']=={}
  assert w.investment_case['fit']['decision']=='do_not_pursue'
  assert w.company_brief['version']==4
  assert case_current(w)
  assert w.capabilities['external_sending'] is False

def test_actual_work_products_saved_and_partial_retry_skips_completed_work(tmp_path):
 with Store(tmp_path/'db') as s:
  lead=company(s)
  prepare_investment_case(s,lead,Model(fail=4))
  w=s.get_workspace('one',lead_id=lead.id)
  assert len(w.investment_case['products'])==1
  assert w.investment_case['status']=='partial'
  assert set(w.investment_case['stage_errors'])=={'commercial_test','funding_outline'}
  m=Model();w=prepare_investment_case(s,lead,m)
  assert len(m.calls)==2
  assert len(w.investment_case['products'])==3
  assert w.investment_case['status']=='complete'
  assert len(w.investment_case['products']['investment_case']['sections'][0]['content'])>80

def test_evidence_invalidation_and_scoped_download(tmp_path):
 from api.routers.operations import export_investment_case
 with Store(tmp_path/'db') as s:
  lead=company(s);w=prepare_investment_case(s,lead,Model())
  assert 'Commercial hypothesis' in export_investment_case(w.id,s,'one').body.decode()
  with pytest.raises(HTTPException) as wrong:export_investment_case(w.id,s,'other')
  assert wrong.value.status_code==404
  lead.company_profile.evidence.append(CompanyEvidence(field='customer',value='business travelers',quote='Business travelers use these hotels.',source_url='https://hotel.example/'));s.save_lead(lead)
  with pytest.raises(HTTPException) as stale:export_investment_case(w.id,s,'one')
  assert stale.value.status_code==409
  done=prepare_investment_case(s,lead,Model())
  assert len(done.investment_case_history)==1

def test_readiness_queue_does_not_reuse_legacy_brief_and_is_idempotent(tmp_path):
 from api.routers.operations import start_readiness
 with Store(tmp_path/'db') as s:
  lead=company(s);tasks=BackgroundTasks()
  w=start_readiness(lead.id,tasks,s,'one')
  assert len(tasks.tasks)==1 and tasks.tasks[0].kwargs['readiness'] is True
  assert start_readiness(lead.id,tasks,s,'one').automation.id==w.automation.id
  assert len(tasks.tasks)==1


def test_unresolved_fit_produces_screening_memo_without_fundraising_materials(tmp_path):
 with Store(tmp_path/'db') as s:
  m=Model('clarify');w=prepare_investment_case(s,company(s),m)
  assert len(m.calls)==3
  assert set(w.investment_case['products'])=={'investment_case'}
  assert 'operating_metrics' not in m.calls[0]
  assert 'missing' not in m.calls[2]['operating_metrics']
  assert 'geography' not in m.calls[0]


def test_company_type_must_be_grounded_in_cited_company_text(tmp_path):
 class Ungrounded(Model):
  def generate(self,instruction,payload,schema):
   result=super().generate(instruction,payload,schema)
   result.evidence_ids=['E999']
   return result
 with Store(tmp_path/'db') as s:
  lead=company(s)
  with pytest.raises(ValueError,match='Unsupported source citation'):prepare_investment_case(s,lead,Ungrounded())
  case=s.get_workspace('one',lead_id=lead.id).investment_case
  assert not case.get('eligibility') and not case.get('products')
  assert len(case['validation_attempts'])==2


def test_revision_receives_rejected_document_and_specific_feedback(tmp_path):
 class Revising(Model):
  def generate(self,instruction,payload,schema):
   result=super().generate(instruction,payload,schema)
   if 'sections' in schema.model_fields:
    data=json.loads(payload)
    if 'draft_to_revise' not in data:
     result.purpose='The company has 999 paying customers and substantial growth.'
    else:
     assert '999' in data['draft_to_revise']['purpose']
     assert 'purpose' in data['revision_feedback']
   return result
 with Store(tmp_path/'db') as s:
  w=prepare_investment_case(s,company(s),Revising())
  assert w.investment_case['status']=='complete'
  assert len(w.investment_case['validation_attempts'])==3
  assert all('999' not in p['purpose'] for p in w.investment_case['products'].values())


def test_schema_invalid_final_answer_is_also_supplied_for_repair(tmp_path):
 class SchemaRepair(Model):
  def generate(self,instruction,payload,schema):
   result=super().generate(instruction,payload,schema)
   if 'sections' in schema.model_fields:
    data=json.loads(payload)
    if 'draft_to_revise' not in data:
     broken=result.model_dump();broken['missing_inputs'][0]['record']='ARR'
     self.last_response_text=json.dumps(broken)
     return schema.model_validate_json(self.last_response_text)
    assert 'ARR' in data['draft_to_revise']
    assert 'missing_inputs.0.record' in data['revision_feedback']
   return result
 with Store(tmp_path/'db') as s:
  w=prepare_investment_case(s,company(s),SchemaRepair())
  assert w.investment_case['status']=='complete'
  assert len(w.investment_case['validation_attempts'])==3


def test_absence_of_public_fundraising_request_is_not_a_negative_fact():
 from agents.investment_case import FitDecision,validate_fit
 with pytest.raises(ValueError,match='does not prove'):
  validate_fit(FitDecision(decision='clarify',business_source_id='E1',rationale='This business is not currently preparing for investment and fundraising, according to the missing public request.',next_action='Ask the founders about their current financing objectives.'))


def test_preparation_rejects_generic_record_requests_and_reversed_advisor_role():
 from agents.investment_case import FitDecision,WorkProduct,validate_fit,validate_product
 with pytest.raises(ValueError,match='ARE the accelerator'):
  validate_fit(FitDecision(decision='proceed',maturity='early_business',maturity_source_id='E1',rationale='The source shows a specific business problem that deserves a founder conversation about paid demand.',next_action='Engage an accelerator to prepare this company for fundraising.'))
 p=WorkProduct(decision_question='Does delivery leave a margin?',next_action='Request the operating records.',completion_test='Reconcile receipts and costs, including losses.',title='Company preparation memo',purpose='Resolve whether the documented business can earn sustainable revenue.',sections=[dict(heading='Business question',content='Confirm what the customer pays the company and reconcile that amount to the cost of delivering the service.')]*2,missing_inputs=[dict(record='operating_metrics',why='These would be used to assess the business and its investment readiness.')])
 with pytest.raises(ValueError,match='actual record'):validate_product(p)


def test_established_company_without_support_request_cannot_proceed():
 from agents.investment_case import FitDecision,validate_fit
 with pytest.raises(ValueError,match='Proceed requires'):
  validate_fit(FitDecision(decision='proceed',maturity='established_business',maturity_source_id='observed-history',rationale='The company markets innovative services and has a long operating history in its industry.',next_action='Schedule a conversation to develop a startup incubation plan.'))
 validate_fit(FitDecision(decision='clarify',maturity='established_business',maturity_source_id='observed-history',rationale='The company is established and no engagement objective has been confirmed for this transaction.',next_action='Confirm whether a specific company or subsidiary is seeking fundraising preparation.'))


def test_maturity_constrains_decision_schema_and_survives_fit_failure(tmp_path):
 class Established(Model):
  def generate(self,instruction,payload,schema):
   if 'decision' in schema.model_fields:
    assert set(schema.model_json_schema()['properties']['decision']['enum'])=={'clarify','do_not_pursue'}
    if self.fail:raise ValueError('temporary fit failure')
   result=super().generate(instruction,payload,schema)
   if 'maturity' in schema.model_fields:result.maturity='established_business'
   return result
 with Store(tmp_path/'db') as s:
  lead=company(s)
  with pytest.raises(ValueError):prepare_investment_case(s,lead,Established('do_not_pursue',fail=True))
  w=s.get_workspace('one',lead_id=lead.id)
  assert w.investment_case['eligibility']['maturity']=='established_business'
  assert not w.investment_case.get('fit')
  model=Established('do_not_pursue');w=prepare_investment_case(s,lead,model)
  assert len(model.calls)==1
  assert w.investment_case['fit']['decision']=='do_not_pursue'
