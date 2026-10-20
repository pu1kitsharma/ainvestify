import json
import pytest
from agents.runtime.transport import LocalHTTPTransport
from agents.runtime import AgentRuntime

class Response:
    status=200
    def __init__(self, body): self.body=body
    def getheader(self, name): return str(len(self.body))
    def read(self, size):
        data,self.body=self.body[:size],self.body[size:]
        return data

class Connection:
    sock=None
    def __init__(self, response): self.response=response; self.closed=False; self.requests=[]
    def request(self,*args,**kwargs): self.requests.append((args,kwargs))
    def getresponse(self): return self.response
    def close(self): self.closed=True

ENDPOINT='http://127.0.0.1:11434/v1'
def envelope():
    return {'model':'synthetic','choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'synthetic'}}], 'usage':{'total_tokens':3}}

def test_local_transport_single_request():
    connection=Connection(Response(json.dumps(envelope()).encode()))
    transport=LocalHTTPTransport(connection_factory=lambda *a,**k: connection)
    assert transport(endpoint=ENDPOINT,request={},timeout=1)==envelope()
    assert len(connection.requests)==1 and connection.closed
    assert connection.requests[0][0][:2]==('POST','/v1/chat/completions')

@pytest.mark.parametrize('body', [b'{}', b'{"x":NaN}', b'{"choices":[],"choices":[]}'])
def test_bad_envelope_fails(body):
    connection=Connection(Response(body))
    transport=LocalHTTPTransport(connection_factory=lambda *a,**k: connection)
    with pytest.raises(ValueError): transport(endpoint=ENDPOINT,request={},timeout=1)
    assert connection.closed

def test_remote_rejected_before_connection():
    def forbidden(*a,**k): raise AssertionError('network attempted')
    with pytest.raises(ValueError):
        LocalHTTPTransport(connection_factory=forbidden)(endpoint='https://example.com/v1',request={},timeout=1)

def test_redirect_rejected():
    response=Response(b''); response.status=302
    connection=Connection(response)
    with pytest.raises(ValueError):
        LocalHTTPTransport(connection_factory=lambda *a,**k:connection)(endpoint=ENDPOINT,request={},timeout=1)
    assert len(connection.requests)==1

def test_max_size():
    connection=Connection(Response(b'abc'))
    with pytest.raises(ValueError):
        LocalHTTPTransport(max_bytes=2,connection_factory=lambda *a,**k:connection)(endpoint=ENDPOINT,request={},timeout=1)

def test_schema_binding_and_inflight(tmp_path):
    tools={'wb.read':{'schema':{'parameters':{'type':'object'}},'call':lambda:None}}
    runtime=AgentRuntime(endpoint=ENDPOINT,model='synthetic',transport=lambda **kw:None,tools=tools,directory=tmp_path)
    kwargs=dict(endpoint=ENDPOINT,model='synthetic',transport=lambda **kw:None,directory=tmp_path)
    with pytest.raises(ValueError): AgentRuntime.open(**kwargs,tools={})
    runtime.state['status']='inflight'; runtime._save()
    with pytest.raises(ValueError): AgentRuntime.open(**kwargs,tools=tools)

@pytest.mark.parametrize('tamper', ['response', 'manifest'])
def test_runtime_retains_exact_wire_bytes_and_detects_tamper(tmp_path, tamper):
    raw=b'  '+json.dumps(envelope()).encode()+b'\n'
    connection=Connection(Response(raw))
    transport=LocalHTTPTransport(connection_factory=lambda *a,**k:connection)
    runtime=AgentRuntime(endpoint=ENDPOINT,model='synthetic',transport=transport,tools={},directory=tmp_path)
    state=runtime.run('im_writer','synthetic')
    assert state['status']=='human_review_required'
    response_path=tmp_path/'receipts/call-0001-response.bin'
    assert response_path.read_bytes()==raw
    assert (tmp_path/'receipts/call-0001-request.bin').read_bytes()==connection.requests[0][1]['body']
    assert state['receipts'][1]['request_sha256']==state['receipts'][0]['sha256']
    target=response_path if tamper=='response' else response_path.with_name(response_path.name+'.json')
    target.write_bytes(b'tamper')
    with pytest.raises(ValueError,match='tamper'):
        AgentRuntime.open(endpoint=ENDPOINT,model='synthetic',transport=transport,tools={},directory=tmp_path)

def test_malformed_wire_bytes_retained_before_parse(tmp_path):
    connection=Connection(Response(b'not json'))
    transport=LocalHTTPTransport(connection_factory=lambda *a,**k:connection)
    runtime=AgentRuntime(endpoint=ENDPOINT,model='synthetic',transport=transport,tools={},directory=tmp_path)
    assert runtime.run('im_writer','synthetic')['status']=='failed'
    assert (tmp_path/'receipts/call-0001-response.bin').read_bytes()==b'not json'

def test_invalid_final_retains_raw_receipts_and_failed_status(tmp_path):
    payload=envelope()
    payload['choices'][0]['message']['content']=''
    raw=json.dumps(payload).encode()
    connection=Connection(Response(raw))
    transport=LocalHTTPTransport(connection_factory=lambda *a,**k:connection)
    runtime=AgentRuntime(endpoint=ENDPOINT,model='synthetic',transport=transport,tools={},directory=tmp_path)
    state=runtime.run('im_writer','synthetic')
    assert state['status']=='failed' and len(state['receipts'])==2
    assert (tmp_path/'receipts/call-0001-response.bin').read_bytes()==raw
    assert 'nonempty literal final content required' in (tmp_path/'trajectory.jsonl').read_text()
