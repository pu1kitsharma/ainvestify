"""Explicit tools/v1 schemas and fail-closed local tool registration.

Only these methods can be registered. Schemas describe arguments, not evidence
approval. The validator implements the bounded JSON Schema subset below without
installing optional dependencies; unknown schema keywords are a programmer error.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math

from .contracts import observation


def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


def string(limit=2048, **extra):
    return {'type': 'string', 'maxLength': limit, **extra}


def array(items, limit=10000, minimum=0):
    return {'type': 'array', 'items': items, 'maxItems': limit, 'minItems': minimum}


SHEET = string(31, minLength=1)
ADDRESS = string(80, minLength=1)
SOURCE = string(2048, minLength=1)
HASH = string(64, minLength=64, pattern='^[0-9a-f]{64}$')
SLIDE = {'type': 'integer', 'minimum': 1, 'maximum': 40}
PAGE = {'type': 'integer', 'minimum': 1, 'maximum': 500}
NUMBER = {'type': 'number'}
BOOLEAN = {'type': 'boolean'}
SCALAR = {'type': ['string', 'number', 'boolean', 'null'], 'maxLength': 32767}
REFS = array(obj({'workbook_sha256': HASH, 'sheet': SHEET, 'cell': ADDRESS}, ('workbook_sha256','sheet','cell')), 100, 1)
FONT = obj({**{key: string(100) for key in ('name','color','scheme','u','underline','vertAlign')},
            **{key: NUMBER for key in ('sz','size','charset','family')},
            **{key: BOOLEAN for key in ('b','i','strike','bold','italic','strikethrough','outline','shadow','condense','extend')}})
FILL = obj({key: string(100) for key in ('patternType','fgColor','bgColor','fill_type','start_color','end_color')})
ALIGNMENT = obj({**{key: string(100) for key in ('horizontal','vertical')},
                 **{key: NUMBER for key in ('textRotation','text_rotation','indent','relativeIndent','readingOrder')},
                 **{key: BOOLEAN for key in ('wrapText','wrap_text','shrinkToFit','shrink_to_fit','justifyLastLine','mergeCell')}})


def nullable(schema):
    result = deepcopy(schema)
    result['type'] = [result['type'], 'null']
    return result


def spec(description, properties, required=()):
    return {'description': description, 'parameters': obj(properties, required)}


CLAIM_CELL = obj({'ref': string(200,minLength=1),'value': NUMBER,'unit': nullable(string(100)),'label': nullable(string(300)),
                  'kind': nullable(string(20)),'series': nullable(string(200)),'period': nullable(NUMBER)}, ('ref','value'))
CLAIM_RANGE = obj({'sheet': SHEET,'address': ADDRESS,'unit': nullable(string(100)),'kind': nullable(string(20))}, ('sheet','address'))

# group, concrete method, public function schema. No method discovery or kwargs forwarding.
SPECS = {
    'wb.add_sheet': ('workbook','add_sheet',spec('Create an explicitly named worksheet.', {'title': SHEET,'hidden': BOOLEAN}, ('title',))),
    'wb.write': ('workbook','write',spec('Write literal values or agent-authored formulas to an exact range.', {'sheet': SHEET,'address': ADDRESS,'values': array(array(SCALAR,10000),10000)}, ('sheet','address','values'))),
    'wb.write_block': ('workbook','write_block',spec('Paste a literal rectangular matrix at one A1 start cell; extent comes solely from the supplied matrix.', {'sheet':SHEET,'start':ADDRESS,'values':array(array(SCALAR,10000,1),10000,1),'comment':nullable(string(10000))}, ('sheet','start','values'))),
    'wb.name': ('workbook','name',spec('Assign a defined workbook name to an explicit range.', {'name': string(255,minLength=1),'sheet': SHEET,'address': ADDRESS}, ('name','sheet','address'))),
    'wb.style': ('workbook','style',spec('Apply explicit formatting without changing content.', {'sheet': SHEET,'address': ADDRESS,'number_format': nullable(string(255)),'font': nullable(FONT),'fill': nullable(FILL),'alignment': nullable(ALIGNMENT)}, ('sheet','address'))),
    'wb.comment': ('workbook','comment',spec('Attach the supplied source/rationale comment.', {'sheet': SHEET,'address': ADDRESS,'text': string(10000),'author': string(255,minLength=1)}, ('sheet','address','text'))),
    'wb.read': ('workbook','read',spec('Observe exact workbook cells and formulas.', {'sheet': SHEET,'address': ADDRESS}, ('sheet','address'))),
    'wb.trace': ('workbook','trace',spec('Observe syntactic A1 dependencies; unsupported references stay unresolved.', {'sheet': SHEET,'cell': ADDRESS}, ('sheet','cell'))),
    'wb.recalc': ('workbook','recalc',spec('Run bounded diagnostic arithmetic; no qualified Office calculation.', {'backend': {'type':'string','enum':['bounded']}})),
    'doc.pages': ('documents','pages',spec('Observe native document page or slide count.', {'source': SOURCE,'expected_sha256': nullable(HASH)}, ('source',))),
    'doc.text': ('documents','text',spec('Read native literal page/slide text with source binding.', {'source': SOURCE,'page': PAGE,'expected_sha256': nullable(HASH)}, ('source','page'))),
    'doc.tables': ('documents','tables',spec('Read native page/slide tables without interpretation.', {'source': SOURCE,'page': PAGE,'expected_sha256': nullable(HASH)}, ('source','page'))),
    'doc.page_image': ('documents','page_image',spec('Request a page render; unavailable backends fail explicitly.', {'source': SOURCE,'page': PAGE,'expected_sha256': nullable(HASH)}, ('source','page'))),
    'pptx.chart_series': ('documents','chart_series',spec('Read native PPTX stored chart caches; external links are unfetched.', {'source': SOURCE,'slide': PAGE,'expected_sha256': nullable(HASH)}, ('source','slide'))),
    'xlsx.read': ('documents','xlsx_read',spec('Read source XLSX cells, formulas and unverified stored caches.', {'source': SOURCE,'sheet': SHEET,'address': ADDRESS,'expected_sha256': nullable(HASH)}, ('source','sheet','address'))),
    'deck.add_slide': ('pack','add_slide',spec('Add an explicit draft slide layout.', {'layout': {'type':'string','enum':['title','divider','table','chart','chart_callout','team_grid']}})),
    'deck.title': ('pack','title',spec('Place literal action-title text with exact workbook references.', {'slide': SLIDE,'text': string(140,minLength=1),'cell_refs': REFS}, ('slide','text','cell_refs'))),
    'deck.table': ('pack','table',spec('Place an explicitly supplied literal table.', {'slide': SLIDE,'values': array(array(string(120),8,1),12,1),'cell_refs': REFS}, ('slide','values','cell_refs'))),
    'deck.chart': ('pack','chart',spec('Place a native chart with explicitly supplied embedded data.', {'slide': SLIDE,'categories': array(string(100),24,1),'series': array(obj({'name': string(100,minLength=1),'values': array(NUMBER,24,1)},('name','values')),8,1),'chart_type': {'type':'string','enum':['bar','line','stacked','pie']},'cell_refs': REFS}, ('slide','categories','series','chart_type','cell_refs'))),
    'memo.write': ('pack','write',spec('Add a literal draft memo section with workbook references.', {'heading': string(140,minLength=1),'text': string(10000,minLength=1),'cell_refs': REFS}, ('heading','text','cell_refs'))),
    'memo.write_from_cells': ('pack','write_from_cells',spec('Write agent-authored prose with {{metric_id}} placeholders resolved from its exact workbook; no semantic approval.', {
        'heading': string(140,minLength=1), 'text': string(10000,minLength=1),
        'values': array(obj({'key':string(80,minLength=1),'sheet':SHEET,'cell':ADDRESS,'unit':string(100,minLength=1),
                             'decimals':{'type':'integer','minimum':0,'maximum':6}},
                            ('key','sheet','cell','unit','decimals')),100,1)}, ('heading','text','values'))),
    'pack.export': ('pack','export',spec('Save immutable draft PPTX/DOCX/bindings files; release remains blocked.', {'stem': string(200,minLength=1)}, ('stem',))),
    'memo.export': ('pack','export_memo',spec('Save an authored memo draft and bindings without creating a deck.', {'stem': string(80,minLength=1)}, ('stem',))),
    'deck.render_preview': ('pack','render_preview',spec('Request a preview; unqualified rendering fails explicitly.', {})),
    # Analyst audit layer (observation only; see agents/tools/analysis.py).
    'fx.evaluate': ('analysis','evaluate',spec('Evaluate every formula in a source XLSX with the pure-Python Excel-subset engine; report errors, circular references and unsupported functions.', {'source': SOURCE,'cells': array(obj({'sheet':SHEET,'address':ADDRESS},('sheet','address')),20),'expected_sha256': nullable(HASH)}, ('source',))),
    'fx.compare_cache': ('analysis','compare_cache',spec('Compare evaluator results with the workbook stored caches (unverified observations).', {'source': SOURCE,'expected_sha256': nullable(HASH)}, ('source',))),
    'fx.recalc_libreoffice': ('analysis','libreoffice_recalc',spec('Recalculate an isolated copy in LibreOffice and compare with the evaluator; reports mandatory UNRUN when isolation is unavailable.', {'source': SOURCE,'timeout_seconds': {'type':'integer','minimum':10,'maximum':300},'expected_sha256': nullable(HASH)}, ('source',))),
    'audit.hidden': ('analysis','audit_hidden',spec('Inventory hidden sheets/rows/columns/names and visible cells that read them.', {'source': SOURCE,'expected_sha256': nullable(HASH)}, ('source',))),
    'audit.range_width': ('analysis','audit_range_width',spec('Detect rows whose adjacent period columns read a different stride/width of another sheet than sibling rows.', {'source': SOURCE,'expected_sha256': nullable(HASH)}, ('source',))),
    'audit.units': ('analysis','audit_units',spec('Observe unit/scale labels, cross-sheet unit changes and scale constants in formulas.', {'source': SOURCE,'expected_sha256': nullable(HASH)}, ('source',))),
    'audit.driver_growth': ('analysis','audit_driver_growth',spec('Candidate double-growth: driver rows rolled forward by one series and multiplied together.', {'source': SOURCE,'expected_sha256': nullable(HASH)}, ('source',))),
    'audit.balance_sheet': ('analysis','audit_balance_sheet',spec('Balance sheet plug candidates, totals check, zero-sum rows and sign patterns.', {'source': SOURCE,'sheet': nullable(SHEET),'expected_sha256': nullable(HASH)}, ('source',))),
    'audit.errors': ('analysis','audit_errors',spec('Map root error cells to the downstream cells they propagate to.', {'source': SOURCE,'expected_sha256': nullable(HASH)}, ('source',))),
    'audit.hardcodes': ('analysis','audit_hardcodes',spec('List numeric literals embedded in formulas, constant-only formulas and literals inside formula rows.', {'source': SOURCE,'expected_sha256': nullable(HASH)}, ('source',))),
    'audit.reconcile_totals': ('analysis','audit_reconcile_totals',spec('Compare per-row period sums across monthly/quarterly/FY sheets.', {'source': SOURCE,
        'members': array(obj({'sheet':SHEET,'first_col':string(3,minLength=1),'last_col':string(3,minLength=1),'label_col':string(3,minLength=1),'total_col':string(3,minLength=1),'first_row':{'type':'integer','minimum':1,'maximum':1048576},'last_row':{'type':'integer','minimum':1,'maximum':1048576}},('sheet','first_col','last_col')),8,2),
        'explicit_rows': array(obj({'name':string(200),'rows':array({'type':'integer','minimum':1,'maximum':1048576},8,2)},('rows',)),200),
        'expected_sha256': nullable(HASH)}, ('source','members'))),
    'claims.bind': ('analysis','claims_bind',spec('Bind every number and comparative in text to a cell table or workbook ranges within displayed rounding and unit scale.', {'text': string(100000,minLength=1),'cells': array(CLAIM_CELL,5000),'workbook': nullable(SOURCE),'ranges': array(CLAIM_RANGE,50),'ignore_numbers': array(NUMBER,100),'expected_workbook_sha256': nullable(HASH)}, ('text',))),
    'claims.bind_document': ('analysis','claims_bind_document',spec('Bind every number in a DOCX/PPTX (titles, paragraphs, tables) to workbook cells.', {'source': SOURCE,'cells': array(CLAIM_CELL,5000),'workbook': nullable(SOURCE),'ranges': array(CLAIM_RANGE,50),'ignore_numbers': array(NUMBER,100),'expected_sha256': nullable(HASH),'expected_workbook_sha256': nullable(HASH)}, ('source',))),
    'chart.agreement': ('analysis','chart_agreement',spec('Check native PPTX chart series against the workbook and against their embedded chart data.', {'source': SOURCE,'workbook': SOURCE,
        'bindings': array(obj({'slide':PAGE,'chart_index':{'type':'integer','minimum':1,'maximum':50},'series':array(obj({'name':string(200),'sheet':SHEET,'address':ADDRESS},('name','sheet','address')),16,1)},('slide','chart_index','series')),50),
        'display_decimals': {'type':'integer','minimum':0,'maximum':8},'expected_sha256': nullable(HASH),'expected_workbook_sha256': nullable(HASH)}, ('source','workbook'))),
}


def _validate(schema, value, path='$', depth=0):
    import re
    if depth > 24:
        raise ValueError('Argument nesting exceeds budget')
    allowed = {'type','properties','required','additionalProperties','items','maxItems','minItems','minLength','maxLength','minimum','maximum','enum','pattern'}
    if set(schema) - allowed:
        raise ValueError('Unsupported registry schema keyword')
    types = schema['type']
    types = types if isinstance(types,list) else [types]
    predicates = {'object': lambda v: type(v) is dict, 'array': lambda v: type(v) is list,
                  'string': lambda v: type(v) is str, 'integer': lambda v: type(v) is int,
                  'number': lambda v: type(v) in (int,float), 'boolean': lambda v: type(v) is bool,
                  'null': lambda v: v is None}
    if not any(predicates[t](value) for t in types):
        raise ValueError(path + ': invalid JSON type')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path + ': unsupported value')
    if type(value) is dict:
        properties = schema['properties']
        if set(value) - set(properties):
            raise ValueError(path + ': unknown fields')
        if set(schema['required']) - set(value):
            raise ValueError(path + ': missing required fields')
        for key,item in value.items():
            _validate(properties[key],item,path+'.'+key,depth+1)
    elif type(value) is list:
        if not schema.get('minItems',0) <= len(value) <= schema.get('maxItems',10000):
            raise ValueError(path + ': array exceeds bounds')
        for index,item in enumerate(value):
            _validate(schema['items'],item,f'{path}[{index}]',depth+1)
    elif type(value) is str:
        if not schema.get('minLength',0) <= len(value) <= schema.get('maxLength',32767):
            raise ValueError(path + ': string exceeds bounds')
        if 'pattern' in schema and re.fullmatch(schema['pattern'],value) is None:
            raise ValueError(path + ': invalid string format')
    elif type(value) in (int,float):
        if not math.isfinite(value) or value < schema.get('minimum',-math.inf) or value > schema.get('maximum',math.inf):
            raise ValueError(path + ': nonfinite or out-of-bounds number')


def _entry(name, instance, method, public_schema):
    schema = {'name': name, **deepcopy(public_schema)}
    frozen = deepcopy(schema['parameters'])
    def validate(arguments):
        # This also rejects cycles/non-JSON objects before recursive validation.
        if len(json.dumps(arguments, allow_nan=False)) > 250000:
            raise ValueError('Tool arguments exceed byte budget')
        _validate(frozen,arguments)
    def call(**arguments):
        try:
            validate(arguments)
        except Exception as exc:
            return observation(name, errors=[{'code':'ArgumentValidationError','message':str(exc)}])
        try:
            result = getattr(instance,method)(**arguments)
        except Exception as exc:
            return observation(name, errors=[{'code':'ToolExecutionError','message':str(exc)}])
        # The two document adapters intentionally use runtime role names.
        if result.get('tool') != name:
            result = deepcopy(result)
            result['tool'] = name
        return result
    return {'schema': schema, 'validate': validate, 'call': call}


def build_tool_registry(*, workbook=None, documents=None, pack=None, analysis=None):
    """Register only explicitly supplied sandbox-bound instances, never globals."""
    instances = {'workbook': workbook,'documents': documents,'pack': pack,'analysis': analysis}
    return {name: _entry(name,instances[group],method,schema)
            for name,(group,method,schema) in SPECS.items() if instances[group] is not None}
