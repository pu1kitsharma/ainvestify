"""Planner output capacity and source/provenance boundaries, not quality gold."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from agents.research import document_qualification_context as qc
from agents.inference.local_models import generation_schema
from tests.research.test_document_generation import PIN, manifest, record
from tests.research.test_document_source_maps import source_with_blank_page_and_chart


def prepared(*, encoding=dg.CATALOG_ENCODING_V6, kind='intro_deck'):
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=encoding)
    request = dg.frozen_document_request(inventory, {'name': 'local-planner:4b', 'digest': 'c' * 64}, kind,
        catalog_encoding=encoding, qualification_context_profile=lc.PROFILE, page_author_pin=PIN,
        planning_schema_profile=dg.COMPACT_ANCHOR_PLAN_PROFILE)
    return inventory, request


def choice():
    return {'p': [{'i': f'P{index + 1}', 't': list(dg.TOPICS[index * 4:(index + 1) * 4]),
                  'l': 'evidence', 'e': ['U1'], 'b': [], 's': 'limited'} for index in range(3)], 'u': []}


def test_compact_multi_topic_plan_preserves_raw_and_full_quoteable_source_context():
    inventory, request = prepared()
    answer = choice()
    raw = record(request, answer, 1)
    original = deepcopy(raw)
    compiled = dg.replay_document_plan(request, raw, inventory)
    assert request[0] == 'document_plan_compact_anchors_v1'
    assert len(compiled['pages']) == 3 < len(dg.TOPICS)
    assert compiled['unsupported_topics'] == []
    assert [page['topics'] for page in compiled['pages']] == [page['t'] for page in answer['p']]
    assert compiled['pages'][0]['topic'] == answer['p'][0]['t'][0]
    page = dg.frozen_page_request(request, raw, 'P1', inventory)
    assert page[2]['model_pin'] == PIN
    assert page[2]['plan_response_hash'] == raw['response_hash']
    assert page[2]['planned_page']['topics'] == answer['p'][0]['t']
    units = qc._context_units(page)
    assert set(units) == {unit['model_unit_id'] for unit in inventory['units']}
    assert all(units[unit['model_unit_id']]['content'] == unit['content'] for unit in inventory['units'])
    source = units['U1']['content']
    authored = record(page, {'page_id': 'P1', 'title': 'Supplied evidence', 'claims': [
        {'text': source, 'basis': 'reported', 'evidence': [{'unit_id': 'U1', 'quote': source}]}],
        'table_labels': []}, 2)
    review = dg.frozen_page_review_request(page, authored, PIN)
    assert review[2]['planned_page'] == page[2]['planned_page']
    assert review[2]['companion_source_pages'] == page[2]['companion_source_pages']
    progress = dg.generation_progress(request, inventory, [raw], PIN, qualification_context_profile=lc.PROFILE)
    assert progress['maximum_model_calls'] == 7 and progress['phase'] == 'document_page'
    assert dg.document_plan_context(request, inventory, [raw], qualification_context_profile=lc.PROFILE) == (request, raw, 1)
    assert raw == original  # Compiled metadata never becomes a fabricated raw answer.
    assert page[2]['financial_validation'] == page[2]['investor_approval'] == 'not_established'


def test_compact_table_selection_projects_only_exact_native_coordinates_and_cells():
    inventory, request = prepared(kind='pitch_deck')
    answer = {'p': [{'i': 'P1', 't': ['financials', 'material_unknowns'], 'l': 'table', 'e': [],
        'b': [{'id': inventory['tables'][0]['id'], 'c': [0, 1], 'r': [1, 2], 'h': 0}], 's': 'limited'}],
        'u': [topic for topic in dg.TOPICS if topic not in {'financials', 'material_unknowns'}]}
    raw = record(request, answer, 1)
    page = dg.frozen_page_request(request, raw, 'P1', inventory)
    table = page[2]['evidence']['tables'][0]
    headers = [cell for cell in table['cells'] if cell['row'] == 1]
    authored = record(page, {'page_id': 'P1', 'title': 'Supplied table', 'claims': [], 'table_labels': [
        {'table_id': table['table_id'], 'column_labels': [cell['text'] for cell in headers],
         'caption': 'Supplied source table.', 'evidence': [
             {'unit_id': cell['model_unit_id'], 'quote': cell['text']} for cell in headers]}]}, 2)
    section = dg.renderable_document_page(page, authored)
    assert section[4]['rows'][0]['cells'][1]['text'] == inventory['tables'][0]['rows'][1][1]
    assert section[4]['rows'][0]['cells'][1]['value_ref'] in {unit['id'] for unit in inventory['units']}
    assert section[4]['rows'][1]['cells'][1]['value_ref'] is None
    assert '[Table semantics unassessed]' in section[1]
    changed = deepcopy(answer); changed['p'][0]['b'][0]['r'] = [999]
    with pytest.raises(dg.GenerationError, match='table_indexes_invalid'):
        dg.replay_document_plan(request, record(request, changed, 1), inventory)


@pytest.mark.parametrize('mutation, reason', [
    (lambda value: value['p'][0]['t'].append(value['p'][0]['t'][0]), 'schema'),
    (lambda value: value['p'][0]['t'].__setitem__(1, value['p'][0]['t'][0]), 'duplicate_page_topic'),
    (lambda value: value['u'].append(dg.TOPICS[0]), 'conflicting_topic_scope'),
    (lambda value: value['p'][0]['e'].__setitem__(0, 'U999'), 'unknown_or_duplicate_unit'),
])
def test_compact_plan_rejects_structural_or_source_scope_errors(mutation, reason):
    inventory, request = prepared()
    answer = choice(); mutation(answer)
    if reason == 'schema':
        with pytest.raises(ValidationError):
            request[3].model_validate(answer)
    else:
        with pytest.raises(dg.GenerationError, match=reason):
            dg.replay_document_plan(request, record(request, answer, 1), inventory)


def test_compact_output_bounds_pages_and_anchors_without_lowering_full_source_visibility():
    _, request = prepared()
    answer = choice()
    changed = deepcopy(answer); changed['p'][0]['e'] = ['U1', 'U2', 'U3', 'U4', 'U5']
    with pytest.raises(ValidationError):
        request[3].model_validate(changed)
    changed = deepcopy(answer); changed['p'] *= 3
    with pytest.raises(ValidationError):
        request[3].model_validate(changed)
    assert dg.compact_anchor_plan_schema('pitch_deck').model_json_schema()['properties']['p']['maxItems'] == 32
    assert dg.compact_anchor_plan_schema('investment_memo').model_json_schema()['properties']['p']['maxItems'] == 40
    canonical = dg._compile_anchor_plan(answer)
    canonical_raw = {'pages': [{k: v for k, v in page.items() if k != 'topics'} for page in canonical['pages']],
                     'unsupported_topics': canonical['unsupported_topics']}
    assert len(json.dumps(answer, separators=(',', ':'))) < len(json.dumps(canonical_raw, separators=(',', ':')))


def test_explicit_profile_preserves_historical_defaults_and_dense_source_decoder():
    source = manifest()
    inventory = dg.evidence_inventory([source], catalog_encoding=dg.CATALOG_ENCODING_V6)
    for encoding in (dg.CATALOG_ENCODING_V4, dg.CATALOG_ENCODING_V5):
        original = dg.frozen_document_request(inventory, PIN, 'intro_deck', catalog_encoding=encoding,
            qualification_context_profile=lc.PROFILE)
        unchanged = dg.frozen_document_request(inventory, PIN, 'intro_deck', catalog_encoding=encoding,
            qualification_context_profile=lc.PROFILE, planning_schema_profile=None)
        assert dg.request_json(unchanged) == dg.request_json(original)
        assert original[3] is dg.DocumentPlan and original[0] == 'document_plan_v1'
        assert 'planning_schema_profile' not in original[2]
    _, current = prepared()
    original_catalog = lc.complete_literal_catalog(inventory)
    decoded = lc.decode_complete_literal_catalog(current[2]['catalog'])
    assert decoded['pages'] == original_catalog['pages']
    assert decoded['table_navigation'] == original_catalog['table_navigation']
    assert 'first_unit_index+j' in current[1]
    with pytest.raises(dg.GenerationError, match='compact_anchor_plan_requires'):
        dg.frozen_document_request(inventory, PIN, 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V4,
            qualification_context_profile=lc.PROFILE, planning_schema_profile=dg.COMPACT_ANCHOR_PLAN_PROFILE)


def test_finite_anchor_profile_uses_actual_grammar_bounds_instead_of_removed_patterns():
    inventory, old = prepared()
    request = dg.frozen_document_request(inventory, old[2]['model_pin'], 'intro_deck',
        catalog_encoding=dg.CATALOG_ENCODING_V6, qualification_context_profile=lc.PROFILE,
        page_author_pin=PIN, planning_schema_profile=dg.COMPACT_ANCHOR_PLAN_PROFILE_V2)
    assert request[0] == 'document_plan_compact_anchors_v2'
    grammar = generation_schema(request[3], bound_strings=True)
    page = grammar['$defs']['BoundedAnchorPage_intro_deck']['properties']
    assert page['i']['enum'] == [f'P{index}' for index in range(1, 9)]
    assert request[3].model_json_schema()['$defs']['BoundedAnchorPage_intro_deck']['properties']['e']['items']['minLength'] == 2
    assert page['e']['items']['maxLength'] == 6  # Existing grammar drops minima, retains explicit maxima.
    table_id = grammar['$defs']['BoundedAnchorTable_intro_deck']['properties']['id']
    assert table_id.get('enum', [table_id.get('const')]) == [inventory['tables'][0]['id']]
    assert 'pattern' not in page['i']
    for field, bad in (('i', 'P' + '\\' * 192 + 'x' * 1439), ('e', ['U123456789'])):
        answer = choice(); answer['p'][0][field] = bad
        with pytest.raises(ValidationError):
            request[3].model_validate(answer)
    answer = choice()
    answer['p'][0].update(l='table', b=[{'id': 'foreign-table', 'c': [0, 1], 'r': [1], 'h': 0}])
    with pytest.raises(ValidationError):
        request[3].model_validate(answer)
    raw = record(request, choice(), 1)
    plan = dg.replay_document_plan(request, raw, inventory)
    assert len(plan['pages']) == 3 and plan['unsupported_topics'] == []
    writer = dg.frozen_page_request(request, raw, 'P1', inventory)
    assert len(qc._context_units(writer)) == len(inventory['units'])
    assert writer[2]['model_pin'] == PIN and writer[2]['plan_response_hash'] == raw['response_hash']
    assert dg.request_json(old) == dg.request_json(dg.frozen_document_request(inventory, old[2]['model_pin'],
        'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V6, qualification_context_profile=lc.PROFILE,
        page_author_pin=PIN, planning_schema_profile=dg.COMPACT_ANCHOR_PLAN_PROFILE))
    old_grammar = generation_schema(old[3], bound_strings=True)
    assert 'pattern' not in old_grammar['$defs']['CompactAnchorPage']['properties']['i']
    assert 'maxLength' not in old_grammar['$defs']['CompactAnchorPage']['properties']['i']


def test_finite_profile_cannot_choose_native_tables_when_original_has_none():
    inventory = dg.evidence_inventory([source_with_blank_page_and_chart()], catalog_encoding=dg.CATALOG_ENCODING_V6)
    assert not inventory['tables']
    schema = dg.compact_anchor_plan_schema('intro_deck', profile=dg.COMPACT_ANCHOR_PLAN_PROFILE_V2,
        inventory=inventory)
    grammar = generation_schema(schema, bound_strings=True)
    assert grammar['$defs']['BoundedAnchorPage_intro_deck']['properties']['b']['maxItems'] == 0
    answer = choice(); answer['p'][0]['b'] = [{'id': 'foreign-table', 'c': [0, 1], 'r': [1], 'h': 0}]
    with pytest.raises(ValidationError):
        schema.model_validate(answer)


def test_explicit_32k_context_changes_only_planning_and_preserves_full_context_gates():
    inventory, _ = prepared()
    common = {'catalog_encoding': dg.CATALOG_ENCODING_V6, 'qualification_context_profile': lc.PROFILE,
        'page_author_pin': PIN, 'planning_schema_profile': dg.COMPACT_ANCHOR_PLAN_PROFILE_V2}
    old = dg.frozen_document_request(inventory, PIN, 'intro_deck', **common)
    assert dg.request_json(old) == dg.request_json(dg.frozen_document_request(
        inventory, PIN, 'intro_deck', planning_context_profile=None, **common))
    current = dg.frozen_document_request(inventory, PIN, 'intro_deck',
        planning_context_profile=dg.PLAN_CONTEXT_PROFILE_32K, **common)
    assert current[2]['catalog'] == old[2]['catalog'] and current[:2] == old[:2]
    assert current[3].model_json_schema() == old[3].model_json_schema()
    assert current[2]['options'] == {**old[2]['options'], 'context_tokens': 32768}
    answer = choice()
    truncated = record(old, answer, 1); truncated['routing']['prompt_tokens'] = 8194
    with pytest.raises(ValueError, match='full|context|truncat'):
        dg.replay_document_plan(old, truncated, inventory)
    planned_row = record(current, answer, 1)
    dg.replay_document_plan(current, planned_row, inventory)
    still_truncated = deepcopy(planned_row); still_truncated['routing']['prompt_tokens'] = 16386
    with pytest.raises(ValueError, match='full|context|truncat'):
        dg.replay_document_plan(current, still_truncated, inventory)
    page = dg.frozen_page_request(current, planned_row, 'P1', inventory)
    assert page[2]['options']['context_tokens'] == 16384 and 'planning_context_profile' not in page[2]
    text = qc._context_units(page)['U1']['content']
    authored = record(page, {'page_id': 'P1', 'title': 'Supplied evidence', 'claims': [
        {'text': text, 'basis': 'reported', 'evidence': [{'unit_id': 'U1', 'quote': text}]}], 'table_labels': []}, 2)
    review = dg.frozen_page_review_request(page, authored, PIN)
    assert review[2]['options']['context_tokens'] == 16384
    changed = {key: deepcopy(value) for key, value in current[2].items() if key not in
        {'request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'}}
    changed.pop('planning_context_profile')
    unsigned_context = dg._request(current[0], current[1], changed, current[3])
    with pytest.raises(dg.GenerationError, match='planning_context_options_changed'):
        dg.replay_document_plan(unsigned_context, record(unsigned_context, answer, 1), inventory)
    for encoding, schema_profile, context_profile in (
        (dg.CATALOG_ENCODING_V5, dg.COMPACT_ANCHOR_PLAN_PROFILE_V2, dg.PLAN_CONTEXT_PROFILE_32K),
        (dg.CATALOG_ENCODING_V6, dg.COMPACT_ANCHOR_PLAN_PROFILE, dg.PLAN_CONTEXT_PROFILE_32K),
        (dg.CATALOG_ENCODING_V6, dg.COMPACT_ANCHOR_PLAN_PROFILE_V2, 'unknown-context')):
        with pytest.raises(dg.GenerationError, match='explicit_32k_planning_profile'):
            dg.frozen_document_request(inventory, PIN, 'intro_deck', catalog_encoding=encoding,
                qualification_context_profile=lc.PROFILE, planning_schema_profile=schema_profile,
                planning_context_profile=context_profile)
