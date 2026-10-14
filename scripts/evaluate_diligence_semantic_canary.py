"""Checkpointed fictional local-model qualification; no private inputs accepted."""
import argparse
import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest, recorded_call
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research import diligence_semantic_canary as canary
from scripts.evaluate_private_material_acceptance import _installed_digest, _write_new, _replace


OUTPUT_ROOT = Path(__file__).resolve().parents[1] / 'runtime_qualification/local_semantic_canary'


def run(output, phase, model='qwen3:14b', *, contract=None, profile=None):
    root = Path(output).resolve()
    if not root.is_relative_to(OUTPUT_ROOT.resolve()) or root == OUTPUT_ROOT.resolve():
        raise ValueError('Synthetic canary must use a fresh qualification subdirectory')
    request_file = root / 'canary_request.json'
    if phase == 'prepare':
        selected_contract = contract or canary.CONTRACT
        pin = {'name': model, 'digest': _installed_digest(model)}
        options = canary.canary_options(pin, contract=selected_contract, profile=profile)
        requests = canary.frozen_canary_requests(pin, contract=selected_contract, profile=profile)
        body = {'contract': selected_contract, 'model_pin': pin,
                'fixture_digest': digest(canary.canary_fixture(selected_contract)),
                'options': options, 'request_digest': digest([
                    {'task': task, 'instruction': instruction, 'input': payload, 'schema': schema.model_json_schema()}
                    for task, instruction, payload, schema in requests])}
        if profile is not None:
            body['profile'] = profile
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        _write_new(request_file, {**body, 'digest': digest(body)})
        return {'state': 'prepared', 'checkpoints': 5, 'qualification_scope': canary.QUALIFIED_BOUNDARIES}
    frozen = json.loads(request_file.read_text())
    selected_contract = frozen['contract']
    selected_profile = frozen.get('profile')
    if profile is not None and profile != selected_profile:
        raise ValueError('Frozen synthetic capacity profile cannot change')
    if contract is not None and contract != selected_contract:
        raise ValueError('Frozen synthetic canary contract cannot change')
    body = {key: value for key, value in frozen.items() if key != 'digest'}
    pin = frozen['model_pin']
    options = canary.canary_options(pin, contract=selected_contract, profile=selected_profile)
    requests = canary.frozen_canary_requests(pin, contract=selected_contract, profile=selected_profile)
    expected_digest = digest([{'task': task, 'instruction': instruction, 'input': payload,
                              'schema': schema.model_json_schema()} for task, instruction, payload, schema in requests])
    if (digest(body) != frozen['digest'] or selected_contract not in canary.FIXTURES or
            frozen['fixture_digest'] != digest(canary.canary_fixture(selected_contract)) or frozen['options'] != options or
            frozen['request_digest'] != expected_digest or model != pin['name'] or
            _installed_digest(model) != pin['digest']):
        raise ValueError('Frozen synthetic inputs, options or installed model changed')
    attempts = []
    for checkpoint in range(1, 6):
        path = root / ('checkpoint_%s.json' % checkpoint)
        if path.exists():
            if checkpoint != len(attempts) + 1:
                raise ValueError('Synthetic checkpoint history is not contiguous')
            attempts.append(json.loads(path.read_text()))
    result = canary.evaluate_canary(pin, attempts, contract=selected_contract, profile=selected_profile)
    if phase == 'advance' and result['state'] == 'needs_call':
        index = len(attempts)
        rows = list(attempts)
        target = root / ('checkpoint_%s.json' % (index + 1))
        budget = PreparationBudget(105, max_calls=6, max_requests=6)
        role = LocalModel(pin['name'], **options)
        task, instruction, payload, schema = requests[index]
        try:
            with preparation_budget(budget):
                recorded_call(role, task, instruction, payload, schema, rows,
                              lambda: _write_new(target, rows[-1]))
        except Exception:
            # Raw failed responses are immutable. A failed canary has no retry.
            if not target.exists():
                raise
        _write_new(root / ('budget_%s.json' % (index + 1)), budget.snapshot())
        persisted = json.loads(target.read_text())
        if not rows or persisted != rows[-1]:
            raise ValueError('Synthetic model receipt was not preserved exactly')
        result = canary.evaluate_canary(pin, [*attempts, persisted], contract=selected_contract, profile=selected_profile)
    elif phase not in {'advance', 'verify'}:
        raise ValueError('Unknown synthetic canary phase')
    result_file = root / 'canary_result.json'
    (_replace if result_file.exists() else _write_new)(result_file, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('prepare', 'advance', 'verify'), required=True)
    parser.add_argument('--model', default='qwen3:14b')
    parser.add_argument('--canary-contract', choices=(canary.CONTRACT_V1, canary.CONTRACT_V2))
    parser.add_argument('--profile', choices=tuple(canary.PROFILES))
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.phase, args.model, contract=args.canary_contract, profile=args.profile)))
