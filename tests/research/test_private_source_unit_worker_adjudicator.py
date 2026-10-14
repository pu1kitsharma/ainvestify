"""The independent adjudicator is frozen and routed only at checkpoint six."""
import copy
import json
from unittest.mock import Mock

import pytest

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.research import diligence_coverage as coverage, memo_section_units as core
from agents.research.investment_memo import Source
from delivery import source_unit_content_stage as stage
from scripts import private_source_unit_worker as worker
from tests.research.test_private_source_unit_worker_v6 import fixture, budget
from tests.research.test_diligence_coverage import complete_v13_records, PIN as ADJUDICATOR_PIN
from tests.delivery.test_source_unit_content_stage_v5 import setup as stage_setup
from tests.delivery.test_source_unit_content_stage_v6 import options as stage_options

SOURCE_PIN = {'name': 'qwen3.5:9b', 'digest': 'b' * 64}


def test_actual_worker_uses_source_model_for_five_batches_and_selector_and_distinct_adjudicator(tmp_path, monkeypatch):
    request, _, _ = fixture(tmp_path, monkeypatch)
    request.update(coverage_contract=coverage.CONTRACT_V14, coverage_pin=SOURCE_PIN,
                   coverage_adjudicator_pin=ADJUDICATOR_PIN, coverage_adjudicator_role='adjudicator')
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._write(tmp_path, 'content_request.json', request)
    expected = complete_v13_records(request['sources'])
    calls = []
    position = [0]

    def adapter(name, **options):
        model = LocalModel(name, **options)
        model.client = Mock()

        def transport(**kwargs):
            payload = json.loads(kwargs['messages'][1]['content'])
            calls.append((name, payload.get('stage', 'classification'), copy.deepcopy(kwargs['options'])))
            index = position[0]
            position[0] += 1
            answer = expected[index]['answer']
            return {'model': name, 'message': {'content': json.dumps(answer)},
                    'done_reason': 'stop', 'prompt_eval_count': 1200, 'eval_count': 40}

        model.client.chat.side_effect = transport
        return model

    monkeypatch.setattr(worker, 'LocalModel', adapter)
    for phase in worker.COVERAGE_PHASES_V6:
        result = worker.advance(tmp_path, phase, budget())
        assert result['state'] == 'needs_resume', result
    assert [name for name, _, _ in calls] == [SOURCE_PIN['name']] * 5 + [ADJUDICATOR_PIN['name'], SOURCE_PIN['name']]
    assert [step for _, step, _ in calls][-2:] == ['source_adjudication', 'field_source_selection']
    assert all(options['presence_penalty'] == 0 and options['repeat_penalty'] == 1 for _, _, options in calls)
    revision = worker.load_source_unit_revision(tmp_path)
    assert revision['coverage_adjudicator_role'] == 'adjudicator'
    assert revision['coverage_adjudicator_pin'] == ADJUDICATOR_PIN
    rows = revision['diligence_coverage_attempts']
    assert len(rows) == 7 and all(row['input']['contract'] == coverage.CONTRACT_V13 for row in rows[:5])
    bundle = worker._coverage_bundle(request, revision)
    scopes, binding = core._replay_coverage_v9([Source.model_validate(row) for row in request['sources']], bundle)
    assert binding['model_pin'] == SOURCE_PIN and binding['adjudicator_pin'] == ADJUDICATOR_PIN
    assert scopes == rows[-1]['answer'] and binding['coverage_contract'] == coverage.CONTRACT_V14
    assert len(binding['response_ids']) == 7
    changed = copy.deepcopy(bundle)
    changed['adjudicator_pin'] = SOURCE_PIN
    with pytest.raises(ValueError, match='incomplete or blocked'):
        core._replay_coverage_v9([Source.model_validate(row) for row in request['sources']], changed)
    for key in ('coverage_adjudicator_pin', 'coverage_adjudicator_role'):
        invalid = copy.deepcopy(request)
        invalid.pop(key)
        invalid['digest'] = digest({name: value for name, value in invalid.items() if name != 'digest'})
        with pytest.raises(ValueError, match='exact frozen'):
            worker._validate_flow5_request(invalid)
    # Replay the separate stages without starting either model.
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: pytest.fail('Cached role proof must replay'))
    assert worker.advance(tmp_path, 'diligence_source_adjudication', budget())['next_phase'] == 'diligence_field_selection'
    assert worker.advance(tmp_path, 'diligence_field_selection', budget())['next_phase'] == 'source_characterization'


def configured_stage(monkeypatch):
    accepted, sources, profile, _ = stage_setup(monkeypatch)
    profile['profiles']['prose'] = 'qwen3:14b'
    profile['memo_role_model_digests']['prose'] = 'a' * 64
    configured = {**stage_options(), 'coverage_contract': coverage.CONTRACT_V14,
                  'coverage_adjudicator_role': 'prose'}
    return accepted, sources, profile, configured


def test_production_adjudicator_has_own_frozen_role_digest_without_fallback(tmp_path, monkeypatch):
    accepted, sources, profile, configured = configured_stage(monkeypatch)
    missing = copy.deepcopy(profile)
    missing['memo_role_model_digests'].pop('prose')
    missing['memo_author_model_digest'] = 'a' * 64
    with pytest.raises(ValueError, match='own exact frozen role digest'):
        stage._request(tmp_path, accepted, sources, missing, create=True, **configured)
    request = stage._request(tmp_path, accepted, sources, profile, create=True, **configured)
    assert request['coverage_adjudicator_role'] == 'prose'
    assert request['coverage_adjudicator_pin'] == {'name': 'qwen3:14b', 'digest': 'a' * 64}
    assert request['coverage_pin'] == SOURCE_PIN
    for changed in ({'coverage_adjudicator_role': 'review'}, {'coverage_adjudicator_role': None},
                    {'coverage_contract': coverage.CONTRACT_V13}):
        with pytest.raises(ValueError):
            stage._request(tmp_path, accepted, sources, profile, **{**configured, **changed})
    altered = copy.deepcopy(request)
    altered['coverage_adjudicator_pin'] = dict(SOURCE_PIN)
    altered['digest'] = digest({key: value for key, value in altered.items() if key != 'digest'})
    (tmp_path / 'content_request.json').write_text(json.dumps(altered))
    with pytest.raises(ValueError, match='adjudicator differs'):
        stage._request(tmp_path, accepted, sources, profile, **configured)


def test_production_rechecks_adjudicator_installed_digest_at_actual_sixth_checkpoint(tmp_path, monkeypatch):
    accepted, sources, profile, configured = configured_stage(monkeypatch)
    root = tmp_path / stage.ROOT_NAME_V6
    root.mkdir()
    stage._request(root, accepted, sources, profile, create=True, **configured)
    (root / 'content_passes.json').write_text(json.dumps([
        {'pass': number, 'phase': phase, 'state': 'needs_resume'}
        for number, phase in enumerate(stage.COVERAGE_PHASES_V6[:5], 1)]))
    (root / 'content_result.json').write_text(json.dumps({'state': 'needs_resume',
        'next_phase': 'diligence_source_adjudication'}))
    monkeypatch.setattr(stage, '_inventory', lambda: {'qwen3.5:9b': 'b' * 64, 'qwen3:14b': 'c' * 64})
    monkeypatch.setattr(stage, 'run_private', lambda *args, **kwargs: pytest.fail('Changed adjudicator must not run'))
    result = stage.run_source_unit_pass(tmp_path, accepted, sources, profile, timeout=110, **configured)
    assert result['state'] == 'blocked' and result['reason'] == 'source_unit_installed_model_changed'
