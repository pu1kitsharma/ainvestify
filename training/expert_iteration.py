"""Bounded offline expert-iteration plumbing with explicitly injected callbacks.

No default model, training backend, subprocess, endpoint or source collection.
Only dry-run mode is implemented. Callback declarations never prove trained weights.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path

from training.envs import evaluate, score_case, validate_splits


def _write_new(path, value, jsonl=False):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        if jsonl:
            for row in value:
                handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
        else:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write('\n')


def run_iteration(rows, output, *, sampler, trainer=None, evaluator=None,
                  private_holdout_companies=(), max_samples=100, samples_per_case=1,
                  minimum_reward=1.0, dry_run=True):
    """sample(input) -> {prediction, trajectory}; trainer(accepted) -> declaration.

    evaluator(declaration, heldout_inputs) may return predictions for held-out
    cases. None of these callbacks receives held-out answer keys. All callbacks
    must be trusted local implementations; this function is not a sandbox.
    Output is immutable and includes rejected samples as well as accepted ones.
    """
    if dry_run is not True:
        raise ValueError('Only offline dry-run plumbing is implemented; real training is unsupported')
    manifest = validate_splits(rows, private_holdout_companies)
    if type(max_samples) is not int or not 1 <= max_samples <= 10000:
        raise ValueError('max_samples must be bounded between 1 and 10000')
    if type(samples_per_case) is not int or not 1 <= samples_per_case <= 100:
        raise ValueError('samples_per_case must be bounded between 1 and 100')
    if type(minimum_reward) not in (int, float) or not math.isfinite(minimum_reward) or not 0 <= minimum_reward <= 1:
        raise ValueError('minimum_reward must be finite in [0, 1]')
    train = [row for row in rows if row['split'] == 'train']
    if len(train) * samples_per_case > max_samples:
        raise ValueError('Requested samples exceed bound; no partial hidden truncation')
    input_splits = {}
    for row in rows:
        key = row.get('answer_key')
        if not isinstance(row.get('input'), dict) or not isinstance(key, dict) or key.get('case_id') != row['case_id']:
            raise ValueError('Rows need independent answer keys and input objects')
        score_case({'case_id': row['case_id'], 'environment': key.get('environment')}, key)
        # IDs are metadata, not content. Renaming the task/company must not
        # disguise an identical offered task across train and held-out splits.
        offered = {name: value for name, value in row['input'].items()
                   if name not in ('case_id', 'company_key', 'split')}
        input_hash = hashlib.sha256(json.dumps(
            offered, sort_keys=True, allow_nan=False, separators=(',', ':')
        ).encode()).hexdigest()
        previous = input_splits.get(input_hash)
        if previous is not None and previous != row['split']:
            raise ValueError('Cross-split leakage: canonical task input')
        input_splits[input_hash] = row['split']
    output = Path(output)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    canonical = json.dumps(rows, sort_keys=True, allow_nan=False).encode()
    _write_new(output / 'source_manifest.json', {
        'source_sha256': hashlib.sha256(canonical).hexdigest(), 'split_manifest': manifest,
        'case_ids': [row['case_id'] for row in rows], 'dry_run': True,
        'callback_trust': 'caller_responsible_for_local_only_callbacks'})
    raw, accepted = [], []
    try:
        for row in train:
            for attempt in range(samples_per_case):
                # Exact answer keys stay outside model sampling requests.
                sample = sampler(deepcopy(row['input']))
                if not isinstance(sample, dict) or not isinstance(sample.get('trajectory'), list) or not sample['trajectory']:
                    raise ValueError('Sampler must retain a nonempty raw trajectory')
                record = {'case_id': row['case_id'], 'attempt': attempt, 'sample': deepcopy(sample)}
                # Save raw bytes before scoring so malformed failed responses survive.
                _write_new(output / f'sample-{len(raw):06d}.json', record)
                raw.append(record)
                reward = score_case(sample.get('prediction', {}), row['answer_key'])
                _write_new(output / f'reward-{len(raw)-1:06d}.json', reward)
                # Missing/unsupported checks cannot be selected even at threshold 0.
                supported = all(check['status'] in ('matched', 'mismatch') for check in reward['checks'].values())
                if supported and reward['reward'] >= minimum_reward:
                    accepted.append({**record, 'reward': reward})
        _write_new(output / 'accepted.jsonl', accepted, jsonl=True)
        declaration = trainer(deepcopy(accepted)) if trainer and accepted else None
        _write_new(output / 'trainer_declaration.json', {'unverified_callback_result': declaration,
                   'weights_trained': False, 'adapter_verified': False})
        heldout = [row for row in rows if row['split'] in ('valid', 'test')]
        report = None
        if evaluator:
            predictions = evaluator(deepcopy(declaration), [deepcopy(row['input']) for row in heldout])
            report = evaluate(predictions, [row['answer_key'] for row in heldout])
            _write_new(output / 'heldout_report.json', report)
        result = {'contract': 'agentic-expert-iteration-offline-v1', 'status': 'dry_run_plumbing_complete',
                  'samples': len(raw), 'selected': len(accepted), 'split_manifest': manifest,
                  'trainer_callback_invoked': bool(trainer and accepted),
                  'heldout_evaluation_run': report is not None, 'weights_trained': False,
                  'adapter_verified': False, 'investor_acceptance': False,
                  'real_training': 'unsupported', 'memorisation_probe': 'unrun'}
        _write_new(output / 'result.json', result)
        return result
    except Exception as exc:
        _write_new(output / 'failure.json', {'status': 'dry_run_failed', 'error_type': type(exc).__name__,
                   'samples_retained': len(raw), 'weights_trained': False})
        raise
