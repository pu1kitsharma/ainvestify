import copy
import pytest
from agents.research.material_purpose_draft import (
 temporal_quote_views,financial_unknown_candidates_v16,memo_assertion_candidates_v16,
 memo_assertion_candidates,V15_CONTRACT,V16_CONTRACT,_schema_v16_financial,_v16_financial_slide)
from tests.research.test_material_purpose_v15 import memo

def financial_memo():
    out=memo()
    out['recommendation_claims'][0].update(assertion='The company reports ARR as a target, not a verified operating result.',
        quote='ARR target\nFY23 Exit ARR plan\nOperating description.')
    return out

def test_temporal_views_exact_offset_lineage_and_original_unchanged():
    quote='Header\\nFY23 Exit ARR target\\nDecember-23 reporting context'
    saved=quote
    spans=temporal_quote_views('S2',quote)
    assert len(spans)==2
    assert all(quote[row['start']:row['end']]==row['exact_text'] for row in spans)
    assert spans[0]['exact_text']=='FY23 Exit ARR target'
    assert quote==saved


def test_v16_reserves_financial_claim_and_excludes_nonproduct_competition():
    original=financial_memo();saved=copy.deepcopy(original)
    original['business_and_market']['claims'].append({'source_id':'S8',
        'assertion':'The source reports limited competition for the proposed company strategy.',
        'quote':'Limited competition and first mover advantage.'})
    packet=memo_assertion_candidates_v16(original)
    assert packet['contract']==V16_CONTRACT
    assert all(row['source_id']!='S1' for rows in packet['slots'].values() for row in rows)
    assert all(row['source_id']!='S8' for row in packet['slots']['product'])
    assert all(row['source_quote']==original[row['memo_field']]['claims'][0]['quote'] for row in packet['slots']['risk'])
    assert memo_assertion_candidates(original)['contract']==V15_CONTRACT
    assert original['recommendation_claims']==saved['recommendation_claims']


def test_financial_caption_exact_period_context_single_review_line_and_binding():
    item=financial_memo();packet=financial_unknown_candidates_v16(item)
    claim=packet['claims'][0];span=claim['temporal_evidence'][0];unknown=packet['unknowns'][0]
    schema=_schema_v16_financial(packet)
    selection={'heading':'Financial targets','unknown_id':unknown['id'],'claim_id':claim['id'],
        'status':'unverified','layout':'evidence','temporal_evidence_id':span['id'],
        'temporal_caption':'The source presents an historical FY23 Exit target.', 'temporal_basis':'historical_target'}
    sections=[('Company target',claim['assertion']+' [S1].','[S1] retained source'),
        ('Source context',claim['source_quote'],'[S1] retained source')]
    slide=_v16_financial_slide(schema.model_validate(selection),packet,sections)
    assert len(slide.body.splitlines())==4
    assert claim['assertion'].rstrip('.') in slide.body
    assert span['exact_text'] in slide.body
    assert selection['temporal_caption'].rstrip('.') in slide.body
    assert slide.source_sections==[0,1]
    bad=dict(selection,temporal_caption='The source presents an historical FY24 Exit target.')
    with pytest.raises(ValueError,match='unsupported period'):
        _v16_financial_slide(schema.model_validate(bad),packet,sections)
    bad=dict(selection,temporal_evidence_id='another-source-evidence')
    with pytest.raises(ValueError):schema.model_validate(bad)
    with pytest.raises(ValueError,match='absent'):
        _v16_financial_slide(schema.model_validate(selection),packet,sections[:1])

def test_v16_requested_status_is_not_an_absence_claim_and_nofact_validates():
    from agents.research.material_slides import CompactDeckSpec,CompactSlide,validate_deck
    original=memo();packet=financial_unknown_candidates_v16(original)
    assert not packet['claims']
    unknown=packet['unknowns'][0]
    selection={'heading':'Requested financial records','unknown_id':unknown['id'],
        'claim_id':None,'temporal_evidence_id':None,'temporal_caption':None,'temporal_basis':None,
        'status':'unknown','layout':'evidence'}
    schema=_schema_v16_financial(packet)
    with pytest.raises(ValueError):schema.model_validate(dict(selection,status='not supplied'))
    sections=[('Company','The source reports a partner workflow [S1].','[S1] retained source'),
        (unknown['question'],'Conditional relevance.\n\n'+unknown['evidence_needed'],'')]
    slide=_v16_financial_slide(schema.model_validate(selection),packet,sections)
    assert slide.body.startswith('Requested financial evidence status: unknown.')
    spec=CompactDeckSpec(slides=[CompactSlide(heading='Company',body=sections[0][1],source_sections=[0],layout='statement'),slide])
    validate_deck(spec,sections,'intro_deck',reviewed_unknowns=packet['unknowns'],
        reviewed_unknown_status_label='Requested financial evidence status')
    with pytest.raises(ValueError):validate_deck(spec,sections,'intro_deck',reviewed_unknowns=packet['unknowns'])
