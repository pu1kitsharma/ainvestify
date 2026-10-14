"""Mandatory grouped checkpoints preserve shared attempt arrays and bounds."""
from types import SimpleNamespace
import pytest
from agents.inference.model_authorship import digest
from agents.research import memo_source_unit_review_v3, memo_section_review, memo_section_units
from scripts import private_source_unit_worker as worker
from delivery import source_unit_content_stage as stage
from tests.research.test_private_source_unit_worker_v2 import fixture as previous_fixture, invoke


def fixture(root, monkeypatch, section_contract=None):
    request, calls = previous_fixture(root, monkeypatch)
    request['flow_contract'] = worker.FLOW_V3
    if section_contract is not None:
        request['section_author_contract'] = section_contract
    worker._write(root, 'content_request.json', {**request, 'digest': digest(request)})
    groups = ['recommendation', 'u0', 'u1']
    monkeypatch.setattr(memo_source_unit_review_v3, 'frozen_requests', lambda *args: [(key, None, None, None) for key in groups])
    def reviewer(keys, kind, rows, save, model, memo):
        if len(rows) > 6: raise ValueError('Shared review call cap exceeded')
        for index, row in enumerate(rows):
            if row != {'group': keys[index], 'response_hash': digest(keys[index])}:
                raise ValueError('Shared group response changed')
        if len(rows) < len(keys) and model is not None:
            key = keys[len(rows)]
            calls.append(kind + ':' + key)
            rows.append({'group': key, 'response_hash': digest(key)})
            save()
        if len(rows) < len(keys):
            return {'state': 'needs_resume', 'batch_id' if kind == 'source_review' else 'pending_field': keys[len(rows)]}
        return {'state': 'accepted', 'coverage': keys,
                'response_hash': digest(rows), 'request_digest': digest(keys)}
    monkeypatch.setattr(worker.review_engine, 'run_review', lambda memo, sources, proof, authored, apin, rpin, rows, save, model, budget:
        reviewer(groups, 'source_review', rows, save, model, authored['memo']))
    monkeypatch.setattr(memo_section_review, 'run_review', lambda memo, sources, authored, apin, rpin, rows, save, model, budget:
        reviewer(list(memo_section_units.FIELDS), 'section_review', rows, save, model, authored['memo']))
    return request, calls


@pytest.mark.parametrize("section_contract", [None, "memo-section-units-author-v2", "memo-section-units-author-v3"])
def test_all_eleven_checkpoints_add_only_their_own_group_and_replay(tmp_path, monkeypatch, section_contract):
    request, calls = fixture(tmp_path, monkeypatch, section_contract)
    assert worker.PHASES_V3 == stage.PHASES_V3
    for number, phase in enumerate(worker.PHASES_V3):
        result = invoke(tmp_path, phase)
        assert len(calls) == number + 1
        if number < 10:
            assert result['state'] == 'needs_resume'
            assert result['next_phase'] == worker.PHASES_V3[number + 1]
        else:
            assert result['state'] == 'accepted'
    record = worker.load_source_unit_revision(tmp_path)
    assert len(record['source_unit_review_attempts']) == 3
    assert len(record['memo_section_review_attempts']) == 5
    memo, gate = worker.replay_source_unit_revision(request['memo'], request['sources'], record)
    assert gate == result['content_review'] and gate['contract'] == worker.FLOW_V3
    assert gate.get('section_author_contract') == section_contract
    assert len(calls) == 11  # All prior reviewed groups replay without inference.
    assert gate['final_memo_digest'] == digest(memo)


@pytest.mark.parametrize('skipped', ['source_unit_review_u0', 'memo_section_review_business_and_market'])
def test_skip_unfinished_group_is_blocked_before_another_call(tmp_path, monkeypatch, skipped):
    _, calls = fixture(tmp_path, monkeypatch)
    stop = 2 if skipped.startswith('source_') else 6
    for phase in worker.PHASES_V3[:stop]: invoke(tmp_path, phase)
    count = len(calls)
    result = invoke(tmp_path, skipped)
    assert result['state'] == 'blocked' and 'skipped an unfinished' in result['detail']
    assert len(calls) == count


def test_review_engines_keep_shared_six_attempt_ceiling(monkeypatch):
    budget = SimpleNamespace(calls=0, max_calls=6, remaining=lambda: 105)
    monkeypatch.setattr(memo_source_unit_review_v3, 'frozen_requests', lambda *args:
        [('recommendation', {'contract': memo_source_unit_review_v3.CONTRACT_V5}, None, {})])
    with pytest.raises(ValueError, match='finite call plan'):
        memo_source_unit_review_v3.run_review({}, [], {}, {}, {}, {},
            [{'task': memo_source_unit_review_v3.TASK_V5}] * 7, lambda: None, None, budget)
    monkeypatch.setattr(memo_section_review, 'frozen_requests', lambda *args: [])
    with pytest.raises(ValueError, match='six-call plan'):
        memo_section_review.run_review({}, [], {}, {}, {},
            [{'task': memo_section_review.TASK}] * 7, lambda: None, None, budget)


@pytest.mark.parametrize('cached_author', ['valid', 'missing', 'changed'])
def test_cached_source_author_checkpoint_with_existing_reviews_never_infers(tmp_path, monkeypatch, cached_author):
    _, calls = fixture(tmp_path, monkeypatch)
    for phase in worker.PHASES_V3[:5]:
        result = invoke(tmp_path, phase)
        assert result['state'] == 'needs_resume'
    count = len(calls)
    file = tmp_path / 'source_unit_author_attempts.json'
    if cached_author == 'missing':
        worker._write(tmp_path, file.name, [])
    elif cached_author == 'changed':
        rows = worker._load(tmp_path, file.name)
        rows[0]['response_hash'] = 'e' * 64
        worker._write(tmp_path, file.name, rows)
    result = invoke(tmp_path, 'source_unit_author')
    if cached_author == 'valid':
        assert result['state'] == 'needs_resume'
        assert result['next_phase'] == 'source_unit_review_recommendation'
    elif cached_author == 'missing':
        assert result['state'] == 'needs_resume' and result['next_phase'] == 'source_unit_author'
    else:
        assert result['state'] == 'blocked'
    assert len(calls) == count
