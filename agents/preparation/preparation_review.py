"""Check declared analysis inputs against exact model-written record requests."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestedInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['transactions', 'pricing_agreements', 'invoices_and_credits',
                  'revenue_ledger', 'recognition_policy', 'cost_records', 'financial_statements', 'cohort_records', 'other'] = Field(description='financial_statements means summary accounts: profit-and-loss/P&L/income statements, balance sheets or cash-flow statements. These are NOT underlying revenue ledgers or attributable cost records. cost_records means actual cost/expense detail, not cost targets. Use other for public pricing, qualitative documents, ARR bridges and acquisition disclosures. pricing_agreements means actual negotiated contracts, not a pricing page. Label only what the exact requested span establishes.')
    request_quote: str = Field(min_length=5, max_length=450,
        description='Exact contiguous quote from records_to_request naming this input. Never quote the action, sources or another plan. Omit inputs not actually requested.')


class MethodInputs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    method: Literal['fee_reconciliation', 'contribution_analysis', 'cohort_comparison', 'other'] = Field(
        description='Classify the actual proposed calculation, not its topic. fee_reconciliation calculates expected fees and reconciles invoices/revenue. contribution_analysis deducts attributable costs from earned revenue. cohort_comparison compares outcomes for defined customer groups (such as retention). An ARR bridge separating acquired and organic movements is NOT a cohort comparison or contribution analysis: use other. Financial-statement trend review, integration milestones and qualitative document review are also other. Other still requires a substantive reasoning check; it does not waive method validity.')
    negotiated_pricing_in_scope: bool = Field(description='True when fee reconciliation includes custom/bespoke/negotiated arrangements; determine from the draft AND cited sources. Public tariffs alone cannot price those arrangements.')
    recognized_revenue_in_scope: bool = Field(description='True when the action compares or calculates recognized/earned revenue, rather than only reconciling invoices.')
    requested_inputs: list[RequestedInput] = Field(max_length=8)


class WorkInputAudit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    first: MethodInputs
    second: MethodInputs


INPUT_NAMES = {
    'transactions': 'individual transaction records with amounts and applied plan terms',
    'pricing_agreements': 'applicable signed pricing agreements and amendments',
    'invoices_and_credits': 'invoices and credit notes or refund adjustments',
    'revenue_ledger': 'the earned-revenue ledger',
    'recognition_policy': 'the revenue recognition policy and treatment of costs already deducted',
    'cost_records': 'underlying attributable cost records',
    'cohort_records': 'dated records for the comparable customer groups',
}


class ReviewInputError(ValueError):
    """The review's input annotation is invalid; correct the review, not prose."""

# These check the declared record role, not any company-specific fact or answer.
ROLE_WORDS = {
    'transactions': r'transaction|order|booking|sale',
    'pricing_agreements': r'contract|agreement|negotiated terms',
    'invoices_and_credits': r'invoic|bill|credit|refund|adjustment',
    'revenue_ledger': r'ledger|revenue (?:records?|journal|entries)',
    'recognition_policy': r'polic|recognition (?:rule|treatment)|accounting treatment',
    'cost_records': r'cost|expense|supplier invoic',
    'financial_statements': r'financial statements?|profit[ -]and[ -]loss|\bp\s*&\s*l\b|income statements?|balance sheets?|cash[ -]flow statements?',
    'cohort_records': r'cohort|customer|account|retention|churn',
}


def missing_method_inputs(audit, work):
    """Fail closed on unrequested inputs; return correction instructions only."""
    parsed = WorkInputAudit.model_validate(audit)
    issues = []
    annotation_errors = []
    for key, check in parsed.model_dump().items():
        request = work[key]['records_to_request']
        roles = set()
        for item in check['requested_inputs']:
            quote, role = item['request_quote'], item['role']
            if quote not in request:
                annotation_errors.append(f'{key}: quoted input {quote!r} is not in the actual record request. Use exact request spans only.')
                continue
            if role in ROLE_WORDS and not re.search(ROLE_WORDS[role], quote, re.I):
                annotation_errors.append(f'{key}: {role} is unsupported by its quoted request {quote!r}. Summary accounts use financial_statements; qualitative/ARR bridge records use other. Use the actual matching span; do not rewrite the company draft to justify a review label.')
                continue
            if role == 'invoices_and_credits' and not (
                    re.search(r'invoic|bill', request, re.I) and re.search(r'credit|refund|adjustment', request, re.I)):
                # The exact quoted span may name either part; both must be
                # explicitly present in this same underlying record request.
                continue
            if role == 'transactions' and not re.search(r'record|export|log|register|data|amount|detail', quote, re.I):
                # Mentioning the "same transaction set" is not a request for
                # the underlying transactions needed to calculate fees.
                continue
            roles.add(role)
            if role == 'revenue_ledger' and re.search(r'\brevenue ledger with (?:the )?(?:revenue )?recognition policy\b', quote, re.I):
                # One exact requested span can explicitly name two inputs.
                # Do not force a draft rewrite just because the reviewer
                # assigned only the ledger label to this compound request.
                roles.add('recognition_policy')
        required = set()
        if check['method'] == 'fee_reconciliation':
            required = {'transactions', 'invoices_and_credits'}
            if check['negotiated_pricing_in_scope']:
                required.add('pricing_agreements')
            if check['recognized_revenue_in_scope']:
                required.update(('revenue_ledger', 'recognition_policy'))
        elif check['method'] == 'contribution_analysis':
            required = {'revenue_ledger', 'cost_records', 'recognition_policy'}
        elif check['method'] == 'cohort_comparison':
            action = work[key].get('action', '')
            if re.search(r'\bARR\b|annual(?:ized)? recurring revenue', action, re.I) and not re.search(r'cohort|retention|churn|conversion|customer groups', action, re.I):
                annotation_errors.append(f'{key}: an ARR movement/acquisition bridge is not a customer-cohort comparison. Reclassify the actual action; do not request cohort records solely to satisfy a mistaken method label.')
                continue
            required = {'cohort_records'}
        missing = sorted(required - roles)
        if missing:
            issues.append({'section': 'diligence.request_' + ('a' if key == 'first' else 'b'),
                'field': 'records_to_request',
                'explanation': 'The proposed method also needs: ' + '; '.join(INPUT_NAMES[role] for role in missing) + '. Request them explicitly or narrow the analysis to the inputs requested.'})
    if annotation_errors:
        raise ReviewInputError('Invalid method_inputs annotations: ' + ' '.join(annotation_errors))
    return issues
