"""Lossless original-page encoding for opt-in local visual reading.

All literal strings and original metadata survive exact reconstruction. Position
references point into original geometry; no row, column or financial meaning is
inferred. The caller must bind the decoded group to its frozen original digest.
"""
from collections import Counter
from copy import deepcopy
import json
import math

from agents.research import document_generation as dg


CONTRACT='lossless-visual-literal-view-v1'
POSITION_SCOPE='Zero-based literal-row/path/frame references into exact original geometry; no inferred row, column, cell or applied transform.'
MAX_NODES=200000
MAX_DEPTH=80


def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _walk_strings(value,counter,depth=0):
    if depth>MAX_DEPTH:raise dg.GenerationError('visual_literal_metadata_depth_exceeded')
    if isinstance(value,str):counter[value]+=1
    elif isinstance(value,dict):
        if any(not isinstance(key,str) for key in value):
            raise dg.GenerationError('visual_literal_metadata_string_keys_required')
        for key in sorted(value):_walk_strings(value[key],counter,depth+1)
    elif isinstance(value,list):
        for item in value:_walk_strings(item,counter,depth+1)
    elif value is not None and type(value) not in (bool,int,float):
        raise dg.GenerationError('visual_literal_metadata_json_values_required')
    elif type(value) is float and not math.isfinite(value):
        raise dg.GenerationError('visual_literal_metadata_finite_values_required')


def _position_references(group):
    # Reuse the production eligibility/frame calculation without exposing any
    # duplicate coordinates in the new model payload.
    from agents.inference.local_document_vision import _coordinate_view
    positions=_coordinate_view(group)
    literals=group['literal_units']
    row_index={row[0]:index for index,row in enumerate(literals)}
    if len(row_index)!=len(literals):
        raise dg.GenerationError('visual_literal_duplicate_original_unit')
    paths=[];runs=[]
    def path_ref(value):
        if value not in paths:paths.append(value)
        return paths.index(value)
    def original_value(row,path):
        value=row
        for part in path:value=value[part]
        return value
    for uid,x,y,bounds_ref,frame_ref in positions['rows']:
        index=row_index[uid];relative=literals[index][3]
        if isinstance(relative,list) and len(relative)==6 and relative[0]=='emf':
            columns=group['native_emf_placement_columns']
            reference_path=[3,5,columns.index('reference')]
            bounds_path=[3,5,columns.index('record_bounds')]
        elif isinstance(relative,dict) and isinstance(relative.get('native_emf_placement'),dict):
            reference_path=[3,'native_emf_placement','reference']
            bounds_path=[3,'native_emf_placement','record_bounds']
        else:raise dg.GenerationError('visual_literal_original_position_path_unavailable')
        reference=original_value(literals[index],reference_path)
        point=(reference.get('x'),reference.get('y')) if isinstance(reference,dict) else tuple(reference)
        if point!=(x,y) or original_value(literals[index],bounds_path)!=positions['record_bounds'][bounds_ref]:
            raise dg.GenerationError('visual_literal_original_position_path_changed')
        signature=[frame_ref,path_ref(reference_path),path_ref(bounds_path)]
        if not runs or runs[-1][:3]!=signature:runs.append([*signature,[]])
        runs[-1][3].append(index)
    return {'run_columns':['frame_ref','reference_path_ref','record_bounds_path_ref','literal_row_indexes'],
        'runs':runs,'geometry_paths':paths,'frame_identity_digests':positions['frame_identity_digests'],
        'unavailable_literal_rows':[row_index[uid] for uid in positions['unavailable_unit_ids']],
        'scope':POSITION_SCOPE}


def encode_visual_literal_view(complete_group):
    """Encode every original group value; whole literal IDs/text stay visible."""
    if not isinstance(complete_group,dict) or not isinstance(complete_group.get('literal_units'),list):
        raise dg.GenerationError('complete_visual_literal_group_required')
    literals=complete_group['literal_units']
    if any(not isinstance(row,list) or len(row)!=4 or not isinstance(row[0],str) or
           not isinstance(row[2],str) for row in literals):
        raise dg.GenerationError('complete_visual_literal_rows_required')
    # Canonical literal lookup checks original contexts and lossless locators.
    if len(dg.source_map_literal_lookup(complete_group))!=complete_group['literal_unit_count']:
        raise dg.GenerationError('complete_visual_literal_inventory_changed')
    metadata={key:value for key,value in complete_group.items() if key!='literal_units'}
    counter=Counter();_walk_strings(metadata,counter)
    for row in literals:_walk_strings(row[3],counter)
    # Select repeated-string palettes by serialized cost alone, never semantics.
    # Reserve six index digits, so every retained reference is profitable even
    # at the maximum bounded node count.
    strings=sorted(value for value,count in counter.items() if count>=2 and
        count*len(_json(value))>len(_json(value))+count*len('{"s":999999}')+2)
    string_index={value:index for index,value in enumerate(strings)}
    keysets=[];keyset_index={};nodes=0
    def encode(value,depth=0):
        nonlocal nodes
        nodes+=1
        if nodes>MAX_NODES or depth>MAX_DEPTH:
            raise dg.GenerationError('visual_literal_metadata_bound_exceeded')
        if isinstance(value,str):return {'s':string_index[value]} if value in string_index else value
        if isinstance(value,dict):
            keys=tuple(sorted(value))
            if keys not in keyset_index:
                keyset_index[keys]=len(keysets);keysets.append(list(keys))
            return {'o':[keyset_index[keys],[encode(value[key],depth+1) for key in keys]]}
        if isinstance(value,list):return [encode(item,depth+1) for item in value]
        return deepcopy(value)
    encoded_metadata=encode(metadata)
    encoded_rows=[[deepcopy(row[0]),deepcopy(row[1]),deepcopy(row[2]),encode(row[3])] for row in literals]
    body={'contract':CONTRACT,'source_group_digest':dg.canonical_digest(complete_group),
        'literal_columns':['unit_id','context_ref','whole_original_content','relative_locator'],
        'literal_units':encoded_rows,'metadata_keysets':keysets,'shared_strings':strings,
        'metadata':encoded_metadata,'position_references':_position_references(complete_group),
        'metadata_encoding':'All dictionaries are {o:[zero-based keyset ref,parallel values]}; repeated metadata strings are {s:zero-based string ref}; arrays/scalars retain exact values. Literal unit IDs/context/text are whole originals.'}
    return {**body,'view_digest':dg.canonical_digest(body)}


def decode_visual_literal_view(view,*,expected_group_digest):
    """Restore the entire original group against an external frozen binding."""
    expected_keys={'contract','source_group_digest','literal_columns','literal_units','metadata_keysets',
                   'shared_strings','metadata','position_references','metadata_encoding','view_digest'}
    if (not isinstance(view,dict) or set(view)!=expected_keys or view.get('contract')!=CONTRACT or
            view.get('source_group_digest')!=expected_group_digest or
            view.get('view_digest')!=dg.canonical_digest({k:v for k,v in view.items() if k!='view_digest'})):
        raise dg.GenerationError('visual_literal_view_original_binding_changed')
    keysets,strings=view['metadata_keysets'],view['shared_strings']
    if (not isinstance(keysets,list) or not isinstance(strings,list) or
            any(not isinstance(keys,list) or any(not isinstance(key,str) for key in keys) or
                keys!=sorted(set(keys)) for keys in keysets) or
            len({tuple(keys) for keys in keysets})!=len(keysets) or
            any(not isinstance(value,str) for value in strings) or strings!=sorted(set(strings))):
        raise dg.GenerationError('visual_literal_metadata_palette_changed')
    nodes=0
    def decode(value,depth=0):
        nonlocal nodes
        nodes+=1
        if nodes>MAX_NODES or depth>MAX_DEPTH:
            raise dg.GenerationError('visual_literal_metadata_bound_exceeded')
        if isinstance(value,dict):
            if set(value)=={'s'}:
                index=value['s']
                if type(index) is not int or not 0<=index<len(strings):
                    raise dg.GenerationError('visual_literal_string_reference_changed')
                return strings[index]
            if set(value)=={'o'}:
                record=value['o']
                if not isinstance(record,list) or len(record)!=2 or type(record[0]) is not int or not 0<=record[0]<len(keysets):
                    raise dg.GenerationError('visual_literal_keyset_reference_changed')
                keys=keysets[record[0]];values=record[1]
                if not isinstance(values,list) or len(values)!=len(keys):
                    raise dg.GenerationError('visual_literal_parallel_metadata_changed')
                return {key:decode(item,depth+1) for key,item in zip(keys,values)}
            raise dg.GenerationError('visual_literal_metadata_tag_changed')
        if isinstance(value,list):return [decode(item,depth+1) for item in value]
        if value is None or type(value) in (str,bool,int):return deepcopy(value)
        if type(value) is float and math.isfinite(value):return value
        raise dg.GenerationError('visual_literal_metadata_json_values_required')
    metadata=decode(view['metadata'])
    if not isinstance(metadata,dict) or 'literal_units' in metadata:
        raise dg.GenerationError('visual_literal_metadata_root_changed')
    rows=view['literal_units']
    if not isinstance(rows,list) or any(not isinstance(row,list) or len(row)!=4 for row in rows):
        raise dg.GenerationError('visual_literal_original_row_shape_changed')
    original={**metadata,'literal_units':[[deepcopy(row[0]),deepcopy(row[1]),deepcopy(row[2]),decode(row[3])]
                                          for row in rows]}
    if dg.canonical_digest(original)!=expected_group_digest:
        raise dg.GenerationError('visual_literal_reconstructed_original_changed')
    if encode_visual_literal_view(original)!=view:
        raise dg.GenerationError('visual_literal_encoding_noncanonical_or_positions_changed')
    return original


def validate_visual_literal_view(complete_group,view):
    if decode_visual_literal_view(view,expected_group_digest=dg.canonical_digest(complete_group))!=complete_group:
        raise dg.GenerationError('visual_literal_original_projection_changed')
    return True


def source_position_view(view,*,expected_group_digest):
    """Exact historical position-view reconstruction, for replay/validation."""
    from agents.inference.local_document_vision import _coordinate_view
    return _coordinate_view(decode_visual_literal_view(view,expected_group_digest=expected_group_digest))
