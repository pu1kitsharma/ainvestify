"""Typed neutral attribution is present in exact displayed local-model output."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import diligence_coverage, memo_section_units as core, memo_section_review as review
from tests.research.test_memo_section_units_v9 import fixture, coverage_for, coverage_v4_fixture, PIN
from tests.research.test_memo_section_units_v12 import COMPONENTS, Reviewer11
from tests.research.test_memo_section_review import REVIEW_PIN
from tests.research.test_diligence_coverage import complete_v10_records, recorded_row, PIN as COVERAGE_PIN


FIRST_PERSON_PREMISE = 'We operate a partner distribution service with limited incumbent offering overlap.'


class Author13:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0
    bound_strings = compact_prompt = require_full_context = True

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == core.TASK_V13 and instruction == core.INSTRUCTION_V13
        payload = json.loads(evidence)
        field = payload['field']
        values = {**COMPONENTS[field], 'source_premise': FIRST_PERSON_PREMISE}
        answer = {'units': {sid: {'supporting_evidence_id': next(iter(payload['sources'][sid]['spans'])),
            'source_label': 'Unverified company report', 'premise_scope': 'reported',
            'status': 'conditional_hypothesis' if field == 'differentiation_and_execution'
                else core.STATUSES[field][0], **values} for sid in payload['unit_source_ids']}}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **core.options_for(core.CONTRACT_V13), 'prompt_tokens': 2000}
        return schema.model_validate(answer)


class Reviewer12(Reviewer11):
    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == review.TASK_V12 and instruction == review.INSTRUCTION_V12
        return super().generate_for_task(review.TASK_V11, review.INSTRUCTION_V11, evidence, schema, attempt=attempt)


def fresh_authored():
    memo, sources = fixture()
    coverage = coverage_for(sources)
    rows = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        authored = core.run_author(memo, sources, PIN, rows, lambda: None, Author13(), budget,
                                   contract=core.CONTRACT_V13, coverage=coverage)
    assert authored['state'] == 'accepted' and len(rows) == 5
    return memo, sources, coverage, rows, authored


def test_v13_first_person_is_explicitly_labeled_in_claim_body_and_exact_replay():
    memo, sources, coverage, rows, authored = fresh_authored()
    for field in core.FIELDS:
        unit = authored['answer'][field]['units']['S1']
        assert unit['source_premise'] == FIRST_PERSON_PREMISE and not core._ATTRIBUTION_V10.search(FIRST_PERSON_PREMISE)
        expected = unit['source_label'] + ': ' + ' '.join(unit[key] for key in core._COMPONENTS_V12[field])
        assert authored['memo'][field]['claims'][0]['assertion'] == expected
        assert expected.startswith('Unverified company report: We operate')
        assert authored['memo'][field]['analysis'] == expected.rstrip('.!? ') + ' [S1].'
        assert 180 <= len(expected) <= 280 and len(core._WORDS_V9.findall(expected)) <= 48
    assert core.run_author(memo, sources, PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=core.CONTRACT_V13, coverage=coverage) == authored
    changed = copy.deepcopy(rows)
    changed[0]['routing']['prompt_tokens'] = 4098
    with pytest.raises(ValueError, match='context integrity'):
        core.run_author(memo, sources, PIN, changed, lambda: None, None,
            SimpleNamespace(calls=0, max_calls=0), contract=core.CONTRACT_V13, coverage=coverage)


def test_v13_label_cannot_rescue_scope_fragments_financial_labels_or_comparisons():
    unit = {'premise_scope': 'reported', 'source_label': 'Unverified company report',
            **COMPONENTS['investment_thesis'], 'source_premise': FIRST_PERSON_PREMISE}
    quote = 'The company reports operating a partner distribution service with limited overlap against incumbent offerings.'
    with pytest.raises(ValueError, match='attributed'):
        core.validate_components_v12('investment_thesis', unit, quote, 180)
    original = copy.deepcopy(unit)
    assert core.validate_components_v13('investment_thesis', unit, quote, 180) == core.decision_text(unit, core.CONTRACT_V13)
    assert unit == original
    for key, value, error in (
        ('source_label', 'Unverified company plan', 'declared premise scope'),
        ('source_premise', FIRST_PERSON_PREMISE.rstrip('.'), 'finish before'),
        ('source_premise', 'We operate the service with high founder ownership and limited offering overlap.', 'Comparative premises'),
        ('condition', 'If the service can deliver USD500 in revenue per transaction,', 'Quantified/date facts'),
        ('condition', 'If the reported service can sustain additional revenue,', 'metric|financial labels')):
        altered = {**unit, key: value}
        with pytest.raises(ValueError, match=error):
            core.validate_components_v13('investment_thesis', altered, quote, 180)
    assert unit == original


def test_v13_displayed_label_counts_in_hard_character_and_word_caps():
    unit = {'premise_scope': 'reported', 'source_label': 'Unverified company report',
            **COMPONENTS['investment_thesis'], 'source_premise': FIRST_PERSON_PREMISE}
    unit['prospective_effect'] = 'customer adoption could justify diligence into that distribution mechanism and customer proposition.'
    raw = ' '.join(unit[key] for key in core._COMPONENTS_V12['investment_thesis'])
    # The rendered label consumes the unchanged cap; no off-body attribution waiver.
    unit['source_premise'] = FIRST_PERSON_PREMISE[:-1] + ' through operating partners.'
    raw = ' '.join(unit[key] for key in core._COMPONENTS_V12['investment_thesis'])
    assert len(raw) <= 280 < len(core.decision_text(unit, core.CONTRACT_V13))
    with pytest.raises(ValueError, match='280 characters'):
        core.validate_components_v13('investment_thesis', unit, FIRST_PERSON_PREMISE, 180)


@pytest.mark.parametrize('coverage_contract', ['diligence-source-coverage-v10', 'diligence-source-coverage-v11'])
def test_v13_coverage10_preserves_recorded_structured_kind_and_exact_quote_lineage(coverage_contract):
    memo, sources, _ = coverage_v4_fixture()
    sources[3]['passage'] = 'Reported targets\nRevenue INR million 20\nEquity raised INR million 3'
    sources += [{**sources[0], 'id': 'S6', 'version': 'synthetic-heading-version',
                 'passage': 'Our synthetic market\nTomorrow\nSynthetic Future', 'url': 'private://synthetic-heading'},
                {**sources[0], 'id': 'S7', 'version': 'synthetic-contact-version',
                 'passage': 'Contact: synthetic@example.invalid', 'url': 'private://synthetic-contact'}]
    if coverage_contract == diligence_coverage.CONTRACT_V11:
        # Distinct synthetic passages avoid unrelated duplicate-topic disputes.
        for index in (1, 4):
            sources[index]['passage'] += '\nSynthetic source context ' + sources[index]['id'] + '.'
    records = complete_v10_records(sources)
    if coverage_contract == diligence_coverage.CONTRACT_V11:
        # A recorded classifier mislabels the synthetic heading; the final
        # recorded model patch fixes its kind without changing any source bytes.
        prefix = records[:-1]
        old = copy.deepcopy(prefix[1]['answer'])
        eid = old['S6']['kind_evidence_id']
        old['S6'].update(content_kind='information', disposition='relevant',
                         category_support={'product_and_customers': eid})
        original_request = diligence_coverage.frozen_coverage_requests(sources, COVERAGE_PIN,
            contract=diligence_coverage.CONTRACT_V10)[1]
        prefix[1] = recorded_row(original_request, old, 2)
        request = diligence_coverage.pending_coverage_request(sources, COVERAGE_PIN, prefix,
            contract=diligence_coverage.CONTRACT_V11)
        answer = {'patches': [{'source_id': 'S6', 'kind': 'heading_only', 'use': 'context_only',
                              'proof': eid, 'topics': {},
                              'why': 'Heading has no reported operating proposition.'}],
                  **records[-1]['answer']}
        records = prefix + [recorded_row(request, answer, len(records))]
        assert prefix[1]['answer']['S6']['content_kind'] == 'information'
    coverage = {'model_pin': COVERAGE_PIN, 'contract': coverage_contract, 'attempts': records}
    requests = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V13, coverage=coverage)
    binding = requests[0][1]['coverage_binding']
    assert binding['coverage_contract'] == coverage_contract
    assert binding['source_content_kinds']['S3'] == binding['source_content_kinds']['S4'] == 'structured_information'
    assert binding['source_content_kinds']['S6'] == 'heading_only'
    assert binding['source_content_kinds']['S7'] == 'contact_only'
    offered = core.frozen_offered_spans(sources, requests)
    assert not {'S6', 'S7'} & {span['source_id'] for span in offered.values()}
    for span in offered.values():
        source = next(source for source in sources if source['id'] == span['source_id'])
        assert span['exact_text'] == source['passage'][span['start']:span['end']]
        assert span['source_version'] == source['version']
        assert 15 <= len(span['exact_text']) <= 700
        assert span['quote_hash'] == core.digest(span['exact_text'])


def test_v12_review_requires_clear_displayed_attribution_without_weakening_other_flags():
    memo, sources, coverage, _, authored = fresh_authored()
    with pytest.raises(ValueError, match='versioned author|mandatory v12'):
        review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN, contract=review.CONTRACT_V11, coverage=coverage)
    calls = review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN, contract=review.CONTRACT_V12, coverage=coverage)
    field, payload, schema = calls[0]
    unit = payload['units']['S1']
    assert unit['source_premise'] == FIRST_PERSON_PREMISE
    assert unit['displayed_source_premise'] == unit['source_label'] + ': ' + FIRST_PERSON_PREMISE
    assert unit['rendered_narrative'] == authored['memo'][field]['claims'][0]['assertion']
    answer = Reviewer12().generate_for_task(review.TASK_V12, review.INSTRUCTION_V12,
                                           json.dumps(payload), schema).model_dump(mode='json')
    flag = 'displayed_source_attribution_is_clear'
    altered = copy.deepcopy(answer)
    altered['judgments']['S1'][flag] = False
    assert {row['reason'] for row in review._findings(payload, altered)} == {flag}
    altered['judgments']['S1'][flag] = 1
    with pytest.raises(ValueError):
        schema.model_validate(altered)
    rows = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        reviewed = review.run_review(memo, sources, authored, PIN, REVIEW_PIN, rows, lambda: None,
            Reviewer12(), budget, contract=review.CONTRACT_V12, coverage=coverage)
    assert reviewed['state'] == 'accepted' and len(rows) == 5
    assert review.run_review(memo, sources, authored, PIN, REVIEW_PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V12, coverage=coverage) == reviewed
