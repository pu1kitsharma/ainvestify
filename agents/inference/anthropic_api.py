"""Official Messages API transport for bounded public-evidence work.

The HTTP worker is a separate process so cancellation and the shared wall-clock
deadline also stop a stalled network response. No subscription credentials or
automatic provider fallback are used. Secrets never enter recorded routing.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from agents.inference.model_output import json_body
from agents.preparation.preparation_budget import ACTIVE_BUDGET
from agents.inference.subscription_model import ClaudeProModel

API_PREFIX = 'anthropic-api:'


def api_model_name():
    return API_PREFIX + os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5')


def run_api(model, task, instruction, evidence, schema, *, web_search=False):
    budget = ACTIVE_BUDGET.get()
    if budget is None:
        raise ValueError('A bounded preparation budget is required for API inference.')
    model.last_response_text = ''
    model.last_route = {'invoked': False, 'provider': 'anthropic_api',
                        'data_scope': 'public_website_evidence', 'model': model.name}
    secret = os.environ.get('ANTHROPIC_API_KEY', '')
    if not secret and os.environ.get('ANTHROPIC_API_KEY_FILE'):
        secret = Path(os.environ['ANTHROPIC_API_KEY_FILE']).read_text().strip()
    if not secret:
        raise ValueError('Configure the server-side ANTHROPIC_API_KEY or ANTHROPIC_API_KEY_FILE. No subscription fallback was used.')
    # Reserve the initial response plus at most two search continuations before
    # sending anything. This retains the existing six-main-request ceiling.
    reserved = 3 if web_search else 1
    for _ in range(reserved):
        budget.start_request()
    body = {'model': model.name.removeprefix(API_PREFIX), 'max_tokens': 6000,
            'system': instruction + '\nReturn only a JSON object matching this schema. No commentary or tool wrappers.\n' + json.dumps(schema.model_json_schema()),
            'messages': [{'role': 'user', 'content': evidence}]}
    if web_search:
        body['tools'] = [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 2}]
        body['system'] += '\nWebSearch means the web_search tool. Use it at least once, at most twice. Put the final JSON after all tool results.'
    env = os.environ.copy()
    env['ANTHROPIC_API_KEY'] = secret
    started = time.monotonic()
    process = subprocess.Popen([sys.executable, '-m', 'agents.inference.anthropic_http_worker'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, cwd=str(Path(__file__).resolve().parents[2]))
    model.last_route['invoked'] = True
    pending = json.dumps(body)
    try:
        while True:
            if getattr(model, 'on_activity', None):
                model.on_activity('generating', 0, task)
            try:
                stdout, _ = process.communicate(input=pending, timeout=min(1, budget.remaining()))
                break
            except subprocess.TimeoutExpired:
                pending = None
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        model.last_route['elapsed_seconds'] = round(time.monotonic() - started, 3)
    try:
        response = json.loads(stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError('The Claude API returned an unreadable response.') from exc
    if process.returncode or 'error' in response:
        # Worker returns only a fixed error category/status, never request headers
        # or an upstream error body which could echo input or credentials.
        model.last_route['http_status'] = response.get('status')
        raise ValueError('Claude API request failed (HTTP %s). Check server credentials, credit and model access; no fallback or retry was used.' % response.get('status', 'transport'))
    model.last_route['api_response'] = response
    model.last_route['usage'] = response.get('usage', {})
    blocks = response.get('content', [])
    # For navigation, preliminary search commentary is retained in api_response;
    # only the exact final text segment after the final tool result is the answer.
    final_start = max((i + 1 for i, b in enumerate(blocks) if b.get('type') == 'web_search_tool_result'), default=0)
    model.last_response_text = ''.join(b.get('text', '') for b in blocks[final_start:] if b.get('type') == 'text')
    calls = [b for b in blocks if b.get('type') == 'server_tool_use']
    if response.get('stop_reason') != 'end_turn':
        raise ValueError('Claude API response was incomplete; its original output is retained without an automatic continuation.')
    if web_search:
        if not 1 <= len(calls) <= 2 or any(b.get('name') != 'web_search' for b in calls):
            raise ValueError('Public navigation exceeded its search-only contract or did not search.')
        results = [b for b in blocks if b.get('type') == 'web_search_tool_result']
        if any(not isinstance(b.get('content'), list) for b in results):
            raise ValueError('Public web search returned an error; no invented result was substituted.')
        model.search_transcript = [response]
        model.last_route['search_transcript'] = model.search_transcript
        budget.requests -= reserved - (len(calls) + 1)
    elif any(b.get('type') != 'text' for b in blocks):
        raise ValueError('Drafting must return one tool-free text response.')
    model.last_route['inference_turns'] = len(calls) + 1
    return schema.model_validate_json(json_body(model.last_response_text))


class ClaudeAPIModel(ClaudeProModel):
    """Reuse the public payload boundary, not subscription authentication."""
    def __init__(self, name=None):
        super().__init__()
        self.name = name or api_model_name()

    def _run_cli(self, task, instruction, evidence, schema, *, web_search=False):
        return run_api(self, task, instruction, evidence, schema, web_search=web_search)
