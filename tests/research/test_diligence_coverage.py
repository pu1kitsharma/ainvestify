"""Source traversal, exact replay and scope-selection safety. Synthetic only."""
import copy
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research import diligence_coverage as module


PIN = {'name': 'qwen3:14b', 'digest': 'a' * 64}


def sources(count=8):
    return [{'id': f'S{i}', 'url': f'private://synthetic-{i}/page/1',
             'title': 'Synthetic source', 'version': f'version-{i:03d}',
             'attribution': 'Synthetic company report, unverified',
             'passage': f'The company reports a product offering through its partner channel. '
                        f'It provides customer support for the service. Synthetic source {i}.'}
            for i in range(1, count + 1)]


def recorded_row(request, answer, index):
    task, instruction, payload, schema = request
    parsed = schema.model_validate(answer).model_dump(mode='json')
    raw = json.dumps(parsed)
    routing = {'model': payload['model_pin']['name'], **payload['options'], 'prompt_tokens': 1200}
    if payload['options'].get('factual_sampling'):
        routing['sampling'] = {'presence_penalty': 0, 'repeat_penalty': 1}
    return {'id': f'response_{index}', 'task': task, 'instruction': instruction,
            'input': payload, 'schema': schema.model_json_schema(), 'answer': parsed,
            'raw_response': raw, 'response_hash': digest(raw),
            'model': payload['model_pin']['name'], 'routing': routing}


def complete_records(rows, *, structures=None, financial_scope=None):
    attempts = []
    while True:
        request = module.pending_coverage_request(rows, PIN, attempts, structures=structures,
                                                  financial_scope=financial_scope)
        if request is None:
            return attempts
        task, _, payload, _ = request
        if task == module.CLASSIFY_TASK:
            answer = {sid: {'disposition': 'relevant',
                           'categories': ['product_and_customers'],
                           'supporting_evidence_ids': [next(iter(row['evidence_spans']))],
                           'reason': 'Discusses the reported product and distribution.'}
                      for sid, row in payload['sources'].items()}
        else:
            ids = payload['eligible_narrative_source_ids']
            answer = {field: [ids[index % len(ids)]]
                      for index, field in enumerate(module.FIELDS)}
        attempts.append(recorded_row(request, answer, len(attempts) + 1))


def test_complete_inventory_is_assessed_then_model_selects_each_field():
    rows = sources(22)
    attempts = complete_records(rows)
    result = module.evaluate_coverage(rows, PIN, attempts)
    assert len(attempts) == module.MAX_CALLS
    assert result['state'] == 'accepted'
    assert result['coverage_complete'] is True
    assert result['unassessed_sources'] == []
    assert result['category_source_ids']['product_and_customers'] == [r['id'] for r in rows]
    assert result['field_source_ids'] == attempts[-1]['answer']
    assert 'identity' in result['missing_categories']
    assert result['investment_approval'] == 'not_established'
    assert 'independent_diligence_review_required' in result['positive_suggestion_blockers']
    assert 'mandatory_diligence_categories_missing' in result['positive_suggestion_blockers']


def test_partial_traversal_has_precise_unassessed_sources_and_no_selected_field_map():
    rows = sources(8)
    attempts = complete_records(rows)
    result = module.evaluate_coverage(rows, PIN, attempts[:1])
    assert result['state'] == 'needs_call'
    assert result['unassessed_sources'] == ['S6', 'S7', 'S8']
    assert 'field_source_ids' not in result
    result = module.evaluate_coverage(rows, PIN, attempts[:-1])
    assert result['state'] == 'needs_call'
    assert result['reason'] == 'model_field_scope_selection_required'
    assert result['unassessed_sources'] == []
    assert result['coverage_complete'] is False


@pytest.mark.parametrize('tamper', ['raw', 'source', 'pin', 'instruction', 'schema', 'routing', 'id', 'selection_binding'])
def test_tampered_lineage_cannot_replay(tamper):
    rows = sources(8)
    attempts = complete_records(rows)
    altered = copy.deepcopy(attempts)
    if tamper == 'raw':
        altered[0]['raw_response'] += ' '
    elif tamper == 'source':
        rows[0]['passage'] += ' Added fact.'
    elif tamper == 'pin':
        altered[0]['input']['model_pin']['digest'] = 'b' * 64
    elif tamper == 'instruction':
        altered[0]['instruction'] += ' Skip a source.'
    elif tamper == 'schema':
        altered[0]['schema']['title'] = 'Changed'
    elif tamper == 'routing':
        altered[0]['routing']['temperature'] = 0.8
    elif tamper == 'id':
        altered[-1]['id'] = altered[0]['id']
    else:
        altered[-1]['input']['selection_binding'] = 'sha256:' + 'b' * 64
    assert module.evaluate_coverage(rows, PIN, altered)['state'] == 'blocked'


def test_numeric_source_is_assessed_but_not_offered_as_qualitative_core_scope():
    rows = sources(2)
    rows[1]['passage'] = 'Revenue\nFY2025 FY2026\nUSD million\n100 200\nMargin 10 20'
    attempts = complete_records(rows)
    result = module.evaluate_coverage(rows, PIN, attempts)
    assert 'S2' in result['category_source_ids']['product_and_customers']
    assert attempts[-1]['input']['eligible_narrative_source_ids'] == ['S1']
    assert all(ids == ['S1'] for ids in result['field_source_ids'].values())


def test_structure_warnings_are_frozen_separately_and_never_claim_financial_approval():
    rows = sources(2)
    structure = {'S1': {'visual_content_status': 'unassessed', 'embedded_images': 2}}
    attempts = complete_records(rows, structures=structure)
    assert module.evaluate_coverage(rows, PIN, attempts, structures=structure)['state'] == 'accepted'
    altered = {'S1': {'visual_content_status': 'reviewed', 'embedded_images': 2}}
    assert module.evaluate_coverage(rows, PIN, attempts, structures=altered)['state'] == 'blocked'
    assert module.evaluate_coverage(rows, PIN, attempts, structures=structure)['financial_validation'] == 'not_established'


def test_oversized_inventory_or_context_blocks_without_dropping_rows():
    with pytest.raises(ValueError, match='twenty-five'):
        module.frozen_coverage_requests(sources(26), PIN)
    rows = sources(8)
    for row in rows:
        row['passage'] = 'The company reports this offering. ' * 110
    with pytest.raises(ValueError, match='twenty-four thousand'):
        module.frozen_coverage_requests(rows, PIN)


def test_selected_duplicate_or_foreign_ids_cannot_replay():
    rows = sources(3)
    attempts = complete_records(rows)
    request = module.pending_coverage_request(rows, PIN, attempts[:-1])
    answer = copy.deepcopy(attempts[-1]['answer'])
    answer['investment_thesis'] = ['S1', 'S1']
    attempts[-1] = recorded_row(request, answer, len(attempts))
    assert module.evaluate_coverage(rows, PIN, attempts)['state'] == 'blocked'
    answer['investment_thesis'] = ['S99']
    with pytest.raises(ValueError):
        recorded_row(request, answer, len(attempts))


def test_failed_call_blocks_instead_of_restarting_traversal():
    rows = sources(2)
    attempts = complete_records(rows)
    attempts[0]['error'] = 'bounded inference timeout'
    result = module.evaluate_coverage(rows, PIN, attempts)
    assert result['state'] == 'blocked'
    assert result['coverage_complete'] is False


def test_out_of_order_or_extra_calls_cannot_replay_as_complete_traversal():
    rows = sources(8)
    attempts = complete_records(rows)
    assert module.evaluate_coverage(rows, PIN, [attempts[1], attempts[0], attempts[2]])['state'] == 'blocked'
    extra = copy.deepcopy(attempts[-1])
    extra['id'] = 'response_extra'
    assert module.evaluate_coverage(rows, PIN, attempts + [extra])['state'] == 'blocked'


def test_actual_orchestration_verifies_claude_traversal_plan_and_deduplicates_ids_only(monkeypatch):
    rows = sources(2)
    attempts = complete_records(rows)
    seen = []
    original = module.verify_traversal

    def verify(plan, batches, selection):
        seen.append((plan, batches, selection))
        return original(plan, batches, selection)

    monkeypatch.setattr(module, 'verify_traversal', verify)
    result = module.evaluate_coverage(rows, PIN, attempts)
    assert result['state'] == 'accepted'
    assert seen
    plan, batches, selection = seen[-1]
    assert batches[0]['batch_key'] == attempts[0]['input']['batch_key']
    assert [unit['source_id'] for unit in batches[0]['results']] == ['S1', 'S2']
    assert selection['selected_ids'] == ['S1', 'S2']
    assert result['field_source_ids'] == attempts[-1]['answer']
    assert result['traversal_plan_digest'] == plan.plan_digest


def test_fixed_plan_fails_closed_instead_of_silently_rebatching_dense_sources():
    rows = sources(6)
    for row in rows:
        row['passage'] = 'The company reports an offering. ' * 110
    with pytest.raises(ValueError, match='fixed diligence batch'):
        module.frozen_coverage_requests(rows, PIN)


def test_workbook_inventory_existence_is_frozen_without_financial_promotion():
    rows = sources(2)
    scope = {**module.FINANCIAL_SCOPE, 'supplied_workbook_inventory_digest': 'b' * 64}
    attempts = complete_records(rows, financial_scope=scope)
    result = module.evaluate_coverage(rows, PIN, attempts, financial_scope=scope)
    assert result['state'] == 'accepted'
    assert result['financial_evidence_scope'] == scope
    assert all(row['input']['financial_evidence_scope'] == scope for row in attempts)
    assert module.evaluate_coverage(rows, PIN, attempts)['state'] == 'blocked'
    changed = {**scope, 'supplied_workbook_inventory_digest': 'c' * 64}
    assert module.evaluate_coverage(rows, PIN, attempts, financial_scope=changed)['state'] == 'blocked'
    for key, value in [('semantic_coverage', 'reviewed'),
                       ('financial_validation', 'passed'),
                       ('workbook_recalculation', 'performed')]:
        with pytest.raises(ValueError, match='unqualified workbook'):
            module.frozen_coverage_requests(rows, PIN, financial_scope={**scope, key: value})


def test_selector_preserves_full_text_without_repeating_source_transport_metadata():
    rows = sources(3)
    attempts = complete_records(rows)
    compact = attempts[-1]['input']['sources']
    assert all(set(row) == {'id', 'passage', 'attribution'} for row in compact)
    assert [row['passage'] for row in compact] == [row['passage'] for row in rows]
    assert attempts[-1]['input']['source_set_digest'] == digest(rows)
    assert all('exact_text' not in span for spans in attempts[-1]['input']['narrative_evidence_spans'].values()
               for span in spans.values())
    for sid, spans in attempts[-1]['input']['narrative_evidence_spans'].items():
        original = next(row for row in rows if row['id'] == sid)['passage']
        assert all(original[span['start']:span['end']] for span in spans.values())


def test_selection_context_guard_blocks_before_inference_and_never_truncates(monkeypatch):
    rows = sources(3)
    attempts = complete_records(rows)
    monkeypatch.setattr(module, 'MAX_SELECTION_WIRE_CHARACTERS', 100)
    with pytest.raises(ValueError, match='bounded serialized context'):
        module.pending_coverage_request(rows, PIN, attempts[:-1])
    assert attempts[-1]['input']['sources'][0]['passage'] == rows[0]['passage']


def test_preflight_context_failure_preserves_verified_classification_progress_only(monkeypatch):
    rows = sources(3)
    attempts = complete_records(rows)[:-1]
    monkeypatch.setattr(module, 'MAX_SELECTION_WIRE_CHARACTERS', 100)
    result = module.evaluate_coverage(rows, PIN, attempts)
    assert result['state'] == 'blocked'
    assert result['reason'] == 'diligence_field_scope_context_blocked'
    assert result['field_scope_selection'] == 'blocked_before_inference'
    assert result['assessed_source_ids'] == ['S1', 'S2', 'S3']
    assert result['unassessed_sources'] == []
    assert result['coverage_complete'] is False
    assert len(result['judgments']) == 3
    altered = copy.deepcopy(attempts)
    altered[0]['raw_response'] += ' '
    invalid = module.evaluate_coverage(rows, PIN, altered)
    assert invalid['state'] == 'blocked'
    assert invalid['assessed_source_ids'] == []
    assert invalid['unassessed_sources'] == ['S1', 'S2', 'S3']


def complete_v2_records(rows):
    attempts = []
    categories = {
        'S1': ['product_and_customers', 'market_and_competition'],
        'S2': ['risks', 'market_and_competition'],
        'S3': ['team_and_governance'],
        'S4': ['financial_evidence', 'funding_and_ownership'],
        'S5': ['legal_and_compliance', 'material_unknowns']}
    for request in module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V2):
        answer = {sid: {'disposition': 'relevant', 'categories': categories[sid],
                       'supporting_evidence_ids': [next(iter(row['evidence_spans']))],
                       'reason': 'Describes this synthetic diligence topic.'}
                  for sid, row in request[2]['sources'].items()}
        attempts.append(recorded_row(request, answer, len(attempts) + 1))
    request = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V2)
    answer = {'investment_thesis': ['S1'], 'business_and_market': ['S1', 'S2'],
              'differentiation_and_execution': ['S3'], 'risks_and_countercase': ['S2'],
              'diligence_plan': ['S4', 'S5']}
    attempts.append(recorded_row(request, answer, len(attempts) + 1))
    return attempts


def test_v2_reuses_exact_classification_requests_but_scopes_fresh_selection():
    rows = sources(5)
    old = module.frozen_coverage_requests(rows, PIN)
    fresh = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V2)
    assert [request[:3] for request in old] == [request[:3] for request in fresh]
    assert [request[3].model_json_schema() for request in old] == [request[3].model_json_schema() for request in fresh]
    attempts = complete_v2_records(rows)
    result = module.evaluate_coverage(rows, PIN, attempts, contract=module.CONTRACT_V2)
    assert result['state'] == 'accepted'
    assert result['contract'] == module.CONTRACT_V2
    assert attempts[0]['input']['contract'] == module.CONTRACT
    assert attempts[-1]['input']['contract'] == module.CONTRACT_V2
    assert result['field_source_ids'] == attempts[-1]['answer']
    assert 'S3' in result['selected_source_ids'] and 'S4' in result['selected_source_ids']
    assert 'narrative_evidence_spans' not in attempts[-1]['input']
    assert len(attempts[-1]['input']['source_view_inventory_digest']) == 64
    assert module.evaluate_coverage(rows, PIN, attempts)['state'] == 'blocked'


def test_v2_complete_nominal_sources_are_admitted_without_inventing_relationships():
    source = sources(1)[0]
    source['passage'] = 'Synthetic team\nPerson A\nPerson B\nRole descriptions awaiting review.'
    views = module.complete_source_views(source)
    quote = next(iter(views.values()))
    assert quote['exact_text'] == source['passage']
    assert quote['start'] == 0 and quote['end'] == len(source['passage'])
    assert quote['source_version'] == source['version']
    assert quote['quote_hash'] == digest(source['passage'])
    assert quote['verification_status'] == 'source_report_only'
    assert 'interpretation' not in quote


def test_v2_complete_paragraphs_are_never_truncated_to_fit_quotes():
    source = sources(1)[0]
    long = 'Uninterpreted source text ' * 40
    short = 'The company reports a separate complete paragraph.'
    source['passage'] = long + '\n\n' + short
    views = module.complete_source_views(source)
    assert [row['exact_text'] for row in views.values()] == [short]
    assert next(iter(views.values()))['start'] == len(long) + 2
    source['passage'] = long
    with pytest.raises(ValueError, match='complete bounded'):
        module.complete_source_views(source)


def test_v2_rejects_topic_omission_and_same_scopes_without_replacing_answers():
    rows = sources(5)
    attempts = complete_v2_records(rows)
    request = module.pending_coverage_request(rows, PIN, attempts[:-1], contract=module.CONTRACT_V2)
    no_team = copy.deepcopy(attempts[-1]['answer'])
    no_team['differentiation_and_execution'] = ['S1']
    altered = attempts[:-1] + [recorded_row(request, no_team, len(attempts))]
    result = module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V2)
    assert result['state'] == 'blocked'
    assert result['field_scope_selection'] == 'blocked'
    assert result['assessed_source_ids'] == [row['id'] for row in rows]
    assert result['unassessed_sources'] == []
    assert result['coverage_complete'] is False
    assert 'field_source_ids' not in result
    assert altered[-1]['answer'] == no_team
    bad_prefix = copy.deepcopy(altered)
    bad_prefix[0]['raw_response'] += ' '
    untrusted = module.evaluate_coverage(rows, PIN, bad_prefix, contract=module.CONTRACT_V2)
    assert untrusted['state'] == 'blocked'
    assert untrusted['assessed_source_ids'] == []
    assert untrusted['unassessed_sources'] == [row['id'] for row in rows]
    no_finance = copy.deepcopy(attempts[-1]['answer'])
    no_finance['diligence_plan'] = ['S5']
    altered = attempts[:-1] + [recorded_row(request, no_finance, len(attempts))]
    assert module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V2)['state'] == 'blocked'
    with pytest.raises(ValueError, match='three distinct'):
        module._validate_field_diversity_v2({field: ['S1'] for field in module.FIELDS},
                                          {'required_topic_source_groups': {}})


def test_v2_category_policy_cannot_select_an_ineligible_topic_for_a_field():
    rows = sources(5)
    attempts = complete_v2_records(rows)
    request = module.pending_coverage_request(rows, PIN, attempts[:-1], contract=module.CONTRACT_V2)
    wrong = copy.deepcopy(attempts[-1]['answer'])
    wrong['business_and_market'] = ['S3']
    with pytest.raises(ValueError):
        recorded_row(request, wrong, len(attempts))


def test_v3_topics_are_required_in_their_fields_with_exact_prefix_pin_and_scope_binding():
    rows = sources(5)
    original = complete_v2_records(rows)
    prefix = original[:-1]
    v3_requests = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V3)
    assert [request[:3] for request in v3_requests] == [
        request[:3] for request in module.frozen_coverage_requests(rows, PIN)]
    assert [request[3].model_json_schema() for request in v3_requests] == [
        record['schema'] for record in prefix]
    assert module.evaluate_coverage(rows, PIN, original, contract=module.CONTRACT_V2)['state'] == 'accepted'
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V3)
    assert request[0] == module.SELECT_TASK_V3
    assert request[2]['field_source_candidates']['differentiation_and_execution'] == ['S3']
    assert request[2]['field_source_candidates']['diligence_plan'] == ['S4']
    answer = {**original[-1]['answer'], 'diligence_plan': ['S4']}
    records = prefix + [recorded_row(request, answer, len(original))]
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V3)
    assert result['state'] == 'accepted'
    assert result['field_source_ids'] == answer  # No software substitution.
    assert module.source_views_for_coverage(rows[2], module.CONTRACT_V3) == module.complete_source_views(rows[2])
    for field, ids in [('differentiation_and_execution', ['S1']), ('diligence_plan', ['S5'])]:
        with pytest.raises(ValueError):
            recorded_row(request, {**answer, field: ids}, len(original))
    for altered_key in ('pin', 'scope'):
        altered = copy.deepcopy(records)
        if altered_key == 'pin':
            altered[-1]['input']['model_pin']['digest'] = 'b' * 64
        else:
            altered[-1]['input']['field_source_candidates']['diligence_plan'].append('S5')
        assert module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V3)['state'] == 'blocked'
    # The role restrictions depend on eligible recorded categories, never source
    # IDs or company names. Missing eligible specialist topics retain V2 fallbacks.
    candidates, required = module._field_candidates_v3(
        rows, prefix[0]['answer'], ['S1', 'S2', 'S5'])
    assert candidates['differentiation_and_execution'] == ['S1']
    assert candidates['diligence_plan'] == ['S5']
    assert required == {}


def complete_v4_records(rows):
    """Synthetic only: callers supply a capital-labelled fourth source."""
    categories = {'S1': ['product_and_customers', 'market_and_competition'],
                  'S2': ['risks', 'market_and_competition'],
                  'S3': ['team_and_governance'],
                  'S4': ['financial_evidence', 'funding_and_ownership'],
                  'S5': ['legal_and_compliance', 'material_unknowns'],
                  'S6': ['team_and_governance']}
    attempts = []
    for request in module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V4):
        answer = {sid: {'disposition': 'relevant',
                       'writing_utility': 'contact' if sid == 'S6' else 'substantive',
                       'utility_evidence_id': next(iter(row['evidence_spans'])),
                       'category_support': {category: next(iter(row['evidence_spans']))
                                            for category in categories[sid]},
                       'reason': 'Reports this synthetic diligence topic.'}
                  for sid, row in request[2]['sources'].items()}
        attempts.append(recorded_row(request, answer, len(attempts) + 1))
    request = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V4)
    answer = {'investment_thesis': ['S1'], 'business_and_market': ['S1', 'S2'],
              'differentiation_and_execution': ['S3'], 'risks_and_countercase': ['S2'],
              'diligence_plan': ['S4']}
    attempts.append(recorded_row(request, answer, len(attempts) + 1))
    return attempts


def test_v4_fresh_category_support_and_recorded_utility_gate_without_company_mapping():
    rows = sources(6)
    rows[3]['passage'] = 'Synthetic financing report includes equity raised and venture debt.'
    attempts = complete_v4_records(rows)
    assert attempts[0]['task'] == module.CLASSIFY_TASK_V2
    assert attempts[-1]['task'] == module.SELECT_TASK_V4
    result = module.evaluate_coverage(rows, PIN, attempts, contract=module.CONTRACT_V4)
    assert result['state'] == 'accepted'
    assert result['assessed_source_ids'] == [row['id'] for row in rows]
    assert result['judgments']['S6']['writing_utility'] == 'contact'
    assert 'S6' not in attempts[-1]['input']['eligible_narrative_source_ids']
    assert attempts[-1]['input']['field_source_candidates']['differentiation_and_execution'] == ['S3']
    assert result['field_source_ids'] == attempts[-1]['answer']
    assert module.evaluate_coverage(rows, PIN, attempts, contract=module.CONTRACT_V3)['state'] == 'blocked'
    assert all('exact_text' not in span for source in attempts[0]['input']['sources'].values()
               for span in source['evidence_spans'].values())
    assert [source['source']['passage'] for source in attempts[0]['input']['sources'].values()] == [
        row['passage'] for row in rows[:5]]
    assert attempts[0]['input']['source_set_digest'] == digest(rows)


@pytest.mark.parametrize('defect', ['false_funding', 'omitted_funding', 'foreign_support'])
def test_v4_capital_label_validation_blocks_without_reclassifying(defect):
    rows = sources(5)
    rows[3]['passage'] = 'Synthetic financing report includes a cap table and venture debt.'
    original = complete_v4_records(rows)
    request = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V4)[0]
    answer = copy.deepcopy(original[0]['answer'])
    if defect == 'false_funding':
        answer['S1']['category_support']['funding_and_ownership'] = 'S1.e001'
    elif defect == 'omitted_funding':
        answer['S4']['category_support'].pop('funding_and_ownership')
    else:
        answer['S1']['category_support']['product_and_customers'] = 'S4.e001'
    if defect == 'foreign_support':
        with pytest.raises(ValueError):
            recorded_row(request, answer, 1)
        return
    recorded = recorded_row(request, answer, 1)
    result = module.evaluate_coverage(rows, PIN, [recorded], contract=module.CONTRACT_V4)
    assert result['state'] == 'blocked'
    assert recorded['answer'] == answer
    assert result['coverage_complete'] is False
    assert 'field_source_ids' not in result


@pytest.mark.parametrize('separator', ['\n', r'\n'])
def test_v4_exact_whole_line_groups_admit_long_sources_without_widening_claim_quotes(separator):
    source = sources(1)[0]
    lines = ['Synthetic team experience and stated role. ' * 6] * 4
    source['passage'] = separator.join(lines)
    assert len(source['passage']) > 700
    views = module.source_views_for_coverage(source, module.CONTRACT_V4)
    assert len(views) == 2
    for view in views.values():
        assert len(view['exact_text']) <= 700
        assert source['passage'][view['start']:view['end']] == view['exact_text']
        assert view['quote_hash'] == digest(view['exact_text'])
        assert view['source_version'] == source['version']
        assert view['verification_status'] == 'source_report_only'
    assert [view['exact_text'] for view in views.values()] == [
        separator.join(lines[:2]), separator.join(lines[2:])]
    with pytest.raises(ValueError):
        module.source_views_for_coverage(source, module.CONTRACT_V3)


def test_v4_long_original_lines_and_serialized_tables_are_retained_but_not_cut():
    source = sources(1)[0]
    long = 'Uninterpreted source text ' * 40
    complete = 'A separate complete original source line.'
    source['passage'] = long + '\n' + complete
    views = module.source_views_for_coverage(source, module.CONTRACT_V4)
    assert [view['exact_text'] for view in views.values()] == [complete]
    source['passage'] = json.dumps({'rows': [long, complete + '\n' + complete]})
    with pytest.raises(ValueError, match='original-line'):
        module.source_views_for_coverage(source, module.CONTRACT_V4)


@pytest.mark.parametrize('utility', ['header', 'contact', 'context'])
def test_v4_non_substantive_context_can_have_no_topic_but_never_author_a_field(utility):
    rows = sources(5)
    rows[3]['passage'] = 'Synthetic financing report includes equity raised and venture debt.'
    original = complete_v4_records(rows)
    request = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V4)[0]
    answer = copy.deepcopy(original[0]['answer'])
    answer['S1'].update(disposition='context_only', writing_utility=utility, category_support={})
    recorded = recorded_row(request, answer, 1)
    result = module.evaluate_coverage(rows, PIN, [recorded], contract=module.CONTRACT_V4)
    assert result['state'] == 'needs_call'
    assert result['judgments']['S1']['categories'] == []
    pending = module.pending_coverage_request(rows, PIN, [recorded], contract=module.CONTRACT_V4)
    assert 'S1' not in pending[2]['eligible_narrative_source_ids']
    assert all('S1' not in ids for ids in pending[2]['field_source_candidates'].values())
    answer['S1']['writing_utility'] = 'substantive'
    invalid = recorded_row(request, answer, 1)
    blocked = module.evaluate_coverage(rows, PIN, [invalid], contract=module.CONTRACT_V4)
    assert blocked['state'] == 'blocked'
    assert 'supported category' in blocked['detail']
    assert blocked['coverage_complete'] is False


def complete_v5_records(rows, *, preliminary_context=False):
    original = complete_v4_records(rows)
    prefix = original[:-1]
    if preliminary_context:
        answer = copy.deepcopy(prefix[0]['answer'])
        answer['S1'].update(disposition='context_only', writing_utility='context')
        request = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V4)[0]
        prefix[0] = recorded_row(request, answer, 1)
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V5)
    answer = {**original[-1]['answer'],
              'content_kinds': {row['id']: 'contact_only' if row['id'] == 'S6' else 'information'
                                for row in rows}}
    return prefix + [recorded_row(request, answer, len(original))]


def test_v5_reuses_v4_classification_bytes_and_records_independent_content_kinds():
    rows = sources(6)
    rows[3]['passage'] = 'Synthetic financing report includes equity raised and venture debt.'
    v4 = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V4)
    v5 = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V5)
    assert [request[:3] for request in v4] == [request[:3] for request in v5]
    assert [request[3].model_json_schema() for request in v4] == [request[3].model_json_schema() for request in v5]
    original = complete_v4_records(rows)
    assert module.evaluate_coverage(rows, PIN, original, contract=module.CONTRACT_V4)['state'] == 'accepted'
    records = complete_v5_records(rows, preliminary_context=True)
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V5)
    assert result['state'] == 'accepted'
    assert records[0]['input']['contract'] == module.CONTRACT_V4
    assert records[-1]['task'] == module.SELECT_TASK_V5
    assert result['judgments']['S1']['writing_utility'] == 'context'
    assert result['judgments']['S1']['disposition'] == 'context_only'
    assert result['source_content_kinds'] == records[-1]['answer']['content_kinds']
    assert result['source_content_kinds']['S1'] == 'information'
    assert result['field_source_ids'] == {field: records[-1]['answer'][field] for field in module.FIELDS}
    assert 'S1' in result['field_source_ids']['business_and_market']
    assert set(result['source_content_kinds']) == {row['id'] for row in rows}
    payload = records[-1]['input']
    assert all(key not in payload for key in (
        'eligible_narrative_source_ids', 'source_view_ids', 'classification_response_ids'))
    assert len(payload['source_view_inventory_digest']) == 64
    assert len(payload['classification_response_digest']) == 64
    assert [row['passage'] for row in payload['sources']] == [row['passage'] for row in rows]
    assert module.source_views_for_coverage(rows[2], module.CONTRACT_V5) == module.source_views_for_coverage(rows[2], module.CONTRACT_V4)
    assert module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V4)['state'] == 'blocked'


@pytest.mark.parametrize('kind', ['heading_only', 'contact_only'])
def test_v5_new_kind_blocks_selected_non_information_without_losing_valid_prefix(kind):
    rows = sources(5)
    rows[3]['passage'] = 'Synthetic financing report includes equity raised and venture debt.'
    records = complete_v5_records(rows)
    request = module.pending_coverage_request(rows, PIN, records[:-1], contract=module.CONTRACT_V5)
    answer = copy.deepcopy(records[-1]['answer'])
    answer['content_kinds']['S1'] = kind
    records[-1] = recorded_row(request, answer, len(records))
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V5)
    assert result['state'] == 'blocked'
    assert result['coverage_complete'] is False
    assert result['assessed_source_ids'] == [row['id'] for row in rows]
    assert 'field_source_ids' not in result
    assert records[-1]['answer'] == answer
    for kinds in ({'S1': 'information'}, {**answer['content_kinds'], 'foreign': 'information'}):
        with pytest.raises(ValueError):
            recorded_row(request, {**answer, 'content_kinds': kinds}, len(records))
    # The new all-source map must not count as another field source set.
    two_sets = {field: ['S1'] for field in module.FIELDS}
    two_sets['diligence_plan'] = ['S4']
    selected = module._selected_field_scopes(
        {**two_sets, 'content_kinds': {row['id']: 'information' for row in rows}},
        module.CONTRACT_V5, {row['id'] for row in rows})
    with pytest.raises(ValueError, match='three distinct'):
        module._validate_field_diversity_v2(selected, {'required_topic_source_groups': {}})


def test_v6_has_fixed_required_source_kind_properties_with_unchanged_classification_prefix():
    rows = sources(5)
    rows[3]['passage'] = 'Synthetic financing report includes equity raised and venture debt.'
    original = complete_v5_records(rows, preliminary_context=True)
    prefix = original[:-1]
    v4 = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V4)
    v6 = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V6)
    assert [request[:3] for request in v6] == [request[:3] for request in v4]
    assert [request[3].model_json_schema() for request in v6] == [record['schema'] for record in prefix]
    assert module.evaluate_coverage(rows, PIN, original, contract=module.CONTRACT_V5)['state'] == 'accepted'
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V6)
    schema = request[3].model_json_schema()
    fixed = schema['$defs']['DiligenceSourceContentKindsV6']
    assert fixed['additionalProperties'] is False
    assert set(fixed['properties']) == {row['id'] for row in rows}
    assert set(fixed['required']) == set(fixed['properties'])
    assert 'propertyNames' not in fixed
    assert schema['$defs']['SourceKindV6']['enum'] == [
        'information', 'heading_only', 'contact_only']
    assert all(value['$ref'] == '#/$defs/SourceKindV6'
               for value in fixed['properties'].values())
    valid = recorded_row(request, original[-1]['answer'], len(original))
    result = module.evaluate_coverage(rows, PIN, prefix + [valid], contract=module.CONTRACT_V6)
    assert result['state'] == 'accepted'
    assert result['source_content_kinds'] == valid['answer']['content_kinds']
    assert result['field_source_ids'] == {field: valid['answer'][field] for field in module.FIELDS}
    assert result['judgments']['S1']['writing_utility'] == 'context'
    for kinds in ({field: 'information' for field in module.FIELDS},
                  {'S1': 'information'},
                  {**valid['answer']['content_kinds'], 'foreign': 'information'},
                  {**valid['answer']['content_kinds'], 'S1': 'unsupported_kind'}):
        with pytest.raises(ValueError):
            recorded_row(request, {**valid['answer'], 'content_kinds': kinds}, len(original))
    heading = copy.deepcopy(valid['answer'])
    heading['content_kinds']['S1'] = 'heading_only'
    bad = recorded_row(request, heading, len(original))
    blocked = module.evaluate_coverage(rows, PIN, prefix + [bad], contract=module.CONTRACT_V6)
    assert blocked['state'] == 'blocked'
    assert blocked['coverage_complete'] is False
    assert 'field_source_ids' not in blocked
    assert bad['answer'] == heading
    assert module.source_views_for_coverage(rows[2], module.CONTRACT_V6) == module.source_views_for_coverage(rows[2], module.CONTRACT_V5)


def test_v7_orders_kind_first_projects_only_recorded_categories_and_preserves_raw_binding():
    rows = sources(5)
    rows[3]['passage'] = 'Synthetic financing report includes equity raised and venture debt.'
    prior = complete_v5_records(rows, preliminary_context=True)
    prefix = prior[:-1]
    v4 = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V4)
    v7 = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V7)
    assert [request[:3] for request in v7] == [request[:3] for request in v4]
    assert [request[3].model_json_schema() for request in v7] == [record['schema'] for record in prefix]
    assert all(record['routing'].get('require_full_context') is None for record in prefix)
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V7)
    schema = request[3].model_json_schema()
    assert next(iter(schema['properties'])) == 'content_kinds'
    assert schema['required'][0] == 'content_kinds'
    fixed = schema['$defs']['SourceKindsV7']
    assert fixed['additionalProperties'] is False
    assert set(fixed['properties']) == set(fixed['required']) == {row['id'] for row in rows}
    assert schema['$defs']['KindV7']['enum'] == ['information', 'heading_only', 'contact_only']
    payload = request[2]
    assert payload['options'] == module.OPTIONS_V7
    assert module.options_for(module.CONTRACT_V7, 'classification') == module.OPTIONS
    assert module.options_for(module.CONTRACT_V7, 'diligence_field_selection') == module.OPTIONS_V7
    assert payload['classification_response_digest'] == digest(prefix)
    assert [source['passage'] for source in payload['sources']] == [row['passage'] for row in rows]
    for sid, unit in prefix[0]['answer'].items():
        assert payload['judgments'][sid] == {key: unit[key] for key in ('disposition', 'category_support')}
    final = recorded_row(request, prior[-1]['answer'], len(prior))
    result = module.evaluate_coverage(rows, PIN, prefix + [final], contract=module.CONTRACT_V7)
    assert result['state'] == 'accepted'
    assert result['judgments']['S1']['writing_utility'] == 'context'
    assert result['source_content_kinds'] == final['answer']['content_kinds']
    assert module.source_views_for_coverage(rows[2], module.CONTRACT_V7) == module.source_views_for_coverage(rows[2], module.CONTRACT_V6)
    # Exact replay must independently reject receipt loss, overflow and output
    # starvation even if the original recorded inference error were removed.
    for count in (None, 4098, 8000, True):
        altered = copy.deepcopy(final)
        altered['routing']['prompt_tokens'] = count
        blocked = module.evaluate_coverage(rows, PIN, prefix + [altered], contract=module.CONTRACT_V7)
        assert blocked['state'] == 'blocked'
        assert 'context integrity' in blocked['detail']
        assert 'field_source_ids' not in blocked
    altered = copy.deepcopy(final)
    altered['routing']['compact_prompt'] = False
    assert module.evaluate_coverage(rows, PIN, prefix + [altered], contract=module.CONTRACT_V7)['state'] == 'blocked'


def test_v8_keeps_old_category_wire_but_requires_each_cached_full_context_receipt():
    rows = sources(6)
    rows[3]['passage'] = 'Synthetic financing report includes equity raised and venture debt.'
    rows[5]['passage'] = 'Synthetic Platform Tomorrow\nSynthetic Market'
    prior = complete_v5_records(rows, preliminary_context=True)
    prefix = prior[:-1]
    old = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V4)
    fresh = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V8)
    assert [request[:3] for request in old] == [request[:3] for request in fresh]
    assert [request[3].model_json_schema() for request in old] == [
        request[3].model_json_schema() for request in fresh]
    assert all(record['routing'].get('require_full_context') is None for record in prefix)
    assert module.options_for(module.CONTRACT_V8, 'classification') == {
        **module.OPTIONS, 'require_full_context': True}
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V8)
    assert request[2]['options'] == module.OPTIONS_V8
    assert next(iter(request[3].model_json_schema()['properties'])) == 'content_kinds'
    answer = copy.deepcopy(prior[-1]['answer'])
    answer['content_kinds']['S6'] = 'heading_only'  # Recorded local choice, no lexical exclusion.
    final = recorded_row(request, answer, len(prior))
    result = module.evaluate_coverage(rows, PIN, prefix + [final], contract=module.CONTRACT_V8)
    assert result['state'] == 'accepted'
    assert result['source_content_kinds'] == answer['content_kinds']
    assert 'S6' not in result['selected_source_ids']
    for index in range(len(prefix)):
        for count in (None, 4098, 8000):
            altered = copy.deepcopy(prefix)
            altered[index]['routing']['prompt_tokens'] = count
            blocked = module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V8)
            assert blocked['state'] == 'blocked'
            assert 'context integrity' in blocked['detail']
            assert 'field_source_ids' not in blocked
    # Receipt enforcement is a new V8 contract rule; historic V7 replay stays
    # unchanged for category calls whose old options did not require receipts.
    altered = copy.deepcopy(prefix)
    altered[0]['routing']['prompt_tokens'] = 4098
    assert module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V7)['state'] == 'needs_call'


def complete_v9_records(rows, *, contract=module.CONTRACT_V9, structured_ids=()):
    categories = {'S1': ['product_and_customers', 'market_and_competition'],
                  'S2': ['risks', 'market_and_competition'],
                  'S3': ['team_and_governance'],
                  'S4': ['financial_evidence', 'funding_and_ownership'],
                  'S5': ['legal_and_compliance', 'material_unknowns']}
    attempts = []
    for request in module.frozen_coverage_requests(rows, PIN, contract=contract):
        answer = {}
        for sid, offered in request[2]['sources'].items():
            kind = 'heading_only' if sid == 'S6' else 'contact_only' if sid == 'S7' else 'information'
            if sid in structured_ids:
                kind = 'structured_information'
            answer[sid] = {'content_kind': kind,
                'disposition': 'relevant' if kind in {'information', 'structured_information'} else 'context_only',
                'kind_evidence_id': next(iter(offered['evidence_spans'])),
                'category_support': {category: next(iter(offered['evidence_spans']))
                    for category in categories.get(sid, ['product_and_customers'])}
                    if kind in {'information', 'structured_information'} else {},
                'reason': 'Reports this synthetic diligence topic.'}
        attempts.append(recorded_row(request, answer, len(attempts) + 1))
    request = module.pending_coverage_request(rows, PIN, attempts, contract=contract)
    answer = {'investment_thesis': ['S1'], 'business_and_market': ['S1', 'S2'],
              'differentiation_and_execution': ['S3'], 'risks_and_countercase': ['S2'],
              'diligence_plan': ['S4']}
    attempts.append(recorded_row(request, answer, len(attempts) + 1))
    return attempts


def complete_v10_records(rows):
    return complete_v9_records(rows, contract=module.CONTRACT_V10,
                               structured_ids={'S3', 'S4'})


def complete_v11_records(rows):
    old = complete_v10_records(rows)
    prefix = old[:-1]
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V11)
    return [*prefix, recorded_row(request, {'patches': [], **old[-1]['answer']}, len(prefix) + 1)]


def complete_v12_records(rows, *, patches=None, fields=None):
    old = complete_v10_records(rows)
    prefix = old[:-1]
    adjudication = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V12)
    recorded = recorded_row(adjudication, {'patches': [] if patches is None else patches}, len(prefix) + 1)
    selection = module.pending_coverage_request(rows, PIN, [*prefix, recorded], contract=module.CONTRACT_V12)
    return [*prefix, recorded, recorded_row(selection, old[-1]['answer'] if fields is None else fields,
                                            len(prefix) + 2)]


def complete_v13_records(rows):
    # All rows are new synthetic model responses, not relabeled real history.
    synthetic = complete_v10_records(rows)
    attempts = [recorded_row(request, synthetic[index]['answer'], index + 1)
        for index, request in enumerate(module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V13))]
    adjudication = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V13)
    attempts.append(recorded_row(adjudication, {'patches': []}, len(attempts) + 1))
    selection = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V13)
    attempts.append(recorded_row(selection, synthetic[-1]['answer'], len(attempts) + 1))
    return attempts


def test_v9_kind_is_first_in_every_small_batch_and_selector_only_chooses_recorded_information():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    rows[5]['passage'] = 'Synthetic Funding Round\nOur Synthetic Market'
    rows[6]['passage'] = 'Contact: synthetic@example.invalid'
    records = complete_v9_records(rows)
    assert len(records) == module.MAX_CALLS
    assert len(records[:-1]) == 5
    for record in records[:-1]:
        assert record['task'] == module.CLASSIFY_TASK_V3
        assert len(record['input']['sources']) <= module.BATCH_SOURCES
        assert record['input']['options'] == module.OPTIONS_V9
        for sid in record['input']['sources']:
            unit = record['schema']['$defs']['DiligenceSourceCategoryV3_' + sid]
            assert next(iter(unit['properties'])) == 'content_kind'
            assert unit['required'][0] == 'content_kind'
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V9)
    assert result['state'] == 'accepted'
    assert result['assessed_source_ids'] == [row['id'] for row in rows]
    assert result['source_content_kinds'] == {
        sid: unit['content_kind'] for record in records[:-1] for sid, unit in record['answer'].items()}
    assert result['source_content_kinds']['S6'] == 'heading_only'
    assert result['judgments']['S6']['category_support'] == {}
    assert result['judgments']['S7']['category_support'] == {}
    assert records[-1]['task'] == module.SELECT_TASK_V9
    assert set(records[-1]['schema']['properties']) == set(module.FIELDS)
    assert 'content_kinds' not in records[-1]['answer']
    assert all(not {'S6', 'S7'}.intersection(ids)
               for ids in records[-1]['input']['field_source_candidates'].values())
    assert result['field_source_ids'] == records[-1]['answer']
    assert result['financial_validation'] == 'not_established'
    assert 'independent_diligence_review_required' in result['positive_suggestion_blockers']
    assert module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V8)['state'] == 'blocked'
    assert module.source_views_for_coverage(rows[2], module.CONTRACT_V9) == module.source_views_for_coverage(rows[2], module.CONTRACT_V8)


def test_v9_heading_categories_and_bad_classification_receipts_never_become_field_evidence():
    rows = sources(6)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    rows[5]['passage'] = 'Synthetic Funding Round\nOur Synthetic Market'
    records = complete_v9_records(rows)
    requests = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V9)
    answer = copy.deepcopy(records[1]['answer'])
    answer['S6']['category_support'] = {'funding_and_ownership': 'S6.e001'}
    bad = recorded_row(requests[1], answer, 2)
    blocked = module.evaluate_coverage(rows, PIN, [records[0], bad], contract=module.CONTRACT_V9)
    assert blocked['state'] == 'blocked'
    assert 'Heading/contact-only' in blocked['detail']
    assert bad['answer'] == answer
    for count in (None, 4098, 8000):
        altered = copy.deepcopy(records[:-1])
        altered[1]['routing']['prompt_tokens'] = count
        blocked = module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V9)
        assert blocked['state'] == 'blocked'
        assert 'context integrity' in blocked['detail']
        assert 'field_source_ids' not in blocked
    scope = module.pending_coverage_request(rows, PIN, records[:-1], contract=module.CONTRACT_V9)
    with pytest.raises(ValueError):
        recorded_row(scope, {**records[-1]['answer'], 'risks_and_countercase': ['S6']}, len(records))


def test_v10_structured_values_roles_and_financial_cues_retain_exact_model_decisions():
    rows = sources(22)
    rows[2]['passage'] = 'Operating model\nFounder — stated role\nDistribution partner — stated role'
    rows[3]['passage'] = 'Reported targets\nRevenue INR million 20\nMargin 5%\nEquity raised INR million 3'
    rows[5]['passage'] = 'Our Market\nTomorrow\nSynthetic Funding Round'
    rows[6]['passage'] = 'Contact: synthetic@example.invalid'
    records = complete_v10_records(rows)
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V10)
    assert len(records) == module.MAX_CALLS
    assert len(records[:-1]) == 5
    assert result['state'] == 'accepted'
    assert result['source_content_kinds']['S3'] == 'structured_information'
    assert result['source_content_kinds']['S4'] == 'structured_information'
    assert result['judgments']['S3']['category_support'] == records[0]['answer']['S3']['category_support']
    assert 'S3' in records[-1]['input']['field_source_candidates']['differentiation_and_execution']
    assert 'S4' in records[-1]['input']['field_source_candidates']['diligence_plan']
    assert result['field_source_ids'] == records[-1]['answer']
    assert records[-1]['task'] == module.SELECT_TASK_V10
    assert set(records[-1]['schema']['properties']) == set(module.FIELDS)
    assert all(not {'S6', 'S7'}.intersection(ids)
               for ids in records[-1]['input']['field_source_candidates'].values())
    for record in records[:-1]:
        assert record['task'] == module.CLASSIFY_TASK_V4
        assert record['input']['options'] == module.OPTIONS_V10
        for sid, source in record['input']['sources'].items():
            schema = record['schema']['$defs']['DiligenceSourceCategoryV4_' + sid]
            assert schema['required'][0] == 'content_kind'
            for label in source['literal_financial_labels'].values():
                assert source['source']['passage'][label['start']:label['end']] == label['exact_text']
    cues = records[0]['input']['sources']['S4']['literal_financial_labels']
    assert {item['exact_text'] for item in cues.values()} == {'Revenue', 'Margin'}
    assert result['financial_validation'] == 'not_established'
    assert result['financial_evidence_scope']['semantic_coverage'] == 'unassessed'
    assert result['investment_approval'] == 'not_established'
    assert module.source_views_for_coverage(rows[2], module.CONTRACT_V10) == module.source_views_for_coverage(rows[2], module.CONTRACT_V9)


@pytest.mark.parametrize('fault', ['empty_support', 'foreign_support', 'heading_support', 'receipt'])
def test_v10_structured_kind_requires_own_support_and_context_proof(fault):
    rows = sources(7)
    rows[2]['passage'] = 'Team diagram\nFounder — stated role\nPartner — stated role'
    rows[3]['passage'] = 'Revenue forecast 20\nEquity raised INR million 3'
    records = complete_v10_records(rows)
    request = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V10)[0]
    answer = copy.deepcopy(records[0]['answer'])
    if fault == 'empty_support':
        answer['S3']['category_support'] = {}
    elif fault == 'foreign_support':
        answer['S3']['category_support'] = {'team_and_governance': 'S4.e001'}
        with pytest.raises(ValueError):
            recorded_row(request, answer, 1)
        return
    elif fault == 'heading_support':
        answer['S3']['content_kind'] = 'heading_only'
    first = recorded_row(request, answer, 1)
    if fault == 'receipt':
        first['routing']['prompt_tokens'] = 4098
    blocked = module.evaluate_coverage(rows, PIN, [first], contract=module.CONTRACT_V10)
    assert blocked['state'] == 'blocked'
    assert 'field_source_ids' not in blocked
    assert blocked['assessed_source_ids'] == []


def test_v10_financial_label_cues_never_assign_categories_and_v9_requests_replay_unchanged():
    rows = sources(7)
    rows[0]['passage'] = 'Market report: industry sales target 20; product channel described.'
    rows[3]['passage'] = 'Reported equity raised INR million 3.'
    legacy = complete_v9_records(rows)
    legacy_bytes = json.dumps(legacy, ensure_ascii=False)
    v10 = complete_v10_records(rows)
    # The recorded local source assessment has product/market, not financial;
    # lexical sales/target cues cannot create a software-authored finance answer.
    result = module.evaluate_coverage(rows, PIN, v10, contract=module.CONTRACT_V10)
    assert result['state'] == 'accepted'
    assert 'S1' not in result['category_source_ids']['financial_evidence']
    assert 'S1' in result['category_source_ids']['market_and_competition']
    assert module.evaluate_coverage(rows, PIN, legacy, contract=module.CONTRACT_V9)['state'] == 'accepted'
    assert json.dumps(legacy, ensure_ascii=False) == legacy_bytes
    assert module.evaluate_coverage(rows, PIN, legacy, contract=module.CONTRACT_V10)['state'] == 'blocked'


def v11_duplicate_fixture():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    rows[9]['passage'] = rows[0]['passage']
    legacy = complete_v10_records(rows)
    requests = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V10)
    answer = copy.deepcopy(legacy[1]['answer'])
    answer['S10'].update(content_kind='heading_only', disposition='context_only',
                         category_support={}, reason='Only a synthetic section heading.')
    prefix = [legacy[0], recorded_row(requests[1], answer, 2), *legacy[2:-1]]
    patch = {'source_id': 'S10', 'kind': 'information', 'use': 'relevant', 'proof': 'S10.e001',
        'topics': {'product_and_customers': 'S10.e001', 'market_and_competition': 'S10.e001'},
        'why': 'Reports the synthetic product and market.'}
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V11)
    return rows, prefix, patch, request, legacy[-1]['answer']


def test_v11_reuses_exact_v10_classifier_bytes_and_projects_only_recorded_own_source_patches():
    rows, prefix, patch, request, fields = v11_duplicate_fixture()
    frozen = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V11)
    legacy = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V10)
    assert [(task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in frozen] == [
        (task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in legacy]
    assert all(row['input']['contract'] == module.CONTRACT_V10 for row in prefix)
    original = json.dumps(prefix, ensure_ascii=False)
    record = recorded_row(request, {'patches': [patch], **fields}, 6)
    result = module.evaluate_coverage(rows, PIN, [*prefix, record], contract=module.CONTRACT_V11)
    assert result['state'] == 'accepted'
    assert result['classifier_contract'] == module.CONTRACT_V10
    assert result['adjudication_patches'] == [patch]
    assert result['source_content_kinds']['S10'] == 'information'
    assert result['judgments']['S10']['category_support'] == patch['topics']
    assert result['field_source_ids'] == fields
    assert set(result['field_source_ids']) == set(module.FIELDS)
    assert json.dumps(prefix, ensure_ascii=False) == original
    assert request[0] == module.SELECT_TASK_V11
    assert request[2]['classifier_contract'] == module.CONTRACT_V10
    assert request[2]['duplicate_passage_groups'][0]['source_ids'] == ['S1', 'S10']
    assert result['financial_validation'] == 'not_established'
    assert result['investment_approval'] == 'not_established'
    assert module.evaluate_coverage(rows, PIN, [*prefix, record], contract=module.CONTRACT_V10)['state'] == 'blocked'


@pytest.mark.parametrize('fault', ['unpatched_duplicate', 'foreign_evidence', 'heading_with_topics',
                                 'unresolved_duplicate', 'duplicate_patch', 'wrong_field', 'receipt', 'raw'])
def test_v11_unresolved_or_unbound_adjudication_blocks_without_erasing_five_valid_classifiers(fault):
    rows, prefix, patch, request, fields = v11_duplicate_fixture()
    answer = {'patches': [copy.deepcopy(patch)], **copy.deepcopy(fields)}
    if fault == 'unpatched_duplicate':
        answer['patches'] = []
    elif fault == 'foreign_evidence':
        answer['patches'][0]['proof'] = 'S1.e001'
    elif fault == 'heading_with_topics':
        answer['patches'][0]['kind'] = 'heading_only'
    elif fault == 'unresolved_duplicate':
        answer['patches'][0]['use'] = 'unresolved'
    elif fault == 'duplicate_patch':
        answer['patches'].append(copy.deepcopy(patch))
    elif fault == 'wrong_field':
        answer['differentiation_and_execution'] = ['S10']
    record = recorded_row(request, answer, 6)
    if fault == 'receipt':
        record['routing']['prompt_tokens'] = 4098
    elif fault == 'raw':
        record['raw_response'] += ' '
    result = module.evaluate_coverage(rows, PIN, [*prefix, record], contract=module.CONTRACT_V11)
    assert result['state'] == 'blocked'
    assert result['coverage_complete'] is False
    assert result['assessed_source_ids'] == [row['id'] for row in rows]
    assert result['judgments']['S10']['content_kind'] == 'heading_only'
    assert 'field_source_ids' not in result


def test_v11_patch_limit_and_topic_changes_drive_final_field_candidates_only():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    rows[14]['passage'] = 'Reported revenue target 20 and margin 5 percent.'
    old = complete_v10_records(rows)
    prefix = old[:-1]
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V11)
    patch = {'source_id': 'S15', 'kind': 'structured_information', 'use': 'relevant',
             'proof': 'S15.e001', 'topics': {'financial_evidence': 'S15.e001'},
             'why': 'Reports synthetic revenue and margin targets.'}
    answer = {'patches': [patch], **old[-1]['answer'], 'diligence_plan': ['S15']}
    records = [*prefix, recorded_row(request, answer, 6)]
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V11)
    assert result['state'] == 'accepted'
    assert result['field_source_ids']['diligence_plan'] == ['S15']
    assert 'S15' in result['category_source_ids']['financial_evidence']
    assert result['judgments']['S15']['category_support'] == patch['topics']
    assert request[3].model_json_schema()['properties']['patches']['maxItems'] == 8
    with pytest.raises(ValueError):
        recorded_row(request, {**answer, 'patches': [patch] * 9}, 6)


@pytest.mark.parametrize('tamper', ['provenance_digest', 'input_judgment', 'window_end'])
def test_v11_compact_provenance_and_visible_original_judgments_cannot_be_substituted(tamper):
    rows, prefix, patch, request, fields = v11_duplicate_fixture()
    record = recorded_row(request, {'patches': [patch], **fields}, 6)
    changed = copy.deepcopy(record)
    if tamper == 'provenance_digest':
        changed['input']['adjudication_binding_digest'] = 'b' * 64
    elif tamper == 'input_judgment':
        changed['input']['judgments']['S10']['kind'] = 'information'
    else:
        changed['input']['evidence_window_ends']['S10'] = [1, len(rows[9]['passage'])]
    result = module.evaluate_coverage(rows, PIN, [*prefix, changed], contract=module.CONTRACT_V11)
    assert result['state'] == 'blocked'
    assert result['assessed_source_ids'] == [row['id'] for row in rows]
    assert 'field_source_ids' not in result


def test_v12_distinct_adjudication_then_frozen_field_enums_with_exact_v10_prefix():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    rows[14]['passage'] = 'Reported revenue target 20 and margin 5 percent.'
    patch = {'source_id': 'S15', 'kind': 'structured_information', 'use': 'relevant',
             'proof': 'S15.e001', 'topics': {'financial_evidence': 'S15.e001'},
             'why': 'Reports synthetic revenue and margin targets.'}
    fields = {'investment_thesis': ['S1'], 'business_and_market': ['S1', 'S2'],
              'differentiation_and_execution': ['S3'], 'risks_and_countercase': ['S2'],
              'diligence_plan': ['S15']}
    records = complete_v12_records(rows, patches=[patch], fields=fields)
    assert len(records) == module.MAX_CALLS_V12 == 7
    assert [row['input']['contract'] for row in records[:5]] == [module.CONTRACT_V10] * 5
    assert records[5]['task'] == module.ADJUDICATE_TASK_V12
    assert records[6]['task'] == module.SELECT_TASK_V12
    assert set(records[5]['schema']['properties']) == {'patches'}
    assert set(records[6]['schema']['properties']) == set(module.FIELDS)
    legacy = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V10)
    fresh = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V12)
    assert [(task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in legacy] == [
        (task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in fresh]
    classified = module.evaluate_coverage(rows, PIN, records[:5], contract=module.CONTRACT_V12)
    assert classified['state'] == 'needs_call'
    assert classified['pending_stage'] == classified['batch_id'] == 'source_adjudication'
    adjudicated = module.evaluate_coverage(rows, PIN, records[:6], contract=module.CONTRACT_V12)
    assert adjudicated['state'] == 'needs_call'
    assert adjudicated['source_adjudication'] == 'accepted'
    assert adjudicated['pending_stage'] == adjudicated['batch_id'] == 'field_source_selection'
    assert adjudicated['source_content_kinds']['S15'] == 'structured_information'
    assert 'field_source_ids' not in adjudicated
    assert 'S15' in records[6]['input']['field_source_candidates']['diligence_plan']
    assert 'S15' not in records[6]['input']['field_source_candidates']['business_and_market']
    with pytest.raises(ValueError):
        recorded_row(module.pending_coverage_request(rows, PIN, records[:6], contract=module.CONTRACT_V12),
                     {**fields, 'business_and_market': ['S15']}, 7)
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V12)
    assert result['state'] == 'accepted'
    assert result['adjudication_patches'] == [patch]
    assert result['field_source_ids'] == fields
    assert result['financial_validation'] == 'not_established'
    assert result['investment_approval'] == 'not_established'
    assert module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V11)['state'] == 'blocked'


@pytest.mark.parametrize('fault', ['own_evidence', 'duplicate_conflict', 'sampling', 'receipt'])
def test_v12_invalid_adjudication_never_offers_later_field_selection(fault):
    rows, prefix, patch, _, _ = v11_duplicate_fixture()
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V12)
    if fault == 'own_evidence':
        patch['proof'] = 'S1.e001'
    answer = {'patches': [] if fault == 'duplicate_conflict' else [patch]}
    record = recorded_row(request, answer, 6)
    if fault == 'sampling':
        record['routing']['sampling']['presence_penalty'] = 1.5
    elif fault == 'receipt':
        record['routing']['prompt_tokens'] = 4098
    result = module.evaluate_coverage(rows, PIN, [*prefix, record], contract=module.CONTRACT_V12)
    assert result['state'] == 'blocked'
    assert result['source_adjudication'] == 'blocked'
    assert result['coverage_complete'] is False
    assert result['assessed_source_ids'] == [row['id'] for row in rows]
    assert 'field_source_ids' not in result
    with pytest.raises(ValueError):
        module.pending_coverage_request(rows, PIN, [*prefix, record], contract=module.CONTRACT_V12)


@pytest.mark.parametrize('fault', ['repeat', 'flag', 'frozen_enum', 'binding', 'raw_adjudication', 'extra_record'])
def test_v12_selection_replay_retains_valid_adjudication_but_blocks_tampering(fault):
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    records = complete_v12_records(rows)
    altered = copy.deepcopy(records)
    if fault == 'repeat':
        altered[-1]['routing']['sampling']['repeat_penalty'] = 1.2
    elif fault == 'flag':
        altered[-1]['routing']['factual_sampling'] = False
    elif fault == 'frozen_enum':
        altered[-1]['schema']['properties']['business_and_market']['items']['enum'].append('S6')
    elif fault == 'binding':
        altered[-1]['input']['selection_binding_digest'] = 'c' * 64
    elif fault == 'raw_adjudication':
        altered[-2]['raw_response'] += ' '
    else:
        altered.append({**altered[-1], 'id': 'eighth_response'})
    result = module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V12)
    assert result['state'] == 'blocked'
    assert result['coverage_complete'] is False
    assert 'field_source_ids' not in result
    if fault not in {'raw_adjudication'}:
        assert result['source_adjudication'] == 'accepted'


def test_v12_generic_three_stage_helper_preserves_classification_keys_and_binds_adjudication_receipt():
    from dataclasses import replace
    rows, pin, structures = module._inputs(sources(22), PIN)
    plan = module._adjudicated_plan_v12(rows, pin, structures, module.FINANCIAL_SCOPE)
    old = module._traversal_plan(rows, pin, structures, module.FINANCIAL_SCOPE,
                                model_options=module.OPTIONS_V10)
    assert plan.classification_plan == old
    assert old.call_budget == 6 and plan.call_budget == 7
    batches = [{'batch_key': batch.key, 'results': [{'source_id': sid, 'classification': {}}
               for sid in batch.source_ids]} for batch in old.batches]
    adjudication = {'inventory_digest': old.inventory_digest, 'binding': plan.adjudication_binding,
                    'response_hash': 'a' * 64}
    selected = {'inventory_digest': old.inventory_digest, 'binding': plan.selection_binding,
                'adjudication_response_hash': 'a' * 64, 'selected_ids': ['S1', 'S2']}
    assert module.verify_adjudicated_traversal(plan, batches, adjudication, selected).selected_ids == ('S1', 'S2')
    with pytest.raises(ValueError):
        module.verify_adjudicated_traversal(plan, batches, adjudication,
            {**selected, 'adjudication_response_hash': 'b' * 64})
    with pytest.raises(ValueError):
        module.verify_adjudicated_traversal(plan, batches, adjudication,
            {**selected, 'selected_ids': ['S999']})
    with pytest.raises(ValueError):
        module.verify_adjudicated_traversal(replace(plan, call_budget=8), batches, adjudication, selected)


def test_v13_fresh_classifier_sampling_version_keeps_exact_old_instruction_schema_and_source_values():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    legacy = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V10)
    fresh = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V13)
    for old, new in zip(legacy, fresh):
        assert new[0] == module.CLASSIFY_TASK_V5 and new[0] != old[0]
        assert new[1] == old[1]
        assert new[3].model_json_schema() == old[3].model_json_schema()
        assert new[2]['sources'] == old[2]['sources']
        assert new[2]['category_definitions'] == old[2]['category_definitions']
        assert new[2]['contract'] == module.CONTRACT_V13
        assert new[2]['options'] == module.OPTIONS_V13
        assert new[2]['options']['factual_sampling'] is True
        assert new[2]['batch_key'] != old[2]['batch_key']
        assert new[2]['traversal_plan_digest'] != old[2]['traversal_plan_digest']
    records = complete_v13_records(rows)
    assert len(records) == module.MAX_CALLS_V12
    assert records[-2]['task'] == module.ADJUDICATE_TASK_V13
    assert records[-1]['task'] == module.SELECT_TASK_V13
    assert all(record['input']['contract'] == module.CONTRACT_V13 for record in records)
    assert all(record['input']['options']['factual_sampling'] is True for record in records)
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V13)
    assert result['state'] == 'accepted'
    assert result['classifier_contract'] == module.CONTRACT_V13
    assert result['field_source_ids'] == records[-1]['answer']
    assert result['financial_validation'] == 'not_established'
    assert module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V12)['state'] == 'blocked'
    old_records = complete_v12_records(rows)
    assert module.evaluate_coverage(rows, PIN, old_records, contract=module.CONTRACT_V12)['state'] == 'accepted'
    blocked = module.evaluate_coverage(rows, PIN, old_records[:5], contract=module.CONTRACT_V13)
    assert blocked['state'] == 'blocked' and blocked['assessed_source_ids'] == []


@pytest.mark.parametrize('stage', [0, 1, 2, 3, 4, 5, 6])
def test_v13_every_record_requires_actual_factual_sampler_receipt(stage):
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    records = complete_v13_records(rows)
    altered = copy.deepcopy(records)
    altered[stage]['routing']['sampling']['presence_penalty'] = 1.5
    result = module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V13)
    assert result['state'] == 'blocked'
    assert 'field_source_ids' not in result
    assert 'actual zero presence' in result['detail']


def test_v13_conflicting_duplicate_inventory_requires_a_model_patch_without_supplying_resolution():
    rows, old_prefix, patch, _, fields = v11_duplicate_fixture()
    requests = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V13)
    prefix = [recorded_row(request, old_prefix[index]['answer'], index + 1)
              for index, request in enumerate(requests)]
    original = json.dumps(prefix, ensure_ascii=False)
    request = module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V13)
    assert request[3].model_json_schema()['properties']['patches']['minItems'] == 1
    inventory = request[2]['conflict_inventory']
    assert len(inventory) == 1
    assert inventory[0]['source_ids'] == ['S1', 'S10']
    assert inventory[0]['original_judgments']['S1']['kind'] == 'information'
    assert inventory[0]['original_judgments']['S10']['kind'] == 'heading_only'
    assert inventory[0]['minimum_edit_lower_bound'] == 1
    assert all('resolved' not in key and 'chosen' not in key for key in inventory[0])
    with pytest.raises(ValueError):
        recorded_row(request, {'patches': []}, 6)
    adjudication = recorded_row(request, {'patches': [patch]}, 6)
    selector = module.pending_coverage_request(rows, PIN, [*prefix, adjudication], contract=module.CONTRACT_V13)
    selected = recorded_row(selector, fields, 7)
    result = module.evaluate_coverage(rows, PIN, [*prefix, adjudication, selected], contract=module.CONTRACT_V13)
    assert result['state'] == 'accepted'
    assert result['source_content_kinds']['S10'] == patch['kind']
    assert result['adjudication_patches'] == [patch]
    assert json.dumps(prefix, ensure_ascii=False) == original
    legacy = module.pending_coverage_request(rows, PIN, old_prefix, contract=module.CONTRACT_V12)
    assert 'conflict_inventory' not in legacy[2]
    assert 'minItems' not in legacy[3].model_json_schema()['properties']['patches']


def test_v13_duplicate_conflict_edit_lower_bound_blocks_more_than_eight_patches_before_call():
    rows = sources(9)
    for row in rows:
        row['passage'] = rows[0]['passage']
    requests = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V13)
    prefix = []
    for request in requests:
        answer = {sid: {'content_kind': 'information', 'disposition': 'unresolved',
            'kind_evidence_id': next(iter(offered['evidence_spans'])),
            'category_support': {'product_and_customers': next(iter(offered['evidence_spans']))},
            'reason': 'Meaning remains uncertain in the source.'}
            for sid, offered in request[2]['sources'].items()}
        prefix.append(recorded_row(request, answer, len(prefix) + 1))
    with pytest.raises(ValueError, match='patch capacity'):
        module.pending_coverage_request(rows, PIN, prefix, contract=module.CONTRACT_V13)
    result = module.evaluate_coverage(rows, PIN, prefix, contract=module.CONTRACT_V13)
    assert result['state'] == 'blocked'
    assert result['assessed_source_ids'] == [row['id'] for row in rows]
    assert 'field_source_ids' not in result


def test_v14_explicit_adjudicator_role_keeps_exact_v13_prefix_and_historical_replay():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    source_pin = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    adjudicator_pin = PIN
    original = complete_v13_records(rows)
    assert module.evaluate_coverage(rows, PIN, original, contract=module.CONTRACT_V13)['state'] == 'accepted'
    old_requests = module.frozen_coverage_requests(rows, source_pin, contract=module.CONTRACT_V13)
    new_requests = module.frozen_coverage_requests(rows, source_pin, contract=module.CONTRACT_V14,
                                                  adjudicator_pin=adjudicator_pin)
    assert [(t, i, p, s.model_json_schema()) for t, i, p, s in new_requests] == [
        (t, i, p, s.model_json_schema()) for t, i, p, s in old_requests]
    prefix = [recorded_row(request, original[index]['answer'], index + 1)
              for index, request in enumerate(new_requests)]
    frozen_prefix = json.dumps(prefix, ensure_ascii=False)
    adjudication = module.pending_coverage_request(rows, source_pin, prefix,
        contract=module.CONTRACT_V14, adjudicator_pin=adjudicator_pin)
    old_adjudication = module.pending_coverage_request(rows, source_pin, prefix, contract=module.CONTRACT_V13)
    assert adjudication[0] == module.ADJUDICATE_TASK_V14
    assert adjudication[1] == old_adjudication[1]
    assert adjudication[3].model_json_schema() == old_adjudication[3].model_json_schema()
    assert adjudication[2]['model_pin'] == adjudicator_pin
    assert adjudication[2]['classifier_model_pin'] == source_pin
    assert adjudication[2]['adjudication_binding_digest'] != old_adjudication[2]['adjudication_binding_digest']
    records = [*prefix, recorded_row(adjudication, {'patches': []}, 6)]
    selection = module.pending_coverage_request(rows, source_pin, records,
        contract=module.CONTRACT_V14, adjudicator_pin=adjudicator_pin)
    assert selection[0] == module.SELECT_TASK_V14
    assert selection[2]['model_pin'] == source_pin
    assert selection[2]['adjudicator_pin'] == adjudicator_pin
    records.append(recorded_row(selection, original[-1]['answer'], 7))
    result = module.evaluate_coverage(rows, source_pin, records,
        contract=module.CONTRACT_V14, adjudicator_pin=adjudicator_pin)
    assert result['state'] == 'accepted'
    assert result['classifier_contract'] == module.CONTRACT_V13
    assert result['model_pin'] == source_pin and result['adjudicator_pin'] == adjudicator_pin
    assert result['financial_validation'] == 'not_established'
    assert json.dumps(prefix, ensure_ascii=False) == frozen_prefix
    for fault in ('adjudicator_digest', 'classifier_digest', 'row_role', 'routing_role', 'legacy_adjudication'):
        altered = copy.deepcopy(records)
        changed_source, changed_adjudicator = source_pin, adjudicator_pin
        if fault == 'adjudicator_digest':
            changed_adjudicator = {**adjudicator_pin, 'digest': 'c' * 64}
        elif fault == 'classifier_digest':
            changed_source = {**source_pin, 'digest': 'd' * 64}
        elif fault == 'row_role':
            altered[5]['model'] = source_pin['name']
        elif fault == 'routing_role':
            altered[5]['routing']['model'] = source_pin['name']
        else:
            altered[5] = recorded_row(old_adjudication, {'patches': []}, 6)
        rejected = module.evaluate_coverage(rows, changed_source, altered,
            contract=module.CONTRACT_V14, adjudicator_pin=changed_adjudicator)
        assert rejected['state'] == 'blocked' and 'field_source_ids' not in rejected


def test_v14_role_required_and_old_contracts_reject_role_parameter():
    rows = sources(8)
    for operation in (module.frozen_coverage_requests, module.pending_coverage_request, module.evaluate_coverage):
        args = (rows, PIN) if operation == module.frozen_coverage_requests else (rows, PIN, [])
        for adjudicator in (None, {'name': 'qwen3:14b', 'digest': 'short'},
                            {'name': 'claude-pro-sonnet', 'digest': 'a' * 64}):
            with pytest.raises(ValueError):
                operation(*args, contract=module.CONTRACT_V14, adjudicator_pin=adjudicator)
        with pytest.raises(ValueError, match='only for coverage14'):
            operation(*args, contract=module.CONTRACT_V13, adjudicator_pin=PIN)


def test_v14_generic_role_plan_binds_stage_pins_without_changing_v13_classification_plan():
    from dataclasses import replace
    rows, source_pin, structures = module._inputs(sources(22), {'name': 'qwen3.5:9b', 'digest': 'b' * 64})
    old = module._adjudicated_plan_v12(rows, source_pin, structures, module.FINANCIAL_SCOPE,
                                     contract=module.CONTRACT_V13)
    plan = module._adjudicated_plan_v12(rows, source_pin, structures, module.FINANCIAL_SCOPE,
        contract=module.CONTRACT_V14, adjudicator_pin=PIN)
    assert plan.classification_plan == old.classification_plan
    assert plan.adjudicator_model_name == PIN['name'] and plan.selector_model_name == source_pin['name']
    batches = [{'batch_key': batch.key, 'results': [{'source_id': sid, 'classification': {}}
               for sid in batch.source_ids]} for batch in plan.classification_plan.batches]
    adjudication = {'inventory_digest': plan.classification_plan.inventory_digest,
                    'binding': plan.adjudication_binding, 'response_hash': 'e' * 64}
    selected = {'inventory_digest': plan.classification_plan.inventory_digest,
                'binding': plan.selection_binding, 'adjudication_response_hash': 'e' * 64,
                'selected_ids': ['S1', 'S2']}
    assert module.verify_role_adjudicated_traversal(plan, batches, adjudication, selected).selected_ids == ('S1', 'S2')
    with pytest.raises(ValueError):
        module.verify_role_adjudicated_traversal(replace(plan, adjudicator_model_digest='f' * 64),
                                               batches, adjudication, selected)
    with pytest.raises(ValueError):
        module.verify_role_adjudicated_traversal(plan, batches, adjudication,
                                               {**selected, 'adjudication_response_hash': 'f' * 64})


def complete_v15_records(rows, *, shard_patches=None):
    adjudicator = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    old = complete_v13_records(rows)
    prefix = copy.deepcopy(old[:len(module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V13))])
    attempts = prefix
    while True:
        request = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V15,
                                                  adjudicator_pin=adjudicator)
        if request is None:
            return attempts, adjudicator
        answer = ({'patches': (shard_patches or {}).get(request[2]['batch_id'], [])}
                  if request[2]['stage'] == 'source_adjudication' else old[-1]['answer'])
        attempts.append(recorded_row(request, answer, len(attempts) + 1))


def test_v15_shards_keep_exact_duplicates_and_block_impossible_fixed_partition():
    rows = sources(22)
    rows[9]['passage'] = rows[0]['passage']
    shards = module.frozen_adjudication_shards(rows)
    assert len(shards) == 5
    assert all(len(shard['source_ids']) <= 5 for shard in shards)
    assert sorted(sid for shard in shards for sid in shard['source_ids']) == sorted(row['id'] for row in rows)
    assert any({'S1', 'S10'} <= set(shard['source_ids']) for shard in shards)
    assert module.frozen_adjudication_shards(rows) == shards
    impossible = sources(24)
    for index, row in enumerate(impossible):
        row['passage'] = impossible[(index // 3) * 3]['passage']
    with pytest.raises(ValueError, match='cannot_fit_five_shards'):
        module.frozen_adjudication_shards(impossible)
    too_large = sources(6)
    for row in too_large:
        row['passage'] = too_large[0]['passage']
    with pytest.raises(ValueError, match='exceeds_shard_bound'):
        module.frozen_adjudication_shards(too_large)


def test_v15_exact_prefix_and_all_shards_bind_before_final_model_enum_selection():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    attempts, adjudicator = complete_v15_records(rows)
    assert len(attempts) == module.MAX_CALLS_V15
    old = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V13)
    fresh = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V15, adjudicator_pin=adjudicator)
    assert [(t, i, p, s.model_json_schema()) for t, i, p, s in old] == [
        (t, i, p, s.model_json_schema()) for t, i, p, s in fresh]
    shards = attempts[5:10]
    assert [row['input']['batch_id'] for row in shards] == [f'source_adjudication_{i}' for i in range(1, 6)]
    assert all(row['model'] == adjudicator['name'] for row in shards)
    assert all(row['input']['category_definitions'] == module.CATEGORY_DEFINITIONS_V4 for row in shards)
    retained = {source['id']: source['passage'] for row in shards for source in row['input']['sources']}
    assert retained == {row['id']: row['passage'] for row in rows}
    assert all(row['input']['options']['factual_sampling'] is True for row in attempts)
    partial = module.evaluate_coverage(rows, PIN, attempts[:9], contract=module.CONTRACT_V15, adjudicator_pin=adjudicator)
    assert partial['state'] == 'needs_call' and partial['batch_id'] == 'source_adjudication_5'
    assert partial['completed_adjudication_shards'] == [f'source_adjudication_{i}' for i in range(1, 5)]
    assert 'field_source_ids' not in partial
    result = module.evaluate_coverage(rows, PIN, attempts, contract=module.CONTRACT_V15, adjudicator_pin=adjudicator)
    assert result['state'] == 'accepted'
    assert result['field_source_ids'] == attempts[-1]['answer']
    assert result['source_adjudication'] == 'accepted' and result['adjudication_patch_count'] == 0
    assert result['financial_validation'] == 'not_established'
    for index in (5, 9):
        altered = copy.deepcopy(attempts)
        altered[index]['routing']['sampling']['presence_penalty'] = 1.5
        bad = module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V15, adjudicator_pin=adjudicator)
        assert bad['state'] == 'blocked' and 'field_source_ids' not in bad
    altered = copy.deepcopy(attempts)
    altered[5]['raw_response'] += ' '
    assert module.evaluate_coverage(rows, PIN, altered, contract=module.CONTRACT_V15,
                                    adjudicator_pin=adjudicator)['state'] == 'blocked'


def test_v15_patch_budget_is_shared_and_wrong_shard_evidence_cannot_be_admitted():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    old = complete_v13_records(rows)
    adjudicator = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    attempts = copy.deepcopy(old[:5])
    patches = []
    for shard_index in (1, 2):
        request = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V15,
                                                  adjudicator_pin=adjudicator)
        members = request[2]['required_source_ids'][:5 if shard_index == 1 else 3]
        answer = {'patches': []}
        for sid in members:
            original = next(record['answer'][sid] for record in old[:5] if sid in record['answer'])
            answer['patches'].append({'source_id': sid, 'kind': original['content_kind'],
                'use': original['disposition'], 'proof': original['kind_evidence_id'],
                'topics': original['category_support'], 'why': original['reason']})
        patches.extend(answer['patches'])
        attempts.append(recorded_row(request, answer, len(attempts) + 1))
    assert len(patches) == 8
    next_request = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V15,
                                                   adjudicator_pin=adjudicator)
    assert next_request[2]['remaining_global_patch_budget'] == 0
    assert next_request[3].model_json_schema()['properties']['patches']['maxItems'] == 0
    with pytest.raises(ValueError):
        recorded_row(next_request, {'patches': [patches[0]]}, len(attempts) + 1)
    fresh = module.pending_coverage_request(rows, PIN, old[:5], contract=module.CONTRACT_V15,
                                            adjudicator_pin=adjudicator)
    cross = copy.deepcopy(patches[0])
    cross['proof'] = 'S22.e001'
    bad_record = recorded_row(fresh, {'patches': [cross]}, 6)
    result = module.evaluate_coverage(rows, PIN, [*old[:5], bad_record], contract=module.CONTRACT_V15,
                                      adjudicator_pin=adjudicator)
    assert result['state'] == 'blocked'
    assert result['completed_adjudication_shards'] == []
    assert 'field_source_ids' not in result


def test_v15_empty_shards_require_no_fabricated_model_records():
    rows = sources(8)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    records, adjudicator = complete_v15_records(rows)
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V15, adjudicator_pin=adjudicator)
    assert result['state'] == 'accepted'
    assert result['empty_adjudication_shards'] == ['source_adjudication_3', 'source_adjudication_4', 'source_adjudication_5']
    assert result['completed_adjudication_shards'] == ['source_adjudication_1', 'source_adjudication_2']
    assert len(records) == 2 + 2 + 1


def synthetic_blind_answer(request, prefix, *, changed_ids=()):
    answer = {}
    for gid, group in request[2]['groups'].items():
        sid = group['members'][0]['source_id']
        old = next(record['answer'][sid] for record in prefix if sid in record['answer'])
        ordinal = lambda eid: 'E' + eid.split('.e')[1]
        answer[gid] = {'kind': old['content_kind'],
            'use': ('context_only' if old['disposition'] != 'context_only' else 'relevant')
                   if sid in changed_ids else old['disposition'],
            'proof': ordinal(old['kind_evidence_id']),
            'topics': {category: ordinal(eid) for category, eid in old['category_support'].items()},
            'why': 'Own source words support this assessment.'}
    return answer


def complete_v16_records(rows, *, contract=module.CONTRACT_V16):
    old = complete_v13_records(rows)
    adjudicator = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    attempts = copy.deepcopy(old[:len(module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V13))])
    prefix = copy.deepcopy(attempts)
    while True:
        request = module.pending_coverage_request(rows, PIN, attempts, contract=contract,
                                                  adjudicator_pin=adjudicator)
        if request is None:
            return attempts, adjudicator
        answer = synthetic_blind_answer(request, prefix) if request[2]['stage'] == 'source_adjudication' else old[-1]['answer']
        attempts.append(recorded_row(request, answer, len(attempts) + 1))


def test_v16_blind_required_group_judgment_projects_identical_recorded_values_to_every_member():
    rows, old_prefix, patch, _, fields = v11_duplicate_fixture()
    requests = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V13)
    prefix = [recorded_row(request, old_prefix[index]['answer'], index + 1)
              for index, request in enumerate(requests)]
    adjudicator = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    inherited = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V16, adjudicator_pin=adjudicator)
    assert [(t, i, p, s.model_json_schema()) for t, i, p, s in inherited] == [
        (t, i, p, s.model_json_schema()) for t, i, p, s in requests]
    attempts = list(prefix)
    while True:
        request = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V16,
                                                  adjudicator_pin=adjudicator)
        if request is None:
            break
        if request[2]['stage'] == 'source_adjudication':
            assert 'judgments' not in request[2] and 'conflict_inventory' not in request[2]
            assert request[3].model_json_schema()['required'] == request[2]['required_group_ids']
            assert {v['source_id'] for group in request[2]['groups'].values() for v in group['members']} == set(request[2]['required_source_ids'])
            answer = synthetic_blind_answer(request, prefix)
            if request[2]['shard_index'] == 1:
                duplicates = [group for group in request[2]['groups'].values()
                              if {item['source_id'] for item in group['members']} == {'S1', 'S10'}]
                assert len(duplicates) == 1 and duplicates[0]['passage'] == rows[0]['passage']
                assert {member['source_version'] for member in duplicates[0]['members']} == {rows[0]['version'], rows[9]['version']}
        else:
            answer = fields
        attempts.append(recorded_row(request, answer, len(attempts) + 1))
    result = module.evaluate_coverage(rows, PIN, attempts, contract=module.CONTRACT_V16, adjudicator_pin=adjudicator)
    assert result['state'] == 'accepted'
    assert result['judgments']['S1']['content_kind'] == result['judgments']['S10']['content_kind'] == 'information'
    assert result['judgments']['S1']['category_support'] == {'product_and_customers': 'S1.e001', 'market_and_competition': 'S1.e001'}
    assert result['judgments']['S10']['category_support'] == {'product_and_customers': 'S10.e001', 'market_and_competition': 'S10.e001'}
    assert result['changed_source_ids'] == ['S10'] and result['adjudication_patch_count'] == 1
    assert len(result['blind_group_assessments']) == 21 and len(result['reassessed_source_ids']) == 22
    assert result['financial_validation'] == 'not_established'


def test_v16_group_wire_own_quote_versions_and_receipts_remain_frozen():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    records, adjudicator = complete_v16_records(rows)
    result = module.evaluate_coverage(rows, PIN, records, contract=module.CONTRACT_V16, adjudicator_pin=adjudicator)
    assert result['state'] == 'accepted' and result['adjudication_patch_count'] == 0  # Reason-only changes do not count.
    first = module.pending_coverage_request(rows, PIN, records[:5], contract=module.CONTRACT_V16, adjudicator_pin=adjudicator)
    answer = synthetic_blind_answer(first, records[:5])
    with pytest.raises(ValueError):
        recorded_row(first, {key: value for key, value in answer.items() if key != next(iter(answer))}, 6)
    wrong_quote = copy.deepcopy(answer)
    wrong_quote[next(iter(answer))]['proof'] = 'E999'
    with pytest.raises(ValueError):
        recorded_row(first, wrong_quote, 6)
    for fault in ('member_version', 'member_offset', 'raw_answer', 'sampling', 'source_version'):
        altered, inputs = copy.deepcopy(records), copy.deepcopy(rows)
        group = next(iter(altered[5]['input']['groups'].values()))
        if fault == 'member_version':
            group['members'][0]['source_version'] = 'other-version'
        elif fault == 'member_offset':
            group['members'][0]['end'] -= 1
        elif fault == 'raw_answer':
            altered[5]['raw_response'] += ' '
        elif fault == 'sampling':
            altered[5]['routing']['sampling']['repeat_penalty'] = 1.5
        else:
            inputs[0]['version'] = 'other-version'
        rejected = module.evaluate_coverage(inputs, PIN, altered, contract=module.CONTRACT_V16, adjudicator_pin=adjudicator)
        assert rejected['state'] == 'blocked' and 'field_source_ids' not in rejected


def test_v16_changed_source_budget_is_global_and_excludes_reason_only():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    old = complete_v13_records(rows)
    adjudicator = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    attempts = copy.deepcopy(old[:5])
    for index in range(2):
        request = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V16,
                                                  adjudicator_pin=adjudicator)
        answer = synthetic_blind_answer(request, old[:5], changed_ids={f'S{i}' for i in range(1, 10)})
        attempts.append(recorded_row(request, answer, len(attempts) + 1))
    blocked = module.evaluate_coverage(rows, PIN, attempts, contract=module.CONTRACT_V16, adjudicator_pin=adjudicator)
    assert blocked['state'] == 'blocked' and 'eight-changed-source' in blocked['detail']
    assert blocked['changed_source_ids'] == ['S1', 'S2', 'S3', 'S4', 'S5']
    assert blocked['completed_adjudication_shards'] == ['source_adjudication_1']
    assert 'field_source_ids' not in blocked


def test_v17_topic_schema_offers_only_existing_capital_supported_ordinals_without_defaults():
    rows = sources(8)
    rows[1]['passage'] = ('Reported product channels. ' * 24) + '\nEquity raised and venture debt are reported here.'
    validated, pin, structures = module._inputs(rows, PIN)
    adjudicator = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    plan = module._blind_plan_v16(validated, pin, structures, module.FINANCIAL_SCOPE, adjudicator)
    shard = module.frozen_adjudication_shards(validated)[0]
    request = module._blind_shard_request_v16(validated, pin, structures, [], [], module.FINANCIAL_SCOPE,
        adjudicator, shard, plan, contract=module.CONTRACT_V17)
    schema = request[3].model_json_schema()
    ordinary = schema['$defs']['BlindTopicOptionsV17_G1']
    capital = schema['$defs']['BlindTopicOptionsV17_G2']
    assert ordinary['additionalProperties'] is False and not ordinary.get('required')
    assert set(ordinary['properties']) == set(module.CATEGORIES) - {'funding_and_ownership'}
    assert capital['properties']['funding_and_ownership']['const'] == 'E002'
    answer = {gid: {'kind': 'information', 'use': 'unresolved', 'proof': 'E001',
                   'topics': {}, 'why': 'The source meaning remains unresolved.'}
              for gid in request[2]['required_group_ids']}
    assert request[3].model_validate(answer).model_dump(mode='json') == answer
    for topics in ({'funding_and_ownership': 'E001'}, {'unoffered_category': 'E001'},
                   {'product_and_customers': None},
                   {key: 'E001' for key in ('identity', 'product_and_customers', 'market_and_competition',
                                            'team_and_governance', 'risks')}):
        with pytest.raises(ValueError):
            request[3].model_validate({**answer, 'G1': {**answer['G1'], 'topics': topics}})
    with pytest.raises(ValueError):
        request[3].model_validate({**answer, 'G2': {**answer['G2'], 'topics': {'funding_and_ownership': 'E001'}}})
    accepted = {**answer, 'G2': {**answer['G2'], 'topics': {'funding_and_ownership': 'E002'}}}
    assert request[3].model_validate(accepted).model_dump(mode='json') == accepted


def test_v17_complete_replay_keeps_v16_immutable_and_no_category_answer_is_inserted():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    original, adjudicator = complete_v16_records(rows)
    fresh, _ = complete_v16_records(rows, contract=module.CONTRACT_V17)
    assert original[:5] == fresh[:5]
    assert all(record['task'] == module.ADJUDICATE_TASK_V17 for record in fresh[5:10])
    assert module.evaluate_coverage(rows, PIN, fresh, contract=module.CONTRACT_V17,
                                    adjudicator_pin=adjudicator)['state'] == 'accepted'
    assert module.evaluate_coverage(rows, PIN, original, contract=module.CONTRACT_V16,
                                    adjudicator_pin=adjudicator)['state'] == 'accepted'
    borrowed = [*fresh[:5], *original[5:]]
    blocked = module.evaluate_coverage(rows, PIN, borrowed, contract=module.CONTRACT_V17, adjudicator_pin=adjudicator)
    assert blocked['state'] == 'blocked' and 'field_source_ids' not in blocked
    for record, previous in zip(fresh[5:10], original[5:10]):
        assert record['answer'] == previous['answer']
        assert 'judgments' not in record['input']


def synthetic_explicit_answer(request, synthetic_units):
    answer = {}
    for gid, group in request[2]['groups'].items():
        old = synthetic_units[group['members'][0]['source_id']]
        answer[gid] = {'kind': old['content_kind'], **{alias: (
            'E' + old['category_support'][category].split('.e')[1] if category in old['category_support']
            else 'N') for alias, category in request[2]['category_aliases'].items()},
            'use': old['disposition'], 'proof': 'E' + old['kind_evidence_id'].split('.e')[1],
            'why': 'Recorded synthetic source support.'}
    return answer


def test_v18_direct_required_statuses_replace_baseline_and_preserve_v17():
    rows = sources(22)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    old = complete_v13_records(rows)
    rows[9]['passage'] = rows[0]['passage']
    units = {sid: unit for record in old[:5] for sid, unit in record['answer'].items()}
    assessor = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    attempts = []
    while True:
        request = module.pending_coverage_request(rows, PIN, attempts, contract=module.CONTRACT_V18,
                                                  adjudicator_pin=assessor)
        if request is None:
            break
        answer = (synthetic_explicit_answer(request, units) if request[2]['stage'] == 'source_adjudication'
                  else old[-1]['answer'])
        attempts.append(recorded_row(request, answer, len(attempts) + 1))
    assert len(attempts) == 6
    assert all(record['task'] == module.ASSESS_TASK_V18 and record['model'] == assessor['name']
               for record in attempts[:5])
    assert attempts[-1]['task'] == module.SELECT_TASK_V18 and attempts[-1]['model'] == PIN['name']
    result = module.evaluate_coverage(rows, PIN, attempts, contract=module.CONTRACT_V18, adjudicator_pin=assessor)
    assert result['state'] == 'accepted' and result['classifier_contract'] == module.CONTRACT_V18
    assert result['judgments']['S10']['category_support'] == {'product_and_customers': 'S10.e001', 'market_and_competition': 'S10.e001'}
    assert 'adjudication_patches' not in result and 'changed_source_ids' not in result
    assert result['financial_validation'] == 'not_established'
    blocked = module.evaluate_coverage(rows, PIN, old[:5], contract=module.CONTRACT_V18, adjudicator_pin=assessor)
    assert blocked['state'] == 'blocked' and blocked['assessed_source_ids'] == []
    missing = module.evaluate_coverage(rows, PIN, attempts[:4], contract=module.CONTRACT_V18, adjudicator_pin=assessor)
    assert missing['state'] == 'needs_call' and missing['batch_id'] == 'source_adjudication_5'
    assert 'field_source_ids' not in missing


def test_v18_heading_branch_and_required_nonabsent_status_projection_fail_closed():
    rows = sources(8)
    rows[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    old = complete_v13_records(rows)
    units = {sid: unit for record in old[:2] for sid, unit in record['answer'].items()}
    assessor = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    request = module.frozen_coverage_requests(rows, PIN, contract=module.CONTRACT_V18, adjudicator_pin=assessor)[0]
    answer = synthetic_explicit_answer(request, units)
    changed = copy.deepcopy(answer)
    changed['G1']['kind'] = 'heading_only'
    with pytest.raises(ValueError):
        recorded_row(request, changed, 1)
    changed = copy.deepcopy(answer)
    changed['G1'].pop('C10')
    with pytest.raises(ValueError):
        recorded_row(request, changed, 1)
    changed = copy.deepcopy(answer)
    changed['G1']['C2'] = 'E001'
    with pytest.raises(ValueError):
        recorded_row(request, changed, 1)
    changed = copy.deepcopy(answer)
    for alias in ('C1', 'C3', 'C4', 'C5', 'C8'):
        changed['G1'][alias] = 'E001'
    bad = recorded_row(request, changed, 1)
    result = module.evaluate_coverage(rows, PIN, [bad], contract=module.CONTRACT_V18, adjudicator_pin=assessor)
    assert result['state'] == 'blocked' and 'too_many_recorded_present_topics' in result['detail']
    assert result['assessed_source_ids'] == []
    raw = recorded_row(request, answer, 1)
    raw['routing']['sampling']['presence_penalty'] = 1.5
    result = module.evaluate_coverage(rows, PIN, [raw], contract=module.CONTRACT_V18, adjudicator_pin=assessor)
    assert result['state'] == 'blocked' and 'field_source_ids' not in result
