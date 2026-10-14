"""Delivery budget/lineage controls; inference and financial judgment are separate."""
import json
import sys
from types import SimpleNamespace
import pytest
from agents.inference.model_authorship import digest
from agents.research.investment_memo import Memo
from delivery import source_unit_content_stage as stage
from tests.delivery.test_memo_content_stage import setup


def fixture(tmp_path, monkeypatch):
    accepted, sources, profile = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3.5:9b': 'b' * 64})
    def load(root):
        request = json.loads((root / 'content_request.json').read_text())
        return {'contract': request['flow_contract'], 'request_digest': request['digest'],
                **({'author_contract': request['author_contract']} if 'author_contract' in request else {}),
                **({'section_author_contract': request['section_author_contract']} if 'section_author_contract' in request else {}),
                **{key: request[key] for key in
                    (('characterizer_pin', 'author_pin', 'reviewer_pin', 'core_author_pin') if request['flow_contract'] == stage.FLOW_V4 else ('characterizer_pin', 'author_pin', 'reviewer_pin'))}}
    engine = SimpleNamespace(load_source_unit_revision=load,
        replay_source_unit_revision=lambda memo, sources, record:
            (Memo.model_validate(memo).model_dump(mode='json'), {'state': 'accepted'}))
    monkeypatch.setitem(sys.modules, 'scripts.private_source_unit_worker', engine)
    return accepted, sources, profile


@pytest.mark.parametrize("author_contract", [None, "memo-source-unit-author-v2", "memo-source-unit-author-v3", "memo-source-unit-author-v4", "memo-source-unit-author-v5", "memo-source-unit-author-v6"])
def test_exactly_three_separate_private_phases_and_cached_replay(tmp_path, monkeypatch, author_contract):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    calls = []
    def worker(command, root, **options):
        assert options['local_model'] is True
        limits = json.loads((root / 'content_budget.json').read_text())
        assert limits['max_calls'] == 6 and limits['seconds'] <= 105
        number = len(json.loads((root / 'content_passes.json').read_text()))
        calls.append(number)
        result = ({'state': 'needs_resume', 'next_phase': stage.PHASES[number]} if number < 3 else
                  {'state': 'accepted', 'final_memo_digest': digest(accepted['memo']),
                   'content_review': {'state': 'accepted'}})
        (root / 'content_result.json').write_text(json.dumps(result))
    monkeypatch.setattr(stage, 'run_private', worker)
    for number in (1, 2, 3):
        result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110, author_contract=author_contract)
        assert len(calls) == number
        assert result['state'] == ('needs_resume' if number < 3 else 'accepted')
    request = json.loads((tmp_path / stage.ROOT_NAME / 'content_request.json').read_text())
    assert all(request[key] == {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
               for key in ('author_pin', 'reviewer_pin', 'characterizer_pin'))
    monkeypatch.setattr(stage, '_inventory', lambda: (_ for _ in ()).throw(AssertionError('No cached inference')))
    assert stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110, author_contract=author_contract)['state'] == 'accepted'
    assert calls == [1, 2, 3]
    assert stage.replay_source_unit_gate(tmp_path, accepted, sources, profile, author_contract=author_contract)[0] == Memo.model_validate(accepted['memo'])


def test_incomplete_phase_cannot_spend_extra_pass(tmp_path, monkeypatch):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    def worker(command, root, **options):
        (root / 'content_result.json').write_text(json.dumps({'state': 'needs_resume',
            'next_phase': 'source_characterization'}))
    monkeypatch.setattr(stage, 'run_private', worker)
    assert stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110)['reason'] == 'source_unit_phase_incomplete'
    assert stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110)['reason'] == 'source_unit_phase_incomplete'


@pytest.mark.parametrize('rows', [[], [{'pass': 1, 'phase': 'source_characterization', 'state': 'accepted'}],
    [{'pass': n, 'phase': stage.PHASES[min(n - 1, 2)], 'state': 'accepted'} for n in range(1, 5)],
    [{'pass': n, 'phase': stage.PHASES[n - 1], 'state': 'started' if n == 1 else 'accepted'} for n in range(1, 4)]])
def test_accepted_replay_rejects_missing_extra_or_unfinished_phases(tmp_path, rows):
    (tmp_path / 'content_passes.json').write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        stage._history(tmp_path, accepted=True)


def test_room_v32_cannot_fall_back_to_old_gates(tmp_path, monkeypatch):
    from delivery import material_stage
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    job = {'checkpoint': {'workflow_contract': 'room-v32-source-unit-content-gate'}}
    memo = {'content_review': {'state': 'accepted'}, 'content_review_version': 5}
    with pytest.raises(ValueError, match='frozen source unit flow'):
        material_stage._require_content_gate(job, tmp_path, memo)
    revised = {**memo, 'content_flow_contract': stage.FLOW, 'content_revision_path': str(tmp_path / stage.ROOT_NAME)}
    material_stage._require_content_gate(job, tmp_path, revised)
    assert material_stage._memo_digest(revised) != material_stage._memo_digest(memo)
    with pytest.raises(ValueError, match='cannot replace'):
        material_stage._require_content_gate({'checkpoint': {'workflow_contract': 'room-v31-blind-author-content-gate'}}, tmp_path, revised)


@pytest.mark.parametrize('changed', ['author_pin', 'request_digest', 'content_review'])
def test_exact_replay_cannot_replace_production_roles_or_gate(tmp_path, monkeypatch, changed):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    root = tmp_path / stage.ROOT_NAME
    root.mkdir()
    stage._request(root, accepted, sources, profile, create=True)
    (root / 'content_passes.json').write_text(json.dumps([
        {'pass': number, 'phase': phase, 'state': 'needs_resume' if number < 3 else 'accepted'}
        for number, phase in enumerate(stage.PHASES, 1)]))
    result = {'state': 'accepted', 'final_memo_digest': digest(accepted['memo']),
              'content_review': {'state': 'accepted'}}
    engine = sys.modules['scripts.private_source_unit_worker']
    if changed == 'content_review':
        result['content_review'] = {'state': 'accepted', 'unbound': True}
    else:
        loader = engine.load_source_unit_revision
        def changed_loader(root):
            record = loader(root)
            record[changed] = ({'name': 'qwen3:14b', 'digest': 'a' * 64}
                               if changed == 'author_pin' else 'c' * 64)
            return record
        engine.load_source_unit_revision = changed_loader
    (root / 'content_result.json').write_text(json.dumps(result))
    with pytest.raises(ValueError, match='frozen production request|exact replay'):
        stage.replay_source_unit_gate(tmp_path, accepted, sources, profile)


@pytest.mark.parametrize("author_contract", ["memo-source-unit-author-v2", "memo-source-unit-author-v3", "memo-source-unit-author-v4", "memo-source-unit-author-v5", "memo-source-unit-author-v6"])
def test_v33_author_contract_is_frozen_and_cannot_reuse_v32(tmp_path, monkeypatch, author_contract):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    root = tmp_path / stage.ROOT_NAME
    root.mkdir()
    request = stage._request(root, accepted, sources, profile, create=True,
                             author_contract=author_contract)
    assert request['author_contract'] == author_contract
    with pytest.raises(ValueError, match='request changed'):
        stage._request(root, accepted, sources, profile)
    with pytest.raises(ValueError, match='Unknown source unit author'):
        stage._request(root, accepted, sources, profile, author_contract='unrecognized')


@pytest.mark.parametrize("workflow, author_contract", [("room-v33-isolated-source-unit-content-gate", "memo-source-unit-author-v2"),
                                                     ("room-v34-isolated-source-unit-content-gate", "memo-source-unit-author-v3"),
                                                     ("room-v35-isolated-source-unit-content-gate", "memo-source-unit-author-v4"),
                                                     ("room-v36-isolated-source-unit-content-gate", "memo-source-unit-author-v5"),
                                                     ("room-v37-isolated-source-unit-content-gate", "memo-source-unit-author-v6")])
def test_v33_material_requires_its_isolated_author_contract(tmp_path, monkeypatch, workflow, author_contract):
    from delivery import material_stage
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    memo = {'content_review': {'state': 'accepted'}, 'content_flow_contract': stage.FLOW}
    job = {'checkpoint': {'workflow_contract': workflow}}
    with pytest.raises(ValueError, match='frozen source unit author contract'):
        material_stage._require_content_gate(job, tmp_path, memo)
    fresh = {**memo, 'content_author_contract': author_contract}
    material_stage._require_content_gate(job, tmp_path, fresh)
    assert material_stage._memo_digest(fresh) != material_stage._memo_digest(memo)
    with pytest.raises(ValueError, match='frozen source unit author contract'):
        material_stage._require_content_gate({'checkpoint': {'workflow_contract': 'room-v32-source-unit-content-gate'}}, tmp_path, fresh)


@pytest.mark.parametrize("flow_contract", [stage.FLOW_V2, stage.FLOW_V3])
def test_full_memo_flow_requires_five_ordered_phases_and_distinct_root(tmp_path, monkeypatch, flow_contract):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    phases, root_name = stage.flow_config(flow_contract)
    calls = []
    def worker(command, root, **options):
        assert root.name == root_name
        limits = json.loads((root / 'content_budget.json').read_text())
        assert limits['seconds'] <= 105 and limits['max_calls'] == 6
        number = len(json.loads((root / 'content_passes.json').read_text()))
        calls.append(number)
        result = ({'state': 'needs_resume', 'next_phase': phases[number]} if number < len(phases) else
                  {'state': 'accepted', 'final_memo_digest': digest(accepted['memo']),
                   'content_review': {'state': 'accepted'}})
        (root / 'content_result.json').write_text(json.dumps(result))
    monkeypatch.setattr(stage, 'run_private', worker)
    for number in range(1, len(phases) + 1):
        result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110,
            flow_contract=flow_contract, author_contract='memo-source-unit-author-v7')
        assert result['state'] == ('needs_resume' if number < len(phases) else 'accepted')
        assert len(calls) == number
    assert result['content_flow_contract'] == flow_contract
    assert not (tmp_path / stage.ROOT_NAME).exists()
    rows = json.loads((tmp_path / root_name / 'content_passes.json').read_text())
    with pytest.raises(ValueError, match='fixed phase passes'):
        stage._history(tmp_path / root_name, accepted=True)
    (tmp_path / root_name / 'content_passes.json').write_text(json.dumps(rows[:3]))
    with pytest.raises(ValueError, match='completed ordered phases'):
        stage.replay_source_unit_gate(tmp_path, accepted, sources, profile,
            flow_contract=flow_contract, author_contract='memo-source-unit-author-v7')


def test_full_memo_flow_cannot_use_old_author_or_old_room_gate(tmp_path, monkeypatch):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='does not match'):
        stage._request(tmp_path, accepted, sources, profile,
            flow_contract=stage.FLOW_V2, author_contract='memo-source-unit-author-v6')
    from delivery import material_stage
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    memo = {'content_review': {'state': 'accepted'}, 'content_flow_contract': stage.FLOW,
            'content_author_contract': 'memo-source-unit-author-v6'}
    job = {'checkpoint': {'workflow_contract': 'room-v38-full-memo-content-gate'}}
    with pytest.raises(ValueError, match='frozen source unit flow'):
        material_stage._require_content_gate(job, tmp_path, memo)
    material_stage._require_content_gate(job, tmp_path, {**memo,
        'content_flow_contract': stage.FLOW_V2, 'content_author_contract': 'memo-source-unit-author-v7'})


def test_checkpointed_review_does_not_advance_after_an_incomplete_group(tmp_path, monkeypatch):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    calls = []
    def worker(command, root, **options):
        number = len(json.loads((root / 'content_passes.json').read_text()))
        calls.append(number)
        next_phase = stage.PHASES_V3[number] if number < 3 else stage.PHASES_V3[2]
        (root / 'content_result.json').write_text(json.dumps({'state': 'needs_resume', 'next_phase': next_phase}))
    monkeypatch.setattr(stage, 'run_private', worker)
    for number in range(1, 4):
        result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110,
            flow_contract=stage.FLOW_V3, author_contract='memo-source-unit-author-v7')
    assert result['state'] == 'blocked' and result['reason'] == 'source_unit_phase_incomplete'
    assert stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110,
        flow_contract=stage.FLOW_V3, author_contract='memo-source-unit-author-v7')['state'] == 'blocked'
    assert calls == [1, 2, 3]


@pytest.mark.parametrize("section_contract, workflow", [("memo-section-units-author-v2", "room-v40-native-claim-full-memo-gate"),
    ("memo-section-units-author-v3", "room-v41-structured-section-full-memo-gate")])
def test_native_section_author_contract_is_frozen_and_material_bound(tmp_path, monkeypatch, section_contract, workflow):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    request = stage._request(tmp_path, accepted, sources, profile, create=True,
        flow_contract=stage.FLOW_V3, author_contract='memo-source-unit-author-v7',
        section_author_contract=section_contract)
    assert request['section_author_contract'] == section_contract
    with pytest.raises(ValueError, match='request changed'):
        stage._request(tmp_path, accepted, sources, profile, flow_contract=stage.FLOW_V3,
            author_contract='memo-source-unit-author-v7')
    from delivery import material_stage
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    memo = {'content_review': {'state': 'accepted'}, 'content_flow_contract': stage.FLOW_V3,
            'content_author_contract': 'memo-source-unit-author-v7'}
    job = {'checkpoint': {'workflow_contract': workflow}}
    with pytest.raises(ValueError, match='frozen section author contract'):
        material_stage._require_content_gate(job, tmp_path, memo)
    native = {**memo, 'content_section_author_contract': section_contract}
    material_stage._require_content_gate(job, tmp_path, native)
    assert material_stage._memo_digest(native) != material_stage._memo_digest(memo)
    with pytest.raises(ValueError, match='frozen section author contract'):
        material_stage._require_content_gate(
            {'checkpoint': {'workflow_contract': 'room-v39-checkpointed-full-memo-gate'}}, tmp_path, native)


@pytest.mark.parametrize("section_contract", ["memo-section-units-author-v3", "memo-section-units-author-v4", "memo-section-units-author-v5", "memo-section-units-author-v6"])
def test_independent_core_author_has_fifteen_mandatory_phases_and_frozen_pin(tmp_path, monkeypatch, section_contract):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    profile['profiles']['draft'] = 'qwen3:14b'
    profile['memo_role_model_digests']['draft'] = 'a' * 64
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3.5:9b': 'b' * 64, 'qwen3:14b': 'a' * 64})
    options = dict(flow_contract=stage.FLOW_V4, author_contract='memo-source-unit-author-v7',
                   section_author_contract=section_contract)
    calls = []
    gate = {'state': 'accepted', 'core_author_pin': {'name': 'qwen3:14b', 'digest': 'a' * 64},
            'section_author_contract': section_contract}
    sys.modules['scripts.private_source_unit_worker'].replay_source_unit_revision = lambda memo, sources, record: (memo, gate)
    def worker(command, root, **kwargs):
        request = json.loads((root / 'content_request.json').read_text())
        assert request['core_author_pin'] == gate['core_author_pin']
        assert request['author_pin']['name'] == 'qwen3.5:9b'
        row = json.loads((root / 'content_passes.json').read_text())[-1]
        calls.append(row['phase'])
        number = len(calls)
        result = ({'state': 'needs_resume', 'next_phase': stage.PHASES_V4[number]} if number < 15 else
                  {'state': 'accepted', 'final_memo_digest': digest(accepted['memo']), 'content_review': gate})
        (root / 'content_result.json').write_text(json.dumps(result))
    monkeypatch.setattr(stage, 'run_private', worker)
    for number in range(1, 16):
        result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110, **options)
        assert result['state'] == ('accepted' if number == 15 else 'needs_resume')
    assert calls == list(stage.PHASES_V4)
    assert result['content_core_author_pin'] == gate['core_author_pin']
    root = tmp_path / stage.ROOT_NAME_V4
    request = json.loads((root / 'content_request.json').read_text())
    request['core_author_pin']['digest'] = 'c' * 64
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    (root / 'content_request.json').write_text(json.dumps(request))
    with pytest.raises(ValueError, match='frozen local core profile'):
        stage.replay_source_unit_gate(tmp_path, accepted, sources, profile, **options)


def test_independent_author_flow_requires_explicit_installed_draft_role(tmp_path, monkeypatch):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    profile['profiles']['draft'] = 'qwen3:14b'
    profile['memo_role_model_digests']['draft'] = 'a' * 64
    options = dict(flow_contract=stage.FLOW_V4, author_contract='memo-source-unit-author-v7')
    with pytest.raises(ValueError, match='structured section author'):
        stage._request(tmp_path, accepted, sources, profile, create=True, **options)
    with pytest.raises(ValueError, match='installed frozen local core'):
        stage._request(tmp_path, accepted, sources, profile, create=True,
                       section_author_contract='memo-section-units-author-v3', **options)


def test_independent_core_role_is_mandatory_in_material_lineage(tmp_path, monkeypatch):
    from delivery import material_stage
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    job = {'checkpoint': {'workflow_contract': 'room-v42-independent-author-checkpoints'}}
    pin = {'name': 'qwen3:14b', 'digest': 'a' * 64}
    memo = {'content_flow_contract': stage.FLOW_V4,
            'content_author_contract': 'memo-source-unit-author-v7',
            'content_section_author_contract': 'memo-section-units-author-v3',
            'content_review': {'state': 'accepted', 'core_author_pin': pin}}
    with pytest.raises(ValueError, match='frozen core author role'):
        material_stage._require_content_gate(job, tmp_path, memo)
    complete = {**memo, 'content_core_author_pin': pin}
    material_stage._require_content_gate(job, tmp_path, complete)
    assert material_stage._memo_digest(memo) != material_stage._memo_digest(complete)


@pytest.mark.parametrize("workflow,contract,previous", [("room-v44-literal-narrative-author", "memo-section-units-author-v5", "memo-section-units-author-v4"), ("room-v45-narrative-section-budget", "memo-section-units-author-v6", "memo-section-units-author-v5")])
def test_literal_narrative_room_requires_exact_new_section_contract(tmp_path, monkeypatch, workflow, contract, previous):
    from delivery import material_stage
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    pin = {'name': 'qwen3:14b', 'digest': 'a' * 64}
    job = {'checkpoint': {'workflow_contract': workflow}}
    memo = {'content_flow_contract': stage.FLOW_V4,
            'content_author_contract': 'memo-source-unit-author-v7',
            'content_core_author_pin': pin,
            'content_review': {'state': 'accepted', 'core_author_pin': pin},
            'content_section_author_contract': previous}
    with pytest.raises(ValueError, match='frozen section author contract'):
        material_stage._require_content_gate(job, tmp_path, memo)
    memo['content_section_author_contract'] = contract
    material_stage._require_content_gate(job, tmp_path, memo)
    with pytest.raises(ValueError, match='frozen section author contract'):
        material_stage._require_content_gate({'checkpoint': {'workflow_contract':
            'room-v43-bounded-section-author'}}, tmp_path, memo)


def test_v6_uses_frozen_author_role_while_v5_retains_draft_role(tmp_path, monkeypatch):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    profile['profiles']['draft'] = 'qwen3.5:9b'
    profile['memo_role_model_digests']['draft'] = 'b' * 64
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3.5:9b': 'b' * 64, 'qwen3:14b': 'a' * 64})
    for contract, expected in [('memo-section-units-author-v5', {'name': 'qwen3.5:9b', 'digest': 'b' * 64}),
                               ('memo-section-units-author-v6', {'name': 'qwen3:14b', 'digest': 'a' * 64})]:
        root = tmp_path / contract; root.mkdir()
        request = stage._request(root, accepted, sources, profile, create=True, flow_contract=stage.FLOW_V4,
            author_contract='memo-source-unit-author-v7', section_author_contract=contract)
        assert request['core_author_pin'] == expected
    profile['memo_role_model_digests'] = None
    profile['memo_author_model_digest'] = 'a' * 64
    assert stage._core_role(profile, 'memo-section-units-author-v6') == ('qwen3:14b', 'a' * 64)
    profile['memo_author_model_digest'] = 'c' * 64
    root = tmp_path / 'changed'; root.mkdir()
    with pytest.raises(ValueError, match='installed frozen local core'):
        stage._request(root, accepted, sources, profile, create=True, flow_contract=stage.FLOW_V4,
            author_contract='memo-source-unit-author-v7', section_author_contract='memo-section-units-author-v6')


def test_v7_freezes_independent_core_reviewer_and_rejects_missing_profile_digest(tmp_path, monkeypatch):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    profile['profiles']['review'] = 'qwen3:14b'
    profile['memo_role_model_digests']['review'] = 'a' * 64
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3.5:9b': 'b' * 64, 'qwen3:14b': 'a' * 64})
    options = dict(flow_contract=stage.FLOW_V4, author_contract='memo-source-unit-author-v7',
                   section_author_contract='memo-section-units-author-v7')
    request = stage._request(tmp_path, accepted, sources, profile, create=True, **options)
    assert request['core_reviewer_pin'] == {'name': 'qwen3:14b', 'digest': 'a' * 64}
    assert request['reviewer_pin']['name'] == 'qwen3.5:9b'
    profile['memo_role_model_digests']['review'] = 'c' * 64
    with pytest.raises(ValueError, match='frozen local review profile'):
        stage._request(tmp_path, accepted, sources, profile, **options)
    profile['memo_role_model_digests'] = None
    profile['memo_causal_review_model_digest'] = 'a' * 64
    assert stage._core_review_role(profile) == ('qwen3:14b', 'a' * 64)


@pytest.mark.parametrize("workflow,contract", [("room-v46-structured-core-decisions", "memo-section-units-author-v7"), ("room-v47-prospective-risk-scope", "memo-section-units-author-v8")])
def test_structured_core_material_requires_separate_reviewer_lineage(tmp_path, monkeypatch, workflow, contract):
    from delivery import material_stage
    monkeypatch.setattr(material_stage, '_accepted_memo_for_material', lambda *args: {})
    pin = {'name': 'qwen3:14b', 'digest': 'a' * 64}
    memo = {'content_flow_contract': stage.FLOW_V4, 'content_author_contract': 'memo-source-unit-author-v7',
            'content_section_author_contract': contract, 'content_core_author_pin': pin,
            'content_review': {'state': 'accepted', 'core_author_pin': pin, 'core_reviewer_pin': pin}}
    job = {'checkpoint': {'workflow_contract': workflow}}
    with pytest.raises(ValueError, match='frozen core reviewer role'):
        material_stage._require_content_gate(job, tmp_path, memo)
    complete = {**memo, 'content_core_reviewer_pin': pin}
    material_stage._require_content_gate(job, tmp_path, complete)
    assert material_stage._memo_digest(complete) != material_stage._memo_digest(memo)


def test_new_narrative_reviewer_contract_is_frozen_without_changing_old_v8(tmp_path, monkeypatch):
    accepted, sources, profile = fixture(tmp_path, monkeypatch)
    profile['memo_role_model_digests']['review'] = 'b' * 64
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3.5:9b': 'b' * 64, 'qwen3:14b': 'a' * 64})
    options = dict(flow_contract=stage.FLOW_V4, author_contract='memo-source-unit-author-v7',
                   section_author_contract='memo-section-units-author-v8', section_review_contract='memo-section-units-review-v7')
    request = stage._request(tmp_path, accepted, sources, profile, create=True, **options)
    assert request['section_review_contract'] == 'memo-section-units-review-v7'
    with pytest.raises(ValueError, match='request changed'):
        stage._request(tmp_path, accepted, sources, profile, **{key:value for key,value in options.items() if key != 'section_review_contract'})
    old = tmp_path / 'old'; old.mkdir()
    historic = stage._request(old, accepted, sources, profile, create=True,
        **{key:value for key,value in options.items() if key != 'section_review_contract'})
    assert 'section_review_contract' not in historic
