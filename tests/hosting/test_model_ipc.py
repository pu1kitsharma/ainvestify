"""Synthetic relay and native namespace checks; never call a real model."""
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import socket
import sys
import time
import threading
import http.client

import httpx
import pytest

from delivery import model_ipc, isolation
from agents.inference.local_transport import transport_kwargs


@pytest.mark.parametrize('method,path,body', [
    ('POST', '/api/pull', b'{"model":"qwen3:8b"}'),
    ('POST', '/api/create', b'{"model":"qwen3:8b"}'),
    ('DELETE', '/api/delete', b'{"model":"qwen3:8b"}'),
    ('POST', '/api/chat?redirect=https://outside.example', b'{"model":"qwen3:8b"}'),
    ('POST', 'http://127.0.0.1:11434/api/chat', b'{"model":"qwen3:8b"}'),
    ('POST', '/api/chat', b'{"model":"model:cloud"}'),
    ('POST', '/api/chat', b'[]'),
    ('GET', '/api/tags', b'private-body'),
])
def test_admission_refuses_management_cloud_and_ambiguous_requests(method, path, body):
    with pytest.raises(ValueError):
        model_ipc.admit_request(method, path, body)


def test_admission_accepts_only_metadata_and_explicit_local_operations():
    model_ipc.admit_request('GET', '/api/tags', b'')
    model_ipc.admit_request('POST', '/api/chat', b'{"model":"qwen3.5:9b","messages":[]}')


def test_transport_default_unchanged_and_arbitrary_capabilities_rejected(monkeypatch):
    monkeypatch.delenv('PRIVATE_OLLAMA_SOCKET', raising=False)
    assert transport_kwargs() == {}
    monkeypatch.setenv('PRIVATE_OLLAMA_SOCKET', '/tmp/another.sock')
    with pytest.raises(ValueError):
        transport_kwargs()


class Response(BytesIO):
    status = 200

    def getheader(self, name):
        return 'application/x-ndjson' if name == 'Content-Type' else None


class FakeConnection:
    requests = []
    sock = None
    response = b'{"model":"qwen3:8b","message":{"role":"assistant","content":"synthetic"},"done":true}\n'
    response_status = 200

    def __init__(self, host, port, *, timeout):
        assert (host, port) == ('127.0.0.1', 11434) and 0 < timeout <= 120

    def connect(self):
        pass

    def request(self, method, path, *, body, headers):
        assert set(headers) == {'Content-Type', 'Connection'}
        self.path = path
        self.requests.append((method, path, body))

    def getresponse(self):
        response = Response(b'{"models":[]}' if self.path == '/api/tags' else self.response)
        response.status = self.response_status
        return response

    def close(self):
        pass


linux_only = pytest.mark.skipif(platform.system() != 'Linux', reason='Mandatory native Unix IPC qualification requires Linux')


@linux_only
def test_relay_preserves_bytes_caps_requests_denies_credentials_and_cleans_socket(monkeypatch):
    FakeConnection.requests = []
    with model_ipc.model_relay(timeout=8, _connection_factory=FakeConnection) as path:
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(path)), trust_env=False) as client:
            base = 'http://127.0.0.1:11434'
            assert client.post(base + '/api/pull', json={'model': 'qwen3:8b'}).status_code == 403
            assert client.get(base + '/api/tags', headers={'Authorization': 'Bearer synthetic-secret'}).status_code == 400
            for _ in range(6):
                response = client.post(base + '/api/chat', json={'model': 'qwen3:8b'})
                assert response.status_code == 200 and response.content == FakeConnection.response
            assert client.get(base + '/api/tags').status_code == 403
        assert len(FakeConnection.requests) == 6
    assert not path.exists() and not path.parent.exists()


@linux_only
def test_redirects_never_reach_client(monkeypatch):
    monkeypatch.setattr(FakeConnection, 'response_status', 302)
    with model_ipc.model_relay(timeout=5, _connection_factory=FakeConnection) as path:
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(path))) as client:
            response = client.get('http://127.0.0.1:11434/api/tags')
            assert response.status_code == 502 and not response.headers.get('location')


@linux_only
def test_deadline_closes_a_stalled_header_without_hanging_cleanup():
    started = time.monotonic()
    with model_ipc.model_relay(timeout=.3, _connection_factory=FakeConnection) as path:
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(2)
            peer.connect(str(path))
            peer.sendall(b'GET /api/tags HTTP/1.1\r\nHost:')
            assert peer.recv(1) == b''
    assert time.monotonic() - started < 2


@linux_only
def test_client_cancellation_closes_upstream_before_any_model_output():
    started, cancelled = threading.Event(), threading.Event()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(3)
        def fake_ollama():
            with listener.accept()[0] as peer:
                peer.settimeout(2)
                raw = b''
                while b'\r\n\r\n' not in raw:
                    raw += peer.recv(4096)
                headers, body = raw.split(b'\r\n\r\n', 1)
                length = int(next(line.split(b':', 1)[1] for line in headers.split(b'\r\n')
                                  if line.lower().startswith(b'content-length:')))
                while len(body) < length:
                    body += peer.recv(4096)
                started.set()
                if peer.recv(1) == b'':
                    cancelled.set()
        upstream = threading.Thread(target=fake_ollama, daemon=True)
        upstream.start()
        def connection(host, port, *, timeout):
            assert (host, port) == ('127.0.0.1', 11434)
            return http.client.HTTPConnection('127.0.0.1', listener.getsockname()[1], timeout=timeout)
        with model_ipc.model_relay(timeout=5, _connection_factory=connection) as path:
            with socket.socket(socket.AF_UNIX) as peer:
                peer.connect(str(path))
                body = b'{"model":"qwen3:8b"}'
                peer.sendall(b'POST /api/chat HTTP/1.1\r\nHost: 127.0.0.1:11434\r\nContent-Length: '
                             + str(len(body)).encode() + b'\r\n\r\n' + body)
                assert started.wait(2)
            assert cancelled.wait(1), 'Ollama remained active after the worker disconnected'
        upstream.join(timeout=2)


@linux_only
def test_directory_literal_never_becomes_a_recursive_read_grant(tmp_path):
    with pytest.raises(RuntimeError, match='directory_literal_unsupported'):
        isolation.build_bwrap_command(['true'], tmp_path, bwrap='b', project=tmp_path,
                                      extra_read_literals=[tmp_path])


@linux_only
def test_native_bwrap_allows_one_model_socket_but_denies_host_network_siblings_and_secrets(tmp_path, monkeypatch):
    if not isolation.bwrap_binary():
        pytest.skip('Mandatory native IPC qualification UNRUN: bubblewrap absent')
    job = tmp_path / 'job'
    job.mkdir(mode=0o700)
    sibling = tmp_path / 'sibling-private.txt'
    sibling.write_text('synthetic private sibling')
    monkeypatch.setenv('PRIVATE_MODEL_IPC', model_ipc.CONTRACT)
    monkeypatch.setenv('SYNTHETIC_HOST_SECRET', 'must-not-be-in-worker')
    real_relay = model_ipc.model_relay
    monkeypatch.setattr(model_ipc, 'model_relay', lambda **kw: real_relay(**kw, _connection_factory=FakeConnection))
    code = '''
import os,socket,sys,json,asyncio
from pathlib import Path
import ollama
from agents.inference.local_transport import transport_kwargs,local_tags
assert not os.environ.get('SYNTHETIC_HOST_SECRET')
assert not Path(sys.argv[1]).exists()
assert [name for _,name in socket.if_nameindex()] == ['lo']
s=socket.socket();s.settimeout(.2)
try:
 s.connect(('127.0.0.1',int(sys.argv[2])))
except OSError: pass
else: raise AssertionError('host TCP listener was reachable')
finally: s.close()
for asynchronous in (False,True):
 kwargs=transport_kwargs(asynchronous=asynchronous)
 assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
client=ollama.Client(host='http://127.0.0.1:11434',**transport_kwargs())
response=client.chat(model='qwen3:8b',messages=[{'role':'user','content':'synthetic fixture'}])
assert response.message.content == 'synthetic'
client._client.close()
async def streamed():
 client=ollama.AsyncClient(host='http://127.0.0.1:11434',**transport_kwargs(asynchronous=True))
 try:
  chunks=[]
  async for chunk in await client.chat(model='qwen3:8b',messages=[{'role':'user','content':'synthetic fixture'}],stream=True):
   chunks.append(chunk)
  assert chunks[-1].done is True and ''.join(c.message.content for c in chunks) == 'synthetic'
 finally:
  await client._client.aclose()
asyncio.run(streamed())
assert local_tags() == {'models': []}
print('native_private_model_ipc_pass')
'''
    project = Path(__file__).resolve().parents[2]
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        raw = isolation.run_private([sys.executable, '-B', '-c', code, str(sibling), str(listener.getsockname()[1])],
            job, timeout=12, extra_read=[project / 'agents'], local_model=True)
    assert raw.strip() == b'native_private_model_ipc_pass'
    assert sibling.read_text() == 'synthetic private sibling'
