"""A conditional status cannot bypass the explicit present-baseline judgment."""
import copy

from agents.research import memo_section_review as review


def example():
    payload = {'contract': review.CONTRACT_V5, 'field': 'risks_and_countercase',
               'units': {'S1': {'supporting_evidence_id': 'S1.n001',
                                'status': 'conditional_hypothesis'}}}
    answer = {'judgments': {'S1': {
        'evidence_id': 'S1.n001', 'status': 'conditional_hypothesis',
        'fulfills_field_purpose': True, 'preserves_source_attribution': True,
        'preserves_time_scope': True, 'has_unsupported_premise': False,
        'has_unsupported_metric': False, 'has_false_missing_data_claim': False,
        'reason': 'The future condition is explicitly unproved.',
        'asserts_existing_positive_state': False,
        'existing_positive_state_supported': False,
        'baseline_assessment': 'No existing positive baseline is asserted.'}}}
    return payload, answer


def test_conditional_status_with_unsupported_present_baseline_blocks():
    payload, answer = example()
    assert review._findings(payload, answer) == []
    defect = copy.deepcopy(answer)
    defect['judgments']['S1']['asserts_existing_positive_state'] = True
    findings = review._findings(payload, defect)
    assert [row['reason'] for row in findings] == ['unsupported_existing_positive_state']
    defect['judgments']['S1']['existing_positive_state_supported'] = True
    assert review._findings(payload, defect) == []


def test_baseline_assessment_must_be_substantive_and_old_judgments_are_unchanged():
    payload, answer = example()
    answer['judgments']['S1']['baseline_assessment'] = ' ' * 20
    assert review._findings(payload, answer)[0]['reason'] == 'baseline_assessment_too_short'
    payload['contract'] = review.CONTRACT_V4
    for key in ('baseline_assessment', 'asserts_existing_positive_state',
                'existing_positive_state_supported'):
        del answer['judgments']['S1'][key]
    assert review._findings(payload, answer) == []


def test_function_review_preserves_rejection_and_separates_source_status():
    payload, answer = example()
    payload['contract'] = review.CONTRACT_V7
    payload['field'] = 'diligence_plan'
    unit = payload['units']['S1']
    unit['declared_narrative_function'] = 'conditional_request'
    unit['source_verification_status'] = 'source_report_only'
    del unit['status']
    judgment = answer['judgments']['S1']
    del judgment['status']
    judgment['narrative_function'] = 'conditional_request'
    judgment['matches_declared_function'] = True
    assert review._findings(payload, answer) == []
    # The complete alternative enum remains available; an actually wrong
    # function and any failed semantic judgment still reject the narrative.
    judgment['narrative_function'] = 'source_reported'
    assert review._findings(payload, answer)[0]['reason'] == 'assertion_status_mismatch'
    judgment['narrative_function'] = 'conditional_request'
    judgment['matches_declared_function'] = False
    assert review._findings(payload, answer)[0]['reason'] == 'narrative_function_not_supported'
    judgment['matches_declared_function'] = True
    judgment['has_unsupported_premise'] = True
    assert review._findings(payload, answer)[0]['reason'] == 'has_unsupported_premise'


def test_future_effect_remains_unproved_and_numeric_forecasts_are_not_a_pass():
    payload, answer = example()
    payload['contract'] = review.CONTRACT_V6
    answer['judgments']['S1']['prospective_effect_is_unproved'] = False
    assert review._findings(payload, answer)[0]['reason'] == 'prospective_effect_not_unproved'
    answer['judgments']['S1']['prospective_effect_is_unproved'] = True
    assert review._findings(payload, answer) == []
