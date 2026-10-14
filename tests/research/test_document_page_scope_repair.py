"""One recorded scope-feedback repair, preserved originals and mandatory review."""
from copy import deepcopy

import pytest

from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from agents.research import document_source_index as si
from agents.research import document_context_capacity as cc
from tests.research.test_document_generation import PIN, manifest, record


def test_one_actual_feedback_repair_reuses_verified_plan_and_blocks_second_rejection(monkeypatch):
    inventory = dg.evidence_inventory([manifest()], catalog_encoding=dg.CATALOG_ENCODING_V6)
    seed = dg.frozen_document_request(inventory, PIN, 'intro_deck', catalog_encoding=dg.CATALOG_ENCODING_V6,
        qualification_context_profile=lc.PROFILE, page_author_pin=PIN,
        planning_schema_profile=dg.SELECTED_PHYSICAL_PLAN_PROFILE_V5,
        source_context_profile=si.SOURCE_CONTEXT_PROFILE_32K)
    source = dg._source_index_requests_from_seed(seed, inventory)[0]
    attempts = [record(source, {'group_id': 'G1', 'focus_unit_ids': ['U1'], 'visual_semantics': 'unassessed',
        'scope_status': 'local_source_selection_proposal_not_diligence'}, 1)]
    common = {'qualification_context_profile': lc.PROFILE,
        'planning_assignment_profile': dg.SINGLE_SOURCE_OUTLINE_ASSIGNMENT_PROFILE,
        'material_context_profile': cc.MATERIAL_CONTEXT_PROFILE_32K}
    profile = dg.DOCUMENT_PAGE_REPAIR_PROFILE
    opted = {**common, 'document_page_repair_profile': profile}
    plan_request = dg.generation_progress(seed, inventory, attempts, PIN, **common)['request']
    assert dg.request_json(dg.generation_progress(seed, inventory, attempts, PIN, **opted)['request']) == dg.request_json(plan_request)
    attempts.append(record(plan_request, {'p': [{'t': ['customers_and_traction'], 'l': 'evidence',
        'e': ['G1'], 's': 'limited'}]}, 2))
    independent_author = dg.frozen_page_request(plan_request, attempts[1], 'P1', inventory,
        material_context_profile=cc.MATERIAL_CONTEXT_PROFILE_32K)
    calls = []
    real_replay = dg.replay_document_plan
    def counted_replay(*args, **kwargs):
        calls.append(1)
        return real_replay(*args, **kwargs)
    monkeypatch.setattr(dg, 'replay_document_plan', counted_replay)
    monkeypatch.setattr(dg, 'frozen_page_request', lambda *a, **k: (_ for _ in ()).throw(
        AssertionError('already validated plan must use its pure page builder')))
    original_author = dg.generation_progress(seed, inventory, attempts, PIN, **opted)['request']
    assert len(calls) == 1 and dg.request_json(original_author) == dg.request_json(independent_author)
    original_text = 'The source reports a limited pilot in 2024.'
    proposed = {'page_id': 'P1', 'title': 'Supplied pilot', 'claims': [
        {'text': 'The company completed a limited pilot in 2024.', 'basis': 'reported',
         'evidence': [{'unit_id': 'U1', 'quote': 'a limited pilot in 2024'}]}], 'table_labels': []}
    attempts.append(record(original_author, proposed, 3))
    revised_review = dg.generation_progress(seed, inventory, attempts, PIN, **opted)['request']
    assert revised_review[0] == 'document_page_scope_feedback_review_v1'
    assert 'not every original literal' in revised_review[1]
    failure = {'verdict': 'revise', 'financial_status': 'not_established', 'issues': [
        {'claim_index': 0, 'exact_claim_phrase': 'The company completed', 'unit_id': 'U1',
         'exact_source_quote': original_text, 'kind': 'scope'}]}
    old_review = dg.frozen_page_review_request(original_author, attempts[2], PIN)
    old_attempts = [*attempts, record(old_review, failure, 4)]
    old_state = dg.generation_progress(seed, inventory, old_attempts, PIN, **common)
    assert old_state['state'] == 'blocked' and old_state['reason'] == 'independent_document_page_review_failed'
    assert old_review[0] == 'document_page_complete_literal_context_review_v2'
    attempts.append(record(revised_review, failure, 4))
    preserved = deepcopy(attempts)
    repair_progress = dg.generation_progress(seed, inventory, attempts, PIN, **opted)
    assert repair_progress['phase'] == 'document_page_repair' and repair_progress['maximum_model_calls'] == 6
    repair = repair_progress['request']
    assert repair[2]['parent_author']['raw_response'] == attempts[2]['raw_response']
    assert repair[2]['parent_review']['raw_response'] == attempts[3]['raw_response']
    assert repair[2]['companion_source_pages'] == original_author[2]['companion_source_pages']
    assert repair[2]['model_pin'] == original_author[2]['model_pin'] == PIN
    assert repair[2]['options'] == original_author[2]['options']
    assert repair[2]['options']['context_tokens'] == 32768 and repair[2]['options']['max_tokens'] == 2200
    corrected = deepcopy(proposed); corrected['claims'][0]['text'] = original_text
    attempts.append(record(repair, corrected, 5))
    rereview_progress = dg.generation_progress(seed, inventory, attempts, PIN, **opted)
    assert rereview_progress['phase'] == 'document_page_repair_review'
    rereview = rereview_progress['request']
    assert rereview[2]['page_response_id'] == 'response_5'
    assert rereview[2]['proposed_page'] == corrected
    assert rereview[2]['financial_validation'] == rereview[2]['investor_approval'] == 'not_established'
    second_failure = deepcopy(failure); second_failure['issues'][0]['exact_claim_phrase'] = 'The source reports'
    rejected = dg.generation_progress(seed, inventory, [*attempts, record(rereview, second_failure, 6)], PIN, **opted)
    assert rejected['state'] == 'blocked' and rejected['reason'] == 'independent_document_page_repair_review_failed'
    assert 'request' not in rejected
    final_review = record(rereview, {'verdict': 'pass', 'issues': [], 'financial_status': 'not_established'}, 6)
    attempts.append(final_review)
    result = dg.generation_progress(seed, inventory, attempts, PIN, **opted)
    assert result['state'] == 'draft_complete' and result['completed_pages'] == 1
    receipt = result['page_receipts'][0]
    assert receipt['author_response_id'] == 'response_5' and receipt['review_response_id'] == 'response_6'
    assert receipt['repair_receipt']['original_author_response_id'] == 'response_3'
    assert receipt['repair_receipt']['original_review_response_id'] == 'response_4'
    assert result['financial_validation'] == result['regulatory_approval'] == result['investor_approval'] == 'not_established'
    assert result['sections'][0][1] == '[Reported] ' + original_text + ' [S1]'
    assert attempts[:4] == preserved
    forged = deepcopy(attempts); forged[3]['raw_response'] += ' '
    blocked = dg.generation_progress(seed, inventory, forged, PIN, **opted)
    assert blocked['state'] == 'blocked' and 'request' not in blocked
    with pytest.raises(dg.GenerationError, match='first_rejected_author_only'):
        dg.frozen_page_repair_request(repair, attempts[4], rereview, final_review)
    actual, row, cursor = dg.document_plan_context(seed, inventory, attempts, reviewer_pin=PIN, **opted)
    assert dg.request_json(actual) == dg.request_json(plan_request) and row == attempts[1] and cursor == 2
