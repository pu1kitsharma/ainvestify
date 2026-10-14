"""Closed narrative source views bind exact lineage even for conditional metrics."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core
from tests.research.test_memo_section_units import PIN
from tests.research.test_memo_causal_review import sample

PASSAGE=('Provider category\nAlpha Company\nBeta Corporation\n'
         'The company reports operating a partner distribution service with limited overlap against incumbent offerings.\n'
         'Another provider category\nGamma Company\nPotential USD Mn\n2024 0.34 0.93')
TEXTS={
    'investment_thesis':'If the reported partner distribution service could deliver a distinct customer proposition, that mechanism could merit investment diligence, subject to independent evidence of adoption and repeatable delivery.',
    'business_and_market':'The company reports operating a partner distribution service and describes limited overlap against incumbent offerings; these are company-reported positioning statements rather than independent verification.',
    'differentiation_and_execution':'If the reported partner distribution service could be delivered consistently, that capability could support execution and differentiation, subject to independent evidence of operating performance and repeatability.',
    'risks_and_countercase':'If the reported partner distribution service failed to deliver a distinct customer proposition, incumbent alternatives could undermine adoption and weaken the investment case; this is an adverse hypothesis rather than an observed failure.',
    'diligence_plan':'Request partner delivery records and customer adoption evidence to verify the reported distribution service and overlap description; those records would inform whether its positioning supports further investment diligence.'}


def fixture():
    memo,sources=sample()
    sources[0]['passage']=PASSAGE
    for field in core.FIELDS:
        memo[field]['claims'][0]['quote']='The company reports operating a partner distribution service with limited overlap against incumbent offerings.'
    # Preserved recommendation remains source-bound rather than inherited fixture claims.
    memo['recommendation_reason']=TEXTS['business_and_market'].rstrip('.')+' [S1].'
    memo['recommendation_claims']=[{'source_id':'S1','quote':memo['business_and_market']['claims'][0]['quote'],'assertion':TEXTS['business_and_market']}]
    return memo,sources


class Model:
    name=PIN['name']; thinking=False; max_tokens=600; context_tokens=8192; temperature=0; bound_strings=True
    def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
        assert task==core.TASK_V5 and instruction==core.INSTRUCTION_V5
        payload=json.loads(evidence); field=payload['field']
        assert 'Alpha Company' not in evidence and 'Gamma Company' not in evidence and '0.34' not in evidence
        status='conditional_hypothesis' if field=='differentiation_and_execution' else core.STATUSES[field][0]
        obj={'units':{sid:{'supporting_evidence_id':next(iter(payload['sources'][sid]['spans'])),
            'status':status,'decision_analysis':TEXTS[field]} for sid in payload['unit_source_ids']}}
        self.last_response_text=json.dumps(obj); self.last_route={'model':self.name,**core.options_for(core.CONTRACT_V5)}
        return schema.model_validate(obj)


def test_closed_narrative_offers_projection_lineage_replay_and_original_unchanged():
    memo,sources=fixture(); original=copy.deepcopy(sources)
    calls=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V5)
    expected=core.frozen_offered_spans(sources,calls)
    for field,payload,schema in calls:
        assert all('.n' in eid for eid in payload['sources']['S1']['spans'])
        assert 'Alpha Company' not in json.dumps(payload)
        assert payload['sources']['S1']['version']==sources[0]['version']
    changed=[(field,copy.deepcopy(payload),schema) for field,payload,schema in calls]
    changed[0][1]['sources']['S1']['spans']['S1.n001']='Invented narrative replacement'
    with pytest.raises(ValueError,match='original source views'): core.frozen_offered_spans(sources,changed)
    rows=[]; budget=PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in core.FIELDS:
        result=core.run_author(memo,sources,PIN,rows,lambda:None,Model(),budget,contract=core.CONTRACT_V5)
    assert result['state']=='accepted' and result['offered_evidence_spans']==expected
    assert sources==original and '0.34 0.93' in sources[0]['passage']
    for field in core.FIELDS:
        claim=result['memo'][field]['claims'][0]
        assert claim['quote'] in PASSAGE and claim['assertion']==TEXTS[field]
    assert core.run_author(memo,sources,PIN,rows,lambda:None,None,SimpleNamespace(calls=0,max_calls=0),contract=core.CONTRACT_V5)==result


def test_conditional_metric_must_be_named_in_selected_narrative_and_v4_preserved():
    memo,sources=fixture()
    field,payload,schema=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V5)[0]
    obj={'units':{'S1':{'supporting_evidence_id':'S1.n001','status':'conditional_hypothesis',
        'decision_analysis':'If the reported partner distribution service produced stable revenue, its mechanism could merit investment diligence, subject to independent verification of delivery and demonstrated customer adoption.'}}}
    with pytest.raises(ValueError,match='Economic metric "revenue"'):
        core._project_field(memo,field,payload,schema,obj)
    old=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V4)
    assert 'Alpha Company' in json.dumps(old[0][1]) and '0.34' in json.dumps(old[0][1])
    assert core.options_for(core.CONTRACT_V5)['bound_strings'] is True


def test_v5_review_v4_uses_selected_fragment_only_and_recomputes_offset_lineage():
    from agents.research import memo_section_review as review
    from tests.research.test_memo_section_review import REVIEW_PIN
    memo,sources=fixture()
    sources[0]['passage']+='\nCategory Four\nWe offer additional operating compliance records for review.'
    calls=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V5)
    assert len(calls[0][1]['sources']['S1']['spans'])==2
    rows=[]; budget=PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in core.FIELDS:
        result=core.run_author(memo,sources,PIN,rows,lambda:None,Model(),budget,contract=core.CONTRACT_V5)
    requests=review.frozen_requests(memo,sources,result,PIN,REVIEW_PIN)
    assert all(payload['contract']==review.CONTRACT_V4 for _,payload,_ in requests)
    for _,payload,_ in requests:
        unit=payload['units']['S1']; eid=unit['supporting_evidence_id']
        assert set(unit['source_context'])==set(unit['eligible_evidence'])=={eid}
        assert 'additional operating compliance' not in json.dumps(payload)
        span=unit['eligible_evidence_lineage']
        assert span==result['offered_evidence_spans'][eid]
        assert span['exact_text']==sources[0]['passage'][span['start']:span['end']]
        assert span['exact_text']==unit['eligible_evidence'][eid]
    for tamper in ('projection','lineage'):
        changed=copy.deepcopy(result)
        if tamper=='projection': changed['memo']['business_and_market']['analysis']='Unsupported replacement body '*10
        else: changed['offered_evidence_spans']['S1.n001']['start']+=1
        with pytest.raises(ValueError): review.frozen_requests(memo,sources,changed,PIN,REVIEW_PIN)
