"""Actual role-prefix reconstruction and unqualified retrieval-index boundaries."""
from copy import deepcopy

import pytest

from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from agents.research import document_source_index as si
from agents.research import document_context_capacity as cc
from agents.research import document_qualification_context as qc
from tests.research.test_document_generation import PIN, record
from tests.research.test_document_source_maps import source_with_blank_page_and_chart


def prepared(*, profile=dg.INDEXED_PHYSICAL_PLAN_PROFILE_V4, source_context_profile=None, reader_pin=None):
    inventory = dg.evidence_inventory([source_with_blank_page_and_chart()], catalog_encoding=dg.CATALOG_ENCODING_V6)
    reader = reader_pin or {'name': 'local-planner:4b', 'digest': 'c' * 64}
    seed = dg.frozen_document_request(inventory, reader, 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V6,
        qualification_context_profile=lc.PROFILE, page_author_pin=PIN,
        planning_schema_profile=profile, source_context_profile=source_context_profile)
    reads = dg._source_index_requests_from_seed(seed, inventory)
    rows = []
    for number, request in enumerate(reads, 1):
        units = dg.source_map_literal_lookup(request[2]['source_group'])
        choice = next(((uid, item['content'][:200]) for uid, item in units.items() if item['content'].strip()), None)
        if profile == dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5:
            answer = {'group_id': request[2]['source_group_id'],
                'focus_unit_ids': [choice[0]] if choice else [], 'visual_semantics': 'unassessed',
                'scope_status': 'local_source_selection_proposal_not_diligence'}
        else:
            answer = {'group_id': request[2]['source_group_id'],
                'status': 'proposed_literal_summary' if choice else 'unassessed',
                'synopsis': choice[1] if choice else '',
                'quotes': [{'unit_id': choice[0], 'quote': choice[1]}] if choice else [],
                'visual_semantics': 'unassessed', 'scope_status': 'local_source_index_proposal_not_diligence'}
        rows.append(record(request, answer, number))
    return inventory, seed, reads, rows


def planned():
    return {'p': [{'l': 'evidence', 'e': ['G2'], 'b': [], 's': 'limited'} for _ in range(3)],
            'd': [[f'P{index // 4 + 1}'] for index in range(12)]}


def test_every_complete_physical_group_is_read_before_planning_and_exact_offsets_are_preserved(monkeypatch):
    inventory, seed, reads, rows = prepared()
    original = deepcopy(rows)
    monkeypatch.setattr(dg, 'frozen_source_map_requests', lambda *a, **k: (_ for _ in ()).throw(AssertionError('retired source-map route')))
    initial = dg.generation_progress(seed, inventory, [], PIN, qualification_context_profile=lc.PROFILE)
    assert initial['phase'] == 'document_source_index' and dg.request_json(initial['request']) == dg.request_json(reads[0])
    assert initial['maximum_model_calls'] == len(reads) + 81
    second = dg.generation_progress(seed, inventory, rows[:1], PIN, qualification_context_profile=lc.PROFILE)
    assert second['phase'] == 'document_source_index' and second['source_page_read_id'] == 'G2'
    progress = dg.generation_progress(seed, inventory, rows, PIN, qualification_context_profile=lc.PROFILE)
    assert progress['phase'] == 'document_plan' and progress['completed_source_page_reads'] == 2
    request = progress['request']
    assert request[0] == 'document_plan_indexed_physical_v4' and request[2]['options']['context_tokens'] == 16384
    assert 'pages' not in request[2]['catalog'] and 'literal_unit_pool' not in request[2]['catalog']
    assert request[2]['catalog']['entries'][0]['status'] == 'unassessed'
    assert request[2]['catalog']['entries'][1]['response_hash'] == rows[1]['response_hash']
    plan_row = record(request, planned(), 3)
    context_request, context_row, offset = dg.document_plan_context(seed, inventory, [*rows, plan_row],
        qualification_context_profile=lc.PROFILE, reviewer_pin=PIN)
    assert dg.request_json(context_request) == dg.request_json(request) and context_row == plan_row and offset == 3
    author = dg.generation_progress(seed, inventory, [*rows, plan_row], PIN, qualification_context_profile=lc.PROFILE)
    assert author['phase'] == 'document_page' and author['maximum_model_calls'] == 9
    assert author['request'][2]['model_pin'] == PIN
    group = next(page for page in inventory['source_map_topology'] if page['page_or_slide'] == 2)
    expected = dg.source_map_literal_lookup(dg._source_map_page_view(inventory, group))
    actual = qc._context_units(author['request'])
    assert set(actual) == set(expected) and all(actual[uid]['content'] == item['content'] for uid, item in expected.items())
    assert rows == original


def test_index_prefix_failure_or_reorder_never_reaches_planner_or_creates_fallback():
    inventory, seed, _, rows = prepared()
    failed = deepcopy(rows); failed[0]['error'] = 'synthetic terminal failure'
    state = dg.generation_progress(seed, inventory, failed, PIN, qualification_context_profile=lc.PROFILE)
    assert state['state'] == 'blocked' and 'request' not in state
    state = dg.generation_progress(seed, inventory, list(reversed(rows)), PIN, qualification_context_profile=lc.PROFILE)
    assert state['state'] == 'blocked' and 'request' not in state
    with pytest.raises(dg.GenerationError, match='prefix_and_actual_plan_required'):
        dg.document_plan_context(seed, inventory, rows, qualification_context_profile=lc.PROFILE)


def test_rehashed_index_cannot_promote_diligence_or_modify_original_table_scope():
    inventory, seed, _, rows = prepared()
    request = dg.generation_progress(seed, inventory, rows, PIN, qualification_context_profile=lc.PROFILE)['request']
    payload = {key: deepcopy(value) for key, value in request[2].items() if key not in
        {'request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'}}
    payload['catalog']['investor_approval'] = 'approved'
    payload['catalog']['catalog_digest'] = dg.canonical_digest({k: v for k, v in payload['catalog'].items() if k != 'catalog_digest'})
    altered = dg._request(request[0], request[1], payload, request[3])
    with pytest.raises(dg.GenerationError, match='original_grid_or_scope_changed'):
        dg.replay_document_plan(altered, record(altered, planned(), 3), inventory)
    with pytest.raises(dg.GenerationError, match='explicit_indexed_physical_profile'):
        dg.frozen_document_request(inventory, PIN, 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V6,
            qualification_context_profile=lc.PROFILE, source_page_reads=rows)


def test_complete_indexed_generation_remains_only_an_unqualified_draft():
    inventory, seed, _, rows = prepared()
    attempts = deepcopy(rows)
    progress = dg.generation_progress(seed, inventory, attempts, PIN, qualification_context_profile=lc.PROFILE)
    attempts.append(record(progress['request'], planned(), 3))
    for _ in range(3):
        progress = dg.generation_progress(seed, inventory, attempts, PIN, qualification_context_profile=lc.PROFILE)
        page = progress['request']
        units = qc._context_units(page)
        uid, unit = next((uid, value) for uid, value in units.items() if value['content'].strip() and value['kind'] == 'text')
        answer = {'page_id': page[2]['planned_page']['page_id'], 'title': 'Supplied evidence', 'claims': [
            {'text': unit['content'], 'basis': 'reported', 'evidence': [{'unit_id': uid, 'quote': unit['content']}]}],
            'table_labels': []}
        attempts.append(record(page, answer, len(attempts) + 1))
        progress = dg.generation_progress(seed, inventory, attempts, PIN, qualification_context_profile=lc.PROFILE)
        assert progress['phase'] == 'document_page_review'
        attempts.append(record(progress['request'], {'verdict': 'pass', 'issues': [], 'financial_status': 'not_established'}, len(attempts) + 1))
    result = dg.generation_progress(seed, inventory, attempts, PIN, qualification_context_profile=lc.PROFILE)
    assert result['state'] == 'draft_complete' and result['plan_response_id'] == 'response_3'
    assert result['completed_source_page_reads'] == 2
    assert result['planner_reading_scope'] == 'recorded_retrieval_index_and_original_native_grids'
    assert result['literal_reading_scope'] == 'complete_selected_original_page_literals_unreviewed'
    assert result['source_index_status'] == 'proposed_unqualified'
    assert result['financial_validation'] == result['regulatory_approval'] == result['investor_approval'] == 'not_established'


def test_selected_reader_projects_whole_originals_without_authored_synopsis_or_quote_and_preserves_old_seed():
    old_inventory, old_seed, _, _ = prepared()
    inventory, seed, reads, rows = prepared(profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5)
    assert seed[0] == 'document_source_selection_v1'
    assert set(reads[1][3].model_fields) == {'group_id', 'focus_unit_ids', 'visual_semantics', 'scope_status'}
    frozen = deepcopy(rows)
    progress = dg.generation_progress(seed, inventory, rows, PIN, qualification_context_profile=lc.PROFILE)
    assert progress['phase'] == 'document_plan' and progress['request'][0] == 'document_plan_selected_physical_v5'
    catalog = progress['request'][2]['catalog']
    assert all('synopsis' not in entry and 'quotes' not in entry for entry in catalog['entries'])
    own = dg.source_map_literal_lookup(reads[1][2]['source_group'])
    for unit in catalog['entries'][1]['selected_original_units']:
        assert unit['content'] == own[unit['unit_id']]['content']
        assert unit['source_locator'] == own[unit['unit_id']]['source_locator']
    plan = record(progress['request'], planned(), 3)
    state = dg.generation_progress(seed, inventory, [*rows, plan], PIN, qualification_context_profile=lc.PROFILE)
    assert state['phase'] == 'document_page' and state['request'][2]['model_pin'] == PIN
    actual = qc._context_units(state['request'])
    assert set(actual) == set(own)  # Every companion unit, not only model focus pointers.
    assert rows == frozen
    assert dg.request_json(old_seed) == dg.request_json(dg.frozen_document_request(old_inventory,
        old_seed[2]['model_pin'], 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V6,
        qualification_context_profile=lc.PROFILE, page_author_pin=PIN,
        planning_schema_profile=dg.INDEXED_PHYSICAL_PLAN_PROFILE_V4))


def test_selected_source_handle_binding_and_empty_group_minimum_are_not_bypassed():
    inventory, seed, reads, rows = prepared(profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5)
    assert rows[0]['answer']['focus_unit_ids'] == []
    assert reads[0][3].model_json_schema()['properties']['focus_unit_ids']['maxItems'] == 0
    assert reads[1][3].model_json_schema()['properties']['focus_unit_ids']['minItems'] == 1
    bad = deepcopy(rows)
    altered = deepcopy(bad[1]['answer']); altered['focus_unit_ids'] = ['U9999']
    bad[1] = record(reads[1], altered, 2)
    blocked = dg.generation_progress(seed, inventory, bad, PIN, qualification_context_profile=lc.PROFILE)
    assert blocked['state'] == 'blocked' and 'request' not in blocked
    progress = dg.generation_progress(seed, inventory, rows, PIN, qualification_context_profile=lc.PROFILE)
    plan_row = record(progress['request'], planned(), 3)
    request, actual_row, offset = dg.document_plan_context(seed, inventory, [*rows, plan_row],
        qualification_context_profile=lc.PROFILE, reviewer_pin=PIN)
    assert offset == 3 and actual_row == plan_row and request[0] == 'document_plan_selected_physical_v5'


def test_explicit_source_32k_context_does_not_change_planner_author_or_historical_requests():
    inventory, old_seed, _, _ = prepared(profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5)
    assert 'source_context_profile' not in old_seed[2]
    assert old_seed[2]['options']['context_tokens'] == 16384
    inventory, seed, reads, rows = prepared(profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5,
        source_context_profile=si.SOURCE_CONTEXT_PROFILE_32K)
    assert all(request[2]['options']['context_tokens'] == 32768 and
               request[2]['options']['max_tokens'] == 600 for request in reads)
    progress = dg.generation_progress(seed, inventory, rows, PIN, qualification_context_profile=lc.PROFILE)
    plan = progress['request']
    assert plan[2]['source_context_profile'] == si.SOURCE_CONTEXT_PROFILE_32K
    assert plan[2]['catalog']['source_index_request_profile']['source_context_profile'] == si.SOURCE_CONTEXT_PROFILE_32K
    assert plan[2]['options']['context_tokens'] == 16384 and plan[2]['options']['max_tokens'] == 4000
    row = record(plan, planned(), 3)
    page = dg.frozen_page_request(plan, row, 'P1', inventory)
    assert page[2]['options']['context_tokens'] == 16384 and page[2]['options']['max_tokens'] == 2200
    assert dg.request_json(old_seed) == dg.request_json(dg.frozen_document_request(inventory,
        old_seed[2]['model_pin'], 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V6,
        qualification_context_profile=lc.PROFILE, page_author_pin=PIN,
        planning_schema_profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5, source_context_profile=None))


def test_compact_selected_index_is_global_only_and_replays_full_original_entries_and_author_context():
    inventory, seed, _, rows = prepared(profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5,
        source_context_profile=si.SOURCE_CONTEXT_PROFILE_32K)
    flag = si.SOURCE_INDEX_ENCODING_V2
    encoded_seed = dg.frozen_document_request(inventory, seed[2]['model_pin'], 'intro_deck',
        catalog_encoding=dg.CATALOG_ENCODING_V6, qualification_context_profile=lc.PROFILE,
        page_author_pin=PIN, planning_schema_profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5,
        source_context_profile=si.SOURCE_CONTEXT_PROFILE_32K, source_index_encoding=flag)
    assert dg.request_json(encoded_seed) == dg.request_json(seed)
    assert 'source_index_encoding' not in encoded_seed[2]  # Stored by outer run, not reader inputs.
    old = dg.generation_progress(seed, inventory, rows, PIN, qualification_context_profile=lc.PROFILE)['request']
    progress = dg.generation_progress(seed, inventory, rows, PIN, qualification_context_profile=lc.PROFILE,
        source_index_encoding=flag)
    request = progress['request']
    assert request[2]['source_index_encoding'] == request[2]['catalog']['source_index_encoding'] == flag
    assert si.decode_source_index_entries(inventory, request[2]['catalog']) == old[2]['catalog']['entries']
    assert request[2]['catalog']['table_navigation'] == old[2]['catalog']['table_navigation']
    plan_row = record(request, planned(), 3)
    actual_request, actual_row, offset = dg.document_plan_context(seed, inventory, [*rows, plan_row],
        qualification_context_profile=lc.PROFILE, source_index_encoding=flag)
    assert dg.request_json(actual_request) == dg.request_json(request) and actual_row == plan_row and offset == 3
    page = dg.frozen_page_request(request, plan_row, 'P1', inventory)
    original_page = dg.frozen_page_request(old, record(old, planned(), 3), 'P1', inventory)
    assert qc._context_units(page) == qc._context_units(original_page)
    assert page[2]['options']['context_tokens'] == 16384 and page[2]['investor_approval'] == 'not_established'


def test_external_material_32k_profile_preserves_source_and_plan_requests_and_binds_future_roles():
    inventory, seed, reads, rows = prepared(profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5,
        source_context_profile=si.SOURCE_CONTEXT_PROFILE_32K)
    arguments = {'qualification_context_profile': lc.PROFILE, 'source_index_encoding': si.SOURCE_INDEX_ENCODING_V2}
    profile = cc.MATERIAL_CONTEXT_PROFILE_32K
    initial = dg.generation_progress(seed, inventory, [], PIN, material_context_profile=profile, **arguments)
    assert dg.request_json(initial['request']) == dg.request_json(reads[0])
    old_plan = dg.generation_progress(seed, inventory, rows, PIN, **arguments)['request']
    current_plan = dg.generation_progress(seed, inventory, rows, PIN, material_context_profile=profile, **arguments)['request']
    assert dg.request_json(current_plan) == dg.request_json(old_plan) and 'material_context_profile' not in current_plan[2]
    plan_row = record(current_plan, planned(), 3)
    legacy = dg.frozen_page_request(current_plan, plan_row, 'P1', inventory)
    assert dg.request_json(legacy) == dg.request_json(dg.frozen_page_request(current_plan, plan_row,
        'P1', inventory, material_context_profile=None))
    page = dg.generation_progress(seed, inventory, [*rows, plan_row], PIN,
        material_context_profile=profile, **arguments)['request']
    assert page[2]['material_context_profile'] == profile and page[2]['options']['context_tokens'] == 32768
    assert page[2]['options']['max_tokens'] == legacy[2]['options']['max_tokens'] == 2200
    assert page[2]['plan_response_hash'] == legacy[2]['plan_response_hash'] == plan_row['response_hash']
    assert qc._context_units(page) == qc._context_units(legacy)
    units = qc._context_units(page)
    uid, unit = next((uid, value) for uid, value in units.items() if value['content'].strip() and value['kind'] == 'text')
    answer = {'page_id': 'P1', 'title': 'Supplied evidence', 'claims': [
        {'text': unit['content'], 'basis': 'reported', 'evidence': [{'unit_id': uid, 'quote': unit['content']}]}], 'table_labels': []}
    authored = record(page, answer, 4)
    review = dg.frozen_page_review_request(page, authored, PIN, material_context_profile=profile)
    assert review[2]['material_context_profile'] == profile and review[2]['options']['context_tokens'] == 32768
    assert review[2]['options']['max_tokens'] == 2200
    assert review[2]['maximum_page_answer_characters'] == page[2]['maximum_page_answer_characters']
    ambiguous = deepcopy(authored); ambiguous['routing']['prompt_tokens'] = 8194
    with pytest.raises(dg.GenerationError, match='ambiguous_16k_truncation'):
        dg.replay_document_page(page, ambiguous)
    with pytest.raises(dg.GenerationError, match='match_frozen_author_context'):
        dg.frozen_page_review_request(legacy, record(legacy, answer, 4), PIN, material_context_profile=profile)
    actual_plan, actual_row, offset = dg.document_plan_context(seed, inventory, [*rows, plan_row],
        material_context_profile=profile, **arguments)
    assert dg.request_json(actual_plan) == dg.request_json(current_plan) and actual_row == plan_row and offset == 3


def test_reader_prefix_can_stay_9b_while_only_new_global_plan_uses_4b_and_materials_stay_9b():
    inventory, source_seed, reads, rows = prepared(profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5,
        source_context_profile=si.SOURCE_CONTEXT_PROFILE_32K, reader_pin=PIN)
    planner = {'name': 'qwen3.5:4b', 'digest': 'c' * 64}
    child_seed = dg.frozen_document_request(inventory, planner, 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V6,
        qualification_context_profile=lc.PROFILE, page_author_pin=PIN, source_reader_pin=PIN,
        planning_schema_profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5, source_context_profile=si.SOURCE_CONTEXT_PROFILE_32K,
        source_index_encoding=si.SOURCE_INDEX_ENCODING_V2)
    assert dg.request_json(child_seed) == dg.request_json(source_seed)
    assert child_seed[2]['model_pin'] == PIN and 'source_reader_pin' not in child_seed[2]
    assert [dg.request_json(req) for req in dg._source_index_requests_from_seed(child_seed, inventory)] == [dg.request_json(req) for req in reads]
    arguments = {'qualification_context_profile': lc.PROFILE, 'source_index_encoding': si.SOURCE_INDEX_ENCODING_V2,
        'material_context_profile': cc.MATERIAL_CONTEXT_PROFILE_32K, 'document_planner_pin': planner}
    progress = dg.generation_progress(child_seed, inventory, rows, PIN, **arguments)
    plan = progress['request']
    assert plan[2]['model_pin'] == planner and plan[2]['source_reader_pin'] == PIN
    assert plan[2]['catalog']['source_index_request_profile']['reader_pin'] == PIN
    assert si.decode_source_index_entries(inventory, plan[2]['catalog'])[1]['reader_pin'] == PIN
    plan_row = record(plan, planned(), 3)
    actual, row, offset = dg.document_plan_context(child_seed, inventory, [*rows, plan_row], **arguments)
    assert dg.request_json(actual) == dg.request_json(plan) and row == plan_row and offset == 3
    author = dg.generation_progress(child_seed, inventory, [*rows, plan_row], PIN, **arguments)['request']
    assert author[2]['model_pin'] == PIN and author[2]['options']['context_tokens'] == 32768
    assert rows[0]['model'] == rows[1]['model'] == PIN['name']
