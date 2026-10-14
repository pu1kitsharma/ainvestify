"""Adjudicated local judgments precede separately constrained field selection."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.research import diligence_coverage as coverage, memo_section_units as core
from agents.research.investment_memo import Source
from scripts import private_source_unit_worker as worker
from delivery import source_unit_content_stage as stage
from tests.research.test_private_source_unit_worker_v5 import setup as old_setup
from tests.research.test_diligence_coverage import sources, complete_v10_records, recorded_row, PIN


def fixture(root, monkeypatch):
    request, _, models = old_setup(root, monkeypatch)
    rows = sources(22)
    rows[3]['passage'] = 'Reported targets\nRevenue INR million 20\nEquity raised INR million 3'
    rows[5]['passage'] = 'Synthetic heading\nTomorrow\nSynthetic Future'
    rows[6]['passage'] = 'Contact: synthetic@example.invalid'
    request.update(flow_contract=worker.FLOW_V6, sources=rows,
        coverage_pin=PIN, coverage_contract=coverage.CONTRACT_V12,
        section_author_contract='memo-section-units-author-v13',
        section_review_contract='memo-section-units-review-v12')
    request['digest'] = digest(request)
    worker._write(root, 'content_request.json', request)
    return request, complete_v10_records(rows)[:-1], models


def budget():
    return SimpleNamespace(calls=0, max_calls=6, remaining=lambda: 105)


@pytest.mark.parametrize('coverage_contract', ['diligence-source-coverage-v12', 'diligence-source-coverage-v13'])
def test_flow6_freezes_22_phases_and_rejects_contract_downgrades(tmp_path, monkeypatch, coverage_contract):
    request, prefix, _ = fixture(tmp_path, monkeypatch)
    request['coverage_contract'] = coverage_contract
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._validate_flow5_request(request)
    assert worker.phases_for(worker.FLOW_V6) == stage.PHASES_V6
    assert len(stage.PHASES_V6) == 22 and len(stage.PHASES_V5) == 21
    assert stage.PHASES_V6[5:7] == ('diligence_source_adjudication', 'diligence_field_selection')
    assert stage.PHASES_V6[7:] == stage.PHASES_V4
    assert len(prefix) == 5
    assert all(row['input']['contract'] == coverage.CONTRACT_V10 for row in prefix)
    if coverage_contract == 'diligence-source-coverage-v13':
        fresh = coverage.frozen_coverage_requests(request['sources'], PIN, contract=coverage_contract)
        assert len(fresh) == 5
        assert all(row[2]['contract'] == coverage_contract and row[2]['options']['factual_sampling'] is True
                   for row in fresh)
        assert coverage.evaluate_coverage(request['sources'], PIN, prefix,
                                         contract=coverage_contract)['state'] == 'blocked'
        for source in request['sources']:
            assert core._coverage_source_views(Source.model_validate(source), coverage_contract) == coverage.source_views_for_coverage(source, coverage_contract)
    for changes in ({'flow_contract': worker.FLOW_V5},
                    {'coverage_contract': coverage.CONTRACT_V11},
                    {'section_author_contract': 'memo-section-units-author-v12',
                     'section_review_contract': 'memo-section-units-review-v11'}):
        altered = {**request, **changes}
        altered['digest'] = digest({key: value for key, value in altered.items() if key != 'digest'})
        with pytest.raises(ValueError, match='exact frozen'):
            worker._validate_flow5_request(altered)


def test_flow6_records_adjudication_before_selecting_from_exact_new_enums(tmp_path, monkeypatch):
    request, prefix, _ = fixture(tmp_path, monkeypatch)
    worker._write(tmp_path, 'diligence_coverage_attempts.json', prefix)
    old_prefix = copy.deepcopy(prefix)
    options_sent = []
    transports = []

    def adapter(name, **options):
        options_sent.append(copy.deepcopy(options))
        model = LocalModel(name, **options)
        model.client = Mock()

        def transport(**kwargs):
            payload = json.loads(kwargs['messages'][1]['content'])
            transports.append(copy.deepcopy(kwargs['options']))
            if payload['stage'] == 'source_adjudication':
                answer = {'patches': []}
            else:
                assert payload['stage'] == 'field_source_selection'
                assert len(options_sent) == 2
                answer = {'investment_thesis': ['S1'], 'business_and_market': ['S1', 'S2'],
                          'differentiation_and_execution': ['S3'],
                          'risks_and_countercase': ['S2'], 'diligence_plan': ['S4']}
            return {'model': name, 'message': {'content': json.dumps(answer)},
                    'done_reason': 'stop', 'prompt_eval_count': 1200, 'eval_count': 40}

        model.client.chat.side_effect = transport
        return model

    monkeypatch.setattr(worker, 'LocalModel', adapter)
    first = worker.advance(tmp_path, 'diligence_source_adjudication', budget())
    assert first['state'] == 'needs_resume' and first['next_phase'] == 'diligence_field_selection'
    rows = worker._load(tmp_path, 'diligence_coverage_attempts.json')
    assert len(rows) == 6 and rows[:5] == old_prefix
    assert rows[-1]['answer'] == {'patches': []}
    pending = coverage.pending_coverage_request(request['sources'], PIN, rows, contract=coverage.CONTRACT_V12)
    selection_input = pending[2]
    assert selection_input['stage'] == 'field_source_selection'
    schema = pending[3].model_json_schema()
    assert set(schema['properties']) == set(core.FIELDS)
    invalid = {'investment_thesis': ['S1'], 'business_and_market': ['S1', 'S2'],
               'differentiation_and_execution': ['S6'],
               'risks_and_countercase': ['S2'], 'diligence_plan': ['S4']}
    with pytest.raises(ValueError):
        pending[3].model_validate(invalid)
    final = worker.advance(tmp_path, 'diligence_field_selection', budget())
    assert final['state'] == 'needs_resume' and final['next_phase'] == 'source_characterization'
    rows = worker._load(tmp_path, 'diligence_coverage_attempts.json')
    assert len(rows) == 7 and rows[:5] == old_prefix
    result = coverage.evaluate_coverage(request['sources'], PIN, rows, contract=coverage.CONTRACT_V12)
    assert result['state'] == 'accepted' and result['field_source_ids'] == rows[-1]['answer']
    assert all(options['factual_sampling'] is True for options in options_sent)
    assert all(options['presence_penalty'] == 0 and options['repeat_penalty'] == 1 for options in transports)
    assert all(row['routing']['factual_sampling'] is True and row['routing']['sampling']['presence_penalty'] == 0
               for row in rows[5:])
    bundle = worker._coverage_bundle(request, {'diligence_coverage_attempts': rows})
    scoped, binding = core._replay_coverage_v9([Source.model_validate(row) for row in request['sources']], bundle)
    assert scoped == rows[-1]['answer'] and binding['coverage_contract'] == coverage.CONTRACT_V12
    assert len(binding['response_ids']) == 7 and binding['source_content_kinds']['S6'] == 'heading_only'
    for index in (5, 6):
        tampered = copy.deepcopy(rows)
        tampered[index]['routing']['sampling']['presence_penalty'] = 1.5
        assert coverage.evaluate_coverage(request['sources'], PIN, tampered,
                                         contract=coverage.CONTRACT_V12)['state'] == 'blocked'
    # Cached checkpoints verify the same raw lineage without inference.
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: pytest.fail('Cached calls must replay'))
    assert worker.advance(tmp_path, 'diligence_source_adjudication', budget())['next_phase'] == 'diligence_field_selection'
    assert worker.advance(tmp_path, 'diligence_field_selection', budget())['next_phase'] == 'source_characterization'


def test_flow6_cannot_skip_adjudication_or_start_core_from_unselected_sources(tmp_path, monkeypatch):
    request, prefix, _ = fixture(tmp_path, monkeypatch)
    worker._write(tmp_path, 'diligence_coverage_attempts.json', prefix)
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: pytest.fail('Incomplete prerequisite must block'))
    for phase in ('diligence_field_selection', 'source_characterization'):
        result = worker.advance(tmp_path, phase, budget())
        assert result['state'] == 'blocked'
    assert worker._load(tmp_path, 'diligence_coverage_attempts.json') == prefix
