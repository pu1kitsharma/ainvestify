"""Synthetic fixtures prove reward plumbing, not financial correctness."""
import pytest

from training.envs import CONTRACTS, evaluate, score_case, validate_splits


def fixture(env):
    checks = {name: {'kind': 'numeric', 'expected': 12, 'absolute_tolerance': 0.1,
                     'status': 'available'} for name in CONTRACTS[env]}
    return ({'case_id': 'synthetic-' + env, 'environment': env,
             'observations': {name: {'status': 'observed', 'value': 12} for name in checks}},
            {'case_id': 'synthetic-' + env, 'environment': env, 'checks': checks})


@pytest.mark.parametrize('env', CONTRACTS)
def test_complete_and_missing_contracts(env):
    prediction, key = fixture(env)
    assert score_case(prediction, key)['all_checks_matched']
    prediction['observations'] = {}
    result = score_case(prediction, key)
    assert result['reward'] == 0
    assert not result['investor_acceptance']
    assert all(x['status'] == 'missing_observation' for x in result['checks'].values())


def test_unsupported_key_is_not_a_pass_or_removed_denominator():
    prediction, key = fixture('E1')
    key['checks']['citations'] = {'status': 'unsupported'}
    assert score_case(prediction, key)['reward'] == 0.5
    del key['checks']['historical_cells']
    assert score_case(prediction, key)['reward'] == 0


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, '12'])
def test_nonfinite_and_nonnumeric_predictions_fail(value):
    prediction, key = fixture('E1')
    prediction['observations']['historical_cells']['value'] = value
    assert score_case(prediction, key)['checks']['historical_cells']['reward'] == 0


def test_bad_key_tolerance_rejected_even_without_prediction():
    prediction, key = fixture('E1')
    prediction['observations'] = {}
    key['checks']['historical_cells']['absolute_tolerance'] = -1
    with pytest.raises(ValueError):
        score_case(prediction, key)


def test_flags_precision_penalizes_hallucination_and_recall_penalizes_omission():
    prediction, key = fixture('E4')
    key['checks']['flags'] = {'kind': 'set', 'expected': ['unit', 'comparator'], 'status': 'available'}
    prediction['observations']['flags']['value'] = ['unit', 'invented']
    result = score_case(prediction, key)['checks']['flags']
    assert result['precision'] == result['recall'] == result['reward'] == 0.5
    prediction['observations']['flags']['value'] = ['unit', 'unit']
    assert score_case(prediction, key)['reward'] == 0


def test_missing_cases_included_and_duplicates_unexpected_rejected():
    prediction, key = fixture('E1')
    assert evaluate([], [key])['mean_reward'] == 0
    for predictions in ([prediction, prediction], [{'case_id': 'unknown'}]):
        with pytest.raises(ValueError):
            evaluate(predictions, [key])


def corpus():
    return [{'case_id': str(i), 'company_key': 'fictional-' + str(i),
             'sector': 'sector-' + str(i), 'evidence_family_ids': ['family-' + str(i)],
             'source_sha256': [str(i) * 64], 'private': False,
             'rights_status': 'public_training_approved', 'split': split}
            for i, split in enumerate(('train', 'valid', 'test'))]


def test_small_corpus_is_valid_plumbing_but_fails_coverage():
    manifest = validate_splits(corpus())
    assert not manifest['coverage_thresholds_met']
    assert not manifest['release_qualified']


@pytest.mark.parametrize('field', ['company_key', 'sector', 'evidence_family_ids', 'source_sha256'])
def test_split_leakage_for_each_identity(field):
    rows = corpus()
    rows[1][field] = rows[0][field]
    with pytest.raises(ValueError, match='Cross-split leakage'):
        validate_splits(rows)


def test_company_normalization_blocks_cosmetic_split_changes():
    rows = corpus()
    rows[1]['company_key'] = ' FICTIONAL-0 '
    with pytest.raises(ValueError, match='Cross-split leakage'):
        validate_splits(rows)


@pytest.mark.parametrize('patch', [{'private': True}, {'private': None}, {'rights_status': 'pending_review'}])
def test_private_or_unreviewed_sources_rejected(patch):
    rows = corpus()
    rows[0].update(patch)
    with pytest.raises(ValueError, match='rights-approved public'):
        validate_splits(rows)


def test_explicit_holdout_never_enters_public_training_corpus():
    with pytest.raises(ValueError, match='Private holdout'):
        validate_splits(corpus(), [' FICTIONAL-0 '])


def test_cli_preserves_existing_report(tmp_path):
    import subprocess
    import sys
    import json
    from pathlib import Path
    prediction, key = fixture('E1')
    inputs, answers, output = [tmp_path / name for name in ('predictions.json', 'keys.json', 'report.json')]
    inputs.write_text(json.dumps([prediction]))
    answers.write_text(json.dumps([key]))
    command = [sys.executable, 'scripts/evaluate_agentic_banker.py', '--predictions', str(inputs),
               '--answer-key', str(answers), '--output', str(output)]
    root = Path(__file__).resolve().parents[2]
    first = subprocess.run(command, cwd=root, capture_output=True)
    assert first.returncode == 0, first.stderr
    content = output.read_bytes()
    assert json.loads(content)['investor_acceptance'] is False
    assert output.stat().st_mode & 0o777 == 0o600
    assert subprocess.run(command, cwd=root, capture_output=True).returncode != 0
    assert output.read_bytes() == content
