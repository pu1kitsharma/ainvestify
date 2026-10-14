import pytest
from agents.research.material_purpose_draft import (
 financial_unknown_candidates_v18,memo_assertion_candidates_v18,_schema_v18_financial,
 _v18_financial_slide,V18_CONTRACT,TEMPORAL_LABEL_V18)
from tests.research.test_material_purpose_v16 import financial_memo

def fixture():
    packet=financial_unknown_candidates_v18(financial_memo());claim=packet['claims'][0];span=claim['temporal_evidence'][0]
    selection={'heading':'Reported historical target','unknown_id':packet['unknowns'][0]['id'],'claim_id':claim['id'],
        'status':'unverified','layout':'evidence','temporal_evidence_id':span['id'],
        'primary_period_token':span['period_tokens'][0],'temporal_basis':'historical_target'}
    sections=[('Company target',claim['assertion']+' [S1].','[S1] retained source'),
        ('Source context',claim['source_quote'],'[S1] retained source')]
    return packet,selection,sections

def test_schema_requires_finite_exact_period_and_no_caption_authorship():
    packet,answer,_=fixture();schema=_schema_v18_financial(packet)
    schema.model_validate(answer)
    properties=schema.model_json_schema()['properties']
    assert 'temporal_caption' not in properties and 'attributed_period_caption' not in properties
    assert properties['primary_period_token']['const']=='FY23'
    with pytest.raises(ValueError):schema.model_validate(dict(answer,primary_period_token='FY24'))
    with pytest.raises(ValueError):schema.model_validate(dict(answer,primary_period_token=None))
    assert memo_assertion_candidates_v18(financial_memo())['contract']==V18_CONTRACT

def test_neutral_classification_exact_period_and_source_quote_one_line():
    packet,answer,sections=fixture();item=_schema_v18_financial(packet).model_validate(answer)
    slide=_v18_financial_slide(item,packet,sections)
    assert len(slide.body.splitlines())==4
    assert 'Temporal classification: '+TEMPORAL_LABEL_V18['historical_target'] in slide.body
    assert 'Selected period: FY23 [S1].' in slide.body
    assert packet['claims'][0]['temporal_evidence'][0]['exact_text'] in slide.body
    assert packet['claims'][0]['assertion'].rstrip('.') in slide.body
    assert 'Requested financial evidence status: unverified.' in slide.body


def test_undated_selector_requires_null_period_without_manual_absence_prose():
    original=financial_memo();original['recommendation_claims'][0]['quote']='ARR target remains a company description.'
    packet=financial_unknown_candidates_v18(original);claim=packet['claims'][0];span=claim['temporal_evidence'][0]
    assert span['period_tokens']==[]
    answer={'heading':'Source-reported target','unknown_id':packet['unknowns'][0]['id'],'claim_id':claim['id'],
        'status':'unknown','layout':'statement','temporal_evidence_id':span['id'],
        'primary_period_token':None,'temporal_basis':'undated_target'}
    item=_schema_v18_financial(packet).model_validate(answer)
    sections=[('Target',claim['assertion']+' [S1].','[S1] source'),('Exact retained excerpt',claim['source_quote'],'[S1] source')]
    slide=_v18_financial_slide(item,packet,sections)
    assert 'Selected period:' not in slide.body
    assert 'Undated source-reported target' in slide.body
    assert 'not supplied' not in slide.body

def test_complete_bounded_deck_replays_typed_period_with_no_caption():
    import json
    from agents.inference.model_authorship import recorded_call
    from agents.research.material_purpose_draft import replay_purpose_v18
    original=financial_memo()
    for sid,text in [('S9','The source reports a distribution offering for a distinct customer segment.'),
                     ('S10','The source reports software interfaces deployed in another partner workflow.')]:
        original['business_and_market']['claims'].append({'source_id':sid,'assertion':text,'quote':text})
    packet=memo_assertion_candidates_v18(original);financial=financial_unknown_candidates_v18(original)
    sections=[]
    groups=[original['recommendation_claims']]+[original[field]['claims'] for field in
        ('investment_thesis','business_and_market','differentiation_and_execution','risks_and_countercase','diligence_plan')]
    for group in groups:
        for claim in group:
            sections.append(('Reviewed assertion',claim['assertion']+' ['+claim['source_id']+'].','['+claim['source_id']+'] retained source'))
            sections.append(('Exact source excerpt',claim['quote'],'['+claim['source_id']+'] retained source'))
    unknown=financial['unknowns'][0]
    sections.append((unknown['question'],'Conditional relevance.\n\n'+unknown['evidence_needed'],''))
    base={'kind':'pitch_deck','input_revision':'r'*64,'source_hash':'s'*64,'memo_digest':'m'*64,
          'as_of_date':'2026-10-09','memo_assertion_candidates':packet,'financial_unknown_candidates':financial}
    class Selector:
        name='synthetic-local'
        def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
            payload=json.loads(evidence)
            if payload['slot']=='financial_unknown':
                claim=payload['candidates']['claims'][0];span=claim['temporal_evidence'][0]
                answer={'heading':'Source-reported historical target','claim_id':claim['id'],
                    'unknown_id':unknown['id'],'status':'unknown','layout':'evidence',
                    'temporal_evidence_id':span['id'],'primary_period_token':span['period_tokens'][0],
                    'temporal_basis':'historical_target'}
            else:answer={'heading':'Topic '+payload['slot'],'sentence_ids':[payload['candidates'][0]['id']],'layout':'statement'}
            self.last_response_text=json.dumps(answer);self.last_route={'model':self.name}
            return schema.model_validate(answer)
    attempts=[];model=Selector()
    for _ in range(7):
        result=replay_purpose_v18('pitch_deck',base,attempts,sections,model_name=model.name)
        if result['state']!='needs_call':break
        recorded_call(model,result['task'],result['instruction'],result['payload'],result['schema'],attempts,lambda:None)
    result=replay_purpose_v18('pitch_deck',base,attempts,sections,model_name=model.name)
    assert result['state']=='accepted' and len(attempts)==6
    assert all(row['input']['as_of_date']=='2026-10-09' for row in attempts)
    assert 'caption' not in attempts[-1]['raw_response']
    assert len(result['spec'].slides[-1].body.splitlines())==4
