"""Frozen fictional source interpretation, followed by exact replay; no release."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest, recorded_call
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research import source_interpretation as interpreter
from agents.research.diligence_semantic_canary import canary_fixture, CONTRACT_V2
from scripts.evaluate_private_material_acceptance import _installed_digest, _write_new, _replace


ROOT = Path(__file__).resolve().parents[1] / 'runtime_qualification/local_semantic_canary'
CONTRACT = 'source-interpretation-qualification-v1'


def frozen_inputs(pin, interpretation_contract=interpreter.CONTRACT):
    fixture = canary_fixture(CONTRACT_V2)
    sources = [{'id': 'S' + str(index), 'url': 'https://example.invalid/source/' + str(index),
                'title': 'Fictional source ' + str(index), 'passage': case['passage'],
                'version': digest(case['passage']), 'attribution': 'Fictional qualification input'}
               for index, case in enumerate(fixture['cases'], 1)]
    atomic = interpretation_contract in {interpreter.CONTRACT_V2, interpreter.CONTRACT_V3, interpreter.CONTRACT_V4, interpreter.CONTRACT_V5}
    if interpretation_contract not in {interpreter.CONTRACT, interpreter.CONTRACT_V2, interpreter.CONTRACT_V3, interpreter.CONTRACT_V4, interpreter.CONTRACT_V5}:
        raise ValueError('Unknown source interpretation contract')
    batches = interpreter.frozen_interpretation_batches(sources, pin,
        contract=interpretation_contract) if atomic else None
    requests = ([request for batch in batches for request in batch['requests']] if atomic
                else interpreter.frozen_interpretation_requests(sources, pin))
    options = interpreter.OPTIONS_V2 if atomic else interpreter.OPTIONS
    body = {'contract': CONTRACT, 'interpretation_contract': interpretation_contract,
            'fixture_contract': CONTRACT_V2, 'fixture_digest': digest(fixture),
            'model_pin': pin, 'options': options, 'sources': sources,
            'request_digest': digest([[task, instruction, payload, schema.model_json_schema()]
                                     for task, instruction, payload, schema in requests])}
    if atomic:
        body['batch_plan'] = [{'batch_id': b['batch_id'], 'shard_index': b['shard_index'],
            'source_ids': b['source_ids'], 'request_count': len(b['requests'])} for b in batches]
    return fixture, requests, body


def evaluate(fixture, requests, attempts, pin):
    result = {'contract': CONTRACT, 'model_pin': pin, 'attempt_digest': digest(attempts),
              'completed_batches': 0, 'scored_cases': [], 'failures': [],
              'private_acceptance': 'not_established', 'investor_approval': 'not_established',
              'financial_qualification': 'not_established', 'regulatory_approval': 'not_established',
              'untested_positive_categories': ['identity', 'team_and_governance',
                  'legal_and_compliance', 'opposing_evidence']}
    try:
        if len(attempts) > len(requests) or len({row['id'] for row in attempts}) != len(attempts):
            raise ValueError('Response identity/count differs from the frozen batch plan')
        for index, (row, request) in enumerate(zip(attempts, requests)):
            bound = interpreter.replay_assessment(row, request)
            for sid, assessment in bound.items():
                case = fixture['cases'][int(sid[1:]) - 1]
                expected = case['expected']
                topics = {item['topic'] for item in assessment['supported_topics']}
                if assessment['content_kind'] not in expected['kinds']:
                    result['failures'].append(case['id'] + ': incorrect content kind')
                for topic in sorted(set(expected['required']) - topics):
                    result['failures'].append(case['id'] + ': omitted ' + topic)
                for topic in sorted(topics - set(expected['allowed'])):
                    result['failures'].append(case['id'] + ': unsupported ' + topic)
                result['scored_cases'].append(case['id'])
            if request[2]['contract'] in {interpreter.CONTRACT_V2, interpreter.CONTRACT_V3, interpreter.CONTRACT_V4, interpreter.CONTRACT_V5}:
                if request[2]['group_request_index'] == request[2]['group_request_count']:
                    result['completed_batches'] += 1
            else:
                result['completed_batches'] = index + 1
    except (ValueError, KeyError, TypeError) as exc:
        return {**result, 'state': 'blocked', 'reason': 'exact_interpretation_replay_failed',
                'detail': str(exc), 'ambiguity': getattr(exc, 'detail', None)}
    if result['failures']:
        return {**result, 'state': 'blocked', 'reason': 'source_interpretation_failed'}
    if len(attempts) < len(requests):
        return {**result, 'state': 'needs_call', 'next_request': len(attempts) + 1,
                'next_batch': requests[len(attempts)][2]['shard_index']}
    return {**result, 'state': 'qualified_fictional_topic_boundaries'}


def run(output, phase, model='qwen3.5:9b', interpretation_contract=None):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT.resolve()) or output == ROOT.resolve():
        raise ValueError('Use a fresh local qualification subdirectory')
    pin = {'name': model, 'digest': _installed_digest(model)}
    manifest = output / 'source_request.json'
    selected = interpretation_contract or (interpreter.CONTRACT_V2 if phase == 'prepare'
        else json.loads(manifest.read_text())['interpretation_contract'])
    fixture, requests, body = frozen_inputs(pin, selected)
    if phase == 'prepare':
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        _write_new(manifest, {**body, 'digest': digest(body)})
        return {'state': 'prepared', 'model_calls': len(requests),
                'logical_batches': len({r[2]['shard_index'] for r in requests}),
                'cases': len(fixture['cases'])}
    saved = json.loads(manifest.read_text())
    if saved != {**body, 'digest': digest(body)}:
        raise ValueError('Frozen model, inputs, schema, instructions or options changed')
    attempts = []
    prefix = 'group_response_' if selected in {interpreter.CONTRACT_V2, interpreter.CONTRACT_V3, interpreter.CONTRACT_V4, interpreter.CONTRACT_V5} else 'batch_'
    for number in range(1, len(requests) + 1):
        path = output / (prefix + str(number) + '.json')
        if path.exists():
            if number != len(attempts) + 1:
                raise ValueError('Response history is not a contiguous prefix')
            attempts.append(json.loads(path.read_text()))
    result = evaluate(fixture, requests, attempts, pin)
    if phase == 'advance' and result['state'] == 'needs_call':
        shard = requests[len(attempts)][2]['shard_index']
        role = LocalModel(model, **body['options'])
        budget = PreparationBudget(105, max_calls=6, max_requests=6)
        while (result['state'] == 'needs_call' and len(attempts) < len(requests)
               and requests[len(attempts)][2]['shard_index'] == shard):
            number = len(attempts) + 1
            path = output / (prefix + str(number) + '.json')
            task, instruction, payload, schema = requests[number - 1]
            try:
                with preparation_budget(budget):
                    recorded_call(role, task, instruction, payload, schema, attempts,
                                  lambda: _write_new(path, attempts[-1]))
            except Exception:
                if not path.exists():
                    raise
            if json.loads(path.read_text()) != attempts[-1]:
                raise ValueError('Saved raw receipt differs from the recorded model response')
            result = evaluate(fixture, requests, attempts, pin)
        _write_new(output / ('budget_%s.json' % shard), budget.snapshot())
    elif phase not in {'advance', 'verify'}:
        raise ValueError('Unknown qualification phase')
    path = output / 'source_result.json'
    (_replace if path.exists() else _write_new)(path, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('prepare', 'advance', 'verify'), required=True)
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--interpretation-contract', choices=(interpreter.CONTRACT, interpreter.CONTRACT_V2, interpreter.CONTRACT_V3, interpreter.CONTRACT_V4, interpreter.CONTRACT_V5))
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.phase, args.model, args.interpretation_contract)))
