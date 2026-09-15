import json
import pytest
from store import Store
from tests.test_operating_workflow import company
from agents.analyst_pack import prepare_section_pack as prepare_analyst_pack, bound_review, SectionReview, Paragraph, export_pack
from agents.operating_workflow import reconcile_workspace
from schemas import CompanyEvidence
from tests.test_measurement_plan import contribution_plan, cohort_plan

def test_one_agenda_drives_distinct_requests_and_the_founder_offer(tmp_path):
 with Store(tmp_path/'db') as s:
  model=Model();w=prepare_analyst_pack(s,company(s),model)
  questions=w.analyst_pack['agenda']['questions']
  assert len({q['dimension'] for q in questions})==2
  for index,suffix in enumerate(('a','b')):
   assert w.analyst_pack['sections']['diligence.request_'+suffix]['content']['question']==questions[index]['question']
  proposal=next(payload for _,payload in model.calls if 'previous_sections' in payload and 'readiness.action_a' in payload['previous_sections'])
  assert proposal['previous_sections']['readiness.action_a']['output'].startswith('A source-linked')
  assert 'diligence.request_a' in proposal['previous_sections']
  assert w.analyst_pack['sections']['founder.proposal']['dependency']=='readiness.action_a'


def test_agenda_cannot_split_unit_economics_into_duplicate_dimensions():
 from types import SimpleNamespace
 from agents.analyst_pack import InvestmentQuestionPlan,validate_agenda
 q=InvestmentQuestionPlan(dimension='unit_economics',question='Do customer payments cover the costs of delivery?',why_it_matters='Negative contribution would weaken the expansion case.',fact_ids=['f'])
 with pytest.raises(ValueError,match='distinct'):
  validate_agenda(SimpleNamespace(questions=[q,q]),[{'id':'f'}])


def test_bad_source_claim_does_not_discard_other_valid_claims(tmp_path):
 class Partial(Model):
  def generate(self,instruction,evidence,schema):
   payload=json.loads(evidence)
   if 'passages' in payload:
    self.calls.append((instruction,payload))
    if 'claims_to_correct' in payload:return schema(facts=[])
    row=payload['passages'][0]
    from types import SimpleNamespace
    return schema.model_construct(facts=[schema.model_fields['facts'].annotation.__args__[0].model_construct(passage_id=pid,category=category,subject='target') for pid,category in [(row['passage_id'],'offering'),('invented_passage','traction')]])
   return super().generate(instruction,evidence,schema)
 with Store(tmp_path/'db') as s:
  model=Partial();w=prepare_analyst_pack(s,company(s),model)
  assert w.analyst_pack['status']=='complete'
  assert [f['quote'] for f in w.analyst_pack['record']['facts']]==['Hotel Example operates hotels']
  correction=next(p for _,p in model.calls if 'claims_to_correct' in p)
  assert len(correction['claims_to_correct'])==1

def test_citation_formatting_removes_only_redundant_bound_ids():
 from agents.analyst_pack import Economics,attach_citations_in_code,validate_section
 draft=Economics(revenue_mechanism='Customers pay brokerage fees on trades. Source: fact_one, fact_two',unknown_economics='Actual billing records are needed to establish retained revenue. fact_ids: fact_two',fact_ids=['fact_one','fact_two'])
 fixed=attach_citations_in_code(draft)
 assert fixed.revenue_mechanism=='Customers pay brokerage fees on trades.'
 assert fixed.unknown_economics=='Actual billing records are needed to establish retained revenue.'
 assert fixed.fact_ids==draft.fact_ids
 draft.revenue_mechanism='Customers pay fees. Source: fact_one, invented_id'
 assert attach_citations_in_code(draft).revenue_mechanism==draft.revenue_mechanism
 with pytest.raises(ValueError):validate_section(draft,[{'id':'fact_one','quote':'Customers pay fees.'},{'id':'fact_two','quote':'Billing records.'}])

def test_atomic_claims_keep_product_and_administration_separate():
 from types import SimpleNamespace
 from agents.analyst_pack import SourceClaim,bind_source_claims,section_facts
 text='We sell irrigation systems to farms. Account opening requires identity documents. Our systems promise effortless growth.'
 passage={'passage_id':'P1','id':'source1','quote':text,'source_url':'https://example.test/product','retrieved_at':'2026-09-14','observed_at':None,'origin':'public_page'}
 selection=SimpleNamespace(facts=[SourceClaim(passage_id='P1',quote=quote,category=category,subject='target') for quote,category in [('We sell irrigation systems to farms.','offering'),('Account opening requires identity documents.','operations'),('Our systems promise effortless growth.','marketing')]])
 facts=bind_source_claims(selection,[passage])
 assert len(facts)==3
 assert all(f['source_url']==passage['source_url'] and f['retrieved_at']==passage['retrieved_at'] for f in facts)
 assert [f['quote'] for f in section_facts(facts,'diligence','request_a')]==[text]
 assert facts[0]['selected_quote']=='We sell irrigation systems to farms.'
 assert section_facts([facts[1]],'research','business')==[]
 for fact in facts:
  assert text[fact['source_span_start']:].startswith(fact['quote'])


def test_atomic_claims_reject_paraphrases_and_bind_only_unique_exact_sources():
 from types import SimpleNamespace
 from agents.analyst_pack import SourceClaim,bind_source_claims
 p={'passage_id':'P1','id':'a','quote':'The founder previously built factory equipment.','source_url':'https://example.test/team','retrieved_at':'2026-09-14','observed_at':None,'origin':'public_page'}
 def selection(quote,pid='P1'):
  return SimpleNamespace(facts=[SourceClaim(passage_id=pid,quote=quote,category='founder_history',subject='founder')])
 with pytest.raises(ValueError):bind_source_claims(selection('The company sells factory equipment.'),[p])
 with pytest.raises(ValueError):bind_source_claims(selection('The founder ... built factory equipment.'),[p])
 fact=bind_source_claims(selection(p['quote'],'P9'),[p])[0]
 assert fact['source_id']=='a' and fact['subject']=='founder'
 with pytest.raises(ValueError):bind_source_claims(selection(p['quote'],'P9'),[p,{**p,'passage_id':'P2','id':'b'}])

class Model:
 name='fixture'
 last_route={}
 def __init__(self,fail=None,bad_review=False):self.calls=[];self.fail=fail;self.bad_review=bad_review
 def generate(self,instruction,evidence,schema):
  p=json.loads(evidence);self.calls.append((instruction,p))
  if 'passages' in p:
   source=p['passages'][0]
   return schema(facts=[{'passage_id':row['passage_id'],'quote':row['text'],'category':'offering','subject':'target'} for row in p['passages']])
  if 'verdict' in schema.model_fields:
   if self.bad_review:
    item=schema.model_fields['objections'].annotation.__args__[0].model_construct(passage_id='invented_passage',basis_id='task',correction='The question needs more detail.')
    return schema.model_construct(verdict='revise',objections=[item])
   return schema(verdict='pass',objections=[])
  ids=[p['evidence_record'][0]['id']]
  if 'questions' in schema.model_fields:
   return schema(questions=[{'dimension':'unit_economics','question':'Do collected room fees cover servicing costs and cancellations?','why_it_matters':'Negative room contribution would undermine expansion economics.','fact_ids':ids},{'dimension':'customer_demand','question':'Do guests book repeat stays across successive operating periods?','why_it_matters':'Demand may depend on one-off guests rather than repeat bookings.','fact_ids':ids}])
  if self.fail and self.fail in instruction:raise ValueError('temporary section failure')
  if 'reported_observation' in schema.model_fields:
   return schema(reported_observation='Your website describes hotels serving business guests.',question_to_explore='How do repeat bookings contribute after cancellations and servicing costs?',fact_ids=ids)
  if 'revenue_mechanism' in schema.model_fields:
   return schema(revenue_mechanism='The company describes room fees paid by guests for overnight stays.',unknown_economics='Booking receipts and servicing invoices are needed to establish contribution.',fact_ids=ids)
  if 'reason_to_engage' in schema.model_fields:
   return schema(reason_to_engage='Repeat paid stays could justify research if receipts cover delivery costs.',unresolved_risk='Servicing and cancellation costs could consume the room receipts.',next_decision='Assess contribution including loss-making stays before proposing expansion.',fact_ids=ids)
  if 'proposed_work' in schema.model_fields:
   return schema(proposed_work='We could prepare a booking and servicing-cost reconciliation to discuss with your team.',invitation='Would you be open to discussing that reconciliation with us?',fact_ids=ids)
  if 'question' in schema.model_fields:
   return schema(analysis_plan=cohort_plan() if p.get('investment_question',{}).get('dimension')=='customer_demand' else contribution_plan(),question=p.get('investment_question',{}).get('question','Can you share the dated booking receipts and room servicing ledger?'),records_to_request='Booking receipts, refunds and room servicing invoices covering the same operating period.',decision='Establish whether paid room receipts cover direct servicing costs, including cancellations.',fact_ids=ids)
  if 'required_input' in schema.model_fields:
   return schema(required_input='Booking receipts and room servicing invoices from the requested period.',action='Reconcile receipts and refunds against direct servicing costs for the same stays.',output='A reconciliation table and explanation of loss-making stays.',decision='Report contribution for the supplied stays, including losses and missing cost allocations.',fact_ids=ids)
  return schema(text='The company describes operating hotels. Repeat paid stays could justify further research, but booking receipts and servicing records are needed to establish whether those stays leave a contribution.',fact_ids=ids)


def test_sections_persist_independently_and_resume_only_failures(tmp_path):
 with Store(tmp_path/'db') as s:
  l=company(s);m=Model(fail='who pays')
  w=prepare_analyst_pack(s,l,m)
  assert w.analyst_pack['status']=='partial'
  assert len([v for v in w.analyst_pack['sections'].values() if v['status']=='complete'])==8
  before=w.analyst_pack['sections']['research.business']
  retry=Model();w=prepare_analyst_pack(s,l,retry)
  assert len(retry.calls)==4  # Economics and its decision; unchanged downstream prose remains saved.
  assert w.analyst_pack['sections']['research.business']==before
  assert w.analyst_pack['status']=='complete'
  assert all(f['source_id'] and f['retrieved_at'] for f in w.analyst_pack['record']['facts'])
  assert 'pricing' in w.analyst_pack['record']['unknowns']
  assert 'Booking receipts' in export_pack(w.analyst_pack,'diligence')


def test_unbound_review_does_not_rewrite_candidate_or_publish_it(tmp_path):
 with Store(tmp_path/'db') as s:
  l=company(s);m=Model(bad_review=True);w=prepare_analyst_pack(s,l,m)
  assert w.analyst_pack['sections']['research.business']['status']=='review_failed'
  assert len([p for i,p in m.calls if 'text' not in p and 'evidence_record' in p and 'repair' not in p])==7
  assert 'The company describes operating hotels.' not in export_pack(w.analyst_pack)
  retry=Model();w=prepare_analyst_pack(s,l,retry)
  assert w.analyst_pack['status']=='complete'
  # Retain unchanged candidates; changed upstream inputs require a new section.
  assert len(retry.calls)==11  # Reuse candidates; both actions derive from reviewed plans without inference.
  assert all('previous_review_to_correct' not in payload for _,payload in retry.calls)


def test_changed_critic_rechecks_saved_prose_without_rewriting(tmp_path):
 with Store(tmp_path/'db') as s:
  l=company(s);w=prepare_analyst_pack(s,l,Model())
  original=w.analyst_pack['sections']['research.business']['content']
  w.analyst_pack['sections']['research.business']['review_hash']='old-review-policy'
  s.save_workspace(w,expected_revision=w.revision)
  model=Model();w=prepare_analyst_pack(s,l,model)
  assert len(model.calls)==1 and 'draft' in model.calls[0][1]
  assert w.analyst_pack['sections']['research.business']['content']==original
  assert w.analyst_pack['status']=='complete'


def test_changed_review_contract_does_not_reuse_obsolete_retry_errors(tmp_path):
 with Store(tmp_path/'db') as s:
  l=company(s);w=prepare_analyst_pack(s,l,Model(bad_review=True))
  for section in w.analyst_pack['sections'].values():
   if section.get('review_failure'):
    section['review_hash']='obsolete-critic'
    section['review_failure']['error']='Obsolete constraint from a retired review schema'
  s.save_workspace(w,expected_revision=w.revision)
  model=Model();prepare_analyst_pack(s,l,model)
  assert all('review_retry_error' not in payload for _,payload in model.calls)


@pytest.mark.parametrize('repair_works',[True,False])
def test_repair_rewrites_only_the_defective_field(tmp_path,repair_works):
 class RepairModel(Model):
  def __init__(self):super().__init__();self.corrected=False;self.original=None;self.repair_keys=None;self.repair_works=repair_works
  def generate(self,instruction,evidence,schema):
   payload=json.loads(evidence)
   if 'fields_to_correct' in payload:
    self.repair_keys=set(schema.model_fields)
    if not self.repair_works:raise ValueError('Temporary field repair failure')
    self.corrected=True
    return schema(unresolved_risk='Cancellation refunds and room servicing costs could consume the receipts from repeat stays.')
   if 'verdict' in schema.model_fields and not self.corrected:
    target=next((p for p in payload['draft']['passages'] if p['field']=='unresolved_risk'),None)
    if target:return schema(verdict='revise',objections=[{'passage_id':target['id'],'basis_id':'task','correction':'Describe the operating risk of cancellation refunds and servicing costs rather than treating missing public figures as a business risk.'}])
   result=super().generate(instruction,evidence,schema)
   if 'reason_to_engage' in schema.model_fields:
    result.unresolved_risk='Missing public figures prevent an assessment of performance.';self.original=result.model_dump()
   return result
 with Store(tmp_path/'db') as s:
  model=RepairModel();w=prepare_analyst_pack(s,company(s),model)
  result=w.analyst_pack['sections']['research.decision']['content']
  assert model.repair_keys=={'unresolved_risk'}
  assert result['reason_to_engage']==model.original['reason_to_engage']
  assert result['next_decision']==model.original['next_decision']
  assert result['fact_ids']==model.original['fact_ids']
  if repair_works:
   assert w.analyst_pack['status']=='complete'
  else:
   assert w.analyst_pack['sections']['research.decision']['status']=='needs_revision'
   assert result['unresolved_risk']==model.original['unresolved_risk']
   model.repair_works=True
   w=prepare_analyst_pack(s,s.get_lead('one',w.lead_id),model)
   assert w.analyst_pack['status']=='complete'


def test_record_changes_archive_old_sections_and_block_stale_download(tmp_path):
 from api.routers.operations import download_analyst_pack
 from fastapi import HTTPException
 with Store(tmp_path/'db') as s:
  l=company(s);w=prepare_analyst_pack(s,l,Model())
  l.company_profile.evidence.append(CompanyEvidence(field='pricing',value='Room fees',quote='The company charges nightly room fees.',source_url='https://hotel.example/pricing'))
  s.save_lead(l)
  with pytest.raises(HTTPException) as e:download_analyst_pack(w.id,None,s,'one')
  assert e.value.status_code==409
  with pytest.raises(HTTPException) as e:download_analyst_pack(w.id,None,s,'other')
  assert e.value.status_code==404
  w=prepare_analyst_pack(s,l,Model())
  assert len(w.analyst_pack_history)==1


def test_review_requires_actual_passage_and_actual_evidence():
 draft=Paragraph(text='The company describes operating hotels for business guests.',fact_ids=['F1'])
 r=SectionReview(verdict='revise',objections=[dict(passage='operating hotels',basis_id='F1',supporting_quote='Made up source sentence',correction='Clarify the intended customer segment.')])
 with pytest.raises(ValueError,match='supplied evidence'):bound_review(r,draft,{'F1':'The company operates hotels.'})


def test_application_queue_uses_new_pipeline_and_is_idempotent(tmp_path):
 from fastapi import BackgroundTasks
 from api.routers.operations import start_analyst_preparation
 with Store(tmp_path/'db') as s:
  l=company(s);tasks=BackgroundTasks();w=start_analyst_preparation(l.id,tasks,s,'one')
  assert tasks.tasks[0].kwargs['analyst'] is True
  assert start_analyst_preparation(l.id,tasks,s,'one')['automation']['id']==w['automation']['id']
  assert 'attempts' not in w['analyst_pack'] and 'events' not in w
  assert len(tasks.tasks)==1


def test_stopped_queued_job_never_runs_and_stale_stop_cannot_cancel_replacement(tmp_path,monkeypatch):
 from fastapi import BackgroundTasks,HTTPException
 from api.routers import operations as api
 with Store(tmp_path/'db') as s:
  lead=company(s);tasks=BackgroundTasks();queued=api.start_analyst_preparation(lead.id,tasks,s,'one')
  stopped=api.stop_preparation(queued['id'],queued['automation']['id'],s,'one')
  assert stopped['automation']['status']=='cancelled'
  monkeypatch.setattr(api,'LocalModel',lambda:pytest.fail('Cancelled queued job must not construct a model'))
  api._prepare_job(s.db_path,'one',lead.id,queued['automation']['id'],analyst=True)
  with pytest.raises(HTTPException) as error:api.stop_preparation(queued['id'],queued['automation']['id'],s,'another-tenant')
  assert error.value.status_code==404
  w=s.get_workspace('one',workspace_id=queued['id']);w.automation.id='replacement';w.automation.status='queued';s.save_workspace(w,expected_revision=w.revision)
  with pytest.raises(HTTPException) as error:api.stop_preparation(w.id,queued['automation']['id'],s,'one')
  assert error.value.status_code==409
  assert s.get_workspace('one',workspace_id=w.id).automation.status=='queued'


def test_stop_during_work_is_not_overwritten_as_failure(tmp_path,monkeypatch):
 from fastapi import BackgroundTasks
 from api.routers import operations as api
 import agents.analyst_pack as pipeline
 with Store(tmp_path/'db') as s:
  lead=company(s);queued=api.start_analyst_preparation(lead.id,BackgroundTasks(),s,'one')
  monkeypatch.setattr(api,'LocalModel',lambda:Model())
  monkeypatch.setattr(pipeline,'collect_preparation_evidence',lambda store,lead,**kw:lead)
  def cancelled(store,lead,model):
   api.stop_preparation(queued['id'],queued['automation']['id'],store,'one')
   raise ValueError('In-flight completion cannot overwrite changed workspace revision')
  monkeypatch.setattr(pipeline,'prepare_analyst_pack',cancelled)
  api._prepare_job(s.db_path,'one',lead.id,queued['automation']['id'],analyst=True)
  job=s.get_workspace('one',workspace_id=queued['id']).automation
  assert job.status=='cancelled' and job.error is None


def test_model_selection_requires_completed_cross_case_audits():
 from scripts.evaluate_analyst_workflows import select_completed_model
 from agents.analyst_pack import VERSION,IMPLEMENTATION_HASH
 rows=[{'model':'small','case_id':case,'elapsed_seconds':10,'metrics':{'completion_rate':1},'pack':{'version':VERSION,'implementation_hash':IMPLEMENTATION_HASH},'settings':{'thinking':True}} for case in ('one','two')]
 assert select_completed_model(rows,['one','two']) is None
 for row in rows:row['audit']={'reviewed':True,'factual_errors':0,'actionable_sections':9}
 assert select_completed_model(rows,['one','two'])=='small'
 rows[1]['audit']['factual_errors']=1
 assert select_completed_model(rows,['one','two']) is None
 rows[1]['audit']['factual_errors']=0
 rows[1]['settings']['thinking']=False
 assert select_completed_model(rows,['one','two']) is None
 rows[1]['settings']['thinking']=True
 rows[1]['pack']['implementation_hash']='older-implementation'
 assert select_completed_model(rows,['one','two']) is None


def test_source_passages_are_copied_by_code_with_original_metadata():
 from agents.analyst_pack import source_passages,bind_facts,RecordSelection
 source={'id':'E1','quote':'The founder previously worked for another business; this describes prior experience, not target-company traction.','source_url':'https://example.test','retrieved_at':'2026-09-14','observed_at':None,'origin':'public_web'}
 passages=source_passages([source])
 selection=RecordSelection(items=[{'passage_id':passages[0]['passage_id'],'category':'founder_history','subject':'founder'}])
 facts=bind_facts(selection,passages)
 assert facts[0]['quote'] in source['quote']
 assert facts[0]['source_id']=='E1' and facts[0]['category']=='founder_history'
 with pytest.raises(ValueError):bind_facts(RecordSelection(items=[{'passage_id':'P999','category':'traction','subject':'target'}]),passages)


def test_preparation_reads_observed_pricing_without_user_urls(tmp_path):
 from agents.analyst_pack import collect_preparation_evidence
 from agents.web_sources import Page
 class Fetcher:
  def __init__(self):self.urls=[]
  def fetch(self,url):
   self.urls.append(url)
   return Page(url,'Company','This company describes hotel services and published commercial terms for room bookings.',[{'url':'https://hotel.example/pricing','label':'Pricing'}])
 with Store(tmp_path/'db') as s:
  l=company(s);fetcher=Fetcher();l=collect_preparation_evidence(s,l,fetcher)
  assert fetcher.urls==['https://hotel.example/','https://hotel.example/pricing']
  assert any(e.source_url.endswith('/pricing') and e.origin=='preparation_public_page' for e in l.company_profile.evidence)
  collect_preparation_evidence(s,l,fetcher)
  assert len(fetcher.urls)==2


def test_calculated_figures_are_cited_from_code_not_invented_by_writer(tmp_path):
 from agents.company_metrics import metrics_report
 from agents.analyst_pack import financial_facts,validate_section
 with Store(tmp_path/'db') as s:
  w=reconcile_workspace(s,company(s))
  w.metrics=metrics_report([{'id':'M1','month':'2025-08','currency':'GBP','revenue':'1000','direct_costs':'700','source_note':'Company monthly operating statement'}])
  facts=financial_facts(w,'2026-09-14')
  contribution=next(f for f in facts if f.get('calculation',{}).get('name')=='Delivery contribution')
  assert contribution['input_ids']==['M1']
  assert contribution['calculation']['value']=='300.00'
  validate_section(Paragraph(text='The code-calculated delivery contribution is 300 GBP, before overhead and taxes.',fact_ids=[contribution['id']]),facts)
  with pytest.raises(ValueError,match='absent'):
   validate_section(Paragraph(text='The company earned 999 GBP of delivery contribution.',fact_ids=[contribution['id']]),facts)


def test_section_context_budget_preserves_category_diversity():
 from agents.analyst_pack import section_facts
 facts=[{'id':f'{c}{i}','category':c,'subject':'target','quote':'Source passage '*60,'retrieved_at':'2026-09-14','observed_at':None} for c in ['offering','customers','pricing','traction','company_structure'] for i in range(10)]
 selected=section_facts(facts,'research','decision')
 assert sum(len(json.dumps(f)) for f in selected)<=9000
 assert {f['category'] for f in selected}=={'offering','customers','pricing','traction'}


def test_review_sentence_ids_bind_exact_draft_and_cannot_target_source_text():
 from types import SimpleNamespace
 from agents.analyst_pack import bind_passage_review,draft_passages
 draft=Paragraph(text='The company describes room booking. We need dated booking receipts to assess repeat demand.',fact_ids=['F1'])
 passages=draft_passages(draft)
 assert [p['text'] for p in passages]==['The company describes room booking.','We need dated booking receipts to assess repeat demand.']
 review=SimpleNamespace(verdict='revise',objections=[SimpleNamespace(passage_id='D1',basis_id='F1',correction='The source describes hotel software, not room booking.')])
 result=bind_passage_review(review,draft,{'F1':'The company sells hotel software.'})
 assert result['objections'][0]['passage']==passages[0]['text']
 review.objections[0].passage_id='F1'
 with pytest.raises(ValueError,match='DRAFT'):bind_passage_review(review,draft,{'F1':'Source-only statement'})


def test_numeric_spelling_normalization_keeps_units_distinct():
 from agents.analyst_pack import comparable_numbers
 assert comparable_numbers('300.00 GBP')==comparable_numbers('300 GBP')
 assert comparable_numbers('30.0%')==comparable_numbers('30%')
 assert comparable_numbers('30%')!=comparable_numbers('30 GBP')


def test_requested_lookback_is_not_mistaken_for_a_company_metric():
 from agents.analyst_pack import Request,validate_section
 request=Request(analysis_plan=contribution_plan(),question='Can you share the booking receipts for the last 12 months?',records_to_request='Dated booking receipts and servicing invoices for the same reporting period.',decision='Assess whether collected room receipts cover direct delivery costs.',fact_ids=['F1'])
 facts=[{'id':'F1','quote':'The company operates hotels.'}]
 validate_section(request,facts)
 request.question='Can you verify the reported 75% margin using those receipts?'
 with pytest.raises(ValueError,match='75%'):validate_section(request,facts)


def test_outside_adviser_cannot_claim_the_company_pricing_as_its_own():
 from agents.analyst_pack import FounderOffer,validate_section
 facts=[{'id':'F1','quote':'The company publishes customer pricing.'}]
 offer=FounderOffer(proposed_work='We can assess whether our published fee schedules cover delivery costs.',invitation='Would you discuss this work with our team?',fact_ids=['F1'])
 with pytest.raises(ValueError,match='outside adviser'):validate_section(offer,facts)
 offer.proposed_work='We can assess your published fees against billing and actual delivery-cost records.'
 validate_section(offer,facts)


def test_schema_length_repair_preserves_the_other_financial_field(tmp_path):
 class LengthModel(Model):
  def __init__(self):super().__init__();self.repaired_fields=None
  def generate(self,instruction,evidence,schema):
   payload=json.loads(evidence)
   if 'fields_to_correct' in payload:
    self.repaired_fields=set(schema.model_fields)
    return schema(revenue_mechanism='The company describes charging guests nightly room fees.')
   if 'revenue_mechanism' in schema.model_fields:
    raw={'revenue_mechanism':'The company describes charging guests nightly room fees. '*50,
         'unknown_economics':'Booking receipts and servicing invoices are needed to establish contribution.',
         'fact_ids':[payload['evidence_record'][0]['id']]}
    self.last_response_text=json.dumps(raw)
    return schema.model_validate(raw)
   return super().generate(instruction,evidence,schema)
 with Store(tmp_path/'db') as s:
  model=LengthModel();w=prepare_analyst_pack(s,company(s),model)
  assert model.repaired_fields=={'revenue_mechanism'}
  assert w.analyst_pack['sections']['research.economics']['content']['unknown_economics']=='Booking receipts and servicing invoices are needed to establish contribution.'
  assert w.analyst_pack['status']=='complete'


def test_review_citation_bookkeeping_rebinds_only_unique_exact_quotes():
 draft=Paragraph(text='The company says it offers a paid delivery service.',fact_ids=['F1'])
 review=SectionReview(verdict='revise',objections=[{'passage':'paid delivery service','basis_id':'F1','supporting_quote':'Offers a delivery service','correction':'The source does not establish that deliveries are paid.'}])
 checked=bound_review(review,draft,{'F1':'An unrelated source passage','F2':'Offers a delivery service'})
 assert checked['objections'][0]['basis_id']=='F2'
 review.objections[0].basis_id='F1'
 with pytest.raises(ValueError):bound_review(review,draft,{'F1':'Unrelated','F2':'Offers a delivery service','F3':'Offers a delivery service'})


def test_polling_view_retains_documents_without_candidate_or_trace_leak(tmp_path):
 from api.routers.operations import company_work_view
 with Store(tmp_path/'db') as s:
  w=prepare_analyst_pack(s,company(s),Model(bad_review=True))
  original=json.dumps(w.analyst_pack)
  view=company_work_view(w)
  assert 'attempts' not in view['analyst_pack']
  assert 'batches' not in view['analyst_pack']['record']
  assert 'candidate' not in view['analyst_pack']['sections']['research.business']
  assert json.dumps(w.analyst_pack)==original


def test_critic_selects_fields_and_code_attaches_actual_evidence():
 from types import SimpleNamespace
 from agents.analyst_pack import bind_field_review
 draft=Paragraph(text='The company operates hotels for business guests.',fact_ids=['F1'])
 review=SimpleNamespace(verdict='revise',objections=[SimpleNamespace(field='text',passage=draft.text,basis_id='F1',correction='Attribute this description to the company source.')])
 checked=bind_field_review(review,draft,{'F1':'Our hotels serve business guests.'})
 assert checked['objections'][0]['passage']==draft.text
 assert checked['objections'][0]['supporting_quote']=='Our hotels serve business guests.'
 review.objections[0].field='other_field'
 with pytest.raises(ValueError):bind_field_review(review,draft,{'F1':'Our hotels serve business guests.'})


def test_business_claim_attribution_and_fee_basis_are_checked():
 from agents.analyst_pack import validate_section
 facts=[{'id':'F1','quote':'The annual advisory fee is based on AUM.'}]
 with pytest.raises(ValueError,match='attributing'):
  validate_section(Paragraph(text='This company guarantees effortless global investing.',fact_ids=['F1']),facts,'research.business')
 with pytest.raises(ValueError,match='asset-based'):
  validate_section(Paragraph(text='Revenue is performance-based (AUM fees) and requires client growth.',fact_ids=['F1']),facts)
 validate_section(Paragraph(text='The company reports an AUM-based advisory fee, not a performance fee.',fact_ids=['F1']),facts,'research.business')


def test_known_defective_cached_text_is_not_republished(tmp_path):
 from agents.analyst_pack import validate_saved_sections
 with Store(tmp_path/'db') as s:
  w=prepare_analyst_pack(s,company(s),Model());p=w.analyst_pack
  p['sections']['research.decision']['content']['unresolved_risk']='The revenue is performance-based (AUM fees) and transactional.'
  assert 'performance-based (AUM fees)' not in export_pack(p)
  assert p['sections']['research.decision']['status']=='complete'
  validate_saved_sections(p)
  assert p['sections']['research.decision']['status']=='needs_revision'
  assert p['sections']['founder.observation']['status']=='complete'


def test_critic_cannot_rewrite_for_a_claim_only_present_in_sources():
 from types import SimpleNamespace
 from agents.analyst_pack import bind_field_review
 draft=Paragraph(text='According to the company, it supplies packaged goods.',fact_ids=['F1'])
 review=SimpleNamespace(verdict='revise',objections=[SimpleNamespace(field='text',passage='SIPC Insured',basis_id='F1',correction='Remove the legal assurance from the draft.')])
 with pytest.raises(ValueError,match='CURRENT draft'):
  bind_field_review(review,draft,{'F1':'Reference source contains SIPC Insured.'})


def test_citation_excerpt_cleanup_preserves_unknown_ids_and_following_claims():
 from agents.analyst_pack import normalize_citation_metadata
 def clean(text):return normalize_citation_metadata({'text':text,'fact_ids':['fact_one','fact_two']})['text']
 assert clean("Clients pay brokerage on trades. Source: 'Pay brokerage' (fact_one), 'Advisory fees' (fact_two).")=='Clients pay brokerage on trades.'
 for tail in ("'Pay brokerage' (unknown), 'Advisory fees' (fact_two)","'Pay brokerage' (fact_one). Revenue doubled.","fact_one, invented_id"):
  original='Clients pay fees. Source: '+tail
  assert clean(original)==original


def test_long_citation_metadata_is_fixed_without_another_model_call(tmp_path):
 class Citations(Model):
  def generate(self,instruction,evidence,schema):
   if 'revenue_mechanism' in schema.model_fields:
    p=json.loads(evidence);self.calls.append((instruction,p))
    fid=p['evidence_record'][0]['id']
    raw={'revenue_mechanism':"The company reports charging guests room fees. Source: '"+'Exact citation excerpt '*60+"' ("+fid+')', 'unknown_economics':'Booking receipts and servicing invoices are needed to establish contribution.','fact_ids':[fid]}
    self.last_response_text=json.dumps(raw)
    return schema.model_validate(raw)
   return super().generate(instruction,evidence,schema)
 with Store(tmp_path/'db') as s:
  model=Citations();w=prepare_analyst_pack(s,company(s),model)
  assert w.analyst_pack['status']=='complete'
  assert w.analyst_pack['sections']['research.economics']['content']['revenue_mechanism']=='The company reports charging guests room fees.'
  assert len([r for r in w.analyst_pack['attempts'] if r.get('citation_normalization')])==1
  assert not any('fields_to_correct' in p for _,p in model.calls)


def test_unrelated_code_edits_do_not_invalidate_reviews(monkeypatch):
 import agents.analyst_pack as ap
 pack={'generation_config':{'writer':'fixture'}}
 original=ap.current_review_hash(pack)
 monkeypatch.setattr(ap,'IMPLEMENTATION_HASH','new-source-collector-code')
 assert ap.current_review_hash(pack)==original
 monkeypatch.setattr(ap,'REVIEW_CONTRACT_HASH','new-content-review-policy')
 assert ap.current_review_hash(pack)!=original


def test_partial_source_coverage_does_not_hide_complete_drafts(tmp_path):
 class Partial(Model):
  def generate(self,instruction,evidence,schema):
   p=json.loads(evidence)
   if 'passages' in p:
    row=p['passages'][0]
    from types import SimpleNamespace
    return schema.model_construct(facts=[schema.model_fields['facts'].annotation.__args__[0].model_construct(passage_id=pid,category=category,subject='target') for pid,category in [(row['passage_id'],'offering'),('invented_passage','traction')]])
   return super().generate(instruction,evidence,schema)
 with Store(tmp_path/'db') as s:
  w=prepare_analyst_pack(s,company(s),Partial())
  assert w.analyst_pack['record']['coverage']=='partial'
  assert w.analyst_pack['status']=='complete'
  assert 'Source coverage is incomplete' in export_pack(w.analyst_pack)
  assert 'Unsupported operating results' not in export_pack(w.analyst_pack)


def test_agenda_rejects_invented_company_metrics():
 from types import SimpleNamespace
 from agents.analyst_pack import InvestmentQuestionPlan,validate_agenda
 base=dict(why_it_matters='Loss-making delivery would weaken the expansion case.',fact_ids=['f'])
 first=InvestmentQuestionPlan(dimension='unit_economics',question='Can the reported 95% margin support expansion?',**base)
 second=InvestmentQuestionPlan(dimension='customer_demand',question='Do customers buy the service repeatedly?',**base)
 with pytest.raises(ValueError,match='unsupported company figures'):
  validate_agenda(SimpleNamespace(questions=[first,second]),[{'id':'f','quote':'The company sells a delivery service.'}])


def test_format_repair_does_not_consume_content_revision_budget(tmp_path):
 class SeparateBudgets(Model):
  def __init__(self):super().__init__();self.repairs=0
  def generate(self,instruction,evidence,schema):
   p=json.loads(evidence)
   if 'fields_to_correct' in p and 'revenue_mechanism' in p['fields_to_correct']:
    self.repairs+=1
    return schema(revenue_mechanism='The company describes room fees paid by guests for stays.' if self.repairs==1 else 'According to the company, guests pay room fees for overnight stays.')
   if 'verdict' in schema.model_fields:
    target=next((r for r in p['draft']['passages'] if r['field']=='revenue_mechanism'),None)
    if target and self.repairs==1:
     return schema(verdict='revise',objections=[{'passage_id':target['id'],'basis_id':'task','correction':'Clarify that the fee buys overnight stays.'}])
   if 'revenue_mechanism' in schema.model_fields:
    raw={'revenue_mechanism':'The company charges room fees. '*60,'unknown_economics':'Booking receipts and servicing invoices are needed to establish contribution.','fact_ids':[p['evidence_record'][0]['id']]}
    self.last_response_text=json.dumps(raw)
    return schema.model_validate(raw)
   return super().generate(instruction,evidence,schema)
 with Store(tmp_path/'db') as s:
  model=SeparateBudgets();w=prepare_analyst_pack(s,company(s),model)
  assert model.repairs==2
  assert w.analyst_pack['sections']['research.economics']['status']=='complete'


@pytest.mark.parametrize('override',[None,'auto','qwen3:8b'])
def test_resume_retains_profile_unless_explicitly_changed(tmp_path,override):
 from fastapi import BackgroundTasks
 from api.routers.operations import start_analyst_preparation
 with Store(tmp_path/'db') as s:
  lead=company(s);w=reconcile_workspace(s,lead)
  from agents.analyst_pack import VERSION
  w.analyst_pack={'version':VERSION,'generation_config':{'mode':'model_authored_v1','model':'qwen3:14b','thinking':True,'review_model':'qwen3:8b','review_thinking':False}}
  s.save_workspace(w,expected_revision=w.revision)
  tasks=BackgroundTasks();start_analyst_preparation(lead.id,tasks,s,'one',model=override)
  kwargs=tasks.tasks[0].kwargs
  if override is None:
   assert kwargs['analyst_model']=='qwen3:14b' and kwargs['analyst_thinking'] is True
   assert kwargs['analyst_review_model']=='qwen3:8b' and kwargs['analyst_review_thinking'] is False
  else:
   assert kwargs['analyst_model']==override and kwargs['analyst_thinking'] is False
   assert kwargs['analyst_review_model'] is None


def test_planning_rationale_is_not_promoted_into_company_evidence(tmp_path):
 class Rationale(Model):
  def generate(self,instruction,evidence,schema):
   result=super().generate(instruction,evidence,schema)
   if 'questions' in schema.model_fields:
    # Simulates an obsolete planner shape. Substantive analysis belongs in
    # reviewed deliverables, not unreviewed planning context.
    for q in result.questions:q.__dict__['why_it_matters']='Uncited law caps every company fee.'
   return result
 with Store(tmp_path/'db') as s:
  model=Rationale();w=prepare_analyst_pack(s,company(s),model)
  assert w.analyst_pack['status']=='complete'
  assert all('Uncited law' not in json.dumps(payload) for _,payload in model.calls)


def test_refresh_replaces_only_collector_snapshots_and_preserves_history(tmp_path):
 from agents.analyst_pack import collect_preparation_evidence
 from agents.web_sources import Page,SourceError
 class Fetcher:
  text='The company charges guests room fees and offers business accommodation.'
  def fetch(self,url):return Page(url,'Company',self.text,[])
 with Store(tmp_path/'db') as s:
  lead=company(s);original=[e.id for e in lead.company_profile.evidence];f=Fetcher()
  lead=collect_preparation_evidence(s,lead,f)
  prior=[e for e in lead.company_profile.evidence if e.origin=='preparation_public_page']
  f.text='The company now describes charging nightly room fees for its accommodation.'
  lead=collect_preparation_evidence(s,lead,f,force=True)
  assert set(original)<={e.id for e in lead.company_profile.evidence}
  assert not {e.id for e in prior}&{e.id for e in lead.company_profile.evidence}
  w=s.get_workspace('one',lead_id=lead.id)
  assert w.research['preparation_source_history'][-1]['evidence'][0]['quote']==prior[0].quote
  current=[e.model_dump() for e in lead.company_profile.evidence]
  class Failed:
   def fetch(self,url):raise SourceError('blocked','Source unavailable')
  lead=collect_preparation_evidence(s,lead,Failed(),force=True)
  assert [e.model_dump() for e in lead.company_profile.evidence]==current


def test_record_list_numbers_are_not_reported_financial_metrics():
 from agents.analyst_pack import Request,validate_section
 facts=[{'id':'fact_record','quote':'The company sells equipment and servicing.'}]
 request=Request(analysis_plan=contribution_plan(),question='Do customer payments cover the cost of servicing equipment?',records_to_request='Request: (1) billing ledger entries; (2) servicing cost invoices; (3) refund records for the same reporting period.',decision='Compare retained payments against direct servicing costs, including loss-making orders.',fact_ids=['fact_record'])
 validate_section(request,facts)
 request.analysis_plan.left.record_needed+=' Revenue was 999 last month.'
 with pytest.raises(ValueError,match='999'):validate_section(request,facts)


def test_proposed_cohort_windows_do_not_assert_company_performance():
 from agents.analyst_pack import Request,validate_section
 facts=[{'id':'fact_record','quote':'The company offers an investment app.'}]
 request=Request(analysis_plan=contribution_plan(),question='Do funded accounts remain active after onboarding?',records_to_request='Export account opening and funding events for the last 12 months, with retained balances within the following 30-day, 90-day, and 6-month windows.',decision='Distinguish retained funded accounts from withdrawn balances before proposing expansion.',fact_ids=['fact_record'])
 validate_section(request,facts)
 request.analysis_plan.left.record_needed+=' Include evidence of the reported 95% retention rate.'
 with pytest.raises(ValueError,match='95%'):validate_section(request,facts)


def test_agenda_can_propose_retention_windows_without_inventing_results():
 from types import SimpleNamespace
 from agents.analyst_pack import InvestmentQuestionPlan,validate_agenda
 questions=[InvestmentQuestionPlan(dimension='unit_economics',question='Do retained fees cover the cost of serving clients?',fact_ids=['fact_source']),InvestmentQuestionPlan(dimension='customer_demand',question='What percentage of accounts remains funded after 3 months?',fact_ids=['fact_source'])]
 validate_agenda(SimpleNamespace(questions=questions),[{'id':'fact_source','quote':'The company offers account servicing.'}])
