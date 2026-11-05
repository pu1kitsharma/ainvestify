"""Private intake classifies assets without creating labels or losing holdouts."""
import json

import pytest

from scripts.audit_training_assets import audit
from scripts.build_memo_gold_sft import build
from tests.research.test_memo_gold_sft import _row


def _write(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


def test_intake_separates_logs_holdouts_rights_and_target_checks(tmp_path):
    private, source = tmp_path / 'private', tmp_path / 'private' / 'import'
    source.mkdir(parents=True)
    candidate = _row(1, 'test')
    candidate['provenance'].update(rights_status='private_training_approved',
                                   adjudication='pending', reviewer_ids=[])
    rows = [candidate, {'origin': {}, 'reason': 'recorded_failure'},
            {'case_id': 'synthetic-case', 'environment': 'tool-test',
             'input': {'secret': 'never-export-this-private-content'},
             'rights_status': 'synthetic_fixture', 'split': 'train'},
            {'case_id': 'synthetic-case', 'checks': {'hidden': 'hidden-answer-key'}},
            {'messages': [{'role': 'assistant', 'content': 'private-unapproved-answer'}]}]
    _write(source / 'train.jsonl', rows)
    result = audit(source, private / 'report', private_root=private)
    assert result['rows'] == 5
    assert result['kinds'] == {'memo_candidate': 1, 'exclusion_log': 1,
                               'task_fixture': 1, 'scorer_answer_key': 1,
                               'unqualified_chat_or_text': 1}
    assert result['explicit_splits'] == {'test': 1, 'unspecified': 3, 'train': 1}
    assert result['memo_target_checks'] == {'runtime_target_pass': 1}
    assert result['rights'] == {'approved': 1, 'not_approved': 4}
    assert result['memo_holdout_rows'] == 1
    assert result['weight_update_eligible_rows'] == 0
    emitted = ''.join(path.read_text() for path in (private / 'report').iterdir())
    for secret in ('never-export-this-private-content', 'hidden-answer-key',
                   'private-unapproved-answer', candidate['company_key'],
                   candidate['source_bundle'][0]['passage']):
        assert secret not in emitted
    with pytest.raises(ValueError, match='must be new'):
        audit(source, private / 'report', private_root=private)


def test_intake_blocks_training_on_a_family_used_by_any_holdout(tmp_path):
    private, source = tmp_path / 'private', tmp_path / 'private' / 'import'
    source.mkdir(parents=True)
    train, heldout = _row(1, 'train'), _row(2, 'test')
    heldout['evidence_family_ids'] = train['evidence_family_ids']
    _write(source / 'assets.jsonl', [train, heldout])
    result = audit(source, private / 'report', private_root=private)
    assert result['cross_split_lineage_rows'] == 2
    assert result['weight_update_eligible_rows'] == 0
    assert result['review']['approved_two_reviewers'] == 2


def test_private_export_uses_explicit_external_root_and_keeps_gold_gates(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    rows = [_row(1, 'train'), _row(2, 'valid'), _row(3, 'test')]
    for row in rows:
        row['provenance']['rights_status'] = 'private_training_approved'
    source = private / 'reviewed.jsonl'
    _write(source, rows)
    result = build(source, private / 'export', private_root=private)
    assert result['counts'] == {'train': 1, 'valid': 1, 'test': 1}
    assert not result['weights_trained'] and not result['release_qualified']
    rows[0]['provenance']['reviewer_ids'] = []
    _write(source, rows)
    with pytest.raises(ValueError, match='two distinct reviewer'):
        build(source, private / 'other-export', private_root=private)


def test_private_root_rejects_repository_and_symlink_escape(tmp_path, monkeypatch):
    from scripts import build_memo_gold_sft as gold
    repo, private, elsewhere = tmp_path / 'repo', tmp_path / 'private', tmp_path / 'elsewhere'
    for folder in (repo, private, elsewhere):
        folder.mkdir()
    monkeypatch.setattr(gold, 'ROOT', repo)
    (private / 'escape').symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match='must stay under'):
        build(private / 'escape' / 'missing', private / 'out', private_root=private)
    with pytest.raises(ValueError, match='outside the repository'):
        build(repo / 'missing', repo / 'out', private_root=repo)
    with pytest.raises(ValueError, match='outside the repository'):
        build(repo / 'missing', repo / 'out', private_root=tmp_path)


def test_private_gold_cannot_use_legacy_checkout_default(tmp_path, monkeypatch):
    from scripts import build_memo_gold_sft as gold
    monkeypatch.setattr(gold, 'PRIVATE_DATA', tmp_path)
    row = _row(1, 'train')
    row['provenance']['rights_status'] = 'private_training_approved'
    _write(tmp_path / 'reviewed.jsonl', [row])
    with pytest.raises(ValueError, match='explicit outside-Git private root'):
        build(tmp_path / 'reviewed.jsonl', tmp_path / 'export')
    assert not (tmp_path / 'export').exists()
