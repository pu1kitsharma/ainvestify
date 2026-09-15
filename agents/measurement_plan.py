"""Validate proposed measurements symbolically; do not invent observed results."""
from typing import Literal, Union, Annotated
from pydantic import BaseModel, Field, model_validator

EXPECTED_OUTPUTS = {
    'contribution':'contribution_profit', 'fee_yield':'period_fee_yield',
    'cash_reconciliation':'unreconciled_cash', 'cohort_rate':'cohort_rate',
    'cohort_comparison':'observed_difference', 'operating_comparison':'observed_difference',
    'unit_cost':'cost_per_unit', 'contribution_margin':'contribution_margin',
}

class QuantityRecord(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    dimension: Literal['duration', 'money', 'count', 'ratio', 'mass', 'length', 'energy', 'power', 'volume', 'temperature']
    unit: str = Field(min_length=1, max_length=40, description='Explicit unit: e.g. hours, INR, customers, fraction. Use the same unit for like quantities.')
    record_needed: str = Field(min_length=5, max_length=600)

class MeasurementPlan(BaseModel):
    question: str = Field(min_length=5, max_length=300)
    left: QuantityRecord
    operation: Literal['subtract', 'divide', 'compare']
    right: QuantityRecord
    population_basis: str = Field(min_length=5, max_length=200, description='The comparable cohort, workflow and observation windows; a proposed scope, not an observed result.')

    @model_validator(mode='after')
    def compatible_quantities(self):
        if self.operation in {'subtract', 'compare'} and (self.left.dimension != self.right.dimension or self.left.unit.strip().casefold() != self.right.unit.strip().casefold()):
            raise ValueError('Cannot subtract or compare unlike quantities. Time, money, counts and retention are separate measures; first establish explicit compatible units.')
        if self.operation == 'divide' and self.left.dimension == self.right.dimension and self.left.unit.strip().casefold() != self.right.unit.strip().casefold():
            raise ValueError('Convert to the same unit before dividing like dimensions; never mix currencies or hours and minutes without an explicit conversion.')
        return self

    def display(self):
        symbol={'subtract':'−','divide':'÷','compare':'versus'}[self.operation]
        return f'{self.left.name} ({self.left.unit}) {symbol} {self.right.name} ({self.right.unit})'


class EconomicQuantity(QuantityRecord):
    """Proposed input definition, never an observed value or audited account."""
    role: Literal['customer_assets', 'transaction_volume', 'billed_fees', 'collected_cash',
                  'recognized_revenue', 'partner_charge', 'variable_service_cost',
                  'fixed_expense', 'contribution_profit', 'count', 'rate', 'operating_measure']
    entity: str = Field(min_length=3, max_length=140, description='Entity whose records are required. Use investment target, identity to confirm when unknown; never substitute partner accounts.')
    service: str = Field(min_length=3, max_length=100, description='Plan/product scope, or explicitly all services with a documented allocation.')
    population: str = Field(min_length=3, max_length=140, description='Comparable accounts, orders or eligible cohort; use identical definitions for both operands.')
    window: str = Field(min_length=3, max_length=100, description='Proposed reporting window; not a reported result.')
    time_basis: Literal['flow', 'average_stock', 'point_stock', 'observation_window']
    exposure: str = Field(min_length=3, max_length=100, description='Equal time at risk / cohort age / measurement duration for comparable observations.')
    revenue_treatment: Literal['gross', 'net', 'not_applicable']
    deducted_costs: list[Literal['partner_charge', 'variable_service_cost', 'fixed_expense']] = Field(max_length=3)

    @model_validator(mode='after')
    def role_matches_definition(self):
        financial = {'customer_assets','transaction_volume','billed_fees','collected_cash',
                     'recognized_revenue','partner_charge','variable_service_cost','fixed_expense','contribution_profit'}
        if self.role in financial and self.dimension != 'money':
            raise ValueError('Financial quantities require explicit currency units.')
        if self.role == 'customer_assets' and self.time_basis not in {'average_stock','point_stock'}:
            raise ValueError('Customer assets are a stock, not revenue or a cash flow.')
        if self.role in financial - {'customer_assets'} and self.time_basis != 'flow':
            raise ValueError('Income, costs and transaction volume require a flow period.')
        if self.role in {'count','rate'} and self.dimension != {'count':'count','rate':'ratio'}[self.role]:
            raise ValueError('Counts and rates need their corresponding dimensions.')
        if self.role in {'count','rate','operating_measure'} and self.time_basis != 'observation_window':
            raise ValueError('Operating observations require an explicit measurement window.')
        if self.role == 'recognized_revenue':
            if self.revenue_treatment == 'not_applicable':
                raise ValueError('Recognized revenue must specify gross/net presentation.')
            if self.revenue_treatment == 'gross' and self.deducted_costs:
                raise ValueError('Gross revenue cannot already have deducted costs.')
            if self.revenue_treatment == 'net' and not self.deducted_costs:
                raise ValueError('Net revenue must identify costs already deducted.')
        elif self.revenue_treatment != 'not_applicable' or self.deducted_costs:
            raise ValueError('Revenue presentation applies only to recognized revenue inputs.')
        return self


class FeeYieldBasis(BaseModel):
    agreement_record: str = Field(min_length=5, max_length=200)
    fee_period: str = Field(min_length=3, max_length=100)
    balance_period: str = Field(min_length=3, max_length=100)
    balance_method: Literal['time_weighted_average']
    interpretation: Literal['period_fee_yield_not_profitability']


class DecisionMeasurementPlan(MeasurementPlan):
    """Narrow supported methods with economic meaning, beyond unit matching.

    Unsupported methods must remain an unresolved request. This validates a
    proposal's declared definitions; it cannot verify model labels or records.
    """
    kind: Literal['measurement']
    left: EconomicQuantity
    right: EconomicQuantity
    purpose: Literal['contribution', 'fee_yield', 'cash_reconciliation', 'cohort_rate',
                     'cohort_comparison', 'operating_comparison', 'unit_cost', 'contribution_margin']
    expected_output: Literal['contribution_profit', 'period_fee_yield', 'unreconciled_cash',
                             'cohort_rate', 'observed_difference', 'cost_per_unit', 'contribution_margin']
    population_relation: Literal['same_population', 'numerator_subset_of_denominator']
    partner_charge_treatment: Literal['not_applicable', 'included_in_cost_input', 'already_deducted_from_revenue']
    fee_yield_basis: Union[FeeYieldBasis, None] = None
    missing_inputs: Literal['request_records_and_defer_decision']
    inference_limit: Literal['descriptive_only_no_causal_claim']

    @model_validator(mode='after')
    def economically_compatible(self):
        left, right = self.left, self.right
        if self.expected_output != EXPECTED_OUTPUTS[self.purpose]:
            raise ValueError('Output must reflect the calculation: revenue/assets are not profit.')
        for field in ('entity','service','population','exposure'):
            if getattr(left,field).strip().casefold() != getattr(right,field).strip().casefold():
                raise ValueError(f'Align {field} for both inputs before proposing a comparison.')
        if self.purpose not in {'cohort_comparison','operating_comparison'} and left.window.casefold() != right.window.casefold():
            raise ValueError('Align the flow/stock reporting window for both inputs.')
        roles = (left.role,right.role)
        if (self.population_relation == 'numerator_subset_of_denominator') != (self.purpose == 'cohort_rate'):
            raise ValueError('Cohort rates require an eligible denominator containing the numerator; other methods require the same population.')
        valid = False
        if self.purpose == 'contribution':
            valid = self.operation == 'subtract' and roles == ('recognized_revenue','variable_service_cost')
            if right.role in left.deducted_costs:
                raise ValueError('Do not deduct a cost already included in net revenue.')
            deducted = 'partner_charge' in left.deducted_costs
            if deducted != (self.partner_charge_treatment == 'already_deducted_from_revenue'):
                raise ValueError('Reconcile partner charges exactly once: in costs or already deducted from revenue.')
        elif self.purpose == 'fee_yield':
            valid = self.operation == 'divide' and left.role in {'billed_fees','collected_cash','recognized_revenue'} and right.role == 'customer_assets'
            basis = self.fee_yield_basis
            if not basis or right.time_basis != 'average_stock' or basis.fee_period != left.window or basis.balance_period != right.window:
                raise ValueError('Fee yield requires matched periods, a time-weighted asset balance and the fee agreement; small fees relative to assets are not an adverse result.')
        elif self.purpose == 'cash_reconciliation':
            valid = self.operation == 'subtract' and roles == ('billed_fees','collected_cash')
        elif self.purpose == 'cohort_rate':
            valid = self.operation == 'divide' and roles == ('count','count') and left.unit.casefold() == right.unit.casefold()
        elif self.purpose == 'cohort_comparison':
            valid = self.operation == 'compare' and roles == ('rate','rate')
        elif self.purpose == 'operating_comparison':
            valid = self.operation in {'compare','subtract'} and roles == ('operating_measure','operating_measure') and left.dimension != 'money'
        elif self.purpose == 'unit_cost':
            valid = self.operation == 'divide' and roles == ('variable_service_cost','count')
        elif self.purpose == 'contribution_margin':
            valid = self.operation == 'divide' and roles == ('contribution_profit','recognized_revenue')
        if not valid:
            raise ValueError('Economic roles do not support this operation and decision purpose. Fees versus assets, revenue as profit and currency versus tariffs are not valid adverse tests.')
        if self.purpose != 'fee_yield' and self.fee_yield_basis is not None:
            raise ValueError('Fee basis is applicable only to a fee-yield calculation.')
        return self

    def records(self):
        rows = [self.left.record_needed, self.right.record_needed]
        if self.fee_yield_basis: rows.append(self.fee_yield_basis.agreement_record)
        return '; '.join(dict.fromkeys(rows))

    def method(self):
        return f'{self.display()}. Scope: {self.left.entity}; {self.left.service}; {self.population_basis}. Align records to {self.left.window}; exposure: {self.left.exposure}. Check definitions and reconcile inputs before calculating; leave missing inputs and zero denominators unresolved.'

    def deliverable(self):
        unit = ('fraction' if self.left.dimension==self.right.dimension else self.left.unit+'/'+self.right.unit) if self.operation=='divide' else self.left.unit
        return 'A source-linked ' + self.expected_output.replace('_',' ') + f' table ({unit}) with input reconciliation, definitions and unresolved differences.'

    def decision_text(self):
        decisions = {
            'contribution':'Use reconciled contribution to investigate loss-making services and choose pricing or delivery-cost work before an expansion recommendation. Observed losses alone do not establish future viability.',
            'fee_yield':'Use the period fee yield to investigate billing or contractual differences. Fees being smaller than customer assets is not evidence of poor economics; assess costs separately.',
            'cash_reconciliation':'Investigate timing, refunds, taxes and unsettled balances before interpreting differences as missing cash or revenue.',
            'cohort_rate':'Use measured customer participation to select the next activation or retention investigation; set an experiment threshold from an observed baseline.',
            'cohort_comparison':'Use equally exposed cohorts to identify a segment for investigation. Behavioral records establish differences, not reasons for churn.',
            'operating_comparison':'Use the comparable operating observations to identify a performance gap for investigation; define an acceptable threshold before recommending expansion.',
            'unit_cost':'Use matched service costs per delivered unit to identify a cost investigation. This alone does not establish profitability.',
            'contribution_margin':'Investigate segments with weak contribution margin before recommending expansion; reconcile revenue presentation and cost allocation first.'}
        return 'Decision unresolved until the requested records and definitions are checked. ' + decisions[self.purpose]


class RecordReviewPlan(BaseModel):
    kind: Literal['record_review']
    question: str = Field(min_length=5,max_length=200)
    records_needed: str = Field(min_length=15,max_length=600)
    review_scope: str = Field(min_length=15,max_length=600, description='Specific rights, responsibilities or qualitative customer feedback to establish. No calculations or causal conclusions.')
    missing_inputs: Literal['request_records_and_defer_decision']
    inference_limit: Literal['descriptive_only_no_causal_claim']

    def records(self): return self.records_needed
    def method(self): return 'Review the requested records for: ' + self.review_scope
    def deliverable(self): return 'A source-linked record review with documented responsibilities, observations and unresolved questions.'
    def decision_text(self): return 'Decision unresolved until the requested records are reviewed. Resolve material gaps or inconsistencies before recommending further work; this review establishes neither financial performance nor causation.'


AnalysisPlan = Annotated[Union[DecisionMeasurementPlan, RecordReviewPlan], Field(discriminator='kind')]


class MeasurementScope(BaseModel):
    """A proposed common scope, declared once rather than twice per operand."""
    entity: str = Field(min_length=3, max_length=100, description='Whose accounts; identify the investment entity to confirm if unknown. Never combine partner accounts with the target.')
    service: str = Field(min_length=3, max_length=100, description='Service/plan being tested; explicit per-plan analysis is allowed.')
    population: str = Field(min_length=3, max_length=100, description='Same eligible accounts/orders/cohorts; a rate numerator must be a subset of its denominator.')
    window: str = Field(min_length=3, max_length=80, description='Requested reporting period, not an observed result.')
    exposure: str = Field(min_length=3, max_length=80, description='Equal observation duration or cohort age. Do not compare immature with mature cohorts.')


class CompactQuantity(QuantityRecord):
    role: EconomicQuantity.model_fields['role'].annotation
    time_basis: EconomicQuantity.model_fields['time_basis'].annotation
    record_needed: str = Field(min_length=15, max_length=200, description='Underlying export/document and essential fields. Request raw records, not a precomputed ratio. Use redacted account/order keys.')


class CompactMeasurementPlan(BaseModel):
    """Small inference contract; expansion must pass the full semantic validator.

    Only constants and the declared shared scope are expanded. Operand roles,
    units, time bases and records remain model choices and are never corrected
    by inferring their meaning from a selected purpose.
    """
    purpose: DecisionMeasurementPlan.model_fields['purpose'].annotation
    scope: MeasurementScope
    left: CompactQuantity
    operation: MeasurementPlan.model_fields['operation'].annotation
    right: CompactQuantity
    revenue_treatment: EconomicQuantity.model_fields['revenue_treatment'].annotation
    deducted_costs: EconomicQuantity.model_fields['deducted_costs'].annotation = Field(max_length=3, description='Costs already deducted from the recognized-revenue input, otherwise empty. Never deduct them again.')
    partner_charge_treatment: DecisionMeasurementPlan.model_fields['partner_charge_treatment'].annotation
    fee_yield_basis: Union[FeeYieldBasis, None] = None

    def expand(self, question):
        has_revenue=any(q.role=='recognized_revenue' for q in (self.left,self.right))
        if not has_revenue and (self.revenue_treatment!='not_applicable' or self.deducted_costs):
            raise ValueError('Revenue presentation requires a recognized-revenue operand; it cannot be silently discarded.')
        def quantity(operand):
            revenue=operand.role=='recognized_revenue'
            return EconomicQuantity(**operand.model_dump(),**self.scope.model_dump(),
                revenue_treatment=self.revenue_treatment if revenue else 'not_applicable',
                deducted_costs=self.deducted_costs if revenue else [])
        return DecisionMeasurementPlan(
            kind='measurement',question=question,left=quantity(self.left),operation=self.operation,right=quantity(self.right),
            population_basis=self.scope.population+'; '+self.scope.exposure,
            purpose=self.purpose,expected_output=EXPECTED_OUTPUTS[self.purpose],
            population_relation='numerator_subset_of_denominator' if self.purpose=='cohort_rate' else 'same_population',
            partner_charge_treatment=self.partner_charge_treatment,fee_yield_basis=self.fee_yield_basis,
            missing_inputs='request_records_and_defer_decision',inference_limit='descriptive_only_no_causal_claim')


def contribution_method(service):
    """A requested reconciliation method, never the company's reported accounts.

    Normalize partner treatment before computing contribution; do not ask the
    model to invent mutually dependent accounting and arithmetic fields.
    """
    common=dict(entity='Investment target, legal identity and contracting entities to confirm',
                service=service,population='Eligible service accounts, separated by plan and operating month',
                window='Latest six completed months',exposure='Complete operating month')
    left=EconomicQuantity(name='Recognized service revenue after partner charges, if applicable',
        dimension='money',unit='reconciled reporting currency',role='recognized_revenue',time_basis='flow',
        record_needed='Entity chart and service/fee-sharing agreements; redacted invoices, credit notes, revenue ledger, collection and partner-settlement statements. Include entity, plan, account key, month, currency, refunds and taxes. Reconcile recognition and gross/net presentation; identify any partner charges already deducted and normalize them exactly once. Exclude customer principal, assets and pass-through taxes from revenue.',
        revenue_treatment='net',deducted_costs=['partner_charge'],**common)
    right=EconomicQuantity(name='Attributable variable service costs excluding partner charges already deducted',
        dimension='money',unit=left.unit,role='variable_service_cost',time_basis='flow',
        record_needed='Supplier invoices, direct service/support cost records and staff-time allocations for the same entity, plans, accounts and months. Include currency, expense category, allocation basis and one-off versus ongoing service cost. Exclude fixed corporate overhead and partner charges already deducted from the reconciled revenue input. Request missing records; do not estimate them from public tariffs.',
        revenue_treatment='not_applicable',deducted_costs=[],**common)
    return DecisionMeasurementPlan(kind='measurement',question=f'What income does the investment entity retain from {service}, and does it cover attributable variable service costs?',
        left=left,right=right,operation='subtract',population_basis=common['population'],purpose='contribution',
        expected_output='contribution_profit',population_relation='same_population',
        partner_charge_treatment='already_deducted_from_revenue',missing_inputs='request_records_and_defer_decision',
        inference_limit='descriptive_only_no_causal_claim')


def customer_method(method, service, event):
    """Count unique customers with equal exposure, never events/customers.

    The chosen event defines an observable behavior. No event rate is rendered
    as satisfaction, problem resolution, causal impact or willingness to pay.
    """
    if method not in {'activation','repeat_use','retention'}:raise ValueError('Unsupported customer method.')
    if method=='activation':
        question=f'What proportion of eligible new {service} customers record {event.removeprefix("recorded ")} within the requested observation window?'
        left_name='Customers completing the specified activation event'
        right_name='Eligible newly registered customers with complete follow-up'
        eligibility='Cohort entry is registration; document eligibility exclusions before counting.'
        criterion=f'Count each eligible customer once if {event} occurs after registration within follow-up.'
    elif method=='repeat_use':
        question=f'What proportion of {service} customers record another {event} after their first event within equal follow-up?'
        left_name='Customers completing a subsequent qualifying event'
        right_name='Customers with a first qualifying event and complete follow-up'
        eligibility=f'Cohort entry is the first {event}; exclude customers without full follow-up.'
        criterion=f'Count each eligible customer once if a subsequent {event} occurs within follow-up; exclude the entry event.'
    else:
        question=f'What proportion of newly enrolled {service} customers remain enrolled at the end of equal follow-up?'
        left_name='Customers still enrolled at the end of follow-up'
        right_name='Newly enrolled customers with complete follow-up'
        eligibility='Cohort entry is enrollment; exclude customers without full follow-up.'
        criterion='Count each eligible customer once if enrollment remains active at the end of follow-up. Separate cancellations, pauses and missing status.'
    common=dict(entity='Investment target, legal identity and service operator to confirm',service=service,
                population='Same eligible customer cohort, grouped by entry month and service plan',
                window='Latest six completed months',exposure='First ninety days after cohort entry; exclude immature accounts',
                role='count',dimension='count',unit='unique customers',time_basis='observation_window',
                revenue_treatment='not_applicable',deducted_costs=[])
    left=EconomicQuantity(name=left_name,record_needed='Redacted account-event export with stable customer key, event type, event timestamp, plan and completion/cancellation status. '+criterion+' Link to the eligible cohort file; missing event coverage is unresolved, not a negative outcome.',**common)
    right=EconomicQuantity(name=right_name,record_needed='Redacted customer/cohort export with stable customer key, registration/enrollment/first-event date, plan, eligibility flags and data cutoff. '+eligibility+' Use the same cohort and customer keys as the event export; retain only fully observed customers.',**common)
    return DecisionMeasurementPlan(kind='measurement',question=question,left=left,right=right,operation='divide',
        population_basis=common['population'],purpose='cohort_rate',expected_output='cohort_rate',
        population_relation='numerator_subset_of_denominator',partner_charge_treatment='not_applicable',
        missing_inputs='request_records_and_defer_decision',inference_limit='descriptive_only_no_causal_claim')
