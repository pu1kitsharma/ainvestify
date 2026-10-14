"""Signed serialization/finite source costs, using synthetic recorded fixtures."""
from copy import deepcopy
import json

import pytest

from agents.research import document_generation as dg
from agents.research import document_context_capacity as cc
from agents.research import document_qualification_context as qc
from tests.research.test_document_generation import PIN,manifest,planned,record


def request():
    inv=dg.evidence_inventory([manifest()],catalog_encoding=dg.CATALOG_ENCODING_V6)
    plan=dg.frozen_document_request(inv,PIN,'intro_deck',catalog_encoding=dg.CATALOG_ENCODING_V6,
        qualification_context_profile=qc.LITERAL_PROFILE)
    row=record(plan,planned(inv),1)
    actual=dg.frozen_page_request(plan,row,'P1',inv)
    payload={k:deepcopy(v) for k,v in actual[2].items() if k not in
        {'request_binding_digest','schema_order_digest','generation_schema_order_digest'}}
    payload['page_context_capacity_profile']=cc.PROFILE
    return inv,dg._request(actual[0],actual[1],payload,actual[3])


def test_complete_signed_payload_and_schema_are_measured_and_do_not_attest_token_fit():
    _,value=request();before=deepcopy(value[2])
    receipt=cc.validate_signed_request_capacity(value)
    assert receipt['signed_payload_characters']==len(cc.compact_json(value[2]))
    assert all(key in cc.compact_json(value[2]) for key in
        ['request_binding_digest','schema_order_digest','generation_schema_order_digest'])
    assert receipt['complete_message_content_characters']>receipt['signed_payload_characters']
    assert receipt['context_tokens']==16384 and 'unassessed' in receipt['token_fit']
    assert value[2]==before


def test_unsigned_or_rehashed_oversize_request_cannot_pass_signed_capacity_gate():
    _,value=request();payload=deepcopy(value[2]);payload.pop('request_binding_digest')
    with pytest.raises(dg.GenerationError):cc.validate_signed_request_capacity((value[0],value[1],payload,value[3]))
    payload={k:deepcopy(v) for k,v in value[2].items() if k not in
        {'request_binding_digest','schema_order_digest','generation_schema_order_digest'}}
    payload['extra_untrusted_text']='x'*32000
    oversized=dg._request(value[0],value[1],payload,value[3])
    with pytest.raises(dg.GenerationError,match='exceeds_bound'):
        cc.validate_signed_request_capacity(oversized)


def test_review_reserve_contains_no_proposed_page_and_covers_signed_actual_review_at_answer_cap():
    _,value=request()
    reserved=cc.review_capacity_reserve(value)
    assert reserved['maximum_page_answer_characters']>=cc.MINIMUM_PAGE_ANSWER_CHARACTERS
    assert 'proposed_page' not in reserved
    payload=cc.review_payload_base(value[2])
    assert 'proposed_page' not in payload
    cap=reserved['maximum_page_answer_characters']
    # This synthetic sizing object is not an authored company answer or model
    # record. Its exact compact size reaches the reserved aggregate JSON cap.
    sizing={'title':''};sizing['title']='x'*(cap-len(cc.compact_json(sizing)))
    assert len(cc.compact_json(sizing))==cap
    payload.update(maximum_page_answer_characters=cap,model_pin=PIN,options=deepcopy(dg.OPTIONS),
        page_response_id='response_3',page_response_hash='f'*64,
        page_request_digest=dg.canonical_digest(dg.request_json(value)),proposed_page=sizing)
    review=dg._request('document_page_complete_literal_context_review_v2',
        qc.LITERAL_PAGE_CONTEXT_REVIEW_INSTRUCTION,payload,dg.DocumentPageReview)
    assert cc.validate_signed_request_capacity(review)['signed_payload_characters']<=32000
    assert reserved['signed_review_fixed_characters']+cap<=32000


def test_review_reserve_blocks_complete_context_that_cannot_leave_a_minimum_real_answer():
    _,value=request();payload=deepcopy(value[2])
    payload['evidence']['retained_untrusted_context']='x'*32000
    value=dg._request(value[0],value[1],{k:v for k,v in payload.items() if k not in
        {'request_binding_digest','schema_order_digest','generation_schema_order_digest'}},value[3])
    with pytest.raises(dg.GenerationError,match='requires_model_source_group_split'):
        cc.review_capacity_reserve(value)


def test_navigation_binds_every_physical_group_order_original_uids_and_exact_compact_cost():
    inv,_=request();before=deepcopy(inv)
    nav=cc.planner_capacity_navigation(inv)
    assert nav['inventory_revision']==inv['inventory_revision']
    assert nav['source_topology_digest']==inv['source_map_topology_digest']
    assert nav['navigation_digest']==dg.canonical_digest({k:v for k,v in nav.items() if k!='navigation_digest'})
    for index,row in enumerate(nav['groups']):
        entry=dict(zip(nav['group_columns'],row));original=inv['source_map_topology'][index]
        group=dg._source_map_page_view(inv,original)
        assert entry['group_id']=='G'+str(index+1)
        assert entry['catalog_page_row_index']==index
        assert entry['physical_observation_digest']==original['physical_observation_digest']
        assert entry['complete_companion_compact_characters']==len(cc.compact_json(group))
        assert entry['original_model_unit_ids_digest']==dg.canonical_digest(list(dg.source_map_literal_lookup(group)))
    assert inv==before and nav['source_semantics']=='unassessed'


def test_explicit_material_32k_preserves_old_fields_and_binds_author_review_reserve():
    _,old=request()
    assert cc.material_role_options(old[2])==old[2]['options']
    assert 'material_context_profile' not in cc.review_payload_base(old[2])
    payload={key:deepcopy(value) for key,value in old[2].items() if key not in
        {'request_binding_digest','schema_order_digest','generation_schema_order_digest'}}
    payload['material_context_profile']=cc.MATERIAL_CONTEXT_PROFILE_32K
    payload['options']=cc.material_role_options(payload)
    current=dg._request(old[0],old[1],payload,old[3])
    assert current[2]['options']['context_tokens']==32768 and current[2]['options']['max_tokens']==2200
    assert current[2]['evidence']==old[2]['evidence']
    assert cc.validate_signed_request_capacity(current)['context_tokens']==32768
    reserve=cc.review_capacity_reserve(current,reviewer_pin=PIN)
    base=cc.review_payload_base(current[2])
    assert base['material_context_profile']==cc.MATERIAL_CONTEXT_PROFILE_32K
    # A synthetic exact-size capacity object exercises signed reviewer overhead;
    # it is never treated as an authored page or actual model response.
    cap=reserve['maximum_page_answer_characters']
    sizing={'title':''};sizing['title']='x'*(cap-len(cc.compact_json(sizing)))
    base.update(maximum_page_answer_characters=cap,model_pin=PIN,options=cc.material_role_options(current[2]),
        page_response_id='response_3',page_response_hash='f'*64,
        page_request_digest=dg.canonical_digest(dg.request_json(current)),proposed_page=sizing)
    review=dg._request('document_page_complete_literal_context_review_v2',
        qc.LITERAL_PAGE_CONTEXT_REVIEW_INSTRUCTION,base,dg.DocumentPageReview)
    assert cc.validate_signed_request_capacity(review)['context_tokens']==32768
    assert reserve['signed_review_fixed_characters']+cap<=32000
    for marker,context in ((cc.MATERIAL_CONTEXT_PROFILE_32K,16384),('unknown',32768)):
        altered=deepcopy(payload);altered['material_context_profile']=marker
        altered['options']['context_tokens']=context
        changed=dg._request(current[0],current[1],altered,current[3])
        with pytest.raises(ValueError):cc.validate_signed_request_capacity(changed)
