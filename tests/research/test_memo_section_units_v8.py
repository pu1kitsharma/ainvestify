"""Nonnumeric prospective effects are hypotheses; premises and figures stay bound."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core
from agents.research.decision_components import validate_decision_components
from tests.research.test_memo_section_units_v5 import fixture, TEXTS, PIN
from tests.research.test_memo_section_units_v7 import RISK, DILIGENCE

EFFECT='future revenue and profitability could be limited, undermining the investment case; this is an unproved prospective effect rather than reported performance.'


def risk_answer():
    return {'units':{'S1':{'supporting_evidence_id':'S1.n001','status':'conditional_hypothesis',
        'failure_condition':RISK['failure_condition'],'prospective_consequence':EFFECT}}}


def test_v8_risk_unproved_nonnumeric_financial_effect_only_and_v7_strict_default():
    memo,sources=fixture()
    field,payload,schema=next(row for row in core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V8) if row[0]=='risks_and_countercase')
    answer=risk_answer()
    section=core._project_field(memo,field,payload,schema,answer)
    assert section.claims[0].assertion==RISK['failure_condition']+' '+EFFECT
    oldfield,oldpayload,oldschema=next(row for row in core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V7) if row[0]==field)
    with pytest.raises(ValueError,match='financial labels'):
        core._project_field(memo,oldfield,oldpayload,oldschema,answer)
    unit={key:answer['units']['S1'][key] for key in ('failure_condition','prospective_consequence')}
    with pytest.raises(ValueError,match='financial labels'):
        validate_decision_components('risk',unit,'Partner service description',180)
    assert validate_decision_components('risk',unit,'Partner service description',180,bind_financial_labels=False)==RISK['failure_condition']+' '+EFFECT
    with pytest.raises(ValueError,match='must be a bool'):
        validate_decision_components('risk',unit,'Partner service description',180,bind_financial_labels=0)
    assert 'do not introduce financial measures here' not in core.INSTRUCTION_V8
    assert 'NO numbers or dates' in core.INSTRUCTION_V8


def test_v8_rejects_numbers_dates_in_effect_and_unbound_failure_or_other_field_metrics():
    memo,sources=fixture()
    field,payload,schema=next(row for row in core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V8) if row[0]=='risks_and_countercase')
    for effect in (EFFECT.replace('limited','limited by 30%'),EFFECT.replace('limited','limited in November 2021'),EFFECT.replace('limited','limited in FY24')):
        answer=risk_answer(); answer['units']['S1']['prospective_consequence']=effect
        with pytest.raises(ValueError,match='nonnumeric and undated'):
            core._project_field(memo,field,payload,schema,answer)
    answer=risk_answer(); answer['units']['S1']['failure_condition']='If the reported service failed to maintain profitability and customer adoption,'
    with pytest.raises(ValueError,match='profit'):
        core._project_field(memo,field,payload,schema,answer)
    field,payload,schema=next(row for row in core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V8) if row[0]=='diligence_plan')
    answer={'units':{'S1':{'supporting_evidence_id':'S1.n001','status':'conditional_request',
        **DILIGENCE,'decision_relevance':'These records would help review prospective profitability and determine whether to continue further investment diligence.'}}}
    with pytest.raises(ValueError,match='profit'):
        core._project_field(memo,field,payload,schema,answer)


class Model:
    name=PIN['name']; thinking=False; max_tokens=600; context_tokens=8192; temperature=0; bound_strings=True
    def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
        assert task==core.TASK_V8 and instruction==core.INSTRUCTION_V8
        payload=json.loads(evidence); field=payload['field']
        status='conditional_hypothesis' if field=='differentiation_and_execution' else core.STATUSES[field][0]
        values={**RISK,'prospective_consequence':EFFECT} if field=='risks_and_countercase' else DILIGENCE if field=='diligence_plan' else {'decision_analysis':TEXTS[field]}
        obj={'units':{sid:{'supporting_evidence_id':next(iter(payload['sources'][sid]['spans'])),
            'status':status,**values} for sid in payload['unit_source_ids']}}
        self.last_response_text=json.dumps(obj); self.last_route={'model':self.name,**core.options_for(core.CONTRACT_V8)}
        return schema.model_validate(obj)


def test_five_field_v8_projection_and_exact_replay_preserve_sources_and_other_fields():
    memo,sources=fixture(); original=copy.deepcopy(sources)
    rows=[]; budget=PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in core.FIELDS:
        result=core.run_author(memo,sources,PIN,rows,lambda:None,Model(),budget,contract=core.CONTRACT_V8)
    assert result['state']=='accepted' and len(rows)==5
    assert result['memo']['risks_and_countercase']['claims'][0]['assertion']==RISK['failure_condition']+' '+EFFECT
    assert result['memo']['unknowns']==memo['unknowns'] and sources==original
    assert core.run_author(memo,sources,PIN,rows,lambda:None,None,SimpleNamespace(calls=0,max_calls=0),contract=core.CONTRACT_V8)==result
    assert core.decision_text(result['answer']['risks_and_countercase']['units']['S1'],core.CONTRACT_V8)==RISK['failure_condition']+' '+EFFECT
