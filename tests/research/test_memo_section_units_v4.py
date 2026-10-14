"""Decision-only units opt into bounded decoding without altering old replay."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core
from tests.research.test_memo_causal_review import sample
from tests.research.test_memo_section_units import TEXT, PIN

DECISIONS={**TEXT,'differentiation_and_execution':
    'If dated transaction records confirmed completion and available capital, that evidence could help assess whether the reported position supports execution, subject to independent review of the primary records.'}


class Model:
    name=PIN['name']; thinking=False; max_tokens=600; context_tokens=8192; temperature=0; bound_strings=True
    def __init__(self, oversize=False): self.oversize,self.calls=oversize,0
    def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
        self.calls+=1
        assert task==core.TASK_V4
        payload=json.loads(evidence); field=payload['field']
        assert instruction==(core.RETRY_INSTRUCTION_V4 if payload.get('correction_number') else core.INSTRUCTION_V4)
        status='conditional_hypothesis' if field=='differentiation_and_execution' else core.STATUSES[field][0]
        text=DECISIONS[field]
        if self.oversize and not payload.get('correction_number') and field=='investment_thesis': text='X'*421
        obj={'units':{sid:{'supporting_evidence_id':next(iter(payload['sources'][sid]['spans'])),
            'status':status,'decision_analysis':text} for sid in payload['unit_source_ids']}}
        self.last_response_text=json.dumps(obj); self.last_route={'model':self.name,**core.OPTIONS_V4}
        return schema.model_validate(obj)


def test_v4_single_decision_purpose_native_bounds_and_optin_only():
    memo,sources=sample()
    calls=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V4)
    for field,payload,schema in calls:
        unit=schema.model_fields['units'].annotation.model_fields['S1'].annotation
        assert set(unit.model_fields)=={'supporting_evidence_id','status','decision_analysis'}
        assert unit.model_fields['decision_analysis'].metadata[1].max_length==420
        assert payload['required_field_purpose']==core.PURPOSES_V4[field]
        assert 'analysis' not in payload and 'claims' not in payload
    assert core.options_for(core.CONTRACT_V4)=={**core.OPTIONS,'bound_strings':True}
    for old in (core.CONTRACT_V1,core.CONTRACT_V2,core.CONTRACT_V3):
        assert 'bound_strings' not in core.options_for(old)
    assert 'source_report' not in calls[0][2].model_fields['units'].annotation.model_fields['S1'].annotation.model_fields
    obj={'units':{'S1':{'supporting_evidence_id':'S1.e001','status':'conditional_hypothesis','decision_analysis':'X'*421}}}
    with pytest.raises(ValueError): calls[0][2].model_validate(obj)


def test_v4_exact_decision_projection_one_shared_correction_and_route_tamper():
    memo,sources=sample()
    for field in core.FIELDS: memo[field]['heading']='Unsupported company superiority'
    original=copy.deepcopy(memo); rows=[]; model=Model(oversize=True); budget=PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in range(6):
        record=core.run_author(memo,sources,PIN,rows,lambda:None,model,budget,contract=core.CONTRACT_V4)
        if record['state']=='accepted': break
    assert record['state']=='accepted' and len(rows)==model.calls==6
    assert rows[0]['failure_kind']=='schema_validation' and rows[1]['input']['correction_number']==1
    for field in core.FIELDS:
        unit=record['answer'][field]['units']['S1']
        assert record['memo'][field]['claims'][0]['assertion']==unit['decision_analysis']
        assert record['memo'][field]['claims'][0]['quote']==sources[0]['passage']
        assert record['memo'][field]['analysis']==unit['decision_analysis'].rstrip('.!? ')+' [S1].'
        assert record['memo'][field]['heading']==core.FIELD_LABELS[field]
    assert record['memo']['unknowns']==memo['unknowns'] and memo==original
    assert core.run_author(memo,sources,PIN,rows,lambda:None,None,SimpleNamespace(calls=0,max_calls=0),contract=core.CONTRACT_V4)==record
    tampered=copy.deepcopy(rows); tampered[0]['routing'].pop('bound_strings')
    with pytest.raises(ValueError,match='frozen contract'):
        core.run_author(memo,sources,PIN,tampered,lambda:None,None,SimpleNamespace(calls=0,max_calls=0),contract=core.CONTRACT_V4)
