import copy
import json
import pytest

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import recorded_call
from agents.research import diligence_semantic_canary as canary


PIN = {'name': 'qwen3:14b', 'digest': 'b' * 64}


def synthetic_answers(contract=canary.CONTRACT):
    fixture = canary.canary_fixture(contract)
    requests = canary.frozen_canary_requests(PIN, contract=contract)
    answers = []
    for index, request in enumerate(requests):
        groups = {}
        for number, gid in enumerate(request[2]['groups']):
            expected = fixture['cases'][index * 2 + number]['expected']
            kind = expected['kinds'][0]
            groups[gid] = {'kind': kind, **{alias: ('E001' if category in expected['required'] else 'N')
                for alias, category in request[2]['category_aliases'].items()},
                'use': 'irrelevant' if kind in {'heading_only', 'contact_only'} else 'relevant',
                'proof': 'E001', 'why': 'Synthetic test evidence support.'}
        answers.append(groups)
    return answers


def recorded_synthetic_rows(monkeypatch, *, extra_market=False, contract=canary.CONTRACT,
                            pin=PIN, profile=None):
    rows, answers, current = [], synthetic_answers(contract), {'index': 0}
    if extra_market:
        answers[1]['G1']['C4'] = 'E001'

    def request(self, operation, **kwargs):
        self.last_call['transport_count'] += 1
        if kwargs.get('think'):
            return {'model': pin['name'], 'message': {'thinking': 'Synthetic transport stub.', 'content': ''},
                    'eval_count': kwargs['options']['num_predict'], 'prompt_eval_count': 1200, 'done_reason': 'length'}
        answer = answers[current['index']]
        current['index'] += 1
        assert operation == 'generate' and kwargs['raw'] is True
        assert kwargs['prompt'].endswith('Synthetic transport stub.\n</think>\n\n')
        return {'model': pin['name'], 'response': json.dumps(answer, separators=(',', ':')),
                'eval_count': 210, 'prompt_eval_count': 1420, 'done_reason': 'stop'}

    monkeypatch.setattr(LocalModel, '_request', request)
    for task, instruction, payload, schema in canary.frozen_canary_requests(pin, contract=contract, profile=profile):
        role = LocalModel(pin['name'], **canary.canary_options(pin, contract=contract, profile=profile))
        recorded_call(role, task, instruction, payload, schema, rows, lambda: None)
    return rows


def test_canary_expectations_are_held_out_and_all_categories_scored():
    requests = canary.frozen_canary_requests(PIN)
    assert len(requests) == 5
    for request in requests:
        assert len(request[2]['groups']) == 2
        assert set(request[2]['category_aliases'].values()) == set(canary.coverage.CATEGORIES)
        assert 'expected' not in json.dumps(request[2])
        assert all(len(group['passage']) >= 30 for group in request[2]['groups'].values())
    answer = synthetic_answers()[1]
    expectations = {gid: canary.canary_fixture()['cases'][2 + index]['expected']
                    for index, gid in enumerate(requests[1][2]['groups'])}
    aliases = requests[1][2]['category_aliases']
    assert canary.score_required_statuses(answer, expectations, aliases) == []
    for category in set(canary.coverage.CATEGORIES) - {'product_and_customers'}:
        changed = copy.deepcopy(answer)
        alias = next(key for key, value in aliases.items() if value == category)
        changed['G1'][alias] = 'E001'
        assert any('category not allowed' in failure
                   for failure in canary.score_required_statuses(changed, expectations, aliases))


def test_actual_mocked_two_transport_replay_and_unscored_topics_block(monkeypatch):
    rows = recorded_synthetic_rows(monkeypatch)
    result = canary.evaluate_canary(PIN, rows)
    assert result['state'] == 'qualified_synthetic_boundaries'
    assert len(result['scored_cases']) == 10
    assert result['private_context_qualification'] == 'not_established'
    assert result['investor_approval'] == 'not_established'
    assert result['untested_positive_categories'] == canary.UNTESTED_POSITIVE_CATEGORIES
    assert all(row['routing']['transport_count'] == 2 for row in rows)
    changed = recorded_synthetic_rows(monkeypatch, extra_market=True)
    blocked = canary.evaluate_canary(PIN, changed)
    assert blocked['state'] == 'blocked' and 'market_and_competition' in str(blocked['failures'])
    changed = copy.deepcopy(rows)
    changed[0]['routing']['transport_receipts'][0]['prompt_tokens'] = 2050
    assert canary.evaluate_canary(PIN, changed)['state'] == 'blocked'
    changed = copy.deepcopy(rows)
    changed[0]['raw_response'] += ' '
    assert canary.evaluate_canary(PIN, changed)['state'] == 'blocked'
    changed = copy.deepcopy(rows)
    changed[0]['routing'] = copy.deepcopy(rows[1]['routing'])
    blocked = canary.evaluate_canary(PIN, changed)
    assert blocked['state'] == 'blocked' and 'independently frozen' in blocked['detail']


def test_checkpoint_runner_preserves_raw_and_frozen_installed_pin(monkeypatch, tmp_path):
    from scripts import evaluate_diligence_semantic_canary as runner
    rows = recorded_synthetic_rows(monkeypatch)
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(runner, '_installed_digest', lambda name: PIN['digest'])
    root = tmp_path / 'fresh'
    assert runner.run(root, 'prepare')['state'] == 'prepared'
    receipt = rows[0]

    def invoke(model, task, instruction, payload, schema, attempts, save):
        assert receipt['input'] == payload and receipt['instruction'] == instruction
        attempts.append(copy.deepcopy(receipt))
        save()

    monkeypatch.setattr(runner, 'recorded_call', invoke)
    result = runner.run(root, 'advance')
    assert result['state'] == 'needs_call' and result['next_checkpoint'] == 2
    assert json.loads((root / 'checkpoint_1.json').read_text()) == receipt
    assert runner.run(root, 'verify')['next_checkpoint'] == 2
    monkeypatch.setattr(runner, '_installed_digest', lambda name: 'c' * 64)
    with pytest.raises(ValueError, match='installed model changed'):
        runner.run(root, 'advance')


def test_v2_disjoint_case_and_v1_contract_replay_remain_separate(monkeypatch, tmp_path):
    from scripts import evaluate_diligence_semantic_canary as runner
    old, new = canary.canary_fixture(canary.CONTRACT_V1), canary.canary_fixture(canary.CONTRACT_V2)
    changed = [index for index, (before, after) in enumerate(zip(old['cases'], new['cases'])) if before != after]
    assert changed == [3]
    assert old['cases'][3]['expected'] == new['cases'][3]['expected']
    assert 'eligible outlets' in old['cases'][3]['passage']
    assert 'Industry category annual growth rate' in new['cases'][3]['passage']
    old_rows = recorded_synthetic_rows(monkeypatch, contract=canary.CONTRACT_V1)
    assert canary.evaluate_canary(PIN, old_rows, contract=canary.CONTRACT_V1)['state'] == 'qualified_synthetic_boundaries'
    assert canary.evaluate_canary(PIN, old_rows, contract=canary.CONTRACT_V2)['state'] == 'blocked'
    assert all(row['task'] == canary.TASK_V1 for row in old_rows)
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(runner, '_installed_digest', lambda name: PIN['digest'])
    root = tmp_path / 'frozen_old'
    runner.run(root, 'prepare', contract=canary.CONTRACT_V1)
    result = runner.run(root, 'verify')
    assert result['contract'] == canary.CONTRACT_V1 and result['next_checkpoint'] == 1
    with pytest.raises(ValueError, match='contract cannot change'):
        runner.run(root, 'verify', contract=canary.CONTRACT_V2)


def test_full_thinking_profile_freezes_model_sampling_and_existing_defaults(monkeypatch, tmp_path):
    from scripts import evaluate_diligence_semantic_canary as runner
    pin = {'name': 'qwen3.5:9b', 'digest': 'c' * 64}
    profile = canary.FULL_THINKING_9B
    requests = canary.frozen_canary_requests(pin, profile=profile)
    assert all(request[2]['options']['reasoning_budget'] == 1024 and
               request[2]['options']['max_tokens'] == 1724 and
               request[2]['options']['context_tokens'] == 6144 and
               request[2]['options']['temperature'] == 1.0 for request in requests)
    assert all(request[2]['expected_sampling'] == canary.PROFILES[profile]['sampling'] for request in requests)
    historical = canary.frozen_canary_requests(PIN, contract=canary.CONTRACT_V1)
    assert all('profile' not in request[2] and request[2]['options'] == canary.OPTIONS for request in historical)
    for bad_pin, bad_contract, bad_profile in (
        (PIN, canary.CONTRACT_V2, profile), (pin, canary.CONTRACT_V1, profile),
        (pin, canary.CONTRACT_V2, 'unknown')):
        with pytest.raises(ValueError, match='exact model'):
            canary.frozen_canary_requests(bad_pin, contract=bad_contract, profile=bad_profile)
    rows = recorded_synthetic_rows(monkeypatch, pin=pin, profile=profile)
    result = canary.evaluate_canary(pin, rows, profile=profile)
    assert result['state'] == 'qualified_synthetic_boundaries' and result['profile'] == profile
    assert all(row['routing']['continuation_transport'] == 'raw_generate' for row in rows)
    assert canary.evaluate_canary(pin, rows)['state'] == 'blocked'
    changed = copy.deepcopy(rows)
    changed[0]['routing']['sampling']['top_p'] = 0.8
    assert canary.evaluate_canary(pin, changed, profile=profile)['state'] == 'blocked'
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(runner, '_installed_digest', lambda name: pin['digest'])
    root = tmp_path / 'fresh_9b'
    runner.run(root, 'prepare', pin['name'], profile=profile)
    assert runner.run(root, 'verify', pin['name'])['profile'] == profile
    with pytest.raises(ValueError, match='profile cannot change'):
        runner.run(root, 'verify', pin['name'], profile='unknown')
