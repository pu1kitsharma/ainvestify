"""Native claim-sized core units remain concise, source-bound and versioned."""
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core
from tests.research.test_memo_section_units import TEXT, PIN
from tests.research.test_memo_causal_review import sample

LONG_THESIS = (TEXT['investment_thesis'].rstrip('.') +
    '; the conditional investment mechanism would require confirmation through primary transaction records and a documented assessment before relying on reported capital.')
assert 300 < len(LONG_THESIS) <= 450


class Model:
    name=PIN['name']; thinking=False; max_tokens=600; context_tokens=8192; temperature=0
    def __init__(self, oversize=False): self.oversize,self.calls=oversize,0
    def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
        self.calls+=1
        assert task==core.TASK_V2
        payload=json.loads(evidence); field=payload['field']
        assert instruction==(core.RETRY_INSTRUCTION_V2 if payload.get('correction_number') else core.INSTRUCTION_V2)
        text=LONG_THESIS if field=='investment_thesis' else TEXT[field]
        if self.oversize and field=='investment_thesis' and not payload.get('correction_number'):
            text='X'*451
        obj={'units':{sid:{'supporting_evidence_id':next(iter(payload['sources'][sid]['spans'])),
            'status':core.STATUSES[field][0],'standalone_text':text} for sid in payload['unit_source_ids']}}
        self.last_response_text=json.dumps(obj); self.last_route={'model':self.name,**core.OPTIONS}
        return schema.model_validate(obj)


def run(model):
    memo,sources=sample(); rows=[]; budget=PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in range(6):
        result=core.run_author(memo,sources,PIN,rows,lambda:None,model,budget,contract=core.CONTRACT_V2)
        if result['state']=='accepted': return result,rows,memo,sources
    return result,rows,memo,sources


def test_native_claim450_schema_bound_and_legacy300_contract_preserved():
    memo,sources=sample()
    old=core.frozen_requests(memo,sources,PIN)
    new=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V2)
    answer={'units':{'S1':{'supporting_evidence_id':'S1.e001','status':'conditional_hypothesis','standalone_text':LONG_THESIS}}}
    with pytest.raises(ValueError): old[0][2].model_validate(answer)
    new[0][2].model_validate(answer)
    with pytest.raises(ValueError): new[0][2].model_validate({'units':{'S1':{**answer['units']['S1'],'standalone_text':'X'*451}}})
    assert '140–300 characters' in core.INSTRUCTION and '140–450 characters' in core.INSTRUCTION_V2
    assert '35–50 words' in core.INSTRUCTION_V2
    assert old[0][1]['contract']==core.CONTRACT_V1 and new[0][1]['contract']==core.CONTRACT_V2
    for field,_,schema in new:
        assert 'conditional' in json.dumps(schema.model_json_schema()) or field=='business_and_market'


def test_v2_native_claim_projection_exact_raw_replay_and_global_shape_correction():
    result,rows,memo,sources=run(Model(oversize=True))
    assert result['state']=='accepted' and result['contract']==core.CONTRACT_V2
    assert len(rows)==6 and rows[0]['failure_kind']=='schema_validation'
    assert '450' in rows[1]['input']['validation_error']
    assert result['memo']['investment_thesis']['claims'][0]['assertion']==LONG_THESIS
    assert result['memo']['unknowns']==memo['unknowns']
    assert result['memo']['recommendation_reason']==memo['recommendation_reason']
    assert core.run_author(memo,sources,PIN,rows,lambda:None,None,SimpleNamespace(calls=0,max_calls=0),contract=core.CONTRACT_V2)==result
    with pytest.raises(ValueError):
        core.run_author(memo,sources,PIN,rows,lambda:None,None,SimpleNamespace(calls=0,max_calls=0))
