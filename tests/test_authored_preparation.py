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
        def select(value, contract):
            result = {}
            for key, field in contract.model_fields.items():
                if key not in value:
                    continue
                annotation = field.annotation
                result[key] = select(value[key], annotation) if isinstance(value[key], dict) and hasattr(annotation, 'model_fields') else deepcopy(value[key])
            return result
        value=select(self.data[phase],schema)
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
        assert w.analyst_pack['generation_metrics']['first_attempt_contract_pass'] is True
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


def test_founder_download_requires_current_review_and_exports_recorded_prose(tmp_path):
    import pytest
    from fastapi import HTTPException
    from api.routers.operations import download_analyst_pack
    with Store(tmp_path/'test.db') as store:
        lead = company(store)
        model = Model()
        prepared = prepare_analyst_pack(store, lead, model)
        response = download_analyst_pack(prepared.id, 'founder', store, 'one')
        assert response.status_code == 200
        assert answers()['founder']['proposal']['proposed_work'] in response.body.decode()
        assert 'hotel-example-founder.md' in response.headers['content-disposition']
        prepared.analyst_pack['author_review']['contract'] = 'outdated-review-contract'
        store.save_workspace(prepared, expected_revision=prepared.revision)
        with pytest.raises(HTTPException) as error:
            download_analyst_pack(prepared.id, 'founder', store, 'one')
        assert error.value.status_code == 409


def test_resume_applies_saved_review_objection_before_spending_another_review_call(tmp_path):
    with Store(tmp_path/'test.db') as store:
        lead = company(store); broken = Model()
        broken.data['review'] = {'verdict': 'revise', 'issues': [{'section': 'readiness.action_a', 'field': 'action', 'explanation': 'Clarify which records identify unmatched reservation dates.'}]}
        initial = prepare_analyst_pack(store, lead, broken)
        assert initial.analyst_pack['status'] == 'partial'
        assert initial.analyst_pack['pending_review']['response_id'] == initial.analyst_pack['attempts'][-1]['id']
        count = len(initial.analyst_pack['attempts'])
        fixed = Model()
        resumed = prepare_analyst_pack(store, lead, fixed).analyst_pack
        assert resumed['status'] == 'complete', resumed.get('stop_reason')
        assert fixed.calls == ['work', 'review']
        assert len(resumed['attempts']) == count + 2
        assert 'pending_review' not in resumed


def test_model_repairs_only_bad_sections_and_original_responses_remain(tmp_path):
    class BadEconomics(Model):
        def generate_for_task(self,task,instruction,evidence,schema,**kwargs):
            result=super().generate_for_task(task,instruction,evidence,schema,**kwargs)
            if len(self.calls)==1:
                data=result.model_dump()
                data['economics']['revenue_mechanism']='The hotel charges performance-based (AUM) fees for every guest booking.'
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
        assert 'performance-based (AUM)' in pack['attempts'][0]['raw_response']
        assert pack['sections']['research.business']['content']==pack['attempts'][0]['answer']['business']
        reconstructed=authored_answer(pack['attempts'],pack['authored']['research'])
        assert reconstructed['economics']==pack['attempts'][1]['answer']['economics']
        assert 'performance-based (AUM)' not in export_pack(pack)


def test_content_validation_keeps_source_and_rate_rules_outside_decoder_grammar():
    import pytest
    from agents.authored_preparation import Research, bound_schema
    from agents.local_models import generation_schema
    schema = bound_schema(Research, [{'id': 'S1'}])
    for section, field, bad in [
        ('business', 'text', 'The source describes hotel operations. Sources S1.'),
        ('economics', 'revenue_mechanism', 'The hotel charges guests a published rate of 25% per booking.'),
    ]:
        data = answers()['research']
        data[section][field] = bad
        with pytest.raises(ValueError, match='pattern'):
            schema.model_validate(data)
    good = answers()['research']
    good['business']['text'] = 'The website describes 12 hotels using Wi-Fi 6. Published information needs verification.'
    assert schema.model_validate(good).business.text == good['business']['text']
    encoded = json.dumps(generation_schema(schema))
    assert 'pattern' not in encoded
    assert '"const": "S1"' in encoded


def test_outbound_payments_cannot_be_described_as_collected():
    import pytest
    from agents.authored_preparation import validate_prose, ProseCorrections
    facts = [{'id': 'S1', 'quote': 'The platform lets businesses collect incoming payments and send outbound payments.', 'status': 'source_reported'}]
    data = answers()['research']
    data['business']['text'] = 'The platform lets businesses collect one-off, recurring and outbound bank-to-bank payments.'
    with pytest.raises(ProseCorrections, match='sending outbound'):
        validate_prose('research', data, facts)
    data['business']['text'] = 'The platform lets businesses collect incoming payments and send outbound bank-to-bank payments.'
    validate_prose('research', data, facts)


def test_resume_repairs_saved_failed_candidate_instead_of_restarting_research(tmp_path):
    with Store(tmp_path/'test.db') as store:
        lead = company(store); broken = Model()
        broken.data['research']['decision']['reason_to_engage'] = 'The hotel charges performance-based (AUM) fees, making it worth investigation.'
        failed = prepare_analyst_pack(store, lead, broken)
        assert failed.analyst_pack['status'] == 'partial'
        # A second bounded correction is allowed for a still-invalid prose
        # candidate; it remains unpublished when the model repeats the defect.
        assert broken.calls == ['research', 'research', 'research']
        original = deepcopy(failed.analyst_pack['attempts'])
        fixed = Model()
        result = prepare_analyst_pack(store, lead, fixed)
        assert result.analyst_pack['status'] == 'complete'
        assert fixed.calls == ['research', 'work', 'founder', 'review']
        assert set(result.analyst_pack['attempts'][len(original)]['answer']) == {'decision'}
        assert result.analyst_pack['attempts'][:len(original)] == original


def test_changed_contract_revalidates_original_candidates_and_rereviews(tmp_path, monkeypatch):
    import agents.authored_preparation as authored
    with Store(tmp_path/'test.db') as store:
        lead = company(store); model = Model()
        first = prepare_analyst_pack(store, lead, model)
        # Existing live packs predate these optional diagnostic settings.
        first.analyst_pack['generation_config'].pop('combined_draft')
        first.analyst_pack['generation_config'].pop('natural_reasoning')
        store.save_workspace(first, expected_revision=first.revision)
        originals = deepcopy(first.analyst_pack['attempts'])
        monkeypatch.setattr(authored, 'CONTRACT', 'new-validation-contract')
        updated = prepare_analyst_pack(store, lead, model)
        assert updated.analyst_pack['status'] == 'complete'
        assert model.calls == ['research', 'work', 'founder', 'review', 'review']
        assert updated.analyst_pack['attempts'][:4] == originals
        assert updated.analyst_pack_history[-1]['attempts'] == originals


def test_numbered_steps_do_not_become_company_figures_but_actual_figures_still_fail(tmp_path):
    import pytest
    from agents.authored_preparation import validate_prose
    model = Model()
    model.data['work']['first']['action'] = 'Step 1: Read the requested reservation records. Step 2: Match dates to room availability. Step 3: Investigate unfulfilled reservations with the founders.'
    with Store(tmp_path/'test.db') as store:
        w = prepare_analyst_pack(store, company(store), model)
        assert w.analyst_pack['status'] == 'complete', w.analyst_pack.get('stop_reason')
        assert w.analyst_pack['sections']['readiness.action_a']['content']['action'] == model.data['work']['first']['action']
        model.data['work']['first']['action'] += ' The company has 99 properties.'
        with pytest.raises(ValueError, match='99'):
            validate_prose('work', model.data['work'], w.analyst_pack['record']['facts'])


class OverlongField(Model):
    """Replay a nested length defect; never used by the runtime writer."""
    def __init__(self, fail_calls=1):
        super().__init__()
        self.fail_calls = fail_calls
        self.inputs = []

    def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
        phase = task.removeprefix('authored_')
        self.calls.append(phase)
        self.inputs.append(json.loads(evidence))
        value = deepcopy(self.data[phase])
        if phase == 'research' and self.calls.count(phase) <= self.fail_calls:
            value['economics']['unknown_economics'] = 'Request booking contracts and dated invoice records. ' * 8

        def select(data, model):
            from pydantic import BaseModel
            return {k: select(data[k], f.annotation)
                    if isinstance(f.annotation, type) and issubclass(f.annotation, BaseModel)
                    else data[k] for k, f in model.model_fields.items()}

        value = select(value, schema)
        self.last_response_text = json.dumps(value)
        return schema.model_validate(value)


def test_overlong_field_repaired_without_rewriting_other_model_fields(tmp_path):
    import pytest
    with Store(tmp_path/'test.db') as store:
        model = OverlongField()
        w = prepare_analyst_pack(store, company(store), model)
        pack = w.analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        original, repair = pack['attempts'][:2]
        assert original['failure_kind'] == 'schema_validation'
        assert len(original['answer']['economics']['unknown_economics']) > 350
        with pytest.raises(ValueError, match='successful'):
            response_answer(pack['attempts'], original['id'])
        assert repair['answer'] == {'economics': {'unknown_economics': answers()['research']['economics']['unknown_economics']}}
        assert model.inputs[1]['answer_to_correct'] == original['answer']
        reconstructed = authored_answer(pack['attempts'], pack['authored']['research'])
        assert reconstructed['business'] == original['answer']['business']
        assert reconstructed['economics']['revenue_mechanism'] == original['answer']['economics']['revenue_mechanism']
        assert pack['generation_metrics']['first_attempt_contract_pass'] is False
        assert pack['generation_metrics']['writing_repair_calls'] == 1
        assert model.calls == ['research', 'research', 'work', 'founder', 'review']
        # Unaccepted original text cannot be resurrected by changing the display.
        pack['sections']['research.economics']['content']['unknown_economics'] = original['answer']['economics']['unknown_economics']
        assert validate_saved_sections(pack)['status'] == 'partial'


def test_invalid_leaf_patch_remains_candidate_and_resume_repairs_it(tmp_path):
    with Store(tmp_path/'test.db') as store:
        lead = company(store)
        first = prepare_analyst_pack(store, lead, OverlongField(fail_calls=2), budget=PreparationBudget(max_calls=2))
        assert first.analyst_pack['sections'] == {}
        originals = deepcopy(first.analyst_pack['attempts'])
        assert len(originals) == 3
        assert all(a['failure_kind'] == 'schema_validation' for a in originals[:2])
        assert originals[2]['routing']['invoked'] is False
        assert 'model-call limit' in originals[2]['error']
        fixed = OverlongField(fail_calls=0)
        resumed = prepare_analyst_pack(store, lead, fixed)
        pack = resumed.analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert pack['attempts'][:3] == originals
        assert pack['attempts'][3]['answer'] == {'economics': {'unknown_economics': answers()['research']['economics']['unknown_economics']}}
        assert fixed.calls == ['research', 'work', 'founder', 'review']
        assert pack['generation_metrics']['first_attempt_contract_pass'] is False


def test_invalid_candidate_cannot_bypass_citation_checks_or_raw_integrity(tmp_path):
    with Store(tmp_path/'test.db') as store:
        lead = company(store)
        model = OverlongField(fail_calls=0)
        model.data['research']['business']['fact_ids'] = ['S999']
        pack = prepare_analyst_pack(store, lead, model).analyst_pack
        assert pack['status'] == 'partial'
        assert pack['sections'] == {}
        assert pack['generation_metrics']['first_attempt_contract_pass'] is False

    with Store(tmp_path/'other.db') as store:
        w = prepare_analyst_pack(store, company(store), OverlongField())
        assert w.analyst_pack['status'] == 'complete'
        w.analyst_pack['attempts'][0]['raw_response'] = '{}'
        assert validate_saved_sections(w.analyst_pack)['status'] == 'partial'


def test_missing_nested_field_uses_model_replacement_without_inventing_defaults(tmp_path):
    class Missing(Model):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            result = super().generate_for_task(task, instruction, evidence, schema, **kwargs)
            if len(self.calls) == 1:
                value = result.model_dump()
                value['economics'].pop('unknown_economics')
                self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            return result
    with Store(tmp_path/'test.db') as store:
        pack = prepare_analyst_pack(store, company(store), Missing()).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert 'unknown_economics' not in pack['attempts'][0]['answer']['economics']
        assert pack['authored']['research']['response_id'] == pack['attempts'][1]['id']
        assert pack['generation_metrics']['first_attempt_contract_pass'] is False


def test_denied_inference_is_not_counted_as_an_executed_repair(tmp_path):
    with Store(tmp_path/'test.db') as store:
        pack = prepare_analyst_pack(store, company(store), Model()).analyst_pack
        pack['attempts'].append({'id': 'denied', 'task': 'authored_work',
                                 'routing': {'invoked': False}, 'error': 'Diagnostic disallows repair.'})
        validate_saved_sections(pack)
        assert pack['generation_metrics']['calls_by_phase']['work'] == 1
        assert pack['generation_metrics']['writing_repair_calls'] == 0
        assert pack['generation_metrics']['first_attempt_contract_pass'] is False


def test_inline_numbered_actions_do_not_hide_real_company_figures(tmp_path):
    import pytest
    from agents.authored_preparation import validate_prose
    model = Model()
    model.data['work']['first']['action'] = '1. Read reservation records. 2. Match dates to room availability. 3. Investigate unfulfilled reservations with founders.'
    with Store(tmp_path/'test.db') as store:
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        model.data['work']['first']['action'] += ' The company has 20 properties.'
        with pytest.raises(ValueError, match='20'):
            validate_prose('work', model.data['work'], pack['record']['facts'])


def test_volume_revenue_category_error_is_rejected_in_investment_case(tmp_path):
    import pytest
    from agents.authored_preparation import validate_prose
    with Store(tmp_path/'test.db') as store:
        pack = prepare_analyst_pack(store, company(store), Model()).analyst_pack
        data = answers()['research']
        data['decision']['reason_to_engage'] = 'Investigate whether the processed volume reflects gross or net revenue before proposing work.'
        with pytest.raises(ValueError, match='Processed volume'):
            validate_prose('research', data, pack['record']['facts'])
        data['decision']['reason_to_engage'] = 'Processed volume is not company revenue; reservation demand may justify investigating actual earned fees and costs.'
        validate_prose('research', data, pack['record']['facts'])


def test_source_label_variation_does_not_bypass_separate_citation_fields(tmp_path):
    import pytest
    from agents.authored_preparation import validate_prose
    with Store(tmp_path/'test.db') as store:
        pack = prepare_analyst_pack(store, company(store), Model()).analyst_pack
        data = answers()['research']
        data['business']['text'] += ' Sources S[1] attribute these claims.'
        with pytest.raises(ValueError, match='source labels'):
            validate_prose('research', data, pack['record']['facts'])


def test_inference_compaction_preserves_distinct_prices_and_original_records():
    from agents.preparation_sources import compact_repeated_blocks, inference_facts
    block = 'Standard\n\nA transaction fee applies.\n\nTax is excluded.'
    distinct = 'Standard\n\nA monthly fee applies.\n\nTax is included.'
    quote = block + '\n\n' + block + '\n\n' + distinct
    facts = [{'id': 'S1', 'quote': quote, 'status': 'source_reported', 'category': 'commercial_terms'}]
    original = deepcopy(facts)
    compacted = inference_facts(facts)
    assert compacted[0]['quote'] == block + '\n\n' + distinct
    assert facts == original
    assert compact_repeated_blocks(distinct) == distinct


class CombinedModel(Model):
    combined_draft = True

    def __init__(self):
        super().__init__()
        self.data['draft'] = {phase: self.data[phase] for phase in ('research', 'work', 'founder')}

    def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
        if task == 'authored_review':
            self.data['review']['method_inputs'] = {key: {
                'method': 'other', 'negotiated_pricing_in_scope': False,
                'recognized_revenue_in_scope': False, 'requested_inputs': []}
                for key in ('first', 'second')}
            self.data['review']['checks'] = {key: {
                'verdict': 'pass',
                'source_check': 'The cited fixture passage supports the description of hotel operations.',
                'reasoning_check': 'The proposed record review addresses the stated operational question.'}
                for key in json.loads(evidence)['sections']}
        return super().generate_for_task(task, instruction, evidence, schema, **kwargs)


def test_combined_draft_keeps_exact_authorship_and_reuses_cache(tmp_path):
    with Store(tmp_path/'test.db') as store:
        lead = company(store)
        model = CombinedModel()
        pack = prepare_analyst_pack(store, lead, model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'review']
        assert pack['generation_metrics']['first_attempt_contract_pass'] is True
        for phase, reference in pack['authored'].items():
            assert reference['response_phase'] == phase
            assert authored_answer(pack['attempts'], reference) == pack['attempts'][0]['answer'][phase]
        assert len(pack['sections']) == 9
        prepare_analyst_pack(store, lead, model)
        assert model.calls == ['draft', 'review']
        pack['attempts'][0]['raw_response'] = '{}'
        assert validate_saved_sections(pack)['status'] == 'partial'


def test_search_turns_do_not_consume_the_six_task_call_review_allowance(tmp_path):
    from agents.preparation_budget import ACTIVE_BUDGET
    class RequestCounted(CombinedModel):
        def generate_for_task(self, *args, **kwargs):
            ACTIVE_BUDGET.get().start_request()
            return super().generate_for_task(*args, **kwargs)
    # A navigation task used three turns, link recovery one, and an earlier
    # bounded transport request one. The two remaining draft/review requests
    # still fit, without resetting the original clock or task counters.
    budget = PreparationBudget(max_calls=6, max_requests=8)
    budget.calls, budget.requests = 3, 5
    with Store(tmp_path/'test.db') as store:
        model = RequestCounted()
        pack = prepare_analyst_pack(store, company(store), model, budget=budget).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'review']
        assert budget.calls == 5 and budget.requests == 7
        assert budget.max_calls == 6 and budget.max_requests == 8


def test_invalid_review_gets_one_recorded_model_correction_without_rewriting_draft(tmp_path):
    class ExtraReviewField(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            result = super().generate_for_task(task, instruction, evidence, schema, **kwargs)
            if task == 'authored_review' and self.calls.count('review') == 1:
                value = result.model_dump()
                value['checks']['diligence.request_a']['question'] = 'Unexpected echoed question'
                self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            if task == 'authored_review':
                assert kwargs['attempt'] == 1
                assert 'Unexpected echoed question' in evidence
            return result
    with Store(tmp_path/'test.db') as store:
        model = ExtraReviewField()
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'review', 'review']
        assert pack['attempts'][1]['failure_kind'] == 'schema_validation'
        assert pack['author_review']['response_id'] == pack['attempts'][2]['id']
        for phase, reference in pack['authored'].items():
            assert authored_answer(pack['attempts'], reference) == pack['attempts'][0]['answer'][phase]


def test_invalid_input_annotation_corrects_the_review_not_the_company_draft(tmp_path):
    class BadAnnotation(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            result = super().generate_for_task(task, instruction, evidence, schema, **kwargs)
            if task == 'authored_review' and self.calls.count('review') == 1:
                value = result.model_dump()
                value['method_inputs']['first']['requested_inputs'] = [{'role': 'transactions', 'request_quote': 'room availability logs'}]
                self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            if task == 'authored_review':
                assert 'method_inputs' in json.loads(evidence)['correction_required']
            return result
    with Store(tmp_path/'test.db') as store:
        model = BadAnnotation()
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'review', 'review']
        for phase, ref in pack['authored'].items():
            assert authored_answer(pack['attempts'], ref) == pack['attempts'][0]['answer'][phase]
        assert pack['author_review']['response_id'] == pack['attempts'][-1]['id']


def test_reviewer_cannot_treat_its_own_annotation_as_a_company_prose_defect(tmp_path):
    class MisplacedIssue(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            result = super().generate_for_task(task, instruction, evidence, schema, **kwargs)
            if task == 'authored_review' and self.calls.count('review') == 1:
                value = result.model_dump()
                value.update(verdict='revise', issues=[{'section': 'diligence.request_b',
                    'field': 'method_inputs.second', 'explanation': 'Correct my summary-account annotation, not the company record request.'}])
                self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            return result
    with Store(tmp_path/'test.db') as store:
        model = MisplacedIssue()
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'review', 'review']
        assert pack['attempts'][1]['failure_kind'] == 'schema_validation'
        for phase, ref in pack['authored'].items():
            assert authored_answer(pack['attempts'], ref) == pack['attempts'][0]['answer'][phase]


def test_combined_draft_repairs_one_field_without_replacing_other_phases(tmp_path):
    class LongField(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            if task == 'authored_draft':
                value = deepcopy(self.data['draft'])
                value['research']['economics']['unknown_economics'] = 'Unknown records. ' * 30
                self.calls.append('draft')
                self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            if task == 'authored_research':
                self.calls.append('research')
                value = {'economics': {'unknown_economics': self.data['research']['economics']['unknown_economics']}}
                self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            return super().generate_for_task(task, instruction, evidence, schema, **kwargs)
    with Store(tmp_path/'test.db') as store:
        model = LongField()
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'research', 'review']
        assert pack['generation_metrics']['first_attempt_contract_pass'] is False
        assert pack['generation_metrics']['writing_repair_calls'] == 1
        assert pack['attempts'][0]['failure_kind'] == 'schema_validation'
        for phase in ('work', 'founder'):
            assert authored_answer(pack['attempts'], pack['authored'][phase]) == pack['attempts'][0]['answer'][phase]


def test_a_schema_invalid_correction_is_repaired_within_the_shared_budget(tmp_path):
    class RepeatedLength(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            if task == 'authored_draft':
                value = deepcopy(self.data['draft'])
                value['founder']['observation']['reported_observation'] = 'Long observation. ' * 30
                self.calls.append('draft'); self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            if task == 'authored_founder':
                self.calls.append('founder')
                value = {'observation': {'reported_observation': 'Still long. ' * 40 if self.calls.count('founder') == 1 else self.data['founder']['observation']['reported_observation']}}
                assert 'Ignore whole-draft word targets' in instruction
                self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            return super().generate_for_task(task, instruction, evidence, schema, **kwargs)
    with Store(tmp_path/'test.db') as store:
        model = RepeatedLength()
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'founder', 'founder', 'review']
        assert pack['attempts'][1]['failure_kind'] == 'schema_validation'
        assert authored_answer(pack['attempts'], pack['authored']['founder']) == answers()['founder']


def test_review_repairs_multiple_phases_in_one_call_with_exact_patch_provenance(tmp_path):
    class MultiCorrection(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            if task == 'authored_review':
                first = self.calls.count('review') == 0
                self.data['review'].update(verdict='revise' if first else 'pass', issues=[
                    {'section': 'research.business', 'field': 'text', 'explanation': 'Clarify which source describes the hotel operations.'},
                    {'section': 'readiness.action_a', 'field': 'action', 'explanation': 'Clarify how reservation dates match the availability records.'}
                ] if first else [])
            if task == 'authored_draft' and kwargs.get('attempt'):
                assert set(schema.model_fields) == {'research', 'work'}
                self.data['draft']['research']['business']['text'] = 'The supplied website describes Hotel Example as a hotel operator. Customer segments remain unspecified.'
                self.data['draft']['work']['first']['action'] = 'Match each reservation date to the room availability log for that property. Record unexplained date or room discrepancies for discussion.'
            return super().generate_for_task(task, instruction, evidence, schema, **kwargs)
    with Store(tmp_path/'test.db') as store:
        model = MultiCorrection()
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'review', 'draft', 'review']
        assert authored_answer(pack['attempts'], pack['authored']['founder']) == pack['attempts'][0]['answer']['founder']
        assert authored_answer(pack['attempts'], pack['authored']['research'])['business']['text'] == pack['attempts'][2]['answer']['research']['business']['text']
        assert authored_answer(pack['attempts'], pack['authored']['research'])['business']['fact_ids'] == pack['attempts'][0]['answer']['research']['business']['fact_ids']
        pack['attempts'][2]['raw_response'] = '{}'
        assert validate_saved_sections(pack)['status'] == 'partial'


def test_malformed_patch_does_not_poison_last_model_candidate():
    from agents.authored_preparation import usable_candidate_reference
    from agents.model_authorship import digest
    base=answers()['founder']
    invalid={'$FUNCTION_NAME':'StructuredOutput','$PARAMETER_NAME':'proposal'}
    attempts=[]
    for index,value in enumerate((base,invalid),1):
        raw=json.dumps(value)
        attempts.append({'id':f'response_{index}','answer':value,'raw_response':raw,'response_hash':digest(raw),
                         **({'error':'Schema mismatch','failure_kind':'schema_validation'} if index==2 else {})})
    reference={'response_id':'response_1','patch_response_ids':['response_2']}
    recovered=usable_candidate_reference(attempts,reference)
    assert recovered=={'response_id':'response_1'}
    assert authored_answer(attempts,recovered)==base
    assert attempts[1]['answer']==invalid and reference['patch_response_ids']==['response_2']


def test_review_cannot_pass_when_a_section_check_requires_revision(tmp_path):
    class ConflictingReview(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            result = super().generate_for_task(task, instruction, evidence, schema, **kwargs)
            if task == 'authored_review':
                value = result.model_dump()
                value['checks']['research.business']['verdict'] = 'revise'
                self.last_response_text = json.dumps(value)
                return schema.model_validate(value)
            return result
    with Store(tmp_path/'test.db') as store:
        pack = prepare_analyst_pack(store, company(store), ConflictingReview()).analyst_pack
        assert pack['status'] == 'partial'
        assert 'without identifying a defect' in pack['stop_reason']


def test_fenced_model_answers_preserve_provenance_and_still_validate(tmp_path):
    class Fenced(CombinedModel):
        def generate_for_task(self, *args, **kwargs):
            result = super().generate_for_task(*args, **kwargs)
            self.last_response_text = '```json\n' + self.last_response_text + '\n```'
            return result
    with Store(tmp_path/'test.db') as store:
        pack = prepare_analyst_pack(store, company(store), Fenced()).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert pack['attempts'][0]['raw_response'].startswith('```json\n')
        assert authored_answer(pack['attempts'], pack['authored']['research']) == answers()['research']


def test_review_of_projected_input_repairs_only_original_records_field(tmp_path):
    class InputCorrection(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            if task == 'authored_review' and self.calls.count('review') == 0:
                self.data['review'].update(verdict='revise', issues=[{
                    'section': 'readiness.action_a', 'field': 'required_input',
                    'explanation': 'Specify which date fields are needed to align reservations and room records.'}])
            elif task == 'authored_review':
                self.data['review'].update(verdict='pass', issues=[])
            if task == 'authored_work':
                self.data['work']['first']['records_to_request'] += ' Include arrival and departure dates.'
            return super().generate_for_task(task, instruction, evidence, schema, **kwargs)
    with Store(tmp_path/'test.db') as store:
        model = InputCorrection()
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'review', 'work', 'review']
        assert set(pack['attempts'][2]['answer']) == {'first'}
        assert set(pack['attempts'][2]['answer']['first']) == {'records_to_request'}
        original = pack['attempts'][0]['answer']['work']
        corrected = authored_answer(pack['attempts'], pack['authored']['work'])
        assert corrected['second'] == original['second']
        assert corrected['first']['action'] == original['first']['action']


def test_single_method_correction_can_reconcile_its_entire_plan(tmp_path):
    class MethodCorrection(CombinedModel):
        def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
            if task == 'authored_review':
                first = self.calls.count('review') == 0
                self.data['review'].update(verdict='revise' if first else 'pass', issues=[{
                    'section': 'readiness.action_a', 'field': 'action',
                    'explanation': 'Compare reservation fulfilment across distinct periods with consistent definitions.'
                }] if first else [])
            if task == 'authored_work':
                feedback = json.loads(evidence)['correction_required']
                assert set(feedback['first']) == set(answers()['work']['first'])
                assert 'second' not in feedback
                self.data['work']['first'].update(
                    records_to_request='Request dated reservation and room availability records for comparable earlier and later periods.',
                    action='Match reservations to available rooms separately in each period, using the same fulfilment definition. Compare exceptions without assuming a cause.',
                    output='A comparison of fulfilment exceptions across the earlier and later periods.')
            return super().generate_for_task(task, instruction, evidence, schema, **kwargs)
    with Store(tmp_path/'test.db') as store:
        model = MethodCorrection()
        pack = prepare_analyst_pack(store, company(store), model).analyst_pack
        assert pack['status'] == 'complete', pack.get('stop_reason')
        assert model.calls == ['draft', 'review', 'work', 'review']
        original = pack['attempts'][0]['answer']['work']
        corrected = authored_answer(pack['attempts'], pack['authored']['work'])
        assert corrected['first'] == pack['attempts'][2]['answer']['first']
        assert corrected['first']['records_to_request'] != original['first']['records_to_request']
        assert corrected['second'] == original['second']
