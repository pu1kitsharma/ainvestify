import json
import pytest
from agents.investment_case import prepare_investment_case, case_current
from agents.investment_practice import practice_context, practice_instruction, practice_manifest, ROOT
from agents.preparation_quality import review_preparation
from tests.test_investment_case import Model
from tests.test_operating_workflow import company
from store import Store


def test_methods_are_scoped_and_not_passed_as_company_evidence():
    assert {m['id'] for m in practice_context('pitch')['methods']} == {'founder_pitch'}
    assert 'US templates do not establish Indian compliance' in practice_instruction('fundraising', 'Write')
    assert practice_context('eligibility')['methods'] == []
    assert practice_manifest('research')['adaptation'] == 'retrieved_practice_not_weight_training'
    teaching = json.loads((ROOT/'teaching_examples.json').read_text())
    evaluation = json.loads((ROOT.parents[1]/'evals/investment_preparation/cases.json').read_text())
    assert not {e['input'].get('company_name',e['input'].get('company')) for e in teaching['examples']} & {e['input']['company_name'] for e in evaluation}


def test_review_questions_continue_independent_work_without_claiming_clearance(tmp_path):
    class Reject(Model):
        def generate(self, instruction, payload, schema):
            if 'grounding' in schema.model_fields:
                draft = json.loads(payload)['draft_fields']
                result=passing_review(schema,draft)
                result.usefulness.verdict='revise'
                result.usefulness.reason='Write a specific investment question and evidence comparison instead of generic advice.'
                return result
            return super().generate(instruction, payload, schema)
    with Store(tmp_path/'db') as store:
        lead=company(store)
        prepare_investment_case(store,lead,Reject())
        w=store.get_workspace('one',lead_id=lead.id)
        assert w.investment_case['eligibility'] and w.investment_case['fit']
        assert len(w.investment_case['products'])==3
        assert all(p['review_state']=='needs_review' for p in w.investment_case['products'].values())
        assert len(w.investment_case['quality_attempts'])==6
        assert w.investment_case['status']=='needs_review'
        from api.routers.operations import export_investment_case
        text=export_investment_case(w.id,store,'one').body.decode()
        assert 'not verified materials for investors' in text
        assert 'not a confirmed finding' in text
        done=prepare_investment_case(store,lead,Model())
        assert case_current(done)
        assert done.investment_case['status']=='complete'
        assert done.investment_case['products']['investment_case']['quality_review']['independent_verification'] is False
        assert done.capabilities['external_sending'] is False


def test_reviewer_cannot_invent_an_error_excerpt():
    class Invented:
        name='fixture'
        def generate(self,instruction,payload,schema):
            from agents.preparation_quality import QualityReview
            return QualityReview(**{k:dict(verdict='revise',draft_field='absent_field',reason='Remove it.') for k in schema.model_fields if k!='field_checks'})
    with pytest.raises(ValueError,match='absent from the draft'):
        review_preparation(Invented(),'investment_case',{'sources':[]},{'title':'Actual written title'})


def test_current_pack_requires_completed_automated_review(tmp_path):
    with Store(tmp_path/'db') as store:
        w=prepare_investment_case(store,company(store),Model())
        assert case_current(w)
        del w.investment_case['products']['investment_case']['quality_review']
        assert not case_current(w)


def test_training_export_keeps_validation_and_client_data_separate(tmp_path):
    from scripts.export_preparation_training import export
    manifest=export(tmp_path)
    assert manifest['counts']=={'train':8,'validation':2}
    assert manifest['weights_trained'] is False and manifest['held_out_cases_exported'] is False
    train=(tmp_path/'train.jsonl').read_text()
    valid=(tmp_path/'valid.jsonl').read_text()
    assert 'crop treatment laboratory' not in train and 'crop treatment laboratory' in valid
    assert 'Harbor Rooms' not in train+valid


def test_mixed_directory_ask_does_not_reverse_founder_and_customer_roles():
    from agents.company_brief import select_context_facts
    from schemas import CompanyEvidence
    mixed=CompanyEvidence(field='founder_ask',value='Mixed directory block',
        quote='We want to run your procurement. Intros to procurement leads at hardware enterprises. Founded: 2026',source_url='https://example.test/profile')
    selected=select_context_facts([mixed])
    assert selected[0].quote=='Intros to procurement leads at hardware enterprises.'
    assert selected[0].id==mixed.id and 'run your procurement' in mixed.quote
    sales=mixed.model_copy(update={'quote':'Hardware founders: we want to run your procurement.'})
    assert select_context_facts([sales])[0].field!='founder_ask'


def test_all_readiness_priorities_are_reviewed_individually():
    from agents.preparation_quality import review_passed
    class Recorder:
        name='fixture'
        def __init__(self):self.calls=[]
        def generate(self,instruction,payload,schema):
            data=json.loads(payload)['draft_fields'];self.calls.append(data)
            result=passing_review(schema,data)
            if any(k.startswith('priority_2') for k in data):
                result.stage_fit.verdict='revise';result.stage_fit.reason='Premature expansion before validating the prototype.'
            return result
    model=Recorder()
    review=review_preparation(model,'readiness',{}, {'priorities':[{'title':'Test prototype'},{'title':'Compare costs'},{'title':'Expand immediately'}]})
    assert len(model.calls)==3 and len(review['issues'])==1
    assert not review_passed(review)


def test_maturity_sees_dated_history_and_can_only_cite_that_history(tmp_path):
    from schemas import CompanyEvidence
    class HistoryModel(Model):
        def generate(self,instruction,payload,schema):
            if 'maturity' in schema.model_fields and 'decision' not in schema.model_fields:
                data=json.loads(payload)
                assert data['as_of'] and all(e['field']=='founded' for e in data['sources'])
                citation=data['sources'][0]['id']
                return schema(maturity='early_business',evidence_ids=[citation])
            return super().generate(instruction,payload,schema)
    with Store(tmp_path/'db') as store:
        lead=company(store)
        lead.company_profile.evidence.append(CompanyEvidence(field='founded',value='2026',quote='Founded: 2026',source_url='https://example.test/profile'))
        store.save_lead(lead)
        result=prepare_investment_case(store,lead,HistoryModel())
        assert result.investment_case['eligibility']['maturity']=='early_business'


def passing_review(schema,draft):
    checks = {k:dict(verdict="pass",draft_field=next(iter(draft)),reason="Fixture assessment: the cited business supports this scoped draft.") for k in schema.model_fields if k!='field_checks'}
    checks['field_checks']={k:dict(verdict='pass',reason='Fixture text is scoped to supplied evidence.') for k in schema.model_fields['field_checks'].annotation.model_fields}
    return schema(**checks)


def test_every_section_is_checked_and_overall_pass_cannot_override_a_field_failure():
    from agents.preparation_quality import review_passed
    class Reviewer:
        name='fixture'
        def generate(self,instruction,payload,schema):
            data=json.loads(payload)
            assert 'sections.1.content' in data['fields_to_check']
            assert 'completion_test' in data['fields_to_check']
            result=passing_review(schema,data['draft_fields'])
            field=getattr(result.field_checks,'sections.1.content')
            field.verdict='revise';field.reason='Attribute the claimed benefit; no observed comparison establishes it.'
            return result
    result=review_preparation(Reviewer(),'investment_case',{},dict(sections=[{'content':'The company says it automates procurement.'},{'content':'It ensures inventory accuracy.'}],next_action='Draft a founder proposal.',completion_test='The proposal names the records to request.'))
    assert not review_passed(result)
    assert any('Attribute' in issue['correction'] for issue in result['issues'])


def test_old_partial_field_review_is_not_current():
    from agents.preparation_quality import review_record_valid
    assert not review_record_valid({'version':3,'kind':'automated_critique','checks':{},'issues':[]})
