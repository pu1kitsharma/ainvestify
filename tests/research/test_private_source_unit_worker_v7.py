"""Fixed shard checkpoints bind exact receipts and preserve all source evidence."""
import copy
import json
from unittest.mock import Mock

import pytest

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.research import diligence_coverage as coverage, memo_section_units as core
from agents.research.investment_memo import Source
from scripts import private_source_unit_worker as worker
from delivery import source_unit_content_stage as stage
from tests.research.test_private_source_unit_worker_v6 import fixture, budget
from tests.research.test_private_source_unit_worker_adjudicator import SOURCE_PIN
from tests.research.test_diligence_coverage import complete_v13_records, synthetic_blind_answer, PIN as ADJUDICATOR_PIN


def inventory():
    return [{'batch_id': 'B1', 'source_ids': []},
            {'batch_id': 'B2', 'source_ids': ['A1'], 'metadata': 'preserved'},
            {'batch_id': 'B3', 'source_ids': []},
            {'batch_id': 'B4', 'source_ids': ['A2']},
            {'batch_id': 'B5', 'source_ids': []}]


def test_claude_receipt_guard_preserves_empty_and_cached_stages_without_calls():
    original = inventory()
    assert worker.should_call_shard(original, 'B1', [], 'B2') is False
    assert worker.should_call_shard(original, 'B2', [], 'B2') is True
    assert worker.should_call_shard(original, 'B3', ['B2'], 'B4') is False
    assert worker.should_call_shard(original, 'B4', ['B2'], 'B4') is True
    assert [worker.should_call_shard(original, item['batch_id'], ['B2', 'B4'], None)
            for item in original] == [False] * 5
    assert original == inventory()


@pytest.mark.parametrize('target,completed,pending', [
    ('B3', [], 'B2'), ('B5', ['B2'], 'B4'), ('B2', ['B4', 'B2'], None),
    ('B2', ['B2', 'B2'], 'B4'), ('B2', ['B9'], 'B2'), ('B2', ['B1'], 'B2'),
    ('B2', [], 'B4'), ('B4', ['B2'], None), ('B9', [], 'B2')])
def test_claude_receipt_guard_rejects_skips_unknowns_duplicates_and_wrong_pending(target, completed, pending):
    with pytest.raises(ValueError):
        worker.should_call_shard(inventory(), target, completed, pending)


@pytest.mark.parametrize('source_count', [22, 16])
@pytest.mark.parametrize('flow,coverage_contract', [(worker.FLOW_V7, coverage.CONTRACT_V15),
                                                  (worker.FLOW_V8, coverage.CONTRACT_V16),
                                                  (worker.FLOW_V9, coverage.CONTRACT_V17)])
def test_sharded_flows_actual_mocked_routes_all_nonempty_shards_and_never_fabricates_empty_receipts(tmp_path, monkeypatch, source_count, flow, coverage_contract):
    request, _, legacy_models = fixture(tmp_path, monkeypatch)
    request.update(flow_contract=flow, coverage_contract=coverage_contract,
        coverage_pin=SOURCE_PIN, coverage_adjudicator_pin=ADJUDICATOR_PIN,
        coverage_adjudicator_role='adjudicator', sources=request['sources'][:source_count])
    reference = complete_v13_records(request['sources'])
    if flow in {worker.FLOW_V8, worker.FLOW_V9}:
        # Preserve the synthetic classifier's inconsistent earlier labels; only
        # the fresh blind model response may reconcile exact duplicate content.
        request['sources'][-1]['passage'] = request['sources'][0]['passage']
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._write(tmp_path, 'content_request.json', request)
    classification_answers = {sid: answer for row in reference[:-2]
                              for sid, answer in row['answer'].items()}
    field_answer = reference[-1]['answer']
    calls = []

    def adapter(name, **options):
        model = LocalModel(name, **options)
        model.client = Mock()

        def transport(**kwargs):
            payload = json.loads(kwargs['messages'][1]['content'])
            task_stage = payload.get('stage', 'classification')
            calls.append((name, task_stage, copy.deepcopy(kwargs['options'])))
            if task_stage == 'source_adjudication' and flow in {worker.FLOW_V8, worker.FLOW_V9}:
                assert 'judgments' not in payload and 'conflict_inventory' not in payload
                assert set(payload['groups']) == set(payload['required_group_ids'])
                assert all('content_kind' not in item and 'category_support' not in item
                           for item in payload['groups'].values())
                if flow == worker.FLOW_V9:
                    # Assert the actual Ollama grammar retains optional own-proof
                    # topic constraints, rather than only checking Pydantic.
                    grammar = kwargs['format']
                    def resolved(node):
                        return grammar['$defs'][node['$ref'].split('/')[-1]] if '$ref' in node else node
                    for gid, group in payload['groups'].items():
                        unit = resolved(grammar['properties'][gid])
                        topics = resolved(unit['properties']['topics'])
                        assert topics['additionalProperties'] is False
                        assert not topics.get('required')
                        assert ('funding_and_ownership' in topics['properties']) == bool(group.get('literal_capital_labels'))
            answer = ({sid: classification_answers[sid] for sid in payload['sources']}
                      if task_stage == 'classification' else
                      synthetic_blind_answer((None, None, payload, None), reference[:-2])
                      if task_stage == 'source_adjudication' and flow in {worker.FLOW_V8, worker.FLOW_V9} else {'patches': []}
                      if task_stage == 'source_adjudication' else field_answer)
            return {'model': name, 'message': {'content': json.dumps(answer)},
                    'done_reason': 'stop', 'prompt_eval_count': 1200, 'eval_count': 40}

        model.client.chat.side_effect = transport
        return model

    monkeypatch.setattr(worker, 'LocalModel', adapter)
    shards = coverage.frozen_adjudication_shards(request['sources'])
    assert len(shards) == 5 and all(len(item['source_ids']) <= 5 for item in shards)
    assert sorted(sid for item in shards for sid in item['source_ids']) == sorted(row['id'] for row in request['sources'])
    empty_count = 0
    for phase in worker.phases_for(flow)[:11]:
        before = len(calls)
        result = worker.advance(tmp_path, phase, budget())
        assert result['state'] == 'needs_resume', result
        if result['reason'] == 'diligence_source_adjudication_empty':
            empty_count += 1
            assert len(calls) == before
    batches = (source_count + 4) // 5
    nonempty = sum(bool(item['source_ids']) for item in shards)
    assert [name for name, _, _ in calls] == [SOURCE_PIN['name']] * batches + [ADJUDICATOR_PIN['name']] * nonempty + [SOURCE_PIN['name']]
    assert empty_count == 5 - nonempty
    assert all(options['presence_penalty'] == 0 and options['repeat_penalty'] == 1 for _, _, options in calls)
    revision = worker.load_source_unit_revision(tmp_path)
    records = revision['diligence_coverage_attempts']
    assert len(records) == batches + nonempty + 1
    assert all(row['input']['contract'] == coverage.CONTRACT_V13 for row in records[:batches])
    assert [row['input']['batch_id'] for row in records[batches:-1]] == [item['batch_id'] for item in shards if item['source_ids']]
    _, binding = core._replay_coverage_v9([Source.model_validate(row) for row in request['sources']],
                                        worker._coverage_bundle(request, revision))
    assert binding['coverage_contract'] == coverage_contract
    if flow in {worker.FLOW_V8, worker.FLOW_V9}:
        evaluated = coverage.evaluate_coverage(request['sources'], SOURCE_PIN, records,
                                              contract=coverage_contract, adjudicator_pin=ADJUDICATOR_PIN)
        assert evaluated['state'] == 'accepted'
        assert len(evaluated['blind_group_assessments']) == source_count - 1
        assert evaluated['reassessed_source_ids'] == [row['id'] for row in request['sources']]
        last_id = request['sources'][-1]['id']
        assert evaluated['judgments'][last_id]['content_kind'] == evaluated['judgments']['S1']['content_kind']
        assert all(eid.startswith(last_id + '.e')
                   for eid in evaluated['judgments'][last_id]['category_support'].values())
    assert binding['adjudicator_pin'] == ADJUDICATOR_PIN
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: pytest.fail('Cached shards cannot infer'))
    for phase in worker.phases_for(flow)[5:11]:
        assert worker.advance(tmp_path, phase, budget())['state'] == 'needs_resume'
    # The eleven coverage slots must preserve the prior source checkpoint order.
    for phase in worker.phases_for(flow)[11:16]:
        result = worker.advance(tmp_path, phase, budget(), models=legacy_models)
        assert result['state'] == 'needs_resume', result
    assert result['next_phase'] == 'memo_section_author_investment_thesis'
    assert len(worker.phases_for(flow)) == 26
    assert stage.flow_config(flow)[0] == worker.phases_for(flow)
    assert worker.PHASES_V9 == worker.PHASES_V8 == worker.PHASES_V7
    assert stage.flow_config(worker.FLOW_V8)[1] == 'content_units_v8'
    assert stage.flow_config(worker.FLOW_V9)[1] == 'content_units_v9'
    assert [len(worker.phases_for(flow)) for flow in (worker.FLOW_V4, worker.FLOW_V5, worker.FLOW_V6)] == [15, 21, 22]
    for old_flow in (candidate for candidate in (worker.FLOW_V5, worker.FLOW_V6, worker.FLOW_V7, worker.FLOW_V8, worker.FLOW_V9, worker.FLOW_V10)
                     if candidate != flow):
        invalid = {**request, 'flow_contract': old_flow}
        invalid['digest'] = digest({key: value for key, value in invalid.items() if key != 'digest'})
        with pytest.raises(ValueError, match='exact frozen'):
            worker._validate_flow5_request(invalid)
