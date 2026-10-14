"""Exact input/raw/evidence invariants; these do not establish model quality."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from agents.inference.model_authorship import digest
from agents.research.source_interpretation import (
    AssessmentBatch, InterpretationError, OPTIONS, bind_assessment,
    canonical_digest, frozen_interpretation_requests, projection_into_diligence,
    interpretation_progress, quote_occurrences, replay_assessment, replay_interpretations,
    CONTRACT_V2, OPTIONS_V2, frozen_interpretation_batches,
    interpretation_atomic_progress,
    CONTRACT_V3, TASK_V3, INSTRUCTION_V3, OPTIONS_V3,
    CONTRACT_V4, EvidenceAtomicAssessmentBatch, schema_order_digest,
    CONTRACT_V5, OPTIONS_V5, ConditionalEvidenceAtomicAssessmentBatch,
)


PIN = {'name': 'qwen3.5:9b', 'digest': 'a' * 64}


def source(number=1, passage='A supplied source has exact retained bytes for inspection.'):
    return {'id': f'S{number}', 'url': f'https://example.invalid/source/{number}',
            'title': f'Input {number}', 'passage': passage,
            'version': f'version-{number}', 'attribution': 'Fictional invariant fixture'}


def request(sources=None):
    return frozen_interpretation_requests([source()] if sources is None else sources, PIN)[0]


def answer(req, topics=None, kind='information'):
    return {'assessments': [{'group_id': group['group_id'], 'content_kind': kind,
        'supported_topics': [] if topics is None else deepcopy(topics)} for group in req[2]['groups']]}


def recorded(req, value):
    raw = json.dumps(value, ensure_ascii=False)
    return {'id': 'response_1', 'task': req[0], 'instruction': req[1], 'input': req[2],
        'schema': req[3].model_json_schema(), 'answer': deepcopy(value), 'raw_response': raw,
        'model': PIN['name'], 'response_hash': digest(raw),
        'routing': {**OPTIONS, 'model': PIN['name'], 'prompt_tokens': 1000,
            'generated_tokens': 200, 'done_reason': 'stop',
            'sampling': {'presence_penalty': 0, 'repeat_penalty': 1}}}


def test_schema_reused_without_alias_absence_union_or_defaults():
    schema = AssessmentBatch.model_json_schema()
    wire = json.dumps(schema)
    assert all(name not in wire for name in ('oneOf', 'anyOf', '"default"', '"C1"', '"N"', '"why"'))
    assert list(schema['$defs']['SupportedTopic']['properties']) == ['quote', 'topic', 'basis']
    assert schema == request([source(1), source(2, 'A different exact input retains a different version.')])[3].model_json_schema()
    assert len(json.dumps(schema, separators=(',', ':'))) < 2000


def test_duplicate_full_inputs_are_once_in_prompt_and_each_member_remains_bound():
    req = request([source(1), source(2)])
    payload = req[2]
    assert len(payload['groups']) == 1
    assert len(payload['groups'][0]['members']) == 2
    assert all('passage' not in member for member in payload['groups'][0]['members'])
    assert json.dumps(payload).count(source()['passage']) == 1
    bound = bind_assessment(payload, answer(req))
    assert set(bound) == {'S1', 'S2'}
    assert bound['S1']['full_source_binding']['version'] == 'version-1'
    assert bound['S2']['full_source_binding']['version'] == 'version-2'
    assert all(row['full_source_binding']['passage'] == source()['passage'] for row in bound.values())


def test_literal_quote_does_not_expand_to_old_window():
    text = 'Prefix text. An exact own excerpt. Suffix text remains complete.'
    req = request([source(passage=text)])
    chosen = {'quote': 'An exact own excerpt.', 'topic': 'identity', 'basis': 'reported'}
    bound = bind_assessment(req[2], answer(req, [chosen]))
    projected = projection_into_diligence(bound)['S1']
    span = projected['exact_quote_spans']['S1.q001']
    assert text[span['start']:span['end']] == chosen['quote']
    assert span['end'] - span['start'] == len(chosen['quote'])
    assert projected['topic_basis'] == {'identity': 'reported'}
    assert projected['kind_evidence_id'] == 'S1.full'
    assert projected['source_interpretation_binding']['full_source_binding']['passage'] == text


def test_all_overlapping_occurrences_retained_and_ambiguity_blocks():
    assert quote_occurrences('aaaa', 'aa') == [
        {'start': 0, 'end': 2}, {'start': 1, 'end': 3}, {'start': 2, 'end': 4}]
    req = request([source(passage='This repeated excerpt. This repeated excerpt.')])
    value = answer(req, [{'quote': 'This repeated excerpt.', 'topic': 'identity', 'basis': 'reported'}])
    with pytest.raises(InterpretationError) as exc:
        bind_assessment(req[2], value)
    assert exc.value.code == 'ambiguous_quote_occurrence'
    assert exc.value.detail['all_occurrences'] == [{'start': 0, 'end': 22}, {'start': 23, 'end': 45}]


def test_quotes_are_not_normalized_or_taken_from_other_sources():
    req = request([source(1, 'Exact casing and café are retained in this source.'),
                   source(2, 'Different source content supplies different exact bytes.')])
    value = answer(req)
    value['assessments'][0]['supported_topics'] = [
        {'quote': 'Different source content', 'topic': 'identity', 'basis': 'reported'}]
    with pytest.raises(InterpretationError, match='quote_not_in_own_complete_passage'):
        bind_assessment(req[2], value)
    value['assessments'][0]['supported_topics'][0]['quote'] = 'cafe\u0301'
    with pytest.raises(InterpretationError, match='quote_not_in_own_complete_passage'):
        bind_assessment(req[2], value)


def test_full_member_and_request_byte_changes_block():
    req = request()
    payload = deepcopy(req[2])
    payload['groups'][0]['passage'] += ' changed'
    with pytest.raises(InterpretationError, match='interpretation_input_binding_changed'):
        bind_assessment(payload, answer(req))
    payload['assessment_binding_digest'] = canonical_digest({key: value for key, value in payload.items()
                                                             if key != 'assessment_binding_digest'})
    with pytest.raises(InterpretationError, match='member_full_source_binding_changed'):
        bind_assessment(payload, answer(req))


def test_every_group_exactly_once_and_topic_unique():
    req = request([source(1), source(2, 'A different full source needs its own recorded judgment.')])
    value = answer(req)
    with pytest.raises(InterpretationError, match='assess_every_group_exactly_once'):
        bind_assessment(req[2], {'assessments': [value['assessments'][0]]})
    value['assessments'][1] = deepcopy(value['assessments'][0])
    with pytest.raises(InterpretationError, match='assess_every_group_exactly_once'):
        bind_assessment(req[2], value)
    one = request()
    topic = {'quote': 'exact retained bytes', 'topic': 'identity', 'basis': 'reported'}
    with pytest.raises(InterpretationError, match='duplicate_topic_judgment'):
        bind_assessment(one[2], answer(one, [topic, topic]))


def test_empty_topics_and_heading_contact_checks_do_not_force_substantive_answers():
    req = request()
    for kind in ('information', 'structured_information', 'heading_only', 'contact_only'):
        bound = bind_assessment(req[2], answer(req, kind=kind))
        assert bound['S1']['supported_topics'] == []
        assert projection_into_diligence(bound)['S1']['disposition'] == 'irrelevant'
    with pytest.raises(InterpretationError, match='heading_contact_cannot_supply_topics'):
        bind_assessment(req[2], answer(req, [{'quote': 'exact retained bytes',
            'topic': 'identity', 'basis': 'reported'}], kind='heading_only'))


def test_existing_explicit_capital_quote_guard_remains():
    text = 'Equity capital sought: 50 illustrative units. Product description follows.'
    req = request([source(passage=text)])
    with pytest.raises(InterpretationError, match='explicit_capital_topic_omitted'):
        bind_assessment(req[2], answer(req))
    with pytest.raises(InterpretationError, match='capital_topic_quote_lacks_explicit_label'):
        bind_assessment(req[2], answer(req, [{'quote': 'Product description follows.',
            'topic': 'funding_and_ownership', 'basis': 'planned'}]))
    bound = bind_assessment(req[2], answer(req, [{'quote': 'Equity capital sought: 50 illustrative units.',
        'topic': 'funding_and_ownership', 'basis': 'planned'}]))
    assert bound['S1']['supported_topics'][0]['basis'] == 'planned'


def test_inventory_context_and_no_more_than_five_batches():
    sources = [source(index, f'Unique exact full input number {index} retains its original bytes.')
               for index in range(1, 26)]
    requests = frozen_interpretation_requests(sources, PIN)
    assert len(requests) == 5
    assert [req[2]['shard_index'] for req in requests] == [1, 2, 3, 4, 5]
    assert [req[2]['batch_id'] for req in requests] == [f'source_adjudication_{index}' for index in range(1, 6)]
    assert {sid for req in requests for sid in req[2]['required_source_ids']} == {row['id'] for row in sources}
    with pytest.raises(InterpretationError, match='bounded_source_inventory_required'):
        frozen_interpretation_requests([*sources, source(26)], PIN)
    with pytest.raises(ValueError, match='duplicate_group_exceeds_shard_bound'):
        frozen_interpretation_requests([source(index) for index in range(1, 7)], PIN)
    with pytest.raises(InterpretationError, match='complete_batch_exceeds_character_bound'):
        frozen_interpretation_requests([source(index, str(index) * 3000) for index in range(1, 6)], PIN)


def test_exact_record_replay_and_raw_mutation_block():
    req = request()
    row = recorded(req, answer(req))
    assert replay_assessment(row, req)['S1']['supported_topics'] == []
    row['raw_response'] += ' '
    with pytest.raises(ValueError, match='Recorded model response was modified'):
        replay_assessment(row, req)


@pytest.mark.parametrize('case', ['fenced', 'prefixed', 'duplicate', 'nonfinite'])
def test_whole_raw_body_rejects_decoder_rescue_duplicate_keys_and_nonfinite(case):
    req = request()
    row = recorded(req, answer(req))
    if case == 'fenced':
        raw = '```json\n' + row['raw_response'] + '\n```'
    elif case == 'prefixed':
        raw = 'Here is an answer: ' + row['raw_response']
    elif case == 'duplicate':
        field = json.dumps(row['answer']['assessments'])
        raw = '{"assessments":' + field + ',"assessments":' + field + '}'
    else:
        raw = '{"assessments":NaN}'
    row['raw_response'], row['response_hash'] = raw, digest(raw)
    with pytest.raises(ValueError):
        replay_assessment(row, req)


@pytest.mark.parametrize('reason,generated', [('length', 200), ('stop', 0),
                                              ('stop', True), ('stop', 1401)])
def test_incomplete_or_invalid_actual_output_allocation_blocks(reason, generated):
    req = request()
    row = recorded(req, answer(req))
    row['routing'].update(done_reason=reason, generated_tokens=generated)
    with pytest.raises(InterpretationError, match='incomplete_or_unbounded_model_output'):
        replay_assessment(row, req)


@pytest.mark.parametrize('key,value', [('max_tokens', 1401), ('model', 'qwen3:14b'), ('prompt_tokens', 8100)])
def test_actual_model_options_or_full_context_mismatch_block(key, value):
    req = request()
    row = recorded(req, answer(req))
    row['routing'][key] = value
    with pytest.raises(ValueError):
        replay_assessment(row, req)


def test_failed_prefix_never_advances_and_excess_records_block():
    req = request()
    row = recorded(req, answer(req))
    row['error'] = 'Retained actual failed inference'
    with pytest.raises(InterpretationError, match='failed_recorded_prefix_cannot_advance'):
        replay_interpretations([source()], PIN, [row])
    with pytest.raises(InterpretationError, match='bounded_unique_response_prefix_required'):
        replay_interpretations([source()], PIN, [row, row])


def test_resume_binds_the_complete_prefix_and_next_exact_request_without_retry():
    sources = [source(index, f'Input {index} retains all complete original source bytes.')
               for index in range(1, 7)]
    requests = frozen_interpretation_requests(sources, PIN)
    row1 = recorded(requests[0], answer(requests[0]))
    progress = interpretation_progress(sources, PIN, [row1])
    assert progress['completed_batches'] == 1
    assert progress['total_batches'] == 2
    assert progress['pending_request'] == requests[1]
    assert progress['response_digest'] == canonical_digest([row1])
    row2 = recorded(requests[1], answer(requests[1]))
    row2['id'] = 'response_2'
    complete = interpretation_progress(sources, PIN, [row1, row2])
    assert complete['pending_request'] is None
    assert set(complete['judgments']) == {source['id'] for source in sources}
    row1['input'] = deepcopy(row1['input'])
    row1['input']['input_revision'] = 'changed'
    with pytest.raises(InterpretationError, match='recorded_call_differs_from_frozen_request'):
        interpretation_progress(sources, PIN, [row1, row2])


def test_basis_and_topic_schema_do_not_inject_defaults():
    req = request()
    value = answer(req, [{'quote': 'exact retained bytes', 'topic': 'identity'}])
    with pytest.raises(ValidationError):
        bind_assessment(req[2], value)
    value['assessments'][0]['supported_topics'][0]['basis'] = 'verified'
    with pytest.raises(ValidationError):
        bind_assessment(req[2], value)
    with pytest.raises(InterpretationError, match='input_not_canonical'):
        canonical_digest({'nonfinite': float('nan')})


def atomic_record(req, value, number):
    row = recorded(req, value)
    row['id'] = f'response_{number}'
    row['routing'].update(req[2]['options'])
    if req[2]['contract'] == CONTRACT_V5:
        row['routing']['format_object_receipts'] = [{'operation': 'chat', 'model': PIN['name'],
            'format_order_digest': req[2]['generation_schema_order_digest']}]
    return row


def test_v2_one_complete_group_per_call_and_five_physical_bins():
    sources = [source(index, f'Original distinct source {index} retains every supplied character.')
               for index in range(1, 7)]
    batches = frozen_interpretation_batches(sources, PIN)
    assert len(batches) == 5
    assert [len(batch['requests']) for batch in batches] == [5, 1, 0, 0, 0]
    flat = [req for batch in batches for req in batch['requests']]
    assert len({req[2]['request_id'] for req in flat}) == 6
    for req in flat:
        assert req[2]['contract'] == CONTRACT_V2
        assert len(req[2]['groups']) == 1
        assert req[2]['options'] == OPTIONS_V2
        assert req[3].model_json_schema()['properties']['assessments']['maxItems'] == 1
        assert req[2]['groups'][0]['passage'] == sources[int(req[2]['required_source_ids'][0][1:]) - 1]['passage']


def test_v2_group_prefix_never_returns_next_checkpoint_to_current_pass():
    sources = [source(index, f'Original distinct source {index} retains every supplied character.')
               for index in range(1, 7)]
    batches = frozen_interpretation_batches(sources, PIN)
    first = batches[0]['requests']
    rows = [atomic_record(req, answer(req), index) for index, req in enumerate(first, 1)]
    partial = interpretation_atomic_progress(sources, PIN, rows[:2], pass_shard_index=1)
    assert partial['checkpoint_requests_remaining'] == first[2:]
    assert not partial['batch_done'][0]
    done = interpretation_atomic_progress(sources, PIN, rows, pass_shard_index=1)
    assert done['pass_exhausted']
    assert done['pending_request'] is None and done['checkpoint_requests_remaining'] == []
    assert done['next_shard_index'] == 2
    assert done['batch_done'][0] and not done['batch_done'][1]
    rows[1]['error'] = 'Actual saved failure'
    with pytest.raises(InterpretationError, match='failed_recorded_prefix_cannot_advance'):
        interpretation_atomic_progress(sources, PIN, rows, pass_shard_index=1)


def test_v2_duplicate_passage_one_call_retains_independent_member_versions():
    batches = frozen_interpretation_batches([source(1), source(2)], PIN)
    assert sum(len(batch['requests']) for batch in batches) == 1
    req = batches[0]['requests'][0]
    row = atomic_record(req, answer(req), 1)
    progress = interpretation_atomic_progress([source(1), source(2)], PIN, [row])
    assert progress['completed_group_calls'] == 1
    assert progress['pending_request'] is None
    assert set(progress['judgments']) == {'S1', 'S2'}
    assert progress['judgments']['S1']['source_version'] != progress['judgments']['S2']['source_version']


def test_v2_financial_measure_context_guard_without_changing_v1_quote():
    text = 'Projected revenue (illustrative units) | Period\n2030 | 75'
    sources = [source(passage=text)]
    v1 = frozen_interpretation_requests(sources, PIN)[0]
    v2 = frozen_interpretation_batches(sources, PIN)[0]['requests'][0]
    bare = {'quote': '2030 | 75', 'topic': 'financial_evidence', 'basis': 'projected'}
    # The preserved V1 protocol admits the same raw record it admitted previously.
    original = bind_assessment(v1[2], answer(v1, [bare]))
    assert original['S1']['supported_topics'][0]['quote'] == bare['quote']
    with pytest.raises(InterpretationError, match='financial_context_missing'):
        bind_assessment(v2[2], answer(v2, [bare]))
    complete = {**bare, 'quote': text}
    bound = bind_assessment(v2[2], answer(v2, [complete], kind='structured_information'))
    assert bound['S1']['supported_topics'][0]['quote'] == text
    assert bound['S1']['supported_topics'][0]['basis'] == 'projected'


def test_v2_freeze_cannot_change_v1_options_schema_instruction_or_request_digests():
    sources = [source(1), source(2, 'Another original source retains its own complete literal text.')]
    before = frozen_interpretation_requests(sources, PIN)
    digest_before = canonical_digest([[task, instruction, payload, schema.model_json_schema()]
                                     for task, instruction, payload, schema in before])
    frozen_interpretation_batches(sources, PIN)
    after = frozen_interpretation_requests(sources, PIN)
    assert canonical_digest([[task, instruction, payload, schema.model_json_schema()]
                             for task, instruction, payload, schema in after]) == digest_before
    assert OPTIONS['max_tokens'] == 1400
    assert before[0][3] is AssessmentBatch


def test_v2_one_group_schema_cannot_accept_multiple_assessments():
    req = frozen_interpretation_batches([source()], PIN)[0]['requests'][0]
    value = answer(req)
    value['assessments'].append(deepcopy(value['assessments'][0]))
    with pytest.raises(ValidationError):
        bind_assessment(req[2], value)


def batch_digest(batches):
    return canonical_digest([
        {**{key: value for key, value in batch.items() if key != 'requests'},
         'requests': [[task, instruction, payload, schema.model_json_schema()]
                      for task, instruction, payload, schema in batch['requests']]}
        for batch in batches])


def test_v3_is_explicit_and_keeps_v1_v2_input_bytes_options_and_schema():
    sources = [source(1), source(2, 'Another original source retains its own complete literal text.')]
    legacy = frozen_interpretation_requests(sources, PIN)
    legacy_digest = canonical_digest([[task, instruction, payload, schema.model_json_schema()]
                                      for task, instruction, payload, schema in legacy])
    v2 = frozen_interpretation_batches(sources, PIN)
    before = batch_digest(v2)
    assert before == batch_digest(frozen_interpretation_batches(sources, PIN, contract=CONTRACT_V2))
    v3 = frozen_interpretation_batches(sources, PIN, contract=CONTRACT_V3)
    assert batch_digest(v3) != before
    assert batch_digest(frozen_interpretation_batches(sources, PIN)) == before
    assert OPTIONS_V3 == OPTIONS_V2
    assert v3[0]['requests'][0][3] is v2[0]['requests'][0][3]
    assert all(req[0] == TASK_V3 and req[1] == INSTRUCTION_V3 and req[2]['contract'] == CONTRACT_V3
               for batch in v3 for req in batch['requests'])
    assert canonical_digest([[task, instruction, payload, schema.model_json_schema()]
                             for task, instruction, payload, schema in
                             frozen_interpretation_requests(sources, PIN)]) == legacy_digest


def test_v3_replay_does_not_supply_topic_defaults_and_cannot_replay_as_v2():
    sources = [source()]
    req = frozen_interpretation_batches(sources, PIN, contract=CONTRACT_V3)[0]['requests'][0]
    row = atomic_record(req, answer(req), 1)
    progress = interpretation_atomic_progress(sources, PIN, [row], contract=CONTRACT_V3)
    assert progress['judgments']['S1']['categories'] == []
    assert progress['judgments']['S1']['topic_basis'] == {}
    assert progress['pending_request'] is None
    with pytest.raises(InterpretationError, match='recorded_call_differs_from_frozen_request'):
        interpretation_atomic_progress(sources, PIN, [row], contract=CONTRACT_V2)


def test_v3_retains_financial_scope_guard_and_unknown_versions_fail_closed():
    text = 'Projected revenue (illustrative units) | Period\n2030 | 75'
    req = frozen_interpretation_batches([source(passage=text)], PIN,
                                         contract=CONTRACT_V3)[0]['requests'][0]
    bare = {'quote': '2030 | 75', 'topic': 'financial_evidence', 'basis': 'projected'}
    with pytest.raises(InterpretationError, match='financial_context_missing'):
        bind_assessment(req[2], answer(req, [bare]))
    with pytest.raises(InterpretationError, match='unknown_atomic_interpretation_contract'):
        frozen_interpretation_batches([source()], PIN, contract='unrecognized-version')


def test_v4_generation_schema_commits_evidence_before_kind_and_keeps_prior_schemas():
    from agents.inference.local_models import generation_schema
    sources = [source()]
    before = {contract: batch_digest(frozen_interpretation_batches(sources, PIN, contract=contract))
              for contract in (CONTRACT_V2, CONTRACT_V3)}
    batches = frozen_interpretation_batches(sources, PIN, contract=CONTRACT_V4)
    req = batches[0]['requests'][0]
    assert req[3] is EvidenceAtomicAssessmentBatch
    spec = generation_schema(req[3], bound_strings=True)
    entry = spec['$defs']['EvidenceSourceAssessment']
    assert list(entry['properties']) == entry['required'] == ['supported_topics', 'group_id', 'content_kind']
    topic = spec['$defs']['SupportedTopic']
    assert list(topic['properties']) == topic['required'] == ['quote', 'topic', 'basis']
    assert entry['properties']['supported_topics']['maxItems'] == 4
    assert spec['properties']['assessments']['maxItems'] == 1
    assert topic['properties']['quote']['maxLength'] == 240
    assert req[2]['schema_order_digest'] == schema_order_digest(req[3].model_json_schema())
    assert req[2]['generation_schema_order_digest'] == schema_order_digest(spec)
    for contract, old in before.items():
        assert batch_digest(frozen_interpretation_batches(sources, PIN, contract=contract)) == old
    legacy = generation_schema(AssessmentBatch, bound_strings=True)['$defs']['SourceAssessment']
    assert list(legacy['properties']) == ['group_id', 'content_kind', 'supported_topics']


def test_v4_recorded_property_order_tamper_blocks_even_with_equal_canonical_hash():
    req = frozen_interpretation_batches([source()], PIN, contract=CONTRACT_V4)[0]['requests'][0]
    row = atomic_record(req, answer(req), 1)
    assert replay_assessment(row, req)['S1']['supported_topics'] == []
    row['schema'] = deepcopy(row['schema'])
    props = row['schema']['$defs']['EvidenceSourceAssessment']['properties']
    original_hash = canonical_digest(row['schema'])
    row['schema']['$defs']['EvidenceSourceAssessment']['properties'] = dict(reversed(list(props.items())))
    assert canonical_digest(row['schema']) == original_hash
    assert row['schema'] == req[3].model_json_schema()
    with pytest.raises(InterpretationError, match='recorded_evidence_first_schema_order_changed'):
        replay_assessment(row, req)


def test_v4_retains_financial_and_literal_binding_guards():
    text = 'Projected revenue (illustrative units) | Period\n2030 | 75'
    req = frozen_interpretation_batches([source(passage=text)], PIN,
                                         contract=CONTRACT_V4)[0]['requests'][0]
    topic = {'quote': '2030 | 75', 'topic': 'financial_evidence', 'basis': 'projected'}
    with pytest.raises(InterpretationError, match='financial_context_missing'):
        bind_assessment(req[2], answer(req, [topic]))
    topic['quote'] = 'A phrase never present in the supplied passage.'
    with pytest.raises(InterpretationError, match='quote_not_in_own_complete_passage'):
        bind_assessment(req[2], answer(req, [topic]))


def test_v5_transport_grammar_encodes_existing_consistency_and_preserves_order():
    from agents.inference.local_models import generation_schema
    spec = generation_schema(ConditionalEvidenceAtomicAssessmentBatch, bound_strings=True)
    branches = spec['properties']['assessments']['items']['anyOf']
    assert len(branches) == 2
    by_kinds = {}
    for branch in branches:
        obj = spec['$defs'][branch['$ref'].rsplit('/', 1)[1]]
        assert list(obj['properties']) == obj['required'] == ['supported_topics', 'group_id', 'content_kind']
        assert obj['additionalProperties'] is False
        by_kinds[frozenset(obj['properties']['content_kind']['enum'])] = obj
        assert obj['properties']['supported_topics']['items'] == {'$ref': '#/$defs/SupportedTopic'}
    assert by_kinds[frozenset(('information', 'structured_information'))]['properties']['supported_topics']['maxItems'] == 4
    assert by_kinds[frozenset(('heading_only', 'contact_only'))]['properties']['supported_topics']['maxItems'] == 0
    assert list(spec['$defs']['SupportedTopic']['properties']) == ['quote', 'topic', 'basis']


def test_v5_all_kinds_and_empty_information_remain_model_choices_without_repairs():
    req = frozen_interpretation_batches([source()], PIN, contract=CONTRACT_V5)[0]['requests'][0]
    chosen = {'quote': 'exact retained bytes', 'topic': 'identity', 'basis': 'reported'}
    for kind in ('information', 'structured_information', 'heading_only', 'contact_only'):
        bound = bind_assessment(req[2], answer(req, kind=kind))
        assert bound['S1']['content_kind'] == kind and bound['S1']['supported_topics'] == []
    for kind in ('information', 'structured_information'):
        bound = bind_assessment(req[2], answer(req, [chosen], kind=kind))
        assert bound['S1']['content_kind'] == kind
    for kind in ('heading_only', 'contact_only'):
        with pytest.raises(ValidationError):
            bind_assessment(req[2], answer(req, [chosen], kind=kind))


def test_v5_preserves_every_prior_atomic_request_schema_and_digest():
    sources = [source()]
    versions = (CONTRACT_V2, CONTRACT_V3, CONTRACT_V4)
    before = {version: batch_digest(frozen_interpretation_batches(sources, PIN, contract=version))
              for version in versions}
    frozen_interpretation_batches(sources, PIN, contract=CONTRACT_V5)
    assert OPTIONS_V5 == OPTIONS_V3
    for version in versions:
        assert batch_digest(frozen_interpretation_batches(sources, PIN, contract=version)) == before[version]


@pytest.mark.parametrize('tamper', ['missing', 'changed'])
def test_v5_requires_actual_format_object_receipt(tamper):
    req = frozen_interpretation_batches([source()], PIN, contract=CONTRACT_V5)[0]['requests'][0]
    row = atomic_record(req, answer(req), 1)
    assert replay_assessment(row, req)['S1']['supported_topics'] == []
    if tamper == 'missing':
        row['routing'].pop('format_object_receipts')
    else:
        row['routing']['format_object_receipts'][0]['format_order_digest'] = '0' * 64
    with pytest.raises(InterpretationError, match='actual_evidence_first_format_receipt_missing_or_changed'):
        replay_assessment(row, req)
