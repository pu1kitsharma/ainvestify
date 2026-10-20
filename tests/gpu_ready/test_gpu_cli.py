import json

import pytest

from agents.inference.endpoint_policy import resolve_selfhosted_route
from agents.inference.selfhosted_client import SelfHostedClient, SelfHostedTransport
from agents.runtime.banker_session import run_banker_session
from tests.selfhosted.fake_openai import TOKEN, FakeServer
from training import gpu_generate as gg


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('SELFHOSTED_TOKEN', TOKEN)
    monkeypatch.setenv('SELFHOSTED_ALLOWED_HOSTS', 'localhost')


def test_bakeoff_without_run_makes_no_request(env, monkeypatch, tmp_path, capsys):
    with FakeServer() as server:
        server.reply(b'{}')
        monkeypatch.setenv('SELFHOSTED_BASE_URL', server.base_url)
        case = tmp_path / 'case.json'
        case.write_text(json.dumps({'sources': [{'text': 'synthetic'}]}))
        assert gg.main(['bakeoff', '--case', str(case), '--output', str(tmp_path / 'o'), '--model', 'banker-base']) == 0
        assert server.requests == []
    assert json.loads(capsys.readouterr().out)['status'] == 'validated_not_run'


def test_banker_session_accepts_private_endpoint_only_with_selfhosted_transport(env, tmp_path):
    with FakeServer() as server:
        server.reply(b'', status=503)            # server fault: must surface as infra fault, not harness rejection
        route = resolve_selfhosted_route('selfhosted:banker-base', base_url=server.base_url, token=TOKEN, allowed_hosts=('localhost',))
        client = SelfHostedClient(route, allowed_hosts=('localhost',))
        report = run_banker_session(case={'sources': [{'text': 's'}]}, output=tmp_path / 'run', model='banker-base',
                                    endpoint=client.endpoint, mode='blocks', block_ids=None,
                                    transport_factory=lambda: SelfHostedTransport(client))
        assert server.requests and server.requests[0]['path'] == '/v1/chat/completions'
        assert report['status'] != 'draft_exported'
        assert TOKEN not in json.dumps(report)
    # the default (Ollama) path still refuses a private endpoint
    with pytest.raises(ValueError):
        run_banker_session(case={'sources': [{'text': 's'}]}, output=tmp_path / 'run2', model='m', endpoint='http://10.0.0.5:8000/v1')


def test_round_cli_requires_private_route(monkeypatch, tmp_path):
    monkeypatch.setenv('SELFHOSTED_TOKEN', TOKEN)
    monkeypatch.setenv('SELFHOSTED_BASE_URL', 'http://8.8.8.8:8000')
    with pytest.raises(ValueError):
        gg.main(['probe', '--facts', 'f', '--base-name', 'b', '--adapter-name', 'a', '--output', str(tmp_path / 'r')])
