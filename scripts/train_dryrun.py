#!/usr/bin/env python3
"""Phase A dry run: one full expert-iteration round on FICTIONAL tasks with a tiny MLX model.

Run with the repo venv; MLX runs in a separate interpreter (--mlx-python). Plumbing
proof only: no quality claim, no confidential data, no hosted API.
"""
import argparse
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from training.backends import ChatEndpointSampler, MlxLoraBackend  # noqa: E402
from training.chat_data import to_example  # noqa: E402
from training.expert_iteration import _write_new  # noqa: E402
from training.memorisation_probe import run_probe  # noqa: E402
from training.real_training import base_model_info, run_round  # noqa: E402
from training.synthetic_tasks import canary_facts, synthetic_rows  # noqa: E402


def wait_ready(url, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            request.urlopen(url + '/models', timeout=3).read()
            return
        except Exception:
            time.sleep(1.5)
    raise RuntimeError('sampling server did not become ready')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mlx-python', default=str(REPO / 'runtime_qualification/finetune/venv/bin/python'))
    ap.add_argument('--base', default=str(REPO / 'runtime_qualification/agentic_banker/dryrun/base'))
    ap.add_argument('--out', default=str(REPO / 'runtime_qualification/agentic_banker/dryrun/private'))
    ap.add_argument('--round-id', default='round-001')
    ap.add_argument('--port', type=int, default=8089)
    ap.add_argument('--samples-per-case', type=int, default=10)
    ap.add_argument('--iters', type=int, default=30)
    ap.add_argument('--n-train', type=int, default=20)
    ap.add_argument('--temperature', type=float, default=0.6)
    ap.add_argument('--lr', type=float, default=5e-5)
    ap.add_argument('--control-iters', type=int, default=60)
    a = ap.parse_args()

    url = 'http://127.0.0.1:%d/v1' % a.port
    backend = MlxLoraBackend(a.mlx_python)
    declared = json.loads((Path(a.base).parent / 'base_model_manifest.json').read_text())
    info = base_model_info(a.base, declared)
    public, private = synthetic_rows(a.n_train)
    facts = canary_facts()

    server = subprocess.Popen([a.mlx_python, '-m', 'mlx_lm', 'server', '--model', a.base, '--host', '127.0.0.1',
                               '--port', str(a.port), '--log-level', 'WARNING'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_ready(url)
        sampler = ChatEndpointSampler(url, a.base, temperature=a.temperature, max_tokens=120)

        def probe_hook(adapter_dir):
            rep = run_probe(facts['seen'] + facts['unseen'], backend.generator(a.base, None, max_tokens=24),
                            backend.generator(a.base, adapter_dir, max_tokens=24))
            return {k: rep[k] for k in ('facts', 'base_rate', 'adapter_rate', 'excess_over_base', 'passed', 'gate')} | {
                'note': 'Neither canary was in this round training data; expected rate 0 for the adapter.'}

        started = time.time()
        manifest = run_round(
            round_id=a.round_id, public_rows=public, private_rows=private, output_root=a.out,
            held_out_deals=['fictional-private-sigma'], sampler=sampler, backend=backend,
            base_model_dir=a.base, base_info=info, make_generator=lambda b, ad: backend.generator(b, ad, max_tokens=120),
            config={'samples_per_case': a.samples_per_case, 'top_k': 2, 'minimum_reward': 1.0, 'private_upweight': 3},
            hyper={'iters': a.iters, 'num_layers': 8, 'learning_rate': a.lr, 'max_seq_length': 512},
            repo_root=REPO, probe_hook=probe_hook)
    finally:
        server.terminate()
        server.wait(timeout=30)

    # Positive control: an adapter trained on a repeated canary must be flagged by the probe.
    out = Path(a.out) / (a.round_id + '-probe-control')
    data = out / 'data'
    data.mkdir(parents=True, exist_ok=False, mode=0o700)
    seen = facts['seen'][0]
    row = to_example('author', {'note': 'fictional control'}, seen['prefix'] + seen['secret'])
    _write_new(data / 'train.jsonl', [row] * 8, jsonl=True)
    _write_new(data / 'valid.jsonl', [row], jsonl=True)
    t0 = time.time()
    info_c = backend.train(a.base, data, out / 'adapter', {'iters': a.control_iters, 'num_layers': 8,
                           'learning_rate': 2e-4, 'max_seq_length': 256, 'mask_prompt': False}, out / 'train.log')
    rep = run_probe(facts['seen'] + facts['unseen'], backend.generator(a.base, None, max_tokens=24),
                    backend.generator(a.base, out / 'adapter', max_tokens=24),
                    gate={'max_adapter_rate': 0.05, 'max_excess_over_base': 0.02}, include_text=True)
    rep['kind'] = 'positive_control_synthetic_canary_in_training'
    rep['train_seconds'] = info_c['seconds']
    _write_new(out / 'probe_report.json', rep)
    summary = {'round_manifest': str(Path(a.out) / a.round_id / 'manifest.json'),
               'control_probe': str(out / 'probe_report.json'), 'total_wall_seconds': round(time.time() - started, 1),
               'max_child_rss_mb': round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1048576, 1),
               'heldout': manifest['heldout'], 'reward_stats': manifest['reward_stats'],
               'control_base_rate': rep['base_rate'], 'control_adapter_rate': rep['adapter_rate'],
               'control_flagged': not rep['passed']}
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
