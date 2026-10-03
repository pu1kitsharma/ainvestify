"""Legacy deal routes must use an explicit loopback inference transport."""
import ast
from pathlib import Path

import httpx
import ollama
import pytest

from agents.inference.local_ollama import local_chat, local_embed


def test_legacy_transport_ignores_remote_ollama_host(monkeypatch):
    monkeypatch.setenv('OLLAMA_HOST', 'https://remote.example.test')
    hosts = []

    class Client:
        def __init__(self, *, host, timeout):
            hosts.append(host)

        def chat(self, **kwargs):
            return {'model': 'phi4-mini', 'done_reason': 'stop',
                    'message': {'content': '{"answer":"local"}'}}

        def embed(self, **kwargs):
            return {'model': 'bge-large', 'embeddings': [[1.0, 0.0]]}

    monkeypatch.setattr(ollama, 'Client', Client)
    assert local_chat(model='phi4-mini', messages=[{'role': 'user', 'content': 'synthetic'}])['message']['content']
    assert local_embed(model='bge-large', input='synthetic')['embeddings']
    assert hosts == ['http://127.0.0.1:11434'] * 2


@pytest.mark.parametrize('bad', ['https://remote.example.test/model', 'anthropic-api:sonnet', 'cloud-model'])
def test_legacy_transport_rejects_remote_model_selectors(monkeypatch, bad):
    monkeypatch.setattr(ollama, 'Client', lambda **kwargs: pytest.fail('Client must not start'))
    with pytest.raises(ValueError, match='local model name'):
        local_chat(model=bad, messages=[])


def test_legacy_transport_fails_closed_on_wrong_model_or_interruption(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            return {'model': 'another-model', 'done_reason': 'stop', 'message': {'content': '{}'}}

    monkeypatch.setattr(ollama, 'Client', Client)
    with pytest.raises(ValueError, match='different model'):
        local_chat(model='phi4-mini', messages=[])
    Client.chat = lambda self, **kwargs: {'model': 'phi4-mini', 'done_reason': 'cancelled', 'message': {'content': '{}'}}
    with pytest.raises(ValueError, match='did not finish normally'):
        local_chat(model='phi4-mini', messages=[])


def test_legacy_transport_reports_local_outage_without_fallback(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            raise httpx.ConnectError('refused')

    monkeypatch.setattr(ollama, 'Client', Client)
    with pytest.raises(RuntimeError, match='no hosted fallback'):
        local_chat(model='phi4-mini', messages=[])


def test_active_legacy_routes_do_not_call_module_level_ollama():
    root = Path(__file__).resolve().parents[2]
    paths = ['main.py', 'agents/core/extraction_agent.py', 'agents/core/planner_agent.py',
             'agents/core/compilation_agent.py', 'agents/core/research_agent.py']
    for name in paths:
        tree = ast.parse((root / name).read_text())
        assert not any(isinstance(node, ast.Attribute) and node.attr in {'chat', 'embed', 'generate'}
                       and isinstance(node.value, ast.Name) and node.value.id == 'ollama'
                       for node in ast.walk(tree)), name
