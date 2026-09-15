from copy import deepcopy
import pytest
from agents.measurement_plan import DecisionMeasurementPlan


def quantity(role='recognized_revenue', **overrides):
    data = dict(name='Recognized room revenue', dimension='money', unit='INR',
                record_needed='Booking receipts and recognized revenue ledger, with refunds and settlement records.',
                role=role, entity='Investment target, identity to confirm', service='Room stays',
                population='Completed stays', window='Latest six completed months',
                time_basis='flow', exposure='Complete operating month',
                revenue_treatment='gross' if role=='recognized_revenue' else 'not_applicable', deducted_costs=[])
    data.update(overrides)
    return data


def contribution_plan(**overrides):
    data=dict(kind='measurement', question='Do paid stays cover their variable service costs?',
              left=quantity(), right=quantity('variable_service_cost', name='Room servicing cost',
                 record_needed='Room servicing invoices, staffing allocations and cancellation records for the same stays.'),
              operation='subtract', population_basis='Completed stays by room plan over matched operating months',
              purpose='contribution', expected_output='contribution_profit', partner_charge_treatment='not_applicable',
              population_relation='same_population',
              missing_inputs='request_records_and_defer_decision', inference_limit='descriptive_only_no_causal_claim')
    data.update(overrides)
    return data


def cohort_plan():
    return contribution_plan(left=quantity('count',name='Repeat guests',dimension='count',unit='guests',time_basis='observation_window',record_needed='Redacted booking events with first and repeat stays for equally exposed cohorts.'),
        right=quantity('count',name='Eligible guests',dimension='count',unit='guests',time_basis='observation_window',record_needed='Redacted account export with cohort membership and eligibility dates.'),
        operation='divide',purpose='cohort_rate',expected_output='cohort_rate',population_relation='numerator_subset_of_denominator')


@pytest.mark.parametrize('change,match',[
    ({'right':quantity('customer_assets',name='Customer assets',time_basis='point_stock')},'Economic roles'),
    ({'right':quantity('rate',name='Tariff',dimension='ratio',unit='percent',time_basis='observation_window')},'unlike quantities'),
    ({'left':quantity('transaction_volume',name='Gross merchandise value')},'Economic roles'),
    ({'left':quantity('collected_cash',name='Cash collected')},'Economic roles'),
    ({'right':quantity('fixed_expense',name='Fixed corporate expenses')},'Economic roles'),
    ({'expected_output':'period_fee_yield'},'Output'),
    ({'right':quantity('variable_service_cost',entity='Service partner')},'entity'),
    ({'right':quantity('variable_service_cost',service='Another plan')},'service'),
    ({'right':quantity('variable_service_cost',window='Previous operating year')},'window'),
    ({'right':quantity('variable_service_cost',unit='USD')},'unlike quantities'),
    ({'right':quantity('variable_service_cost',exposure='Partial operating month')},'exposure'),
    ({'left':quantity(revenue_treatment='net',deducted_costs=['variable_service_cost'])},'already included'),
    ({'left':quantity(revenue_treatment='net',deducted_costs=['partner_charge'])},'partner charges'),
])
def test_rejects_financially_invalid_plans(change,match):
    with pytest.raises(ValueError,match=match):DecisionMeasurementPlan(**contribution_plan(**change))


def test_gross_and_net_contribution_treatment_and_unresolved_results():
    gross=DecisionMeasurementPlan(**contribution_plan(partner_charge_treatment='included_in_cost_input'))
    net=DecisionMeasurementPlan(**contribution_plan(left=quantity(revenue_treatment='net',deducted_costs=['partner_charge']),partner_charge_treatment='already_deducted_from_revenue'))
    assert gross.expected_output==net.expected_output=='contribution_profit'
    assert 'Decision unresolved' in net.decision_text()
    assert 'zero denominators' in net.method()
    assert 'value' not in net.model_fields


def test_fee_yield_allowed_only_with_matched_contract_balance_and_period():
    data=contribution_plan(left=quantity('billed_fees',name='Billed service fees'),
        right=quantity('customer_assets',name='Time-weighted customer assets',time_basis='average_stock'),
        operation='divide',purpose='fee_yield',expected_output='period_fee_yield',
        fee_yield_basis={'agreement_record':'Service agreement and billing-basis reconciliation',
                         'fee_period':'Latest six completed months','balance_period':'Latest six completed months',
                         'balance_method':'time_weighted_average','interpretation':'period_fee_yield_not_profitability'})
    plan=DecisionMeasurementPlan(**data)
    assert 'not evidence of poor economics' in plan.decision_text()
    for mutate in (lambda d:d.update(operation='compare'),lambda d:d.update(fee_yield_basis=None),
                   lambda d:d['right'].update(time_basis='point_stock'),
                   lambda d:d['fee_yield_basis'].update(fee_period='Another period')):
        bad=deepcopy(data);mutate(bad)
        with pytest.raises(ValueError):DecisionMeasurementPlan(**bad)


def test_cohort_comparison_rejects_unequal_exposure_and_causal_conclusions():
    data=cohort_plan()
    DecisionMeasurementPlan(**data)
    data['right']['exposure']='Only first week available'
    with pytest.raises(ValueError,match='exposure'):DecisionMeasurementPlan(**data)
    data=cohort_plan();data['inference_limit']='currency depreciation caused churn'
    with pytest.raises(ValueError):DecisionMeasurementPlan(**data)


def test_generic_physical_measurements_remain_available():
    data=contribution_plan(left=quantity('operating_measure',name='Baseline energy',dimension='energy',unit='kWh',time_basis='observation_window'),
        right=quantity('operating_measure',name='Observed energy',dimension='energy',unit='kWh',time_basis='observation_window'),
        purpose='operating_comparison',expected_output='observed_difference')
    assert 'kWh' in DecisionMeasurementPlan(**data).display()
