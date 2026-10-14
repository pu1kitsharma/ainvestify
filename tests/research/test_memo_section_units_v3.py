"""Structured company report and decision reasoning project separate raw strings."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core
from tests.research.test_memo_causal_review import sample
from tests.research.test_memo_section_units import TEXT, PIN

REPORT = 'The registry reports uncertain transaction completion and does not state current cash availability.'
DECISIONS = {**TEXT,
    'differentiation_and_execution': 'If dated transaction records confirmed completion and available capital, that evidence would help assess whether the reported position could support execution.'}


class Model:
    name=PIN['name']; thinking=False; max_tokens=600; context_tokens=8192; temperature=0
    def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
        assert task==core.TASK_V3 and instruction==core.INSTRUCTION_V3
        payload=json.loads(evidence); field=payload['field']
        status='conditional_hypothesis' if field=='differentiation_and_execution' else core.STATUSES[field][0]
        obj={'units':{sid:{'supporting_evidence_id':next(iter(payload['sources'][sid]['spans'])),
            'status':status,'source_report':REPORT,'decision_analysis':DECISIONS[field]} for sid in payload['unit_source_ids']}}
        self.last_response_text=json.dumps(obj); self.last_route={'model':self.name,**core.OPTIONS}
        return schema.model_validate(obj)


def test_v3_structure_purpose_typed_status_and_legacy_single_text_schemas_preserved():
    memo,sources=sample()
    v1=core.frozen_requests(memo,sources,PIN)
    v2=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V2)
    v3=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V3)
    for _,_,schema in v1+v2:
        assert 'standalone_text' in json.dumps(schema.model_json_schema())
        assert 'source_report' not in schema.model_fields['units'].annotation.model_fields['S1'].annotation.model_fields
    for field,payload,schema in v3:
        text=json.dumps(payload)
        assert 'analysis' not in payload and 'prior' not in text
        assert 'source_cards' not in payload
        unit_schema=schema.model_fields['units'].annotation.model_fields['S1'].annotation
        assert set(unit_schema.model_fields)=={'supporting_evidence_id','status','source_report','decision_analysis'}
        assert unit_schema.model_fields['source_report'].metadata[1].max_length==180
        assert unit_schema.model_fields['decision_analysis'].metadata[1].max_length==240
    _,_,schema=next(row for row in v3 if row[0]=='differentiation_and_execution')
    with pytest.raises(ValueError):
        schema.model_validate({'units':{'S1':{'supporting_evidence_id':'S1.e001','status':'source_reported',
            'source_report':REPORT,'decision_analysis':DECISIONS['differentiation_and_execution']}}})
    assert 'Do not expand an acronym' in core.INSTRUCTION_V3
    assert 'position or proximity' in core.INSTRUCTION_V3
    assert 'specific record/check AND the decision' in core.INSTRUCTION_V3


def test_v3_raw_two_text_projection_generic_headings_and_exact_replay():
    memo,sources=sample()
    for field in core.FIELDS: memo[field]['heading']='Unsupported asserted competitive leadership'
    original=copy.deepcopy(memo); rows=[]; budget=PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in core.FIELDS:
        record=core.run_author(memo,sources,PIN,rows,lambda:None,Model(),budget,contract=core.CONTRACT_V3)
    assert record['state']=='accepted' and len(rows)==5
    for field in core.FIELDS:
        unit=record['answer'][field]['units']['S1']
        combined=unit['source_report']+' '+unit['decision_analysis']
        assert len(combined)<=421
        assert record['field_patches'][field]['claims'][0]['assertion']==combined
        assert record['field_patches'][field]['analysis']==combined.rstrip('.!? ')+' [S1].'
        assert record['field_patches'][field]['heading']==core.FIELD_LABELS[field]
    assert record['memo']['recommendation_reason']==memo['recommendation_reason']
    assert record['memo']['unknowns']==memo['unknowns'] and memo==original
    assert core.run_author(memo,sources,PIN,rows,lambda:None,None,SimpleNamespace(calls=0,max_calls=0),contract=core.CONTRACT_V3)==record
    legacy_field,legacy_payload,legacy_schema=core.frozen_requests(memo,sources,PIN)[0]
    legacy=core._project_field(memo,legacy_field,legacy_payload,legacy_schema,
        {'units':{'S1':{'supporting_evidence_id':'S1.e001','status':'conditional_hypothesis','standalone_text':TEXT[legacy_field]}}})
    assert legacy.heading==memo[legacy_field]['heading']


def test_each_structured_sentence_and_reported_metric_binding_are_checked():
    memo,sources=sample()
    field,payload,schema=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V3)[0]
    answer={'units':{'S1':{'supporting_evidence_id':'S1.e001','status':'conditional_hypothesis',
        'source_report':REPORT,'decision_analysis':TEXT[field]}}}
    changed=copy.deepcopy(answer)
    changed['units']['S1']['source_report']=REPORT+' The entry remains unverified.'
    with pytest.raises(ValueError,match='source_report must contain exactly one sentence'):
        core._project_field(memo,field,payload,schema,changed)
    changed=copy.deepcopy(answer)
    changed['units']['S1']['source_report']='The registry reports revenue of INR 2 crore without dated transaction completion confirmation.'
    with pytest.raises(ValueError,match='Economic metric "revenue"'):
        core._project_field(memo,field,payload,schema,changed)
    changed=copy.deepcopy(answer)
    changed['units']['S1']['source_report']=REPORT.replace('availability','availability in FY99')
    with pytest.raises(ValueError,match='numbers or dates'):
        core._project_field(memo,field,payload,schema,changed)
