import pytest

from agents.preparation.preparation_review import missing_method_inputs


def audit(quote):
    return {'first': {'method': 'fee_reconciliation', 'negotiated_pricing_in_scope': True,
        'recognized_revenue_in_scope': True, 'requested_inputs': [
            {'role': 'transactions', 'request_quote': quote}]},
        'second': {'method': 'other', 'negotiated_pricing_in_scope': False,
                   'recognized_revenue_in_scope': False, 'requested_inputs': []}}


def test_tariff_comparison_cannot_pass_with_unrequested_contracts_or_accounting_inputs():
    request = 'Transaction-level billing records for an agreed period.'
    issues = missing_method_inputs(audit(request), {'first': {'records_to_request': request}, 'second': {'records_to_request': 'Other records'}})
    assert len(issues) == 1
    assert all(word in issues[0]['explanation'] for word in ('agreements', 'credit notes', 'revenue ledger', 'recognition policy'))


def test_reviewer_cannot_invent_input_quotes_or_mislabel_records():
    work = {'first': {'records_to_request': 'Transaction records for an agreed period.'}, 'second': {'records_to_request': 'Other records'}}
    with pytest.raises(ValueError, match='not in the actual'):
        missing_method_inputs(audit('Signed pricing agreements'), work)
    bad = audit(work['first']['records_to_request'])
    bad['first']['requested_inputs'][0]['role'] = 'pricing_agreements'
    with pytest.raises(ValueError, match='unsupported'):
        missing_method_inputs(bad, work)


def test_mentioning_a_transaction_set_does_not_request_underlying_records():
    request = 'Signed agreements covering merchants over the same transaction set.'
    issues = missing_method_inputs(audit(request), {'first': {'records_to_request': request}, 'second': {'records_to_request': 'Other records'}})
    assert 'individual transaction records' in issues[0]['explanation']


def test_complete_comparison_request_passes_without_writing_company_content():
    records = {'transactions': 'Individual transaction records', 'pricing_agreements': 'signed pricing agreements',
        'invoices_and_credits': 'invoices and credit notes', 'revenue_ledger': 'revenue ledger',
        'recognition_policy': 'revenue recognition policy'}
    request = ', '.join(records.values()) + ', same entity, period and currency.'
    value = audit(request)
    value['first']['requested_inputs'] = [{'role': role, 'request_quote': quote} for role, quote in records.items()]
    assert missing_method_inputs(value, {'first': {'records_to_request': request}, 'second': {'records_to_request': 'Other records'}}) == []
    value['first']['requested_inputs'][2]['request_quote'] = 'credit notes'
    assert missing_method_inputs(value, {'first': {'records_to_request': request}, 'second': {'records_to_request': 'Other records'}}) == []
    without_invoices = request.replace('invoices and ', '')
    issues = missing_method_inputs(value, {'first': {'records_to_request': without_invoices}, 'second': {'records_to_request': 'Other records'}})
    assert 'invoices and credit notes' in issues[0]['explanation']


def test_compound_ledger_and_policy_request_is_not_a_missing_policy():
    request = 'Individual transaction records, invoices and credits, signed pricing agreements, revenue ledger with recognition policy.'
    value = audit(request)
    value['first']['requested_inputs'] = [{'role': role, 'request_quote': quote} for role, quote in [
        ('transactions', 'Individual transaction records'), ('invoices_and_credits', 'invoices and credits'),
        ('pricing_agreements', 'signed pricing agreements'), ('revenue_ledger', 'revenue ledger with recognition policy')]]
    work = {'first': {'records_to_request': request}, 'second': {'records_to_request': 'Other records'}}
    assert missing_method_inputs(value, work) == []
    work['first']['records_to_request'] = request.replace('with recognition', 'without recognition')
    value['first']['requested_inputs'][-1]['request_quote'] = 'revenue ledger without recognition policy'
    assert 'recognition policy' in missing_method_inputs(value, work)[0]['explanation']


@pytest.mark.parametrize('statement', ['a consolidated profit-and-loss statement by entity and period',
    'income statements for the agreed reporting periods', 'the P&L and balance sheet'])
def test_summary_accounts_have_their_own_role_without_satisfying_underlying_records(statement):
    value = audit(statement)
    value['first'].update(method='other', requested_inputs=[{'role': 'financial_statements', 'request_quote': statement}])
    work = {'first': {'records_to_request': statement}, 'second': {'records_to_request': 'Other records'}}
    assert missing_method_inputs(value, work) == []
    value['first']['method'] = 'contribution_analysis'
    issue = missing_method_inputs(value, work)[0]['explanation']
    assert all(term in issue for term in ('earned-revenue ledger', 'attributable cost records', 'recognition policy'))
    value['first']['requested_inputs'][0]['role'] = 'revenue_ledger'
    with pytest.raises(ValueError, match='unsupported'):
        missing_method_inputs(value, work)


def test_arr_bridge_misclassification_and_bad_record_roles_are_corrected_together():
    first = 'Monthly ARR movements and acquisition-date balances for an agreed period.'
    second = 'Consolidated profit-and-loss statements by entity and reporting period.'
    value = audit(first)
    value['first'].update(method='cohort_comparison', requested_inputs=[{'role': 'other', 'request_quote': first}])
    value['second']['requested_inputs'] = [{'role': 'cost_records', 'request_quote': second}]
    work = {'first': {'records_to_request': first, 'action': 'Build an ARR bridge separating acquired balances from organic movements.'},
            'second': {'records_to_request': second, 'action': 'Review reported profit and loss trends.'}}
    with pytest.raises(ValueError) as error:
        missing_method_inputs(value, work)
    assert 'not a customer-cohort comparison' in str(error.value)
    assert 'cost_records is unsupported' in str(error.value)
    value['first']['method'] = 'other'
    value['second']['requested_inputs'][0]['role'] = 'financial_statements'
    assert missing_method_inputs(value, work) == []
