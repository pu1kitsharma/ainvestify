"""Unit selectors bind model choices to original data; they do not approve facts."""
from copy import deepcopy
import json

import pytest

from agents.research import document_generation as dg
from tests.research.test_document_generation import PIN, manifest, record
from tests.research.test_document_source_maps import source_with_blank_page_and_chart, mapped


def selected(request, *, topic='financials', ids=(), tables=()):
    answer = {'map_id': request[2]['map_id'], 'scope_status': 'source_reading_proposal_not_diligence'}
    for name in dg.TOPICS:
        answer[name] = {'status': 'unassessed', 'coverage': 'limited', 'basis': 'unverified_observation',
                        'unit_ids': [], 'table_ids': []}
    if ids:
        answer[topic].update(status='selected', unit_ids=list(ids), table_ids=list(tables))
    return answer


def test_selector_copies_full_original_cells_once_without_synthesized_joined_quotes():
    source = manifest()
    # A long literal tests full-original retrieval, not a shortened quote copy.
    source['units'][0]['content'] = source['units'][0]['text'] = 'A complete original observation. ' * 20
    source['units'][0]['content_sha256'] = dg.canonical_digest(source['units'][0]['content'])
    source['manifest_digest'] = dg.canonical_digest({k: v for k, v in source.items() if k != 'manifest_digest'})
    inventory = dg.evidence_inventory([source], catalog_encoding=dg.CATALOG_ENCODING_V3)
    profiles = [dg.SOURCE_MAP_UNIT_PROFILE]
    request = dg.frozen_source_map_requests(inventory, PIN, source_map_profiles=profiles,
        source_map_token_budgets=[1600])[0]
    units = {unit['content']: unit['model_unit_id'] for unit in inventory['units']}
    chosen = ['U1', units['Revenue'], units['120']]
    answer = selected(request, ids=chosen, tables=[inventory['tables'][0]['id']])
    # Cross-topic references to a selected original are legal; the pool remains deduplicated.
    answer['risks_and_countercase'].update(status='selected', unit_ids=['U1'])
    row = record(request, answer, 1)
    assert 'quote' not in json.dumps(request[3].model_json_schema())
    assert set(dg.TOPICS) <= set(request[3].model_json_schema()['properties'])
    assert dg.replay_source_map(request, row) == answer
    plan = dg.frozen_document_request(inventory, PIN, 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V3,
        source_maps=[row], source_map_profiles=profiles, source_map_token_budgets=[1600])
    catalog = plan[2]['catalog']
    pool = {unit['unit_id']: unit for unit in catalog['literal_unit_pool']}
    assert len(pool) == len(chosen)
    assert pool['U1']['content'] == source['units'][0]['content'] and len(pool['U1']['content']) > 160
    assert pool[units['Revenue']]['content'] == 'Revenue' and pool[units['120']]['content'] == '120'
    assert not any(unit['content'] == 'Revenue 120' for unit in pool.values())
    assert catalog['source_map_status'] == 'proposed_unreviewed'
    assert catalog['financial_validation'] == catalog['investor_approval'] == 'not_established'
    assert catalog['literal_unit_pool_digest'] == dg.canonical_digest(catalog['literal_unit_pool'])
    assert plan[1] == dg.UNIT_POOL_PLAN_INSTRUCTION
    assert dg.source_map_catalog_selections(catalog, catalog['pages'][0])[0]['evidence'][0]['quote'] == source['units'][0]['content']


def test_selector_rejects_foreign_duplicate_blank_and_nonselected_ids_or_foreign_table():
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V3)
    request = dg.frozen_source_map_requests(inventory, PIN, source_map_profiles=[dg.SOURCE_MAP_UNIT_PROFILE])[0]
    blank = next(unit['model_unit_id'] for unit in inventory['units'] if unit['content'] == '')
    for ids, tables, status in ((['U9999'], [], 'selected'), (['U1', 'U1'], [], 'selected'),
        ([blank], [], 'selected'), (['U1'], [], 'unassessed'), (['U1'], ['foreign-table'], 'selected'),
        (['U1'], [inventory['tables'][0]['id']], 'selected')):
        answer = selected(request, ids=ids, tables=tables)
        answer['financials']['status'] = status
        with pytest.raises(dg.GenerationError):
            dg.replay_source_map(request, record(request, answer, 1))
    answer = selected(request, ids=['U1'])
    row = record(request, answer, 1)
    raw = row['raw_response']
    raw = raw[:-1] + ',"financials":' + json.dumps(answer['financials']) + '}'
    row.update(raw_response=raw, response_hash=dg.digest(raw))
    with pytest.raises(ValueError):
        dg.replay_source_map(request, row)  # Duplicate fixed-topic keys cannot pass exact JSON replay.


def test_mixed_profile_preserves_completed_quoted_prefix_and_actual_plan_replay_offset():
    inventory = dg.evidence_inventory([source_with_blank_page_and_chart(), manifest()], catalog_encoding=dg.CATALOG_ENCODING_V3)
    original = dg.frozen_source_map_requests(inventory, PIN)
    profiles, budgets = ['quoted-v1', 'quoted-v1', 'unit-ids-v2'], [900, 900, 1600]
    current = dg.frozen_source_map_requests(inventory, PIN, source_map_profiles=profiles, source_map_token_budgets=budgets)
    assert [dg.request_json(r) for r in current[:2]] == [dg.request_json(r) for r in original[:2]]
    assert [dg.request_json(r) for r in original] == [dg.request_json(r) for r in dg.frozen_source_map_requests(
        inventory, PIN, source_map_profiles=['quoted-v1'] * 3)]
    assert all('source_map_profiles' not in request[2] for request in current)
    prefix = [record(original[i], mapped(original[i]), i + 1) for i in range(2)]
    own = next(row[0] for row in current[2][2]['source_page']['literal_units'] if row[2].strip())
    selector = record(current[2], selected(current[2], topic='customers_and_traction', ids=[own]), 3)
    rows = [*prefix, selector]
    progress = dg.generation_progress(current[0], inventory, rows, PIN, source_map_profiles=profiles,
        source_map_token_budgets=budgets)
    assert progress['phase'] == 'document_plan'
    plan_request = progress['request']
    choice = {'pages': [{'page_id': 'P1', 'topic': 'customers_and_traction', 'layout': 'evidence',
        'narrative_unit_ids': [own], 'table_selections': [], 'coverage': 'limited'}],
        'unsupported_topics': [topic for topic in dg.TOPICS if topic != 'customers_and_traction']}
    planned = record(plan_request, choice, 4)
    context = dg.document_plan_context(current[0], inventory, [*rows, planned], source_map_profiles=profiles,
        source_map_token_budgets=budgets)
    assert dg.request_json(context[0]) == dg.request_json(plan_request) and context[1] == planned and context[2] == 4
    assert dg.generation_progress(current[0], inventory, rows, PIN)['state'] == 'blocked'
    for bad in (['unit-ids-v2'], ['quoted-v1', 'quoted-v1', 'unknown'], ['quoted-v1', 'quoted-v1', {}]):
        with pytest.raises(dg.GenerationError, match='profile_vector_required'):
            dg.frozen_source_map_requests(inventory, PIN, source_map_profiles=bad)


def test_selector_ocr_cannot_become_financially_qualified_by_confidence_or_topic_choice():
    source = manifest()
    unit = deepcopy(source['units'][0])
    unit.update(id='proposed-ocr-unit', kind='ocr_text', origin='local_ocr_proposed', confidence=1.0)
    source['units'].append(unit)
    source['manifest_digest'] = dg.canonical_digest({k: v for k, v in source.items() if k != 'manifest_digest'})
    inventory = dg.evidence_inventory([source], catalog_encoding=dg.CATALOG_ENCODING_V3)
    proposed = next(u['model_unit_id'] for u in inventory['units'] if u['id'] == unit['id'])
    request = dg.frozen_source_map_requests(inventory, PIN, source_map_profiles=['unit-ids-v2'])[0]
    answer = selected(request, ids=[proposed])
    answer['financials'].update(coverage='supported', basis='reported')
    with pytest.raises(dg.GenerationError, match='ocr_must_remain_unverified_proposal'):
        dg.replay_source_map(request, record(request, answer, 1))
    answer['financials'].update(coverage='limited', basis='unverified_observation')
    row = record(request, answer, 1)
    catalog = dg._mapped_catalog(inventory, PIN, [row], kind='intro_deck', mandate='', source_map_profiles=['unit-ids-v2'])
    assert catalog['literal_unit_pool'][0]['origin'] == 'local_ocr_proposed'
    assert catalog['financial_validation'] == catalog['investor_approval'] == 'not_established'
