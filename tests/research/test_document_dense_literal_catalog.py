"""Lossless representation proofs, not company answers or financial labels."""
from copy import deepcopy
import json

import pytest

from agents.research import document_generation as dg
from agents.research import document_literal_catalog as codec
from tests.research.test_document_generation import manifest
from tests.research.test_document_native_visual_text import source_bytes,IDENTITY
from agents.research.document_evidence_manifest import build_document_manifest


def inventory(*,visual=False):
    source=build_document_manifest(source_bytes(),'pptx',media_text_profile='native-pptx-visual-text-v1',**IDENTITY) if visual else manifest()
    return dg.evidence_inventory([source],catalog_encoding=dg.CATALOG_ENCODING_V5)


def normalized(catalog):
    value=codec.decode_complete_literal_catalog(catalog)
    value['catalog_encoding']=codec.ENCODING
    value.pop('catalog_digest')
    return value


@pytest.mark.parametrize('visual',[False,True])
def test_dense_decode_retains_every_original_literal_id_full_native_grids_geometry_and_binding(visual):
    inv=inventory(visual=visual);before=deepcopy(inv)
    prior=codec.complete_literal_catalog(inv)
    compact_prior=codec.complete_literal_catalog(inv,catalog_encoding=codec.ENCODING_V2)
    dense=codec.complete_literal_catalog(inv,catalog_encoding=codec.ENCODING_V3)
    assert normalized(dense)==normalized(prior)==normalized(compact_prior)
    assert dense['inventory_revision']==prior['inventory_revision']==inv['inventory_revision']
    assert dense['source_literal_provenance_digest']==prior['source_literal_provenance_digest']
    assert codec.validate_complete_literal_catalog(inv,dense)
    assert inv==before
    assert codec.complete_literal_catalog(inv)==prior
    assert codec.complete_literal_catalog(inv,catalog_encoding=codec.ENCODING_V2)==compact_prior
    assert all(type(n) is int for t in dense['table_navigation'] for row in t['model_cell_unit_ids'] for n in row)
    assert dense['unit_index_encoding']=={'prefix':'U','index_origin':1,'encoding':'exact_original_U_integer_suffix'}
    # This small fixture may contain no long runs. Completeness, not relative
    # savings on a tiny document, is the software property under test.
    assert dense['literal_coverage']==prior['literal_coverage']


def test_kind_or_identifier_discontinuity_splits_run_without_reordering_or_assigning_new_ids():
    body={'page_columns':codec.PAGE_COLUMNS,'pages':[['S1',1,'pptx',
        [['U1','text','  exact '],['U2','text',''],['U4','text','after gap'],['U5','notes','note']],
        [],[],{},1,'unassessed',0]],'table_navigation':[]}
    inv={'units':[{'model_unit_id':uid} for uid in ['U1','U2','U4','U5']]}
    codec._dense_original_literals(body,inv)
    assert body['pages'][0][3]==[[0,1,['  exact ','']],[0,4,['after gap']],[1,5,['note']]]


@pytest.mark.parametrize('uid',['U01','u1','U0','U5001','other','U+1'])
def test_dense_conversion_refuses_noncanonical_or_out_of_bound_original_identifiers(uid):
    with pytest.raises(dg.GenerationError):codec._unit_index(uid)


@pytest.mark.parametrize('change',['text','start','kind','table_id'])
def test_rehashed_dense_representation_cannot_override_original_source_binding(change):
    inv=inventory();dense=codec.complete_literal_catalog(inv,catalog_encoding=codec.ENCODING_V3)
    col=dense['page_columns'].index('literal_units')
    if change=='text':dense['pages'][0][col][0][2][0]='tampered original'
    elif change=='start':dense['pages'][0][col][0][1]+=1
    elif change=='kind':dense['literal_kinds'][0]='altered_kind'
    else:dense['table_navigation'][0]['model_cell_unit_ids'][0][0]+=1
    dense['catalog_digest']=dg.canonical_digest({k:v for k,v in dense.items() if k!='catalog_digest'})
    with pytest.raises(dg.GenerationError,match='complete_original_literal_catalog_changed'):
        codec.validate_complete_literal_catalog(inv,dense)


@pytest.mark.parametrize('change',['prefix','bool_index','empty_run','duplicate_unit'])
def test_dense_decoder_rejects_ambiguous_or_invalid_encoding_even_if_self_hash_resealed(change):
    dense=codec.complete_literal_catalog(inventory(),catalog_encoding=codec.ENCODING_V3)
    col=dense['page_columns'].index('literal_units')
    runs=dense['pages'][0][col]
    if change=='prefix':dense['unit_index_encoding']['prefix']='different'
    elif change=='bool_index':runs[0][1]=True
    elif change=='empty_run':runs[0][2]=[]
    else:runs.append(deepcopy(runs[0]))
    dense['catalog_digest']=dg.canonical_digest({k:v for k,v in dense.items() if k!='catalog_digest'})
    with pytest.raises(dg.GenerationError):codec.decode_complete_literal_catalog(dense)
