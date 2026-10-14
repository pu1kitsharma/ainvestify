"""Two-call authorship and strict provenance mechanics; not model-quality labels."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from agents.inference.model_authorship import digest
from agents.research import source_interpretation_pair as pair
from agents.research.source_interpretation import InterpretationError


PIN = {'name': 'qwen3.5:9b', 'digest': 'a' * 64}


def source(number=1, passage='Original source text retains each complete supplied byte.'):
    return {'id': f'S{number}', 'url': f'https://example.invalid/source/{number}',
        'title': f'Input {number}', 'passage': passage, 'version': f'version-{number}',
        'attribution': 'Fictional protocol invariant input'}


def record(request, answer, number):
    task, instruction, payload, schema = request
    raw = json.dumps(answer, ensure_ascii=False)
    return {'id': f'response_{number}', 'task': task, 'instruction': instruction,
        'input': deepcopy(payload), 'schema': schema.model_json_schema(), 'answer': deepcopy(answer),
        'raw_response': raw, 'response_hash': digest(raw), 'model': PIN['name'],
        'routing': {**payload['options'], 'model': PIN['name'], 'prompt_tokens': 1100,
            'generated_tokens': 150, 'done_reason': 'stop',
            'sampling': {'presence_penalty': 0, 'repeat_penalty': 1},
            'format_object_receipts': [{'operation': 'chat', 'model': PIN['name'],
                'format_order_digest': payload['generation_schema_order_digest']}]}}


def first_record(descriptor, topics=None):
    return record(descriptor['first_request'], {'supported_topics': [] if topics is None else topics,
        'group_id': descriptor['group_id']}, 1)


def test_plain_extraction_is_separate_and_freezes_both_kind_policies():
    pairs = pair.frozen_source_pairs([source()], PIN)
    schema = pairs[0]['first_request'][3].model_json_schema()
    assert list(schema['properties']) == ['supported_topics', 'group_id']
    assert 'content_kind' not in json.dumps(schema)
    assert 'anyOf' not in json.dumps(schema) and 'default' not in json.dumps(schema)
    manifest = pair.pair_plan_manifest(pairs)
    assert set(manifest[0]['kind_schema_templates']) == {'with_supported_topics', 'without_supported_topics'}
    assert len(manifest) == 1
    json.dumps(manifest, allow_nan=False)


def test_partial_extraction_does_not_fabricate_complete_assessment_or_next_pair():
    pairs = pair.frozen_source_pairs([source(1), source(2, 'A distinct complete source retains different original bytes.')], PIN)
    empty = pair.pair_progress(pairs, [])
    assert empty['request'] == pairs[0]['first_request'] and empty['bound'] == {}
    first = first_record(pairs[0])
    partial = pair.pair_progress(pairs, [first])
    assert partial['bound'] == {} and partial['completed_pairs'] == []
    second_request = partial['request']
    assert second_request[0] == pair.KIND_TASK
    assert second_request[2]['group'] == pairs[0]['group']
    assert second_request[2]['topic_proposal'] == first['answer']
    assert second_request[2]['topic_response_hash'] == first['response_hash']
    second = record(second_request, {'content_kind': 'information', 'group_id': 'G1'}, 2)
    complete = pair.pair_progress(pairs, [first, second], pass_pair_index=1)
    assert complete['state'] == 'needs_call' and complete['pair_index'] == 2
    assert complete['pass_exhausted'] and complete['request'] is None
    assert complete['bound']['S1']['response_ids'] == ['response_1', 'response_2']
    receipt = complete['logical_pair_receipts'][0]
    assert not receipt['is_model_row'] and receipt['first_response_hash'] == first['response_hash']
    assert receipt['second_response_hash'] == second['response_hash']


def test_positive_topics_only_restrict_kind_consistency_without_selecting_kind():
    descriptor = pair.frozen_source_pairs([source()], PIN)[0]
    topics = [{'quote': 'complete supplied byte', 'topic': 'identity', 'basis': 'reported'}]
    first = first_record(descriptor, topics)
    second = pair.frozen_content_kind_request(descriptor, first)
    kinds = second[3].model_json_schema()['properties']['content_kind']['enum']
    assert kinds == ['information', 'structured_information']
    for chosen in kinds:
        actual = record(second, {'content_kind': chosen, 'group_id': descriptor['group_id']}, 2)
        bound, _ = pair.replay_source_pair(descriptor, first, actual)
        assert bound['S1']['content_kind'] == chosen
        assert bound['S1']['supported_topics'][0]['quote'] == topics[0]['quote']
    with pytest.raises(ValidationError):
        second[3].model_validate({'content_kind': 'heading_only', 'group_id': descriptor['group_id']})


def test_actual_receipt_and_parent_record_changes_block_without_repair():
    descriptor = pair.frozen_source_pairs([source()], PIN)[0]
    first = first_record(descriptor)
    second_request = pair.frozen_content_kind_request(descriptor, first)
    second = record(second_request, {'content_kind': 'information', 'group_id': 'G1'}, 2)
    second['input']['topic_response_hash'] = '0' * 64
    assert pair.pair_progress([descriptor], [first, second])['state'] == 'blocked'
    first['routing'].pop('format_object_receipts')
    with pytest.raises(InterpretationError, match='source_pair_actual_model_or_format_receipt_changed'):
        pair.replay_topic_extraction(descriptor, first)


def test_own_financial_quote_scope_ambiguity_and_deferred_capital_guard():
    finance = pair.frozen_source_pairs([source(passage='Projected revenue in illustrative units: 40 for 2030.')], PIN)[0]
    with pytest.raises(InterpretationError, match='financial_context_missing'):
        pair.replay_topic_extraction(finance, first_record(finance, [
            {'quote': '40 for 2030', 'topic': 'financial_evidence', 'basis': 'projected'}]))
    repeated = pair.frozen_source_pairs([source(passage='Repeated literal phrase. Repeated literal phrase.')], PIN)[0]
    with pytest.raises(InterpretationError) as exc:
        pair.replay_topic_extraction(repeated, first_record(repeated, [
            {'quote': 'Repeated literal phrase.', 'topic': 'identity', 'basis': 'reported'}]))
    assert exc.value.code == 'ambiguous_quote_occurrence'
    assert len(exc.value.detail['all_occurrences']) == 2
    capital = pair.frozen_source_pairs([source(passage='Equity capital overview with retained source text.')], PIN)[0]
    first = first_record(capital)
    second_request = pair.frozen_content_kind_request(capital, first)
    # P1 cannot classify a heading; final omission is checked after recorded P2.
    heading = record(second_request, {'content_kind': 'heading_only', 'group_id': 'G1'}, 2)
    assert pair.replay_source_pair(capital, first, heading)[0]['S1']['supported_topics'] == []
    data = record(second_request, {'content_kind': 'information', 'group_id': 'G1'}, 2)
    with pytest.raises(InterpretationError, match='explicit_capital_topic_omitted'):
        pair.replay_source_pair(capital, first, data)


def test_duplicate_full_sources_use_one_pair_and_preserve_member_versions():
    descriptors = pair.frozen_source_pairs([source(1), source(2)], PIN)
    assert len(descriptors) == 1 and descriptors[0]['source_ids'] == ['S1', 'S2']
    first = first_record(descriptors[0])
    second_request = pair.frozen_content_kind_request(descriptors[0], first)
    second = record(second_request, {'content_kind': 'information', 'group_id': 'G1'}, 2)
    progress = pair.pair_progress(descriptors, [first, second])
    assert progress['state'] == 'accepted' and progress['pair_index'] is None
    assert progress['bound']['S1']['source_version'] != progress['bound']['S2']['source_version']
    assert progress['completed_pairs'] == ['source_pair_1']
    assert len(progress['logical_pair_receipts']) == 1


def test_failed_or_excess_raw_prefix_blocks_and_capacity_is_finite():
    descriptors = pair.frozen_source_pairs([source()], PIN)
    first = first_record(descriptors[0])
    first['error'] = 'Preserved failed call'
    failed = pair.pair_progress(descriptors, [first])
    assert failed['state'] == 'blocked' and failed['request'] is None
    assert pair.pair_progress(descriptors, [first, first, first])['state'] == 'blocked'
    sources = [source(index, f'Unique source {index} retains its own complete original supplied bytes.')
               for index in range(1, 26)]
    assert len(pair.frozen_source_pairs(sources, PIN)) == 25
    with pytest.raises(InterpretationError, match='bounded_source_pair_inventory_required'):
        pair.frozen_source_pairs([*sources, source(26)], PIN)


def test_v2_genuine_reasoning_and_fast_kind_are_separately_frozen_without_v1_changes():
    from agents.research.source_interpretation import canonical_digest
    sources = [source()]
    v1 = pair.frozen_source_pairs(sources, PIN)
    old_digest = canonical_digest(pair.pair_plan_manifest(v1))
    v2 = pair.frozen_source_pairs(sources, PIN, contract=pair.CONTRACT_V2)[0]
    assert v2['topic_options'] == pair.OPTIONS_THINKING
    assert v2['topic_options']['reasoning_budget'] == 1024
    assert v2['topic_options']['max_tokens'] - v2['topic_options']['reasoning_budget'] == 700
    assert v2['kind_options'] == pair.OPTIONS and v2['kind_options']['thinking'] is False
    assert v2['first_request'][2]['options'] == v2['topic_options']
    assert v2['max_expected_http_requests'] == 3 and v2['max_pair_requests'] == 6
    assert v2['first_request'][1] == v1[0]['first_request'][1]
    assert v2['first_request'][3] is v1[0]['first_request'][3]
    assert canonical_digest(pair.pair_plan_manifest(pair.frozen_source_pairs(sources, PIN))) == old_digest
    assert 'topic_options' not in v1[0]


def test_v2_missing_native_transport_proof_blocks_the_recorded_prefix():
    descriptor = pair.frozen_source_pairs([source()], PIN, contract=pair.CONTRACT_V2)[0]
    row = first_record(descriptor)
    row['routing']['format_object_receipts'][0]['operation'] = 'generate'
    original = deepcopy(row)
    progress = pair.pair_progress([descriptor], [row])
    assert progress['state'] == 'blocked'
    assert progress['request'] is None and progress['completed_pairs'] == []
    assert row == original


def test_v2_native_binding_rebuilt_independently_and_p2_keeps_fast_request(monkeypatch):
    import agents.inference.local_models as transport
    descriptor = pair.frozen_source_pairs([source()], PIN, contract=pair.CONTRACT_V2)[0]
    req = descriptor['first_request']
    row = first_record(descriptor)
    row['routing']['format_object_receipts'][0]['operation'] = 'generate'
    expected = transport.bounded_thinking_input_binding(req[1], req[2], req[3],
                                                        compact_prompt=True, bound_strings=True)
    calls = []
    def native_gate(routing, *, raw_response, expected_input_binding):
        calls.append((raw_response, expected_input_binding))
        assert expected_input_binding == expected
        # This test doubles only the native gate; missing actual proof is tested
        # separately above and cannot pass through the production implementation.
    monkeypatch.setattr(transport, 'validate_bounded_thinking_receipts', native_gate)
    second = pair.frozen_content_kind_request(descriptor, row)
    assert calls == [(row['raw_response'], expected)]
    assert second[2]['options'] == pair.OPTIONS
    assert second[2]['topic_response_hash'] == row['response_hash']
    assert second[2]['group'] == descriptor['group']
