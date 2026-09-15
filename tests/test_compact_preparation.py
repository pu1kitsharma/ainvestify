from copy import deepcopy
from pathlib import Path
import json
import pytest
from agents.measurement_plan import CompactMeasurementPlan, DecisionMeasurementPlan
from agents.analyst_pack import CompactDiligencePair, expand_compact_requests
from tests.test_measurement_plan import contribution_plan, cohort_plan, quantity


def compact_plan(full):
    """Fixture projection only. Runtime never infers model operand meanings."""
    scope={k:full['left'][k] for k in ('entity','service','population','window','exposure')}
    operands={side:{k:full[side][k] for k in ('name','dimension','unit','record_needed','role','time_basis')} for side in ('left','right')}
    revenue=next((full[side] for side in ('left','right') if full[side]['role']=='recognized_revenue'),None)
    return dict(scope=scope,**operands,purpose=full['purpose'],operation=full['operation'],
        revenue_treatment=revenue['revenue_treatment'] if revenue else 'not_applicable',deducted_costs=revenue['deducted_costs'] if revenue else [],
        partner_charge_treatment=full['partner_charge_treatment'],fee_yield_basis=full.get('fee_yield_basis'))


@pytest.mark.parametrize('full',[contribution_plan(),cohort_plan(),contribution_plan(left=quantity(revenue_treatment='net',deducted_costs=['partner_charge']),partner_charge_treatment='already_deducted_from_revenue')])
def test_expansion_preserves_roles_units_records_scope_and_accounting(full):
    proposed=CompactMeasurementPlan(**compact_plan(full))
    expanded=proposed.expand(full['question'])
    original=DecisionMeasurementPlan(**full)
    assert expanded.left==original.left and expanded.right==original.right
    assert expanded.operation==original.operation
    assert expanded.expected_output==original.expected_output
    assert expanded.decision_text()==original.decision_text()
    assert len(json.dumps(proposed.model_dump()))<len(json.dumps(original.model_dump()))


@pytest.mark.parametrize('mutate,match',[
    (lambda p:p['left'].update(role='customer_assets',name='Customer assets',time_basis='point_stock',revenue_treatment='not_applicable'),'presentation|Economic roles'),
    (lambda p:p['right'].update(role='rate',dimension='ratio',unit='percent',time_basis='observation_window'),'unlike quantities'),
    (lambda p:p['right'].update(unit='USD'),'unlike quantities'),
    (lambda p:p.update(revenue_treatment='net',deducted_costs=['variable_service_cost']),'already included'),
    (lambda p:p.update(revenue_treatment='net',deducted_costs=['partner_charge']),'partner charges'),
    (lambda p:p.update(operation='divide'),'Economic roles'),
])
def test_compact_representation_cannot_bypass_existing_financial_guards(mutate,match):
    compact=compact_plan(contribution_plan());mutate(compact)
    with pytest.raises(ValueError,match=match):CompactMeasurementPlan(**compact).expand('Do retained fees cover matched service costs?')


def pair_data():
    return {'questions':[
        {'dimension':'unit_economics','question':'Do room fees cover attributable service costs?','fact_ids':['source'],'measurement':compact_plan(contribution_plan())},
        {'dimension':'customer_demand','question':'Do eligible guests make repeat paid bookings?','fact_ids':['source'],'measurement':compact_plan(cohort_plan())}]}


def test_pair_uses_current_citation_numbers_and_distinct_dimension_checks():
    facts=[{'id':'source','quote':'The company describes hotel rooms for business travelers.'}]
    data=pair_data()
    requests=expand_compact_requests(CompactDiligencePair(**data),facts)
    assert len(requests)==2 and all(r.decision.startswith('Decision unresolved') for r in requests)
    assert 'Booking receipts' in requests[0].records_to_request
    for mutation in (lambda p:p['questions'][1].update(dimension='unit_economics'),
                     lambda p:p['questions'][0].update(fact_ids=['invented']),
                     lambda p:p['questions'][0]['measurement']['left'].update(record_needed='The ledger shows reported revenue of 999 last month.'),
                     lambda p:p['questions'][0].update(dimension='delivery_capacity')):
        invalid=deepcopy(data);mutation(invalid)
        with pytest.raises(ValueError):expand_compact_requests(CompactDiligencePair(**invalid),facts)


def test_valid_fee_yield_retains_the_contract_basis_and_nonadverse_interpretation():
    full=contribution_plan(left=quantity('billed_fees',name='Service billings'),right=quantity('customer_assets',name='Average customer assets',time_basis='average_stock'),operation='divide',purpose='fee_yield',expected_output='period_fee_yield',
        fee_yield_basis={'agreement_record':'Fee agreement and period billing records','fee_period':'Latest six completed months','balance_period':'Latest six completed months','balance_method':'time_weighted_average','interpretation':'period_fee_yield_not_profitability'})
    expanded=CompactMeasurementPlan(**compact_plan(full)).expand('What effective fee yield is reconciled to the fee agreement?')
    assert expanded.fee_yield_basis.model_dump()==full['fee_yield_basis']
    assert 'not evidence of poor economics' in expanded.decision_text()


@pytest.mark.parametrize('invalid',[False,True])
def test_capability_gate_is_one_bounded_call_and_keeps_rejected_output(invalid):
    from scripts.evaluate_analyst_workflows import evaluate_compact_diligence
    from agents.preparation_budget import ACTIVE_BUDGET
    class Model:
        name='offline';last_call={};calls=0
        def generate(self,instruction,evidence,schema):
            self.calls+=1
            ACTIVE_BUDGET.get().start_request()
            payload=json.loads(evidence)
            assert payload['facts'][0]['quote']==case['evidence'][0]['quote']
            data=pair_data()
            if invalid:data['questions'][0]['measurement']['left']['role']='customer_assets'
            self.last_response_text=json.dumps(data)
            return schema.model_validate_json(self.last_response_text)
    case={'id':'fixture','company':'Hotels','website':'https://example.test',
          'evidence':[{'id':'source','quote':'The company describes hotel rooms for business travelers.',
                       'field':'offering','source_url':'https://example.test'}]}
    model=Model();report=evaluate_compact_diligence(case,model,max_seconds=120)
    assert model.calls==report['budget']['calls']==report['budget']['requests']==1
    assert report['budget']['max_seconds']==60
    assert report['raw_response']==model.last_response_text
    assert not report['live_data_updated'] and report['selected_model'] is None
    assert report['acceptance']['independent_audit_required']
    assert report['status']==('failed' if invalid else 'validated_awaiting_independent_audit')
    if invalid:
        assert report['error'] and 'requests' not in report
    else:
        assert len(report['requests'])==len(report['actions'])==2


@pytest.mark.parametrize('index,match',[(0,'Gross revenue'),(1,'measurement window')])
def test_each_retained_model_plan_is_rejected_without_repair(index,match):
    path=Path(__file__).resolve().parents[1]/'evals/investment_preparation/section-workflows/compact-diligence-gate/paasa_reference_test.json'
    report=json.loads(path.read_text())
    pair=CompactDiligencePair.model_validate_json(report['raw_response'])
    proposed=pair.questions[index]
    with pytest.raises(ValueError,match=match):proposed.measurement.expand(proposed.question)


@pytest.mark.parametrize('purpose,operation,left,right,output',[
    ('cash_reconciliation','subtract',quantity('billed_fees'),quantity('collected_cash'),'unreconciled_cash'),
    ('contribution_margin','divide',quantity('contribution_profit'),quantity(),'contribution_margin'),
    ('unit_cost','divide',quantity('variable_service_cost'),quantity('count',dimension='count',unit='stays',time_basis='observation_window'),'cost_per_unit'),
    ('cohort_comparison','compare',quantity('rate',dimension='ratio',unit='fraction',time_basis='observation_window'),quantity('rate',dimension='ratio',unit='fraction',time_basis='observation_window'),'observed_difference'),
    ('operating_comparison','subtract',quantity('operating_measure',dimension='energy',unit='kWh',time_basis='observation_window'),quantity('operating_measure',dimension='energy',unit='kWh',time_basis='observation_window'),'observed_difference'),
])
def test_other_supported_methods_preserve_operands_including_revenue_denominator(purpose,operation,left,right,output):
    full=contribution_plan(purpose=purpose,operation=operation,left=left,right=right,expected_output=output)
    proposed=CompactMeasurementPlan(**compact_plan(full)).expand(full['question'])
    canonical=DecisionMeasurementPlan(**full)
    assert proposed.left==canonical.left and proposed.right==canonical.right
    assert proposed.decision_text()==canonical.decision_text()


@pytest.mark.parametrize('bad_reference',[False,True])
def test_capability_cli_rejects_unreviewable_runs_before_model_initialization(tmp_path,monkeypatch,bad_reference):
    import sys
    from scripts import evaluate_analyst_workflows as evaluator
    source=tmp_path/'case.json';source.write_text(json.dumps([{'id':'fixture'}]))
    output=tmp_path/'original'
    argv=['evaluate','--cases',str(source),'--output',str(output),'--compact-diligence-only','--model','offline']
    if bad_reference:
        argv+=['--reference',str(tmp_path/'missing.md')]
    else:
        output.mkdir();(output/'answer.json').write_text('original answer')
    def unexpected_model(*args,**kwargs):pytest.fail('Must reject before initializing inference')
    monkeypatch.setattr(evaluator,'LocalModel',unexpected_model)
    monkeypatch.setattr(sys,'argv',argv)
    with pytest.raises(FileNotFoundError if bad_reference else FileExistsError):evaluator.main()
    if bad_reference:assert not output.exists()
    else:assert (output/'answer.json').read_text()=='original answer'
