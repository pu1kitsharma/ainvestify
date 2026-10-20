"""One real expert-iteration round: sample -> score -> filter -> train -> evaluate -> manifest.

Replaces the mock trainer of `expert_iteration.run_iteration`. Everything model-facing
is injected: `sampler(messages) -> text` (OpenAI-compatible endpoint), a trainer
backend (MLX LoRA locally, CUDA QLoRA on a GPU host) and a generator factory used
for held-out evaluation of base and adapter. The module itself imports no ML library.

Guarantees enforced here (see tests/training):
  * rewards come only from training.envs.score_case against answer keys that never
    reach the sampler; unsupported/missing checks cannot be selected;
  * leave-one-deal-out: no deal is evaluated by an adapter trained on it;
  * private trajectories are upweighted but capped at <=10% of the mix, and a round
    that touches private data may only write under ignored private paths;
  * the manifest is written exclusively (never overwritten) and made read-only.
Nothing here claims investment-quality output; `quality_claim` is always 'none'.
"""
import hashlib
import json
import os
import platform
import resource
import time
from pathlib import Path

from training.chat_data import (build_prompt, parse_prediction, to_example, validate_dataset, ROLES)
from training.envs import (assert_deals_unseen, evaluate, mix_private_examples, score_case,
                           split_training_rows, validate_splits, adapter_destination_ok)
from training.expert_iteration import _write_new

CONTRACT = 'agentic-expert-iteration-real-v1'
DEFAULT_CONFIG = {'role': 'author', 'samples_per_case': 4, 'top_k': 2, 'minimum_reward': 1.0,
                  'private_upweight': 3, 'private_cap': 0.10, 'eval_max_tokens': 256}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()


def _check_row(row):
    key = row.get('answer_key')
    if not isinstance(row.get('input'), dict) or not isinstance(key, dict) or key.get('case_id') != row['case_id']:
        raise ValueError('Rows need input objects and independent answer keys')
    # Fail closed on a malformed key before any model call.
    score_case({'case_id': row['case_id'], 'environment': key.get('environment')}, key)


def _check_private_row(row):
    if row.get('rights_status') != 'private_training_approved' or row.get('private') is not True:
        raise ValueError('Private rows need rights_status=private_training_approved and private=true')
    if not row.get('case_id') or not row.get('deal_id'):
        raise ValueError('Private rows need case_id and deal_id')
    _check_row(row)


def _supported(reward):
    return all(c['status'] in ('matched', 'mismatch') for c in reward['checks'].values())


def model_prediction(text, row):
    """Parse model text into a prediction the scorer accepts. The scorer raises on
    malformed observations (a contract error for caller-supplied data); for *model*
    output that is just a zero-reward answer, so such text becomes an empty prediction."""
    prediction = parse_prediction(text, row['case_id'], row['answer_key']['environment'])
    try:
        score_case(prediction, row['answer_key'])
        return prediction, False
    except ValueError:
        return parse_prediction(None, row['case_id'], row['answer_key']['environment']), True


def sample_and_score(rows, sampler, role, samples_per_case, out_dir):
    """Returns list of records; raw model text is saved before scoring."""
    records = []
    for row in rows:
        messages = build_prompt(role, row['input'])  # answer_key never enters the prompt
        for attempt in range(samples_per_case):
            text = sampler(messages)
            if not isinstance(text, str):
                raise ValueError('Sampler must return text')
            idx = len(records)
            _write_new(out_dir / ('sample-%06d.json' % idx), {'case_id': row['case_id'], 'attempt': attempt, 'text': text})
            prediction, malformed = model_prediction(text, row)
            reward = {**score_case(prediction, row['answer_key']), 'malformed_model_output': malformed}
            _write_new(out_dir / ('reward-%06d.json' % idx), reward)
            records.append({'case_id': row['case_id'], 'deal_id': row.get('deal_id') or row.get('company_key'),
                            'private': row.get('private') is True, 'text': text, 'reward': reward,
                            'input': row['input']})
    return records


def select_top_k(records, top_k, minimum_reward):
    """Top-k distinct, fully supported responses per task by reward (stable tie-break)."""
    by_case = {}
    for r in records:
        if _supported(r['reward']) and r['reward']['reward'] >= minimum_reward and r['reward']['reward'] > 0:
            by_case.setdefault(r['case_id'], []).append(r)
    chosen = []
    for case_id in sorted(by_case):
        seen = set()
        for r in sorted(by_case[case_id], key=lambda x: -x['reward']['reward']):
            if r['text'].strip() in seen:
                continue
            seen.add(r['text'].strip())
            chosen.append(r)
            if len(seen) >= top_k:
                break
    return chosen


def _reward_stats(records, chosen):
    rewards = [r['reward']['reward'] for r in records]
    return {'samples': len(records), 'mean_reward': sum(rewards) / len(rewards) if rewards else 0.0,
            'max_reward': max(rewards, default=0.0), 'selected': len(chosen),
            'selected_mean_reward': (sum(r['reward']['reward'] for r in chosen) / len(chosen)) if chosen else 0.0,
            'cases_with_selection': len({r['case_id'] for r in chosen})}


def heldout_eval(rows, generate, role, max_tokens_note=None):
    """generate(list_of_messages) -> list[str]. Uses the same prompt builder as sampling."""
    prompts = [build_prompt(role, row['input']) for row in rows]
    texts = generate(prompts)
    if len(texts) != len(rows):
        raise ValueError('Generator returned wrong number of outputs')
    parsed = [model_prediction(t, row) for t, row in zip(texts, rows)]
    predictions = [p for p, _ in parsed]
    report = evaluate(predictions, [row['answer_key'] for row in rows])
    return {'mean_reward': report['mean_reward'], 'cases': len(rows), 'answer_key_sha256': report['answer_key_sha256'],
            'outputs_sha256': sha256_bytes(canonical(texts)),
            'malformed_outputs': sum(m for _, m in parsed),
            'per_case': {c['case_id']: c['reward'] for c in report['cases']}, 'raw_outputs': texts}


def base_model_info(base_dir, manifest=None):
    base_dir = Path(base_dir)
    files = {p.name: {'bytes': p.stat().st_size, 'sha256': sha256_file(p)}
             for p in sorted(base_dir.iterdir()) if p.is_file() and p.suffix in ('.safetensors', '.json')}
    return {'path': str(base_dir), 'files': files, 'declared': manifest or {}}


def run_round(*, round_id, public_rows, output_root, sampler, backend, base_model_dir, base_info,
              make_generator, private_rows=(), held_out_deals=(), config=None, hyper=None,
              repo_root='.', probe_hook=None):
    """Run one round and return its manifest. `make_generator(base_dir, adapter_dir_or_None)`
    -> fn(prompts)->texts. `probe_hook(adapter_dir)` may run the memorisation probe."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    role = cfg['role']
    if role not in ROLES:
        raise ValueError('Unknown role')
    for key, lo, hi in (('samples_per_case', 1, 100), ('top_k', 1, 20)):
        if type(cfg[key]) is not int or not lo <= cfg[key] <= hi:
            raise ValueError('%s out of bounds' % key)
    public_rows, private_rows = list(public_rows), list(private_rows)
    split_manifest = validate_splits(public_rows)
    for row in public_rows:
        _check_row(row)
    for row in private_rows:
        _check_private_row(row)
    uses_private = bool(private_rows)

    train_pub_rows = [r for r in public_rows if r['split'] == 'train']
    eval_pub_rows = [r for r in public_rows if r['split'] in ('valid', 'test')]
    train_pub, train_priv, excluded_priv, trained_deals = split_training_rows(train_pub_rows, private_rows, held_out_deals)
    eval_rows = eval_pub_rows + excluded_priv
    eval_deals = [r.get('deal_id') or r['company_key'] for r in eval_rows]
    assert_deals_unseen(trained_deals, eval_deals)
    if not eval_rows:
        raise ValueError('No held-out cases')

    root = adapter_destination_ok(Path(output_root), trained_on_private=uses_private, repo_root=repo_root)
    out = root / round_id
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    adapter_dir = adapter_destination_ok(out / 'adapter', trained_on_private=uses_private, repo_root=repo_root)
    (out / 'samples').mkdir(mode=0o700)
    started = time.time()
    try:
        records = sample_and_score(train_pub + train_priv, sampler, role, cfg['samples_per_case'], out / 'samples')
        chosen = select_top_k(records, cfg['top_k'], cfg['minimum_reward'])
        pub_examples = [to_example(role, r['input'], r['text']) for r in chosen if not r['private']]
        priv_examples = [to_example(role, r['input'], r['text']) for r in chosen if r['private']]
        mixed, mix_stats = mix_private_examples(pub_examples, priv_examples, cfg['private_upweight'], cfg['private_cap'])
        if not mixed:
            raise ValueError('No sample reached the reward threshold; nothing to train on')
        validate_dataset(mixed, role)
        data_dir = out / 'data'
        data_dir.mkdir(mode=0o700)
        # MLX needs a non-empty validation file. With very few examples it is a copy of
        # training rows: recorded as overlap, so its loss is a plumbing signal only.
        valid_examples = mixed[-1:] if len(mixed) > 3 else mixed[:1]
        overlap = True
        _write_new(data_dir / 'train.jsonl', mixed, jsonl=True)
        _write_new(data_dir / 'valid.jsonl', valid_examples, jsonl=True)
        train_sha = sha256_file(data_dir / 'train.jsonl')

        extra = {'role': role, 'private': uses_private} if backend.name == 'cuda_qlora' else {}
        train_info = backend.train(base_model_dir, data_dir, adapter_dir, hyper or {}, out / 'train.log', **extra)

        adapter_files = {p.relative_to(adapter_dir).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha256_file(p)}
                         for p in sorted(adapter_dir.rglob('*')) if p.is_file()}
        if not any(name.endswith('.safetensors') for name in adapter_files):
            raise RuntimeError('Trainer produced no adapter weights')

        base_gen = make_generator(base_model_dir, None)
        adapter_gen = make_generator(base_model_dir, adapter_dir)
        sanity = adapter_gen([build_prompt(role, eval_rows[0]['input'])])
        adapter_verified = bool(sanity and isinstance(sanity[0], str) and sanity[0].strip())
        base_eval = heldout_eval(eval_rows, base_gen, role)
        adapter_eval = heldout_eval(eval_rows, adapter_gen, role)
        probe = probe_hook(adapter_dir) if probe_hook else None
        _write_new(out / 'heldout_base.json', base_eval)
        _write_new(out / 'heldout_adapter.json', adapter_eval)

        manifest = {
            'contract': CONTRACT, 'round_id': round_id, 'role': role, 'quality_claim': 'none',
            'weights_trained': True, 'adapter_verified': adapter_verified, 'investor_acceptance': False,
            'config': cfg, 'hyper': train_info.get('hyper', hyper or {}), 'trainer': train_info,
            'base_model': base_info,
            'data_provenance': {
                'public_source_sha256': sha256_bytes(canonical([{k: v for k, v in r.items()} for r in public_rows])),
                'private_rows_sha256': sha256_bytes(canonical(private_rows)) if private_rows else None,
                'split_manifest': split_manifest, 'train_jsonl_sha256': train_sha,
                'valid_overlaps_train': overlap, 'mix': mix_stats,
                'trained_on_deals': trained_deals, 'held_out_deals': sorted({str(d).casefold() for d in eval_deals}),
                'excluded_private_cases': [r['case_id'] for r in excluded_priv]},
            'reward_stats': _reward_stats(records, chosen),
            'heldout': {'cases': len(eval_rows), 'base_mean_reward': base_eval['mean_reward'],
                        'adapter_mean_reward': adapter_eval['mean_reward'],
                        'adapter_beats_base': adapter_eval['mean_reward'] > base_eval['mean_reward']},
            'adapter': {'dir': str(adapter_dir), 'files': adapter_files, 'trained_on_private': uses_private,
                        'storage_policy': 'ignored private path' if uses_private else 'public allowed'},
            'memorisation_probe': probe if probe is not None else 'unrun',
            'environment': {'platform': platform.platform(), 'python': platform.python_version(),
                            'wall_seconds': round(time.time() - started, 2),
                            'peak_rss_mb_driver': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1048576 if platform.system() == 'Darwin' else 1024), 1)},
        }
        _write_new(out / 'manifest.json', manifest)
        os.chmod(out / 'manifest.json', 0o400)
        return manifest
    except Exception as exc:
        _write_new(out / 'failure.json', {'status': 'round_failed', 'error_type': type(exc).__name__,
                                          'error': str(exc)[:500], 'weights_trained': False})
        raise
