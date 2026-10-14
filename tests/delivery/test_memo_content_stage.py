"""Production gate blocks rendering and reuses exact accepted revisions."""
import json
import stat
import pytest

from agents.inference.model_authorship import digest
from delivery import memo_content_stage as stage
from tests.research.test_memo_causal_review import sample


def setup(tmp_path, monkeypatch):
    memo, sources = sample()
    profile = {'profiles': {'author': 'qwen3:14b', 'challenge': 'qwen3.5:9b',
                           'review': 'qwen3.5:9b', 'corrector': 'qwen3:14b'},
               'memo_role_model_digests': {'author': 'a' * 64, 'challenge': 'b' * 64}}
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3:14b': 'a' * 64,
                                                     'qwen3.5:9b': 'b' * 64})
    return {'memo': memo}, sources, profile


def test_resume_freezes_private_request_and_six_call_budget(tmp_path, monkeypatch):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    def worker(command, root, **options):
        assert options['local_model'] is True
        assert json.loads((root / 'content_budget.json').read_text())['max_calls'] == 6
        (root / 'content_result.json').write_text(json.dumps({'state': 'needs_resume'}))
    monkeypatch.setattr(stage, 'run_private', worker)
    result = stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)
    assert result['state'] == 'needs_resume'
    root = tmp_path / 'content_v3'
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / 'content_request.json').stat().st_mode) == 0o600
    assert accepted['memo'] == setup(tmp_path, monkeypatch)[0]['memo']


def test_blocked_result_never_repeats_inference(tmp_path, monkeypatch):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    calls = []
    def worker(command, root, **options):
        calls.append(1)
        (root / 'content_result.json').write_text(json.dumps({'state': 'blocked', 'reason': 'unsupported'}))
    monkeypatch.setattr(stage, 'run_private', worker)
    assert stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)['state'] == 'blocked'
    monkeypatch.setattr(stage, '_inventory', lambda: (_ for _ in ()).throw(AssertionError('cached block')))
    assert stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)['state'] == 'blocked'
    assert calls == [1]


def test_accepted_result_requires_exact_replay_and_skips_inference(tmp_path, monkeypatch):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    calls = []
    def worker(command, root, **options):
        calls.append(1)
        (root / 'content_result.json').write_text(json.dumps(
            {'state': 'accepted', 'final_memo_digest': digest(accepted['memo'])}))
    monkeypatch.setattr(stage, 'run_private', worker)
    monkeypatch.setattr(stage, '_load_revision', lambda root: {'frozen': 'record'})
    monkeypatch.setattr(stage.repair, 'replay_content_revision',
                        lambda memo, sources, revision: (memo, {'state': 'accepted'}))
    result = stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)
    assert result['state'] == 'accepted' and result['independent_review'] == 'pending'
    monkeypatch.setattr(stage, '_inventory', lambda: (_ for _ in ()).throw(AssertionError('cached pass')))
    assert stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)['state'] == 'accepted'
    assert calls == [1]
    (tmp_path / 'content_v3' / 'content_result.json').write_text(json.dumps(
        {'state': 'accepted', 'final_memo_digest': 'f' * 64}))
    assert stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)['reason'] == 'memo_content_result_digest_changed'


def test_changed_source_or_memo_cannot_reuse_request(tmp_path, monkeypatch):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(stage, 'run_private', lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)
    changed = {**accepted, 'memo': {**accepted['memo'], 'recommendation': 'decline'}}
    result = stage.run_content_pass(tmp_path, changed, sources, profile, timeout=30)
    assert result['reason'] == 'memo_content_request_changed'


def test_three_content_pass_cap_is_terminal(tmp_path, monkeypatch):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    calls = []
    def worker(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()
    monkeypatch.setattr(stage, 'run_private', worker)
    for _ in range(3):
        assert stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)['state'] == 'needs_resume'
    result = stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30)
    assert result['reason'] == 'bounded_memo_content_passes_exhausted'
    assert len(calls) == 3


def test_material_options_use_revised_memo_and_bind_lineage(tmp_path, monkeypatch):
    from delivery import material_stage
    from agents.research import investment_memo
    from agents.research.investment_memo import Memo
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    (tmp_path / 'result.json').write_text(json.dumps({'state': 'accepted', 'accepted': accepted}))
    (tmp_path / 'request.json').write_text(json.dumps({'sources': sources}))
    (tmp_path / 'attempts.json').write_text('[]')
    (tmp_path / 'model.json').write_text(json.dumps(profile))
    updated = {**accepted['memo'], 'recommendation': 'decline'}
    lineage, revision = {'state': 'accepted', 'final_memo_digest': digest(updated)}, {'frozen': 'revision'}
    monkeypatch.setattr(stage, 'replay_content_gate',
                        lambda *args: (Memo.model_validate(updated), revision, lineage))
    def renderer(accepted_input, sources, attempts, projection=None, content_revision=None):
        assert accepted_input == accepted
        assert content_revision == revision
        return [('Revised rationale', 'Recorded revised model text.', [])]
    monkeypatch.setattr(investment_memo, 'renderable_sections', renderer)
    memo = {'sections': [['Revised rationale', 'Recorded revised model text.', []]],
            'recommendation': 'decline', 'content_review': lineage,
            'content_revision_path': str(tmp_path / 'content_v3')}
    assert material_stage._accepted_memo_for_material(tmp_path, memo)['memo'] == updated
    import pytest
    with pytest.raises(ValueError, match='lineage differs'):
        material_stage._accepted_memo_for_material(tmp_path, {**memo, 'recommendation': 'advance_to_diligence'})
    original_digest = material_stage._memo_digest(memo)
    assert material_stage._memo_digest({**memo, 'content_review': {'state': 'accepted'}}) != original_digest


def test_fresh_material_boundary_rejects_stripped_gate(tmp_path):
    import pytest
    from delivery import material_stage
    fresh = {'checkpoint': {'workflow_contract': 'room-v27-rationale-content-gate'}}
    with pytest.raises(ValueError, match='require accepted memo content review lineage'):
        material_stage._require_content_gate(fresh, tmp_path, {'state': 'accepted'})
    # Saved old jobs remain replayable, until a content gate is created.
    material_stage._require_content_gate({'checkpoint': {}}, tmp_path, {'state': 'accepted'})
    (tmp_path / 'content_v3').mkdir()
    with pytest.raises(ValueError, match='require accepted memo content review lineage'):
        material_stage._require_content_gate({'checkpoint': {}}, tmp_path, {'state': 'accepted'})
    with pytest.raises(ValueError, match='cannot omit'):
        material_stage._accepted_memo_for_material(tmp_path, {'state': 'accepted'})


@pytest.mark.parametrize("version", [4, 5])
def test_scope_gate_is_separate_and_freezes_review_and_repair_contract(tmp_path, monkeypatch, version):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(stage, 'run_private', lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    result = stage.run_content_pass(tmp_path, accepted, sources, profile,
                                    timeout=30, review_version=version)
    assert result['state'] == 'needs_resume'
    request = json.loads((tmp_path / f'content_v{version}' / 'content_request.json').read_text())
    assert request['review_contract']['version'] == f'memo-content-review-v{version}'
    assert request['author_pin']['repair_contract'] == 'memo-content-repair-v4'
    assert not (tmp_path / 'content_v3').exists()
    request['author_pin'].pop('repair_contract')
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    (tmp_path / f'content_v{version}' / 'content_request.json').write_text(json.dumps(request))
    assert stage.run_content_pass(tmp_path, accepted, sources, profile,
                                 timeout=30, review_version=version)['reason'] == 'memo_content_request_changed'


def test_scope_material_boundary_cannot_use_historical_gate(tmp_path, monkeypatch):
    import pytest
    from delivery import material_stage
    job = {'checkpoint': {'workflow_contract': 'room-v28-scope-content-gate'}}
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    memo = {'content_review': {'state': 'accepted'}, 'content_review_version': 3}
    with pytest.raises(ValueError, match='frozen content gate version'):
        material_stage._require_content_gate(job, tmp_path, memo)
    material_stage._require_content_gate(job, tmp_path, {**memo, 'content_review_version': 4})
    before = material_stage._memo_digest({**memo, 'content_review_version': 4,
                                         'content_revision_path': str(tmp_path / 'content_v4')})
    after = material_stage._memo_digest({**memo, 'content_review_version': 4,
                                        'content_revision_path': str(tmp_path / 'content_v3')})
    assert before != after


def test_scope_material_replays_version_and_exact_path(tmp_path, monkeypatch):
    import pytest
    from delivery import material_stage
    from agents.research import investment_memo
    from agents.research.investment_memo import Memo
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    for name, value in [('result', {'state': 'accepted', 'accepted': accepted}),
                        ('request', {'sources': sources}), ('attempts', []), ('model', profile)]:
        (tmp_path / f'{name}.json').write_text(json.dumps(value))
    lineage = {'state': 'accepted'}
    revision = {'frozen': 'scope-revision'}
    def replay(*args, review_version):
        assert review_version == 4
        return Memo.model_validate(accepted['memo']), revision, lineage
    monkeypatch.setattr(stage, 'replay_content_gate', replay)
    monkeypatch.setattr(investment_memo, 'renderable_sections', lambda *args, **kwargs: [])
    memo = {'sections': [], 'recommendation': accepted['memo']['recommendation'],
            'content_review': lineage, 'content_review_version': 4,
            'content_revision_path': str(tmp_path / 'content_v4')}
    assert material_stage._accepted_memo_for_material(tmp_path, memo)['memo'] == accepted['memo']
    with pytest.raises(ValueError, match='lineage differs'):
        material_stage._accepted_memo_for_material(tmp_path, {**memo,
            'content_revision_path': str(tmp_path / 'content_v3')})


def test_blind_material_boundary_rejects_scope_gate_downgrade(tmp_path, monkeypatch):
    from delivery import material_stage
    job = {'checkpoint': {'workflow_contract': 'room-v29-blind-scope-content-gate'}}
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    memo = {'content_review': {'state': 'accepted'}}
    for version in (3, 4):
        with pytest.raises(ValueError, match='frozen content gate version'):
            material_stage._require_content_gate(job, tmp_path, {**memo, 'content_review_version': version})
    material_stage._require_content_gate(job, tmp_path, {**memo, 'content_review_version': 5})
    before = material_stage._memo_digest({**memo, 'content_review_version': 5,
                                         'content_revision_path': str(tmp_path / 'content_v5')})
    after = material_stage._memo_digest({**memo, 'content_review_version': 4,
                                        'content_revision_path': str(tmp_path / 'content_v5')})
    assert before != after


@pytest.mark.parametrize('history', [
    None, [], [{'pass': number, 'state': 'needs_resume' if number < 4 else 'accepted'}
               for number in range(1, 5)],
    [{'pass': 2, 'state': 'accepted'}],
    [{'pass': True, 'state': 'accepted'}],
    [{'pass': 1, 'state': 'started'}, {'pass': 2, 'state': 'accepted'}],
    [{'pass': 1, 'state': 'accepted'}, {'pass': 2, 'state': 'accepted'}],
    [{'pass': 1, 'state': 'blocked'}, {'pass': 2, 'state': 'accepted'}],
    [{'pass': 1, 'state': 'needs_resume'}],
])
def test_blind_terminal_acceptance_requires_completed_bounded_history(tmp_path, monkeypatch, history):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    def worker(command, root, **options):
        (root / 'content_result.json').write_text(json.dumps({'state': 'needs_resume'}))
    monkeypatch.setattr(stage, 'run_private', worker)
    stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30, review_version=5)
    root = tmp_path / 'content_v5'
    (root / 'content_result.json').write_text(json.dumps(
        {'state': 'accepted', 'final_memo_digest': digest(accepted['memo'])}))
    if history is None:
        (root / 'content_passes.json').unlink()
    else:
        (root / 'content_passes.json').write_text(json.dumps(history))
    revision = {'review_contract': {'version': 'memo-content-review-v5',
                'source_characterization': {'result': {'state': 'accepted',
                    'contract': 'rationale-source-characterization-v2'}}}}
    monkeypatch.setattr(stage, '_load_revision', lambda root: revision)
    monkeypatch.setattr(stage, '_inventory', lambda: (_ for _ in ()).throw(AssertionError('No inference on replay')))
    assert stage.run_content_pass(tmp_path, accepted, sources, profile,
        timeout=30, review_version=5)['reason'] == 'memo_content_production_proof_invalid'
    with pytest.raises(ValueError, match='pass'):
        stage.replay_content_gate(tmp_path, accepted, sources, profile, review_version=5)


@pytest.mark.parametrize('source_version', ['rationale-source-characterization-v1',
                                           'rationale-source-characterization-v2'])
def test_blind_terminal_acceptance_requires_current_characterization(tmp_path, monkeypatch, source_version):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    def worker(command, root, **options):
        (root / 'content_result.json').write_text(json.dumps({'state': 'needs_resume'}))
    monkeypatch.setattr(stage, 'run_private', worker)
    stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30, review_version=5)
    root = tmp_path / 'content_v5'
    (root / 'content_result.json').write_text(json.dumps(
        {'state': 'accepted', 'final_memo_digest': digest(accepted['memo'])}))
    (root / 'content_passes.json').write_text(json.dumps([
        {'pass': 1, 'state': 'worker_error'}, {'pass': 2, 'state': 'needs_resume'},
        {'pass': 3, 'state': 'accepted'}]))
    revision = {'review_contract': {'version': 'memo-content-review-v5',
                'source_characterization': {'result': {'state': 'accepted', 'contract': source_version}}}}
    monkeypatch.setattr(stage, '_load_revision', lambda root: revision)
    monkeypatch.setattr(stage.repair, 'replay_content_revision',
                        lambda memo, sources, revision: (stage.Memo.model_validate(memo), {'state': 'accepted'}))
    monkeypatch.setattr(stage, '_inventory', lambda: (_ for _ in ()).throw(AssertionError('No inference on replay')))
    result = stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30, review_version=5)
    if source_version.endswith('v1'):
        assert result['reason'] == 'memo_content_production_proof_invalid'
        with pytest.raises(ValueError, match='current source characterization'):
            stage.replay_content_gate(tmp_path, accepted, sources, profile, review_version=5)
    else:
        assert result['state'] == 'accepted'
        assert stage.replay_content_gate(tmp_path, accepted, sources, profile, review_version=5)[1] == revision


@pytest.mark.parametrize("repair_contract", ["memo-content-repair-v5", "memo-content-repair-v6"])
def test_author_scope_request_freezes_repair_v5_and_cannot_reuse_v29(tmp_path, monkeypatch, repair_contract):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(stage, 'run_private', lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30,
                           review_version=5, repair_contract=repair_contract)
    request = json.loads((tmp_path / 'content_v5' / 'content_request.json').read_text())
    assert request['author_pin']['repair_contract'] == repair_contract
    assert request['review_contract']['version'] == 'memo-content-review-v5'
    assert stage.run_content_pass(tmp_path, accepted, sources, profile, timeout=30,
                                 review_version=5)['reason'] == 'memo_content_request_changed'
    (tmp_path / 'content_v5' / 'content_result.json').write_text(json.dumps({'state': 'accepted'}))
    with pytest.raises(ValueError, match='exact accepted memo content gate'):
        stage.replay_content_gate(tmp_path, accepted, sources, profile, review_version=5)


@pytest.mark.parametrize("workflow, repair_contract", [("room-v30-author-scope-content-gate", "memo-content-repair-v5"),
                                                       ("room-v31-blind-author-content-gate", "memo-content-repair-v6")])
def test_author_scope_material_requires_frozen_repair_v5(tmp_path, monkeypatch, workflow, repair_contract):
    from delivery import material_stage
    job = {'checkpoint': {'workflow_contract': workflow}}
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    memo = {'content_review': {'state': 'accepted'}, 'content_review_version': 5}
    for prior_contract in (None, 'memo-content-repair-v4'):
        with pytest.raises(ValueError, match='frozen content repair contract'):
            material_stage._require_content_gate(job, tmp_path,
                {**memo, **({'content_repair_contract': prior_contract} if prior_contract else {})})
    updated = {**memo, 'content_repair_contract': repair_contract}
    material_stage._require_content_gate(job, tmp_path, updated)
    assert material_stage._memo_digest(updated) != material_stage._memo_digest(memo)
    with pytest.raises(ValueError, match='frozen content repair contract'):
        material_stage._require_content_gate(
            {'checkpoint': {'workflow_contract': 'room-v29-blind-scope-content-gate'}}, tmp_path, updated)


def test_author_scope_repair_contract_requires_blind_review():
    for version in (3, 4):
        with pytest.raises(ValueError, match='does not match'):
            stage.content_repair_contract(version, 'memo-content-repair-v5')
