"""The fresh split flow persists all 22 checkpoints and immutable role lineage."""
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from agents.inference.model_authorship import digest
from agents.research import diligence_coverage as coverage
from delivery import source_unit_content_stage as stage
from tests.delivery.test_source_unit_content_stage_v5 import setup


def options():
    return {'flow_contract': stage.FLOW_V6, 'author_contract': 'memo-source-unit-author-v7',
            'section_author_contract': 'memo-section-units-author-v13',
            'section_review_contract': 'memo-section-units-review-v12',
            'coverage_contract': coverage.CONTRACT_V12, 'coverage_role': 'challenge'}


@pytest.mark.parametrize('coverage_contract', ['diligence-source-coverage-v12', 'diligence-source-coverage-v13'])
def test_flow6_has_own_root_and_rejects_coverage_or_author_downgrade(tmp_path, monkeypatch, coverage_contract):
    accepted, sources, profile, _ = setup(monkeypatch)
    configured = {**options(), 'coverage_contract': coverage_contract}
    request = stage._request(tmp_path, accepted, sources, profile, create=True, **configured)
    assert request['flow_contract'] == stage.FLOW_V6 and request['coverage_role'] == 'challenge'
    assert request['coverage_pin'] != request['core_author_pin']
    assert stage.flow_config(stage.FLOW_V6) == (stage.PHASES_V6, 'content_units_v6')
    assert stage.flow_config(stage.FLOW_V5) == (stage.PHASES_V5, 'content_units_v5')
    assert request['coverage_contract'] == coverage_contract
    assert stage._request(tmp_path, accepted, sources, profile, **configured) == request
    for changes in ({'flow_contract': stage.FLOW_V5},
                    {'coverage_contract': coverage.CONTRACT_V11},
                    {'section_author_contract': 'memo-section-units-author-v12',
                     'section_review_contract': 'memo-section-units-review-v11'}):
        with pytest.raises(ValueError, match='Split adjudication'):
            stage._request(tmp_path, accepted, sources, profile, **{**configured, **changes})
    other = 'diligence-source-coverage-v13' if coverage_contract.endswith('v12') else 'diligence-source-coverage-v12'
    with pytest.raises(ValueError, match='request changed'):
        stage._request(tmp_path, accepted, sources, profile, **{**configured, 'coverage_contract': other})


@pytest.mark.parametrize('flow_contract', [stage.FLOW_V6, stage.FLOW_V7, stage.FLOW_V8, stage.FLOW_V9, stage.FLOW_V10])
def test_flow6_production_persists_all_phases_and_exact_gate_without_restarting_work(tmp_path, monkeypatch, flow_contract):
    accepted, sources, profile, _ = setup(monkeypatch)
    configured = options()
    if flow_contract in {stage.FLOW_V7, stage.FLOW_V8, stage.FLOW_V9, stage.FLOW_V10}:
        configured.update(flow_contract=flow_contract, coverage_contract=coverage.CONTRACT_V18 if flow_contract == stage.FLOW_V10 else
                                            coverage.CONTRACT_V17 if flow_contract == stage.FLOW_V9 else
                                            coverage.CONTRACT_V16 if flow_contract == stage.FLOW_V8 else coverage.CONTRACT_V15,
                          coverage_adjudicator_role='prose')
        profile['profiles']['prose'] = 'qwen3:14b'
        profile['memo_role_model_digests']['prose'] = 'a' * 64
    phases, root_name = stage.flow_config(flow_contract)
    calls = []
    gate = {'state': 'accepted', 'contract': flow_contract,
            'core_author_pin': {'name': 'qwen3:14b', 'digest': 'a' * 64},
            'core_reviewer_pin': {'name': 'qwen3:14b', 'digest': 'a' * 64},
            'coverage_pin': {'name': 'qwen3.5:9b', 'digest': 'b' * 64},
            'coverage_role': 'challenge', 'coverage_contract': configured['coverage_contract'],
            'section_author_contract': configured['section_author_contract'],
            'section_review_contract': configured['section_review_contract'],
            'diligence_coverage': {'state': 'accepted', 'coverage_complete': True,
                                  'missing_categories': ['identity']}}
    if flow_contract in {stage.FLOW_V7, stage.FLOW_V8, stage.FLOW_V9, stage.FLOW_V10}:
        gate.update(coverage_adjudicator_pin={'name': 'qwen3:14b', 'digest': 'a' * 64},
                    coverage_adjudicator_role='prose')

    def load(root):
        request = json.loads((root / 'content_request.json').read_text())
        return {'contract': request['flow_contract'], 'request_digest': request['digest'],
                **{key: request[key] for key in ('author_contract', 'section_author_contract',
                    'section_review_contract', 'characterizer_pin', 'author_pin', 'reviewer_pin',
                    'core_author_pin', 'core_reviewer_pin', 'coverage_pin', 'coverage_contract',
                    'coverage_structures', 'coverage_financial_scope', 'coverage_role')},
                **{key: request[key] for key in ('coverage_adjudicator_pin', 'coverage_adjudicator_role') if key in request}}

    engine = SimpleNamespace(load_source_unit_revision=load,
        replay_source_unit_revision=lambda memo, sources, record: (memo, copy.deepcopy(gate)))
    monkeypatch.setitem(sys.modules, 'scripts.private_source_unit_worker', engine)

    def worker(command, root, **kwargs):
        phase = json.loads((root / 'content_passes.json').read_text())[-1]['phase']
        calls.append(phase)
        limits = json.loads((root / 'content_budget.json').read_text())
        assert limits['seconds'] <= 105 and limits['max_calls'] == 6
        result = ({'state': 'needs_resume', 'next_phase': phases[len(calls)],
                   'diligence_coverage': gate['diligence_coverage']}
                  if len(calls) < len(phases) else
                  {'state': 'accepted', 'final_memo_digest': digest(accepted['memo']), 'content_review': gate})
        (root / 'content_result.json').write_text(json.dumps(result))

    monkeypatch.setattr(stage, 'run_private', worker)
    for index in range(len(phases)):
        result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110, **configured)
        assert result['state'] == ('accepted' if index == len(phases) - 1 else 'needs_resume')
        assert result['content_coverage_role'] == 'challenge'
    assert calls == list(phases)
    if flow_contract == stage.FLOW_V10:
        assert calls[:6] == list(stage.COVERAGE_PHASES_V10)
        assert len(calls) == 21
    elif flow_contract in {stage.FLOW_V7, stage.FLOW_V8, stage.FLOW_V9}:
        assert calls[5:11] == list(stage.COVERAGE_PHASES_V7[5:])
    else:
        assert calls[5:7] == ['diligence_source_adjudication', 'diligence_field_selection']
    root = tmp_path / root_name
    stage._history(root, accepted=True, flow_contract=flow_contract)
    monkeypatch.setattr(stage, 'run_private', lambda *args, **kwargs: pytest.fail('Accepted work must replay'))
    assert stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110, **configured)['state'] == 'accepted'
    for key, wrong in (('contract', stage.FLOW_V5), ('coverage_contract', coverage.CONTRACT_V11)):
        original = gate[key]
        gate[key] = wrong
        result_path = root / 'content_result.json'
        result = json.loads(result_path.read_text())
        result['content_review'] = copy.deepcopy(gate)
        result_path.write_text(json.dumps(result))
        with pytest.raises(ValueError, match='frozen flow/coverage contract'):
            stage.replay_source_unit_gate(tmp_path, accepted, sources, profile, **configured)
        gate[key] = original
        result['content_review'] = copy.deepcopy(gate)
        result_path.write_text(json.dumps(result))
    history = json.loads((root / 'content_passes.json').read_text())
    history.pop(5)
    (root / 'content_passes.json').write_text(json.dumps(history))
    with pytest.raises(ValueError, match='history changed|completed ordered'):
        stage.replay_source_unit_gate(tmp_path, accepted, sources, profile, **configured)
