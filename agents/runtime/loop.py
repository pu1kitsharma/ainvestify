"""Bounded, fail-closed tool loop with an injected OpenAI-compatible transport.

Transport signature: transport(endpoint=..., request=..., timeout=seconds) -> dict.
It must honor timeout and must not redirect, retry or select another endpoint.
No transport is installed by default. Checkpoints and trajectories are PRIVATE.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit


REPAIR_HINT = ('Arguments must be one JSON object matching the schema. Matrices are arrays of arrays of '
               'literals (numbers/strings/booleans/null), never a JSON string. Formulas are strings starting with "=" '
               '(e.g. "=B2*C2"); never put arithmetic like 1/12 or a stringified array where a number or array is required. '
               'Keep the case unit (e.g. USD thousands) and do not rescale.')


def validate_endpoint(endpoint):
    if not isinstance(endpoint, str) or any(char.isspace() for char in endpoint):
        raise ValueError('literal loopback endpoint without whitespace required')
    url = urlsplit(endpoint)
    try:
        address = ipaddress.ip_address(url.hostname or '')
        port = url.port
    except ValueError as exc:
        raise ValueError('literal loopback IP required') from exc
    if (url.scheme != 'http' or not address.is_loopback or url.username or url.password
            or url.query or url.fragment or port is None or port == 0):
        raise ValueError('local phase requires http literal loopback IP and explicit port')
    if url.path.rstrip('/') != '/v1':
        raise ValueError('endpoint path must be /v1')
    return endpoint.rstrip('/')


@dataclass(frozen=True)
class Role:
    name: str
    tools: tuple[str, ...]
    steps: int = 6
    tokens: int = 8192


ROLES = {
    'deal_lead': Role('deal_lead', ('task.assign', 'task.status', 'pack.blueprint')),
    'document_analyst': Role('document_analyst', ('doc.pages', 'doc.text', 'doc.tables', 'doc.page_image', 'pptx.chart_series', 'xlsx.read')),
    'modeling_analyst': Role('modeling_analyst', ('wb.add_sheet', 'wb.write', 'wb.write_block', 'wb.name', 'wb.style', 'wb.comment', 'wb.read', 'wb.trace', 'wb.recalc'), tokens=32768),
    'market_analyst': Role('market_analyst', ('wb.read', 'wb.write', 'wb.add_sheet', 'wb.comment')),
    'qc_associate': Role('qc_associate', ('wb.read', 'wb.trace', 'wb.recalc', 'doc.text', 'doc.tables', 'flag.raise', 'task.return')),
    'im_writer': Role('im_writer', ('wb.read', 'memo.write', 'memo.write_from_cells'), tokens=32768),
    'deck_designer': Role('deck_designer', ('wb.read', 'deck.add_slide', 'deck.table', 'deck.chart', 'deck.title', 'deck.render_preview')),
    'md_reviewer': Role('md_reviewer', ('pack.read', 'task.return')),
}


class InfraFault(Exception):
    """Transport/server fault (empty frame, connection loss): not a model capability signal."""


class ModelFault(ValueError):
    """Response arrived but is not a usable completion because of what the model generated (e.g. output cap hit)."""


class BudgetExhausted(Exception):
    """Pass wall-clock deadline reached while executing a model response."""


@dataclass(frozen=True)
class RepairPolicy:
    """Bounded model-visible repair of failed tool calls. Every repair is a NEW model call."""
    max_consecutive: int = 2
    max_total: int = 6

    def __post_init__(self):
        if not (type(self.max_consecutive) is int and type(self.max_total) is int
                and 1 <= self.max_consecutive <= 4 and self.max_consecutive <= self.max_total <= 16):
            raise ValueError('repair caps out of bounds')


DEFAULT_LIMITS = {'seconds': 120, 'calls': 6}
DIAGNOSTIC_LIMITS = {'seconds': 600, 'calls': 24}


@dataclass(frozen=True)
class Budget:
    seconds: float = 120
    calls: int = 6
    tokens: int = 8192
    output_tokens: int = 1024
    profile: str = 'default'      # 'diagnostic' is an explicit, labelled larger-limit profile
    call_seconds: float | None = None

    def __post_init__(self):
        limits = {'default': DEFAULT_LIMITS, 'diagnostic': DIAGNOSTIC_LIMITS}.get(self.profile)
        if (limits is None or not 0 < self.seconds <= limits['seconds'] or not 0 < self.calls <= limits['calls']
                or self.tokens <= 0 or type(self.output_tokens) is not int or not 512 <= self.output_tokens <= 4096
                or (self.call_seconds is not None and not 0 < self.call_seconds <= self.seconds)):
            raise ValueError('budget exceeds bounded local pass')


class AgentRuntime:
    def __init__(self, *, endpoint, model, transport, tools, directory, budget=Budget(), clock=time.monotonic, repair=None, after_tool=None):
        self.endpoint = getattr(transport, 'validate_endpoint', validate_endpoint)(endpoint)  # self-hosted transports bring their own private-route validator
        if not model or ':' in model and model.split(':', 1)[0].lower() in {'anthropic', 'claude', 'deepseek', 'openai'}:
            raise ValueError('explicit installed local model required')
        self.model, self.transport, self.tools = model, transport, dict(tools)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.budget, self.clock, self.repair = budget, clock, repair
        self.after_tool = after_tool
        self._allow_identical_request = False
        self.state = {'version': 'runtime/v1', 'calls': 0, 'tokens': 0, 'elapsed': 0, 'status': 'ready', 'tasks': {}, 'messages': [], 'role': None, 'tool_call_ids': [], 'receipts': []}
        self._init_repair_state()
        if (self.directory / 'checkpoint.json').exists():
            raise ValueError('existing run directory: use AgentRuntime.open to resume')
        self.state['binding'] = self._binding()
        self._save()

    @classmethod
    def open(cls, *, directory, **kwargs):
        state = json.loads((Path(directory) / 'checkpoint.json').read_text())
        instance = cls.__new__(cls)
        instance.endpoint = getattr(kwargs['transport'], 'validate_endpoint', validate_endpoint)(kwargs['endpoint'])
        instance.model = kwargs['model']
        instance.budget = kwargs.get('budget', Budget())
        instance.repair = kwargs.get('repair')
        instance.after_tool = kwargs.get('after_tool')
        instance._allow_identical_request = False
        instance.tools = dict(kwargs['tools'])
        binding = instance._binding()
        if state.get('binding') != binding or state['status'] == 'inflight':
            raise ValueError('changed binding or unresolved in-flight call')
        instance.transport, instance.tools = kwargs['transport'], dict(kwargs['tools'])
        instance.directory, instance.clock, instance.state = Path(directory), kwargs.get('clock', time.monotonic), state
        instance._init_repair_state()
        instance._verify_receipts()
        return instance

    def _binding(self):
        prompts = {name: (Path(__file__).parents[1] / 'roles' / f'{name}.md').read_text() for name in ROLES}
        contract = {'roles': {name: role.__dict__ for name, role in ROLES.items()},
                    'prompts': prompts, 'tools': {name: tool['schema'] for name, tool in self.tools.items()}}
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
        binding = {'endpoint': self.endpoint, 'model': self.model,
                   'budget': self.budget.__dict__, 'contract_sha256': digest}
        if getattr(self, 'repair', None) is not None:
            binding['repair'] = self.repair.__dict__
        return binding

    def _init_repair_state(self):
        for key, value in (('fault_class', None), ('faults', []), ('bad_turns_consecutive', 0), ('bad_turns_total', 0),
                           ('repair_calls', 0), ('failed_call_hashes', []), ('request_hashes', []),
                           ('infra_resumes', 0), ('tool_failures', [])):
            self.state.setdefault(key, value)

    def _verify_receipts(self):
        for record in self.state['receipts']:
            path = self.directory / record['file']
            if path.is_symlink() or not path.resolve().is_relative_to(self.directory.resolve()):
                raise ValueError('receipt path escapes private run')
            manifest = self.directory / (record['file'] + '.json')
            if manifest.is_symlink() or hashlib.sha256(manifest.read_bytes()).hexdigest() != record['manifest_sha256']:
                raise ValueError('receipt manifest tamper detected')
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('receipt tamper detected')

    def _receipt(self, phase, data, metadata):
        directory = self.directory / 'receipts'
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or not directory.resolve().is_relative_to(self.directory.resolve()):
            raise ValueError('receipt directory escapes private run')
        name = f"receipts/call-{self.state['calls']:04d}-{phase}.bin"
        path = self.directory / name
        with path.open('xb') as out:
            path.chmod(0o600)
            out.write(data)
            out.flush()
            import os
            os.fsync(out.fileno())
        record = {'file': name, 'sha256': hashlib.sha256(data).hexdigest(),
                  'bytes': len(data), 'phase': phase, 'call': self.state['calls'],
                  'binding': self.state['binding'], 'metadata': metadata,
                  'request_sha256': hashlib.sha256(data).hexdigest() if phase == 'request' else next(
                      item['sha256'] for item in self.state['receipts']
                      if item['call'] == self.state['calls'] and item['phase'] == 'request'),
                  'checkpoint_before_sha256': hashlib.sha256((self.directory / 'checkpoint.json').read_bytes()).hexdigest()}
        manifest_data = json.dumps(record, sort_keys=True).encode()
        manifest = self.directory / (name + '.json')
        with manifest.open('xb') as out:
            manifest.chmod(0o600)
            out.write(manifest_data)
            out.flush()
            import os
            os.fsync(out.fileno())
        record['manifest_sha256'] = hashlib.sha256(manifest_data).hexdigest()
        self.state['receipts'].append(record)
        self._event('raw_http_receipt', **record)
        self._save()

    def _save(self):
        target = self.directory / 'checkpoint.json'
        pending = self.directory / 'checkpoint.tmp'
        pending.write_text(json.dumps(self.state, indent=2))
        pending.chmod(0o600)
        pending.replace(target)

    def _event(self, kind, **data):
        with (self.directory / 'trajectory.jsonl').open('a') as out:
            out.write(json.dumps({'version': 'trajectory/v1', 'kind': kind, **data}) + '\n')
        (self.directory / 'trajectory.jsonl').chmod(0o600)

    def resume(self):
        state = json.loads((self.directory / 'checkpoint.json').read_text())
        if state.get('binding') != self.state.get('binding') or state['status'] == 'inflight':
            raise ValueError('changed binding or unresolved in-flight call: replay forbidden')
        self.state = state
        self._verify_receipts()

    # ---- fault classification -------------------------------------------------
    def _fault(self, fault_class, detail, **extra):
        self.state['fault_class'] = fault_class
        record = {'fault_class': fault_class, 'detail': detail, 'call': self.state['calls'], **extra}
        self.state['faults'].append(record)
        self._event('fault', **record)

    @staticmethod
    def _schema_snippet(schema, path):
        """Subschema at a '$.a[0].b' path, shortened, for instructive repair observations."""
        node = schema
        try:
            for part in re.findall(r'\.([A-Za-z_]\w*)|\[(\d+)\]', path):
                if part[0]:
                    node = node['properties'][part[0]]
                else:
                    node = node['items']
        except (KeyError, TypeError):
            node = schema
        text = json.dumps(node, sort_keys=True)
        return text if len(text) <= 500 else text[:497] + '...'

    def _error_observation(self, name, code, message, *, path='$', hint=None, attempt=None):
        schema = self.tools.get(name, {}).get('schema', {}).get('parameters', {}) if name in self.tools else {}
        error = {'code': code, 'message': message, 'path': path,
                 'expected_schema': self._schema_snippet(schema, path) if schema else None,
                 'hint': hint or REPAIR_HINT}
        result = {'repair': {'attempt': attempt, 'max_consecutive': self.repair.max_consecutive,
                             'note': 'This call had NO effect. Re-issue ONE corrected call; an identical call is refused.'}} if self.repair else {}
        return {'version': 'tools/v1', 'ok': False, 'tool': name, 'result': result, 'errors': [error]}

    def resume_after_infra_fault(self, role_name):
        """ONE labelled resume of the same session state after an infrastructure fault.

        Not a content retry: no model output was received, no message is added or changed.
        The identical request is allowed to be sent once; the event is logged as infra_resume.
        """
        if (self.state['status'] != 'failed' or self.state['fault_class'] != 'infra_fault'
                or self.state['infra_resumes'] >= 1):
            raise ValueError('resume permitted once, only after an infra fault')
        self.state['infra_resumes'] += 1
        self.state.update(status='paused', fault_class=None)
        self.state.pop('error', None)
        self._allow_identical_request = True
        self._event('infra_resume', label='infra resume of same session state; not a content retry',
                    resumes=self.state['infra_resumes'])
        self._save()
        return self.run(role_name, None, resume=True)

    # ---- run -------------------------------------------------------------------
    def run(self, role_name, mandate, *, resume=False):
        role = ROLES[role_name]
        if self.state['status'] not in {'ready', 'paused'}:
            raise ValueError('terminal runtime cannot be replayed')
        self.state.update(role=role_name, status='running')
        if not resume:
            prompt = (Path(__file__).parents[1] / 'roles' / f'{role.name}.md').read_text()
            self.state['messages'].extend([{'role': 'system', 'content': prompt}, {'role': 'user', 'content': mandate}])
        start = self.clock()
        prior = self.state['elapsed']
        phase = 'setup'
        call_started, call_timeout = None, None
        try:
            steps = role.steps if self.budget.profile == 'default' else self.budget.calls
            for _ in range(steps):
                remaining = self.budget.seconds - prior - (self.clock() - start)
                if remaining <= 0 or self.state['calls'] >= self.budget.calls or self.state['tokens'] >= min(role.tokens, self.budget.tokens):
                    self.state['status'] = 'budget_exhausted'
                    self._fault('budget_exhausted', 'pass limit reached before next call')
                    break
                schemas = [{'type': 'function', 'function': {**self.tools[name]['schema'], 'name': name}} for name in role.tools if name in self.tools]
                request = {'model': self.model, 'messages': self.state['messages'], 'tools': schemas, 'max_tokens': min(self.budget.output_tokens, self.budget.tokens - self.state['tokens'], role.tokens - self.state['tokens'])}
                digest = hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()
                if digest in self.state['request_hashes'] and not self._allow_identical_request:
                    raise ValueError('identical model request replay forbidden')
                self._allow_identical_request = False
                self.state['request_hashes'].append(digest)
                self.state['calls'] += 1
                self.state['status'] = 'inflight'
                call_started = prior + self.clock() - start   # elapsed-at-call-start (single clock read)
                self.state['elapsed'] = call_started
                self._save()
                is_repair = self.state['bad_turns_consecutive'] > 0
                if is_repair:
                    self.state['repair_calls'] += 1
                self._event('request', role=role_name, endpoint=self.endpoint, request=request, repair_call=is_repair)
                call_timeout = remaining if self.budget.call_seconds is None else min(remaining, self.budget.call_seconds)
                phase = 'transport'
                if getattr(self.transport, 'supports_receipts', False):
                    response = self.transport(endpoint=self.endpoint, request=request, timeout=call_timeout, receipt=self._receipt)
                else:
                    self._event('transport_provenance', raw_capture=False, kind_detail='injected_dict_transport')
                    response = self.transport(endpoint=self.endpoint, request=request, timeout=call_timeout)
                phase = 'response'
                self._event('response', response=response)
                if self.clock() - start + prior >= self.budget.seconds:
                    self.state['status'] = 'budget_exhausted'
                    self._fault('budget_exhausted', 'deadline reached during model call')
                    break
                if response.get('model') != self.model:
                    raise ValueError('returned model does not match request')
                choices = response.get('choices')
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ValueError('one terminal completion required')
                choice = choices[0]
                message = choice.get('message', {})
                if not isinstance(message, dict) or message.get('role') != 'assistant':
                    raise ValueError('assistant message required')
                calls = message.get('tool_calls', [])
                if not isinstance(calls, list) or len(calls) > 16:
                    raise ValueError('tool_calls must be a bounded list')
                for call in calls:
                    if (not isinstance(call, dict) or not isinstance(call.get('id'), str) or not call['id']
                            or call.get('type') != 'function' or not isinstance(call.get('function'), dict)
                            or not isinstance(call['function'].get('name'), str) or not call['function']['name']
                            or not isinstance(call['function'].get('arguments'), str)):
                        raise ValueError('invalid tool call envelope')
                terminal = 'tool_calls' if calls else 'stop'
                if choice.get('finish_reason') != terminal:
                    raise ValueError('missing or nonterminal finish reason')
                usage = response.get('usage', {}).get('total_tokens')
                if type(usage) is not int or usage < 0:
                    raise ValueError('missing token accounting')
                self.state['tokens'] += usage
                if self.state['tokens'] > min(role.tokens, self.budget.tokens):
                    self.state['status'] = 'budget_exhausted'
                    self._fault('budget_exhausted', 'token budget exceeded')
                    break
                message = response['choices'][0]['message']
                self.state['messages'].append(message)
                calls = message.get('tool_calls', [])
                if not calls:
                    if not isinstance(message.get('content'), str) or not message['content'].strip():
                        raise ValueError('nonempty literal final content required')
                    self.state['status'] = 'human_review_required'
                    break
                if len(calls) > 16:
                    raise ValueError('tool batch exceeds bound')
                batch_ids = [call.get('id') for call in calls]
                if (any(not isinstance(item, str) or not item for item in batch_ids)
                        or len(set(batch_ids)) != len(batch_ids)
                        or set(batch_ids).intersection(self.state['tool_call_ids'])):
                    raise ValueError('duplicate or invalid tool call id: replay forbidden')
                phase = 'tools'
                bad_turn = False
                for position, call in enumerate(calls):
                    if prior + self.clock() - start >= self.budget.seconds:
                        raise BudgetExhausted('tool deadline exhausted')
                    name = call['function']['name']
                    problem = None
                    arguments = None
                    if name not in role.tools or name not in self.tools:
                        problem = ('ToolNotAllowed', f'tool {name!r} is not available to this role; available: {sorted(n for n in role.tools if n in self.tools)}', '$')
                    else:
                        def unique_arguments(pairs):
                            result = {}
                            for key, value in pairs:
                                if key in result: raise ValueError('duplicate tool argument key')
                                result[key] = value
                            return result
                        def reject_constant(value): raise ValueError('nonfinite tool argument')
                        try:
                            arguments = json.loads(call['function']['arguments'], object_pairs_hook=unique_arguments,
                                                   parse_constant=reject_constant)
                        except ValueError as exc:
                            problem = ('ArgumentParseError', f'arguments are not valid JSON: {exc}', '$')
                        if problem is None and not isinstance(arguments, dict):
                            problem = ('ArgumentParseError', 'tool arguments must be a JSON object', '$')
                        validator = self.tools[name].get('validate')
                        if problem is None and not callable(validator):
                            raise ValueError('tool registry argument validator required')
                        if problem is None and self.repair is not None and hashlib.sha256(
                                json.dumps([name, arguments], sort_keys=True).encode()).hexdigest() in self.state['failed_call_hashes']:
                            problem = ('IdenticalFailedCall', 'this exact call (same tool and arguments) already failed validation; it was not executed', '$')
                        if problem is None:
                            try:
                                validator(arguments)
                            except ValueError as exc:
                                text = str(exc)
                                path = text.split(':', 1)[0] if text.startswith('$') else '$'
                                problem = ('ArgumentValidationError', text, path)
                    if problem is not None and self.repair is None:
                        # Legacy fail-closed behavior: no model-visible repair.
                        if problem[0] == 'ToolNotAllowed': raise ValueError('tool outside role allowlist')
                        if problem[0] == 'ArgumentParseError' and arguments is None:
                            json.loads(call['function']['arguments'], object_pairs_hook=unique_arguments, parse_constant=reject_constant)
                        raise ValueError(problem[1])
                    self.state['tool_call_ids'].append(call['id'])
                    if problem is not None:
                        bad_turn = True
                        if problem[0] == 'ArgumentValidationError' and arguments is not None:
                            self.state['failed_call_hashes'].append(hashlib.sha256(json.dumps([name, arguments], sort_keys=True).encode()).hexdigest())
                        observation = self._error_observation(name, problem[0], problem[1], path=problem[2],
                                                              attempt=self.state['bad_turns_consecutive'] + 1)
                        record = {'call_id': call['id'], 'tool': name, 'code': problem[0], 'message': problem[1][:300], 'path': problem[2]}
                        self.state['tool_failures'].append(record)
                        self._event('tool_failure', raw_arguments=call['function']['arguments'], pre_effect=True, **record)
                        self.state['messages'].append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(observation)})
                        # Ordered batch: later calls may depend on this one, so they are not executed.
                        for later in calls[position + 1:]:
                            self.state['tool_call_ids'].append(later['id'])
                            skipped = {'version': 'tools/v1', 'ok': False, 'tool': later['function']['name'], 'result': {},
                                       'errors': [{'code': 'SkippedAfterFailure', 'message': 'not executed because an earlier call in this batch failed; re-issue after fixing it', 'path': '$', 'expected_schema': None, 'hint': REPAIR_HINT}]}
                            self._event('tool_skipped', call_id=later['id'], tool=later['function']['name'])
                            self.state['messages'].append({'role': 'tool', 'tool_call_id': later['id'], 'content': json.dumps(skipped)})
                        break
                    # Persist the reservation before any side effect. A crash remains inflight.
                    self._save()
                    self._event('tool_intent', tool=name, arguments=arguments, call_id=call['id'])
                    observation = self.tools[name]['call'](**arguments)
                    if (observation.get('version') != 'tools/v1' or observation.get('tool') != name
                            or type(observation.get('ok')) is not bool or not isinstance(observation.get('result'), dict)
                            or not isinstance(observation.get('errors'), list)):
                        raise ValueError('invalid tools/v1 observation')
                    self._event('tool_observation', observation=observation, call_id=call['id'])
                    if self.after_tool is not None:
                        self.after_tool(name, observation)   # host-side state hook (e.g. reload workbook after a failed mutation)
                    if not observation['ok']:
                        bad_turn = True
                        self.state['tool_failures'].append({'call_id': call['id'], 'tool': name, 'code': 'ToolReturnedError',
                                                            'message': json.dumps(observation['errors'])[:300], 'path': '$'})
                    self.state['messages'].append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(observation)})
                if self.repair is not None:
                    if bad_turn:
                        self.state['bad_turns_consecutive'] += 1
                        self.state['bad_turns_total'] += 1
                        if (self.state['bad_turns_consecutive'] > self.repair.max_consecutive
                                or self.state['bad_turns_total'] > self.repair.max_total):
                            self.state['status'] = 'repair_cap_reached'
                            self._fault('model_error', 'repair cap reached: model did not produce a valid corrected call',
                                        consecutive=self.state['bad_turns_consecutive'], total=self.state['bad_turns_total'])
                            break
                    else:
                        self.state['bad_turns_consecutive'] = 0
                self.state['status'] = 'running'
                self._save()
                phase = 'between'
            else:
                self.state['status'] = 'budget_exhausted'
                self._fault('budget_exhausted', 'step limit reached')
        except Exception as exc:
            self.state['status'] = 'failed'
            self.state['error'] = str(exc)
            spent = prior + self.clock() - start
            deadline_hit = (spent >= self.budget.seconds - 0.5
                            or (call_started is not None and spent - call_started >= call_timeout - 0.5))
            if isinstance(exc, BudgetExhausted) or (phase == 'transport' and isinstance(exc, TimeoutError) and deadline_hit):
                self.state['status'] = 'budget_exhausted'
                self._fault('budget_exhausted', str(exc))
            elif phase == 'transport' and isinstance(exc, (InfraFault, OSError)):
                self._fault('infra_fault', f'{type(exc).__name__}: {exc}')
            elif isinstance(exc, ModelFault) or (phase in {'response', 'tools'} and isinstance(exc, ValueError)):
                self._fault('model_error', f'{type(exc).__name__}: {exc}')
            else:
                self._fault('harness_error', f'{type(exc).__name__}: {exc}')
            self._event('failure', error=str(exc), fault_class=self.state['fault_class'])
        finally:
            self.state['elapsed'] = prior + self.clock() - start
            self._save()
        return self.state
