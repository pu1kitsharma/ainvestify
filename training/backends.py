"""Trainer / generator backends for the real expert-iteration round.

MLX LoRA runs `python -m mlx_lm lora` in a *separate* interpreter (the MLX venv),
so the repository venv never imports MLX. The CUDA QLoRA backend shells out to
training/qlora_train.py, which needs PEFT/TRL/torch on a GPU host.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib import request as urlrequest
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}
HOSTED_BLOCKLIST = ('openai.com', 'anthropic.com', 'googleapis.com', 'azure.com', 'cohere.com',
                    'mistral.ai', 'together.xyz', 'groq.com', 'openrouter.ai', 'fireworks.ai')

MLX_HYPER_DEFAULTS = {'iters': 30, 'batch_size': 1, 'num_layers': 4, 'learning_rate': 1e-4,
                      'max_seq_length': 1024, 'rank': 8, 'scale': 20.0, 'dropout': 0.0, 'seed': 0,
                      'grad_checkpoint': True, 'mask_prompt': True}


def check_endpoint(base_url, allow_remote=False):
    """Samplers talk to a local or operator-owned OpenAI-compatible server only."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('http', 'https') or not host:
        raise ValueError('Endpoint must be an http(s) URL')
    if any(host == h or host.endswith('.' + h) for h in HOSTED_BLOCKLIST):
        raise ValueError('Hosted model APIs are not allowed')
    if host not in LOOPBACK and not allow_remote:
        raise ValueError('Non-loopback endpoint requires allow_remote=True (operator-owned vLLM host)')
    return base_url.rstrip('/')


class ChatEndpointSampler:
    """POST {base_url}/chat/completions (Ollama /v1, mlx_lm.server, vLLM)."""

    def __init__(self, base_url, model, *, api_key=None, temperature=0.8, max_tokens=256, timeout=180,
                 allow_remote=False, post=None):
        self.base_url = check_endpoint(base_url, allow_remote)
        self.model, self.api_key = model, api_key
        self.temperature, self.max_tokens, self.timeout = temperature, max_tokens, timeout
        self._post = post or self._http_post

    def _http_post(self, url, payload):
        data = json.dumps(payload).encode()
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        req = urlrequest.Request(url, data=data, headers=headers, method='POST')
        with urlrequest.urlopen(req, timeout=self.timeout) as response:  # noqa: S310 (checked above)
            return json.loads(response.read().decode())

    def __call__(self, messages):
        body = self._post(self.base_url + '/chat/completions', {
            'model': self.model, 'messages': messages, 'temperature': self.temperature,
            'max_tokens': self.max_tokens, 'stream': False})
        try:
            return body['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError('Endpoint response lacks choices[0].message.content') from exc


def _yaml_config(h):
    return ('lora_parameters:\n  rank: %d\n  scale: %s\n  dropout: %s\n' % (h['rank'], h['scale'], h['dropout']))


class MlxLoraBackend:
    name = 'mlx_lora'

    def __init__(self, python, runner=None):
        self.python = str(python)
        self._run = runner or subprocess.run

    def version(self):
        out = self._run([self.python, '-c', 'import mlx_lm; print(mlx_lm.__version__)'],
                        capture_output=True, text=True, timeout=120)
        return out.stdout.strip() if out.returncode == 0 else 'unknown'

    def train_command(self, base_model, data_dir, adapter_dir, hyper, config_path):
        h = {**MLX_HYPER_DEFAULTS, **hyper}
        cmd = [self.python, '-m', 'mlx_lm', 'lora', '--model', str(base_model), '--train',
               '--data', str(data_dir), '--adapter-path', str(adapter_dir), '--iters', str(h['iters']),
               '--batch-size', str(h['batch_size']), '--num-layers', str(h['num_layers']),
               '--learning-rate', str(h['learning_rate']), '--max-seq-length', str(h['max_seq_length']),
               '--seed', str(h['seed']), '--steps-per-report', '5', '--steps-per-eval', str(max(5, h['iters'])),
               '--save-every', str(h['iters']), '-c', str(config_path)]
        if h['grad_checkpoint']:
            cmd.append('--grad-checkpoint')
        if h['mask_prompt']:
            cmd.append('--mask-prompt')
        return cmd, h

    def train(self, base_model, data_dir, adapter_dir, hyper, log_path):
        config = Path(data_dir) / 'mlx_lora.yaml'
        h = {**MLX_HYPER_DEFAULTS, **hyper}
        config.write_text(_yaml_config(h))
        cmd, h = self.train_command(base_model, data_dir, adapter_dir, hyper, config)
        started = time.time()
        with open(log_path, 'w') as log:
            proc = self._run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
        seconds = time.time() - started
        if proc.returncode != 0:
            raise RuntimeError('mlx_lm lora failed (see %s)' % log_path)
        adapter_file = Path(adapter_dir) / 'adapters.safetensors'
        if not adapter_file.is_file():
            raise RuntimeError('mlx_lm lora finished without adapters.safetensors')
        return {'backend': self.name, 'command': cmd, 'hyper': h, 'seconds': round(seconds, 2),
                'mlx_lm_version': self.version(), 'adapter_file': adapter_file.name}

    def generator(self, base_model, adapter_dir=None, *, max_tokens=256, temperature=0.0, seed=0):
        """Return fn(list_of_prompts) -> list[str]; prompt = messages list or {'raw': text}."""
        def generate(prompts):
            items = [p if isinstance(p, dict) and 'raw' in p else {'messages': p} for p in prompts]
            with tempfile.TemporaryDirectory() as tmp:
                req, res = Path(tmp) / 'req.json', Path(tmp) / 'res.json'
                req.write_text(json.dumps({'model': str(base_model), 'adapter': str(adapter_dir) if adapter_dir else None,
                                           'prompts': items, 'max_tokens': max_tokens,
                                           'temperature': temperature, 'seed': seed}))
                proc = self._run([self.python, str(HERE / 'mlx_infer.py'), str(req), str(res)],
                                 capture_output=True, text=True, timeout=3600)
                if proc.returncode != 0:
                    raise RuntimeError('mlx generation failed: ' + (proc.stderr or '')[-400:])
                return json.loads(res.read_text())['outputs']
        return generate


class QloraBackend:
    """Shells to training/qlora_train.py on a CUDA host (python with torch/peft/trl)."""
    name = 'cuda_qlora'

    def __init__(self, python=None, runner=None, extra_args=()):
        self.python = python or sys.executable
        self.extra_args = list(extra_args)
        self._run = runner or subprocess.run

    def train_command(self, base_model, data_dir, adapter_dir, hyper, role, private):
        cmd = [self.python, str(HERE / 'qlora_train.py'), '--base-model', str(base_model),
               '--data-dir', str(data_dir), '--output-dir', str(adapter_dir), '--role', role]
        for key, flag in (('lora_r', '--lora-r'), ('lora_alpha', '--lora-alpha'), ('epochs', '--epochs'),
                          ('learning_rate', '--learning-rate'), ('max_seq_length', '--max-seq-length'),
                          ('batch_size', '--batch-size'), ('grad_accum', '--grad-accum'), ('seed', '--seed')):
            if key in hyper:
                cmd += [flag, str(hyper[key])]
        if private:
            cmd.append('--private')
        return cmd + self.extra_args

    def train(self, base_model, data_dir, adapter_dir, hyper, log_path, role='author', private=False):
        cmd = self.train_command(base_model, data_dir, adapter_dir, hyper, role, private)
        started = time.time()
        with open(log_path, 'w') as log:
            proc = self._run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0:
            raise RuntimeError('qlora_train failed (see %s)' % log_path)
        return {'backend': self.name, 'command': cmd, 'hyper': hyper, 'seconds': round(time.time() - started, 2)}
