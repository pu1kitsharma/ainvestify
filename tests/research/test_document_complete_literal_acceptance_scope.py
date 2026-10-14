"""Independent full-literal visibility/review boundary; fictional input only.

These recorded-call stubs exercise software contracts. They are neither model
performance evidence nor training gold or professional review records.
"""
from copy import deepcopy

import pytest

from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from tests.research.test_document_generation import PIN, author, manifest, planned, record


def _fixture():
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V4)
    request = dg.frozen_document_request(inventory, PIN, 'intro_deck',
        mandate='Synthetic internal diligence only.', catalog_encoding=dg.CATALOG_ENCODING_V4,
        qualification_context_profile=lc.PROFILE)
    return inventory, request


def test_resealed_full_literal_catalog_cannot_hide_source_or_inflate_approval():
    inventory, request = _fixture()
    catalog = request[2]['catalog']
    coverage = catalog['literal_coverage']
    assert coverage['available_literal_unit_count'] == len(inventory['units'])
    assert coverage['native_table_cell_count'] + coverage['noncell_literal_unit_count'] == len(inventory['units'])
    assert coverage['physical_page_count'] == len(inventory['source_map_topology'])
    assert catalog['reading_semantics'] == 'unassessed'
    assert catalog['source_map_status'] == catalog['source_coverage_review_status'] == 'not_performed'
    assert all(catalog[key] == 'not_established' for key in
               ('financial_validation', 'regulatory_approval', 'investor_approval'))

    for change in ('omit_literal', 'rewrite_literal', 'approval'):
        changed = deepcopy(catalog)
        if change == 'omit_literal':
            changed['pages'][0]['literal_units'].pop()
        elif change == 'rewrite_literal':
            changed['pages'][0]['literal_units'][0][2] = 'An invented replacement.'
        else:
            changed['investor_approval'] = 'approved'
        changed['catalog_digest'] = dg.canonical_digest({key: value for key, value in changed.items()
                                                       if key != 'catalog_digest'})
        with pytest.raises(dg.GenerationError, match='complete_original_literal_catalog_changed'):
            lc.validate_complete_literal_catalog(inventory, changed)


def test_direct_literal_plan_still_requires_page_review_and_cannot_grant_approval():
    inventory, request = _fixture()
    plan_row = record(request, planned(inventory), 1)
    page_request = dg.frozen_page_request(request, plan_row, 'P1', inventory)
    assert page_request[2]['mandate'] == request[2]['mandate']
    assert page_request[2]['qualification_context_profile'] == lc.PROFILE
    assert 'source_reading_proposals' not in page_request[2]
    page_row = record(page_request, author(page_request), 2)
    before_review = dg.generation_progress(request, inventory, [plan_row, page_row], PIN,
                                           qualification_context_profile=lc.PROFILE)
    assert before_review['state'] == 'needs_call'
    assert before_review['phase'] == 'document_page_review'

    review_request = dg.frozen_page_review_request(page_request, page_row, PIN)
    assert review_request[2]['mandate'] == request[2]['mandate']
    rejected = record(review_request, {'verdict': 'revise', 'issues': [{
        'claim_index': 0, 'exact_claim_phrase': 'a limited pilot', 'unit_id': 'U1',
        'exact_source_quote': 'a limited pilot', 'kind': 'scope'}],
        'financial_status': 'not_established'}, 3)
    blocked = dg.generation_progress(request, inventory, [plan_row, page_row, rejected], PIN,
                                     qualification_context_profile=lc.PROFILE)
    assert blocked['state'] == 'blocked'
    assert blocked['reason'] == 'independent_document_page_review_failed'

    passed = record(review_request, {'verdict': 'pass', 'issues': [],
                                     'financial_status': 'not_established'}, 3)
    # Untrusted incidental record metadata cannot appoint an approver.
    passed.update(regulatory_approval='approved', investor_approval='approved')
    final = dg.generation_progress(request, inventory, [plan_row, page_row, passed], PIN,
                                   qualification_context_profile=lc.PROFILE)
    assert final['state'] == 'draft_complete'
    assert final['source_mapping'] == final['source_coverage_review'] == 'not_performed'
    assert final['literal_reading_scope'] == 'complete_available_literals_unreviewed'
    assert all(final[key] == 'not_established' for key in
               ('financial_validation', 'regulatory_approval', 'investor_approval'))
    inflated = record(review_request, {'verdict': 'pass', 'issues': [],
                                      'financial_status': 'approved'}, 3)
    assert dg.generation_progress(request, inventory, [plan_row, page_row, inflated], PIN,
                                  qualification_context_profile=lc.PROFILE)['state'] == 'blocked'
