import pytest

from training.envs import (adapter_destination_ok, assert_deals_unseen, mix_private_examples,
                           split_training_rows)


def row(deal, private=False):
    return {'deal_id': deal, 'company_key': deal, 'private': private}


def test_leave_one_deal_out_excludes_private_heldout_and_lists_trained_deals():
    pub, priv, excluded, trained = split_training_rows(
        [row('a'), row('b')], [row('Omega', True), row('Sigma', True)], held_out_deals=['sigma'])
    assert [r['deal_id'] for r in priv] == ['Omega'] and [r['deal_id'] for r in excluded] == ['Sigma']
    assert trained == ['a', 'b', 'omega']


def test_heldout_deal_in_public_training_rows_is_an_error_not_silent_drop():
    with pytest.raises(ValueError):
        split_training_rows([row('a')], [], held_out_deals=['A'])


def test_private_flag_confusion_rejected():
    with pytest.raises(ValueError):
        split_training_rows([row('a', True)], [])
    with pytest.raises(ValueError):
        split_training_rows([row('a')], [row('b', False)])


def test_adapter_never_scored_on_trained_deal():
    assert_deals_unseen(['a', 'b'], ['c'])
    with pytest.raises(ValueError):
        assert_deals_unseen(['a', 'B'], ['b'])


@pytest.mark.parametrize('n_public', [0, 5, 9, 10, 30, 100])
def test_private_share_never_exceeds_ten_percent(n_public):
    mixed, stats = mix_private_examples([{'p': i} for i in range(n_public)], [{'q': i} for i in range(7)], upweight=5)
    assert stats['private_used'] / max(len(mixed), 1) <= 0.10
    assert len(mixed) == n_public + stats['private_used']


def test_upweight_repeats_private_examples_when_cap_allows_and_keeps_distinct_first():
    mixed, stats = mix_private_examples([{'p': i} for i in range(90)], [{'q': 1}, {'q': 2}], upweight=3)
    assert stats['private_used'] == 6 and stats['distinct_private_used'] == 2
    mixed, stats = mix_private_examples([{'p': i} for i in range(18)], [{'q': 1}, {'q': 2}, {'q': 3}], upweight=3)
    assert stats['private_used'] == 2 and stats['distinct_private_used'] == 2  # distinct before copies


def test_cap_cannot_be_raised_above_ten_percent():
    with pytest.raises(ValueError):
        mix_private_examples([{}], [{}], cap=0.2)
    with pytest.raises(ValueError):
        mix_private_examples([{}], [{}], upweight=0)


def test_private_adapters_only_under_ignored_private_roots(tmp_path):
    root = tmp_path
    for ok in ('runtime_qualification/agentic_banker/x', 'evals/agentic_banker/private/x'):
        adapter_destination_ok(root / ok, trained_on_private=True, repo_root=root)
    for bad in ('models/adapters/run1', 'models/adapters', 'evals/agentic_banker/ws-c/x', 'other'):
        with pytest.raises(ValueError):
            adapter_destination_ok(root / bad, trained_on_private=True, repo_root=root)
    with pytest.raises(ValueError):
        adapter_destination_ok(tmp_path.parent / 'outside', trained_on_private=True, repo_root=root)
    adapter_destination_ok(root / 'models/adapters/run1', trained_on_private=False, repo_root=root)


def test_symlink_into_lfs_path_is_resolved(tmp_path):
    (tmp_path / 'models/adapters').mkdir(parents=True)
    (tmp_path / 'runtime_qualification').mkdir()
    (tmp_path / 'runtime_qualification/link').symlink_to(tmp_path / 'models/adapters')
    with pytest.raises(ValueError):
        adapter_destination_ok(tmp_path / 'runtime_qualification/link/a', trained_on_private=True, repo_root=tmp_path)
