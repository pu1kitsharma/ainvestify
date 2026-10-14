"""Independent raw-role and approval boundaries; synthetic evidence only."""
from copy import deepcopy

import pytest

from agents.research import document_generation as generation
from agents.research import document_qualification_context as context
from tests.research.test_document_source_map_acceptance_scope import (
    PIN, _one_synthetic_source, _record,
)


REVIEWER_PIN = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}


def _record_with_id(request, answer, response_id):
    row = _record(request, answer)
    row['id'] = response_id
    return row


def _reading_pair():
    inventory = _one_synthetic_source()
    profile = {'source_map_profiles': [generation.SOURCE_MAP_BOUND_UNIT_PROFILE],
               'source_map_token_budgets': [1600]}
    request = generation.frozen_source_map_requests(inventory, PIN, **profile)[0]
    answer = {'map_id': request[2]['map_id'],
        **{topic: {'status': 'unassessed', 'coverage': 'limited',
            'basis': 'unverified_observation', 'unit_ids': [], 'table_ids': []}
            for topic in generation.TOPICS},
        'scope_status': 'source_reading_proposal_not_diligence'}
    mapper = _record_with_id(request, answer, 'response_1')
    review_request = context.frozen_source_map_coverage_request(request, mapper, REVIEWER_PIN)
    original_id = next(unit[0] for unit in request[2]['source_page']['literal_units'] if unit[2].strip())
    review = {'verdict': 'corrected',
        'topic_patches': [{'topic': 'customers_and_traction', 'selection': {
            'status': 'selected', 'coverage': 'limited', 'basis': 'reported',
            'unit_ids': [original_id], 'table_ids': []}}],
        'review_scope': 'local_model_source_reading_only',
        'financial_validation': 'not_established', 'regulatory_approval': 'not_established',
        'investor_approval': 'not_established'}
    critic = _record_with_id(review_request, review, 'response_2')
    return inventory, profile, request, mapper, review_request, critic


def test_critic_changes_require_both_raw_roles_and_cannot_grant_professional_approval():
    inventory, profile, request, mapper, review_request, critic = _reading_pair()
    original_mapper = deepcopy(mapper)
    original_critic = deepcopy(critic)
    effective = context.effective_source_map(request, mapper, review_request, critic)
    assert 'id' not in effective and 'raw_response' not in effective and 'response_hash' not in effective
    assert mapper == original_mapper and critic == original_critic
    plan = generation.frozen_document_request(inventory, PIN, 'intro_deck',
        catalog_encoding=generation.CATALOG_ENCODING_V3, source_maps=[mapper],
        qualification_context_profile=context.PROFILE, source_map_reviews=[critic],
        reviewer_pin=REVIEWER_PIN, **profile)
    catalog = plan[2]['catalog']
    assert catalog['source_map_status'] == 'proposed_unreviewed'
    assert catalog['source_coverage_review_status'] == 'local_model_only_unqualified'
    assert catalog['financial_validation'] == catalog['investor_approval'] == 'not_established'
    assert catalog['literal_unit_pool'][0]['content'] == inventory['units'][0]['content']
    expected_provenance = [{'map_id': request[2]['map_id'],
        'source_page_id': request[2]['source_page_id'], 'response_id': mapper['id'],
        'response_hash': mapper['response_hash'],
        'request_digest': generation.canonical_digest(generation.request_json(request)),
        'coverage_response_id': critic['id'], 'coverage_response_hash': critic['response_hash'],
        'coverage_request_digest': generation.canonical_digest(generation.request_json(review_request)),
        'effective_projection_digest': generation.canonical_digest(effective)}]
    assert catalog['source_map_provenance_digest'] == generation.canonical_digest(expected_provenance)
    with pytest.raises(generation.GenerationError, match='distinct_local_source_coverage'):
        generation.frozen_document_request(inventory, PIN, 'intro_deck',
            catalog_encoding=generation.CATALOG_ENCODING_V3, source_maps=[mapper],
            qualification_context_profile=context.PROFILE, source_map_reviews=[mapper],
            reviewer_pin=REVIEWER_PIN, **profile)


def test_foreign_critic_ids_approved_scope_and_wrong_trusted_reviewer_pin_are_rejected():
    inventory, profile, request, mapper, review_request, critic = _reading_pair()
    foreign = deepcopy(critic['answer'])
    foreign['topic_patches'][0]['selection']['unit_ids'] = ['U999999']
    with pytest.raises(ValueError):
        context.effective_source_map(request, mapper, review_request,
            _record_with_id(review_request, foreign, 'response_2'))
    inflated = deepcopy(critic['answer'])
    inflated['investor_approval'] = 'approved'
    with pytest.raises(ValueError):
        context.effective_source_map(request, mapper, review_request,
            _record_with_id(review_request, inflated, 'response_2'))
    with pytest.raises(generation.GenerationError, match='differs_from_frozen'):
        generation.frozen_document_request(inventory, PIN, 'intro_deck',
            catalog_encoding=generation.CATALOG_ENCODING_V3, source_maps=[mapper],
            qualification_context_profile=context.PROFILE, source_map_reviews=[critic],
            reviewer_pin=PIN, **profile)
