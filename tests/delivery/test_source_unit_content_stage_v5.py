"""Production phase history cannot skip all-source scope or downgrade its gate."""
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from agents.inference.model_authorship import digest
from agents.research import diligence_coverage
from delivery import source_unit_content_stage as stage
from tests.research.test_memo_section_units_v9 import fixture as memo_fixture


def setup(monkeypatch):
    memo, sources = memo_fixture()
    profile = {'profiles': {'author': 'qwen3:14b', 'challenge': 'qwen3.5:9b', 'review': 'qwen3:14b'},
               'memo_role_model_digests': {'author': 'a' * 64, 'challenge': 'b' * 64, 'review': 'a' * 64}}
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3:14b': 'a' * 64, 'qwen3.5:9b': 'b' * 64})
    options = {'flow_contract': stage.FLOW_V5, 'author_contract': 'memo-source-unit-author-v7',
               'section_author_contract': 'memo-section-units-author-v9', 'section_review_contract': 'memo-section-units-review-v8'}
    return {'memo': memo}, sources, profile, options


def test_flow5_freezes_exact_models_structure_and_unqualified_financial_scope(tmp_path, monkeypatch):
    accepted, sources, profile, options = setup(monkeypatch)
    structures = {sources[0]['id']: {'unassessed_images': True}}
    financial = diligence_coverage._financial_scope({'supplied_workbook_inventory_digest': 'f' * 64,
        'semantic_coverage': 'unassessed', 'financial_validation': 'not_established', 'workbook_recalculation': 'not_performed'})
    request = stage._request(tmp_path, accepted, sources, profile, create=True,
                             coverage_structures=structures, coverage_financial_scope=financial, **options)
    assert request['coverage_pin'] == request['core_author_pin'] == {'name': 'qwen3:14b', 'digest': 'a' * 64}
    assert 'coverage_role' not in request
    assert request['coverage_contract'] == diligence_coverage.CONTRACT
    assert request['coverage_structures'] == structures and request['coverage_financial_scope'] == financial
    assert stage._request(tmp_path, accepted, sources, profile, coverage_structures=structures,
                          coverage_financial_scope=financial, **options) == request
    for changed in ({'coverage_structures': {}}, {'coverage_financial_scope': None}):
        kwargs = {'coverage_structures': structures, 'coverage_financial_scope': financial, **changed}
        with pytest.raises(ValueError, match='request changed'):
            stage._request(tmp_path, accepted, sources, profile, **kwargs, **options)


def test_flow5_cannot_use_historical_core_or_omit_its_clarity_review(tmp_path, monkeypatch):
    accepted, sources, profile, options = setup(monkeypatch)
    for changes in ({'section_author_contract': 'memo-section-units-author-v8'},
                    {'section_review_contract': None}, {'flow_contract': stage.FLOW_V4}):
        with pytest.raises(ValueError, match='exact v7/v9/v8|cannot downgrade'):
            stage._request(tmp_path, accepted, sources, profile, create=True, **{**options, **changes})


@pytest.mark.parametrize('author_contract,review_contract', [('memo-section-units-author-v10', 'memo-section-units-review-v9'), ('memo-section-units-author-v11', 'memo-section-units-review-v10'), ('memo-section-units-author-v12', 'memo-section-units-review-v11'), ('memo-section-units-author-v13', 'memo-section-units-review-v12')])
def test_flow5_v10_uses_author_role_pin_and_requires_v9_reviewer(tmp_path, monkeypatch, author_contract, review_contract):
    accepted, sources, profile, options = setup(monkeypatch)
    options.update(section_author_contract=author_contract,
                   section_review_contract=review_contract)
    request = stage._request(tmp_path, accepted, sources, profile, create=True,
                             coverage_contract=diligence_coverage.CONTRACT_V5, **options)
    assert request['core_author_pin'] == request['coverage_pin'] == {'name': 'qwen3:14b', 'digest': 'a' * 64}
    assert request['core_reviewer_pin'] == {'name': 'qwen3:14b', 'digest': 'a' * 64}
    with pytest.raises(ValueError, match='exact v7/v9/v8'):
        stage._request(tmp_path, accepted, sources, profile,
                       **{**options, 'section_review_contract': 'memo-section-units-review-v8'})


def test_flow5_freezes_v2_coverage_without_reinterpreting_saved_v1_request(tmp_path, monkeypatch):
    accepted, sources, profile, options = setup(monkeypatch)
    request = stage._request(tmp_path, accepted, sources, profile, create=True,
                             coverage_contract=diligence_coverage.CONTRACT_V2, **options)
    assert request['coverage_contract'] == diligence_coverage.CONTRACT_V2
    assert stage._request(tmp_path, accepted, sources, profile,
                          coverage_contract=diligence_coverage.CONTRACT_V2, **options) == request
    with pytest.raises(ValueError, match='request changed'):
        stage._request(tmp_path, accepted, sources, profile, **options)


def test_flow5_independent_coverage_role_freezes_its_own_profile_pin(tmp_path, monkeypatch):
    accepted, sources, profile, options = setup(monkeypatch)
    request = stage._request(tmp_path, accepted, sources, profile, create=True,
                             coverage_role='challenge', **options)
    assert request['coverage_role'] == 'challenge'
    assert request['coverage_pin'] == {'name': 'qwen3.5:9b', 'digest': 'b' * 64}
    assert request['core_author_pin'] == {'name': 'qwen3:14b', 'digest': 'a' * 64}
    assert stage._request(tmp_path, accepted, sources, profile, coverage_role='challenge', **options) == request
    for altered in (None, 'author', 'review'):
        with pytest.raises(ValueError, match='request changed'):
            stage._request(tmp_path, accepted, sources, profile, coverage_role=altered, **options)
    changed = copy.deepcopy(request)
    changed['coverage_pin'] = dict(request['core_author_pin'])
    changed['digest'] = digest({key: value for key, value in changed.items() if key != 'digest'})
    (tmp_path / 'content_request.json').write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='Coverage differs'):
        stage._request(tmp_path, accepted, sources, profile, coverage_role='challenge', **options)


def test_flow5_coverage_role_requires_own_digest_and_installed_model_without_fallback(tmp_path, monkeypatch):
    accepted, sources, profile, options = setup(monkeypatch)
    missing = copy.deepcopy(profile)
    missing['memo_role_model_digests'].pop('challenge')
    missing['memo_causal_review_model_digest'] = 'b' * 64
    with pytest.raises(ValueError, match='own exact frozen role digest'):
        stage._request(tmp_path, accepted, sources, missing, create=True, coverage_role='challenge', **options)
    mismatched = copy.deepcopy(profile)
    mismatched['profiles']['coverage'] = 'qwen3.5:9b'
    mismatched['memo_role_model_digests']['coverage'] = 'c' * 64
    with pytest.raises(ValueError, match='Coverage requires its installed'):
        stage._request(tmp_path, accepted, sources, mismatched, create=True, coverage_role='coverage', **options)
    assert not (tmp_path / 'content_request.json').exists()


def test_flow5_coverage11_freezes_new_selection_contract_with_exact_coverage10_batches(tmp_path, monkeypatch):
    accepted, sources, profile, options = setup(monkeypatch)
    options.update(section_author_contract='memo-section-units-author-v13',
                   section_review_contract='memo-section-units-review-v12')
    request = stage._request(tmp_path, accepted, sources, profile, create=True,
        coverage_contract=diligence_coverage.CONTRACT_V11, coverage_role='challenge', **options)
    assert request['coverage_contract'] == diligence_coverage.CONTRACT_V11
    old = diligence_coverage.frozen_coverage_requests(request['sources'], request['coverage_pin'],
        structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'],
        contract=diligence_coverage.CONTRACT_V10)
    fresh = diligence_coverage.frozen_coverage_requests(request['sources'], request['coverage_pin'],
        structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'],
        contract=diligence_coverage.CONTRACT_V11)
    assert [item[:3] for item in fresh] == [item[:3] for item in old]
    assert [item[3].model_json_schema() for item in fresh] == [item[3].model_json_schema() for item in old]
    assert all(item[2]['contract'] == diligence_coverage.CONTRACT_V10 for item in fresh)
    assert stage._request(tmp_path, accepted, sources, profile,
        coverage_contract=diligence_coverage.CONTRACT_V11, coverage_role='challenge', **options) == request
    with pytest.raises(ValueError, match='request changed'):
        stage._request(tmp_path, accepted, sources, profile,
            coverage_contract=diligence_coverage.CONTRACT_V10, coverage_role='challenge', **options)


def test_flow5_coverage_checkpoint_rechecks_independent_installed_digest(tmp_path, monkeypatch):
    accepted, sources, profile, options = setup(monkeypatch)
    calls = []
    def worker(command, root, **kwargs):
        calls.append(command)
        request = json.loads((root / 'content_request.json').read_text())
        assert request['coverage_pin']['name'] == 'qwen3.5:9b'
        (root / 'content_result.json').write_text(json.dumps({
            'state': 'needs_resume', 'next_phase': stage.PHASES_V5[1],
            'diligence_coverage': {'state': 'needs_call'}}))
    monkeypatch.setattr(stage, 'run_private', worker)
    result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110,
                                       coverage_role='challenge', **options)
    assert result['state'] == 'needs_resume' and result['content_coverage_role'] == 'challenge'
    assert result['content_coverage_pin'] != result['content_core_author_pin']
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3:14b': 'a' * 64, 'qwen3.5:9b': 'd' * 64})
    result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110,
                                       coverage_role='challenge', **options)
    assert result['state'] == 'blocked' and result['reason'] == 'source_unit_installed_model_changed'
    assert len(calls) == 1


def test_flow5_production_records_all_twenty_one_phases_and_reuses_accepted_exact_gate(tmp_path, monkeypatch):
    accepted, sources, profile, options = setup(monkeypatch)
    calls = []
    gate = {'state': 'accepted', 'core_author_pin': {'name': 'qwen3:14b', 'digest': 'a' * 64},
            'coverage_pin': {'name': 'qwen3:14b', 'digest': 'a' * 64},
            'core_reviewer_pin': {'name': 'qwen3:14b', 'digest': 'a' * 64},
            'section_author_contract': options['section_author_contract'], 'section_review_contract': options['section_review_contract'],
            'diligence_coverage': {'state': 'accepted', 'coverage_complete': True, 'missing_categories': ['identity']}}
    def load(root):
        request = json.loads((root / 'content_request.json').read_text())
        return {'contract': request['flow_contract'], 'request_digest': request['digest'],
                **{key: request[key] for key in ('author_contract', 'section_author_contract', 'section_review_contract',
                    'characterizer_pin', 'author_pin', 'reviewer_pin', 'core_author_pin', 'core_reviewer_pin',
                    'coverage_pin', 'coverage_contract', 'coverage_structures', 'coverage_financial_scope')}}
    engine = SimpleNamespace(load_source_unit_revision=load,
        replay_source_unit_revision=lambda memo, sources, record: (memo, copy.deepcopy(gate)))
    monkeypatch.setitem(sys.modules, 'scripts.private_source_unit_worker', engine)
    def worker(command, root, **kwargs):
        phase = json.loads((root / 'content_passes.json').read_text())[-1]['phase']
        calls.append(phase)
        limits = json.loads((root / 'content_budget.json').read_text())
        assert limits['seconds'] <= 105 and limits['max_calls'] == 6
        result = ({'state': 'needs_resume', 'next_phase': stage.PHASES_V5[len(calls)], 'diligence_coverage': gate['diligence_coverage']}
                  if len(calls) < len(stage.PHASES_V5) else
                  {'state': 'accepted', 'final_memo_digest': digest(accepted['memo']), 'content_review': gate})
        (root / 'content_result.json').write_text(json.dumps(result))
    monkeypatch.setattr(stage, 'run_private', worker)
    for index in range(21):
        result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110, **options)
        assert result['state'] == ('accepted' if index == 20 else 'needs_resume')
        assert result['content_diligence_coverage'] == gate['diligence_coverage']
    assert calls == list(stage.PHASES_V5)
    root = tmp_path / stage.ROOT_NAME_V5
    stage._history(root, accepted=True, flow_contract=stage.FLOW_V5)
    monkeypatch.setattr(stage, 'run_private', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('No accepted inference')))
    assert stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110, **options)['state'] == 'accepted'
    history = json.loads((root / 'content_passes.json').read_text())
    history.pop(2)
    (root / 'content_passes.json').write_text(json.dumps(history))
    with pytest.raises(ValueError, match='history changed|completed ordered'):
        stage.replay_source_unit_gate(tmp_path, accepted, sources, profile, **options)
