"""Direct blind assessments drive fresh scopes without a classifier baseline."""
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
from tests.research.test_diligence_coverage import complete_v13_records, synthetic_blind_answer
from tests.research.test_private_source_unit_worker_adjudicator import SOURCE_PIN, ADJUDICATOR_PIN
from tests.research.test_private_source_unit_worker_v6 import fixture, budget


def assert_fixed_category_grammar(grammar, payload):
    aliases = payload['category_aliases']
    assert set(aliases.values()) == set(coverage.CATEGORIES)
    def resolved(node):
        return grammar['$defs'][node['$ref'].split('/')[-1]] if '$ref' in node else node
    for gid, group in payload['groups'].items():
        unit = resolved(grammar['properties'][gid])
        branches = [resolved(branch) for branch in unit.get('oneOf', unit.get('anyOf', [unit]))]
        assert len(branches) >= 2
        for branch in branches:
            properties = branch['properties']
            assert set(branch['required']) == {*aliases, 'kind', 'use', 'proof', 'why'}
            assert set(properties) == set(branch['required'])
            assert branch['additionalProperties'] is False
            kind = resolved(properties['kind'])
            kinds = set(kind.get('enum', [kind.get('const')]))
            for alias, category in aliases.items():
                option = resolved(properties[alias])
                values = set(option.get('enum', [option.get('const')]))
                assert 'N' in values and 'default' not in option
                if kinds <= {'heading_only', 'contact_only'} or (
                    category == 'funding_and_ownership' and not group.get('literal_capital_labels')):
                    assert values == {'N'}


@pytest.mark.parametrize('source_count', [22, 8])
def test_flow10_actual_adapter_uses_only_fresh_assessor_then_selector_and_exact_status_projection(tmp_path, monkeypatch, source_count):
    request, _, legacy_models = fixture(tmp_path, monkeypatch)
    request['sources'] = request['sources'][:source_count]
    # Synthetic model answer fixtures only; no historical raw row is accepted
    # into the fresh production assessment stream.
    reference = complete_v13_records(request['sources'])
    request['sources'][-1]['passage'] = request['sources'][0]['passage']
    request.update(flow_contract=worker.FLOW_V10, coverage_contract=coverage.CONTRACT_V18,
                   coverage_pin=SOURCE_PIN, coverage_adjudicator_pin=ADJUDICATOR_PIN,
                   coverage_adjudicator_role='adjudicator')
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._write(tmp_path, 'content_request.json', request)
    calls = []
    def adapter(name, **options):
        model = LocalModel(name, **options)
        model.client = Mock()
        def transport(**kwargs):
            payload = json.loads(kwargs['messages'][1]['content'])
            assert payload['contract'] == coverage.CONTRACT_V18
            calls.append((name, payload['stage'], copy.deepcopy(kwargs['options'])))
            if payload['stage'] == 'source_adjudication':
                assert 'judgments' not in payload and 'conflict_inventory' not in payload
                assert_fixed_category_grammar(kwargs['format'], payload)
                old = synthetic_blind_answer((None, None, payload, None), reference[:-2])
                answer = {gid: {'kind': unit['kind'],
                    **{alias: unit['topics'].get(category, 'N')
                       for alias, category in payload['category_aliases'].items()},
                    'use': unit['use'], 'proof': unit['proof'],
                    'why': 'Assesses this exact source passage.'}
                    for gid, unit in old.items()}
            else:
                assert payload['stage'] == 'field_source_selection'
                answer = reference[-1]['answer']
            return {'model': name, 'message': {'content': json.dumps(answer)},
                    'done_reason': 'stop', 'prompt_eval_count': 1200, 'eval_count': 200}
        model.client.chat.side_effect = transport
        return model
    monkeypatch.setattr(worker, 'LocalModel', adapter)
    shards = coverage.frozen_adjudication_shards(request['sources'])
    nonempty = sum(bool(item['source_ids']) for item in shards)
    for phase in worker.COVERAGE_PHASES_V10:
        before = len(calls)
        result = worker.advance(tmp_path, phase, budget())
        assert result['state'] == 'needs_resume', result
        if result['reason'] == 'diligence_source_adjudication_empty':
            assert len(calls) == before
    assert [name for name, _, _ in calls] == [ADJUDICATOR_PIN['name']] * nonempty + [SOURCE_PIN['name']]
    assert [item[1] for item in calls] == ['source_adjudication'] * nonempty + ['field_source_selection']
    assert all(options['presence_penalty'] == 0 and options['repeat_penalty'] == 1 for _, _, options in calls)
    revision = worker.load_source_unit_revision(tmp_path)
    records = revision['diligence_coverage_attempts']
    assert len(records) == nonempty + 1 <= 6
    assert all(row['input']['contract'] == coverage.CONTRACT_V18 for row in records)
    result = worker._coverage_result(request, revision)
    assert result['state'] == 'accepted' and result['coverage_complete'] is True
    assert len(result['blind_group_assessments']) == source_count - 1
    assert result['assessed_source_ids'] == [row['id'] for row in request['sources']]
    aliases = records[0]['input']['category_aliases']
    for row in records[:-1]:
        assert json.loads(row['raw_response']) == row['answer']
        for gid, answer in row['answer'].items():
            assert set(answer) == {*aliases, 'kind', 'use', 'proof', 'why'}
            for member in row['input']['groups'][gid]['members']:
                sid = member['source_id']
                expected = {category: sid + '.e' + answer[alias][1:]
                            for alias, category in aliases.items() if answer[alias] != 'N'}
                assert result['judgments'][sid]['category_support'] == expected
    _, binding = core._replay_coverage_v9([Source.model_validate(row) for row in request['sources']],
                                        worker._coverage_bundle(request, revision))
    assert binding['coverage_contract'] == coverage.CONTRACT_V18
    assert binding['model_pin'] == SOURCE_PIN and binding['adjudicator_pin'] == ADJUDICATOR_PIN
    historical = copy.deepcopy(revision)
    historical['diligence_coverage_attempts'] = reference[:(source_count + 4) // 5]
    assert worker._coverage_result(request, historical)['state'] == 'blocked'
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: pytest.fail('Exact cached assessment must replay'))
    for phase in worker.COVERAGE_PHASES_V10:
        assert worker.advance(tmp_path, phase, budget())['state'] == 'needs_resume'
    for phase in worker.PHASES_V10[6:11]:
        result = worker.advance(tmp_path, phase, budget(), models=legacy_models)
        assert result['state'] == 'needs_resume', result
    assert result['next_phase'] == 'memo_section_author_investment_thesis'
    assert len(worker.PHASES_V10) == 21 and worker.PHASES_V10[6:] == worker.PHASES_V4
    assert stage.flow_config(worker.FLOW_V10) == (worker.PHASES_V10, 'content_units_v10')
    for changes in ({'flow_contract': worker.FLOW_V9}, {'coverage_contract': coverage.CONTRACT_V17}):
        wrong = {**request, **changes}
        wrong['digest'] = digest({key: value for key, value in wrong.items() if key != 'digest'})
        with pytest.raises(ValueError, match='exact frozen'):
            worker._validate_flow5_request(wrong)
