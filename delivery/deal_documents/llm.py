"""Recorded local Ollama calls with JSON-schema output.

Every request and raw response is written to the run directory before it is
parsed, so failed or rejected answers remain inspectable. Responses stream so a
degenerate repetition loop is stopped early instead of running to the token
cap; for single-array schemas the complete items produced before the loop are
salvaged and the salvage is recorded. Loopback only.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import ollama

from agents.inference.model_routing import validate_local_model_name

OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')
DEFAULT_MODEL = os.environ.get('DEAL_DOCUMENTS_MODEL', 'qwen3:30b-a3b')
# Seconds without a streamed chunk before a call fails. A dense model run mostly on CPU reads a 26k-token
# prompt for tens of minutes before its first chunk, so the wait is configurable.
CALL_TIMEOUT = float(os.environ.get('DEAL_DOCUMENTS_CALL_TIMEOUT', '900'))
# Layers to place on the GPU. Ollama's automatic fit reserves room for the unused vision projector and a wide
# margin (3 of 66 layers for a dense 27B on a 6 GB card); 14 measured 15% faster with identical weights.
NUM_GPU = os.environ.get('DEAL_DOCUMENTS_NUM_GPU')
# Ollama servers per profile, for example 'write=http://127.0.0.1:11435|http://127.0.0.1:11436,review=http://127.0.0.1:11436'.
# Remote GPU servers are reached through SSH tunnels, so every listed address must be loopback. Unlisted profiles use OLLAMA_HOST.
ROUTES = os.environ.get('DEAL_DOCUMENTS_ROUTES', '')
# A separate model for the checking agents, so a writer is not marked by its own weights. It is also far faster.
REVIEW_MODEL = os.environ.get('DEAL_DOCUMENTS_REVIEW_MODEL', '')
REVIEW_PROFILES = {'check', 'score', 'ask', 'review'}
LOOPBACK = ('http://127.0.0.1:', 'http://localhost:')
# A model server that fails mid-call (a driver reset, a lost host) is retried here, so a hardware fault costs one
# call and not the step. After a GPU fault the rest of the run puts fewer layers on the card, down to MIN_GPU_LAYERS.
CALL_RETRIES = int(os.environ.get('DEAL_DOCUMENTS_CALL_RETRIES', '3'))
RETRY_WAIT = float(os.environ.get('DEAL_DOCUMENTS_RETRY_WAIT', '30'))
MIN_GPU_LAYERS = 6


def parse_routes(text: str) -> dict[str, list[str]]:
    routes = {}
    for entry in filter(None, (part.strip() for part in text.split(','))):
        profile, _, hosts = entry.partition('=')
        if profile.strip() not in PROFILES or not hosts:
            raise ValueError(f'DEAL_DOCUMENTS_ROUTES: unknown profile or empty host list in {entry!r}')
        routes[profile.strip()] = [host.strip().rstrip('/') for host in hosts.split('|') if host.strip()]
    for host in [OLLAMA_HOST.rstrip('/'), *(host for hosts in routes.values() for host in hosts)]:
        if not host.startswith(LOOPBACK):
            raise ValueError(f'model server {host} is not loopback; reach remote servers through an SSH tunnel')
    return routes

# Qwen3 guidance: non-thinking 0.7/0.8/20, thinking 0.6/0.95/20. Extraction runs
# cooler to keep literals exact but not at 0.1, which looped on noisy OCR.
PROFILES = {
    'extract': {'think': False, 'options': {'temperature': 0.2, 'top_p': 0.8, 'top_k': 20, 'num_ctx': 16384, 'num_predict': 4000}},
    'analyse': {'think': True, 'thinking_chars': 12000,
                'options': {'temperature': 0.6, 'top_p': 0.95, 'top_k': 20, 'num_ctx': 40960, 'num_predict': 8000}},
    'write': {'think': False, 'options': {'temperature': 0.4, 'top_p': 0.8, 'top_k': 20, 'num_ctx': 40960, 'num_predict': 5000,
                                          'presence_penalty': 0.5}},
    'review': {'think': True, 'thinking_chars': 8000,
               'options': {'temperature': 0.6, 'top_p': 0.95, 'top_k': 20, 'num_ctx': 40960, 'num_predict': 8000}},
    # Claim-by-claim checking of one section against its cited facts. Every fact-check call
    # ran to the 12k-character thinking cap (about 4.5 minutes each) before this profile;
    # code now supplies each calculation's meaning, so the check needs no long reasoning.
    # The same context size as writing: a different num_ctx makes Ollama reload the model between steps.
    'check': {'think': False, 'options': {'temperature': 0.2, 'top_p': 0.8, 'top_k': 20, 'num_ctx': 40960, 'num_predict': 2500}},
    # Questions come before any writing, so they must take minutes: the fast reviewer, without long reasoning.
    'ask': {'think': False, 'options': {'temperature': 0.2, 'top_p': 0.8, 'top_k': 20, 'num_ctx': 40960, 'num_predict': 3000}},
    'score': {'think': False, 'options': {'temperature': 0.2, 'top_p': 0.8, 'top_k': 20, 'num_ctx': 40960, 'num_predict': 600}},
}
FINALISE_NOTE = ('\n\nYOUR PRELIMINARY ANALYSIS (reasoning budget reached; use it, do not restart the analysis):\n{thinking}\n\n'
                 'Now give the final answer in the required JSON format.')


class ModelResponseError(RuntimeError):
    pass


def repeating(text: str, window: int = 160, repeats: int = 4) -> bool:
    """True when the latest `window` characters already occur `repeats` times in the recent tail."""
    if len(text) < window * repeats:
        return False
    tail = text[-window * repeats * 3:]
    return tail.count(text[-window:]) >= repeats


def salvage_array(content: str, schema: dict) -> str | None:
    """Close a truncated JSON response after its last complete object.

    Cuts after the most recent '}' that closes an array element and appends
    the closers for every structure still open at that point. The result must
    still satisfy the caller's validation; nothing is invented.
    """
    stack, in_string, escape, best = [], False, False, None
    for position, char in enumerate(content):
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack:
                return None
            stack.pop()
            if char == '}' and stack and stack[-1] == '[':
                best = (position, list(stack))
    if best is None:
        return None
    position, open_structures = best
    closers = ''.join(']' if opener == '[' else '}' for opener in reversed(open_structures))
    candidate = content[:position + 1] + closers
    try:
        json.loads(candidate)
    except ValueError:
        return None
    return candidate


class RecordedModel:
    def __init__(self, run_dir: Path, model: str = DEFAULT_MODEL, timeout: float = CALL_TIMEOUT):
        self.model = validate_local_model_name(model)
        self.review_model = validate_local_model_name(REVIEW_MODEL) if REVIEW_MODEL else self.model
        self.calls_dir = Path(run_dir) / 'calls'
        self.calls_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.routes = parse_routes(ROUTES)
        hosts = {OLLAMA_HOST.rstrip('/'), *(host for hosts in self.routes.values() for host in hosts)}
        self.clients = {host: ollama.Client(host=host, timeout=timeout) for host in hosts}
        self.busy = dict.fromkeys(hosts, 0)
        self.last = threading.local()  # a repair extends its revision's prompt, so it stays on that server's cache
        self.count = len(list(self.calls_dir.glob('*.json')))
        self.lock = threading.Lock()  # calls may come from several pipeline threads
        self.gpu_layers = int(NUM_GPU) if NUM_GPU else None

    def _acquire(self, profile: str) -> str:
        candidates = self.routes.get(profile) or [OLLAMA_HOST.rstrip('/')]
        with self.lock:
            previous = getattr(self.last, 'host', None)
            host = previous if previous in candidates and not self.busy[previous] else \
                min(candidates, key=lambda candidate: self.busy[candidate])
            self.busy[host] += 1
        self.last.host = host
        return host

    def _release(self, host: str):
        with self.lock:
            self.busy[host] -= 1

    def json(self, name: str, profile: str, system: str, user: str, schema: dict, images: list[Path] = (),
             settings: dict | None = None, meta: dict | None = None, attempt: int = 0) -> dict:
        """`meta` is saved in the call record, for example the short-id map a prompt was written with."""
        settings = settings or PROFILES[profile]
        model_name = self.review_model if profile in REVIEW_PROFILES else self.model
        if self.gpu_layers and model_name == self.model:
            settings = {**settings, 'options': {**settings['options'], 'num_gpu': self.gpu_layers}}
        user_message = {'role': 'user', 'content': user}
        image_hashes = []
        if images:
            payload = [Path(image).read_bytes() for image in images]
            image_hashes = [hashlib.sha256(data).hexdigest() for data in payload]
            user_message['images'] = payload
        messages = [{'role': 'system', 'content': system}, user_message]
        recorded = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user, 'image_sha256': image_hashes}]
        with self.lock:
            self.count += 1
            record_path = self.calls_dir / f'{self.count:04d}-{name}.json'
        record = {'model': model_name, 'profile': profile, 'settings': settings, 'schema': schema,
                  'messages': recorded, 'request_sha256': hashlib.sha256(
                      json.dumps([model_name, settings, schema, recorded], sort_keys=True).encode()).hexdigest(),
                  **(meta or {})}
        host = self._acquire(profile)
        record['host'] = host
        started = time.monotonic()
        content, thinking, final = [], [], {}
        done_reason = None
        try:
            stream = self.clients[host].chat(model=model_name, messages=messages, format=schema, stream=True,
                                      think=settings['think'], options=settings['options'])
            for chunk in stream:
                message = chunk.get('message') or {}
                content.append(message.get('content') or '')
                thinking.append(message.get('thinking') or '')
                if chunk.get('done'):
                    final, done_reason = chunk, chunk.get('done_reason')
                    break
                if len(content) % 40 == 0 and (repeating(''.join(content)) or repeating(''.join(thinking))):
                    done_reason = 'repetition'
                    stream.close() if hasattr(stream, 'close') else None
                    break
                if settings.get('thinking_chars') and not ''.join(content).strip() and \
                        sum(map(len, thinking)) > settings['thinking_chars']:
                    done_reason = 'thinking_budget'
                    stream.close() if hasattr(stream, 'close') else None
                    break
        except Exception as exc:
            record.update(error=f'{type(exc).__name__}: {exc}', seconds=round(time.monotonic() - started, 2),
                          content=''.join(content), thinking=''.join(thinking))
            _write(record_path, record)
            failure = exc
        else:
            failure = None
        finally:
            self._release(host)
        if failure is not None:
            if attempt >= CALL_RETRIES:
                raise ModelResponseError(record['error']) from failure
            if 'CUDA' in record['error'] and self.gpu_layers:
                self.gpu_layers = max(MIN_GPU_LAYERS, self.gpu_layers // 2)
            time.sleep(RETRY_WAIT * (attempt + 1))
            return self.json(name, profile, system, user, schema, images, settings=settings, meta=meta, attempt=attempt + 1)
        text = ''.join(content)
        record.update(seconds=round(time.monotonic() - started, 2), content=text, thinking=''.join(thinking),
                      done_reason=done_reason, prompt_tokens=final.get('prompt_eval_count'), output_tokens=final.get('eval_count'),
                      prefill_seconds=round((final.get('prompt_eval_duration') or 0) / 1e9, 2),
                      decode_seconds=round((final.get('eval_duration') or 0) / 1e9, 2))
        if done_reason == 'thinking_budget':
            # Budget forcing: one bounded non-thinking request that finishes from the recorded partial reasoning.
            _write(record_path, record)
            finish = {key: value for key, value in settings.items() if key != 'thinking_chars'}
            finish['think'] = False
            note = FINALISE_NOTE.format(thinking=''.join(thinking)[-settings['thinking_chars']:])
            return self.json(f'{name}-finish', profile, system, user + note, schema, images, settings=finish, meta=meta)
        if done_reason != 'stop':
            salvaged = salvage_array(text, schema)
            record['salvaged'] = salvaged is not None
            _write(record_path, record)
            if salvaged is None:
                raise ModelResponseError(f'{name}: generation ended with {done_reason}')
            data = json.loads(salvaged)
            missing = [key for key in schema.get('required', []) if key not in data]
            if missing:
                raise ModelResponseError(f'{name}: generation ended with {done_reason}; salvage lacks {missing}')
            return data
        _write(record_path, record)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ModelResponseError(f'{name}: response is not valid JSON') from exc


def _write(path: Path, record: dict):
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    os.chmod(path, 0o600)
