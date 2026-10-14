"""Recorded page-topic choices, immutable source reuse and unchanged table gates."""
from copy import deepcopy

import pytest

from agents.inference.local_models import generation_schema
from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from agents.research import document_source_index as si
from agents.research import document_qualification_context as qc
from tests.research.test_document_generation import PIN, manifest, record


def test_page_topics_only_changes_global_assignment_and_preserves_exact_source_and_table_bindings():
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V6)
    reader_arguments = {'catalog_encoding': dg.CATALOG_ENCODING_V6,
        'qualification_context_profile': lc.PROFILE, 'page_author_pin': PIN,
        'planning_schema_profile': dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5,
        'source_context_profile': si.SOURCE_CONTEXT_PROFILE_32K,
        'source_index_encoding': si.SOURCE_INDEX_ENCODING_V2}
    seed = dg.frozen_document_request(inventory, PIN, 'intro_deck', **reader_arguments)
    planner = {'name': 'qwen3.5:4b', 'digest': 'c' * 64}
    flag = dg.PAGE_TOPICS_ASSIGNMENT_PROFILE
    new_seed = dg.frozen_document_request(inventory, planner, 'intro_deck', source_reader_pin=PIN,
        planning_assignment_profile=flag, **reader_arguments)
    assert dg.request_json(new_seed) == dg.request_json(seed)
    reads = dg._source_index_requests_from_seed(seed, inventory)
    assert [dg.request_json(r) for r in dg._source_index_requests_from_seed(new_seed, inventory)] == [dg.request_json(r) for r in reads]
    rows = []
    for index, request in enumerate(reads, 1):
        own = dg.source_map_literal_lookup(request[2]['source_group'])
        choice = next(uid for uid, unit in own.items() if unit['content'].strip())
        rows.append(record(request, {'group_id': request[2]['source_group_id'], 'focus_unit_ids': [choice],
            'visual_semantics': 'unassessed', 'scope_status': 'local_source_selection_proposal_not_diligence'}, index))
    frozen_rows = deepcopy(rows)
    arguments = {'qualification_context_profile': lc.PROFILE,
        'source_index_encoding': si.SOURCE_INDEX_ENCODING_V2, 'document_planner_pin': planner}
    old = dg.generation_progress(seed, inventory, rows, PIN, **arguments)['request']
    assert set(old[3].model_fields) == {'p', 'd'}
    current = dg.generation_progress(seed, inventory, rows, PIN,
        planning_assignment_profile=flag, **arguments)['request']
    assert current[0] == 'document_plan_page_topics_v1'
    assert current[2]['planning_assignment_profile'] == flag and 'planning_assignment_profile' not in seed[2]
    assert current[2]['catalog'] == old[2]['catalog']
    assert current[2]['model_pin'] == planner and current[2]['source_reader_pin'] == PIN
    grammar = generation_schema(current[3], bound_strings=True)
    assert set(grammar['properties']) == {'p'}
    topic_field = grammar['$defs']['PageTopicsPhysicalPlanPage_intro_deck']['properties']['t']
    assert topic_field['minItems'] == 1 and topic_field['maxItems'] == 4 and topic_field['uniqueItems'] is True
    assert topic_field['items']['enum'] == list(dg.TOPICS)
    original_table = inventory['tables'][0]['id']
    answer = {'p': [{'t': ['financials', 'risks_and_countercase'], 'l': 'table', 'e': ['G1'],
        'b': [{'id': original_table, 'c': [0, 1], 'r': [1], 'h': 0}], 's': 'limited'},
        {'t': ['material_unknowns'], 'l': 'statement', 'e': [], 'b': [], 's': 'missing'}]}
    plan_row = record(current, answer, len(rows) + 1)
    untouched = deepcopy(plan_row)
    plan = dg.replay_document_plan(current, plan_row, inventory)
    assert plan['pages'][0]['topics'] == answer['p'][0]['t']
    assert plan['pages'][0]['topic'] == 'financials'
    assert plan['unsupported_topics'] == [topic for topic in dg.TOPICS if topic not in
        {'financials', 'risks_and_countercase', 'material_unknowns'}]
    assert plan['unsupported_topic_status'] == 'unassessed'
    assert all(page['evidence_scope_status'] == 'unassessed' for page in plan['pages'])
    actual, actual_row, offset = dg.document_plan_context(seed, inventory, [*rows, plan_row],
        planning_assignment_profile=flag, **arguments)
    assert dg.request_json(actual) == dg.request_json(current) and actual_row == plan_row and offset == len(rows) + 1
    author = dg.generation_progress(seed, inventory, [*rows, plan_row], PIN,
        planning_assignment_profile=flag, **arguments)['request']
    assert author[2]['planned_page']['topics'] == answer['p'][0]['t']
    assert author[2]['model_pin'] == PIN and author[2]['investor_approval'] == 'not_established'
    assert set(qc._context_units(author)) == {unit['model_unit_id'] for unit in inventory['units']
        if isinstance(unit['content'], str)}
    for invalid_topics in [['financials'] * 2, list(dg.TOPICS[:5]), ['invented_topic']]:
        invalid = deepcopy(answer); invalid['p'][0]['t'] = invalid_topics
        with pytest.raises(ValueError):
            dg.replay_document_plan(current, record(current, invalid, len(rows) + 1), inventory)
    invalid = deepcopy(answer); invalid['d'] = [[]] * len(dg.TOPICS)
    with pytest.raises(ValueError):
        dg.replay_document_plan(current, record(current, invalid, len(rows) + 1), inventory)
    invalid = deepcopy(answer); invalid['p'][0]['b'][0]['r'] = [0]
    with pytest.raises(dg.GenerationError, match='table_indexes_invalid'):
        dg.replay_document_plan(current, record(current, invalid, len(rows) + 1), inventory)
    assert rows == frozen_rows and plan_row == untouched
    assert dg.request_json(dg.generation_progress(seed, inventory, rows, PIN,
        planning_assignment_profile=None, **arguments)['request']) == dg.request_json(old)
    with pytest.raises(dg.GenerationError, match='page_topic_assignment_requires'):
        dg.frozen_document_request(inventory, planner, 'intro_deck',
            planning_assignment_profile='unknown', **reader_arguments)


def test_single_source_outline_reuses_exact_readers_but_cannot_select_native_ranges_or_multiple_groups():
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V6)
    arguments = {'catalog_encoding': dg.CATALOG_ENCODING_V6, 'qualification_context_profile': lc.PROFILE,
        'planning_schema_profile': dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5, 'page_author_pin': PIN,
        'source_context_profile': si.SOURCE_CONTEXT_PROFILE_32K}
    seed = dg.frozen_document_request(inventory, PIN, 'intro_deck', **arguments)
    profile = dg.SINGLE_SOURCE_OUTLINE_ASSIGNMENT_PROFILE
    changed_seed = dg.frozen_document_request(inventory, PIN, 'intro_deck',
        planning_assignment_profile=profile, **arguments)
    assert dg.request_json(changed_seed) == dg.request_json(seed)
    reads = dg._source_index_requests_from_seed(seed, inventory)
    assert [dg.request_json(r) for r in dg._source_index_requests_from_seed(changed_seed, inventory)] == [dg.request_json(r) for r in reads]
    rows = [record(request, {'group_id': request[2]['source_group_id'], 'focus_unit_ids': ['U1'],
        'visual_semantics': 'unassessed', 'scope_status': 'local_source_selection_proposal_not_diligence'}, index)
        for index, request in enumerate(reads, 1)]
    flow = {'qualification_context_profile': lc.PROFILE, 'planning_assignment_profile': profile}
    current = dg.generation_progress(seed, inventory, rows, PIN, **flow)['request']
    grammar = generation_schema(current[3], bound_strings=True)
    fields = grammar['$defs']['SingleSourceOutlinePage_intro_deck']['properties']
    assert set(grammar['properties']) == {'p'} and set(fields) == {'t', 'l', 'e', 's'}
    assert fields['e']['minItems'] == fields['e']['maxItems'] == 1
    assert 'table' not in fields['l']['enum'] and 'missing' not in fields['s']['enum']
    assert current[0] == 'document_plan_single_source_outline_v2'
    old_page_topics = dg.generation_progress(seed, inventory, rows, PIN,
        qualification_context_profile=lc.PROFILE, planning_assignment_profile=dg.PAGE_TOPICS_ASSIGNMENT_PROFILE)['request']
    assert current[2]['catalog'] == old_page_topics[2]['catalog']
    assert current[2]['catalog']['table_navigation']  # Original grids preserved, not rewritten.
    old_grammar = generation_schema(old_page_topics[3], bound_strings=True)
    assert 'b' in old_grammar['$defs']['PageTopicsPhysicalPlanPage_intro_deck']['properties']
    answer = {'p': [{'t': ['financials', 'risks_and_countercase'], 'l': 'evidence', 'e': ['G1'], 's': 'limited'}]}
    raw = record(current, answer, len(rows) + 1); unchanged = deepcopy(raw)
    plan = dg.replay_document_plan(current, raw, inventory)
    assert plan['pages'][0]['table_selections'] == [] and plan['pages'][0]['source_page_ids'] == ['G1']
    assert plan['pages'][0]['topics'] == answer['p'][0]['t']
    assert plan['unsupported_topic_status'] == 'unassessed'
    actual, row, offset = dg.document_plan_context(seed, inventory, [*rows, raw], **flow)
    assert dg.request_json(actual) == dg.request_json(current) and row == raw and offset == len(rows) + 1
    author = dg.generation_progress(seed, inventory, [*rows, raw], PIN, **flow)['request']
    assert author[2]['planned_page']['table_selections'] == []
    assert set(qc._context_units(author)) == {unit['model_unit_id'] for unit in inventory['units']
        if isinstance(unit['content'], str)}
    assert author[2]['investor_approval'] == 'not_established'
    for change in ({'e': []}, {'e': ['G1', 'G1']}, {'e': ['G999']}, {'b': []},
                   {'l': 'table'}, {'s': 'missing'}, {'t': list(dg.TOPICS[:5])}):
        invalid = deepcopy(answer); invalid['p'][0].update(change)
        with pytest.raises(ValueError):
            dg.replay_document_plan(current, record(current, invalid, len(rows) + 1), inventory)
    assert raw == unchanged
