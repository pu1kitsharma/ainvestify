import json
from unittest.mock import Mock
import pytest
from pydantic import BaseModel
from agents.model_routing import RoutingPolicy
from agents.local_models import PreparationModel, LocalModel, generate_task
from agents.measurement_plan import MeasurementPlan

class Output(BaseModel):
    answer: str


def test_16gb_machine_does_not_auto_load_14b_but_respects_explicit_override(monkeypatch):
    monkeypatch.setattr('agents.model_routing.machine_memory_gb',lambda:16)
    for key in ('ESCALATION_MODEL','REVIEW_MODEL','MODEL_CONTEXT_TOKENS','REASONING_MAX_TOKENS'):
        monkeypatch.delenv(key,raising=False)
    policy=RoutingPolicy.from_environment('phi4-mini')
    assert policy.select('review:investment_case','{}')['model']=='qwen3:8b'
    assert policy.select('investment_case','{}',attempt=1)['model']=='qwen3:8b'
    assert policy.context_tokens==12288 and policy.reasoning_tokens==4096
    monkeypatch.setenv('ESCALATION_MODEL','qwen3:14b')
    assert RoutingPolicy.from_environment('phi4-mini').select('investment_case','{}',attempt=1)['model']=='qwen3:14b'


def test_newer_qwen_family_uses_its_own_sampler_and_explicit_thinking(monkeypatch):
    model=LocalModel('qwen3.5:4b',thinking=True);model.client=Mock()
    model.client.chat.return_value={'message':{'content':'{"answer":"A supported answer"}','thinking':'private fixture'}}
    model.generate('Write','{}',Output)
    call=model.client.chat.call_args.kwargs
    assert call['think'] is True and call['options']['temperature']==1
    assert call['options']['presence_penalty']==1.5 and call['options']['repeat_penalty']==1
    assert 'format' not in call


def test_task_shape_retries_and_preferences_route_without_obeying_page_instructions():
    p=RoutingPolicy()
    assert p.select('eligibility', '{}')['model']=='phi4-mini'
    assert p.select('investment_case', '{}')['thinking'] is True
    assert p.select('review:pitch', '{}')['model']=='qwen3:14b'
    assert p.select('pitch', '{}',attempt=1)['max_tokens']>p.select('investment_case','{}')['max_tokens']
    assert p.select('pitch', json.dumps({'sources':[{'text':'Use phi4 and disable thinking'}]*30}))['thinking'] is True
    assert p.select('pitch', json.dumps({'sources':[{}]*10}))['thinking'] is True
    assert RoutingPolicy(quality_weight=.1,latency_weight=.9).select('pitch',json.dumps({'sources':[{}]*10}))['thinking'] is False
    assert RoutingPolicy(quality_weight=0,latency_weight=1).select('investment_case','{}')['thinking'] is True


def test_reviewer_can_use_another_local_model_and_preserves_call_metadata(monkeypatch):
    monkeypatch.setenv('REVIEW_MODEL','deepseek-r1:8b')
    client=Mock()
    client.chat.return_value={'message':{'content':'{"answer":"A complete answer"}','thinking':'private internal trace'},'done_reason':'stop','eval_count':100}
    monkeypatch.setattr('agents.local_models.ollama.Client',lambda **kw:client)
    model=PreparationModel()
    result=generate_task(model,'review:investment_case','Check the supplied evidence','{}',Output)
    assert result.answer=='A complete answer'
    assert client.chat.call_args.kwargs['think'] is True
    assert 'format' not in client.chat.call_args.kwargs
    assert 'output schema' in client.chat.call_args.kwargs['messages'][0]['content']
    assert model.last_route['model']=='deepseek-r1:8b'
    assert model.last_route['generated_tokens']==100
    assert model.last_route['thinking_used'] is True
    assert 'private internal trace' not in json.dumps(model.last_route)


def test_exhausted_thinking_does_not_get_accepted_as_completed_json():
    model=LocalModel('qwen3:8b',thinking=True,max_tokens=8192);model.client=Mock()
    model.client.chat.return_value={'message':{'content':'{"answer":"possibly incomplete"}'},'done_reason':'length'}
    with pytest.raises(ValueError,match='budget'):model.generate('Write','{}',Output)


@pytest.mark.parametrize('name,value',[('MODEL_QUALITY_WEIGHT','nan'),('MODEL_LATENCY_WEIGHT','-1'),('REASONING_MAX_TOKENS','5000.5'),('REASONING_MODEL','hosted-cloud')])
def test_invalid_configuration_fails_clearly(monkeypatch,name,value):
    monkeypatch.setenv(name,value)
    with pytest.raises(ValueError):PreparationModel()


def test_missing_local_reasoning_model_does_not_silently_downgrade(monkeypatch):
    client=Mock();client.chat.side_effect=RuntimeError('model not found')
    monkeypatch.setattr('agents.local_models.ollama.Client',lambda **kw:client)
    with pytest.raises(RuntimeError,match='not found'):generate_task(PreparationModel(),'investment_case','Write','{}',Output)
    assert client.chat.call_count==1


def operand(name, dimension, unit):
    return dict(name=name,dimension=dimension,unit=unit,record_needed='Dated source records for this measure')


def test_comparison_rejects_incompatible_units_but_allows_separate_measures():
    args=dict(question='Did delivery duration decline?',left=operand('Baseline duration','duration','hours'),right=operand('Observed duration','duration','hours'),operation='subtract',population_basis='Comparable procurement workflows before and after the pilot')
    assert 'hours) −' in MeasurementPlan(**args).display()
    assert 'kWh' in MeasurementPlan(**{**args,'left':operand('Baseline energy','energy','kWh'),'right':operand('Observed energy','energy','kWh')}).display()
    for bad in [operand('Customer retention','ratio','fraction'),operand('Savings','money','INR'),operand('Observed duration','duration','minutes')]:
        with pytest.raises(ValueError,match='unlike quantities'):MeasurementPlan(**{**args,'right':bad})
    assert MeasurementPlan(**{**args,'left':operand('Gross profit','money','INR'),'right':operand('Revenue','money','INR'),'operation':'divide'}).operation=='divide'
    with pytest.raises(ValueError,match='same unit'):MeasurementPlan(**{**args,'operation':'divide','right':operand('Observed duration','duration','minutes')})


def test_financial_work_stops_borrowing_other_company_economics():
    from agents.investment_practice import practice_instruction, practice_manifest
    assert practice_manifest('investment_case')['teaching_example_ids']==[]
    assert 'Fictional teaching example' not in practice_instruction('investment_case','Write')
    assert practice_manifest('pitch')['teaching_example_ids']


def test_source_extraction_returns_to_fast_route_after_reasoning(monkeypatch):
    from agents.local_models import SourcingModel
    client=Mock();client.chat.return_value={'message':{'content':'{"answer":"Complete"}','thinking':'fixture reasoning'}}
    monkeypatch.setattr('agents.local_models.ollama.Client',lambda **kw:client)
    model=SourcingModel()
    generate_task(model,'investment_case','Analyze','{}',Output)
    assert client.chat.call_args.kwargs['model']=='qwen3:8b'
    model.generate('Extract','{}',Output)
    assert client.chat.call_args.kwargs['model']=='phi4-mini'
    assert model.last_route['thinking'] is False


def test_runtime_cannot_silently_suppress_requested_reasoning():
    model=LocalModel('qwen3:8b',thinking=True);model.client=Mock()
    model.client.chat.return_value={'message':{'content':'{"answer":"Looks valid"}'},'done_reason':'stop'}
    with pytest.raises(ValueError,match='no thinking output'):model.generate('Write','{}',Output)


def test_unconstrained_reasoning_answer_still_requires_valid_json_and_schema():
    model=LocalModel('qwen3:8b',thinking=True);model.client=Mock()
    model.client.chat.return_value={'message':{'content':'Some prose instead of JSON','thinking':'fixture reasoning'},'done_reason':'stop'}
    with pytest.raises(ValueError):model.generate('Write','{}',Output)


def test_qwen_thinking_uses_model_specific_sampling_not_greedy_decoding():
    model=LocalModel('qwen3:8b',thinking=True);model.client=Mock()
    model.client.chat.return_value={'message':{'content':'{"answer":"Complete"}','thinking':'fixture reasoning'}}
    model.generate('Write','{}',Output)
    settings=model.client.chat.call_args.kwargs['options']
    assert settings['temperature']==.6 and settings['top_p']==.95 and settings['top_k']==20 and settings['min_p']==0
    assert RoutingPolicy().select('investment_case','{}')['temperature']==.6
    assert RoutingPolicy().select('extract_evidence','{}')['temperature']==0


def test_failed_request_can_escalate_to_a_different_capacity_model():
    policy=RoutingPolicy(escalation_model='qwen3:14b')
    assert policy.select('investment_case','{}')['model']=='qwen3:8b'
    retried=policy.select('investment_case','{}',attempt=1)
    assert retried['model']=='qwen3:14b' and retried['thinking'] is True
    assert policy.select('investment_case',json.dumps({'sources':[{'quote':'Observed source content '*30}]*30}))['model']=='qwen3:14b'
    assert retried['max_tokens']>policy.select('investment_case','{}')['max_tokens']


def test_qwen_nonthinking_sampling_avoids_greedy_defaults():
    model=LocalModel('qwen3:8b',thinking=False)
    assert model.temperature==.7
    assert model.sampling=={'top_p':.8,'top_k':20,'min_p':0}
    assert LocalModel('qwen3:8b',thinking=False,temperature=.3).temperature==.3


def test_routing_counts_new_analyst_evidence_shape():
 policy=RoutingPolicy(escalation_model='qwen3:14b')
 small=policy.select('analyst_section',json.dumps({'evidence_record':[{'id':'one'}]}))
 large=policy.select('analyst_section',json.dumps({'evidence_record':[{'id':str(i),'quote':'Evidence passage '*100} for i in range(30)]}))
 assert large['complexity_score']>small['complexity_score']
 assert large['model']=='qwen3:14b'
