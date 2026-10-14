"""Source-local binding and raw transport proofs; all inputs are synthetic."""
from copy import deepcopy
import hashlib
import json

import pytest

from agents.inference.local_models import STREAM_OBSERVATION_V1,_transport_digest,bounded_thinking_input_binding
from agents.research import document_generation as dg
from agents.research import document_source_index as module
from tests.delivery.test_document_generation_stage_source_maps import full_source
from tests.research.test_document_generation import PIN,manifest,record


def answer(request,*,unassessed=False):
    return {'group_id':request[2]['source_group_id'],
        'status':'unassessed' if unassessed else 'proposed_literal_summary',
        'synopsis':'' if unassessed else 'The source reports a limited pilot in 2024.',
        'quotes':[] if unassessed else [{'unit_id':'U1','quote':'a limited pilot in 2024'}],
        'visual_semantics':'unassessed','scope_status':'local_source_index_proposal_not_diligence'}


def actual_mock_record(request,value,number):
    row=record(request,value,number)
    if request[2]['options'].get('streaming_transport_contract') is None:return row
    route=row['routing'];raw=row['raw_response']
    route['stream_observation']={'contract':STREAM_OBSERVATION_V1,'state':'terminal',
        'terminal_observed':True,'client_close_completed':True,'model':PIN['name'],
        'returned_model':PIN['name'],'done_reason':'stop','prompt_tokens':route['prompt_tokens'],
        'generated_tokens':route['generated_tokens'],'unexpected_thinking_observed':False,
        'actual_options_digest':_transport_digest({'temperature':route['temperature'],
            'num_ctx':route['context_tokens'],'num_predict':route['max_tokens'],**route['sampling']}),
        'content_sha256':hashlib.sha256(raw.encode()).hexdigest(),'content_characters':len(raw),
        'content_bytes':len(raw.encode()),'observed_chunks':1,'observed_content_chunks':1,
        'first_chunk_seconds':0,'first_content_seconds':0,'last_chunk_seconds':1,'elapsed_seconds':1,
        **bounded_thinking_input_binding(request[1],json.dumps(request[2],ensure_ascii=False),request[3],
            compact_prompt=True,bound_strings=True)}
    return row


def test_all_physical_groups_including_blank_are_read_and_actual_stream_provenance_replays():
    inv=dg.evidence_inventory([full_source()],catalog_encoding=dg.CATALOG_ENCODING_V6)
    requests=module.frozen_source_index_requests(inv,PIN,kind='intro_deck',page_author_pin=PIN,
        streaming_transport_contract=STREAM_OBSERVATION_V1,planning_context_profile=dg.PLAN_CONTEXT_PROFILE_32K)
    assert len(requests)==2 and [r[2]['source_group_id'] for r in requests]==['G1','G2']
    assert all(r[2]['options']['context_tokens']==16384 and r[2]['options']['max_tokens']==600 for r in requests)
    assert requests[0][2]['planning_context_profile']==dg.PLAN_CONTEXT_PROFILE_32K
    first=actual_mock_record(requests[0],answer(requests[0]),1)
    second=actual_mock_record(requests[1],answer(requests[1],unassessed=True),2)
    assert module.replay_source_index(requests[0],first)['response_hash']==first['response_hash']
    assert module.replay_source_index(requests[1],second)['status']=='unassessed'
    modified=deepcopy(first);modified['routing']['stream_observation']['terminal_observed']=False
    with pytest.raises(ValueError,match='completed transport'):module.replay_source_index(requests[0],modified)
    catalog=module.source_index_catalog(inv,PIN,[first,second],kind='intro_deck',page_author_pin=PIN,
        streaming_transport_contract=STREAM_OBSERVATION_V1,planning_context_profile=dg.PLAN_CONTEXT_PROFILE_32K)
    assert len(catalog['entries'])==2 and catalog['entries'][1]['synopsis']==''
    assert module.validate_source_index_catalog(inv,catalog)
    assert 'physical_group_catalog' not in catalog


def test_synopsis_requires_own_nonblank_quotes_and_numeric_date_tokens_cannot_be_borrowed():
    inv=dg.evidence_inventory([manifest()],catalog_encoding=dg.CATALOG_ENCODING_V6)
    request=module.frozen_source_index_requests(inv,PIN,kind='intro_deck')[0]
    good=answer(request)
    assert module.replay_source_index(request,actual_mock_record(request,good,1))['synopsis']==good['synopsis']
    for changed in [
        {**good,'quotes':[]},
        {**good,'quotes':[{'unit_id':'U2','quote':'a limited pilot in 2024'}]},
        {**good,'synopsis':'The source reports 999 customers.'},
        {**good,'status':'unassessed'},
    ]:
        with pytest.raises(ValueError):module.replay_source_index(request,actual_mock_record(request,changed,1))


def test_rehashed_catalog_cannot_swap_groups_change_native_cells_or_inflate_approval():
    inv=dg.evidence_inventory([manifest()],catalog_encoding=dg.CATALOG_ENCODING_V6)
    request=module.frozen_source_index_requests(inv,PIN,kind='intro_deck')[0]
    catalog=module.source_index_catalog(inv,PIN,[actual_mock_record(request,answer(request),1)],kind='intro_deck')
    assert module.validate_source_index_catalog(inv,catalog)
    for change in ('grid','group','approval'):
        altered=deepcopy(catalog)
        if change=='grid':altered['table_navigation'][0]['rows'][1][1]='replaced source value'
        elif change=='group':altered['entries'][0]['source_group_id']='G2'
        else:altered['entries'][0]['financial_validation']='established'
        altered['catalog_digest']=dg.canonical_digest({k:v for k,v in altered.items() if k!='catalog_digest'})
        with pytest.raises(ValueError):module.validate_source_index_catalog(inv,altered)


def test_selected_profile_projects_only_complete_own_originals_and_preserves_synopsis_default():
    inv=dg.evidence_inventory([full_source()],catalog_encoding=dg.CATALOG_ENCODING_V6)
    old=module.frozen_source_index_requests(inv,PIN,kind='intro_deck')
    explicit=module.frozen_source_index_requests(inv,PIN,kind='intro_deck',planning_schema_profile=module.PROFILE)
    assert [dg.request_json(r) for r in old]==[dg.request_json(r) for r in explicit]
    requests=module.frozen_source_index_requests(inv,PIN,kind='intro_deck',
        planning_schema_profile=module.SELECTED_PROFILE)
    assert len(requests)==2 and requests[0][0]==module.SELECTED_TASK
    assert all(r[2]['options']['max_tokens']==600 and r[2]['options']['context_tokens']==16384 for r in requests)
    assert requests[0][2]['source_group']==old[0][2]['source_group']
    def selection(request,ids):
        return {'group_id':request[2]['source_group_id'],'focus_unit_ids':ids,
            'visual_semantics':'unassessed','scope_status':'local_source_selection_proposal_not_diligence'}
    value=selection(requests[0],['U1'])
    rows=[actual_mock_record(requests[0],value,1),
          actual_mock_record(requests[1],selection(requests[1],[]),2)]
    entry=module.replay_source_index(requests[0],rows[0])
    original=dg.source_map_literal_lookup(requests[0][2]['source_group'])['U1']
    assert entry['selected_original_units'][0]['content']==original['content']
    assert entry['selected_original_units'][0]['source_locator']==original['source_locator']
    assert entry['selected_original_units'][0]['original_unit_digest']==dg.canonical_digest(original)
    assert 'synopsis' not in entry and 'quotes' not in entry
    catalog=module.source_index_catalog(inv,PIN,rows,kind='intro_deck',planning_schema_profile=module.SELECTED_PROFILE)
    assert module.validate_source_index_catalog(inv,catalog)
    assert catalog['entries'][1]['selected_original_units']==[]
    for ids in ([],['U1','U1'],['U9999']):
        with pytest.raises(ValueError):
            module.replay_source_index(requests[0],actual_mock_record(requests[0],selection(requests[0],ids),1))
    altered=deepcopy(catalog)
    altered['entries'][0]['selected_original_units'][0]['content']='changed original value'
    altered['catalog_digest']=dg.canonical_digest({k:v for k,v in altered.items() if k!='catalog_digest'})
    with pytest.raises(ValueError):module.validate_source_index_catalog(inv,altered)


def test_selected_source_context_32k_is_explicit_frozen_and_preserves_default_requests():
    inv=dg.evidence_inventory([manifest()],catalog_encoding=dg.CATALOG_ENCODING_V6)
    kwargs={'kind':'intro_deck','planning_schema_profile':module.SELECTED_PROFILE}
    default=module.frozen_source_index_requests(inv,PIN,**kwargs)[0]
    absent=module.frozen_source_index_requests(inv,PIN,**kwargs,source_context_profile=None)[0]
    assert dg.request_json(default)==dg.request_json(absent)
    assert default[2]['options']['context_tokens']==16384 and 'source_context_profile' not in default[2]
    profile=module.SOURCE_CONTEXT_PROFILE_32K
    expanded=module.frozen_source_index_requests(inv,PIN,**kwargs,source_context_profile=profile)[0]
    assert expanded[2]['options']['context_tokens']==32768 and expanded[2]['options']['max_tokens']==600
    assert expanded[2]['source_group']==default[2]['source_group']
    assert expanded[2]['source_context_profile']==profile
    value={'group_id':'G1','focus_unit_ids':['U1'],'visual_semantics':'unassessed',
           'scope_status':'local_source_selection_proposal_not_diligence'}
    row=actual_mock_record(expanded,value,1)
    assert module.replay_source_index(expanded,row)['reader_request_digest']!=dg.canonical_digest(dg.request_json(default))
    catalog=module.source_index_catalog(inv,PIN,[row],**kwargs,source_context_profile=profile)
    assert catalog['source_index_request_profile']['source_context_profile']==profile
    assert module.validate_source_index_catalog(inv,catalog)
    for rejected in (
        {'kind':'intro_deck','source_context_profile':profile},
        {**kwargs,'source_context_profile':'unknown-source-context'},
    ):
        with pytest.raises(ValueError):module.frozen_source_index_requests(inv,PIN,**rejected)
    changed=(expanded[0],expanded[1],deepcopy(expanded[2]),expanded[3])
    changed[2]['options']['context_tokens']=16384
    with pytest.raises(ValueError):module.replay_source_index(changed,actual_mock_record(changed,value,1))


def test_bound_selected_encoding_roundtrips_originals_and_metadata_without_changing_readers():
    inv=dg.evidence_inventory([manifest()],catalog_encoding=dg.CATALOG_ENCODING_V6)
    kwargs={'kind':'intro_deck','planning_schema_profile':module.SELECTED_PROFILE,
            'source_context_profile':module.SOURCE_CONTEXT_PROFILE_32K}
    old=module.frozen_source_index_requests(inv,PIN,**kwargs)
    encoded=module.frozen_source_index_requests(inv,PIN,**kwargs,source_index_encoding=module.SOURCE_INDEX_ENCODING_V2)
    assert [dg.request_json(r) for r in old]==[dg.request_json(r) for r in encoded]
    value={'group_id':'G1','focus_unit_ids':['U1','U2','U3'],'visual_semantics':'unassessed',
           'scope_status':'local_source_selection_proposal_not_diligence'}
    rows=[actual_mock_record(old[0],value,1)]
    full=module.source_index_catalog(inv,PIN,rows,**kwargs)
    dense=module.source_index_catalog(inv,PIN,rows,**kwargs,source_index_encoding=module.SOURCE_INDEX_ENCODING_V2)
    assert 'source_index_encoding' not in full
    assert module.decode_source_index_entries(inv,dense)==full['entries']
    assert dense['table_navigation']==full['table_navigation']
    assert module.validate_source_index_catalog(inv,dense)
    assert 'source_locator' not in dense['selected_unit_columns']
    assert dense['entries'][0][4][0][1]==full['entries'][0]['selected_original_units'][0]['content']
    for mutation in ('text','unit_digest','group','common','locator_contract'):
        changed=deepcopy(dense)
        if mutation=='text':changed['entries'][0][4][0][1]='rewritten source literal'
        elif mutation=='unit_digest':changed['entries'][0][4][0][3]='b'*64
        elif mutation=='group':changed['entries'][0][0]='G2'
        elif mutation=='common':changed['entry_common']['financial_validation']='established'
        else:changed['source_location_metadata']='invented external locator'
        changed['catalog_digest']=dg.canonical_digest({k:v for k,v in changed.items() if k!='catalog_digest'})
        with pytest.raises(ValueError):module.validate_source_index_catalog(inv,changed)
    for bad in (
        {'kind':'intro_deck','source_index_encoding':module.SOURCE_INDEX_ENCODING_V2},
        {**kwargs,'source_index_encoding':'unknown'},
    ):
        with pytest.raises(ValueError):module.frozen_source_index_requests(inv,PIN,**bad)
