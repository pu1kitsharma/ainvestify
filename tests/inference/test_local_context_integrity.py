"""A valid JSON answer cannot conceal dropped instructions or evidence."""
import json
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from agents.inference.local_models import LocalModel


class Answer(BaseModel):
    answer: str


def model(count=7100, **policies):
    adapter = LocalModel('qwen3:14b', context_tokens=8192, max_tokens=600,
                         compact_prompt=True, require_full_context=True, **policies)
    adapter.client = Mock()
    adapter.client.chat.return_value = {'model': 'qwen3:14b', 'done_reason': 'stop',
        'message': {'content': '{"answer":"Recorded model answer"}'},
        'prompt_eval_count': count, 'prompt_eval_cached_count': 31, 'eval_count': 10}
    return adapter


def test_compaction_preserves_all_evidence_and_uses_the_complete_schema():
    adapter = model()
    evidence = {'sources': [{'id': 'S1', 'passage': 'Quoted ₹ text\nwith spaces  retained.'}],
                'flags': [True, None], 'amount': 1.25}
    assert adapter.generate('Use the sources', json.dumps(evidence), Answer).answer == 'Recorded model answer'
    messages = adapter.client.chat.call_args.kwargs['messages']
    assert json.loads(messages[1]['content']) == evidence
    assert '₹' in messages[1]['content']
    schema = messages[0]['content'].split('Follow field descriptions and length limits:\n', 1)[1]
    assert json.loads(schema) == Answer.model_json_schema()
    assert adapter.last_call['prompt_tokens'] == 7100
    assert adapter.last_call['prompt_cached_tokens'] == 31


@pytest.mark.parametrize('count, error', [(4098, 'overflow cutoff'), (8000, 'output headroom'),
                                         (None, 'token receipt'), (True, 'token receipt'), (0, 'token receipt')])
def test_normal_stop_and_valid_json_do_not_override_context_failure(count, error):
    adapter = model(count)
    with pytest.raises(ValueError, match=error):
        adapter.generate('Use complete evidence', '{}', Answer)
    assert adapter.last_response_text == '{"answer":"Recorded model answer"}'
    assert adapter.last_call['require_full_context'] is True


def test_historical_calls_preserve_transport_and_do_not_gain_a_new_policy():
    adapter = LocalModel('qwen3:14b', context_tokens=8192, max_tokens=600)
    adapter.client = Mock()
    adapter.client.chat.return_value = {'message': {'content': '{"answer":"Old answer"}'},
                                      'prompt_eval_count': 4098}
    evidence = '{ "old": "source" }'
    assert adapter.generate('Old task', evidence, Answer).answer == 'Old answer'
    assert adapter.client.chat.call_args.kwargs['messages'][1]['content'] == evidence
    assert 'require_full_context' not in adapter.last_call
    assert 'compact_prompt' not in adapter.last_call


def test_invalid_compact_evidence_fails_before_inference():
    adapter = model()
    with pytest.raises(json.JSONDecodeError):
        adapter.generate('Task', 'not JSON', Answer)
    adapter.client.chat.assert_not_called()
