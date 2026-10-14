"""Decoder choices enforce original-ID syntax, never semantic acceptance."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from agents.inference.local_models import generation_schema
from agents.research import document_generation as dg
from tests.research.test_document_generation import PIN, manifest, record
from tests.research.test_document_source_unit_selector import selected
from tests.research.test_document_source_maps import source_with_blank_page_and_chart


def fixture():
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V3)
    request = dg.frozen_source_map_requests(inventory, PIN,
        source_map_profiles=[dg.SOURCE_MAP_BOUND_UNIT_PROFILE], source_map_token_budgets=[1600])[0]
    return inventory, request


def test_decoder_enum_rejects_blank_foreign_unit_foreign_table_and_wrong_destination():
    inventory, request = fixture()
    blank = next(u['model_unit_id'] for u in inventory['units'] if not u['content'].strip())
    # Blank source values remain in the read view, not removed from originals.
    assert blank in dg.source_map_literal_lookup(request[2]['source_page'])
    for ids, tables, destination in (([blank], [], 'M1'), (['U9999'], [], 'M1'),
                                    (['U1'], ['foreign-table'], 'M1'), (['U1'], [], 'M2')):
        answer = selected(request, ids=ids, tables=tables)
        answer['map_id'] = destination
        with pytest.raises(ValidationError):
            request[3].model_validate(answer)
    grammar = generation_schema(request[3], bound_strings=True)
    definition = grammar['$defs']['SourceBoundTopicUnitSelectionV3']
    allowed = definition['properties']['unit_ids']['items']['enum']
    assert blank not in allowed and 'U1' in allowed
    assert len(allowed) == sum(bool(u['content'].strip()) for u in inventory['units'])
    # One reusable definition, not twelve copies of the finite unit-ID set.
    branches = {'anyOf': [{'$ref': '#/$defs/SourceBoundTopicUnitSelectionV3'},
                          {'$ref': '#/$defs/SourceUnselectedTopicUnitSelectionV3'}], 'title': 'Identity'}
    assert all(grammar['properties'][topic]['anyOf'] == branches['anyOf'] for topic in dg.TOPICS)
    assert definition['properties']['unit_ids']['minItems'] == 1
    bad = selected(request)
    bad['financials']['status'] = 'selected'
    with pytest.raises(ValidationError):
        request[3].model_validate(bad)
    bad = selected(request, ids=['U1'])
    bad['financials']['status'] = 'unassessed'
    with pytest.raises(ValidationError):
        request[3].model_validate(bad)


def test_valid_choice_projects_original_values_and_keeps_approval_unestablished():
    inventory, request = fixture()
    answer = selected(request, topic='product', ids=['U1'])
    row = record(request, answer, 1)
    assert dg.replay_source_map(request, row) == answer
    plan = dg.frozen_document_request(inventory, PIN, 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V3,
        source_maps=[row], source_map_profiles=[dg.SOURCE_MAP_BOUND_UNIT_PROFILE], source_map_token_budgets=[1600])
    pool = plan[2]['catalog']['literal_unit_pool']
    assert len(pool) == 1 and pool[0]['content'] == inventory['units'][0]['content']
    assert plan[2]['catalog']['source_map_status'] == 'proposed_unreviewed'
    assert plan[2]['catalog']['financial_validation'] == 'not_established'


def test_empty_page_permits_no_ids_and_full_literal_scope_is_preserved():
    inventory = dg.evidence_inventory([source_with_blank_page_and_chart()], catalog_encoding=dg.CATALOG_ENCODING_V3)
    requests = dg.frozen_source_map_requests(inventory, PIN,
        source_map_profiles=[dg.SOURCE_MAP_BOUND_UNIT_PROFILE] * 2)
    empty = requests[0]
    assert not empty[2]['source_page']['literal_units']
    answer = selected(empty)
    assert dg.replay_source_map(empty, record(empty, answer, 1)) == answer
    answer['identity'].update(status='selected', unit_ids=['U1'])
    with pytest.raises(ValidationError):
        empty[3].model_validate(answer)
    answer['identity']['unit_ids'] = []
    with pytest.raises(ValidationError):
        empty[3].model_validate(answer)  # A zero-choice page cannot claim a selected topic.


def test_new_profile_does_not_change_existing_requests_or_decode_receipt_schema():
    inventory, new = fixture()
    for profile in (dg.SOURCE_MAP_QUOTED_PROFILE, dg.SOURCE_MAP_UNIT_PROFILE):
        before = dg.frozen_source_map_requests(inventory, PIN, source_map_profiles=[profile])[0]
        after = dg.frozen_source_map_requests(inventory, PIN, source_map_profiles=[profile])[0]
        assert dg.request_json(before) == dg.request_json(after)
        assert before[3] is (dg.SourcePageMap if profile == dg.SOURCE_MAP_QUOTED_PROFILE else dg.SourcePageUnitMap)
    repeated = dg.frozen_source_map_requests(inventory, PIN,
        source_map_profiles=[dg.SOURCE_MAP_BOUND_UNIT_PROFILE], source_map_token_budgets=[1600])[0]
    assert dg.request_json(new) == dg.request_json(repeated)
    altered = deepcopy(record(new, selected(new, ids=['U1']), 1))
    altered['schema'] = dg.SourcePageUnitMap.model_json_schema()
    with pytest.raises(dg.GenerationError, match='differs_from_frozen'):
        dg.replay_source_map(new, altered)
