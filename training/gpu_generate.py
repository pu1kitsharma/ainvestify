"""Batch generators `fn(prompts) -> texts` for held-out evaluation and the memorisation probe on a GPU host.

Same call shape as `MlxLoraBackend.generator`: a prompt is a chat `messages` list or `{'raw': text}`.
Two backends, selected by the caller:

  * vLLM through the private self-hosted route (`SelfHostedClient`): the base model is the served
    name; an adapter is selected by *model name* (vLLM `--lora-modules name=path`, or runtime loading).
    Requests run concurrently (vLLM batches them) and results keep input order.
  * Local PEFT/transformers (`PeftGenerator`) when torch is importable. Imports are lazy, so this
    module imports cleanly on machines without torch (including the macOS dev box).

Nothing here changes `real_training.run_round` or `memorisation_probe.run_probe`; plug in via their
injected callables:

    make_generator = make_generator_factory(client, base_name='banker-base', adapter_names={...})
    run_round(..., make_generator=make_generator, probe_hook=make_probe_hook(make_generator, facts))
"""
from __future__ import annotations

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _is_raw(prompt):
    return isinstance(prompt, dict) and 'raw' in prompt


def adapter_model_name(adapter_dir, prefix='adapter'):
    """Deterministic vLLM LoRA name for an adapter directory (used when no explicit name is given)."""
    return '%s-%s' % (prefix, hashlib.sha256(str(Path(adapter_dir).resolve()).encode()).hexdigest()[:10])


def vllm_generator(client, *, max_tokens=256, temperature=0.0, workers=8, timeout=300, receipt=None):
    """fn(prompts)->list[str] against one served model name (base or LoRA adapter) of a vLLM server."""
    if type(max_tokens) is not int or max_tokens <= 0 or not 1 <= workers <= 64:
        raise ValueError('max_tokens must be positive and workers within 1..64')

    def one(prompt):
        if _is_raw(prompt):
            return client.raw_completion(prompt['raw'], max_tokens=max_tokens, temperature=temperature,
                                         timeout=timeout, receipt=receipt)
        if not isinstance(prompt, list):
            raise ValueError('prompt must be a messages list or {"raw": text}')
        return client.chat(prompt, max_tokens=max_tokens, temperature=temperature, timeout=timeout,
                           receipt=receipt, allow_length=True)

    def generate(prompts):
        prompts = list(prompts)
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(prompts)))) as pool:
            return list(pool.map(one, prompts))   # map preserves order and re-raises the first failure
    return generate


class PeftGenerator:
    """Local transformers (+ optional PEFT adapter) greedy generation. Needs torch; loads lazily on first use."""

    def __init__(self, base_model, adapter_dir=None, *, max_tokens=256, temperature=0.0, seed=0, load_in_4bit=False,
                 batch_size=4, importer=None):
        self.base_model, self.adapter_dir = str(base_model), str(adapter_dir) if adapter_dir else None
        self.max_tokens, self.temperature, self.seed = max_tokens, temperature, seed
        self.load_in_4bit, self.batch_size = load_in_4bit, batch_size
        self._import = importer or __import__
        self._model = self._tok = self._torch = None

    @staticmethod
    def available():
        import importlib.util
        return all(importlib.util.find_spec(n) is not None for n in ('torch', 'transformers', 'peft'))

    def _load(self):
        if self._model is not None:
            return
        torch = self._import('torch')
        transformers = self._import('transformers')
        kwargs = {'torch_dtype': torch.bfloat16, 'device_map': 'auto'}
        if self.load_in_4bit:
            kwargs['quantization_config'] = transformers.BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.bfloat16)
        tok = transformers.AutoTokenizer.from_pretrained(self.base_model)
        tok.padding_side = 'left'
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        model = transformers.AutoModelForCausalLM.from_pretrained(self.base_model, **kwargs)
        if self.adapter_dir:
            peft = self._import('peft')
            model = peft.PeftModel.from_pretrained(model, self.adapter_dir)
        model.eval()
        self._torch, self._tok, self._model = torch, tok, model

    def __call__(self, prompts):
        self._load()
        torch, tok, model = self._torch, self._tok, self._model
        torch.manual_seed(self.seed)
        texts = [p['raw'] if _is_raw(p) else tok.apply_chat_template(p, tokenize=False, add_generation_prompt=True)
                 for p in prompts]
        outputs = []
        for start in range(0, len(texts), self.batch_size):
            batch = tok(texts[start:start + self.batch_size], return_tensors='pt', padding=True).to(model.device)
            sample = self.temperature > 0
            with torch.no_grad():
                out = model.generate(**batch, max_new_tokens=self.max_tokens, do_sample=sample,
                                     **({'temperature': self.temperature} if sample else {}), pad_token_id=tok.pad_token_id)
            width = batch['input_ids'].shape[1]
            outputs += tok.batch_decode(out[:, width:], skip_special_tokens=True)
        return outputs


def make_generator_factory(client=None, *, base_name=None, adapter_names=None, auto_load_adapters=False, adapter_subdir=None,
                           backend='vllm', max_tokens=256, temperature=0.0, workers=8, load_in_4bit=False):
    """Return make_generator(base_dir, adapter_dir_or_None) for `run_round`.

    backend='vllm': `client` is a SelfHostedClient; `base_name` is the served base model name;
      `adapter_names` maps str(adapter_dir) -> served LoRA name (else a deterministic name is derived;
      with auto_load_adapters=True it is registered via /v1/load_lora_adapter using the directory path,
      which must be visible to the server).
    adapter_subdir: qlora_train.py writes weights to <adapter_dir>/<role>/; pass the role so that directory is used.
    backend='peft': local transformers/PEFT using base_dir directly (import errors surface at first call).
    """
    if backend not in ('vllm', 'peft'):
        raise ValueError('backend must be vllm or peft')
    if backend == 'vllm' and (client is None or not base_name):
        raise ValueError('vllm backend needs a SelfHostedClient and the served base model name')
    names = dict(adapter_names or {})
    loaded = set()

    def make_generator(base_dir, adapter_dir=None):
        if adapter_dir is not None and adapter_subdir and (Path(adapter_dir) / adapter_subdir).is_dir():
            adapter_dir = Path(adapter_dir) / adapter_subdir
        if backend == 'peft':
            return PeftGenerator(base_dir, adapter_dir, max_tokens=max_tokens, temperature=temperature, load_in_4bit=load_in_4bit)
        if adapter_dir is None:
            model = base_name
        else:
            key = str(adapter_dir)
            model = names.get(key) or adapter_model_name(adapter_dir)
            if auto_load_adapters and model not in loaded:
                client.load_lora_adapter(model, Path(adapter_dir).resolve())
                loaded.add(model)
        return vllm_generator(client.with_model(model), max_tokens=max_tokens, temperature=temperature, workers=workers)
    return make_generator


def make_probe_hook(make_generator, facts, *, base_dir=None, gate=None):
    """probe_hook(adapter_dir) for `run_round`. Build `make_generator` with a short max_tokens
    (e.g. 24) for the probe; held-out evaluation uses its own, longer-token factory."""
    from training.memorisation_probe import run_probe

    def hook(adapter_dir):
        report = run_probe(facts, make_generator(base_dir, None), make_generator(base_dir, adapter_dir), gate=gate)
        return {k: report[k] for k in ('facts', 'base_rate', 'adapter_rate', 'excess_over_base', 'passed', 'gate')}
    return hook


def sampler_from_client(client, *, temperature=0.8, max_tokens=256, timeout=300):
    """`sampler(messages)->text` for `sample_and_score` over the private vLLM route (no hosted APIs)."""
    def sampler(messages):
        return client.chat(messages, max_tokens=max_tokens, temperature=temperature, timeout=timeout, allow_length=True)
    return sampler


class ServingPausedBackend:
    """Wrap a trainer backend so vLLM releases the GPU during training, then comes back.

    `run_round` samples (vLLM up), trains (needs the GPU memory vLLM is holding), then evaluates (vLLM up
    again). Commands are argv lists run WITHOUT a shell, e.g. ['sudo','systemctl','stop','vllm'].
    """

    def __init__(self, inner, *, stop_cmd, start_cmd, ready, runner=None, wait_seconds=600, sleep=None, clock=None):
        import subprocess
        import time
        if not (isinstance(stop_cmd, list) and isinstance(start_cmd, list) and stop_cmd and start_cmd):
            raise ValueError('stop/start commands must be non-empty argv lists')
        self.inner, self.name = inner, inner.name
        self.stop_cmd, self.start_cmd, self.ready = stop_cmd, start_cmd, ready
        self._run = runner or (lambda cmd: subprocess.run(cmd, check=True, timeout=300))
        self.wait_seconds = wait_seconds
        self._sleep, self._clock = sleep or time.sleep, clock or time.monotonic

    def _wait_ready(self):
        deadline = self._clock() + self.wait_seconds
        while True:
            try:
                if self.ready():
                    return
            except Exception:
                pass
            if self._clock() >= deadline:
                raise RuntimeError('vLLM did not become ready after training; adapter evaluation cannot proceed')
            self._sleep(5)

    def train(self, *args, **kwargs):
        self._run(self.stop_cmd)
        try:
            return self.inner.train(*args, **kwargs)
        finally:
            self._run(self.start_cmd)
            self._wait_ready()


def _client_from_env(model):
    from agents.inference.endpoint_policy import resolve_selfhosted_route, selfhosted_allowed_hosts
    from agents.inference.selfhosted_client import SelfHostedClient
    route = resolve_selfhosted_route('selfhosted:' + model)          # SELFHOSTED_BASE_URL + token from env/file
    return SelfHostedClient(route, allowed_hosts=sorted(selfhosted_allowed_hosts()))


def cmd_probe(a):
    from training.expert_iteration import _write_new
    from training.memorisation_probe import DEFAULT_GATE, run_probe
    client = _client_from_env(a.base_name)
    facts = json.loads(Path(a.facts).read_text())
    report = run_probe(facts, vllm_generator(client.with_model(a.base_name), max_tokens=a.max_tokens),
                       vllm_generator(client.with_model(a.adapter_name), max_tokens=a.max_tokens),
                       gate={'max_adapter_rate': a.max_adapter_rate, 'max_excess_over_base': a.max_excess_over_base},
                       include_text=a.include_text)
    _write_new(a.output, report)
    print(json.dumps({k: report[k] for k in ('facts', 'base_rate', 'adapter_rate', 'passed')}))
    return 0 if report['passed'] else 2


def cmd_bakeoff(a):
    """Banker bake-off through the self-hosted route. Mirrors scripts/evaluate_local_banker.py (--run gated)."""
    from agents.runtime.banker_session import run_banker_session, validate_case
    from agents.runtime.loop import RepairPolicy
    from agents.inference.selfhosted_client import SelfHostedTransport
    client = _client_from_env(a.model)
    case = validate_case(json.loads(Path(a.case).read_text()))
    if not a.run:
        print(json.dumps({'status': 'validated_not_run', 'model': a.model, 'endpoint': client.endpoint, 'mode': a.mode,
                          'scope': a.scope, 'profile': a.profile, 'no_network_or_inference': True}))
        return 0
    limits = {'profile': a.profile, 'output_tokens': a.output_tokens, 'call_seconds': a.call_seconds}
    if a.profile == 'diagnostic':
        limits.update(seconds=a.block_seconds if a.mode == 'blocks' else a.pass_seconds)
    pass_args = {k: v for k, v in limits.items() if v is not None} if a.mode == 'single' else {'profile': a.profile}
    block_args = {k: v for k, v in limits.items() if v is not None} if a.mode == 'blocks' else {'profile': a.profile}
    report = run_banker_session(case=case, output=Path(a.output), model=a.model, endpoint=client.endpoint, passes=a.passes,
                                scope=a.scope, mode=a.mode, repair=None if a.no_repair else RepairPolicy(2, 6),
                                budget_args=pass_args, block_budget_args=block_args, session_seconds=a.session_seconds,
                                infra_resume=a.infra_resume,
                                transport_factory=lambda: SelfHostedTransport(client, max_timeout=1800))
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'draft_exported' else 1


def cmd_round(a):
    """One real expert-iteration round on the GPU host: vLLM sampling, QLoRA training, vLLM held-out eval + probe."""
    from training.backends import QloraBackend
    from training.chat_data import read_jsonl
    from training.real_training import base_model_info, run_round
    client = _client_from_env(a.base_name)
    public = read_jsonl(a.public_rows)
    private = read_jsonl(a.private_rows) if a.private_rows else []
    declared = json.loads(Path(a.base_manifest).read_text())
    info = base_model_info(a.base_dir, declared)
    held = a.held_out_deal or []
    factory = make_generator_factory(client, base_name=a.base_name, auto_load_adapters=True, adapter_subdir=a.role,
                                     max_tokens=a.eval_max_tokens)
    probe_hook = None
    if a.facts:
        probe_factory = make_generator_factory(client, base_name=a.base_name, auto_load_adapters=True,
                                               adapter_subdir=a.role, max_tokens=24)
        probe_hook = make_probe_hook(probe_factory, json.loads(Path(a.facts).read_text()), base_dir=a.base_dir)
    backend = QloraBackend(python=a.train_python)
    if a.vllm_stop_cmd or a.vllm_start_cmd:
        import shlex
        if not (a.vllm_stop_cmd and a.vllm_start_cmd):
            raise ValueError('--vllm-stop-cmd and --vllm-start-cmd must be given together')
        backend = ServingPausedBackend(backend, stop_cmd=shlex.split(a.vllm_stop_cmd), start_cmd=shlex.split(a.vllm_start_cmd),
                                       ready=lambda: bool(client.list_models(timeout=5)))
    manifest = run_round(
        round_id=a.round_id, public_rows=public, private_rows=private, output_root=a.out, held_out_deals=held,
        sampler=sampler_from_client(client.with_model(a.base_name), temperature=a.temperature, max_tokens=a.sample_max_tokens),
        backend=backend, base_model_dir=a.base_dir, base_info=info, make_generator=factory,
        config={'role': a.role, 'samples_per_case': a.samples_per_case, 'top_k': a.top_k, 'minimum_reward': 1.0,
                'eval_max_tokens': a.eval_max_tokens},
        hyper=json.loads(a.hyper) if a.hyper else None, repo_root=Path(__file__).resolve().parents[1], probe_hook=probe_hook)
    print(json.dumps({k: manifest[k] for k in ('round_id', 'heldout', 'reward_stats', 'adapter_verified', 'quality_claim')}, indent=2))
    return 0


def build_parser():
    import argparse
    ap = argparse.ArgumentParser(description='GPU-host helpers over the private vLLM route (env: SELFHOSTED_BASE_URL, SELFHOSTED_TOKEN_FILE)')
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('probe', help='memorisation probe, base vs served LoRA adapter')
    p.add_argument('--facts', required=True)
    p.add_argument('--base-name', required=True)
    p.add_argument('--adapter-name', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--max-tokens', type=int, default=24)
    p.add_argument('--max-adapter-rate', type=float, default=0.05)
    p.add_argument('--max-excess-over-base', type=float, default=0.02)
    p.add_argument('--include-text', action='store_true')
    p.set_defaults(func=cmd_probe)
    b = sub.add_parser('bakeoff', help='banker harness against a served model (validated_not_run without --run)')
    b.add_argument('--case', required=True)
    b.add_argument('--output', required=True)
    b.add_argument('--model', required=True, help='served model name (also the part after selfhosted:)')
    b.add_argument('--passes', type=int, choices=(1, 2, 3), default=1)
    b.add_argument('--scope', choices=('full', 'historical', 'pnl'), default='full')
    b.add_argument('--mode', choices=('single', 'blocks'), default='blocks')
    b.add_argument('--profile', choices=('default', 'diagnostic'), default='diagnostic')
    b.add_argument('--no-repair', action='store_true')
    b.add_argument('--infra-resume', action='store_true')
    b.add_argument('--pass-seconds', type=float, default=600)
    b.add_argument('--block-seconds', type=float, default=600)
    b.add_argument('--call-seconds', type=float, default=300)
    b.add_argument('--output-tokens', type=int, default=2200)
    b.add_argument('--session-seconds', type=float, default=3600)
    b.add_argument('--run', action='store_true', help='explicitly authorise inference on the private GPU endpoint')
    b.set_defaults(func=cmd_bakeoff)
    r = sub.add_parser('round', help='one expert-iteration round (QLoRA) on the GPU host')
    r.add_argument('--round-id', required=True)
    r.add_argument('--public-rows', required=True, help='JSONL rows with answer_key (same shape as synthetic_rows())')
    r.add_argument('--private-rows')
    r.add_argument('--held-out-deal', action='append')
    r.add_argument('--out', required=True, help='output root; private-trained adapters must be under an ignored private path')
    r.add_argument('--base-dir', required=True, help='local snapshot of the base weights (also given to qlora_train.py)')
    r.add_argument('--base-manifest', required=True, help='JSON declaring repo/revision of the base weights')
    r.add_argument('--base-name', required=True, help='name vLLM serves the base under')
    r.add_argument('--role', default='author')
    r.add_argument('--train-python', default=sys.executable)
    r.add_argument('--vllm-stop-cmd', help='command (no shell) that frees the GPU before training, e.g. "sudo systemctl stop vllm"')
    r.add_argument('--vllm-start-cmd', help='command that restarts vLLM (with LoRA enabled) after training')
    r.add_argument('--samples-per-case', type=int, default=8)
    r.add_argument('--top-k', type=int, default=2)
    r.add_argument('--temperature', type=float, default=0.8)
    r.add_argument('--sample-max-tokens', type=int, default=512)
    r.add_argument('--eval-max-tokens', type=int, default=256)
    r.add_argument('--hyper', help='JSON for QloraBackend (lora_r, epochs, learning_rate, ...)')
    r.add_argument('--facts', help='private memorisation-probe facts JSON')
    r.set_defaults(func=cmd_round)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == '__main__':
    raise SystemExit(main())
