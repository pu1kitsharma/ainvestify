"""Synthetic two-phase reviewer replay; no Ollama/network/model invocation."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import Field, create_model

from agents.inference import local_models as lm
from agents.inference.model_authorship import recorded_call
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research import bounded_material_review as capacity
from agents.research import document_generation as generation
from delivery import material_argument as material
from tests.delivery.test_material_argument import prepared, record


def request_and_answer():
    _, author_request, author_answer = prepared(handles=True)
    author_row = record(author_request, author_answer)
    request = capacity.frozen_review_request(author_request, author_row)
    vote = {'verdict': 'pass', 'category': 'none', 'reason': 'Supported in this synthetic source scope.'}
    answer = {'overall_verdict': 'pass', 'financial_status': 'not_established',
        **{item['block_id']: {**vote, 'selected_quote_support': {q: 'supports' for q in
            author_row['answer']['blocks'][item['index']]['evidence_handles']}}
            for item in request[2]['block_inventory']}, 'section_coherence': vote}
    return author_request, author_row, request, answer


def generate_record(monkeypatch):
    author_request, author_row, request, answer = request_and_answer()
    raw = json.dumps(answer)
    thought = 'Private synthetic intermediate reasoning, never retained.'
    first = {'model': capacity.MODEL_PIN['name'], 'done_reason': 'length', 'eval_count': 256,
        'prompt_eval_count': 6900, 'prompt_eval_cached_count': 0,
        'message': {'thinking': thought, 'content': ''}}
    final = {'model': capacity.MODEL_PIN['name'], 'done_reason': 'stop', 'eval_count': 500,
        'prompt_eval_count': 7200, 'prompt_eval_cached_count': 0, 'response': raw}
    client = SimpleNamespace(chat=AsyncMock(return_value=first), generate=AsyncMock(return_value=final),
                             _client=SimpleNamespace(aclose=AsyncMock()))
    monkeypatch.setattr(lm.ollama, 'AsyncClient', lambda **kwargs: client)
    model = lm.LocalModel(capacity.MODEL_PIN['name'], **capacity.OPTIONS)
    attempts = []
    budget = PreparationBudget(max_seconds=105, max_calls=1, max_requests=2)
    with preparation_budget(budget):
        recorded_call(model, *request, attempts, lambda: None)
    return author_request, author_row, request, answer, attempts[0], client, budget, thought


def resign(request, mutate, *, schema=None):
    payload = deepcopy(request[2])
    for key in ('request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'):
        payload.pop(key)
    mutate(payload)
    return generation._request(request[0], request[1], payload, schema or request[3])


def test_two_actual_adapter_transports_and_semantic_votes_replay_without_double_headroom(monkeypatch):
    author_request, author_row, request, answer, row, client, budget, thought = generate_record(monkeypatch)
    assert budget.calls == 1 and budget.requests == 2
    assert client.chat.await_count == client.generate.await_count == 1
    assert client._client.aclose.await_count == 2
    assert row['routing']['format_object_receipts'][0]['operation'] == 'generate'
    assert [r['options']['num_predict'] for r in row['routing']['transport_receipts']] == [256, 900]
    # Final prompt includes reasoning. 7200+900 fits; charging 1156 again does
    # not. Existing nonthinking headroom validation still rejects that sum.
    with pytest.raises(ValueError, match='headroom'):
        lm.validate_full_context_receipt(row['routing'])
    assert generation._replay(request, row) == answer
    assert material.replay_compact_argument_review(request, row) == answer
    assert request[2]['units'] == author_request[2]['units']
    assert request[2]['proposed_section'] == author_row['answer']
    assert request[2]['exact_rendered_section'] == list(material.renderable_argument(author_request, author_row))
    assert request[2]['reviewer_relationship'] == 'separate_model_unqualified'
    assert thought not in json.dumps(row)
    for item in request[2]['block_inventory']:
        assert set(answer[item['block_id']]['selected_quote_support']) == set(
            author_row['answer']['blocks'][item['index']]['evidence_handles'])


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(review_capacity_profile='unknown'),
    lambda p: p['model_pin'].update(name='qwen3:14b'),
    lambda p: p['model_pin'].update(digest='f' * 64),
    lambda p: p['options'].update(context_tokens=16384),
    lambda p: p['options'].update(reasoning_budget=512),
    lambda p: p['options'].update(streaming_transport_contract=lm.STREAM_OBSERVATION_V1),
    lambda p: p.update(contract='evidence-document-generation-v1'),
])
def test_unknown_profile_model_or_options_cannot_enable_thinking_replay(monkeypatch, mutation):
    _, _, request, _, row, *_ = generate_record(monkeypatch)
    changed = resign(request, mutation)
    replay_row = deepcopy(row)
    replay_row.update(input=deepcopy(changed[2]), schema=changed[3].model_json_schema(),
                      model=changed[2]['model_pin']['name'])
    with pytest.raises(ValueError, match='not_allowlisted'):
        generation._replay(changed, replay_row)


@pytest.mark.parametrize('phase,key,value,error', [
    (0, 'prompt_tokens', 4098, 'overflow cutoff'),
    (0, 'prompt_tokens', 8000, 'headroom'),
    (1, 'prompt_tokens', 7400, 'headroom'),
    (1, 'returned_model', 'qwen3:14b', 'model identity'),
    (0, 'output_allocation', 255, 'allocation'),
])
def test_both_transport_receipts_are_required_and_individually_bounded(monkeypatch, phase, key, value, error):
    _, _, request, _, row, *_ = generate_record(monkeypatch)
    changed = deepcopy(row)
    changed['routing']['transport_receipts'][phase][key] = value
    with pytest.raises(ValueError, match=error):
        generation._replay(request, changed)


def test_final_stop_input_binding_and_actual_sampling_are_mandatory(monkeypatch):
    _, _, request, _, row, *_ = generate_record(monkeypatch)
    length = deepcopy(row); length['routing']['done_reason'] = 'length'
    with pytest.raises(ValueError, match='incomplete_or_unbounded'):
        generation._replay(request, length)
    missing = deepcopy(row); missing['routing']['transport_receipts'].pop()
    with pytest.raises(ValueError, match='both complete'):
        generation._replay(request, missing)
    swapped = resign(request, lambda p: p['units'][0].update(content='Replaced source bytes.'))
    old_transport = deepcopy(row); old_transport['input'] = deepcopy(swapped[2])
    with pytest.raises(ValueError, match='independently frozen'):
        generation._replay(swapped, old_transport)
    sampling = deepcopy(row); sampling['routing']['sampling']['top_p'] = .8
    with pytest.raises(ValueError, match='actual_sampling_changed'):
        generation._replay(request, sampling)


def test_capacity_schema_cannot_drop_a_block_Q_vote_or_relax_reason_limit():
    _, _, request, _ = request_and_answer()
    source_schema = request[3]
    for field_name in ('B1', 'section_coherence'):
        vote = source_schema.model_fields[field_name].annotation
        relaxed = create_model('UnapprovedLongReason', __base__=vote,
                               reason=(str, Field(min_length=1, max_length=180)))
        changed = create_model('UnapprovedCapacityVote', __base__=source_schema, **{field_name: (relaxed, ...)})
        with pytest.raises(ValueError, match='reason_or_vote_fields'):
            capacity.validate_request(request[0], request[2], changed)
    vote = source_schema.model_fields['B1'].annotation
    support = create_model('OmittedQSupport', __base__=generation.Strict)
    dropped = create_model('ReducedB1Support', __base__=vote, selected_quote_support=(support, ...))
    changed = create_model('ReducedSupportSchema', __base__=source_schema, B1=(dropped, ...))
    with pytest.raises(ValueError, match='Q_support_inventory'):
        capacity.validate_request(request[0], request[2], changed)


def test_normal_chat_replay_and_all_semantic_support_gates_are_unchanged(monkeypatch):
    author_request, author_row, bounded, _, _, *_ = generate_record(monkeypatch)
    base = material.frozen_compact_argument_review_request(author_request, author_row, capacity.MODEL_PIN)
    _, _, _, answer = request_and_answer()
    ordinary = record(base, answer)
    assert material.replay_compact_argument_review(base, ordinary) == answer
    ordinary['routing']['format_object_receipts'][0]['operation'] = 'generate'
    with pytest.raises(ValueError, match='actual_model_options_or_format_changed'):
        generation._replay(base, ordinary)
    # Thinking is not a semantic waiver: a supported-format result with an
    # all-support matrix cannot claim an entity defect without identifying Q.
    base_answer = deepcopy(answer)
    base_answer['B1'].update(verdict='revise', category='entity_or_metric')
    base_answer['overall_verdict'] = 'revise'
    with pytest.raises(ValueError, match='identified_quote'):
        material.replay_compact_argument_review(base, record(base, base_answer))
