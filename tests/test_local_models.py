import json
from unittest.mock import Mock
import pytest
from pydantic import BaseModel,Field,ValidationError
from agents.local_models import LocalModel,generation_schema


class Output(BaseModel):
    summary:str=Field(min_length=5,max_length=20)


def test_decoder_does_not_clip_prose_but_original_contract_still_validates():
    spec=generation_schema(Output)
    assert 'maxLength' not in spec['properties']['summary']
    assert Output.model_json_schema()['properties']['summary']['maxLength']==20
    model=LocalModel();model.client=Mock()
    model.client.chat.return_value={'message':{'content':json.dumps({'summary':'A full sentence that exceeds the allowed field length.'})}}
    with pytest.raises(ValidationError):model.generate('Write a summary','source',Output)
    assert model.client.chat.call_args.kwargs['format']==spec


def test_local_qwen_structured_calls_use_the_budget_for_final_json(monkeypatch):
    monkeypatch.setenv('SOURCING_MODEL','qwen3:8b')
    model=LocalModel();model.client=Mock()
    model.client.chat.return_value={'message':{'content':'{"summary":"A supported summary"}'}}
    assert model.generate('Summarize','source',Output).summary=='A supported summary'
    assert model.client.chat.call_args.kwargs['think'] is False
    assert model.last_response_text=='{"summary":"A supported summary"}'


def test_preparation_model_is_separate_and_retains_explicit_local_override(monkeypatch):
    from agents.local_models import PreparationModel
    monkeypatch.setenv('SOURCING_MODEL','phi4-mini')
    monkeypatch.setenv('PREPARATION_MODEL','qwen3:8b')
    assert LocalModel().name=='phi4-mini'
    assert PreparationModel().name=='qwen3:8b'
    monkeypatch.delenv('PREPARATION_MODEL')
    assert PreparationModel().name=='phi4-mini'
    monkeypatch.setenv('PREPARATION_MODEL','hosted-cloud')
    with pytest.raises(ValueError,match='local model'):PreparationModel()


def test_nonthinking_prompt_includes_field_meanings_and_limits():
    from pydantic import Field
    class Task(BaseModel):
        records_to_request: str = Field(max_length=100,description='Name actual company-held documents and their scope.')
    model=LocalModel('phi4-mini');model.client=Mock()
    model.client.chat.return_value={'message':{'content':'{"records_to_request":"Dated billing records"}'}}
    model.generate('Prepare a diligence question','{}',Task)
    kwargs=model.client.chat.call_args.kwargs
    instruction=kwargs['messages'][0]['content']
    assert 'Name actual company-held documents and their scope.' in instruction
    assert 'maxLength' in instruction
    assert 'maxLength' not in str(kwargs['format'])


def test_failed_call_does_not_reuse_previous_response_as_repair_input():
 model=LocalModel();model.last_response_text='An earlier unrelated response';model.last_call={'generated_tokens':99};model.client=Mock();model.client.chat.side_effect=RuntimeError('Inference failed')
 with pytest.raises(RuntimeError):model.generate('Write','{}',Output)
 assert model.last_response_text==''
 assert 'generated_tokens' not in model.last_call


def test_section_profile_uses_reasoning_for_writing_and_critical_review(monkeypatch):
 from agents.local_models import AnalystModel
 calls=[]
 class Adapter:
  last_call={};last_response_text='';sampling={}
  def __init__(self,name,**kwargs):calls.append(kwargs)
  def generate(self,*args):return Output(summary='A concise summary')
 monkeypatch.setattr('agents.local_models.LocalModel',Adapter)
 m=AnalystModel('qwen3.5:4b',thinking=True)
 for task in ('record_extract','analyst_section','review:analyst_section'):m.generate_for_task(task,'Task','{}',Output)
 assert [c['thinking'] for c in calls]==[False,True,True]
 assert m.generation_config['mode']=='section_router'
 assert [c['reasoning_budget'] for c in calls]==[None,1024,1024]


def test_bounded_reasoning_reserves_answer_tokens_without_persisting_trace():
 model=LocalModel('qwen3.5:9b',thinking=True,max_tokens=1400,reasoning_budget=512)
 model.client=Mock();model.client.chat.return_value={'message':{'thinking':'Private intermediate reasoning','content':''},'done_reason':'length','eval_count':512}
 model.client.generate.return_value={'response':'{"summary":"A concise summary"}','done_reason':'stop','eval_count':30}
 assert model.generate('Write','{}',Output).summary=='A concise summary'
 first=model.client.chat.call_args.kwargs;second=model.client.generate.call_args.kwargs
 assert first['think'] is True and first['options']['num_predict']==512
 assert second['think'] is False and second['options']['num_predict']==888
 assert second['raw'] is True
 assert '<|im_start|>assistant\n<think>\nPrivate intermediate reasoning' in second['prompt']
 assert second['prompt'].endswith('</think>\n\n')
 assert second['format']==generation_schema(Output)
 assert model.last_call['answer_continuation'] and model.last_call['thinking_used']
 assert model.last_call['generated_tokens']==542
 assert 'Private intermediate' not in str(model.last_call)+model.last_response_text


def test_qwen35_continuation_does_not_discard_the_reasoning_it_just_generated():
 # Raw generation bypasses the installed native chat renderer entirely.
 model=LocalModel('qwen3.5:9b',thinking=True,max_tokens=1400,reasoning_budget=512)
 model.client=Mock()
 model.client.chat.return_value={'message':{'thinking':'private intermediate material','content':''},'done_reason':'length','eval_count':512}
 def runtime(**kwargs):
  assert kwargs['raw'] and not kwargs['think']
  assert kwargs['prompt'].endswith('private intermediate material\n</think>\n\n')
  assert 'format' in kwargs
  return {'response':'{"summary":"A concise summary"}','done_reason':'stop','eval_count':30}
 model.client.generate.side_effect=runtime
 assert model.generate('Summarize','{}',Output).summary=='A concise summary'
 assert model.client.chat.call_count==model.client.generate.call_count==1


def test_partial_final_json_continues_without_rewriting_its_prefix():
 model=LocalModel('qwen3:8b',thinking=True,max_tokens=1400,reasoning_budget=512)
 model.client=Mock();model.client.chat.side_effect=[
  {'message':{'thinking':'private','content':'{"summary":'},'done_reason':'length','eval_count':512},
  {'message':{'content':'"A concise summary"}'},'done_reason':'stop','eval_count':20}]
 assert model.generate('Write','{}',Output).summary=='A concise summary'
 second=model.client.chat.call_args_list[1].kwargs
 assert second['messages'][-1]['content'].endswith('{"summary":')
 assert 'format' not in second
 assert model.last_response_text=='{"summary":"A concise summary"}'
 assert 'private' not in model.last_response_text


def test_analyst_profile_can_use_a_distinct_installed_reviewer(monkeypatch):
 from agents.local_models import AnalystModel
 calls=[]
 class Adapter:
  last_call={};last_response_text='';sampling={}
  def __init__(self,name,**kwargs):calls.append((name,kwargs))
  def generate(self,*args):return Output(summary='A concise summary')
 monkeypatch.setattr('agents.local_models.LocalModel',Adapter)
 m=AnalystModel('qwen3.5:9b',review_model='phi4-mini')
 for task in ('analyst_section','review:analyst_section'):m.generate_for_task(task,'Task','{}',Output)
 assert [name for name,_ in calls]==['qwen3.5:9b','phi4-mini']
 assert calls[1][1]['thinking'] is False
 assert m.generation_config['review_model']=='phi4-mini'
 m.generate_for_task('analyst_section','Repair','{}',Output,attempt=1)
 assert calls[-1][0]=='qwen3.5:9b'
 assert calls[-1][1]['thinking'] is True and calls[-1][1]['reasoning_budget']==1024
 direct=AnalystModel('qwen3.5:9b',review_model='qwen3:14b',review_thinking=False)
 direct.generate_for_task('review:analyst_section','Review','{}',Output)
 assert calls[-1][0]=='qwen3:14b' and calls[-1][1]['thinking'] is False
 assert direct.generation_config['review_thinking'] is False
 with pytest.raises(ValueError,match='local'):AnalystModel('qwen3.5:9b',review_model='hosted-cloud')


def test_analyst_uses_reasoning_for_complex_work_not_simple_descriptions(monkeypatch):
 from agents.local_models import AnalystModel
 from agents.analyst_pack import Paragraph,InvestmentQuestion,Action,FounderOffer
 calls=[]
 class Adapter:
  last_call={};last_response_text='';sampling={}
  def __init__(self,name,**kwargs):calls.append(kwargs)
  def generate(self,*args):return Output(summary='A concise summary')
 monkeypatch.setattr('agents.local_models.LocalModel',Adapter)
 model=AnalystModel('qwen3.5:9b',thinking=False)
 for schema in (Paragraph,InvestmentQuestion,Action,FounderOffer):
  model.generate_for_task('analyst_section','Prepare this section','{}',schema)
 assert [row['thinking'] for row in calls]==[False,True,True,True]


def test_initial_agenda_is_fast_unless_explicit_thinking_or_repair(monkeypatch):
 from agents.local_models import AnalystModel
 calls=[]
 class Adapter:
  last_call={};last_response_text='';sampling={}
  def __init__(self,name,**kwargs):calls.append(kwargs)
  def generate(self,*args):return Output(summary='A concise summary')
 monkeypatch.setattr('agents.local_models.LocalModel',Adapter)
 model=AnalystModel('qwen3.5:9b',thinking=False)
 model.generate_for_task('analyst_agenda','Choose questions','{}',Output)
 model.generate_for_task('analyst_agenda','Repair questions','{}',Output,attempt=1)
 AnalystModel('qwen3.5:9b',thinking=True).generate_for_task('analyst_agenda','Choose questions','{}',Output)
 assert [row['thinking'] for row in calls]==[False,True,True]
 assert all(row['reasoning_budget']==1024 for row in calls[1:])
 assert model.generation_config['complex_section_thinking'] is True


def test_shared_tasks_use_short_single_model_calls_and_respect_explicit_review(monkeypatch):
 from agents.local_models import AnalystModel
 calls=[]
 class Adapter:
  last_call={};last_response_text='';sampling={}
  def __init__(self,name,**kwargs):calls.append((name,kwargs))
  def generate(self,*args):return Output(summary='A concise summary')
 monkeypatch.setattr('agents.local_models.LocalModel',Adapter)
 model=AnalystModel('qwen3.5:9b',thinking=False)
 for task in ('shared_analysis','shared_founder','shared_review'):model.generate_for_task(task,'Prepare','{}',Output)
 assert [c[1]['thinking'] for c in calls]==[False,False,False]
 assert [c[1]['max_tokens'] for c in calls]==[1200,650,900]
 assert [c[1]['reasoning_budget'] for c in calls]==[None,None,None]
 AnalystModel('qwen3.5:9b',review_model='qwen3:8b',review_thinking=True).generate_for_task('shared_review','Review','{}',Output)
 assert calls[-1][0]=='qwen3:8b' and calls[-1][1]['thinking'] is True
 distinct=AnalystModel('qwen3.5:9b',review_model='phi4-mini')
 distinct.generate_for_task('shared_review','Review','{}',Output)
 assert calls[-1][0]=='phi4-mini' and calls[-1][1]['thinking'] is False
 assert distinct.name=='qwen3.5:9b'
