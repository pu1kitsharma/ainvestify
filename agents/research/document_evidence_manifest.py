"""Lossless private PDF/PPTX observations, exact coordinates and bounded retrieval.

No model, OCR, financial calculation, chart interpretation or approval occurs.
Original bytes remain the authority. Source text is untrusted document data.
"""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import hashlib
import json
import math
import posixpath
from typing import Any

from defusedxml import ElementTree as ET

from delivery.inspection import _parts
from delivery.storage import MAX_FILE_BYTES

CONTRACT = 'private-document-evidence-manifest-v1'
RETRIEVAL = 'private-document-evidence-retrieval-v1'
NS = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
REL = NS['r']
SCOPE = {
    'source_status': 'reported_unverified',
    'semantic_status': 'unassessed',
    'financial_validation': 'not_established',
    'currency_unit_period_semantics': 'unassessed',
    'chart_semantics': 'unassessed',
    'release_status': 'diagnostic_only_no_release',
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _tag(node):
    return node.tag.rsplit('}', 1)[-1]


def _xml(node):
    return {'tag': node.tag, 'attributes': dict(node.attrib), 'text': node.text,
            'tail': node.tail, 'children': [_xml(child) for child in node]}


def _safe(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Nonfinite document coordinate')
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    raise TypeError('Unsupported PDF observation type')


def _identity(tenant_id, deal_id, document_id):
    for value in (tenant_id, deal_id, document_id):
        if (not isinstance(value, str) or not value or len(value) > 256 or
                any(ord(c) < 32 for c in value)):
            raise ValueError('Private document identity required')


def _unit(manifest, kind, locator, content, coordinates=None, **extra):
    row = {'kind': kind, 'source_id': manifest['binding']['source_sha256'],
           'source_locator': locator, 'content': content,
           'text': content if isinstance(content, str) else '',
           'content_sha256': digest(content), 'coordinates': coordinates or {},
           **SCOPE, **extra}
    row['id'] = 'u_' + digest({'source': row['source_id'], 'kind': kind,
                             'locator': locator})[:32]
    manifest['units'].append(row)
    return row


def _relationships(archive, part):
    folder, name = posixpath.split(part)
    relpart = posixpath.join(folder, '_rels', name + '.rels')
    if relpart not in archive.namelist():
        return []
    result = []
    for rel in ET.fromstring(archive.read(relpart)):
        row = dict(rel.attrib)
        target = row.get('Target', '')
        if row.get('TargetMode') != 'External':
            resolved = (target.lstrip('/') if target.startswith('/') else
                        posixpath.normpath(posixpath.join(folder, target)))
            if resolved.startswith('../') or resolved not in archive.namelist():
                raise ValueError('Missing or unsafe package relationship')
            row['resolved_part'] = resolved
        else:
            row['dependency_status'] = 'not_fetched_unassessed'
        result.append(row)
    return result


def _geometry(node):
    xfrm = node.find('p:spPr/a:xfrm', NS)
    if xfrm is None:
        xfrm = node.find('p:xfrm', NS)
    if xfrm is None:
        xfrm = node.find('p:grpSpPr/a:xfrm', NS)
    if xfrm is None:
        return {'coordinate_system': 'EMU_local_to_parent_group', 'transform': None}
    return {'coordinate_system': 'EMU_local_to_parent_group', 'transform': _xml(xfrm)}


def _text_paragraphs(node):
    paragraphs = []
    for paragraph in node.findall('./p:txBody/a:p', NS):
        pieces = []
        for child in paragraph:
            if _tag(child) in {'r', 'fld'}:
                pieces.extend(text.text or '' for text in child.findall('a:t', NS))
            elif _tag(child) == 'br':
                pieces.append('\n')
        paragraphs.append({'text': ''.join(pieces), 'xml': _xml(paragraph)})
    return paragraphs


def _table(manifest, table, locator, geometry):
    table_id = 't_' + digest({'source': manifest['binding']['source_sha256'],
                             'locator': locator})[:32]
    result = {'id': table_id, 'source_id': manifest['binding']['source_sha256'],
              'source_locator': locator, 'coordinates': geometry, 'rows': [],
              'cells': [], 'native_xml': _xml(table), **SCOPE}
    rows = table.findall('a:tr', NS)
    widths = [int(col.attrib['w']) for col in table.findall('a:tblGrid/a:gridCol', NS)]
    heights = [int(row.attrib['h']) for row in rows]
    if any(value < 0 for value in widths+heights):
        raise ValueError('Invalid native table dimensions')
    result['grid_widths_emu'] = widths
    result['row_heights_emu'] = heights
    for row_number, tr in enumerate(rows, 1):
        texts = []
        for column, tc in enumerate(tr.findall('a:tc', NS), 1):
            text = '\n'.join(''.join(t.text or '' for t in p.findall('.//a:t', NS))
                             for p in tc.findall('a:txBody/a:p', NS))
            where = dict(locator, table_id=table_id, row=row_number, column=column)
            column_span = int(tc.attrib.get('gridSpan', '1'))
            row_span = int(tc.attrib.get('rowSpan', '1'))
            if column_span < 1 or row_span < 1 or column+column_span-1 > len(widths) or row_number+row_span-1 > len(heights):
                raise ValueError('Native table cell span exceeds retained grid')
            x0, y0 = sum(widths[:column-1]), sum(heights[:row_number-1])
            cell_geometry = {'table_shape_transform': geometry,
                'table_local_bbox': [x0,y0,sum(widths[:column-1+column_span]),
                                    sum(heights[:row_number-1+row_span])],
                'coordinate_system': 'EMU_table_local_untransformed',
                'covered_cell': tc.attrib.get('hMerge') == '1' or tc.attrib.get('vMerge') == '1'}
            unit = _unit(manifest, 'table_cell', where, text, cell_geometry,
                         merge_attributes=dict(tc.attrib), table_id=table_id)
            result['cells'].append({'id': unit['id'], 'unit_id': unit['id'],
                                    'row': row_number, 'column': column, 'text': text,
                                    'coordinates': cell_geometry,
                                    'merge_attributes': dict(tc.attrib),
                                    'native_xml': _xml(tc)})
            texts.append(text)
        result['rows'].append(texts)
    manifest['tables'].append(result)
    return table_id


def _chart(manifest, archive, chart_part, locator, geometry):
    tree = ET.fromstring(archive.read(chart_part))
    payload = {'part': chart_part, 'native_xml': _xml(tree),
               'relationships': _relationships(archive, chart_part),
               'cached_values_origin': 'stored_source_observation_not_recalculated',
               'financial_validation': 'not_established'}
    unit = _unit(manifest, 'chart', dict(locator, chart_part=chart_part), payload, geometry)
    # Retain each exact formula/cache literal as a separately retrievable citation.
    def walk(node, path):
        if _tag(node) in {'v', 'f', 'formatCode', 'ptCount'}:
            _unit(manifest, 'chart_literal', dict(locator, chart_part=chart_part,
                    xml_path=path), node.text or '', geometry, chart_unit_id=unit['id'],
                    literal_kind=_tag(node), xml_attributes=dict(node.attrib),
                    cached_values_origin='stored_source_observation_not_recalculated')
        for index, child in enumerate(node):
            walk(child, path + '/' + _tag(child) + '[' + str(index + 1) + ']')
    walk(tree, '/'+_tag(tree))
    manifest['charts'].append({'unit_id': unit['id'], **payload,
                               'source_locator': locator, 'coordinates': geometry})
    return unit['id']


def _pptx(content, manifest):
    with _parts(content) as archive:
        names = archive.namelist()
        if '[Content_Types].xml' not in names or 'ppt/presentation.xml' not in names:
            raise ValueError('Wrong presentation package type')
        manifest['package_parts'] = [{'part': name, 'sha256': hashlib.sha256(
            archive.read(name)).hexdigest(), 'byte_count': archive.getinfo(name).file_size}
            for name in names]
        presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
        size = presentation.find('p:sldSz', NS)
        manifest['canvas'] = {'coordinate_system': 'EMU', 'slide_size':
                              dict(size.attrib) if size is not None else None}
        relations = _relationships(archive, 'ppt/presentation.xml')
        manifest['presentation_relationships'] = relations
        by_id = {rel['Id']: rel for rel in relations}
        slide_ids = presentation.findall('p:sldIdLst/p:sldId', NS)
        if len(slide_ids) > 500:
            raise ValueError('Presentation exceeds complete parser slide limit')
        for number, entry in enumerate(slide_ids, 1):
            rel = by_id.get(entry.attrib.get('{'+REL+'}id'))
            if rel is None or 'resolved_part' not in rel:
                raise ValueError('Missing slide relationship')
            part = rel['resolved_part']
            tree = ET.fromstring(archive.read(part))
            rels = _relationships(archive, part)
            relmap = {row['Id']: row for row in rels}
            slide = {'slide': number, 'part': part, 'slide_id': dict(entry.attrib),
                     'hidden': tree.attrib.get('show') == '0',
                     'relationships': rels, 'shapes': [], 'notes': [],
                     'visual_semantics': 'unassessed', 'raw_xml_sha256':
                     hashlib.sha256(archive.read(part)).hexdigest()}

            def shapes(parent, prefix=()):
                for order, shape in enumerate(parent, 1):
                    kind = _tag(shape)
                    if kind in {'nvGrpSpPr', 'grpSpPr', 'extLst'}:
                        continue
                    path = list(prefix + (order,))
                    where = {'format': 'pptx', 'slide': number, 'part': part,
                             'shape_path': path}
                    nv = shape.find('.//p:cNvPr', NS)
                    geo = _geometry(shape)
                    record = {'shape_path': path, 'shape_type': kind,
                              'attributes': dict(nv.attrib) if nv is not None else {},
                              'coordinates': geo, 'native_xml': _xml(shape),
                              'text_unit_ids': [], 'table_ids': [], 'chart_unit_ids': [],
                              'semantic_status': 'unassessed'}
                    for paragraph_number, paragraph in enumerate(_text_paragraphs(shape), 1):
                        unit = _unit(manifest, 'text', dict(where, paragraph=paragraph_number),
                                     paragraph['text'], geo, paragraph_xml=paragraph['xml'])
                        record['text_unit_ids'].append(unit['id'])
                    for index, table in enumerate([] if kind == 'grpSp' else shape.findall('.//a:tbl', NS), 1):
                        record['table_ids'].append(_table(manifest, table,
                                                    dict(where, table=index), geo))
                    for chart in ([] if kind == 'grpSp' else shape.findall('.//c:chart', NS)):
                        chartrel = relmap.get(chart.attrib.get('{'+REL+'}id'))
                        if chartrel is None or 'resolved_part' not in chartrel:
                            manifest['unsupported'].append(dict(where,
                                code='external_or_missing_chart_dependency'))
                        else:
                            record['chart_unit_ids'].append(_chart(manifest, archive,
                                chartrel['resolved_part'], where, geo))
                    # Group children have their own exact local transforms and path.
                    slide['shapes'].append(record)
                    if kind == 'grpSp':
                        shapes(shape, tuple(path))
                    elif not record['text_unit_ids'] and not record['table_ids'] and not record['chart_unit_ids']:
                        manifest['unsupported'].append(dict(where, code='visual_object_semantics_unassessed',
                                                               shape_type=kind))
            sp_tree = tree.find('p:cSld/p:spTree', NS)
            if sp_tree is None:
                raise ValueError('Slide shape tree missing')
            shapes(sp_tree)
            for rel in rels:
                if rel['Type'].endswith('/notesSlide') and 'resolved_part' in rel:
                    note_part = rel['resolved_part']
                    note_tree = ET.fromstring(archive.read(note_part))
                    note = {'part': note_part, 'native_xml': _xml(note_tree),
                            'unit_ids': [], 'relationships': _relationships(archive, note_part)}
                    for shape_number, shape in enumerate(note_tree.findall('.//p:sp', NS), 1):
                        for para_number, para in enumerate(_text_paragraphs(shape), 1):
                            unit = _unit(manifest, 'notes', {'format':'pptx', 'slide':number,
                                'part':note_part, 'shape_path':[shape_number], 'paragraph':para_number},
                                para['text'], _geometry(shape), paragraph_xml=para['xml'])
                            note['unit_ids'].append(unit['id'])
                    slide['notes'].append(note)
            manifest['slides'].append(slide)
        manifest['embedded_parts'] = [dict(row, interpretation_status='unassessed_not_executed')
            for row in manifest['package_parts'] if '/embeddings/' in row['part']]
        for rel in [*relations, *[rel for slide in manifest['slides'] for rel in slide['relationships']]]:
            if rel.get('TargetMode') == 'External':
                manifest['unsupported'].append({'code': 'external_dependency_not_fetched',
                                                 'relationship': rel})
        for row in manifest['package_parts']:
            if any(marker in row['part'].lower() for marker in ('vbaproject', 'activex/', 'oleobject')):
                manifest['unsupported'].append({'code':'active_or_embedded_object_not_executed', 'part':row['part']})


def _pdf(content, manifest):
    import pdfplumber
    with pdfplumber.open(BytesIO(content)) as pdf:
        if len(pdf.pages) > 500:
            raise ValueError('PDF exceeds complete parser page limit')
        for number, page in enumerate(pdf.pages, 1):
            observations = {'page': number, 'width': page.width, 'height': page.height,
                            'rotation': page.rotation, 'bbox': list(page.bbox),
                            'characters': [], 'text_unit_ids': [], 'table_ids': [],
                            'visual_objects': {}, 'visual_semantics': 'unassessed'}
            for char in page.chars:
                observations['characters'].append(_safe({key: value for key, value in char.items()
                    if key in {'text','x0','y0','x1','y1','top','bottom','doctop','width','height',
                               'fontname','size','adv','upright','matrix','stroking_color','non_stroking_color'}}))
            for line_number, line in enumerate(page.extract_text_lines(return_chars=False) or [], 1):
                geo = {key: _safe(line[key]) for key in ('x0','top','x1','bottom') if key in line}
                unit = _unit(manifest, 'text', {'format':'pdf','page':number,'line':line_number},
                             line['text'], geo)
                observations['text_unit_ids'].append(unit['id'])
            for table_number, table in enumerate(page.find_tables(), 1):
                locator = {'format':'pdf','page':number,'table':table_number}
                table_id = 't_' + digest({'source':manifest['binding']['source_sha256'],
                                         'locator':locator})[:32]
                rows = table.extract() or []
                result = {'id':table_id,'source_id':manifest['binding']['source_sha256'],
                          'source_locator':locator, 'coordinates':{'bbox':list(table.bbox)},
                          'rows':rows, 'cells':[], **SCOPE}
                for row_number, row in enumerate(rows, 1):
                    cell_boxes = table.rows[row_number-1].cells
                    for column, text in enumerate(row, 1):
                        box = cell_boxes[column-1] if column <= len(cell_boxes) else None
                        coordinates = {'bbox':list(box)} if box is not None else {'bbox':None}
                        unit = _unit(manifest, 'table_cell', dict(locator,table_id=table_id,
                            row=row_number,column=column), text or '', coordinates, table_id=table_id,
                            null_source_cell=text is None)
                        result['cells'].append({'id':unit['id'],'unit_id':unit['id'],
                            'row':row_number,'column':column,'text':text, 'coordinates':coordinates})
                manifest['tables'].append(result)
                observations['table_ids'].append(table_id)
            for kind in ('images','curves','rects','lines'):
                keep = {'x0','y0','x1','y1','top','bottom','width','height','pts','path',
                        'fill','stroke','linewidth','stroking_color','non_stroking_color',
                        'name','srcsize','imagemask','bits','mcid','tag','object_type'}
                observations['visual_objects'][kind] = [_safe({key:value for key,value in obj.items()
                    if key in keep}) for obj in getattr(page,kind)]
            if observations['visual_objects']['images'] or observations['visual_objects']['curves']:
                manifest['unsupported'].append({'format':'pdf','page':number,
                    'code':'image_or_vector_chart_semantics_unassessed_no_ocr'})
            if not observations['characters']:
                manifest['unsupported'].append({'format':'pdf','page':number,
                                                'code':'no_native_text_ocr_unrun'})
            manifest['pages'].append(observations)


def document_unit_observation(unit):
    """Prompt view retains exact content/binding without repeating style XML.

    Full native XML remains sealed in the manifest and original package. Removing
    duplicated style data from this view never turns a cache or OCR into fact.
    """
    keys = {'id','kind','source_id','source_locator','content','text','content_sha256',
            'coordinates', *SCOPE, 'origin','confidence','engine','language_correction',
            'cached_values_origin','literal_kind','xml_attributes','chart_unit_id',
            'table_id','merge_attributes','null_source_cell'}
    return {key:deepcopy(value) for key,value in unit.items() if key in keys}


def _packets(manifest, max_chars):
    packets, current = [], []
    excluded = []
    def payload(rows):
        return {'source_sha256':manifest['binding']['source_sha256'],
                'format':manifest['binding']['format'], 'units':rows, **SCOPE}
    for original in manifest['units']:
        unit = document_unit_observation(original)
        if len(canonical(payload([unit]))) > max_chars:
            excluded.append({'unit_id':unit['id'],'reason':'exact_unit_exceeds_packet_limit',
                             'character_count':len(canonical(payload([unit])))})
            continue
        if current and len(canonical(payload(current+[unit]))) > max_chars:
            packets.append(payload(current))
            current=[]
        current.append(unit)
    if current:
        packets.append(payload(current))
    manifest['packets'] = [{'id':'p_'+str(number), 'unit_ids':[u['id'] for u in row['units']],
                            'passage':canonical(row), 'passage_sha256':digest(row)}
                           for number,row in enumerate(packets,1)]
    manifest['unpacketized_units'] = excluded
    manifest['bounded_packet_coverage'] = 'complete' if not excluded else 'partial'
    literal_ids={unit['id'] for unit in manifest['units'] if unit['kind'] != 'chart'}
    manifest['unpacketized_literal_units']=[row for row in excluded if row['unit_id'] in literal_ids]
    manifest['bounded_literal_coverage']='complete' if not manifest['unpacketized_literal_units'] else 'partial'


def build_document_manifest(content: bytes, fmt: str, *, tenant_id: str, deal_id: str,
                            document_id: str, packet_chars: int = 3400,
                            media_text_profile: str | None = None) -> dict[str, Any]:
    _identity(tenant_id, deal_id, document_id)
    if fmt not in {'pdf','pptx'} or not isinstance(content,bytes) or not 0 < len(content) <= MAX_FILE_BYTES:
        raise ValueError('Supported private PDF/PPTX bytes required')
    if not isinstance(packet_chars,int) or isinstance(packet_chars,bool) or not 800 <= packet_chars <= 4000:
        raise ValueError('Bounded private document packet limit required')
    if media_text_profile is not None and (fmt != 'pptx' or media_text_profile not in
            {'native-emf-literals-v1','native-pptx-visual-text-v1'}):
        raise ValueError('Explicit native EMF presentation profile required')
    manifest = {'contract':CONTRACT, 'binding':{'tenant_id':tenant_id,'deal_id':deal_id,
        'document_id':document_id,'source_sha256':hashlib.sha256(content).hexdigest(),'format':fmt},
        'source_byte_count':len(content), 'units':[], 'tables':[], 'charts':[],
        'pages':[], 'slides':[], 'unsupported':[], **SCOPE,
        'native_retention_status':'complete', 'visual_coverage':'unassessed',
        'ocr_status':'not_performed', 'chart_recalculation':'not_performed'}
    (_pdf if fmt == 'pdf' else _pptx)(content,manifest)
    ids=[unit['id'] for unit in manifest['units']]
    if len(ids) != len(set(ids)):
        raise ValueError('Ambiguous retained document coordinates')
    _packets(manifest,packet_chars)
    manifest['counts']={'pages':len(manifest['pages']), 'slides':len(manifest['slides']),
        'units':len(manifest['units']), 'tables':len(manifest['tables']),
        'table_cells':sum(len(t['cells']) for t in manifest['tables']),
        'charts':len(manifest['charts']), 'notes':sum(len(s['notes']) for s in manifest['slides']),
        'shapes':sum(len(s['shapes']) for s in manifest['slides']),
        'native_characters':sum(len(p['characters']) for p in manifest['pages']),
        'packets':len(manifest['packets']), 'unpacketized_units':len(manifest['unpacketized_units'])}
    manifest['manifest_digest']=digest(manifest)
    if media_text_profile is not None:
        if media_text_profile=='native-pptx-visual-text-v1':
            return attach_document_visual_text(manifest,content,expected_binding=manifest['binding'],packet_chars=packet_chars)
        return attach_document_emf(manifest,content,expected_binding=manifest['binding'],packet_chars=packet_chars)
    return manifest


def attach_document_emf(manifest, content, *, expected_binding, packet_chars=3400):
    """Append native EMF text records without altering original observations.

    This is literal binary extraction, not OCR, a reconstructed chart/table,
    financial interpretation or approval. The default manifest stays unchanged.
    """
    from agents.research.emf_text import CONTRACT as emf_contract, extract_emf_text
    if (not isinstance(manifest,dict) or manifest.get('contract') != CONTRACT or
            manifest.get('binding') != expected_binding or expected_binding.get('format') != 'pptx' or
            manifest.get('manifest_digest') != digest({k:v for k,v in manifest.items() if k != 'manifest_digest'}) or
            any(manifest.get(key) != value for key,value in SCOPE.items()) or not isinstance(content,bytes) or
            hashlib.sha256(content).hexdigest() != expected_binding.get('source_sha256')):
        raise ValueError('Private EMF document source/scope/integrity mismatch')
    if not isinstance(packet_chars,int) or isinstance(packet_chars,bool) or not 800<=packet_chars<=4000:
        raise ValueError('Bounded private EMF packet limit required')
    if manifest.get('media_text_profile') is not None:
        if manifest['media_text_profile'] != 'native-emf-literals-v1':
            raise ValueError('Immutable media text profile changed')
        identity={key:expected_binding[key] for key in ('tenant_id','deal_id','document_id')}
        native=build_document_manifest(content,'pptx',packet_chars=packet_chars,**identity)
        if attach_document_emf(native,content,expected_binding=expected_binding,packet_chars=packet_chars) != manifest:
            raise ValueError('Immutable native EMF observations changed')
        return deepcopy(manifest)
    result=deepcopy(manifest)
    result.pop('manifest_digest')
    result['media_text_profile']='native-emf-literals-v1'
    result['native_emf_observations']=[]
    result['emf_text_bindings']=[]
    with _parts(content) as archive:
        media={name:extract_emf_text(archive.read(name)) for name in archive.namelist()
               if name.lower().startswith('ppt/media/') and name.lower().endswith('.emf')}
        for part,observations in media.items():
            result['native_emf_observations'].append({'part':part,**observations,
                'text_retention_status':'literal_records_only',**SCOPE})
        def embeds(node):
            if node['tag'].rsplit('}',1)[-1]=='blip':
                rid=node['attributes'].get('{'+REL+'}embed')
                if rid:yield rid
            for child in node['children']:yield from embeds(child)
        for slide in result['slides']:
            relations={rel['Id']:rel for rel in slide['relationships']}
            for shape in slide['shapes']:
                if shape['shape_type']=='grpSp':continue  # Children have exact own paths.
                for image_index,rid in enumerate(embeds(shape['native_xml']),1):
                    relation=relations.get(rid)
                    if relation is None or 'resolved_part' not in relation:continue
                    part=relation['resolved_part']
                    if part not in media:continue
                    extracted=media[part]
                    where={'format':'pptx','slide':slide['slide'],'part':slide['part'],
                        'shape_path':shape['shape_path'],'image_index':image_index,
                        'relationship_id':rid,'media_part':part,'media_sha256':extracted['media_sha256']}
                    binding={'source_locator':where,'coordinates':deepcopy(shape['coordinates']),
                        'media_sha256':extracted['media_sha256'],'emf_contract':emf_contract,'unit_ids':[],**SCOPE}
                    for observation in extracted['observations']:
                        if observation.get('text') is None:continue  # Glyph/encoding unresolved: raw retained only.
                        locator={**where,'emf_record_index':observation['record_index'],
                            'emf_record_offset':observation['record_offset'],
                            'emf_string_index':observation.get('string_index',0),
                            'emf_record_type':observation['record_type']}
                        unit=_unit(result,'emf_text',locator,observation['text'],
                            {'slide_shape_transform':deepcopy(shape['coordinates']),
                             'coordinate_system':'EMF_logical_untransformed',
                             'native_emf':deepcopy(observation)},
                            origin='native_emf_text_record_unverified',
                            media_sha256=extracted['media_sha256'],
                            emf_font=deepcopy(observation.get('font')),
                            extraction_status='literal_binary_text_not_chart_or_table')
                        binding['unit_ids'].append(unit['id'])
                    for finding in extracted['unsupported']:
                        result['unsupported'].append({**where,'code':'native_emf_semantics_unassessed',
                            'emf_finding':deepcopy(finding)})
                    result['emf_text_bindings'].append(binding)
    _packets(result,packet_chars)
    result['counts'].update(units=len(result['units']),packets=len(result['packets']),
        unpacketized_units=len(result['unpacketized_units']),
        emf_media_parts=len(result['native_emf_observations']),
        emf_image_bindings=len(result['emf_text_bindings']),
        emf_text_units=sum(len(row['unit_ids']) for row in result['emf_text_bindings']))
    result['emf_text_status']='native_literal_records_unverified'
    result['manifest_digest']=digest(result)
    return result


def attach_document_visual_text(manifest,content,*,expected_binding,packet_chars=3400):
    """Native EMF and SmartArt literals, including explicitly separate caches.

    Every string keeps its original part, XML path or binary record. Neither
    record geometry nor cached SmartArt supplies chart/table/team judgments.
    """
    if manifest.get('media_text_profile')=='native-pptx-visual-text-v1':
        identity={key:expected_binding[key] for key in ('tenant_id','deal_id','document_id')}
        native=build_document_manifest(content,'pptx',packet_chars=packet_chars,**identity)
        rebuilt=attach_document_visual_text(native,content,expected_binding=expected_binding,packet_chars=packet_chars)
        if rebuilt != manifest:raise ValueError('Immutable native visual text observations changed')
        return deepcopy(manifest)
    result=attach_document_emf(manifest,content,expected_binding=expected_binding,packet_chars=packet_chars)
    result.pop('manifest_digest')
    result['media_text_profile']='native-pptx-visual-text-v1'
    result['smartart_text_bindings']=[]
    def nodes(node,path=None):
        path=path or '/'+node['tag'].rsplit('}',1)[-1]
        yield node,path
        for index,child in enumerate(node['children'],1):
            yield from nodes(child,path+'/'+child['tag'].rsplit('}',1)[-1]+'['+str(index)+']')
    with _parts(content) as archive:
        for slide in result['slides']:
            relmap={rel['Id']:rel for rel in slide['relationships']}
            for shape in slide['shapes']:
                if shape['shape_type']=='grpSp':continue
                for node,shape_xml_path in nodes(shape['native_xml']):
                    if node['tag'].rsplit('}',1)[-1]!='relIds':continue
                    rid=node['attributes'].get('{'+REL+'}dm')
                    relation=relmap.get(rid)
                    if not relation or 'resolved_part' not in relation:continue
                    data_part=relation['resolved_part']
                    if not relation['Type'].endswith('/diagramData'):continue
                    parts=[(data_part,'native_smartart_data_literal',rid)]
                    data_tree=ET.fromstring(archive.read(data_part))
                    # MS-ODRAWXML dataModelExt explicitly references the
                    # containing slide's Diagram Drawing relationship.
                    # https://learn.microsoft.com/en-us/openspecs/office_standards/ms-odrawxml/66cc6c59-45c6-438e-82ba-7d67de771f68
                    for extension in data_tree.iter('{http://schemas.microsoft.com/office/drawing/2008/diagram}dataModelExt'):
                        cache_rid=extension.attrib.get('relId')
                        cached=relmap.get(cache_rid)
                        if cached and cached['Type'].endswith('/diagramDrawing') and 'resolved_part' in cached:
                            parts.append((cached['resolved_part'],'stored_smartart_drawing_cache_unverified',cache_rid))
                        else:
                            result['unsupported'].append({'format':'pptx','slide':slide['slide'],'part':data_part,
                                'code':'smartart_cache_relationship_unresolved_or_external','relationship_id':cache_rid})
                    for rel in _relationships(archive,data_part):
                        if rel['Type'].endswith('/diagramDrawing'):
                            if 'resolved_part' in rel:parts.append((rel['resolved_part'],'stored_smartart_drawing_cache_unverified',rel['Id']))
                            else:result['unsupported'].append({'format':'pptx','slide':slide['slide'],
                                'code':'external_smartart_cache_not_fetched','relationship':rel})
                    for part,origin,part_rid in parts:
                        raw=archive.read(part);part_sha=hashlib.sha256(raw).hexdigest()
                        parsed=_xml(ET.fromstring(raw))
                        where={'format':'pptx','slide':slide['slide'],'part':slide['part'],
                            'shape_path':shape['shape_path'],'smartart_data_part':data_part,
                            'smartart_part':part,'part_sha256':part_sha,
                            'relationship_id':rid,'part_relationship_id':part_rid,
                            'shape_xml_path':shape_xml_path}
                        binding={'source_locator':where,'origin':origin,'unit_ids':[],**SCOPE}
                        for text_node,xml_path in nodes(parsed):
                            if text_node['tag']!='{'+NS['a']+'}t':continue
                            unit=_unit(result,'smartart_text' if origin=='native_smartart_data_literal' else 'smartart_cached_text',
                                {**where,'xml_path':xml_path},text_node['text'] or '',shape['coordinates'],
                                origin=origin,part_sha256=part_sha,extraction_status='native_xml_literal_not_team_or_chart_interpretation')
                            binding['unit_ids'].append(unit['id'])
                        result['smartart_text_bindings'].append(binding)
        for part in result['embedded_parts']:
            if part['part'].lower().endswith('.doc') or part['part'].lower().endswith('.bin'):
                result['unsupported'].append({'format':'pptx','part':part['part'],
                    'code':'legacy_binary_office_embedding_unparsed_not_executed'})
    _packets(result,packet_chars)
    if len({u['id'] for u in result['units']}) != len(result['units']):
        raise ValueError('Ambiguous native visual text binding')
    result['counts'].update(units=len(result['units']),packets=len(result['packets']),
        unpacketized_units=len(result['unpacketized_units']),
        smartart_text_units=sum(len(row['unit_ids']) for row in result['smartart_text_bindings']))
    result['native_visual_text_status']='available_native_literal_records_unverified'
    result['manifest_digest']=digest(result)
    return result


def retrieve_document_units(manifest, unit_ids, *, expected_binding, max_chars=24000, compact=False):
    if (not isinstance(manifest,dict) or manifest.get('contract') != CONTRACT or
            manifest.get('binding') != expected_binding or manifest.get('manifest_digest') !=
            digest({key:value for key,value in manifest.items() if key != 'manifest_digest'}) or
            any(manifest.get(key) != value for key,value in SCOPE.items())):
        raise ValueError('Private document manifest scope/integrity mismatch')
    if (not isinstance(unit_ids,list) or not unit_ids or len(unit_ids) > 100 or
            len(unit_ids) != len(set(unit_ids)) or
            not isinstance(max_chars,int) or isinstance(max_chars,bool) or not 800 <= max_chars <= 48000):
        raise ValueError('Exact bounded document unit selection required')
    lookup={unit['id']:unit for unit in manifest['units']}
    if any(unit_id not in lookup for unit_id in unit_ids):
        raise ValueError('Unknown private document evidence unit')
    result={'contract':RETRIEVAL,'binding':deepcopy(manifest['binding']),
            'manifest_digest':manifest['manifest_digest'],
            'units':[(document_unit_observation(lookup[unit_id]) if compact else deepcopy(lookup[unit_id]))
                     for unit_id in unit_ids], **SCOPE}
    if len(canonical(result)) > max_chars:
        raise ValueError('Exact document retrieval exceeds context budget; select fewer units')
    result['retrieval_digest']=digest(result)
    return result


def attach_document_ocr(manifest, observations, *, expected_binding, packet_chars=3400):
    """Append literal local OCR proposals; never replace native tables or text.

    Each page wrapper binds the raster digest and immutable original source.
    Recognition is a proposed reading, not a number/claim/review qualification.
    Existing OCR batches are immutable; a repeated exact batch is idempotent.
    """
    if (not isinstance(manifest,dict) or manifest.get('contract') != CONTRACT or
            manifest.get('binding') != expected_binding or manifest.get('manifest_digest') !=
            digest({key:value for key,value in manifest.items() if key != 'manifest_digest'}) or
            any(manifest.get(key) != value for key,value in SCOPE.items())):
        raise ValueError('Private OCR document scope/integrity mismatch')
    if manifest['binding']['format'] != 'pdf':
        raise ValueError('Page OCR observations require a private PDF manifest')
    if not isinstance(observations,list) or not observations or len(observations)>500:
        raise ValueError('Bounded literal OCR page observations required')
    if manifest.get('ocr_observations') is not None:
        if manifest['ocr_observations'] != observations:
            raise ValueError('Immutable local OCR batch changed')
        return deepcopy(manifest)
    if not isinstance(packet_chars,int) or isinstance(packet_chars,bool) or not 800<=packet_chars<=4000:
        raise ValueError('Bounded private OCR packet limit required')
    pages={page['page'] for page in manifest['pages']}
    seen=set()
    for wrapper in observations:
        required={'page','source_sha256','image_sha256','engine','coordinate_system',
                  'language_correction','observations'}
        if not isinstance(wrapper,dict) or set(wrapper)!=required:
            raise ValueError('Exact local OCR page wrapper required')
        page=wrapper['page']
        if not isinstance(page,int) or isinstance(page,bool) or page not in pages or page in seen:
            raise ValueError('OCR page is missing or ambiguous')
        seen.add(page)
        if (wrapper['source_sha256']!=manifest['binding']['source_sha256'] or
                not isinstance(wrapper['image_sha256'],str) or len(wrapper['image_sha256'])!=64 or
                any(c not in '0123456789abcdef' for c in wrapper['image_sha256']) or
                wrapper['engine']!='AppleVision-VNRecognizeTextRequest' or
                wrapper['coordinate_system']!='normalized-bottom-left' or
                wrapper['language_correction'] is not False):
            raise ValueError('Local OCR source/raster/engine binding is invalid')
        if not isinstance(wrapper['observations'],list) or len(wrapper['observations'])>10000:
            raise ValueError('Local OCR page observation limit exceeded')
        for observation in wrapper['observations']:
            if (not isinstance(observation,dict) or set(observation)!={'text','confidence','bbox'} or
                    not isinstance(observation['text'],str) or len(observation['text'])>100000):
                raise ValueError('Exact literal local OCR observation required')
            confidence=observation['confidence']
            box=observation['bbox']
            if (not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or
                    not math.isfinite(confidence) or not 0<=confidence<=1 or
                    not isinstance(box,list) or len(box)!=4 or
                    any(not isinstance(value,(int,float)) or isinstance(value,bool) or
                        not math.isfinite(value) or not 0<=value<=1 for value in box) or
                    box[2]<=0 or box[3]<=0 or box[0]+box[2]>1.000001 or box[1]+box[3]>1.000001):
                raise ValueError('Local OCR confidence/normalized coordinates invalid')
    result=deepcopy(manifest)
    result.pop('manifest_digest')
    result['ocr_observations']=deepcopy(observations)
    for wrapper in observations:
        for index,observation in enumerate(wrapper['observations'],1):
            _unit(result,'ocr_text',{'format':'pdf','page':wrapper['page'],
                'ocr_observation':index,'image_sha256':wrapper['image_sha256']},
                observation['text'],{'bbox':observation['bbox'],
                'coordinate_system':wrapper['coordinate_system']},
                origin='local_ocr_proposed',confidence=observation['confidence'],
                engine=wrapper['engine'],language_correction=False)
    result['ocr_status']='local_ocr_proposed'
    result['ocr_page_coverage']={'observed_pages':sorted(seen),
                                'unobserved_pages':sorted(pages-seen)}
    # Keep original native-parser limitations as historical observations.
    for finding in result['unsupported']:
        if finding.get('page') in seen and finding.get('code')=='no_native_text_ocr_unrun':
            finding['current_resolution']='local_ocr_proposed_unverified'
    _packets(result,packet_chars)
    result['counts']['units']=len(result['units'])
    result['counts']['packets']=len(result['packets'])
    result['counts']['unpacketized_units']=len(result['unpacketized_units'])
    result['counts']['ocr_observations']=sum(len(w['observations']) for w in observations)
    result['manifest_digest']=digest(result)
    return result
