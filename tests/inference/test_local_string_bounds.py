"""Opt-in decoder bounds preserve historical prompts and application checks."""
from copy import deepcopy
import json
from typing import Optional
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, Field, ValidationError

from agents.inference.local_models import LocalModel, generation_schema


class BoundedText(BaseModel):
    text: str = Field(min_length=5, max_length=20, pattern=r'^[A-Za-z ]+$')


class NestedOutput(BaseModel):
    rows: list[BoundedText]
    note: Optional[str] = Field(default=None, min_length=3, max_length=30)


def string_nodes(value):
    if isinstance(value, dict):
        if value.get('type') == 'string':
            yield value
        for child in value.values():
            yield from string_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from string_nodes(child)


def test_opt_in_keeps_nested_maximums_without_minimums_or_patterns():
    original = NestedOutput.model_json_schema()
    frozen = deepcopy(original)

    class CachedSchema:
        @staticmethod
        def model_json_schema():
            return original

    bounded = generation_schema(CachedSchema, bound_strings=True)
    assert sorted(node['maxLength'] for node in string_nodes(bounded)) == [20, 30]
    assert all('minLength' not in node and 'pattern' not in node
               for node in string_nodes(bounded))
    assert original == frozen
    assert bounded['required'] == original['required']
    assert bounded['properties']['rows']['items'] == original['properties']['rows']['items']

    legacy = generation_schema(CachedSchema)
    assert legacy == generation_schema(CachedSchema, bound_strings=False)
    assert all(not {'minLength', 'maxLength', 'pattern'} & set(node)
               for node in string_nodes(legacy))
    assert original == frozen


def test_explicit_bound_reaches_chat_and_is_recorded_without_changing_raw_text():
    model = LocalModel('qwen3.5:9b', bound_strings=True)
    model.client = Mock()
    raw = '{"text":"A concise summary"}'
    model.client.chat.return_value = {
        'message': {'content': raw}, 'done_reason': 'stop', 'eval_count': 12,
    }
    assert model.generate('Summarize', '{}', BoundedText).text == 'A concise summary'
    call = model.client.chat.call_args.kwargs
    spec = call['format']['properties']['text']
    assert spec['maxLength'] == 20
    assert 'minLength' not in spec and 'pattern' not in spec
    assert call['think'] is False
    assert model.last_call['bound_strings'] is True
    assert model.last_response_text == raw
    # The prompt still teaches the complete application contract.
    instruction = call['messages'][0]['content']
    assert '"minLength": 5' in instruction
    assert '"maxLength": 20' in instruction
    assert '"pattern": "^[A-Za-z ]+$"' in instruction


@pytest.mark.parametrize('explicit_false', [False, True])
def test_legacy_transport_and_routing_have_no_bound_flag(explicit_false):
    options = {'bound_strings': False} if explicit_false else {}
    model = LocalModel('qwen3.5:9b', **options)
    model.client = Mock()
    model.client.chat.return_value = {'message': {'content': '{"text":"A concise summary"}'}}
    model.generate('Summarize', '{}', BoundedText)
    assert model.client.chat.call_args.kwargs['format'] == generation_schema(BoundedText)
    assert 'bound_strings' not in model.last_call


@pytest.mark.parametrize('text', ['Hi', 'Contains digits 123', 'A full summary exceeding its field budget'])
def test_decoder_opt_in_keeps_final_validation_for_all_original_constraints(text):
    model = LocalModel('qwen3.5:9b', bound_strings=True)
    model.client = Mock()
    raw = json.dumps({'text': text})
    model.client.chat.return_value = {'message': {'content': raw}}
    with pytest.raises(ValidationError):
        model.generate('Summarize', '{}', BoundedText)
    assert model.last_response_text == raw
    assert model.last_call['bound_strings'] is True


def test_bounded_thinking_is_rejected_before_a_client_is_created(monkeypatch):
    monkeypatch.setattr('agents.inference.local_models.ollama.Client',
                        lambda **kwargs: pytest.fail('Incompatible mode must not create a client'))
    with pytest.raises(ValueError, match='non-thinking structured decoding'):
        LocalModel('qwen3.5:9b', thinking=True, bound_strings=True)


@pytest.mark.parametrize('value', [1, 0, 'true', None])
def test_bound_flag_requires_an_explicit_boolean(value):
    with pytest.raises(TypeError, match='boolean'):
        generation_schema(BoundedText, bound_strings=value)
    with pytest.raises(TypeError, match='boolean'):
        LocalModel('qwen3.5:9b', bound_strings=value)


def test_failed_transport_retains_the_explicit_decoder_policy():
    model = LocalModel('qwen3.5:9b', bound_strings=True)
    model.client = Mock()
    model.client.chat.side_effect = RuntimeError('Inference failed')
    with pytest.raises(RuntimeError, match='Inference failed'):
        model.generate('Summarize', '{}', BoundedText)
    assert model.last_call['bound_strings'] is True
    assert model.last_response_text == ''
