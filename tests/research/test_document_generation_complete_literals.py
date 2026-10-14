"""Direct whole-literal planning keeps source context and exact draft gates."""
from copy import deepcopy

import pytest

from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from agents.research import document_qualification_context as qc
from tests.research.test_document_generation import PIN, manifest, record, planned
from tests.research.test_document_qualification_context import proposal_unit
from tests.research.test_document_source_maps import source_with_blank_page_and_chart


def initial(source=None, *, kind='pitch_deck'):
    inventory = dg.evidence_inventory([source or manifest()], catalog_encoding=dg.CATALOG_ENCODING_V4)
    request = dg.frozen_document_request(inventory, PIN, kind, mandate='Private internal diligence.',
        catalog_encoding=dg.CATALOG_ENCODING_V4, qualification_context_profile=lc.PROFILE)
    return inventory, request


def test_complete_literal_flow_starts_with_plan_without_mapper_or_coverage_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Direct literal planning must never call source-map stages')
    monkeypatch.setattr(dg, 'frozen_source_map_requests', forbidden)
    source = source_with_blank_page_and_chart()
    inventory, request = initial(source)
    assert request[0] == 'document_plan_v1' and request[1] == lc.PLAN_INSTRUCTION
    assert request[2]['catalog']['literal_coverage']['physical_page_count'] == 2
    assert inventory['source_map_topology'][0]['page_or_slide'] == 1  # Empty physical page retained.
    progress = dg.generation_progress(request, inventory, [], PIN, qualification_context_profile=lc.PROFILE)
    assert progress['phase'] == 'document_plan' and progress['maximum_model_calls'] == 81
    first = next(unit['model_unit_id'] for unit in inventory['units']
                 if unit['kind'] == 'text' and isinstance(unit['content'], str) and unit['content'].strip())
    choice = planned(inventory); choice['pages'][0]['narrative_unit_ids'] = [first]
    row = record(request, choice, 1)
    actual = dg.document_plan_context(request, inventory, [row], qualification_context_profile=lc.PROFILE, reviewer_pin=PIN)
    assert actual == (request, row, 1)
    progress = dg.generation_progress(request, inventory, [row], PIN, qualification_context_profile=lc.PROFILE)
    assert progress['phase'] == 'document_page' and progress['maximum_model_calls'] == 3
    opaque = next(unit['model_unit_id'] for unit in inventory['units'] if not isinstance(unit['content'], str))
    bad = deepcopy(choice); bad['pages'][0]['narrative_unit_ids'] = [opaque]
    with pytest.raises(dg.GenerationError, match='unmapped_source_evidence'):
        dg.replay_document_plan(request, record(request, bad, 1), inventory)


def test_complete_literal_author_and_page_reviewer_share_quoteable_original_qualifiers():
    source = manifest()
    qualifier = proposal_unit(source, 'The source labels future figures as projections for 2025.')
    inventory, request = initial(source)
    uid = next(unit['model_unit_id'] for unit in inventory['units'] if unit['id'] == qualifier['id'])
    plan = planned(inventory); plan['pages'][0]['narrative_unit_ids'] = [uid]
    planned_row = record(request, plan, 1)
    page = dg.frozen_page_request(request, planned_row, 'P1', inventory)
    assert page[2]['qualification_context_profile'] == qc.LITERAL_PROFILE
    assert 'source_reading_proposals' not in page[2]
    assert page[2]['evidence']['units'] == []
    assert qc._context_units(page)[uid]['content'] == qualifier['content']
    proposed = {'page_id': 'P1', 'title': 'Supplied projections', 'claims': [
        {'text': qualifier['content'], 'basis': 'projected', 'evidence': [{'unit_id': uid, 'quote': qualifier['content']}]}],
        'table_labels': []}
    authored = record(page, proposed, 2)
    reviewer = dg.frozen_page_review_request(page, authored, PIN)
    assert reviewer[0] == 'document_page_complete_literal_context_review_v2'
    assert reviewer[2]['mandate'] == page[2]['mandate'] == request[2]['mandate']
    assert reviewer[2]['companion_source_pages'] == page[2]['companion_source_pages']
    reviewed = record(reviewer, {'verdict': 'pass', 'issues': [], 'financial_status': 'not_established'}, 3)
    result = dg.generation_progress(request, inventory, [planned_row, authored, reviewed], PIN,
                                    qualification_context_profile=lc.PROFILE)
    assert result['state'] == 'draft_complete'
    assert result['sections'][0][1] == '[Projected] ' + qualifier['content'] + ' [S1]'
    assert result['source_mapping'] == result['source_coverage_review'] == 'not_performed'
    assert result['financial_validation'] == result['regulatory_approval'] == result['investor_approval'] == 'not_established'
    assert authored['answer'] == proposed


def test_complete_original_native_table_is_directly_selectable_with_exact_cell_lineage():
    inventory, request = initial()
    plan = planned(inventory, table=True)
    plan['pages'][0]['narrative_unit_ids'] = []
    planned_row = record(request, plan, 1)
    page = dg.frozen_page_request(request, planned_row, 'P1', inventory)
    original = page[2]['evidence']['tables'][0]
    header = [cell for cell in original['cells'] if cell['row'] == 1]
    proposed = {'page_id': 'P1', 'title': 'Supplied source table', 'claims': [], 'table_labels': [
        {'table_id': original['table_id'], 'column_labels': [cell['text'] for cell in header],
         'caption': 'Supplied source table.', 'evidence': [
            {'unit_id': cell['model_unit_id'], 'quote': cell['text']} for cell in header]}]}
    authored = record(page, proposed, 2)
    section = dg.renderable_document_page(page, authored)
    assert section[4]['columns'][1]['label'] == '2024 projection'
    assert section[4]['rows'][0]['cells'][1]['text'] == inventory['tables'][0]['rows'][1][1]
    assert section[4]['rows'][1]['cells'][1]['text'] == 'Blank in source'
    assert section[4]['rows'][1]['cells'][1]['value_ref'] is None
    assert section[4]['rows'][0]['cells'][1]['value_ref'] in {unit['id'] for unit in inventory['units']}
    assert '[Table semantics unassessed]' in section[1] and 'slide 1' in section[2]


def test_direct_literal_mode_rejects_legacy_stages_and_rehashed_source_changes():
    inventory, request = initial()
    for extra in ({'source_maps': []}, {'source_map_profiles': ['quoted-v1']},
                  {'source_map_token_budgets': [900]}, {'source_map_reviews': []},
                  {'source_coverage_reviewer_pin': PIN}):
        with pytest.raises(dg.GenerationError, match='direct_plan_profile_without_source_maps'):
            dg.frozen_document_request(inventory, PIN, 'pitch_deck', catalog_encoding=dg.CATALOG_ENCODING_V4,
                qualification_context_profile=lc.PROFILE, **extra)
    with pytest.raises(dg.GenerationError):
        dg.generation_progress(request, inventory, [], PIN, qualification_context_profile=qc.PROFILE)
    changed = deepcopy(request[2])
    changed['catalog']['table_navigation'][0]['rows'][1][1] = '999'
    changed['catalog']['catalog_digest'] = dg.canonical_digest({key: value for key, value in changed['catalog'].items()
                                                             if key != 'catalog_digest'})
    changed.pop('request_binding_digest')
    rebuilt = dg._request(request[0], request[1], changed, request[3])
    with pytest.raises(dg.GenerationError, match='complete_original_literal_catalog_changed'):
        dg.replay_document_plan(rebuilt, record(rebuilt, planned(inventory), 1), inventory)


def test_positional_literal_alias_preserves_every_frame_and_uses_same_exact_page_roles():
    source = manifest()
    inventory = dg.evidence_inventory([source], catalog_encoding=dg.CATALOG_ENCODING_V5)
    old = dg.frozen_document_request(inventory, PIN, 'pitch_deck', catalog_encoding=dg.CATALOG_ENCODING_V4,
        qualification_context_profile=lc.PROFILE)
    current = dg.frozen_document_request(inventory, PIN, 'pitch_deck', catalog_encoding=dg.CATALOG_ENCODING_V5,
        qualification_context_profile=lc.PROFILE)
    columns = current[2]['catalog']['page_columns']
    assert [dict(zip(columns, row)) for row in current[2]['catalog']['pages']] == old[2]['catalog']['pages']
    assert current[2]['catalog']['table_navigation'] == old[2]['catalog']['table_navigation']
    assert old[1] == lc.PLAN_INSTRUCTION and current[1].startswith(old[1]) and 'page_columns' in current[1]
    assert dg.frozen_document_request(inventory, PIN, 'pitch_deck', catalog_encoding=dg.CATALOG_ENCODING_V4,
        qualification_context_profile=lc.PROFILE) == old
    choice = planned(inventory)
    planned_row = record(current, choice, 1)
    role = dg.generation_progress(current, inventory, [planned_row], PIN, qualification_context_profile=lc.PROFILE)
    assert role['phase'] == 'document_page' and role['maximum_model_calls'] == 3
    page = role['request']
    assert page[2]['qualification_context_profile'] == qc.LITERAL_PROFILE
    literal = qc._context_units(page)['U1']['content']
    proposed = {'page_id': 'P1', 'title': 'Supplied evidence', 'claims': [
        {'text': literal, 'basis': 'reported', 'evidence': [{'unit_id': 'U1', 'quote': literal}]}], 'table_labels': []}
    authored = record(page, proposed, 2)
    review = dg.frozen_page_review_request(page, authored, PIN)
    reviewed = record(review, {'verdict': 'pass', 'issues': [], 'financial_status': 'not_established'}, 3)
    context = dg.document_plan_context(current, inventory, [planned_row, authored, reviewed],
        qualification_context_profile=lc.PROFILE, reviewer_pin=PIN)
    assert context == (current, planned_row, 1)
    result = dg.generation_progress(current, inventory, [planned_row, authored, reviewed], PIN,
                                   qualification_context_profile=lc.PROFILE)
    assert result['state'] == 'draft_complete' and '[Reported] ' + literal in result['sections'][0][1]
    assert result['source_mapping'] == result['source_coverage_review'] == 'not_performed'
    assert result['financial_validation'] == result['investor_approval'] == 'not_established'


def test_compact_literal_planner_pin_can_change_without_downgrading_page_author_or_reviewer():
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V5)
    common = {'catalog_encoding': dg.CATALOG_ENCODING_V5, 'qualification_context_profile': lc.PROFILE}
    original = dg.frozen_document_request(inventory, PIN, 'pitch_deck', **common)
    assert dg.request_json(original) == dg.request_json(dg.frozen_document_request(
        inventory, PIN, 'pitch_deck', page_author_pin=None, **common))
    assert 'page_author_pin' not in original[2]
    planner = {'name': 'local-planner:4b', 'digest': 'c' * 64}
    request = dg.frozen_document_request(inventory, planner, 'pitch_deck', page_author_pin=PIN, **common)
    assert request[2]['model_pin'] == planner and request[2]['page_author_pin'] == PIN
    assert request[2]['catalog'] == original[2]['catalog'] and request[2]['options'] == original[2]['options']
    planned_row = record(request, planned(inventory), 1)
    page = dg.frozen_page_request(request, planned_row, 'P1', inventory)
    assert page[2]['model_pin'] == PIN and page[2]['plan_response_hash'] == planned_row['response_hash']
    source = qc._context_units(page)['U1']['content']
    answer = {'page_id': 'P1', 'title': 'Supplied evidence', 'claims': [
        {'text': source, 'basis': 'reported', 'evidence': [{'unit_id': 'U1', 'quote': source}]}], 'table_labels': []}
    authored = record(page, answer, 2)
    wrong = deepcopy(authored); wrong['model'] = planner['name']; wrong['routing']['model'] = planner['name']
    with pytest.raises(dg.GenerationError, match='differs_from_frozen_request'):
        dg.replay_document_page(page, wrong)
    reviewer = dg.frozen_page_review_request(page, authored, PIN)
    assert reviewer[2]['model_pin'] == PIN
    reviewed = record(reviewer, {'verdict': 'pass', 'issues': [], 'financial_status': 'not_established'}, 3)
    result = dg.generation_progress(request, inventory, [planned_row, authored, reviewed], PIN,
        qualification_context_profile=lc.PROFILE)
    assert result['state'] == 'draft_complete' and result['financial_validation'] == 'not_established'
    for encoding, extra in ((dg.CATALOG_ENCODING_V1, {}), (dg.CATALOG_ENCODING_V2, {}),
                           (dg.CATALOG_ENCODING_V3, {}),
                           (dg.CATALOG_ENCODING_V4, {'qualification_context_profile': lc.PROFILE})):
        with pytest.raises(dg.GenerationError, match='separate_page_author_requires_compact'):
            dg.frozen_document_request(inventory, planner, 'pitch_deck', catalog_encoding=encoding,
                page_author_pin=PIN, **extra)
