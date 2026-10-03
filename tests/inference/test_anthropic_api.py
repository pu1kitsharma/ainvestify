import json
import subprocess
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from agents.inference.anthropic_api import ClaudeAPIModel, run_api
from agents.inference.model_authorship import recorded_call, response_answer
from agents.preparation.preparation_budget import preparation_budget, PreparationBudget, PreparationBudgetExceeded
from agents.research.public_research import PublicResearchModel, Navigation, observed_search, navigate
from agents.inference.subscription_model import make_preparation_model, default_preparation_name


class Answer(BaseModel):
    text: str


def fake_http(monkeypatch, content, *, stop='end_turn', code=0):
    response = {'type': 'message', 'role': 'assistant', 'id': 'msg_test',
                'model': 'claude-sonnet-5', 'content': content, 'stop_reason': stop,
                'usage': {'input_tokens': 50, 'output_tokens': 10}}
    process = Mock(returncode=code)
    process.poll.return_value = code
    process.communicate.return_value = (json.dumps(response), '')
    start = Mock(return_value=process)
    monkeypatch.setattr('agents.inference.anthropic_api.subprocess.Popen', start)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'unit-test-not-a-real-key')
    return start, response


def test_api_is_explicit_and_missing_key_never_falls_back(monkeypatch):
    monkeypatch.setenv('PREPARATION_PROVIDER', 'anthropic_api_public')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY_FILE', raising=False)
    start = Mock()
    monkeypatch.setattr('agents.inference.anthropic_api.subprocess.Popen', start)
    with pytest.raises(ValueError, match='local'):
        default_preparation_name()
    with pytest.raises(ValueError, match='local'):
        make_preparation_model()
    start.assert_not_called()


def test_api_records_exact_answer_and_never_records_key(monkeypatch):
    raw = '{"text": "A model-authored answer."}'
    start, response = fake_http(monkeypatch, [{'type': 'text', 'text': raw}])
    model = ClaudeAPIModel()
    # The transport does not own the public input gate; generate_for_task does.
    model._public_context = {'company': 'Example', 'facts': []}
    attempts = []
    with preparation_budget(PreparationBudget(10, max_calls=1, max_requests=1)) as budget:
        answer, reference = recorded_call(model, 'authored_draft', 'Write JSON',
            {'company': 'Example', 'facts': [], 'request': {}}, Answer, attempts, lambda: None)
    assert response_answer(attempts, reference) == answer.model_dump()
    assert attempts[0]['raw_response'] == raw
    assert attempts[0]['routing']['api_response'] == response
    assert 'unit-test-not-a-real-key' not in json.dumps(attempts)
    assert budget.calls == budget.requests == 1
    body = json.loads(start.return_value.communicate.call_args.kwargs['input'])
    assert 'tools' not in body


def test_private_payload_cannot_reach_api(monkeypatch):
    start, _ = fake_http(monkeypatch, [])
    model = ClaudeAPIModel()
    model._public_context = {'company': 'Example', 'facts': []}
    with pytest.raises(ValueError, match='Private context'):
        model.generate_for_task('authored_draft', 'test',
            json.dumps({'company': 'Example', 'facts': [], 'request': {}, 'private_notes': 'secret'}), Answer)
    start.assert_not_called()


def test_official_search_links_only_and_final_json_is_unchanged(monkeypatch):
    monkeypatch.setenv('PREPARATION_PROVIDER', 'anthropic_api_public')
    answer = {'interpretation': 'Research public company offerings.',
              'urls': ['https://example.com/'], 'official_website': 'https://example.com/'}
    blocks = [{'type': 'text', 'text': 'I will search. https://invented.example/'},
              {'type': 'server_tool_use', 'id': 'search_1', 'name': 'web_search', 'input': {'query': 'example company'}},
              {'type': 'web_search_tool_result', 'tool_use_id': 'search_1', 'content': [
                  {'type': 'web_search_result', 'url': 'https://example.com/', 'title': 'Example'}]},
              {'type': 'text', 'text': json.dumps(answer)}]
    start, response = fake_http(monkeypatch, blocks)
    attempts = []
    with pytest.raises(ValueError, match='local'):
        navigate('Example', 'company', attempts, lambda: None)
    assert observed_search([response])[0] == {'https://example.com/': 'Example'}
    start.assert_not_called()


@pytest.mark.parametrize('stop', ['max_tokens', 'pause_turn', 'refusal'])
def test_incomplete_api_outputs_are_not_accepted_or_retried(monkeypatch, stop):
    start, _ = fake_http(monkeypatch, [{'type': 'text', 'text': '{"text":"partial"}'}], stop=stop)
    with preparation_budget(), pytest.raises(ValueError, match='incomplete'):
        run_api(ClaudeAPIModel(), 'authored_draft', 'test', '{}', Answer)
    assert start.call_count == 1


def test_request_ceiling_stops_search_before_transmission(monkeypatch):
    start, _ = fake_http(monkeypatch, [])
    with preparation_budget(PreparationBudget(10, max_requests=2)), pytest.raises(PreparationBudgetExceeded):
        run_api(ClaudeAPIModel(), 'public_navigation', 'test', '{}', Navigation, web_search=True)
    start.assert_not_called()


def test_cancel_kills_http_process(monkeypatch):
    start, _ = fake_http(monkeypatch, [])
    process = start.return_value
    process.poll.return_value = None
    process.communicate.side_effect = [subprocess.TimeoutExpired('worker', 1), ('', '')]
    model = ClaudeAPIModel()
    model.on_activity = Mock(side_effect=[None, PreparationBudgetExceeded('cancelled')])
    with preparation_budget(), pytest.raises(PreparationBudgetExceeded, match='cancelled'):
        run_api(model, 'authored_draft', 'test', '{}', Answer)
    process.kill.assert_called_once()


def test_public_analysis_uses_api_transport(monkeypatch):
    from agents.analysis.company_analysis import AnalysisModel
    monkeypatch.setenv('PREPARATION_PROVIDER', 'anthropic_api_public')
    fake_http(monkeypatch, [{'type': 'text', 'text': '{"text":"Public analysis"}'}])
    with pytest.raises(ValueError, match='local'):
        AnalysisModel()
