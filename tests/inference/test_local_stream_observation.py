"""Exact partial preservation and terminal-only receipts; no live inference."""
import asyncio
from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, Field

from agents.inference import local_models as lm
from agents.inference.model_authorship import recorded_call, response_answer
from agents.preparation.preparation_budget import PreparationBudget, PreparationBudgetExceeded, preparation_budget
from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from tests.research.test_document_generation import PIN, manifest, planned, author


class Output(BaseModel):
    text: str = Field(min_length=1, max_length=60)


def streaming_client(monkeypatch, chunks, *, stall=False):
    calls, clients = [], []
    class Client:
        def __init__(self, **kwargs):
            self._client = self
            self.closed = False
            self.iterator_closed = False
            clients.append(self)
        async def chat(self, **kwargs):
            calls.append(deepcopy(kwargs))
            async def output():
                try:
                    for chunk in chunks:
                        yield deepcopy(chunk)
                    if stall:
                        await asyncio.sleep(30)
                finally:
                    self.iterator_closed = True
            return output()
        async def aclose(self):
            self.closed = True
    monkeypatch.setattr(lm.ollama, 'AsyncClient', Client)
    return calls, clients


def terminal(content='', *, tokens=7):
    return {'model': PIN['name'], 'done': True, 'done_reason': 'stop', 'message': {'content': content},
        'prompt_eval_count': 200, 'eval_count': tokens, 'prompt_eval_cached_count': 50,
        'load_duration': 11, 'prompt_eval_duration': 22, 'eval_duration': 33, 'total_duration': 66}


def model():
    return lm.LocalModel(PIN['name'], thinking=False, max_tokens=600, context_tokens=8192,
        temperature=0, bound_strings=True, compact_prompt=True, require_full_context=True,
        factual_sampling=True, streaming_transport_contract=lm.STREAM_OBSERVATION_V1)


def test_cancelled_valid_json_is_preserved_exactly_but_never_becomes_an_answer(monkeypatch):
    raw = '{"text":"exact π"}'
    calls, clients = streaming_client(monkeypatch, [
        {'model': PIN['name'], 'done': False, 'message': {'content': raw}}], stall=True)
    role, attempts = model(), []
    budget = PreparationBudget(.08, max_calls=1, max_requests=6)
    with preparation_budget(budget), pytest.raises(PreparationBudgetExceeded, match='exact partial output'):
        recorded_call(role, 'generic_stream_probe', 'Return the typed observation.', {'source': 'synthetic'}, Output, attempts, lambda: None)
    row = attempts[0]
    receipt = row['routing']['stream_observation']
    assert row['raw_response'] == raw and receipt['content_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    assert receipt['content_characters'] == len(raw) and receipt['content_bytes'] == len(raw.encode())
    assert receipt['state'] == 'cancelled' and receipt['terminal_observed'] is False
    assert receipt['first_content_seconds'] is not None and receipt['observed_chunks'] == 1
    assert 'prompt_tokens' not in row['routing'] and 'generated_tokens' not in row['routing']
    assert 'prompt_tokens' not in receipt and 'generated_tokens' not in receipt
    assert calls[0]['stream'] is True and calls[0]['think'] is False
    assert len(calls) == budget.calls == budget.requests == 1
    assert clients[0].closed and clients[0].iterator_closed and receipt['client_close_completed'] is True
    with pytest.raises(ValueError, match='No successful model response'):
        response_answer(attempts, row['id'])
    with pytest.raises(ValueError, match='no completed transport'):
        lm.validate_stream_observation_receipt(row['routing'], raw_response=raw)


def test_terminal_stream_uses_actual_metrics_and_binds_exact_instruction_source_and_format(monkeypatch):
    parts = ['{', '"text":"exact π"', '}']
    chunks = [{'model': PIN['name'], 'done': False, 'message': {'content': part}} for part in parts[:-1]]
    calls, clients = streaming_client(monkeypatch, [*chunks, terminal(parts[-1])])
    role = model()
    with preparation_budget(PreparationBudget(2, max_calls=1, max_requests=6)):
        result = role.generate('Typed observation.', '{"source":"synthetic"}', Output)
    assert result.text == 'exact π' and role.last_response_text == ''.join(parts)
    receipt = role.last_call['stream_observation']
    assert receipt['state'] == 'terminal' and receipt['observed_chunks'] == receipt['observed_content_chunks'] == 3
    assert receipt['prompt_tokens'] == 200 and receipt['generated_tokens'] == 7
    assert receipt['load_duration'] == 11 and receipt['prompt_eval_duration'] == 22
    expected = lm.bounded_thinking_input_binding('Typed observation.', '{"source":"synthetic"}', Output,
                                                compact_prompt=True, bound_strings=True)
    lm.validate_stream_observation_receipt(role.last_call, raw_response=role.last_response_text, expected_input_binding=expected)
    changed = deepcopy(role.last_call); changed['stream_observation']['source_messages_digest'] = '0' * 64
    with pytest.raises(ValueError, match='frozen instruction'):
        lm.validate_stream_observation_receipt(changed, raw_response=role.last_response_text, expected_input_binding=expected)
    changed = deepcopy(role.last_call); changed['stream_observation']['first_content_seconds'] = -1
    with pytest.raises(ValueError, match='chunk timings'):
        lm.validate_stream_observation_receipt(changed, raw_response=role.last_response_text)
    assert len(calls) == 1 and clients[0].closed


def test_json_without_terminal_or_unexpected_model_is_retained_and_blocked(monkeypatch):
    raw = '{"text":"exact"}'
    for name, error in ((PIN['name'], 'without a terminal'), ('qwen3.5:4b', 'different model')):
        calls, clients = streaming_client(monkeypatch, [{'model': name, 'done': False, 'message': {'content': raw}}])
        role = model()
        with preparation_budget(PreparationBudget(2, max_calls=1, max_requests=6)), pytest.raises((RuntimeError, ValueError), match=error):
            role.generate('Typed observation.', '{}', Output)
        assert role.last_response_text == raw and role.last_call['stream_observation']['state'] == 'failed'
        assert 'prompt_tokens' not in role.last_call and 'generated_tokens' not in role.last_call
        assert len(calls) == 1 and clients[0].closed


def test_historical_default_transport_and_explicit_policy_rejections(monkeypatch):
    role = lm.LocalModel(PIN['name'])
    role.client = Mock()
    role.client.chat.return_value = {'model': PIN['name'], 'done_reason': 'stop', 'message': {'content': '{"text":"exact"}'}}
    assert role.generate('Typed observation.', '{}', Output).text == 'exact'
    assert 'stream' not in role.client.chat.call_args.kwargs
    assert 'streaming_transport_contract' not in role.last_call and 'stream_observation' not in role.last_call
    with pytest.raises(ValueError, match='explicit nonthinking'):
        lm.LocalModel(PIN['name'], streaming_transport_contract=lm.STREAM_OBSERVATION_V1)
    with pytest.raises(ValueError, match='active preparation budget'):
        model().generate('Typed observation.', '{}', Output)


def test_versioned_plan_writer_and_reviewer_propagate_streaming_and_replay_its_receipts(monkeypatch):
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V5)
    request = dg.frozen_document_request(inventory, PIN, 'pitch_deck', catalog_encoding=dg.CATALOG_ENCODING_V5,
        qualification_context_profile=lc.PROFILE, streaming_transport_contract=lm.STREAM_OBSERVATION_V1)
    raw = json.dumps(planned(inventory))
    calls, clients = streaming_client(monkeypatch, [terminal(raw, tokens=150)])
    attempts = []
    role = lm.LocalModel(PIN['name'], **request[2]['options'])
    with preparation_budget(PreparationBudget(2, max_calls=1, max_requests=6)):
        recorded_call(role, request[0], request[1], request[2], request[3], attempts, lambda: None)
    assert dg.replay_document_plan(request, attempts[0], inventory) == planned(inventory)
    page = dg.frozen_page_request(request, attempts[0], 'P1', inventory)
    assert page[2]['options']['streaming_transport_contract'] == lm.STREAM_OBSERVATION_V1
    raw = json.dumps(author(page))
    streaming_client(monkeypatch, [terminal(raw, tokens=150)])
    writer = lm.LocalModel(PIN['name'], **page[2]['options'])
    with preparation_budget(PreparationBudget(2, max_calls=1, max_requests=6)):
        recorded_call(writer, page[0], page[1], page[2], page[3], attempts, lambda: None)
    review = dg.frozen_page_review_request(page, attempts[1], PIN)
    assert review[2]['options']['streaming_transport_contract'] == lm.STREAM_OBSERVATION_V1
    original = dg.frozen_document_request(inventory, PIN, 'pitch_deck', catalog_encoding=dg.CATALOG_ENCODING_V5,
                                        qualification_context_profile=lc.PROFILE)
    assert 'streaming_transport_contract' not in original[2]['options']
    assert original == dg.frozen_document_request(inventory, PIN, 'pitch_deck', catalog_encoding=dg.CATALOG_ENCODING_V5,
        qualification_context_profile=lc.PROFILE, streaming_transport_contract=None)
    with pytest.raises(dg.GenerationError, match='explicit_compact_complete_literal'):
        dg.frozen_document_request(inventory, PIN, 'pitch_deck', catalog_encoding=dg.CATALOG_ENCODING_V4,
            qualification_context_profile=lc.PROFILE, streaming_transport_contract=lm.STREAM_OBSERVATION_V1)
