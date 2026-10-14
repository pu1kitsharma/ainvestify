"""Risk/diligence components are local-authored and exactly projected, never filled."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core
from tests.research.test_memo_section_units_v5 import fixture, TEXTS, PIN

RISK={'failure_condition':'If the reported partner service failed to deliver a distinct customer proposition,',
      'prospective_consequence':'future adoption could fall short and undermine the investment case, an adverse hypothesis rather than an observed failure.'}
DILIGENCE={'requested_verification_records':'Request partner delivery records and customer adoption evidence for the reported service.',
           'decision_relevance':'Those records would inform whether the reported positioning and delivery capability justify further investment diligence.'}


class Model:
    name=PIN['name']; thinking=False; max_tokens=600; context_tokens=8192; temperature=0; bound_strings=True
    def __init__(self, short_risk=False): self.short_risk=short_risk
    def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
        assert task==core.TASK_V7
        payload=json.loads(evidence); field=payload['field']
        assert instruction==(core.RETRY_INSTRUCTION_V7 if payload.get('correction_number') else core.INSTRUCTION_V7)
        status='conditional_hypothesis' if field=='differentiation_and_execution' else core.STATUSES[field][0]
        fields=RISK if field=='risks_and_countercase' else DILIGENCE if field=='diligence_plan' else {'decision_analysis':TEXTS[field]}
        if self.short_risk and field=='risks_and_countercase' and not payload.get('correction_number'):
            fields={'failure_condition':'If the reported delivery process failed, uncertainty would remain.',
                    'prospective_consequence':'future adoption could fall below the hoped outcome.'}
        obj={'units':{sid:{'supporting_evidence_id':next(iter(payload['sources'][sid]['spans'])),
            'status':status,**fields} for sid in payload['unit_source_ids']}}
        self.last_response_text=json.dumps(obj); self.last_route={'model':self.name,**core.options_for(core.CONTRACT_V7)}
        return schema.model_validate(obj)


def test_v7_decomposition_schema_other_three_v6_and_exact_component_projection():
    memo,sources=fixture(); original=copy.deepcopy(memo)
    calls=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V7)
    for field,payload,schema in calls:
        unit=schema.model_fields['units'].annotation.model_fields['S1'].annotation
        expected={'failure_condition','prospective_consequence'} if field=='risks_and_countercase' else {'requested_verification_records','decision_relevance'} if field=='diligence_plan' else {'decision_analysis'}
        assert set(unit.model_fields)=={'supporting_evidence_id','status'}|expected
        for key in expected:
            assert unit.model_fields[key].metadata[1].max_length==(210 if len(expected)==2 else 420)
    rows=[]; budget=PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in range(6):
        record=core.run_author(memo,sources,PIN,rows,lambda:None,Model(short_risk=True),budget,contract=core.CONTRACT_V7)
        if record['state']=='accepted': break
    assert record['state']=='accepted' and len(rows)==6
    assert 'joined length' in rows[4]['input']['validation_error']
    for field in core.FIELDS:
        unit=record['answer'][field]['units']['S1']; text=core.decision_text(unit,core.CONTRACT_V7)
        assert record['memo'][field]['claims'][0]['assertion']==text
        assert record['memo'][field]['analysis']==text.rstrip('.!? ')+' [S1].'
    assert record['memo']['risks_and_countercase']['claims'][0]['assertion']==RISK['failure_condition']+' '+RISK['prospective_consequence']
    assert record['memo']['diligence_plan']['claims'][0]['assertion']==DILIGENCE['requested_verification_records']+' '+DILIGENCE['decision_relevance']
    assert memo==original and record['memo']['unknowns']==memo['unknowns']
    assert core.run_author(memo,sources,PIN,rows,lambda:None,None,SimpleNamespace(calls=0,max_calls=0),contract=core.CONTRACT_V7)==record
    old=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V6)
    assert all('decision_analysis' in schema.model_fields['units'].annotation.model_fields['S1'].annotation.model_fields for _,_,schema in old)


def test_v7_profitability_family_supplements_legacy_without_changing_v6():
    memo,sources=fixture()
    field,payload,schema=next(row for row in core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V7) if row[0]=='risks_and_countercase')
    obj={'units':{'S1':{'supporting_evidence_id':'S1.n001','status':'conditional_hypothesis',
        'failure_condition':RISK['failure_condition'],
        'prospective_consequence':'future profitability could weaken and undermine the investment case, an adverse hypothesis rather than an observed failure.'}}}
    with pytest.raises(ValueError,match='profit'): core._project_field(memo,field,payload,schema,obj)
    # V6's historic lexical binder remains unchanged; it does not recognize this inflection.
    core._metric_binding('Profitability could weaken.', 'Partner distribution description')
