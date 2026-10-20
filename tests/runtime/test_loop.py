import json
import pytest
from agents.runtime import AgentRuntime, Budget, validate_endpoint

@pytest.mark.parametrize('endpoint', ['https://api.openai.com/v1', 'http://localhost:11434/v1', 'http://10.0.0.1:80/v1', 'http://127.0.0.1:80/v1?x=1', 'http://u:p@127.0.0.1:80/v1'])
def test_endpoint_rejects_nonlocal(endpoint):
    with pytest.raises(ValueError): validate_endpoint(endpoint)

def reply(calls=None):
    return {'model':'installed-test', 'usage': {'total_tokens': 10}, 'choices': [{'finish_reason':'tool_calls' if calls else 'stop', 'message': {'role': 'assistant', 'content': 'draft', 'tool_calls': calls or []}}]}

def runtime(tmp_path, transport, tools=None, **kw):
    return AgentRuntime(endpoint='http://127.0.0.1:11434/v1', model='installed-test', transport=transport, tools=tools or {}, directory=tmp_path, **kw)

def test_finish_retains_raw_and_requires_human(tmp_path):
    state=runtime(tmp_path, lambda **kw: reply()).run('im_writer', 'synthetic mandate')
    assert state['status']=='human_review_required'
    assert state['calls']==1
    assert 'draft' in (tmp_path/'trajectory.jsonl').read_text()
    with pytest.raises(ValueError): runtime(tmp_path, lambda **kw: reply())

def test_tool_contract_and_budget(tmp_path):
    call={'type':'function','id':'c1','function':{'name':'wb.read','arguments':'{}'}}
    tool={'validate':lambda arguments: None, 'schema':{'description':'Read cells', 'parameters':{'type':'object'}}, 'call':lambda: {'version':'tools/v1','ok':True,'tool':'wb.read','result':{},'errors':[]}}
    counter=iter(['c1','c2'])
    def respond(**kw):
        call['id']=next(counter)
        return reply([dict(call)])
    state=runtime(tmp_path, respond, {'wb.read':tool}, budget=Budget(calls=2)).run('im_writer','synthetic')
    assert state['status']=='budget_exhausted' and state['calls']==2
    assert len([json.loads(x) for x in (tmp_path/'trajectory.jsonl').read_text().splitlines() if json.loads(x)['kind']=='tool_observation'])==2

def test_disallowed_tool_never_executes(tmp_path):
    call={'type':'function','id':'x','function':{'name':'web.search','arguments':'{}'}}
    state=runtime(tmp_path, lambda **kw: reply([call])).run('im_writer','synthetic')
    assert state['status']=='failed'

def test_transport_failure_no_retry(tmp_path):
    def fail(**kw): raise TimeoutError('offline')
    state=runtime(tmp_path,fail).run('im_writer','synthetic')
    assert state['status']=='failed' and state['calls']==1

def test_elapsed_response_cannot_execute_tool(tmp_path):
    clock_values=iter([0,0,0,121,121])
    state=runtime(tmp_path,lambda **kw: reply(),clock=lambda:next(clock_values)).run('im_writer','synthetic')
    assert state['status']=='budget_exhausted'

def test_missing_usage_fails(tmp_path):
    state=runtime(tmp_path,lambda **kw: {'choices':[]}).run('im_writer','synthetic')
    assert state['status']=='failed'

def test_taskboard_dependency_and_human_gate():
    from agents.runtime.taskboard import TaskBoard
    board=TaskBoard()
    board.assign('read','document_analyst','Read permitted sources')
    board.assign('model','modeling_analyst','Design model',['read'])
    with pytest.raises(ValueError): board.transition('model','running')
    board.transition('read','draft_complete')
    assert board.transition('model','running')['status']=='running'
    with pytest.raises(ValueError): board.transition('model','approved')


@pytest.mark.parametrize('same_batch', [True, False])
def test_duplicate_tool_ids_cannot_replay_effects(tmp_path, same_batch):
    effects=[]
    call={'type':'function','id':'same','function':{'name':'wb.read','arguments':'{}'}}
    tool={'validate':lambda arguments: None, 'schema':{'description':'Read', 'parameters':{'type':'object'}},
          'call':lambda: effects.append(1) or {'version':'tools/v1','ok':True,'tool':'wb.read','result':{},'errors':[]}}
    state=runtime(tmp_path,lambda **kw:reply([call,call] if same_batch else [call]),{'wb.read':tool}).run('im_writer','synthetic')
    assert state['status']=='failed'
    assert len(effects)==(0 if same_batch else 1)
    assert 'replay forbidden' in state['error']

@pytest.mark.parametrize('reason', ['length', None, 'content_filter', 'tool_calls'])
def test_nonterminal_final_response_fails(tmp_path, reason):
    response=reply()
    response['choices'][0]['finish_reason']=reason
    state=runtime(tmp_path,lambda **kw:response).run('im_writer','synthetic')
    assert state['status']=='failed'

def test_model_mismatch_prevents_tools(tmp_path):
    response=reply([{'type':'function','id':'x','function':{'name':'wb.read','arguments':'{}'}}])
    response['model']='wrong'
    state=runtime(tmp_path,lambda **kw:response).run('im_writer','synthetic')
    assert state['status']=='failed' and 'model' in state['error']

def test_fake_transport_does_not_claim_raw_http(tmp_path):
    state=runtime(tmp_path,lambda **kw:reply()).run('im_writer','synthetic')
    assert state['receipts']==[]
    assert '"raw_capture": false' in (tmp_path/'trajectory.jsonl').read_text()


def test_schema_validator_rejects_before_tool_side_effect(tmp_path):
    effects=[]
    def validate(arguments):
        if set(arguments) != {'range'}: raise ValueError('invalid schema arguments')
    tool={'schema':{'parameters':{'type':'object'}},'validate':validate,'call':lambda **kwargs:effects.append(kwargs)}
    response=reply([{'type':'function','id':'x','function':{'name':'wb.read','arguments':'{"unexpected":1}'}}])
    state=runtime(tmp_path,lambda **kw:response,{'wb.read':tool}).run('im_writer','synthetic')
    assert state['status']=='failed' and not effects


def test_missing_schema_validator_fails_closed(tmp_path):
    tool={'schema':{'parameters':{'type':'object'}},'call':lambda:pytest.fail('side effect')}
    response=reply([{'type':'function','id':'x','function':{'name':'wb.read','arguments':'{}'}}])
    state=runtime(tmp_path,lambda **kw:response,{'wb.read':tool}).run('im_writer','synthetic')
    assert state['status']=='failed' and 'validator required' in state['error']

@pytest.mark.parametrize('arguments', ['{"x":1,"x":2}', '{"x":NaN}'])
def test_ambiguous_tool_arguments_fail_before_validation(tmp_path, arguments):
    tool={'schema':{'parameters':{'type':'object'}},'validate':lambda args:pytest.fail('ambiguous args validated'),'call':lambda **kw:None}
    response=reply([{'type':'function','id':'x','function':{'name':'wb.read','arguments':arguments}}])
    assert runtime(tmp_path,lambda **kw:response,{'wb.read':tool}).run('im_writer','synthetic')['status']=='failed'


@pytest.mark.parametrize('content', [None, '', '  \n', 1, {}, []])
def test_empty_or_nonliteral_final_cannot_enter_human_review(tmp_path, content):
    response=reply()
    response['choices'][0]['message']['content']=content
    state=runtime(tmp_path,lambda **kw:response).run('im_writer','synthetic')
    assert state['status']=='failed'
    assert 'literal final content' in state['error']

@pytest.mark.parametrize('calls', [None, {}, 'tools', [{'id':'x','function':{'name':'wb.read','arguments':'{}'}}], [{'type':'function','id':'x','function':{'name':'wb.read','arguments':{}}}]])
def test_injected_malformed_tool_call_envelopes_fail(tmp_path, calls):
    response=reply()
    response['choices'][0]['message']['tool_calls']=calls
    response['choices'][0]['finish_reason']='tool_calls'
    state=runtime(tmp_path,lambda **kw:response).run('im_writer','synthetic')
    assert state['status']=='failed'
