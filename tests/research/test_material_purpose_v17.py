import pytest
from agents.research.material_purpose_draft import (
 financial_unknown_candidates_v17,memo_assertion_candidates_v17,_schema_v17_financial,_v17_financial_slide,
 memo_assertion_candidates_v16,V16_CONTRACT,V17_CONTRACT)
from tests.research.test_material_purpose_v16 import financial_memo

def fixture():
    packet=financial_unknown_candidates_v17(financial_memo());claim=packet['claims'][0];span=claim['temporal_evidence'][0]
    selection={'heading':'Reported historical target','unknown_id':packet['unknowns'][0]['id'],'claim_id':claim['id'],
        'status':'unverified','layout':'evidence','temporal_evidence_id':span['id'],
        'attributed_period_caption':'The company source presents a historical target for FY23 Exit rather than an independently verified observation.',
        'temporal_basis':'historical_target'}
    sections=[('Company target',claim['assertion']+' [S1].','[S1] retained source'),
        ('Source context',claim['source_quote'],'[S1] retained source')]
    return packet,selection,sections

def test_fresh_schema_role_sufficient_complete_sentence_and_oldversion_unchanged():
    packet,answer,sections=fixture();schema=_schema_v17_financial(packet)
    assert len(answer['attributed_period_caption'])>100
    item=schema.model_validate(answer);slide=_v17_financial_slide(item,packet,sections)
    assert len(slide.body.splitlines())==4
    assert 'FY23 Exit' in slide.body
    assert answer['attributed_period_caption'].rstrip('.') in slide.body
    assert 'temporal_caption' not in schema.model_json_schema()['properties']
    assert memo_assertion_candidates_v17(financial_memo())['contract']==V17_CONTRACT
    assert memo_assertion_candidates_v16(financial_memo())['contract']==V16_CONTRACT

@pytest.mark.parametrize('caption,error',[
 ('The company target for FY23 Exit reports ARR of 70 million.','economic'),
 ('The company source presents a historical target rather than an independently verified observation.','omits'),
 ('The company source presents a historical target for FY23 Exit but truncates','complete'),
 ('The company source presents a historical target for FY24 Exit.','omits'),
 ('The company source states a historical target for FY23 Exit with 70 partners.','non-period')])
def test_caption_role_binding_rejects_repeated_amounts_omitted_period_truncation(caption,error):
    packet,answer,sections=fixture();answer['attributed_period_caption']=caption
    item=_schema_v17_financial(packet).model_validate(answer)
    with pytest.raises(ValueError,match=error):_v17_financial_slide(item,packet,sections)
