"""Separate local source tasks retain two real rows under each fixed checkpoint."""
import copy
import json
from unittest.mock import Mock, AsyncMock

import pytest

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research import diligence_coverage as coverage, memo_section_units as core
from agents.research import source_interpretation_pair as pair_engine
from agents.research.investment_memo import Source
from delivery import source_unit_content_stage as stage
from scripts import private_source_unit_worker as worker
from tests.research.test_private_source_unit_worker_adjudicator import SOURCE_PIN, ADJUDICATOR_PIN
from tests.research.test_private_source_unit_worker_v6 import fixture


def setup_pair(root, monkeypatch, count=8):
    request, _, _ = fixture(root, monkeypatch)
    request['sources'] = request['sources'][:count]
    request['sources'][1]['passage'] = 'The report estimates industry demand at INR million 12.'
    request['sources'][2]['passage'] = 'The report names Person Z as chief executive with prior engineering experience.'
    request['sources'][4]['passage'] = 'The report states that supplier concentration poses a material risk.'
    request['sources'][-1]['passage'] = request['sources'][0]['passage']
    request.update(flow_contract=worker.FLOW_V12, coverage_contract=coverage.CONTRACT_V20,
        coverage_pin=SOURCE_PIN, coverage_adjudicator_pin=ADJUDICATOR_PIN,
        coverage_adjudicator_role='author', coverage_batching_contract=pair_engine.CONTRACT)
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._write(root, 'content_request.json', request)
    topics = {'S1': ['product_and_customers'], 'S2': ['market_and_competition'],
        'S3': ['team_and_governance'], 'S4': ['financial_evidence', 'funding_and_ownership'], 'S5': ['risks']}
    selected = {'investment_thesis': ['S1'], 'business_and_market': ['S1', 'S2'],
        'differentiation_and_execution': ['S3'], 'risks_and_countercase': ['S5'], 'diligence_plan': ['S4']}
    calls = []
    def adapter(name, **options):
        model = LocalModel(name, **options)
        def transport(**kwargs):
            payload = json.loads(kwargs['messages'][1]['content'])
            calls.append((name, copy.deepcopy(payload)))
            if payload['stage'] == 'source_interpretation_pair':
                group = payload['group']; sid = group['members'][0]['id']
                if payload['substage'] == 'topic_extraction':
                    assert 'content_kind' not in json.dumps(kwargs['format'])
                    cats = [] if sid in {'S6', 'S7'} else topics.get(sid, ['product_and_customers'])
                    answer = {'supported_topics': [{'quote': group['passage'], 'topic': category, 'basis': 'reported'} for category in cats], 'group_id': group['group_id']}
                else:
                    assert payload['topic_response_hash'] and payload['topic_response_id']
                    assert payload['topic_proposal']['group_id'] == group['group_id']
                    answer = {'group_id': group['group_id'], 'content_kind': 'heading_only' if sid == 'S6' else 'contact_only' if sid == 'S7' else 'information'}
            else:
                answer = selected
            return {'model': name, 'message': {'content': json.dumps(answer)}, 'done_reason': 'stop', 'prompt_eval_count': 1200, 'eval_count': 200}
        model.client = Mock(); model.client.chat.side_effect = transport
        client = Mock(); client.chat = AsyncMock(side_effect=transport); client._client.aclose = AsyncMock()
        monkeypatch.setattr('agents.inference.local_models.ollama.AsyncClient', lambda **kwargs: client)
        return model
    monkeypatch.setattr(worker, 'LocalModel', adapter)
    return request, calls


def test_flow12_has_41_fixed_checkpoints_with_two_actual_model_rows_and_complete_quotes(tmp_path, monkeypatch):
    request, calls = setup_pair(tmp_path, monkeypatch)
    for phase in worker.COVERAGE_PHASES_V12:
        before = len(calls); limits = PreparationBudget(105, max_calls=6, max_requests=6)
        with preparation_budget(limits): result = worker.advance(tmp_path, phase, limits)
        assert result['state'] == 'needs_resume', result
        assert limits.calls == limits.requests == len(calls) - before
        assert limits.calls <= (1 if phase == 'diligence_field_selection' else 2)
    revision = worker.load_source_unit_revision(tmp_path)
    result = worker._coverage_result(request, revision)
    assert result['state'] == 'accepted' and result['coverage_complete'] is True
    assert len(calls) == 2 * 7 + 1
    assert len(result['logical_pair_receipts']) == 7
    assert all(receipt['is_model_row'] is False for receipt in result['logical_pair_receipts'])
    assert len(revision['diligence_coverage_attempts']) == 15
    assert all('raw_response' in row for row in revision['diligence_coverage_attempts'])
    assert result['total_source_call_limit'] == 51 and result['assessment_call_limit'] == 50
    assert result['financial_validation'] == result['investment_approval'] == 'not_established'
    assert len(worker.PHASES_V12) == 41 and stage.flow_config(worker.FLOW_V12)[1] == 'content_units_v12'
    scoped, binding = core._replay_coverage_v9([Source.model_validate(row) for row in request['sources']], worker._coverage_bundle(request, revision))
    assert binding['coverage_contract'] == coverage.CONTRACT_V20 and scoped == result['field_source_ids']
    frozen = core.frozen_requests(request['memo'], request['sources'], request['core_author_pin'], contract=core.CONTRACT_V13, coverage=worker._coverage_bundle(request, revision))
    assert core.frozen_offered_spans(request['sources'], frozen)['S4.q001']['exact_text'] == request['sources'][3]['passage']
    previous = copy.deepcopy(revision)
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: pytest.fail('Committed source pairs must replay'))
    for phase in worker.COVERAGE_PHASES_V12:
        assert worker.advance(tmp_path, phase, PreparationBudget(105,6,6))['state'] == 'needs_resume'
    assert worker.load_source_unit_revision(tmp_path) == previous


def test_flow12_committed_topic_prefix_resumes_kind_only_and_unknown_inflight_blocks(tmp_path, monkeypatch):
    request, calls = setup_pair(tmp_path, monkeypatch)
    limits = PreparationBudget(105, max_calls=6, max_requests=1)
    with preparation_budget(limits): result = worker.advance(tmp_path, worker.COVERAGE_PHASES_V12[0], limits)
    # A real failed request cannot be reopened, even with a valid first answer.
    assert result['state'] == 'blocked' and len(calls) == 1
    rows = worker._load(tmp_path, 'diligence_coverage_attempts.json')
    assert len(rows) == 2 and rows[-1]['error']
    assert worker.source_pair_resume_state(tmp_path, request, worker.COVERAGE_PHASES_V12[0])['state'] == 'blocked'
    original = copy.deepcopy(rows)
    assert worker.advance(tmp_path, worker.COVERAGE_PHASES_V12[0], PreparationBudget(105,6,6))['state'] == 'blocked'
    assert worker._load(tmp_path, 'diligence_coverage_attempts.json') == original


def test_flow12_crash_after_saved_topics_calls_only_unread_kind_and_retains_events(tmp_path, monkeypatch):
    request, calls = setup_pair(tmp_path, monkeypatch)
    worker._write(tmp_path, 'content_budget.json', {'seconds': 105, 'max_calls': 6})
    real_write = worker._write
    def crash_after_first_record(root, filename, value):
        real_write(root, filename, value)
        if filename == 'diligence_coverage_attempts.json' and len(value) == 1:
            raise KeyboardInterrupt('Synthetic process interruption after durable response')
    monkeypatch.setattr(worker, '_write', crash_after_first_record)
    limits = PreparationBudget(105,6,6)
    with pytest.raises(KeyboardInterrupt), preparation_budget(limits):
        worker.advance(tmp_path, worker.COVERAGE_PHASES_V12[0], limits)
    monkeypatch.setattr(worker, '_write', real_write)
    original = worker._load(tmp_path, 'diligence_coverage_attempts.json')
    assert len(original) == len(calls) == 1
    interrupted = worker.record_source_pair_interruption(tmp_path, request, worker.COVERAGE_PHASES_V12[0], 0.5)
    assert interrupted['state'] == 'needs_resume' and interrupted['remaining_seconds'] == 104.5
    events = (tmp_path / worker.PAIR_RECOVERY_EVENTS).read_bytes()
    remaining = worker.source_pair_recovery_budget(tmp_path, request, interrupted)
    limits = PreparationBudget(remaining,6,6)
    with preparation_budget(limits): result = worker.advance(tmp_path, worker.COVERAGE_PHASES_V12[0], limits)
    assert result['state'] == 'needs_resume' and limits.calls == limits.requests == 1
    assert [payload['substage'] for _, payload in calls] == ['topic_extraction', 'content_kind']
    assert worker._load(tmp_path, 'diligence_coverage_attempts.json')[:1] == original
    assert (tmp_path / worker.PAIR_RECOVERY_EVENTS).read_bytes() == events
    # An intent without the corresponding durable actual response cannot retry.
    intent = worker._load(tmp_path, worker.PAIR_INTENT_FILE)
    worker._write(tmp_path, worker.PAIR_INTENT_FILE, {**intent, 'state': 'started', 'record_count_before': 2})
    before = len(calls)
    assert worker.advance(tmp_path, worker.COVERAGE_PHASES_V12[0], PreparationBudget(105,6,6))['state'] == 'blocked'
    assert len(calls) == before


def test_explicit_pair_v2_freezes_different_stage_options_and_preserves_v1(tmp_path, monkeypatch):
    request, _ = setup_pair(tmp_path, monkeypatch)
    source_rows = request['sources'][:2]
    common = {'contract': coverage.CONTRACT_V20, 'adjudicator_pin': ADJUDICATOR_PIN}
    default = coverage.frozen_coverage_requests(source_rows, SOURCE_PIN, **common)
    explicit_v1 = coverage.frozen_coverage_requests(source_rows, SOURCE_PIN,
        interpretation_contract=pair_engine.CONTRACT, **common)
    old = [(task, instruction, copy.deepcopy(payload), schema.model_json_schema()) for task, instruction, payload, schema in default]
    assert old == [(task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in explicit_v1]
    v2 = coverage.frozen_coverage_requests(source_rows, SOURCE_PIN,
        interpretation_contract=pair_engine.CONTRACT_V2, **common)
    assert v2[0][2]['options']['reasoning_budget'] == 1024
    assert v2[0][2]['options']['max_tokens'] == 1724
    assert v2[0][2]['options']['thinking'] is True
    assert v2[0][2]['options']['bounded_thinking_contract'] == 'local-bounded-thinking-v1'
    pairs = pair_engine.frozen_source_pairs(source_rows, ADJUDICATOR_PIN, contract=pair_engine.CONTRACT_V2)
    assert pairs[0]['kind_options']['thinking'] is False
    assert pairs[0]['kind_options']['max_tokens'] == 700
    assert pairs[0]['topic_options'] != pairs[0]['kind_options']
    assert [(task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in default] == old
    assert v2[0][2]['group'] == default[0][2]['group']
    assert v2[0][2]['schema_order_digest'] == default[0][2]['schema_order_digest']
    request['coverage_batching_contract'] = pair_engine.CONTRACT_V2
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._validate_flow5_request(request)
    assert stage.flow_config(worker.FLOW_V12) == (worker.PHASES_V12, 'content_units_v12')
