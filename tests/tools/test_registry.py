import json
from pathlib import Path

import pytest

from agents.tools import WorkbookTools, DocumentTools
from agents.tools.pack import PackTools
from agents.tools.registry import build_tool_registry


def test_registered_scripted_session(tmp_path):
    workbook = WorkbookTools(tmp_path)
    registry = build_tool_registry(workbook=workbook, documents=DocumentTools(tmp_path,tenant_id='synthetic',deal_id='synthetic'), pack=PackTools(tmp_path))
    assert set(registry) == {'wb.add_sheet','wb.write','wb.write_block','wb.name','wb.style','wb.comment','wb.read','wb.trace','wb.recalc',
                             'doc.pages','doc.text','doc.tables','doc.page_image','pptx.chart_series','xlsx.read',
                             'deck.add_slide','deck.title','deck.table','deck.chart','memo.write','memo.write_from_cells','memo.export','pack.export','deck.render_preview'}
    assert registry['wb.write']['call'](sheet='Sheet',address='A1',values=[[7]])['ok']
    assert registry['deck.add_slide']['call'](layout='table')['ok']
    # Build a literal synthetic pack through registered tools only.
    from hashlib import sha256
    ref = [{'workbook_sha256':sha256((tmp_path/'model.xlsx').read_bytes()).hexdigest(),'sheet':'Sheet','cell':'A1'}]
    assert registry['deck.title']['call'](slide=1,text='Synthetic observation',cell_refs=ref)['ok']
    assert registry['deck.table']['call'](slide=1,values=[['7']],cell_refs=ref)['ok']
    assert registry['memo.write']['call'](heading='Synthetic',text='Observed value 7.',cell_refs=ref)['ok']
    exported = registry['pack.export']['call'](stem='synthetic')
    assert exported['ok'], exported
    assert (tmp_path/'model.xlsx').exists()
    assert all((tmp_path / name).exists() for name in exported['result']['files'])
    assert registry['xlsx.read']['call'](source='model.xlsx',sheet='Sheet',address='A1')['tool'] == 'xlsx.read'
    assert registry['xlsx.read']['call'](source='model.xlsx',sheet='Sheet',address='A1')['ok']
    for name,entry in registry.items():
        assert entry['schema']['name'] == name
        assert entry['schema']['parameters']['additionalProperties'] is False
        assert callable(entry['validate'])
        json.dumps(entry['schema'], allow_nan=False)
    assert build_tool_registry() == {}


@pytest.mark.parametrize('name,args', [
    ('wb.write', {'sheet':'Sheet','address':'A1','values':[[1]],'unknown':True}),
    ('wb.write', {'sheet':'Sheet','address':'A1','values':[[float('nan')]]}),
    ('wb.write', {'sheet':'Sheet','address':'A1','values':[[float('inf')]]}),
    ('wb.write', {'sheet':'Sheet','address':'A1','values':[[{'invented':1}]]}),
    ('wb.style', {'sheet':'Sheet','address':'A1','font':{'not_a_font_attribute':1}}),
    ('deck.title', {'slide':True,'text':'Synthetic','cell_refs':[]}),
    ('deck.title', {'slide':1,'text':'Synthetic','cell_refs':[{'workbook_sha256':'0'*64,'sheet':'Sheet','cell':'A1','extra':'lost'}]}),
    ('deck.chart', {'slide':1,'categories':['A'],'series':[{'name':'x','values':[1],'extra':True}],'chart_type':'bar','cell_refs':[]}),
    ('pack.export', {'stem':'synthetic','other':'silently dropped'}),
])
def test_invalid_args_have_no_side_effects(tmp_path,name,args):
    class NeverCalled:
        def __getattr__(self,method):
            raise AssertionError('Validation must run before method lookup/side effects')
    registry = build_tool_registry(workbook=NeverCalled(),pack=NeverCalled())
    result = registry[name]['call'](**args)
    assert not result['ok']
    assert result['errors'][0]['code'] == 'ArgumentValidationError'
    with pytest.raises((ValueError,TypeError)):
        registry[name]['validate'](args)
    assert list(tmp_path.iterdir()) == []


def test_schema_isolated_and_missing_required_fail_before_calls():
    class Fake:
        def read(self, **kwargs):
            raise AssertionError('must not be called')
    registry = build_tool_registry(workbook=Fake())
    registry['wb.read']['schema']['parameters']['required'].clear()
    assert not registry['wb.read']['call']()['ok']
    other = build_tool_registry(workbook=Fake())
    assert other['wb.read']['schema']['parameters']['required'] == ['sheet','address']
