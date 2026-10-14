"""Quote-first local assessments bind fresh scopes without old status aliases."""
import copy
import json
from unittest.mock import Mock, AsyncMock

import pytest

from agents.inference.local_models import LocalModel, generation_schema
from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research import diligence_coverage as coverage, memo_section_units as core
from agents.research import source_interpretation
from agents.research.investment_memo import Source
from delivery import source_unit_content_stage as stage
from scripts import private_source_unit_worker as worker
from tests.research.test_private_source_unit_worker_adjudicator import SOURCE_PIN, ADJUDICATOR_PIN
from tests.research.test_private_source_unit_worker_v6 import fixture, budget


@pytest.mark.parametrize('source_count, interpretation_contract', [(22, source_interpretation.CONTRACT_V2), (8, source_interpretation.CONTRACT_V2), (8, source_interpretation.CONTRACT_V3)])
def test_flow11_uses_static_quote_first_grammar_independent_role_and_exact_core_views(tmp_path, monkeypatch, source_count, interpretation_contract):
    request, _, _ = fixture(tmp_path, monkeypatch)
    request['sources'] = request['sources'][:source_count]
    request['sources'][1]['passage'] = 'The report estimates industry demand at INR million 12.'
    request['sources'][2]['passage'] = 'The report names Person Z as chief executive with prior engineering experience.'
    request['sources'][4]['passage'] = 'The report states that supplier concentration poses a material risk.'
    request['sources'][-1]['passage'] = request['sources'][0]['passage']
    request.update(flow_contract=worker.FLOW_V11, coverage_contract=coverage.CONTRACT_V19,
        coverage_pin=SOURCE_PIN, coverage_adjudicator_pin=ADJUDICATOR_PIN,
        coverage_adjudicator_role='challenge', coverage_batching_contract=interpretation_contract)
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._write(tmp_path, 'content_request.json', request)
    calls = []
    selected = {'investment_thesis': ['S1'], 'business_and_market': ['S1', 'S2'],
        'differentiation_and_execution': ['S3'], 'risks_and_countercase': ['S5'], 'diligence_plan': ['S4']}
    topics = {'S1': ['product_and_customers'], 'S2': ['market_and_competition'],
        'S3': ['team_and_governance'], 'S4': ['financial_evidence', 'funding_and_ownership'],
        'S5': ['risks']}
    def adapter(name, **options):
        model = LocalModel(name, **options)
        model.client = Mock()
        def transport(**kwargs):
            payload = json.loads(kwargs['messages'][1]['content'])
            calls.append((name, payload['stage'], kwargs['options']['num_predict']))
            if payload['stage'] == 'source_adjudication':
                assert payload['contract'] == interpretation_contract
                assert kwargs['format'] == generation_schema(source_interpretation.AtomicAssessmentBatch, bound_strings=True)
                assert 'category_aliases' not in payload and 'judgments' not in payload
                assert len(payload['groups']) == 1
                assessments = []
                for group in payload['groups']:
                    sid = group['members'][0]['id']
                    kind = 'heading_only' if sid == 'S6' else 'contact_only' if sid == 'S7' else 'information'
                    cats = [] if kind in {'heading_only', 'contact_only'} else topics.get(sid, ['product_and_customers'])
                    assessments.append({'group_id': group['group_id'], 'content_kind': kind,
                        'supported_topics': [{'quote': group['passage'], 'topic': category, 'basis': 'reported'}
                                             for category in cats]})
                answer = {'assessments': assessments}
            else:
                assert payload['contract'] == coverage.CONTRACT_V19
                assert payload['exact_topic_quote_spans']['S1']['S1.q001']['exact_text'] == request['sources'][0]['passage']
                answer = selected
            return {'model': name, 'message': {'content': json.dumps(answer)},
                'done_reason': 'stop', 'prompt_eval_count': 1200, 'eval_count': 200}
        model.client.chat.side_effect = transport
        async_client = Mock()
        async_client.chat = AsyncMock(side_effect=transport)
        async_client._client.aclose = AsyncMock()
        monkeypatch.setattr('agents.inference.local_models.ollama.AsyncClient', lambda **kwargs: async_client)
        return model
    monkeypatch.setattr(worker, 'LocalModel', adapter)
    for phase in worker.COVERAGE_PHASES_V11:
        before = len(calls)
        limits = PreparationBudget(105, max_calls=6, max_requests=6)
        with preparation_budget(limits):
            result = worker.advance(tmp_path, phase, limits)
        assert result['state'] == 'needs_resume', result
        assert limits.calls == limits.requests == len(calls) - before
        assert limits.calls <= (1 if phase == 'diligence_field_selection' else 5)
    revision = worker.load_source_unit_revision(tmp_path)
    records = revision['diligence_coverage_attempts']
    assessed_count = len(coverage.frozen_coverage_requests(request['sources'], SOURCE_PIN,
        contract=coverage.CONTRACT_V19, adjudicator_pin=ADJUDICATOR_PIN, interpretation_contract=interpretation_contract))
    assert [name for name, _, _ in calls] == [ADJUDICATOR_PIN['name']] * assessed_count + [SOURCE_PIN['name']]
    assert [limit for _, _, limit in calls] == [700] * (assessed_count + 1)
    assert len(records) == assessed_count + 1 <= 26
    assert assessed_count == source_count - 1
    result = worker._coverage_result(request, revision)
    assert result['state'] == 'accepted' and result['financial_validation'] == 'not_established'
    assert result['assessment_contract'] == interpretation_contract
    assert result['field_source_ids'] == selected
    assert result['judgments']['S1']['category_support'] == {'product_and_customers': 'S1.q001'}
    last = request['sources'][-1]['id']
    assert result['judgments'][last]['category_support'] == {'product_and_customers': last + '.q001'}
    assert result['judgments']['S1']['topic_basis'] == {'product_and_customers': 'reported'}
    _, binding = core._replay_coverage_v9([Source.model_validate(row) for row in request['sources']],
        worker._coverage_bundle(request, revision))
    assert binding['coverage_contract'] == coverage.CONTRACT_V19
    assert binding['adjudicator_pin'] == ADJUDICATOR_PIN
    memo_requests = core.frozen_requests(request['memo'], request['sources'], request['core_author_pin'],
        contract=core.CONTRACT_V13, coverage=worker._coverage_bundle(request, revision))
    for _, payload, _ in memo_requests:
        for sid, offered in payload['sources'].items():
            assert offered['full_source_passage'] == next(row['passage'] for row in request['sources'] if row['id'] == sid)
            assert all(eid.startswith(sid + '.q') for eid in offered['spans'])
    assert core.frozen_offered_spans(request['sources'], memo_requests)['S4.q001']['exact_text'] == request['sources'][3]['passage']
    broken = copy.deepcopy(binding['literal_quote_inventory'])
    broken['S1']['S1.q001']['start'] = 1
    with pytest.raises(ValueError, match='quote/source/offset'):
        core._coverage_source_views(Source.model_validate(request['sources'][0]), coverage.CONTRACT_V19, broken)
    assert len(worker.PHASES_V11) == 21 and worker.PHASES_V11[6:] == worker.PHASES_V4
    assert stage.flow_config(worker.FLOW_V11) == (worker.PHASES_V11, 'content_units_v11')
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: pytest.fail('Cached exact quotes must replay'))
    for phase in worker.COVERAGE_PHASES_V11:
        assert worker.advance(tmp_path, phase, budget())['state'] == 'needs_resume'
    for changes in ({'flow_contract': worker.FLOW_V10}, {'coverage_contract': coverage.CONTRACT_V18}):
        wrong = {**request, **changes}
        wrong['digest'] = digest({key: value for key, value in wrong.items() if key != 'digest'})
        with pytest.raises(ValueError, match='exact frozen'):
            worker._validate_flow5_request(wrong)
    corrupt = copy.deepcopy(revision)
    corrupt['diligence_coverage_attempts'][0]['routing']['model'] = SOURCE_PIN['name']
    assert worker._coverage_result(request, corrupt)['state'] == 'blocked'
    for key, value in [('done_reason', 'length'), ('generated_tokens', 701), ('generated_tokens', True)]:
        corrupt = copy.deepcopy(revision)
        corrupt['diligence_coverage_attempts'][-1]['routing'][key] = value
        assert worker._coverage_result(request, corrupt)['state'] == 'blocked'
    corrupt = copy.deepcopy(revision)
    record = corrupt['diligence_coverage_attempts'][-1]
    record['raw_response'] = 'prefix ' + record['raw_response']
    record['response_hash'] = digest(record['raw_response'])
    assert worker._coverage_result(request, corrupt)['state'] == 'blocked'


def test_flow11_requires_replayed_quote_inventory_and_preserves_old_defaults():
    row = Source.model_validate({'id': 'S1', 'url': 'private://synthetic', 'title': 'Synthetic',
        'version': 'version1', 'attribution': 'Reported', 'passage': 'The source reports a software product.'})
    with pytest.raises(ValueError, match='source/version'):
        coverage.source_views_for_coverage(row, coverage.CONTRACT_V19)
    with pytest.raises(ValueError, match='replayed literal quote'):
        core._coverage_source_views(row, coverage.CONTRACT_V19)
    assert coverage.options_for(coverage.CONTRACT_V18, 'source_adjudication')['max_tokens'] == 700
    assert coverage.options_for(coverage.CONTRACT_V19, 'source_adjudication')['max_tokens'] == 700
    assert coverage.options_for(coverage.CONTRACT_V19, 'field_source_selection')['max_tokens'] == 700


def test_flow11_shared_request_budget_retains_success_prefix_and_blocks_without_retry(tmp_path, monkeypatch):
    request, _, _ = fixture(tmp_path, monkeypatch)
    request['sources'] = request['sources'][:2]
    request.update(flow_contract=worker.FLOW_V11, coverage_contract=coverage.CONTRACT_V19,
        coverage_pin=SOURCE_PIN, coverage_adjudicator_pin=ADJUDICATOR_PIN,
        coverage_adjudicator_role='challenge', coverage_batching_contract=source_interpretation.CONTRACT_V2)
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._write(tmp_path, 'content_request.json', request)
    transports = []
    def adapter(name, **options):
        model = LocalModel(name, **options)
        model.client = Mock()
        def transport(**kwargs):
            payload = json.loads(kwargs['messages'][1]['content'])
            transports.append(payload['request_id'])
            group = payload['groups'][0]
            answer = {'assessments': [{'group_id': group['group_id'], 'content_kind': 'information',
                'supported_topics': [{'quote': group['passage'], 'topic': 'product_and_customers', 'basis': 'reported'}]}]}
            return {'model': name, 'message': {'content': json.dumps(answer)},
                'done_reason': 'stop', 'prompt_eval_count': 1200, 'eval_count': 200}
        model.client.chat.side_effect = transport
        async_client = Mock()
        async_client.chat = AsyncMock(side_effect=transport)
        async_client._client.aclose = AsyncMock()
        monkeypatch.setattr('agents.inference.local_models.ollama.AsyncClient', lambda **kwargs: async_client)
        return model
    monkeypatch.setattr(worker, 'LocalModel', adapter)
    limits = PreparationBudget(105, max_calls=6, max_requests=1)
    with preparation_budget(limits):
        result = worker.advance(tmp_path, worker.COVERAGE_PHASES_V11[0], limits)
    assert result['state'] == 'blocked'
    assert limits.requests == 1 and len(transports) == 1
    rows = worker._load(tmp_path, 'diligence_coverage_attempts.json')
    assert len(rows) == 2 and rows[0]['answer']['assessments'][0]['group_id'] == 'G1'
    assert rows[1].get('answer') is None and rows[1]['error']
    before = copy.deepcopy(rows)
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: pytest.fail('Failed atomic prefix cannot retry'))
    assert worker.advance(tmp_path, worker.COVERAGE_PHASES_V11[0], budget())['state'] == 'blocked'
    assert worker._load(tmp_path, 'diligence_coverage_attempts.json') == before


def test_explicit_v4_dispatch_keeps_v2_default_and_v3_frozen_requests(tmp_path, monkeypatch):
    request, _, _ = fixture(tmp_path, monkeypatch)
    request['sources'] = request['sources'][:2]
    request.update(flow_contract=worker.FLOW_V11, coverage_contract=coverage.CONTRACT_V19,
        coverage_pin=SOURCE_PIN, coverage_adjudicator_pin=ADJUDICATOR_PIN,
        coverage_adjudicator_role='author', coverage_batching_contract='source-interpretation-evidence-first-v4')
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._validate_flow5_request(request)
    common = {'contract': coverage.CONTRACT_V19, 'adjudicator_pin': ADJUDICATOR_PIN}
    default = coverage.frozen_coverage_requests(request['sources'], SOURCE_PIN, **common)
    v2 = coverage.frozen_coverage_requests(request['sources'], SOURCE_PIN,
        interpretation_contract='source-interpretation-evidence-first-v2', **common)
    v3 = coverage.frozen_coverage_requests(request['sources'], SOURCE_PIN,
        interpretation_contract='source-interpretation-evidence-first-v3', **common)
    v3_snapshot = [(task, instruction, copy.deepcopy(payload), schema.model_json_schema())
                   for task, instruction, payload, schema in v3]
    v4 = coverage.frozen_coverage_requests(request['sources'], SOURCE_PIN,
        interpretation_contract=request['coverage_batching_contract'], **common)
    assert [(task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in default] == [
        (task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in v2]
    assert [(task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in v3] == v3_snapshot
    assert v4[0][2]['contract'] == request['coverage_batching_contract']
    assert v3[0][2]['groups'] == v4[0][2]['groups']
    grammar = generation_schema(v4[0][3], bound_strings=True)
    assert list(grammar['$defs']['EvidenceSourceAssessment']['properties']) == ['supported_topics', 'group_id', 'content_kind']
    assert v3[0][3].model_json_schema() != v4[0][3].model_json_schema()
    assert v3[0][2]['assessment_binding_digest'] != v4[0][2]['assessment_binding_digest']
    with pytest.raises(ValueError, match='coverage19'):
        coverage.frozen_coverage_requests(request['sources'], SOURCE_PIN, contract=coverage.CONTRACT_V18,
            adjudicator_pin=ADJUDICATOR_PIN, interpretation_contract=request['coverage_batching_contract'])


def test_explicit_v5_union_prevents_nondata_topics_and_preserves_v4_history(tmp_path, monkeypatch):
    request, _, _ = fixture(tmp_path, monkeypatch)
    request['sources'] = request['sources'][:2]
    request.update(flow_contract=worker.FLOW_V11, coverage_contract=coverage.CONTRACT_V19,
        coverage_pin=SOURCE_PIN, coverage_adjudicator_pin=ADJUDICATOR_PIN,
        coverage_adjudicator_role='author', coverage_batching_contract='source-interpretation-evidence-first-v5')
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._validate_flow5_request(request)
    common = {'contract': coverage.CONTRACT_V19, 'adjudicator_pin': ADJUDICATOR_PIN}
    v4 = coverage.frozen_coverage_requests(request['sources'], SOURCE_PIN,
        interpretation_contract='source-interpretation-evidence-first-v4', **common)
    old = [(task, instruction, copy.deepcopy(payload), schema.model_json_schema())
           for task, instruction, payload, schema in v4]
    v5 = coverage.frozen_coverage_requests(request['sources'], SOURCE_PIN,
        interpretation_contract=request['coverage_batching_contract'], **common)
    assert [(task, instruction, payload, schema.model_json_schema()) for task, instruction, payload, schema in v4] == old
    assert v4[0][2]['groups'] == v5[0][2]['groups']
    assert v4[0][2]['assessment_binding_digest'] != v5[0][2]['assessment_binding_digest']
    group = v5[0][2]['groups'][0]
    topic = {'quote': group['passage'], 'topic': 'product_and_customers', 'basis': 'reported'}
    schema = v5[0][3]
    for kind in ('information', 'structured_information'):
        answer = {'assessments': [{'supported_topics': [topic], 'group_id': group['group_id'], 'content_kind': kind}]}
        assert schema.model_validate(answer).model_dump(mode='json') == answer
    for kind in ('heading_only', 'contact_only'):
        valid = {'assessments': [{'supported_topics': [], 'group_id': group['group_id'], 'content_kind': kind}]}
        assert schema.model_validate(valid).model_dump(mode='json') == valid
        with pytest.raises(ValueError):
            schema.model_validate({'assessments': [{**valid['assessments'][0], 'supported_topics': [topic]}]})
