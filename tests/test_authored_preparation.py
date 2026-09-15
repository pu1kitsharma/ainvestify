"""Contract tests with injected responses, not examples for production prompts."""
import json
from copy import deepcopy

from agents.analyst_pack import prepare_analyst_pack, validate_saved_sections, export_pack
from agents.authored_preparation import project, authored_answer
from agents.model_authorship import response_answer
from agents.preparation_budget import PreparationBudget
from store import Store
from tests.test_operating_workflow import company


def answers():
    cite = {'fact_ids':['S1']}
    return {
        'research': {
            'business': dict(text='Its website reports that Hotel Example operates hotels. The supplied evidence does not identify its customer segments.',**cite),
            'economics': dict(revenue_mechanism='The source describes hotel operations but does not establish the booking or charging terms.',unknown_economics='Request booking contracts and invoices to establish what guests pay for.',**cite),
            'decision': dict(reason_to_engage='Hotel operations could merit investigation if guest demand supports their delivery obligations.',unresolved_risk='Unreliable room availability could prevent the hotel fulfilling guest reservations.',next_decision='Review reservation fulfilment before proposing help; repeated failures would change the scope.',**cite)},
        'work': {
            'first': dict(question='Can the hotel fulfil the reservations it accepts?',records_to_request='Request dated reservation exports, room availability logs and cancellation reasons for an agreed common period.',action='Match accepted reservations to room availability by property and date. Investigate cases without a room and distinguish guest cancellations.',output='A reservation fulfilment table and an exceptions list.',decision='Frequent availability conflicts would support scheduling work; resolved cases would shift attention to other constraints.',**cite),
            'second': dict(question='Which contractual obligations constrain property operations?',records_to_request='Request current property agreements, service obligations and contract amendment records for each hotel.',action='Read the agreements and map each operating obligation to its property and responsible party. Ask founders to resolve ambiguous clauses.',output='A property obligations map with unresolved contract questions.',decision='Unclear obligations would require specialist review before proposing expansion; confirmed obligations would define the permitted scope.',**cite)},
        'founder': {
            'observation':dict(reported_observation='Your website describes hotel operations, which prompted us to examine reservation fulfilment.',question_to_explore='How do you identify reservations affected by room availability?',**cite),
            'proposal':dict(proposed_work='We could review your reservation exports and property agreements to map fulfilment exceptions and operating obligations. The resulting tables would help identify scheduling work or contract questions to resolve before discussing expansion.',invitation='Would you be open to discussing these records and the proposed work?',**cite)},
        'review':{'verdict':'pass','issues':[]}}


class Model:
    name='injected-test-model'
    def __init__(self):
        self.calls=[]
        self.last_route={}
        self.data=answers()
    def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
        phase=task.removeprefix('authored_')
        self.calls.append(phase)
        value={k:deepcopy(v) for k,v in self.data[phase].items() if k in schema.model_fields}
        self.last_response_text=json.dumps(value)
        return schema.model_validate(value)


def test_all_nine_sections_are_exact_model_projections_and_cache_uses_no_calls(tmp_path):
    with Store(tmp_path/'test.db') as store:
        lead=company(store)
        model=Model()
        w=prepare_analyst_pack(store,lead,model)
        assert w.analyst_pack['status']=='complete',w.analyst_pack.get('stop_reason')
        assert model.calls==['research','work','founder','review']
        assert len(w.analyst_pack['sections'])==9
        for phase,reference in w.analyst_pack['authored'].items():
            original=response_answer(w.analyst_pack['attempts'],reference['response_id'])
            for key,content in project(phase,original).items():
                assert w.analyst_pack['sections'][key]['content']==content
        # The model chose fulfilment and contracts, not contribution/activation.
        assert 'property agreements' in export_pack(w.analyst_pack,'readiness')
        cached=prepare_analyst_pack(store,lead,model)
        assert cached.analyst_pack['status']=='complete'
        assert len(model.calls)==4


def test_manual_display_edits_fail_authorship_validation(tmp_path):
    with Store(tmp_path/'test.db') as store:
        w=prepare_analyst_pack(store,company(store),Model())
        w.analyst_pack['sections']['research.business']['content']['text']='A handwritten replacement pretending to be AI.'
        checked=validate_saved_sections(w.analyst_pack)
        assert checked['status']=='partial'
        assert all(s['status']=='needs_revision' for s in checked['sections'].values())
        assert 'handwritten replacement' not in export_pack(checked)


def test_tampered_raw_answer_cannot_be_published(tmp_path):
    with Store(tmp_path/'test.db') as store:
        w=prepare_analyst_pack(store,company(store),Model())
        w.analyst_pack['attempts'][0]['raw_response']='{}'
        assert validate_saved_sections(w.analyst_pack)['status']=='partial'


def test_reported_source_metadata_is_required_without_rewriting_model_sentences(tmp_path):
    with Store(tmp_path/'test.db') as store:
        model=Model()
        model.data['research']['business']['text']='Hotel Example operates hotels. The supplied evidence does not identify its customer segments.'
        w=prepare_analyst_pack(store,company(store),model)
        assert w.analyst_pack['status']=='complete'
        section=w.analyst_pack['sections']['research.business']
        assert section['content']['text']==model.data['research']['business']['text']
        assert section['evidence_status']=='source_reported'
        section.pop('evidence_status')
        assert validate_saved_sections(w.analyst_pack)['status']=='partial'


def test_model_failure_has_no_template_fallback(tmp_path):
    class Broken(Model):
        def generate_for_task(self,*args,**kwargs):
            self.last_response_text='{"broken":true}'
            raise ValueError('Injected failure')
    with Store(tmp_path/'test.db') as store:
        w=prepare_analyst_pack(store,company(store),Broken())
        assert w.analyst_pack['status']=='partial'
        assert w.analyst_pack['sections']=={}
        assert len(w.analyst_pack['attempts'])==2
        assert all(a['raw_response']=='{"broken":true}' for a in w.analyst_pack['attempts'])


def test_partial_work_resumes_without_rewriting_accepted_responses(tmp_path):
    with Store(tmp_path/'test.db') as store:
        lead=company(store); model=Model()
        w=prepare_analyst_pack(store,lead,model,budget=PreparationBudget(max_calls=1))
        assert w.analyst_pack['status']=='partial'
        original=w.analyst_pack['authored']['research']
        w=prepare_analyst_pack(store,lead,model)
        assert w.analyst_pack['status']=='complete'
        assert model.calls==['research','work','founder','review']
        assert w.analyst_pack['authored']['research']==original


def test_review_failure_does_not_mark_authored_work_complete(tmp_path):
    model=Model()
    model.data['review']={'verdict':'revise','issues':[{'section':'readiness.action_a','field':'action','explanation':'The proposed method does not resolve the stated question.'}]}
    with Store(tmp_path/'test.db') as store:
        w=prepare_analyst_pack(store,company(store),model)
        assert w.analyst_pack['status']=='partial'
        assert all(s['status']!='complete' for s in w.analyst_pack['sections'].values())
        assert model.calls==['research','work','founder','review','work','review']


def test_model_repairs_only_bad_sections_and_original_responses_remain(tmp_path):
    class BadEconomics(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if len(self.calls)==1:
                data=result.model_dump()
                data['economics']['revenue_mechanism']='The hotel charges an invented fee of 99 percent per booking.'
                self.last_response_text=json.dumps(data)
                return schema.model_validate(data)
            return result
    with Store(tmp_path/'test.db') as store:
        model=BadEconomics()
        w=prepare_analyst_pack(store,company(store),model)
        pack=w.analyst_pack
        assert pack['status']=='complete',pack.get('stop_reason')
        assert model.calls==['research','research','work','founder','review']
        assert set(pack['attempts'][1]['answer'])=={'economics'}
        assert '99 percent' in pack['attempts'][0]['raw_response']
        assert pack['sections']['research.business']['content']==pack['attempts'][0]['answer']['business']
        reconstructed=authored_answer(pack['attempts'],pack['authored']['research'])
        assert reconstructed['economics']==pack['attempts'][1]['answer']['economics']
        assert '99 percent' not in export_pack(pack)
