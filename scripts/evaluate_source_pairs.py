"""Qualify separately recorded local evidence extraction and content-kind tasks.

The fictional answer matrix never enters inference. Exact replay is a mechanics
check; it grants no private, financial, regulatory or investor acceptance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest, recorded_call
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research import source_interpretation_pair as pairs
from agents.research.diligence_semantic_canary import canary_fixture, CONTRACT_V2
from scripts.evaluate_private_material_acceptance import _installed_digest, _write_new, _replace


ROOT = Path(__file__).resolve().parents[1] / 'runtime_qualification/local_semantic_canary'
CONTRACT = 'source-pair-qualification-v1'


def frozen_inputs(pin, contract=None):
    fixture = canary_fixture(CONTRACT_V2)
    sources = [{'id': 'S' + str(index), 'url': 'https://example.invalid/source/' + str(index),
                'title': 'Fictional source ' + str(index), 'passage': case['passage'],
                'version': digest(case['passage']), 'attribution': 'Fictional qualification input'}
               for index, case in enumerate(fixture['cases'], 1)]
    selected = contract or pairs.CONTRACT
    plan = pairs.frozen_source_pairs(sources, pin, contract=selected)
    body = {'contract': CONTRACT, 'interpretation_contract': selected,
            'fixture_contract': CONTRACT_V2, 'fixture_digest': digest(fixture),
            'model_pin': pin, 'options': dict(pairs.OPTIONS), 'sources': sources,
            'pair_plan': pairs.pair_plan_manifest(plan)}
    if selected != pairs.CONTRACT:
        body['stage_options'] = {'topic_extraction': dict(pairs.OPTIONS_THINKING),
                                 'content_kind': dict(pairs.OPTIONS)}
    return fixture, plan, body


def evaluate(fixture, plan, attempts, pin):
    progress = pairs.pair_progress(plan, attempts)
    result = {'contract': CONTRACT, 'model_pin': pin, 'attempt_digest': digest(attempts),
              'completed_pairs': progress.get('completed_pair_count', 0),
              'scored_cases': [], 'failures': [],
              'private_acceptance': 'not_established', 'investor_approval': 'not_established',
              'financial_qualification': 'not_established', 'regulatory_approval': 'not_established',
              'untested_positive_categories': ['identity', 'team_and_governance',
                  'legal_and_compliance', 'opposing_evidence']}
    for sid, assessment in progress.get('bound', {}).items():
        case = fixture['cases'][int(sid[1:]) - 1]
        expected = case['expected']
        topics = {item['topic'] for item in assessment['supported_topics']}
        if assessment['content_kind'] not in expected['kinds']:
            result['failures'].append(case['id'] + ': incorrect content kind')
        result['failures'].extend(case['id'] + ': omitted ' + topic
                                 for topic in sorted(set(expected['required']) - topics))
        result['failures'].extend(case['id'] + ': unsupported ' + topic
                                 for topic in sorted(topics - set(expected['allowed'])))
        result['scored_cases'].append(case['id'])
    if progress['state'] == 'blocked':
        return {**result, 'state': 'blocked', 'reason': 'exact_pair_replay_failed',
                'detail': progress.get('reason'), 'ambiguity': progress.get('detail')}
    if result['failures']:
        return {**result, 'state': 'blocked', 'reason': 'source_pair_semantics_failed'}
    if progress['state'] == 'accepted':
        return {**result, 'state': 'qualified_fictional_topic_boundaries'}
    return {**result, 'state': 'needs_call', 'next_pair': progress['pair_index']}


def run(output, phase, model='qwen3:14b', contract=None):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT.resolve()) or output == ROOT.resolve():
        raise ValueError('Use a fresh local qualification subdirectory')
    pin = {'name': model, 'digest': _installed_digest(model)}
    manifest = output / 'source_request.json'
    selected = contract or (pairs.CONTRACT if phase == 'prepare'
                            else json.loads(manifest.read_text())['interpretation_contract'])
    fixture, plan, body = frozen_inputs(pin, selected)
    if phase == 'prepare':
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        _write_new(manifest, {**body, 'digest': digest(body)})
        return {'state': 'prepared', 'pairs': len(plan), 'maximum_source_calls': len(plan) * 2,
                'cases': len(fixture['cases'])}
    if json.loads(manifest.read_text()) != {**body, 'digest': digest(body)}:
        raise ValueError('Frozen sources, instructions, schema, rule, model or options changed')
    attempts = []
    for number in range(1, len(plan) * 2 + 1):
        path = output / ('response_%s.json' % number)
        if path.exists():
            if number != len(attempts) + 1:
                raise ValueError('Pair responses are not a contiguous prefix')
            attempts.append(json.loads(path.read_text()))
    result = evaluate(fixture, plan, attempts, pin)
    if phase == 'advance' and result['state'] == 'needs_call':
        pair_index = result['next_pair']
        budget = PreparationBudget(105, max_calls=6, max_requests=6)
        call_start = len(attempts)
        while result['state'] == 'needs_call' and result['next_pair'] == pair_index:
            pending = pairs.pair_progress(plan, attempts, pass_pair_index=pair_index)
            if pending['state'] != 'needs_call' or pending['request'] is None:
                raise ValueError('Pair checkpoint disagrees with its exact replay')
            if len(attempts) - call_start >= 2:
                raise ValueError('A source pair cannot exceed two new model calls')
            number = len(attempts) + 1
            path = output / ('response_%s.json' % number)
            intent = output / ('call_%s.started.json' % number)
            # An interrupted transport without a durable answer cannot be repeated.
            if intent.exists():
                raise ValueError('Unresolved model call intent; review the saved failure before any new run')
            task, instruction, payload, schema = pending['request']
            role = LocalModel(model, **payload['options'])
            _write_new(intent, {'pair_index': pair_index, 'request_digest': digest(
                [task, instruction, payload, schema.model_json_schema()]), 'model_pin': pin})
            try:
                with preparation_budget(budget):
                    recorded_call(role, task, instruction, payload, schema, attempts,
                                  lambda: _write_new(path, attempts[-1]))
            except Exception:
                if not path.exists():
                    raise
            if json.loads(path.read_text()) != attempts[-1]:
                raise ValueError('Saved answer differs from its recorded response')
            result = evaluate(fixture, plan, attempts, pin)
        _write_new(output / ('budget_start_%s.json' % (call_start + 1)), budget.snapshot())
    elif phase not in {'advance', 'verify'}:
        raise ValueError('Unknown qualification phase')
    result_path = output / 'source_result.json'
    (_replace if result_path.exists() else _write_new)(result_path, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('prepare', 'advance', 'verify'), required=True)
    parser.add_argument('--model', default='qwen3:14b')
    parser.add_argument('--pair-contract', choices=('source-interpretation-pair-v1',
                                                   'source-interpretation-pair-v2'))
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.phase, args.model, args.pair_contract)))
