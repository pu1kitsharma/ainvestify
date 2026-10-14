import copy
import pytest
from agents.research.material_purpose_draft import (
 memo_assertion_candidates, financial_unknown_candidates_v15, financial_unknown_candidates,
 _v15_options, _matching_possible, _schema_v15_financial, _v15_financial_slide, replay_purpose_v15)

FIELDS=('investment_thesis','business_and_market','differentiation_and_execution','risks_and_countercase','diligence_plan')
def memo():
    out={'recommendation_claims':[{'source_id':'S1','assertion':'The company reports a deployed workflow for partners.', 'quote':'Deployed workflow for partners.'}],
         'unknowns':[{'question':'Which financial records support the operating model?', 'evidence_needed':'Audited operating accounts and reconciliations.'}]}
    for i, field in enumerate(FIELDS):
        text=('If partner adoption fails, the proposed model may not scale. That outcome could reduce future profitability.' if field=='risks_and_countercase' else
              'Request signed distribution records. They would establish whether the proposed distribution route is feasible.' if field=='diligence_plan' else
              'The source reports a partner workflow whose proposed adoption remains subject to independent verification.')
        out[field]={'claims':[{'source_id':'S'+str(i+2),'assertion':text,'quote':'Partner workflow adoption and distribution records.'}]}
    return out

def test_complete_conditions_and_record_requests_preserved_with_roles():
    original=memo(); saved=copy.deepcopy(original); packet=memo_assertion_candidates(original)
    risk=packet['slots']['risk'][0]
    assert risk['text']==original['risks_and_countercase']['claims'][0]['assertion']
    assert risk['field_function']=='conditional_hypothesis'
    assert risk['source_quote']==original['risks_and_countercase']['claims'][0]['quote']
    assert packet['funding_required'] is False
    assert packet['coverage']['funding']['status']=='missing_reviewed_candidate'
    assert original==saved

@pytest.mark.parametrize('text,quote,expected',[
 ('The source reports ARR and capital efficiency.','ARR and capital efficiency',False),
 ('Request funding records to verify completion.','Funding round reported',False),
 ('The company reports a completed seed round.','Completed seed round',True),
 ('The company plans a proposed financing round.','Proposed financing round',False)])
def test_funding_requires_reported_financing_event_not_capital_or_request(text,quote,expected):
    item=memo();item['recommendation_claims'][0].update(assertion=text,quote=quote)
    assert memo_assertion_candidates(item)['funding_required'] is expected

def test_matching_preserves_later_required_coverage():
    candidates={'product':[{'id':'a'},{'id':'b'}], 'market':[{'id':'a'}]}
    options,maximum=_v15_options('product',['market'],candidates,[])
    assert options==[{'id':'b'}] and maximum==1
    assert _matching_possible(['product','market'],candidates,set())
    assert not _matching_possible(['product','market'],candidates,{'b'})

def test_financial_no_fact_variant_exact_unknown_and_historical_required():
    item=memo()
    item['risks_and_countercase']['claims'][0]['assertion']='If adoption fails, the proposed partner workflow could be delayed.'
    with pytest.raises(ValueError):financial_unknown_candidates(item)
    candidates=financial_unknown_candidates_v15(item)
    assert candidates['claims']==[]
    unknown=candidates['unknowns'][0]
    schema=_schema_v15_financial(candidates)
    selected=schema.model_validate({'heading':'Financial evidence','unknown_id':unknown['id'],'claim_id':None,'status':'unknown','layout':'evidence'})
    section=(unknown['question'],'Conditional relevance.\n\n'+unknown['evidence_needed'],'')
    slide=_v15_financial_slide(selected,candidates,[section])
    assert 'Open diligence question: '+unknown['question'] in slide.body
    assert 'Evidence requested: '+unknown['evidence_needed'] in slide.body
    assert '[S' not in slide.body
    assert slide.source_sections==[0]
    with pytest.raises(ValueError):_v15_financial_slide(selected,candidates,[(unknown['question'],'Unrelated records','')])

def test_financial_claim_has_exact_quote_only_new_packet():
    item=memo();item['recommendation_claims'][0].update(assertion='The source reports ARR as a target requiring verification.',quote='ARR is a target.\nThe source reports it separately.')
    old=financial_unknown_candidates(item);new=financial_unknown_candidates_v15(item)
    assert 'source_quote' not in old['claims'][0]
    assert new['claims'][0]['source_quote']==item['recommendation_claims'][0]['quote']

def test_missing_complete_slot_coverage_blocks_before_call():
    item=memo();packet=memo_assertion_candidates(item)
    packet['slots']['risk']=[]
    result=replay_purpose_v15('intro_deck',{'memo_assertion_candidates':packet,'financial_unknown_candidates':financial_unknown_candidates_v15(item)},[],[])
    assert result['state']=='blocked' and result['response_ids']==[]

def test_conditional_future_profit_is_not_a_financial_fact_option():
    packet=financial_unknown_candidates_v15(memo())
    assert packet['claims']==[]


def test_full_deck_replay_preserves_complete_units_and_raw_contract():
    import json
    from agents.inference.model_authorship import recorded_call
    item=memo()
    # Different sources describe different complete business assertions, so both
    # product and market can be selected without splitting or duplicating them.
    item['business_and_market']['claims'].append({'source_id':'S9',
        'assertion':'The source reports a distinct customer segment whose adoption remains subject to verification.',
        'quote':'Distinct customer segment adoption.'})
    packet=memo_assertion_candidates(item)
    financial=financial_unknown_candidates_v15(item)
    sections=[]
    for field in ('recommendation_reason',)+FIELDS:
        group=item['recommendation_claims'] if field=='recommendation_reason' else item[field]['claims']
        for row in group:sections.append((field,row['assertion']+' ['+row['source_id']+'].','['+row['source_id']+'] retained source'))
    unknown=financial['unknowns'][0]
    sections.append((unknown['question'],'Conditional relevance.\n\n'+unknown['evidence_needed'],''))
    base={'kind':'pitch_deck','input_revision':'r'*64,'source_hash':'s'*64,'memo_digest':'m'*64,
          'memo_assertion_candidates':packet,'financial_unknown_candidates':financial}
    class Selector:
        name='synthetic-local'
        def generate_for_task(self,task,instruction,evidence,schema,*,attempt=0):
            payload=json.loads(evidence)
            if payload['slot']=='financial_unknown':
                answer={'heading':'Financial records','unknown_id':unknown['id'],'claim_id':None,'status':'unknown','layout':'evidence'}
            else:
                answer={'heading':'Topic '+payload['slot'],'sentence_ids':[payload['candidates'][0]['id']],'layout':'statement'}
            self.last_response_text=json.dumps(answer);self.last_route={'model':self.name}
            return schema.model_validate(answer)
    rows=[];model=Selector()
    for _ in range(7):
        result=replay_purpose_v15('pitch_deck',base,rows,sections,model_name=model.name)
        if result['state']!='needs_call':break
        recorded_call(model,result['task'],result['instruction'],result['payload'],result['schema'],rows,lambda:None)
    result=replay_purpose_v15('pitch_deck',base,rows,sections,model_name=model.name)
    assert result['state']=='accepted'
    risk=next(slide for slide in result['spec'].slides if slide.heading=='Topic risk')
    assert risk.body.startswith(item['risks_and_countercase']['claims'][0]['assertion'].rstrip('.'))
    selected=[key for row in rows for key in json.loads(row['raw_response']).get('sentence_ids',[])]
    assert len(selected)==len(set(selected))
    changed=copy.deepcopy(rows);changed[0]['input']['coverage']['funding']['status']='available'
    with pytest.raises(ValueError,match='Saved complete assertion response changed'):
        replay_purpose_v15('pitch_deck',base,changed,sections,model_name=model.name)

def test_sourcefree_optin_does_not_accept_other_company_prose_or_numeric_rows():
    from agents.research.material_slides import CompactDeckSpec, CompactSlide, validate_deck
    item=memo();unknown=financial_unknown_candidates_v15(item)['unknowns'][0]
    sections=[('Source report','The source reports a deployed partner workflow. [S1].','[S1] retained source'),
              (unknown['question'],'Conditional importance.\n\n'+unknown['evidence_needed'],'')]
    model_selection=_schema_v15_financial({'unknowns':[unknown],'claims':[]}).model_validate(
        {'heading':'Financial evidence','unknown_id':unknown['id'],'claim_id':None,'status':'unknown','layout':'statement'})
    financial=_v15_financial_slide(model_selection,{'unknowns':[unknown],'claims':[]},sections)
    first=CompactSlide(heading='Company report',body=sections[0][1],source_sections=[0],layout='statement')
    valid=CompactDeckSpec(slides=[first,financial])
    validate_deck(valid,sections,'intro_deck',reviewed_unknowns=[unknown])
    with pytest.raises(ValueError,match='lacks source citations'):validate_deck(valid,sections,'intro_deck')
    for bad in (financial.model_copy(update={'body':financial.body+'\nThe company is profitable.'}),
                financial.model_copy(update={'body':financial.body.replace('unknown.','unknown in 2024.')}),
                financial.model_copy(update={'source_sections':[0]})):
        with pytest.raises(ValueError,match='lacks source citations'):
            validate_deck(CompactDeckSpec(slides=[first,bad]),sections,'intro_deck',reviewed_unknowns=[unknown])
