"""Role-separated local responses reject factual leakage without rewriting prose."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import diligence_coverage, memo_section_units as core, memo_section_review as review
from tests.research.test_memo_section_units_v9 import fixture, PIN, coverage_for, coverage_v4_fixture
from tests.research.test_memo_quote_premises_v10 import Reviewer as PriorReviewer
from tests.research.test_memo_section_review import REVIEW_PIN
from tests.research.test_diligence_coverage import complete_v9_records, recorded_row, PIN as COVERAGE_PIN


PREMISE = 'The undated company report describes a partner distribution service.'
COMPONENTS = {
    'investment_thesis': {'source_premise': PREMISE,
        'condition': 'If partners deliver the reported service consistently,',
        'prospective_effect': 'customer adoption could justify diligence into that distribution mechanism.'},
    'business_and_market': {'source_premise': PREMISE,
        'scope_qualification': 'The company also describes limited overlap against incumbent offerings; this is its reported competitive position.'},
    'differentiation_and_execution': {'source_premise': PREMISE,
        'condition': 'If partners sustain consistent delivery of that service,',
        'prospective_effect': 'the operating mechanism could support a differentiated customer proposition.'},
    'risks_and_countercase': {'source_premise': PREMISE,
        'condition': 'If partners fail to deliver the reported service consistently,',
        'prospective_effect': 'customer adoption could weaken and undermine that distribution proposition.'},
    'diligence_plan': {'source_premise': PREMISE,
        'requested_records': 'Request partner delivery logs and customer adoption records;',
        'decision_relevance': 'those records would test repeatability before further investment diligence.'}}


class Author12:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0
    bound_strings = compact_prompt = require_full_context = True

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == core.TASK_V12 and instruction == core.INSTRUCTION_V12
        payload = json.loads(evidence)
        field = payload['field']
        answer = {'units': {sid: {'supporting_evidence_id': next(iter(payload['sources'][sid]['spans'])),
            'premise_scope': 'reported', 'status': 'conditional_hypothesis'
                if field == 'differentiation_and_execution' else core.STATUSES[field][0],
            **COMPONENTS[field]} for sid in payload['unit_source_ids']}}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **core.options_for(core.CONTRACT_V12), 'prompt_tokens': 1800}
        return schema.model_validate(answer)


class Reviewer11(PriorReviewer):
    max_tokens = 600
    compact_prompt = require_full_context = True

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == review.TASK_V11 and instruction == review.INSTRUCTION_V11
        result = super().generate_for_task(review.TASK_V9, review.INSTRUCTION_V9, evidence, schema, attempt=attempt)
        self.last_route.update(review.OPTIONS_V10, prompt_tokens=1900)
        return result


def fresh_authored():
    memo, sources = fixture()
    coverage = coverage_for(sources)
    rows = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        authored = core.run_author(memo, sources, PIN, rows, lambda: None, Author12(), budget,
                                   contract=core.CONTRACT_V12, coverage=coverage)
    assert authored['state'] == 'accepted' and len(rows) == 5
    return memo, sources, coverage, rows, authored


def test_v12_first_attempt_components_project_exactly_and_preserve_all_hard_bounds():
    memo, sources, coverage, rows, authored = fresh_authored()
    for field in core.FIELDS:
        unit = authored['answer'][field]['units']['S1']
        rendered = ' '.join(unit[key] for key in core._COMPONENTS_V12[field])
        assert authored['memo'][field]['claims'][0]['assertion'] == rendered
        assert 180 <= len(rendered) <= 280 and len(core._WORDS_V9.findall(rendered)) <= 48
        assert len(core._sentences(rendered)) == 2
    assert core.run_author(memo, sources, PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=core.CONTRACT_V12, coverage=coverage) == authored
    altered = copy.deepcopy(rows)
    altered[0]['routing']['prompt_tokens'] = 4098
    with pytest.raises(ValueError, match='context integrity'):
        core.run_author(memo, sources, PIN, altered, lambda: None, None,
            SimpleNamespace(calls=0, max_calls=0), contract=core.CONTRACT_V12, coverage=coverage)


@pytest.mark.parametrize('leak', ['6.75', '3.5k', 'FY24', 'USD500', 'INR800', '15cr', '4x', 'january'])
def test_v12_quantified_facts_cannot_move_into_hypothetical_components(leak):
    unit = {'premise_scope': 'reported', **COMPONENTS['investment_thesis']}
    unit['condition'] = 'If partners deliver ' + leak + ' through the reported service,'
    original = copy.deepcopy(unit)
    with pytest.raises(ValueError, match='Quantified/date facts'):
        core.validate_components_v12('investment_thesis', unit,
            'The company reports ARPU of INR 6.75 beside a separate 3.5k table cell.', 90)
    assert unit == original


def test_v12_premise_inventory_keeps_currency_scales_and_product_names_distinct():
    assert not core.quantitative_facts_v12('The company describes B2B, Web3, M365 and 5G products.')
    for token in ('USD500', 'EUR3.5k', '4x', '15cr', '5tn', '1lakh'):
        assert core.quantitative_facts_v12(token)
    unit = {'premise_scope': 'ambiguous', **COMPONENTS['investment_thesis']}
    unit['source_premise'] = 'The undated company report labels an ambiguous ARPU table value of INR800.'
    with pytest.raises(ValueError, match='Ambiguous source'):
        core.validate_components_v12('investment_thesis', unit, unit['source_premise'], 90)


@pytest.mark.parametrize('field,key', [('investment_thesis', 'condition'),
    ('investment_thesis', 'prospective_effect'), ('business_and_market', 'scope_qualification'),
    ('diligence_plan', 'requested_records'), ('diligence_plan', 'decision_relevance')])
def test_v12_every_nonrisk_component_binds_financial_families_to_its_own_quote(field, key):
    unit = {'premise_scope': 'reported', **COMPONENTS[field]}
    unit[key] = unit[key].replace('service', 'revenue service').replace('records', 'revenue records')
    if 'revenue' not in unit[key]:
        unit[key] = unit[key].replace('distribution', 'revenue distribution').replace('position', 'revenue position')
    with pytest.raises(ValueError, match='metric|financial labels'):
        core.validate_components_v12(field, unit,
            'The company reports a partner distribution service with limited overlap.', 90)


def test_v12_only_unquantified_risk_effect_keeps_the_prospective_exception():
    unit = {'premise_scope': 'reported', **COMPONENTS['risks_and_countercase']}
    unit['prospective_effect'] = 'future revenue could fall and undermine the proposed distribution mechanism.'
    quote = 'The company reports operating a partner distribution service.'
    result = core.validate_components_v12('risks_and_countercase', unit, quote, 180)
    assert result == core.decision_text(unit, core.CONTRACT_V12)
    unit['condition'] = 'If the company has high adoption of the reported service,'
    with pytest.raises(ValueError, match='Comparative premises'):
        core.validate_components_v12('risks_and_countercase', unit, quote, 90)


def test_v12_core_reconstructs_v9_quote_lineage_only_from_new_recorded_categories():
    memo, sources, _ = coverage_v4_fixture()
    sources[3]['passage'] = 'Synthetic report includes equity raised and venture debt.'
    rows = complete_v9_records(sources)
    request = diligence_coverage.pending_coverage_request(sources, COVERAGE_PIN, rows[:-1], contract=diligence_coverage.CONTRACT_V9)
    answer = {**rows[-1]['answer'], 'business_and_market': ['S1']}
    rows[-1] = recorded_row(request, answer, len(rows))
    coverage = {'model_pin': COVERAGE_PIN, 'contract': diligence_coverage.CONTRACT_V9, 'attempts': rows}
    requests = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V12, coverage=coverage)
    offered = core.frozen_offered_spans(sources, requests)
    assert requests[0][1]['coverage_binding']['coverage_contract'] == diligence_coverage.CONTRACT_V9
    assert set(requests[0][1]['coverage_binding']['source_content_kinds'].values()) == {'information'}
    for span in offered.values():
        source = next(source for source in sources if source['id'] == span['source_id'])
        assert source['passage'][span['start']:span['end']] == span['exact_text']
        assert len(span['exact_text']) <= 700 and span['quote_hash'] == core.digest(span['exact_text'])


def test_v11_component_reviewer_requires_new_pair_and_independent_strict_judgments():
    memo, sources, coverage, _, authored = fresh_authored()
    with pytest.raises(ValueError, match='versioned author|mandatory v11'):
        review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN, contract=review.CONTRACT_V10, coverage=coverage)
    calls = review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN, contract=review.CONTRACT_V11, coverage=coverage)
    field, payload, schema = calls[0]
    unit = payload['units']['S1']
    assert unit['source_premise'] == PREMISE
    assert unit['rendered_narrative'] == core.decision_text(authored['answer'][field]['units']['S1'], core.CONTRACT_V12)
    answer = Reviewer11().generate_for_task(review.TASK_V11, review.INSTRUCTION_V11,
                                           json.dumps(payload), schema).model_dump(mode='json')
    for flag in ('source_premise_grounded', 'judgment_components_are_unproved', 'comparative_premises_grounded'):
        altered = copy.deepcopy(answer)
        altered['judgments']['S1'][flag] = False
        assert {finding['reason'] for finding in review._findings(payload, altered)} == {flag}
        altered['judgments']['S1'][flag] = 'true'
        with pytest.raises(ValueError):
            schema.model_validate(altered)
    assert 'ONLY the judgment components' in review.INSTRUCTION_V11
    assert 'does not require an IF clause' in review.INSTRUCTION_V11
    rows = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        reviewed = review.run_review(memo, sources, authored, PIN, REVIEW_PIN, rows, lambda: None,
            Reviewer11(), budget, contract=review.CONTRACT_V11, coverage=coverage)
    assert reviewed['state'] == 'accepted' and len(rows) == 5
    assert all(row['routing']['max_tokens'] == 600 and row['routing']['require_full_context'] for row in rows)
    assert review.run_review(memo, sources, authored, PIN, REVIEW_PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V11, coverage=coverage) == reviewed
    changed = copy.deepcopy(rows)
    changed[0]['routing']['prompt_tokens'] = 4098
    with pytest.raises(ValueError, match='context integrity'):
        review.run_review(memo, sources, authored, PIN, REVIEW_PIN, changed, lambda: None, None,
            SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V11, coverage=coverage)
