"""Lossless fictional vector metadata; no model or company answers."""
from copy import deepcopy

import pytest

from agents.inference import local_document_vision as vision
from agents.research import document_generation as dg
from agents.research import document_visual_literal_view as codec
from agents.research.document_evidence_manifest import build_document_manifest,attach_document_visual_text
from tests.research.test_document_native_visual_text import IDENTITY,source_bytes


def group():
    raw=source_bytes();native=build_document_manifest(raw,'pptx',**IDENTITY)
    derived=attach_document_visual_text(native,raw,expected_binding=native['binding'])
    inventory=dg.evidence_inventory([derived],catalog_encoding=dg.CATALOG_ENCODING_V6)
    value=dg._source_map_page_view(inventory,inventory['source_map_topology'][0])
    value['synthetic_repeated_metadata']=[{'qualifier':'Unreviewed literal observation requiring original source verification',
        'source_record':{'original_geometry':[1,2,3,4],'applied_transform':False}} for _ in range(12)]
    return value


def test_complete_group_and_original_position_view_roundtrip_without_duplicate_coordinates():
    original=group();before=deepcopy(original);encoded=codec.encode_visual_literal_view(original)
    binding=dg.canonical_digest(original)
    assert codec.decode_visual_literal_view(encoded,expected_group_digest=binding)==original
    assert codec.validate_visual_literal_view(original,encoded)
    assert codec.source_position_view(encoded,expected_group_digest=binding)==vision._coordinate_view(original)
    assert [[row[0],row[1],row[2]] for row in encoded['literal_units']]==[
        [row[0],row[1],row[2]] for row in original['literal_units']]
    positions=encoded['position_references']
    assert 'record_bounds' not in positions and 'rows' not in positions
    assert sum(len(run[3]) for run in positions['runs'])==len(vision._coordinate_view(original)['rows'])
    assert original==before


def test_external_original_binding_rejects_rehashed_literal_geometry_and_position_changes():
    original=group();encoded=codec.encode_visual_literal_view(original);binding=dg.canonical_digest(original)
    for mutation in ('literal','position','palette','expected'):
        changed=deepcopy(encoded);expected=binding
        if mutation=='literal':changed['literal_units'][0][2]+=' manually rewritten'
        elif mutation=='position':changed['position_references']['runs'][0][3]=[]
        elif mutation=='palette':changed['metadata_keysets'][0][0]='replaced_metadata_name'
        else:expected='f'*64
        changed['view_digest']=dg.canonical_digest({k:v for k,v in changed.items() if k!='view_digest'})
        with pytest.raises(ValueError):codec.decode_visual_literal_view(changed,expected_group_digest=expected)
