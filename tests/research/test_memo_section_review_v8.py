"""Fresh clarity flags are mandatory alongside every unchanged support gate."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_review as review
from agents.research import memo_section_units as core
from tests.research.test_memo_section_units_v9 import fixture, PIN, Model as AuthorModel, coverage_for
from tests.research.test_memo_section_units_v9 import coverage_v2_fixture
from tests.research.test_memo_section_units_v9 import coverage_v4_fixture
from tests.research.test_memo_section_review import REVIEW_PIN


def authored_fixture():
    memo, sources = fixture()
    coverage = coverage_for(sources)
    attempts = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        authored = core.run_author(memo, sources, PIN, attempts, lambda: None, AuthorModel(), budget,
                                   contract=core.CONTRACT_V9, coverage=coverage)
    assert authored['state'] == 'accepted'
    return memo, sources, coverage, authored


class Model:
    name = REVIEW_PIN['name']
    thinking = False
    max_tokens = 700
    context_tokens = 8192
    temperature = 0
    bound_strings = True

    def __init__(self, failed_flag=None):
        self.failed_flag = failed_flag

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == review.TASK_V8 and instruction == review.INSTRUCTION_V8
        payload = json.loads(evidence)
        judgments = {}
        for sid, unit in payload['units'].items():
            judgment = {
                'evidence_id': unit['supporting_evidence_id'],
                'narrative_function': unit['declared_narrative_function'],
                'fulfills_field_purpose': True, 'preserves_source_attribution': True,
                'preserves_time_scope': True, 'has_unsupported_premise': False,
                'has_unsupported_metric': False, 'has_false_missing_data_claim': False,
                'reason': 'Specific supported mechanism and clear prose.',
                'asserts_existing_positive_state': False, 'existing_positive_state_supported': True,
                'baseline_assessment': 'No existing positive baseline is asserted.',
                'matches_declared_function': True, 'plain_language': True,
                'complete_statement': True, 'non_repetitive': True}
            if payload['field'] == 'risks_and_countercase':
                judgment['prospective_effect_is_unproved'] = True
            if self.failed_flag:
                judgment[self.failed_flag] = False
            judgments[sid] = judgment
        answer = {'judgments': judgments}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **review.options_for(core.CONTRACT_V9)}
        return schema.model_validate(answer)


def test_v8_clarity_review_requires_v9_author_and_keeps_evidence_separate_from_comparison_text():
    memo, sources, coverage, authored = authored_fixture()
    calls = review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN,
                                   contract=review.CONTRACT_V8, coverage=coverage)
    assert len(calls) == 5
    for field, payload, schema in calls:
        assert payload['contract'] == review.CONTRACT_V8
        judgment = schema.model_fields['judgments'].annotation.model_fields['S1'].annotation
        assert {'plain_language', 'complete_statement', 'non_repetitive', 'matches_declared_function',
                'asserts_existing_positive_state', 'existing_positive_state_supported'} <= set(judgment.model_fields)
        if field == 'risks_and_countercase':
            assert 'prospective_effect_is_unproved' in judgment.model_fields
        assert all(row['field'] != field for row in payload['reference_narratives'])
        assert {row['field'] for row in payload['reference_narratives']} == set(core.FIELDS) - {field}
        assert set(payload['units']['S1']['eligible_evidence']) == {'S1.n001'}
        assert payload['units']['S1']['source_context'] == payload['units']['S1']['eligible_evidence']
    for wrong_contract in (None, review.CONTRACT_V7):
        with pytest.raises(ValueError, match='versioned author|mandatory v8'):
            review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN, contract=wrong_contract, coverage=coverage)
    tampered = copy.deepcopy(authored)
    tampered['coverage_binding']['response_digest'] = '0' * 64
    with pytest.raises(ValueError, match='coverage binding'):
        review.frozen_requests(memo, sources, tampered, PIN, REVIEW_PIN, contract=review.CONTRACT_V8, coverage=coverage)


@pytest.mark.parametrize('flag', ['plain_language', 'complete_statement', 'non_repetitive'])
def test_v8_each_clarity_judgment_blocks_even_when_all_source_and_purpose_flags_pass(flag):
    memo, sources, coverage, authored = authored_fixture()
    attempts = []
    result = review.run_review(memo, sources, authored, PIN, REVIEW_PIN, attempts, lambda: None,
                              Model(flag), PreparationBudget(105, max_calls=6, max_requests=6),
                              contract=review.CONTRACT_V8, coverage=coverage)
    assert result['state'] == 'blocked'
    assert {finding['reason'] for finding in result['findings']} == {flag}
    assert len(attempts) == 1 and attempts[0]['answer']['judgments']['S1'][flag] is False
    assert result['investment_approval'] is False


def test_v8_every_new_clarity_flag_is_strict_bool_and_missing_judgments_fail_shape():
    memo, sources, coverage, authored = authored_fixture()
    _, payload, schema = review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN,
                                               contract=review.CONTRACT_V8, coverage=coverage)[0]
    answer = Model().generate_for_task(review.TASK_V8, review.INSTRUCTION_V8, json.dumps(payload), schema).model_dump(mode='json')
    for flag in ('plain_language', 'complete_statement', 'non_repetitive'):
        for wrong in (None, 1, 'true'):
            changed = copy.deepcopy(answer)
            changed['judgments']['S1'][flag] = wrong
            with pytest.raises(ValueError):
                schema.model_validate(changed)
        changed = copy.deepcopy(answer)
        del changed['judgments']['S1'][flag]
        with pytest.raises(ValueError):
            schema.model_validate(changed)


def test_v8_all_five_reviews_exact_replay_and_changed_raw_contract_blocks():
    memo, sources, coverage, authored = authored_fixture()
    attempts = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        result = review.run_review(memo, sources, authored, PIN, REVIEW_PIN, attempts, lambda: None,
                                  Model(), budget, contract=review.CONTRACT_V8, coverage=coverage)
    assert result['state'] == 'accepted' and len(attempts) == 5
    assert result['coverage'] == list(core.FIELDS)
    assert review.run_review(memo, sources, authored, PIN, REVIEW_PIN, attempts, lambda: None,
                             None, SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V8,
                             coverage=coverage) == result
    tampered = copy.deepcopy(attempts)
    tampered[0]['input']['reference_narratives'][0]['rendered_narrative'] = 'Manually rewritten comparison.'
    with pytest.raises(ValueError, match='exact frozen contract'):
        review.run_review(memo, sources, authored, PIN, REVIEW_PIN, tampered, lambda: None,
                          None, SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V8,
                          coverage=coverage)


@pytest.mark.parametrize('coverage_contract', ['diligence-source-coverage-v2', 'diligence-source-coverage-v3',
                                             'diligence-source-coverage-v4'])
def test_v8_v2_reviewer_reconstructs_whole_source_lineage_and_rejects_hash_or_version_changes(coverage_contract):
    memo, sources, coverage = (coverage_v4_fixture() if coverage_contract == 'diligence-source-coverage-v4'
                              else coverage_v2_fixture(coverage_contract))
    attempts = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        authored = core.run_author(memo, sources, PIN, attempts, lambda: None, AuthorModel(), budget,
                                   contract=core.CONTRACT_V9, coverage=coverage)
    requests = review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN,
                                     contract=review.CONTRACT_V8, coverage=coverage)
    for _, payload, _ in requests:
        for sid, unit in payload['units'].items():
            span = unit['eligible_evidence_lineage']
            assert span == authored['offered_evidence_spans'][unit['supporting_evidence_id']]
            assert span['source_version'] == next(source['version'] for source in sources if source['id'] == sid)
            assert span['quote_hash'] == core.digest(unit['eligible_evidence'][unit['supporting_evidence_id']])
            assert unit['source_context'] == unit['eligible_evidence']
    for key, wrong in [('source_version', 'changed-version'), ('quote_hash', '0' * 64), ('start', 1)]:
        altered = copy.deepcopy(authored)
        altered['offered_evidence_spans']['S3.b001'][key] = wrong
        with pytest.raises(ValueError, match='excerpt lineage changed'):
            review.frozen_requests(memo, sources, altered, PIN, REVIEW_PIN,
                                  contract=review.CONTRACT_V8, coverage=coverage)
