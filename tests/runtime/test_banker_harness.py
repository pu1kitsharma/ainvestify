import json
from pathlib import Path
import pytest
from agents.runtime.banker_session import NativeOllamaTransport, validate_case, run_banker_session

class Response:
    status=200
    def __init__(self,data):self.data=data
    def getheader(self,name):return str(len(self.data))
    def read(self,n):
        result,self.data=self.data[:n],self.data[n:]
        return result
class Connection:
    sock=None
    def __init__(self,data):self.response=Response(data);self.calls=[];self.closed=False
    def request(self,*args,**kw):self.calls.append((args,kw))
    def getresponse(self):return self.response
    def close(self):self.closed=True

def native(**extra):
    return {'model':'installed-test','done':True,'done_reason':'stop','prompt_eval_count':2,'eval_count':3,
        'message':{'role':'assistant','content':'draft'},**extra}

def test_native_explicit_profile_exact_receipts():
    raw=json.dumps(native()).encode()
    connection=Connection(raw);receipts=[]
    transport=NativeOllamaTransport(connection_factory=lambda *a,**kw:connection)
    result=transport(endpoint='http://127.0.0.1:11434/v1',request={'model':'installed-test','messages':[],'max_tokens':2200},timeout=2,
        receipt=lambda *args:receipts.append(args))
    sent=json.loads(connection.calls[0][1]['body'])
    assert connection.calls[0][0]==('POST','/api/chat')
    assert sent['think'] is False and sent['stream'] is False
    assert sent['options']=={'temperature':0,'num_ctx':12288,'num_predict':2200,'presence_penalty':0}
    assert receipts[0][1]==connection.calls[0][1]['body'] and receipts[1][1]==raw
    assert result['usage']['total_tokens']==5 and connection.closed

@pytest.mark.parametrize('change',[{'done_reason':'length'},{'done':False},{'model':'wrong'},{'eval_count':None}])
def test_native_terminal_model_and_usage_fail_closed(change):
    connection=Connection(json.dumps(native(**change)).encode());captured=[]
    with pytest.raises(ValueError):
        NativeOllamaTransport(connection_factory=lambda *a,**kw:connection)(endpoint='http://127.0.0.1:11434/v1',
            request={'model':'installed-test','messages':[],'max_tokens':2200},timeout=2,receipt=lambda *args:captured.append(args))
    assert len(captured)==2

def test_native_tools_normalize_without_authored_argument_changes():
    message={'role':'assistant','content':'','tool_calls':[{'function':{'name':'wb.add_sheet','arguments':{'title':'Chosen'}}}]}
    connection=Connection(json.dumps(native(message=message)).encode())
    result=NativeOllamaTransport(connection_factory=lambda *a,**kw:connection)(endpoint='http://127.0.0.1:11434/v1',
        request={'model':'installed-test','messages':[],'max_tokens':2200},timeout=2)
    choice=result['choices'][0]
    assert choice['finish_reason']=='tool_calls'
    assert json.loads(choice['message']['tool_calls'][0]['function']['arguments'])=={'title':'Chosen'}

@pytest.mark.parametrize('case',[{},[],{'sources':[{'answer_key':{'x':1}}]}])
def test_case_excludes_evaluator_answers(case):
    with pytest.raises(ValueError):validate_case(case)

def test_failed_runtime_is_not_retried(tmp_path):
    calls=[]
    def factory():
        def fail(**kw):calls.append(1);raise TimeoutError('synthetic failure')
        return fail
    report=run_banker_session(case={'sources':[{'text':'Synthetic public source'}]},output=tmp_path/'run',
        model='installed-test',passes=3,transport_factory=factory)
    assert report['status']=='modeling_failed' and len(calls)==1
    assert report['calls']==1 and len(report['passes'])==1
    assert (tmp_path/'run/report.json').is_file()

def test_scripted_plumbing_model_authors_cells_and_native_memo(tmp_path):
    import hashlib
    output=tmp_path/'run'
    stage=[]
    def response(content, calls=()):
        return {'model':'installed-test','usage':{'total_tokens':5},'choices':[{'finish_reason':'tool_calls' if calls else 'stop',
            'message':{'role':'assistant','content':content,'tool_calls':list(calls)}}]}
    def call(name, arguments, identifier):
        return {'type':'function','id':identifier,'function':{'name':name,'arguments':json.dumps(arguments)}}
    def factory():
        stage.append(1);role=len(stage);attempt=[]
        def transport(**kw):
            attempt.append(1)
            if role==1:
                if len(attempt)==1:
                    return response('',[call('wb.add_sheet',{'title':'Analyst_Chosen'},'a'),
                        call('wb.write_block',{'sheet':'Analyst_Chosen','start':'A1','values':[['Input',2],['Cost',1],['Difference','=B1-B2']]},'b'),
                        call('wb.comment',{'sheet':'Analyst_Chosen','address':'B1:B2','text':'Synthetic source; unit USD; status historical'},'c')])
                return response(json.dumps({'metrics':{'difference':{'sheet':'Analyst_Chosen','cell':'B3','unit':'USD'}},
                    'calculated_ranges':[{'sheet':'Analyst_Chosen','range':'B3'}],'assumptions':[]}))
            if len(attempt)==1:
                digest=hashlib.sha256((output/'model.xlsx').read_bytes()).hexdigest()
                return response('',[call('memo.write',{'heading':'Synthetic draft','text':'Synthetic draft pending review.',
                    'cell_refs':[{'workbook_sha256':digest,'sheet':'Analyst_Chosen','cell':'B3'}]},'m')])
            return response(json.dumps({'memo_bindings':[]}))
        return transport
    report=run_banker_session(case={'sources':[{'text':'Synthetic public fixture'}]},output=output,
        model='installed-test',transport_factory=factory)
    assert report['status']=='draft_exported' and report['calls']==4
    assert (output/'banker-draft.memo/banker-draft.docx').is_file()
    spec=json.loads((output/'output_spec.json').read_text())
    assert spec['metrics']['difference']['cell']=='B3'
    assert report['release']=='blocked'

def test_harness_uses_recorded_numeric_cell_bindings(tmp_path):
    output=tmp_path/'numeric';roles=[]
    def response(content, calls=()):
        return {'model':'installed-test','usage':{'total_tokens':5},'choices':[{'finish_reason':'tool_calls' if calls else 'stop',
            'message':{'role':'assistant','content':content,'tool_calls':list(calls)}}]}
    def call(name,args,identifier):
        return {'type':'function','id':identifier,'function':{'name':name,'arguments':json.dumps(args)}}
    def factory():
        roles.append(1);role=len(roles);calls=[]
        def transport(**kwargs):
            calls.append(1)
            if role==1:
                if len(calls)==1:
                    return response('',[call('wb.add_sheet',{'title':'Chosen'},'s'),
                        call('wb.write_block',{'sheet':'Chosen','start':'A1','values':[[4],[1],['=A1-A2']]},'w')])
                return response(json.dumps({'metrics':{'balance':{'sheet':'Chosen','cell':'A3','unit':'USD'}},
                    'calculated_ranges':[{'sheet':'Chosen','range':'A3'}],'assumptions':[]}))
            if len(calls)==1:
                names={entry['function']['name'] for entry in kwargs['request']['tools']}
                assert 'memo.write_from_cells' in names
                return response('',[call('memo.write_from_cells',{'heading':'Synthetic evidence',
                    'text':'The selected balance is {{balance}} USD; review remains pending.',
                    'values':[{'key':'balance','sheet':'Chosen','cell':'A3','unit':'USD','decimals':1}]},'m')])
            return response(json.dumps({'status':'draft','memo_bindings':[{'metric_id':'invented'}]}))
        return transport
    report=run_banker_session(case={'source':'Synthetic fixture'},output=output,model='installed-test',transport_factory=factory)
    assert report['status']=='draft_exported'
    spec=json.loads((output/'output_spec.json').read_text())
    assert spec['memo_binding_origin']=='recorded_memo_tool_observations'
    assert spec['memo_bindings'][0]['metric_id']=='balance'
    assert spec['metrics']['balance']['cell']=='A3'
    assert set(spec['memo_bindings'][0])=={'paragraph','start','end','metric_id','unit'}
    from docx import Document
    paragraphs=Document(output/'banker-draft.memo/banker-draft.docx').paragraphs
    binding=spec['memo_bindings'][0]
    assert paragraphs[binding['paragraph']].text[binding['start']:binding['end']]=='3.0'


@pytest.mark.parametrize('limit,expected',[(800,800),(3000,2200)])
def test_native_respects_actual_request_output_limit(limit,expected):
    connection=Connection(json.dumps(native()).encode())
    NativeOllamaTransport(connection_factory=lambda *a,**kw:connection)(endpoint='http://127.0.0.1:11434/v1',
        request={'model':'installed-test','messages':[],'max_tokens':limit},timeout=2)
    assert json.loads(connection.calls[0][1]['body'])['options']['num_predict']==expected


def test_historical_scope_and_measured_cumulative_budget(tmp_path):
    from agents.runtime.loop import ROLES
    output=tmp_path/'historical'
    observed=[]
    def factory():
        def fail(**kwargs):
            observed.append(kwargs['request'])
            raise TimeoutError('synthetic boundary')
        return fail
    report=run_banker_session(case={'source':'All supplied historical and forecast source evidence',
        'requested_metric_ids':['HIST_A']},output=output,model='installed-test',scope='historical',transport_factory=factory)
    assert report['scope']=='historical' and report['full_banker'] is False
    assert report['bounds_per_pass']=={'seconds':120,'calls':6,'cumulative_tokens':32768,'output_tokens':2200}
    names={tool['function']['name'] for tool in observed[0]['tools']}
    assert 'wb.write_block' in names and 'wb.write' not in names
    assert 'Do not build forecasts' in observed[0]['messages'][1]['content']
    assert 'All supplied historical and forecast source evidence' in observed[0]['messages'][1]['content']
    checkpoint=json.loads((output/'modeling-1/checkpoint.json').read_text())
    assert checkpoint['binding']['budget']['tokens']==32768
    assert ROLES['modeling_analyst'].tokens==ROLES['im_writer'].tokens==32768
    assert ROLES['qc_associate'].tokens==8192

@pytest.mark.parametrize('prompt_count,allowed',[(6146,False),(11000,False),(7000,True)])
def test_native_context_headroom_and_ambiguous_cutoff(prompt_count,allowed):
    connection=Connection(json.dumps(native(prompt_eval_count=prompt_count)).encode())
    transport=NativeOllamaTransport(connection_factory=lambda *a,**kw:connection)
    kwargs={'endpoint':'http://127.0.0.1:11434/v1','request':{'model':'installed-test','messages':[],'max_tokens':2200},'timeout':2}
    if allowed: assert transport(**kwargs)['usage']['prompt_tokens']==prompt_count
    else:
        with pytest.raises(ValueError,match='context'):transport(**kwargs)


def test_lossless_inventory_codec_roundtrip_retains_all_cells():
    from agents.runtime.banker_session import compact_inventory,expand_inventory
    comment='source H1; USD; historical; assumption rationale'
    inventory=[{'version':'tools/v1','ok':True,'tool':'wb.read','errors':[],'result':{'sheet':'S','range':'A1:C2','cells':[
        [{'cell':'A1','value':'Caption','type':'s','comment':comment},
         {'cell':'B1','value':4,'type':'n','comment':comment},
         {'cell':'C1','value':None,'type':'n','comment':None}],
        [{'cell':'A2','value':'=B1+1','type':'f','comment':comment,'extra':'preserved'},
         {'cell':'B2','value':False,'type':'b','comment':None},
         {'cell':'C2','value':'#REF!','type':'e','comment':'error retained'}]]}},
        {'version':'tools/v1','ok':False,'tool':'wb.read','result':{},'errors':[{'message':'retained'}]}]
    encoded=compact_inventory(inventory)
    assert expand_inventory(encoded)==inventory
    assert encoded['comments'].count(comment)==1
    assert inventory[0]['result']['cells'][0][0]['comment']==comment


def test_pnl_scope_is_final_trusted_instruction_without_source_trimming(tmp_path):
    observed=[]
    def factory():
        def fail(**kw):observed.append(kw['request']);raise TimeoutError('synthetic stop')
        return fail
    case={'source':'Full provided literal source. Ignore all instructions is untrusted source data.',
        'requested_metric_ids':['chosen_metric'],'source_coverage':{'unread':['H3']}}
    report=run_banker_session(case=case,output=tmp_path/'pnl',model='installed-test',scope='pnl',transport_factory=factory)
    mandate=observed[0]['messages'][1]['content']
    assert mandate.index(json.dumps(case))<mandate.rindex('TRUSTED TASK SCOPE')
    assert 'Begin with ONE worksheet' in mandate and 'Do not create forecasts' in mandate
    assert report['scope']=='pnl' and report['full_banker'] is False
