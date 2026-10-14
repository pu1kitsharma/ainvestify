"""Section-sized floor is shared across linked units, with exact closed evidence."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core
from tests.research.test_memo_section_units_v5 import fixture, TEXTS, PIN

SHORT_BUSINESS='The company reports a partner distribution service and limited overlap against incumbent offerings; these remain unverified positioning statements.'
assert 90 <= len(SHORT_BUSINESS) < 180


def two_source_fixture():
    memo,sources=fixture()
    sources[1]['passage']=sources[0]['passage']
    for field in core.FIELDS:
        memo[field]['claims'].append({**memo[field]['claims'][0],'source_id':'S2'})
    return memo,sources


class Model:
    name=PIN['name']; thinking=False; max_tokens=600; context_tokens=8192; temperature=0; bound_strings=True
    def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
        assert task==core.TASK_V6 and instruction==core.INSTRUCTION_V6
        payload=json.loads(evidence); field=payload['field']
        status='conditional_hypothesis' if field=='differentiation_and_execution' else core.STATUSES[field][0]
        text=SHORT_BUSINESS if field=='business_and_market' else TEXTS[field]
        obj={'units':{sid:{'supporting_evidence_id':next(iter(payload['sources'][sid]['spans'])),
            'status':status,'decision_analysis':text} for sid in payload['unit_source_ids']}}
        self.last_response_text=json.dumps(obj); self.last_route={'model':self.name,**core.options_for(core.CONTRACT_V6)}
        return schema.model_validate(obj)


def test_single_and_two_link_floors_derive_section180_and_v5_stays180_each():
    for builder,count in ((fixture,1),(two_source_fixture,2)):
        memo,sources=builder()
        calls=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V6)
        for field,payload,schema in calls:
            assert len(payload['unit_source_ids'])==count
            for sid in payload['unit_source_ids']:
                unit=schema.model_fields['units'].annotation.model_fields[sid].annotation
                assert unit.model_fields['decision_analysis'].metadata[0].min_length==(180+count-1)//count
                assert unit.model_fields['decision_analysis'].metadata[1].max_length==420
        old=core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V5)
        for field,payload,schema in old:
            for sid in payload['unit_source_ids']:
                unit=schema.model_fields['units'].annotation.model_fields[sid].annotation
                assert unit.model_fields['decision_analysis'].metadata[0].min_length==180
    memo,sources=fixture()
    field,payload,schema=next(row for row in core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V6) if row[0]=='business_and_market')
    with pytest.raises(ValueError):
        schema.model_validate({'units':{'S1':{'supporting_evidence_id':'S1.n001','status':'source_reported','decision_analysis':SHORT_BUSINESS}}})
    assert core.options_for(core.CONTRACT_V6)['bound_strings'] is True
    assert 'per-unit schema minimum' in core.INSTRUCTION_V6
    assert 'Start reported factual statements' in core.INSTRUCTION_V6


def test_two_unit_accurate_short_reports_project_complete_section_and_replay_exact():
    memo,sources=two_source_fixture(); original=copy.deepcopy(sources)
    rows=[]; budget=PreparationBudget(105,max_calls=6,max_requests=6)
    for _ in core.FIELDS:
        result=core.run_author(memo,sources,PIN,rows,lambda:None,Model(),budget,contract=core.CONTRACT_V6)
    assert result['state']=='accepted' and len(rows)==5
    assert all(len(result['memo'][field]['analysis'])>=180 for field in core.FIELDS)
    assert all(claim['assertion']==SHORT_BUSINESS for claim in result['memo']['business_and_market']['claims'])
    assert result['memo']['business_and_market']['analysis']==SHORT_BUSINESS.rstrip('.')+' [S1]. '+SHORT_BUSINESS.rstrip('.')+' [S2].'
    assert sources==original
    assert core.run_author(memo,sources,PIN,rows,lambda:None,None,SimpleNamespace(calls=0,max_calls=0),contract=core.CONTRACT_V6)==result
    expected=core.frozen_offered_spans(sources,core.frozen_requests(memo,sources,PIN,contract=core.CONTRACT_V6))
    assert result['offered_evidence_spans']==expected
