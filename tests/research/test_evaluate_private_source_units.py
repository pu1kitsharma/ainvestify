"""Independent installed coverage role stays frozen across bounded checkpoints."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research import diligence_coverage
from scripts import evaluate_private_source_units as script
from tests.research.test_memo_section_units_v9 import fixture


SOURCE = 'qwen3.5:9b'
CORE = 'qwen3:14b'
PINS = {SOURCE: 'a' * 64, CORE: 'b' * 64, 'claude-pro-sonnet': 'c' * 64}


def setup(tmp_path, monkeypatch):
    memo, sources = fixture()
    memo_dir = tmp_path / 'memo'
    memo_dir.mkdir()
    monkeypatch.setattr(script, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(script, '_memo_inputs', lambda path:
        (memo_dir, {'sources': sources}, {}, {'memo': memo}))
    monkeypatch.setattr(script, '_installed_digest', lambda name: PINS[name])
    return memo_dir, sources


def prepare(memo_dir, output, **kwargs):
    return script.run(memo_dir, output, 'prepare', SOURCE, CORE, CORE,
                      flow=script.FLOW_V5, **kwargs)


def test_unconfigured_coverage_preserves_the_historical_core_author_default(tmp_path, monkeypatch):
    memo_dir, _ = setup(tmp_path, monkeypatch)
    prepare(memo_dir, tmp_path / 'default')
    prepare(memo_dir, tmp_path / 'explicit-core', coverage_model=CORE)
    historical = json.loads((tmp_path / 'default' / 'content_request.json').read_text())
    explicit = json.loads((tmp_path / 'explicit-core' / 'content_request.json').read_text())
    assert historical == explicit
    assert historical['coverage_pin'] == historical['core_author_pin']
    assert historical['coverage_pin'] == {'name': CORE, 'digest': PINS[CORE]}


def test_independent_coverage_pin_binds_requests_and_cannot_be_reselected_or_reinstalled(tmp_path, monkeypatch):
    memo_dir, sources = setup(tmp_path, monkeypatch)
    output = tmp_path / 'independent'
    prepare(memo_dir, output, coverage_model=SOURCE)
    path = output / 'content_request.json'
    original = path.read_bytes()
    request = json.loads(original)
    assert request['coverage_pin'] == {'name': SOURCE, 'digest': PINS[SOURCE]}
    assert request['core_author_pin'] == request['core_reviewer_pin'] == {'name': CORE, 'digest': PINS[CORE]}
    assert request['digest'] == digest({key: value for key, value in request.items() if key != 'digest'})
    frozen = diligence_coverage.frozen_coverage_requests(sources, request['coverage_pin'],
        structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'],
        contract=request['coverage_contract'],
        **({'adjudicator_pin': request['coverage_adjudicator_pin']} if 'coverage_adjudicator_pin' in request else {}))
    assert frozen[0][2]['model_pin'] == request['coverage_pin']
    assert frozen[0][2]['options'] == diligence_coverage.OPTIONS_V10
    monkeypatch.setattr(script, 'run_private', lambda *args, **kwargs:
                        pytest.fail('Changed frozen coverage role must not start a worker'))
    with pytest.raises(ValueError, match='cannot change'):
        script.run(memo_dir, output, 'advance', coverage_model=CORE)
    monkeypatch.setattr(script, '_installed_digest', lambda name:
                        'd' * 64 if name == SOURCE else PINS[name])
    with pytest.raises(ValueError, match='role changed'):
        script.run(memo_dir, output, 'advance', coverage_model=SOURCE)
    assert path.read_bytes() == original
    assert not (output / 'content_passes.json').exists()


def test_independent_coverage_rejects_hosted_role_without_creating_diagnostic(tmp_path, monkeypatch):
    memo_dir, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        prepare(memo_dir, tmp_path / 'hosted', coverage_model='claude-pro-sonnet')
    assert not (tmp_path / 'hosted').exists()


def test_historical_flow_cannot_receive_an_independent_coverage_role(tmp_path, monkeypatch):
    memo_dir, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='historical flow'):
        script.run(memo_dir, tmp_path / 'historical', 'prepare', SOURCE, CORE, CORE,
                   flow=script.FLOW_V4, coverage_model=SOURCE)
    assert not (tmp_path / 'historical').exists()


def test_split_flow_is_frozen_and_cannot_downgrade_coverage(tmp_path, monkeypatch):
    memo_dir, sources = setup(tmp_path, monkeypatch)
    output = tmp_path / 'split'
    script.run(memo_dir, output, 'prepare', SOURCE, CORE, CORE,
               flow=script.FLOW_V6, coverage_model=SOURCE)
    request = json.loads((output / 'content_request.json').read_text())
    assert request['coverage_contract'] == diligence_coverage.CONTRACT_V14
    assert request['coverage_pin'] == {'name': SOURCE, 'digest': PINS[SOURCE]}
    assert request['core_author_pin'] == request['core_reviewer_pin'] == {'name': CORE, 'digest': PINS[CORE]}
    assert request['coverage_adjudicator_pin'] == request['core_author_pin']
    assert request['coverage_adjudicator_role'] == 'adjudicator'
    current = diligence_coverage.frozen_coverage_requests(sources, request['coverage_pin'],
        structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'],
        contract=request['coverage_contract'],
        **({'adjudicator_pin': request['coverage_adjudicator_pin']} if 'coverage_adjudicator_pin' in request else {}))
    historical = diligence_coverage.frozen_coverage_requests(sources, request['coverage_pin'],
        structures=request['coverage_structures'], financial_scope=request['coverage_financial_scope'],
        contract=diligence_coverage.CONTRACT_V10)
    assert len(current) == len(historical)
    for fresh, old in zip(current, historical):
        assert fresh[0] != old[0]
        assert fresh[1] == old[1]
        assert fresh[2]['sources'] == old[2]['sources']
        assert fresh[2]['options']['factual_sampling'] is True
        assert 'factual_sampling' not in old[2]['options']
        assert fresh[2]['batch_key'] != old[2]['batch_key']
        assert fresh[3].model_json_schema() == old[3].model_json_schema()
    for flow, contract in ((script.FLOW_V6, diligence_coverage.CONTRACT_V11),
                           (script.FLOW_V5, diligence_coverage.CONTRACT_V12)):
        rejected = tmp_path / (flow + '-wrong-contract')
        with pytest.raises(ValueError, match='exact fresh flow'):
            script.run(memo_dir, rejected, 'prepare', SOURCE, CORE, CORE,
                       flow=flow, coverage_contract=contract, coverage_model=SOURCE)
        assert not rejected.exists()


def test_sharded_flow_requires_its_fresh_contract_and_separate_role(tmp_path, monkeypatch):
    memo_dir, sources = setup(tmp_path, monkeypatch)
    output = tmp_path / 'sharded'
    script.run(memo_dir, output, 'prepare', SOURCE, CORE, CORE,
               flow=script.FLOW_V7, coverage_model=SOURCE, adjudication_model=CORE)
    request = json.loads((output / 'content_request.json').read_text())
    assert request['coverage_contract'] == diligence_coverage.CONTRACT_V15
    assert request['coverage_adjudicator_pin'] == {'name': CORE, 'digest': PINS[CORE]}
    assert request['coverage_pin'] == {'name': SOURCE, 'digest': PINS[SOURCE]}
    assert len(script.phases_for(request['flow_contract'])) == 26
    assert request['section_author_contract'] == 'memo-section-units-author-v13'
    assert request['section_review_contract'] == 'memo-section-units-review-v12'
    for flow, contract in ((script.FLOW_V7, diligence_coverage.CONTRACT_V14),
                           (script.FLOW_V6, diligence_coverage.CONTRACT_V15),
                           (script.FLOW_V5, diligence_coverage.CONTRACT_V15)):
        rejected = tmp_path / (flow + '-wrong-shards')
        with pytest.raises(ValueError, match='exact fresh flow'):
            script.run(memo_dir, rejected, 'prepare', SOURCE, CORE, CORE,
                       flow=flow, coverage_contract=contract, coverage_model=SOURCE)
        assert not rejected.exists()


def test_blind_group_flow_is_distinct_and_preserves_sharded_history(tmp_path, monkeypatch):
    memo_dir, _ = setup(tmp_path, monkeypatch)
    output = tmp_path / 'blind-groups'
    script.run(memo_dir, output, 'prepare', SOURCE, CORE, CORE,
               flow=script.FLOW_V8, coverage_model=SOURCE, adjudication_model=CORE)
    request = json.loads((output / 'content_request.json').read_text())
    assert request['coverage_contract'] == diligence_coverage.CONTRACT_V16
    assert request['coverage_adjudicator_pin'] == {'name': CORE, 'digest': PINS[CORE]}
    assert len(script.phases_for(request['flow_contract'])) == 26
    for flow, contract in ((script.FLOW_V8, diligence_coverage.CONTRACT_V15),
                           (script.FLOW_V7, diligence_coverage.CONTRACT_V16),
                           (script.FLOW_V6, diligence_coverage.CONTRACT_V16)):
        rejected = tmp_path / (flow + '-wrong-blind-groups')
        with pytest.raises(ValueError, match='exact fresh flow'):
            script.run(memo_dir, rejected, 'prepare', SOURCE, CORE, CORE,
                       flow=flow, coverage_contract=contract, coverage_model=SOURCE)
        assert not rejected.exists()


def test_direct_source_flow_cannot_resume_under_a_historical_coverage_contract(tmp_path, monkeypatch):
    memo_dir, _ = setup(tmp_path, monkeypatch)
    output = tmp_path / 'direct-groups'
    script.run(memo_dir, output, 'prepare', SOURCE, CORE, CORE,
               flow=script.FLOW_V10, coverage_model=SOURCE, adjudication_model=CORE)
    request = json.loads((output / 'content_request.json').read_text())
    assert request['coverage_contract'] == diligence_coverage.CONTRACT_V18
    assert request['coverage_adjudicator_pin'] == {'name': CORE, 'digest': PINS[CORE]}
    assert request['coverage_pin'] == {'name': SOURCE, 'digest': PINS[SOURCE]}
    assert len(script.phases_for(request['flow_contract'])) == 21
    assert script.phases_for(request['flow_contract'])[0] == 'diligence_source_adjudication_1'
    for flow, contract in ((script.FLOW_V10, diligence_coverage.CONTRACT_V17),
                           (script.FLOW_V9, diligence_coverage.CONTRACT_V18),
                           (script.FLOW_V5, diligence_coverage.CONTRACT_V18)):
        rejected = tmp_path / (flow + '-wrong-direct-groups')
        with pytest.raises(ValueError, match='exact fresh flow'):
            script.run(memo_dir, rejected, 'prepare', SOURCE, CORE, CORE,
                       flow=flow, coverage_contract=contract, coverage_model=SOURCE)
        assert not rejected.exists()
