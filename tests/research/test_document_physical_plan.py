"""Finite source traversal and exact role capacity; no investor-quality labels."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from agents.inference.local_models import generation_schema
from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from agents.research import document_context_capacity as cc
from agents.research import document_qualification_context as qc
from tests.research.test_document_generation import PIN, manifest, record


def prepared():
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V6)
    request = dg.frozen_document_request(inventory, {'name': 'local-planner:4b', 'digest': 'c' * 64},
        'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V6, qualification_context_profile=lc.PROFILE,
        page_author_pin=PIN, planning_schema_profile=dg.PHYSICAL_PLAN_PROFILE_V3,
        planning_context_profile=dg.PLAN_CONTEXT_PROFILE_32K)
    return inventory, request


def choice():
    return {'p': [{'l': 'evidence', 'e': ['G1'], 'b': [], 's': 'limited'} for _ in range(3)],
            'd': [[f'P{index // 4 + 1}'] for index in range(len(dg.TOPICS))]}


def test_physical_choices_preserve_full_original_context_and_actual_raw_provenance():
    inventory, request = prepared()
    raw = record(request, choice(), 1); frozen = deepcopy(raw)
    plan = dg.replay_document_plan(request, raw, inventory)
    assert request[0] == 'document_plan_finite_physical_v3'
    assert plan['unsupported_topics'] == []
    assert [page['page_id'] for page in plan['pages']] == ['P1', 'P2', 'P3']
    assert all(page['narrative_unit_ids'] == [] and page['source_page_ids'] == ['G1'] for page in plan['pages'])
    assert plan['pages'][0]['topics'] == list(dg.TOPICS[:4])
    page = dg.frozen_page_request(request, raw, 'P1', inventory)
    assert page[2]['page_context_capacity_profile'] == cc.PROFILE
    assert page[2]['model_pin'] == PIN and page[2]['options']['context_tokens'] == 16384
    units = qc._context_units(page)
    assert all(units[unit['model_unit_id']]['content'] == unit['content'] for unit in inventory['units'])
    assert set(units) == {unit['model_unit_id'] for unit in inventory['units']}
    text = units['U1']['content']
    authored = record(page, {'page_id': 'P1', 'title': 'Supplied evidence', 'claims': [
        {'text': text, 'basis': 'reported', 'evidence': [{'unit_id': 'U1', 'quote': text}]}], 'table_labels': []}, 2)
    review = dg.frozen_page_review_request(page, authored, PIN)
    assert review[2]['companion_source_pages'] == page[2]['companion_source_pages']
    assert review[2]['maximum_page_answer_characters'] == page[2]['maximum_page_answer_characters']
    assert cc.validate_signed_request_capacity(review)['signed_payload_characters'] <= 32000
    assert raw == frozen and 'answer' not in plan
    assert page[2]['investor_approval'] == review[2]['financial_validation'] == 'not_established'


def test_physical_schema_finitely_bounds_all_source_and_native_table_coordinates():
    inventory, request = prepared()
    grammar = generation_schema(request[3], bound_strings=True)
    props = grammar['$defs']['PhysicalPlanPage_intro_deck']['properties']
    assert set(props) == {'l', 'e', 'b', 's'} and props['e']['items']['const'] == 'G1'
    assert grammar['properties']['d']['minItems'] == grammar['properties']['d']['maxItems'] == 12
    table = grammar['$defs']['PhysicalPlanTable_intro_deck_1']['properties']
    assert table['id']['const'] == inventory['tables'][0]['id']
    assert table['c']['items']['enum'] == [0, 1] and table['r']['items']['enum'] == [0, 1, 2]
    answer = choice(); answer['p'][0]['e'] = ['U0']
    with pytest.raises(ValidationError): request[3].model_validate(answer)
    answer = choice(); answer['p'][0].update(l='table', b=[{'id': inventory['tables'][0]['id'], 'c': [0, 99], 'r': [1], 'h': 0}])
    with pytest.raises(ValidationError): request[3].model_validate(answer)
    answer['p'][0]['b'][0]['c'] = [0, 1]; answer['p'][0]['b'][0]['r'] = [0]
    with pytest.raises(dg.GenerationError, match='table_indexes_invalid'):
        dg.replay_document_plan(request, record(request, answer, 1), inventory)
    answer = choice(); answer['u'] = list(dg.TOPICS)
    with pytest.raises(ValidationError): request[3].model_validate(answer)


def test_disposition_matrix_and_rehashed_capacity_navigation_cannot_escape_binding():
    inventory, request = prepared()
    answer = choice(); answer['d'][0] = ['P8']
    with pytest.raises(dg.GenerationError, match='nonexistent_topic_page'):
        dg.replay_document_plan(request, record(request, answer, 1), inventory)
    answer = choice(); answer['d'][0] *= 2
    with pytest.raises(dg.GenerationError, match='duplicate_or_nonexistent'):
        dg.replay_document_plan(request, record(request, answer, 1), inventory)
    changed = {key: deepcopy(value) for key, value in request[2].items() if key not in
        {'request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'}}
    navigation = changed['physical_group_catalog']
    navigation['groups'][0][5] = 1
    navigation['navigation_digest'] = dg.canonical_digest({k: v for k, v in navigation.items() if k != 'navigation_digest'})
    forged = dg._request(request[0], request[1], changed, request[3])
    with pytest.raises(dg.GenerationError, match='navigation_or_capacity_changed'):
        dg.replay_document_plan(forged, record(forged, choice(), 1), inventory)


def test_real_author_answer_size_is_checked_before_review_even_if_schema_valid():
    inventory, request = prepared()
    raw = record(request, choice(), 1)
    page = dg.frozen_page_request(request, raw, 'P1', inventory)
    # A changed cap is a synthetic stress contract; no future model row is invented.
    payload = {key: deepcopy(value) for key, value in page[2].items() if key not in
        {'request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'}}
    payload['maximum_page_answer_characters'] = 800
    limited = dg._request(page[0], page[1], payload, page[3])
    text = qc._context_units(limited)['U1']['content']
    answer = {'page_id': 'P1', 'title': 'Supplied evidence', 'claims': [
        {'text': text, 'basis': 'reported', 'evidence': [{'unit_id': 'U1', 'quote': text} for _ in range(4)]}
        for _ in range(3)], 'table_labels': []}
    with pytest.raises(dg.GenerationError, match='answer_exceeds_frozen_review_capacity'):
        dg.frozen_page_review_request(limited, record(limited, answer, 2), PIN)
