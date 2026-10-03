"""Personal Claude Pro CLI adapter for explicitly bounded public-source drafting.

The official CLI owns authentication. No tokens, API keys, tools or automatic
provider fallback are used. Private records never belong in this adapter's input.
"""
import json
import os
import re
import signal
import subprocess
import tempfile
import time

from agents.inference.model_output import json_body
from agents.preparation.preparation_budget import ACTIVE_BUDGET, PreparationBudgetExceeded


PRO_MODEL = 'claude-pro-sonnet'
PRO_MODEL_ID = 'claude-sonnet-5'


class TransientSubscriptionError(ValueError):
    """Interrupted provider response; retry only inside the shared budget."""


class SubscriptionLimitError(RuntimeError):
    """Quota requires waiting for the provider reset, not a content retry."""


class SubscriptionModelError(RuntimeError):
    """Unavailable or unexpected model; never silently switch models."""


class SubscriptionAccessError(RuntimeError):
    """Authentication/provider availability needs external action, not repair."""


class ClaudeProModel:
    name = PRO_MODEL
    combined_draft = True
    public_only = True
    thinking = False
    shared_review_thinking = None
    native_structured_output = False

    def __init__(self, capture=None):
        self.last_route = {}
        self.last_response_text = ''
        self._authenticated = False
        self._public_context = None
        self.capture = capture
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('ANTHROPIC_', 'CLAUDE_'))}

    def check_subscription(self):
        if self._authenticated:
            return
        budget = ACTIVE_BUDGET.get()
        status = subprocess.run(['claude', '--safe-mode', '--setting-sources', '', 'auth', 'status', '--json'],
            env=self.env, capture_output=True, text=True, timeout=min(20, budget.remaining()) if budget else 20)
        try:
            account = json.loads(status.stdout)
        except ValueError as exc:
            raise SubscriptionAccessError('Claude Pro sign-in could not be checked. Sign in with the official Claude CLI; no API fallback was used.') from exc
        if status.returncode or not account.get('loggedIn') or account.get('authMethod') != 'claude.ai' or account.get('subscriptionType') != 'pro':
            raise SubscriptionAccessError('Claude Pro is not signed in for this local worker. Run claude auth login in Terminal. No API fallback was used.')
        self._authenticated = True

    def set_public_context(self, company, facts):
        from agents.preparation.preparation_sources import inference_facts, is_public_source
        if not facts or not all(is_public_source(fact) for fact in facts):
            raise ValueError('Claude Pro preparation requires collected public website evidence only.')
        self._public_context = {'company': company, 'facts': inference_facts(facts)}

    def _check_payload(self, evidence):
        data = json.loads(evidence)
        allowed = {'company', 'request', 'facts', 'previous_work', 'answer_to_correct', 'correction_required', 'sections'}
        if (not self._public_context or not isinstance(data, dict) or not set(data) <= allowed
                or data.get('request') not in ({}, '', None)
                or any(data.get(key) != value for key, value in self._public_context.items())):
            raise ValueError('The remote drafting payload differs from its approved public evidence. Private context was not sent.')

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        self.last_response_text = ''
        self.last_route = {'invoked': False, 'provider': 'claude_pro_subscription', 'data_scope': 'public_website_evidence'}
        if task not in {'authored_draft', 'authored_research', 'authored_work', 'authored_founder', 'authored_review'}:
            raise ValueError('The subscription adapter is restricted to public company preparation.')
        self._check_payload(evidence)
        return self._run_cli(task, instruction, evidence, schema)

    def _run_cli(self, task, instruction, evidence, schema, *, web_search=False):
        budget = ACTIVE_BUDGET.get()
        if budget is None:
            raise ValueError('A bounded preparation budget is required for subscription inference.')
        self.check_subscription()
        effort = 'low' if web_search or task == 'authored_review' or 'correction_required' in json.loads(evidence) else 'medium'
        effort = getattr(self, 'task_effort', {}).get(task, effort)
        native = self.native_structured_output and not web_search
        contract = ('\nReturn only one JSON object matching this schema. Use the root schema keys directly, without tool wrappers. Follow every field limit; corrected prose should aim below half the maximum length.\n' if not native else
                    '\nCall StructuredOutput with the schema fields directly as its input object. Do NOT wrap the object in a StructuredOutput key or encode it as a string. Follow all field limits; corrected prose should use short sentences and aim below half the maximum length. Exact schema:\n') + json.dumps(schema.model_json_schema())
        command = ['claude', '--safe-mode', '--setting-sources', '', '--tools', 'WebSearch' if web_search else '',
            '--strict-mcp-config', '--disable-slash-commands', '--no-chrome',
            '--permission-mode', 'dontAsk', '--no-session-persistence', '--model', PRO_MODEL_ID,
            '--effort', effort, '--output-format', 'json', '--system-prompt', instruction + contract, '-p']
        turns = 3 if web_search else 1
        if web_search:
            command += ['--allowedTools', 'WebSearch', '--max-turns', '2', '--verbose']
        else:
            command += ['--verbose', '--max-turns', '1']
            if native:
                command += ['--json-schema', json.dumps(schema.model_json_schema())]
        for _ in range(turns):
            budget.start_request()
        started = time.monotonic()
        self.last_route.update(invoked=True, model=self.name, tools=['WebSearch'] if web_search else [], effort=effort,
                               requested_model=PRO_MODEL_ID,
                               format_enforcement='search_json_then_local_validation' if web_search else 'native_structured_output_then_local_validation' if native else 'json_then_local_validation')
        with tempfile.TemporaryDirectory(prefix='ainvestify-public-draft-') as cwd:
            process = subprocess.Popen(command, cwd=cwd, env=self.env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            pending_input = evidence
            try:
                while True:
                    callback = getattr(self, 'on_activity', None)
                    if callback:
                        callback('generating', 0, task)
                    try:
                        stdout, _ = process.communicate(input=pending_input, timeout=min(1, budget.remaining()))
                        break
                    except subprocess.TimeoutExpired:
                        pending_input = None
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate()
                self.last_route['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if self.capture:
            self.capture(stdout)
        try:
            envelope = json.loads(stdout)
        except ValueError as exc:
            raise ValueError('Claude Pro returned an unreadable response; retained drafts are unchanged.') from exc
        if not isinstance(envelope, list):
            raise ValueError('Claude returned no auditable tool transcript.')
        transcript = envelope
        self.last_route['search_transcript' if web_search else 'structured_transcript'] = transcript
        if web_search: self.search_transcript = transcript
        envelope = next((row for row in reversed(transcript) if row.get('type') == 'result'), {})
        self.last_response_text = envelope.get('result', '')
        self.last_route.update(cli_usage=envelope.get('usage'), model_usage=envelope.get('modelUsage'),
            num_turns=envelope.get('num_turns'), cli_subtype=envelope.get('subtype'),
            api_equivalent_estimate_usd=envelope.get('total_cost_usd'))
        actual_models=sorted({row['message']['model'] for row in transcript if row.get('type')=='assistant' and row.get('message',{}).get('model')})
        self.last_route['response_models']=actual_models
        if any(name!=PRO_MODEL_ID for name in actual_models):
            raise SubscriptionModelError('The provider returned a different model than the requested Sonnet 5. No answer was accepted.')
        if envelope.get('is_error') and 'issue with the selected model' in self.last_response_text.casefold():
            raise SubscriptionModelError('Sonnet 5 is unavailable to this account. No fallback model was used.')
        if envelope.get('is_error') and re.search(r"you.ve hit (?:your )?(?:session|usage|weekly) limit|usage limit reached",self.last_response_text,re.I):
            reset=re.search(r'resets\s+([^\n]+)',self.last_response_text,re.I)
            when=f" Try again after {reset.group(1).strip()}." if reset else ' Try again after the subscription limit resets.'
            raise SubscriptionLimitError('Claude Pro usage limit reached.'+when+' Saved work is retained.')
        if envelope.get('is_error') and any(marker in self.last_response_text.casefold() for marker in (
                'connection closed mid-response', 'connection reset', 'overloaded_error')):
            raise TransientSubscriptionError('Claude connection was interrupted before a complete answer arrived. Original output is retained.')
        if native and (process.returncode or envelope.get('is_error')):
            # Retain the actual invalid model object so the existing bounded
            # schema-correction path can handle it. A formatting failure must
            # not masquerade as a subscription/authentication outage.
            messages = [row['message'] for row in transcript if row.get('type') == 'assistant']
            objects = [item['input'] for message in messages for item in message.get('content', [])
                       if item.get('type') == 'tool_use' and item.get('name') == 'StructuredOutput']
            if len({m.get('id') for m in messages}) == 1 and len(objects) == 1:
                self.last_response_text = json.dumps(objects[0], ensure_ascii=False)
                schema.model_validate_json(self.last_response_text)
            raise ValueError('Claude could not return a valid structured response within its single-response limit. Original output is retained.')
        if process.returncode or envelope.get('is_error'):
            raise SubscriptionAccessError('Claude Pro could not complete this request. Check subscription availability; no paid API fallback was used.')
        actual_turns = envelope.get('num_turns')
        if web_search:
            tool_uses = [item for row in self.search_transcript if row.get('type') == 'assistant'
                         for item in row.get('message', {}).get('content', []) if item.get('type') == 'tool_use']
            if actual_turns not in (2, 3) or not 1 <= len(tool_uses) <= 2 or any(item.get('name') != 'WebSearch' for item in tool_uses):
                raise ValueError('Public navigation exceeded its bounded search-only contract.')
            budget.requests -= turns - actual_turns
        elif native:
            messages = [row['message'] for row in transcript if row.get('type') == 'assistant']
            outputs = [item['input'] for message in messages for item in message.get('content', [])
                       if item.get('type') == 'tool_use' and item.get('name') == 'StructuredOutput']
            message_ids = {message.get('id') for message in messages}
            other_tools = [item for message in messages for item in message.get('content', [])
                           if item.get('type') == 'tool_use' and item.get('name') != 'StructuredOutput']
            if len(message_ids) != 1 or len(outputs) != 1 or other_tools or outputs[0] != envelope.get('structured_output'):
                raise ValueError('Structured output did not come from one bounded model response; hidden repair loops are not accepted.')
            if json.loads(json_body(self.last_response_text)) != outputs[0]:
                raise ValueError('Structured result differs from the recorded model tool response.')
            self.last_route['inference_turns'] = 1
        else:
            messages = [row['message'] for row in transcript if row.get('type') == 'assistant']
            content = [item for message in messages for item in message.get('content', [])]
            text = ''.join(item.get('text', '') for item in content if item.get('type') == 'text')
            if (actual_turns != 1 or len({message.get('id') for message in messages}) != 1
                    or any(item.get('type') == 'tool_use' for item in content) or text != self.last_response_text):
                raise ValueError('JSON result did not come from one recorded tool-free model response.')
            self.last_route['inference_turns'] = 1
        return schema.model_validate_json(json_body(self.last_response_text))


def default_preparation_name():
    provider = os.environ.get('PREPARATION_PROVIDER', 'local')
    if provider != 'local':
        raise ValueError('Only local model responses are enabled; set PREPARATION_PROVIDER=local.')
    from agents.inference.local_models import PreparationModel, shared_model_name
    return shared_model_name(PreparationModel())


def is_public_preparation_name(name):
    return name == PRO_MODEL or name.startswith(('anthropic-api:', 'deepseek-api:'))


def make_preparation_model(selection=None, *, thinking=False, review_model=None, review_thinking=None):
    if os.environ.get('PREPARATION_PROVIDER', 'local') != 'local':
        raise ValueError('Only local model responses are enabled; set PREPARATION_PROVIDER=local.')
    selected = default_preparation_name() if not selection or selection == 'auto' else selection
    if is_public_preparation_name(selected) or (review_model and is_public_preparation_name(review_model)):
        raise ValueError('Hosted model response routes are retired; select an installed local model.')
    from agents.inference.local_models import AnalystModel
    return AnalystModel(selected, thinking=thinking, review_model=review_model, review_thinking=review_thinking)
