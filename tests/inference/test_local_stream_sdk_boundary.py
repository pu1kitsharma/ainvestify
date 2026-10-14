"""Exercise actual SDK NDJSON parsing at terminal/error/clean-EOF boundaries."""
import json

import httpx
import pytest

from agents.inference import local_models as lm
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from tests.inference.test_local_stream_observation import PIN, Output, model, terminal


@pytest.mark.parametrize('ending', ['terminal', 'runtime_error', 'clean_eof'])
def test_actual_sdk_keeps_terminal_and_does_not_turn_error_or_clean_eof_into_success(monkeypatch, ending):
    actual_client = lm.ollama.AsyncClient
    calls = []
    raw = '{"text":"literal"}'
    frames = [{'model': PIN['name'], 'done': False, 'message': {'role': 'assistant', 'content': raw}}]
    if ending == 'terminal':
        final = terminal()
        final['message']['role'] = 'assistant'
        frames.append(final)
    elif ending == 'runtime_error':
        frames.append({'error': 'synthetic runner stopped'})
    wire = '\n'.join(json.dumps(frame) for frame in frames).encode('utf-8') + b'\n'
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=wire, headers={'content-type': 'application/x-ndjson'})
    monkeypatch.setattr(lm.ollama, 'AsyncClient', lambda **kwargs:
        actual_client(**kwargs, transport=httpx.MockTransport(respond)))
    role = model()
    with preparation_budget(PreparationBudget(2, max_calls=1, max_requests=6)):
        if ending == 'terminal':
            assert role.generate('Typed observation.', '{}', Output).text == 'literal'
        else:
            with pytest.raises((RuntimeError, lm.ollama.ResponseError)):
                role.generate('Typed observation.', '{}', Output)
    assert len(calls) == 1 and calls[0]['stream'] is True
    assert role.last_response_text == raw
    receipt = role.last_call['stream_observation']
    assert receipt['client_close_completed'] is True
    if ending == 'terminal':
        assert receipt['terminal_observed'] is True and receipt['last_chunk_done'] is True
        assert receipt['stream_end'] == 'terminal_frame' and receipt['state'] == 'terminal'
        lm.validate_stream_observation_receipt(role.last_call, raw_response=raw)
    else:
        assert receipt['terminal_observed'] is False and receipt['state'] == 'failed'
        assert receipt['last_chunk_done'] is False
        assert receipt['stream_end'] == ('runtime_error' if ending == 'runtime_error' else 'clean_eof_without_terminal')
        assert receipt['failure_type'] == ('ResponseError' if ending == 'runtime_error' else 'RuntimeError')
        assert len(receipt['failure_message_sha256']) == 64
        assert 'prompt_tokens' not in role.last_call and 'generated_tokens' not in role.last_call
        with pytest.raises(ValueError, match='no completed transport'):
            lm.validate_stream_observation_receipt(role.last_call, raw_response=raw)
