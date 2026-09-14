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
