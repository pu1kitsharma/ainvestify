"""Fresh quote inventories and comparison gates; synthetic local responses only."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core, memo_section_review as review
from agents.research import diligence_coverage
from tests.research.test_memo_section_units_v9 import fixture, PIN, Model as OldAuthor, coverage_for, coverage_v4_fixture, DILIGENCE, RISK
from tests.research.test_memo_section_review import REVIEW_PIN
from tests.research.test_diligence_coverage import recorded_row, PIN as COVERAGE_PIN


class Author(OldAuthor):
    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == core.TASK_V10 and instruction == core.INSTRUCTION_V10
        return super().generate_for_task(core.TASK_V9, core.INSTRUCTION_V9, evidence, schema, attempt=attempt)


def authored_fixture():
    memo, sources, coverage = coverage_v4_fixture()
    prefix = coverage['attempts'][:-1]
    request = diligence_coverage.pending_coverage_request(sources, COVERAGE_PIN, prefix,
                                                        contract=diligence_coverage.CONTRACT_V5)
    answer = {**coverage['attempts'][-1]['answer'], 'content_kinds': {source['id']: 'information' for source in sources}}
    coverage = {'contract': diligence_coverage.CONTRACT_V5, 'model_pin': COVERAGE_PIN,
                'attempts': prefix + [recorded_row(request, answer, len(prefix) + 1)]}
    attempts = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        authored = core.run_author(memo, sources, PIN, attempts, lambda: None, Author(), budget,
                                   contract=core.CONTRACT_V10, coverage=coverage)
    assert authored['state'] == 'accepted' and len(attempts) == 5
    assert authored['coverage_binding']['source_content_kinds'] == answer['content_kinds']
    assert core.run_author(memo, sources, PIN, attempts, lambda: None, None, SimpleNamespace(calls=0, max_calls=0),
                           contract=core.CONTRACT_V10, coverage=coverage) == authored
    return memo, sources, coverage, authored


def test_per_quote_financial_inventory_cannot_borrow_another_quotes_metrics():
    memo, sources = fixture()
    sources[0]['passage'] = ('The company reports ARR as a historical operating measure.\n\n'
                            'The company reports Revenue and EBITDA as separate financial measures.')
    coverage = coverage_for(sources)
    field, payload, schema = next(row for row in core.frozen_requests(memo, sources, PIN,
        contract=core.CONTRACT_V10, coverage=coverage) if row[0] == 'diligence_plan')
    inventory = payload['sources']['S1']['financial_measure_inventory']
    assert inventory['S1.n001'] == {'allowed_financial_measure_families': ['arr'], 'allowed_financial_labels': ['ARR']}
    assert inventory['S1.n002']['allowed_financial_measure_families'] == ['ebitda', 'revenue']
    unit = {'supporting_evidence_id': 'S1.n001', 'status': 'conditional_request',
        'requested_verification_records': 'Request ARR records to test the reported historical operating measure and its supporting transactions.',
        'decision_relevance': 'Use those records to decide whether the reported measure provides a sound basis for further investment diligence.'}
    answer = {'units': {'S1': unit}}
    assert core._project_field(memo, field, payload, schema, answer).claims[0].quote == payload['sources']['S1']['spans']['S1.n001']
    wrong = copy.deepcopy(answer)
    wrong['units']['S1']['requested_verification_records'] = unit['requested_verification_records'].replace('ARR', 'Revenue')
    with pytest.raises(ValueError, match='financial labels not in quote'):
        core._project_field(memo, field, payload, schema, wrong)
    multiple = copy.deepcopy(answer)
    multiple['units']['S1']['supporting_evidence_id'] = 'S1.n002'
    multiple['units']['S1']['requested_verification_records'] = unit['requested_verification_records'].replace('ARR', 'Revenue and EBITDA')
    with pytest.raises(ValueError, match='at most one'):
        core._project_field(memo, field, payload, schema, multiple)
    assert wrong['units']['S1']['requested_verification_records'].startswith('Request Revenue')


def test_comparative_baseline_needs_own_term_and_attribution_not_numeric_percentage():
    quote = 'The company reports founder ownership of 55%.'
    with pytest.raises(ValueError, match='absent from selected quote'):
        core.validate_comparative_binding_v10('The company reports high founder ownership.', quote)
    source = 'The company describes high founder ownership.'
    core.validate_comparative_binding_v10('The company reports high founder ownership.', source)
    with pytest.raises(ValueError, match='explicit attribution'):
        core.validate_comparative_binding_v10('High founder ownership supports the investment case.', source)


def test_v10_preserves_unproved_future_risk_effect_and_v9_has_no_new_inventory():
    memo, sources = fixture()
    coverage = coverage_for(sources)
    old = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V9, coverage=coverage)
    assert all('financial_measure_inventory' not in payload['sources']['S1'] for _, payload, _ in old)
    field, payload, schema = next(row for row in core.frozen_requests(memo, sources, PIN,
        contract=core.CONTRACT_V10, coverage=coverage) if row[0] == 'risks_and_countercase')
    answer = {'units': {'S1': {'supporting_evidence_id': 'S1.n001', 'status': 'conditional_hypothesis', **RISK,
        'prospective_consequence': 'future revenue could be lower, weakening the proposed distribution advantage and the investment case built on that mechanism.'}}}
    assert core._project_field(memo, field, payload, schema, answer).claims[0].assertion.endswith('mechanism.')


class Reviewer:
    name = REVIEW_PIN['name']
    thinking = False
    max_tokens = 700
    context_tokens = 8192
    temperature = 0
    bound_strings = True

    def __init__(self, comparative=True):
        self.comparative = comparative

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == review.TASK_V9 and instruction == review.INSTRUCTION_V9
        payload = json.loads(evidence)
        judgments = {}
        for sid, unit in payload['units'].items():
            judgment_type = schema.model_fields['judgments'].annotation.model_fields[sid].annotation
            judgment = {key: (False if key.startswith('has_unsupported') or key == 'has_false_missing_data_claim'
                              or key == 'asserts_existing_positive_state' else True)
                        for key in judgment_type.model_fields}
            judgment.update(evidence_id=unit['supporting_evidence_id'], narrative_function=unit['declared_narrative_function'],
                reason='No unsupported comparative premise is asserted.', baseline_assessment='No existing comparative strength is assumed.',
                comparative_premises_grounded=self.comparative)
            judgments[sid] = judgment
        answer = {'judgments': judgments}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **review.OPTIONS_V5}
        return schema.model_validate(answer)


def test_v9_reviewer_comparison_flag_is_strict_independent_and_mandatory_pair():
    memo, sources, coverage, authored = authored_fixture()
    calls = review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN, contract=review.CONTRACT_V9, coverage=coverage)
    field, payload, schema = calls[0]
    answer = Reviewer().generate_for_task(review.TASK_V9, review.INSTRUCTION_V9, json.dumps(payload), schema).model_dump(mode='json')
    sid = next(iter(answer['judgments']))
    for value in (None, 1, 'true'):
        altered = copy.deepcopy(answer)
        altered['judgments'][sid]['comparative_premises_grounded'] = value
        with pytest.raises(ValueError):
            schema.model_validate(altered)
    for wrong in (None, review.CONTRACT_V8):
        with pytest.raises(ValueError, match='mandatory v9|versioned author'):
            review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN, contract=wrong, coverage=coverage)
    attempts = []
    rejected = review.run_review(memo, sources, authored, PIN, REVIEW_PIN, attempts, lambda: None,
        Reviewer(False), PreparationBudget(105, max_calls=6, max_requests=6), contract=review.CONTRACT_V9, coverage=coverage)
    assert rejected['state'] == 'blocked'
    assert {finding['reason'] for finding in rejected['findings']} == {'comparative_premises_grounded'}
    assert attempts[0]['answer']['judgments'][sid]['comparative_premises_grounded'] is False


def test_v10_v9_all_five_recorded_reviews_replay_exactly():
    memo, sources, coverage, authored = authored_fixture()
    attempts = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        result = review.run_review(memo, sources, authored, PIN, REVIEW_PIN, attempts, lambda: None,
            Reviewer(), budget, contract=review.CONTRACT_V9, coverage=coverage)
    assert result['state'] == 'accepted' and len(attempts) == 5
    assert review.run_review(memo, sources, authored, PIN, REVIEW_PIN, attempts, lambda: None,
        None, SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V9, coverage=coverage) == result
    changed = copy.deepcopy(attempts)
    changed[0]['input']['units'][next(iter(changed[0]['input']['units']))]['financial_measure_inventory']['allowed_financial_measure_families'].append('ebitda')
    with pytest.raises(ValueError, match='frozen contract'):
        review.run_review(memo, sources, authored, PIN, REVIEW_PIN, changed, lambda: None,
            None, SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V9, coverage=coverage)
