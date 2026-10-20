import json
import pytest

from training.expert_iteration import run_iteration
from tests.envs.test_rewards import corpus, fixture


def rows():
    result = corpus()
    for row in result:
        prediction, key = fixture('E4')
        key['case_id'] = row['case_id']
        row['answer_key'] = key
        row['input'] = {'case_id': row['case_id'], 'environment': 'E4',
                        'source_text': 'independent synthetic source ' + row['case_id']}
    return result


def sampler(payload):
    prediction, _ = fixture('E4')
    prediction['case_id'] = payload['case_id']
    return {'prediction': prediction, 'trajectory': [{'role': 'assistant', 'content': 'synthetic response'}]}


def test_full_injected_dry_run_never_claims_mock_adapter_is_trained(tmp_path):
    offered = []
    def train(selected):
        offered.extend(selected)
        return {'weights_trained': True, 'adapter': 'fictional-mock-adapter'}
    def evaluate(declaration, inputs):
        assert declaration['weights_trained'] is True
        assert all('answer_key' not in payload for payload in inputs)
        return [sampler(payload)['prediction'] for payload in inputs]
    output = tmp_path / 'iteration'
    result = run_iteration(rows(), output, sampler=sampler, trainer=train, evaluator=evaluate)
    assert result['status'] == 'dry_run_plumbing_complete'
    assert result['weights_trained'] is result['adapter_verified'] is False
    assert result['memorisation_probe'] == 'unrun'
    assert len(offered) == 1 and offered[0]['case_id'] == '0'
    assert json.loads((output / 'heldout_report.json').read_text())['mean_reward'] == 1
    assert (output / 'sample-000000.json').exists()
    with pytest.raises(FileExistsError):
        run_iteration(rows(), output, sampler=sampler)


def test_private_or_split_leakage_blocks_before_sampler_or_output(tmp_path):
    for changes in ({'private': True}, {'sector': 'sector-1'}):
        data = rows()
        data[0].update(changes)
        output = tmp_path / ('private' if 'private' in changes else 'sector')
        with pytest.raises(ValueError):
            run_iteration(data, output, sampler=lambda _: pytest.fail('callback should not run'))
        assert not output.exists()


def test_rejected_samples_retained_and_not_sent_to_trainer(tmp_path):
    def wrong(payload):
        sample = sampler(payload)
        sample['prediction']['observations'] = {}
        return sample
    result = run_iteration(rows(), tmp_path / 'reject', sampler=wrong,
                           minimum_reward=0, trainer=lambda _: pytest.fail('unsupported checks selected'))
    assert result['samples'] == 1 and result['selected'] == 0
    assert (tmp_path / 'reject' / 'sample-000000.json').exists()


def test_invalid_prediction_is_retained_with_failure(tmp_path):
    def malformed(payload):
        sample = sampler(payload)
        sample['prediction']['case_id'] = 'wrong'
        return sample
    output = tmp_path / 'failed'
    with pytest.raises(ValueError):
        run_iteration(rows(), output, sampler=malformed)
    assert (output / 'sample-000000.json').exists()
    assert json.loads((output / 'failure.json').read_text())['status'] == 'dry_run_failed'


@pytest.mark.parametrize('kwargs', [{'dry_run': False}, {'max_samples': 0}, {'samples_per_case': 101},
                                     {'max_samples': 1, 'samples_per_case': 2}, {'minimum_reward': float('nan')}])
def test_invalid_bounds_block_execution(tmp_path, kwargs):
    with pytest.raises(ValueError):
        run_iteration(rows(), tmp_path / 'invalid', sampler=lambda _: pytest.fail('callback should not run'), **kwargs)


def test_renamed_input_cannot_leak_across_splits_before_callback(tmp_path):
    data = rows()
    # Company/family/hash identities all differ, but actual supplied tasks match.
    data[1]['input'] = {**data[0]['input'], 'case_id': data[1]['case_id'],
                        'company_key': 'different-company', 'split': 'valid'}
    output = tmp_path / 'leaked'
    with pytest.raises(ValueError, match='canonical task input'):
        run_iteration(data, output, sampler=lambda _: pytest.fail('callback should not run'))
    assert not output.exists()


def test_canonical_key_order_does_not_disguise_leakage(tmp_path):
    data = rows()
    data[0]['input']['facts'] = {'b': 2, 'a': 1}
    data[1]['input'] = dict(reversed(list(data[0]['input'].items())))
    data[1]['input']['case_id'] = data[1]['case_id']
    data[1]['input']['facts'] = {'a': 1, 'b': 2}
    with pytest.raises(ValueError, match='canonical task input'):
        run_iteration(data, tmp_path / 'leaked', sampler=sampler)


def test_repeated_input_within_train_split_is_permitted(tmp_path):
    from copy import deepcopy
    data = rows()
    duplicate = deepcopy(data[0])
    duplicate['case_id'] = 'same-train-task'
    duplicate['answer_key']['case_id'] = duplicate['case_id']
    duplicate['input']['case_id'] = duplicate['case_id']
    data.append(duplicate)
    result = run_iteration(data, tmp_path / 'same-split', sampler=sampler)
    assert result['samples'] == 2
