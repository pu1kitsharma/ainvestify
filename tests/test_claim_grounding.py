import json
from pathlib import Path
import pytest
from agents.claim_grounding import validate_numeric_claims
from agents.investment_case import WorkProduct


def document(**overrides):
    data=dict(title='Customer evidence memo',purpose='Decide whether customer-reported outcomes justify further preparation.',
              sections=[{'heading':'Reported evidence','content':'The company reports three pilot users; billing records are needed to distinguish a pilot from paid repeat demand.'}]*2,
              decision_question='Is customer value accompanied by repeat paid demand?',next_action='Request dated pilot invoices and delivery records.',completion_test='Reconcile receipts against delivery records, including cancellations.',missing_inputs=[])
    return WorkProduct(**{**data,**overrides})


def test_recorded_hallucinated_metrics_fail_before_model_review():
    case=json.loads(Path('evals/investment_preparation/reasoning-regression-input.json').read_text())
    bad=document(purpose='Waybill earns a 15% procurement fee from 300 active users.')
    with pytest.raises(ValueError,match='Unattributed numeric'):validate_numeric_claims(bad,case['payload'])


def test_exact_supported_claim_and_source_are_required():
    statement='The company reports 3 employees.'
    product=document(purpose=statement,numeric_claims=[dict(statement=statement,source_id='E1',quote='Team size: 3 employees.')])
    source={'sources':[dict(id='E1',field='team_size',quote='Team size: 3 employees.')]}
    validate_numeric_claims(product,source)
    product.numeric_claims[0].quote='Team size: 300 employees.'
    with pytest.raises(ValueError,match='exact quote'):validate_numeric_claims(product,source)


def test_founder_prior_employer_numbers_cannot_become_company_traction():
    statement='The company serves 400+ brands.'
    quote='At a previous employer, the founder served 400+ brands.'
    product=document(purpose=statement,numeric_claims=[dict(statement=statement,source_id='E1',quote=quote)])
    with pytest.raises(ValueError,match='Founder-history'):validate_numeric_claims(product,{'sources':[dict(id='E1',field='team',quote=quote)]})


def test_requested_source_ids_are_not_treated_as_observed_numbers():
    validate_numeric_claims(document(next_action='Request the company records referenced by E1.'),{'sources':[{'id':'E1','quote':'Observed company source'}]})
    with pytest.raises(ValueError,match='absent from the input'):
        validate_numeric_claims(document(next_action='Request the company records referenced by E13.'),{'sources':[]})


def test_proposed_measurements_do_not_invent_observed_results():
    product=document(measurements=[dict(question='Did delivery duration change?',left=dict(name='Baseline duration',dimension='duration',unit='hours',record_needed='Baseline timestamped workflow logs'),right=dict(name='Pilot duration',dimension='duration',unit='hours',record_needed='Pilot timestamped workflow logs'),operation='subtract',population_basis='Proposed matched workflows over 14 days')])
    validate_numeric_claims(product,{'sources':[]})


def test_retry_feedback_identifies_all_bad_fields_and_discards_unused_annotations():
    product=document(purpose='There are 300 active customers.',completion_test='Secure 3 introductions.',
                     numeric_claims=[dict(statement='The team has 3 employees.',source_id='E1',quote='Team size: 3 employees.')])
    with pytest.raises(ValueError) as failure:
        validate_numeric_claims(product,{'sources':[dict(id='E1',field='team_size',quote='Team size: 3 employees.')]})
    message=str(failure.value)
    assert 'purpose: 300' in message and 'completion_test: 3' in message
    assert not product.numeric_claims


def test_dead_numeric_metadata_cannot_block_or_be_exported_as_company_prose():
    product=document(numeric_claims=[dict(statement='The company has 999 customers.',source_id='E999',quote='A fabricated quote about 999 customers.')])
    validate_numeric_claims(product,{'sources':[]})
    assert product.numeric_claims==[]


def test_inline_citation_binds_real_numbers_without_duplicate_model_annotation():
    product=document(purpose='The company reports a team of 3 employees (E1).')
    validate_numeric_claims(product,{'sources':[dict(id='E1',field='team_size',quote='Team Size: 3')]})
    assert product.numeric_claims[0].statement==product.purpose
    assert product.numeric_claims[0].quote=='Team Size: 3'
    bad=document(purpose='The company reports 3 paying customers (E1).')
    with pytest.raises(ValueError,match='different business measure'):
        validate_numeric_claims(bad,{'sources':[dict(id='E1',field='team_size',quote='Team Size: 3')]})


def test_headcount_cannot_be_reused_as_customer_count():
    statement='The company reports 3 paying customers.'
    product=document(purpose=statement,numeric_claims=[dict(statement=statement,source_id='E1',quote='Team size: 3 employees.')])
    with pytest.raises(ValueError,match='different business measure'):
        validate_numeric_claims(product,{'sources':[dict(id='E1',field='team_size',quote='Team size: 3 employees.')]})


def test_recorded_reviewer_false_positive_is_rejected_before_llm_approval():
    from agents.claim_grounding import validate_outcome_claims
    draft=json.loads(Path('evals/investment_preparation/reasoning-engagement-results.json').read_text())['revised_draft']
    with pytest.raises(ValueError,match='Attribute the claimed benefit'):
        validate_outcome_claims(WorkProduct(**draft),{'sources':[]})


def test_reported_benefit_and_conditional_test_remain_usable():
    from agents.claim_grounding import validate_outcome_claims
    validate_outcome_claims(document(purpose='The company claims its product reduces errors; test this using matched order records.'),{'sources':[]})
    with pytest.raises(ValueError,match='revenue is unknown'):
        validate_outcome_claims(document(purpose='The company is pre-revenue and requires customer validation.'),{'sources':[]})
