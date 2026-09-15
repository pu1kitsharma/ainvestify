"""Recorded-model evaluations must exercise the production repair contract."""
import json
import sys

import pytest

from agents.investment_case import (work_product_schema, preparation_failure_message,
                                   revision_context, rejected_draft_diagnostics)
from scripts import evaluate_reasoning_route as evaluation
from tests.test_investment_case import Model


@pytest.mark.parametrize('stage', ['investment_case', 'funding_outline'])
def test_narrative_contract_rejects_measurement_plan(stage):
    schema = work_product_schema(stage, ['E1'])
    assert schema.model_json_schema()['properties']['measurements']['maxItems'] == 0
    assert work_product_schema('commercial_test', ['E1']).model_json_schema()['properties']['measurements']['maxItems'] == 3


def run_evaluation(tmp_path, monkeypatch, model):
    source = tmp_path / 'input.json'
    output = tmp_path / 'output.json'
    source.write_text(json.dumps({'company': 'Example hotels', 'payload': {
        'company': 'Example hotels', 'sources': [
            {'id': 'E1', 'quote': 'The company operates hotels.', 'field': 'offering'}]}}))
    monkeypatch.setattr(sys, 'argv', ['evaluate', '--fresh', '--input', str(source), '--output', str(output)])
    monkeypatch.setattr(evaluation, 'PreparationModel', lambda: model)
    result = evaluation.main()
    return result, json.loads(output.read_text())


@pytest.mark.parametrize('schema_failure', [False, True])
def test_evaluation_repairs_rejected_final_answer_using_production_context(tmp_path, monkeypatch, schema_failure):
    class RepairModel(Model):
        last_route = {}
        last_response_text = ''

        def generate(self, instruction, payload, schema):
            data = json.loads(payload)
            result = super().generate(instruction, payload, schema)
            if 'sections' in schema.model_fields:
                assert schema.model_json_schema()['properties']['measurements']['maxItems'] == 0
                if 'revision_feedback' not in data:
                    broken = result.model_dump()
                    if schema_failure:
                        broken['missing_inputs'][0]['record'] = 'ARR'
                    else:
                        broken['purpose'] = 'This hotel has 999 customers with substantial growth.'
                    self.last_response_text = json.dumps(broken)
                    return schema.model_validate_json(self.last_response_text)
                assert 'rejected draft is not company evidence' in instruction
                if schema_failure:
                    assert 'ARR' in data['draft_to_revise']
                    assert 'missing_inputs.0.record' in data['revision_feedback']
                else:
                    assert '999' in data['draft_to_revise']['purpose']
                    assert 'purpose' in data['revision_feedback']
            return result

    code, report = run_evaluation(tmp_path, monkeypatch, RepairModel())
    assert code == 0 and report['status'] == 'checked_draft'
    assert report['live_data_updated'] is False
    assert len(report['attempts']) == 2
    assert report['attempts'][0]['error']
    assert report['schema_sha256'] and report['input_sha256']


def test_evaluation_failure_is_not_a_successful_exit(tmp_path, monkeypatch):
    class FailedModel(Model):
        last_route = {}
        last_response_text = ''

        def generate(self, instruction, payload, schema):
            raise ValueError('Inference unavailable')

    code, report = run_evaluation(tmp_path, monkeypatch, FailedModel())
    assert code == 1 and report['status'] == 'failed'
    assert len(report['attempts']) == 2
    assert 'revised_draft' not in report


def test_empty_pack_does_not_claim_saved_documents():
    assert preparation_failure_message({'products': {}}).startswith('No preparation documents passed validation.')
    assert preparation_failure_message({'products': {'investment_case': {}}}).startswith('1 working draft is saved;')


def test_schema_failure_does_not_hide_other_repair_feedback():
    payload = {'sources': [{'id': 'E1', 'field': 'offering', 'quote': 'The company operates hotels.'}]}
    draft = Model().generate('', json.dumps(payload), work_product_schema('investment_case', ['E1'])).model_dump()
    draft['missing_inputs'][0]['record'] = 'CAC'
    draft['purpose'] = 'The company has 999 customers.'
    draft['sections'][0]['content'] = 'The company handles bookings, reducing manual effort and errors.'
    context = revision_context(payload, 'record is too short', raw_response=json.dumps(draft))
    assert 'record is too short' in context['revision_feedback']
    assert 'actual record' in context['revision_feedback']
    assert '999' in context['revision_feedback']
    assert 'Attribute the claimed benefit' in context['revision_feedback']
    with pytest.raises(ValueError):
        work_product_schema('investment_case', ['E1']).model_validate_json(context['draft_to_revise'])
    assert 'draft_to_revise' not in payload


@pytest.mark.parametrize('raw', ['null', '{', '[]', '{"sections": "incorrect shape"}'])
def test_malformed_final_answer_cannot_break_repair_diagnostics(raw):
    assert rejected_draft_diagnostics(raw, {'sources': []}) == ''


def test_frozen_workflow_budget_limits_actual_calls_and_section_repairs():
    from scripts.evaluate_analyst_workflows import EvaluationBudget,SECTIONS
    class Stub:
        name='stub'
        last_route={}
        last_response_text=''
        def generate_for_task(self,*args,**kwargs):return 'answer'
    bounded=EvaluationBudget(Stub(),max_corrections=1,max_calls=4)
    first=SECTIONS[0][3];second=SECTIONS[1][3]
    assert bounded.generate_for_task('analyst_section',first,'{}',None)=='answer'
    assert bounded.generate_for_task('analyst_section','Repair. '+first,'{}',None,attempt=1)=='answer'
    with pytest.raises(ValueError,match='no further corrections'):
        bounded.generate_for_task('analyst_section','Repair. '+first,'{}',None,attempt=2)
    assert bounded.calls==2 and bounded.last_route['budget_denied']
    bounded.generate_for_task('analyst_section',second,'{}',None)
    bounded.generate_for_task('analyst_section','Repair. '+second,'{}',None,attempt=1)
    with pytest.raises(RuntimeError,match='call budget'):
        bounded.generate_for_task('analyst_section',first,'{}',None)
    assert bounded.calls==4


def test_full_workflow_evaluation_budgets_collection_and_preserves_original_report(tmp_path,monkeypatch):
    from scripts import evaluate_analyst_workflows as runner
    from agents.preparation_budget import ACTIVE_BUDGET
    source=tmp_path/'cases.json';out=tmp_path/'result'
    source.write_text(json.dumps([{'id':'new','company':'Example','website':'https://example.org/',
        'sector':'test','region':'test','evidence':[]}]))
    monkeypatch.setattr(sys,'argv',['evaluate','--cases',str(source),'--output',str(out),
                                   '--collect-public','--max-seconds','2'])
    class NoInference:
        def generate_for_task(self,*args,**kwargs):raise AssertionError('No inference may follow failed collection')
    monkeypatch.setattr(runner,'PreparationModel',NoInference)
    def collection(*args,**kwargs):
        assert 0<ACTIVE_BUDGET.get().remaining()<2
        raise TimeoutError('Collection exhausted the shared deadline')
    monkeypatch.setattr(runner,'collect_preparation_evidence',collection)
    assert runner.main()==1
    path=out/'new.json';original=path.read_bytes();report=json.loads(original)
    assert report['budget']['calls']==0 and 'Collection exhausted' in report['error']
    assert ACTIVE_BUDGET.get() is None
    with pytest.raises(SystemExit):runner.main()
    assert path.read_bytes()==original
