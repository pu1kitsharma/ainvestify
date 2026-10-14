"""Concise local authorship preserves exact evidence and historical replay."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.inference.model_authorship import recorded_call
from agents.research import diligence_coverage as coverage_engine
from agents.research import memo_section_units as core
from tests.research.test_memo_section_units_v5 import fixture, PIN

TEXTS = {
    'investment_thesis': 'If partners consistently deliver the reported service, customers could receive a distinct offering through those partners. Adoption evidence would determine whether that distribution mechanism merits investment diligence.',
    'business_and_market': 'The company reports a partner distribution service with limited overlap against incumbent offerings. This describes its reported service and competitive position; it does not establish current performance.',
    'differentiation_and_execution': 'If partners can deliver the reported service consistently, reliable delivery could distinguish the offering from incumbent alternatives. The proposed advantage depends on repeatable execution, not the company description alone.'}
RISK = {
    'failure_condition': 'If partners fail to deliver the reported service consistently,',
    'prospective_consequence': 'customer adoption could weaken, limiting the proposed distribution advantage and the investment case built on that mechanism.'}
DILIGENCE = {
    'requested_verification_records': 'Request partner delivery logs and customer adoption records to test the reported service and competitive overlap.',
    'decision_relevance': 'Use those records to decide whether the distribution proposition is repeatable enough to justify further investment diligence.'}


class CoverageModel:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0
    bound_strings = True

    def __init__(self, selected_source=None):
        self.selected_source = selected_source

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        payload = json.loads(evidence)
        if task == coverage_engine.CLASSIFY_TASK:
            answer = {sid: {'disposition': 'relevant', 'categories': ['product_and_customers', 'market_and_competition'],
                'supporting_evidence_ids': [next(iter(payload['sources'][sid]['evidence_spans']))],
                'reason': 'Reported partner delivery and competitive positioning.'} for sid in payload['required_source_ids']}
        else:
            answer = {field: [self.selected_source or payload['eligible_narrative_source_ids'][0]] for field in core.FIELDS}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **coverage_engine.OPTIONS}
        return schema.model_validate(answer)


def coverage_for(sources, selected_source=None):
    attempts = []
    for _ in range(coverage_engine.MAX_CALLS):
        pending = coverage_engine.pending_coverage_request(sources, PIN, attempts)
        if pending is None:
            break
        task, instruction, payload, schema = pending
        recorded_call(CoverageModel(selected_source), task, instruction, payload, schema, attempts, lambda: None)
    assert coverage_engine.evaluate_coverage(sources, PIN, attempts)['state'] == 'accepted'
    return {'model_pin': PIN, 'attempts': attempts}


def coverage_v2_fixture(contract=coverage_engine.CONTRACT_V2):
    from tests.research.test_diligence_coverage import complete_v2_records, recorded_row, PIN as COVERAGE_PIN
    memo, sources = fixture()
    template = sources[0]
    sources = [{**template, 'id': f'S{index}', 'version': f'version-{index}',
                'url': f'private://synthetic-source-{index}'} for index in range(1, 6)]
    attempts = complete_v2_records(sources)
    request = coverage_engine.pending_coverage_request(sources, COVERAGE_PIN, attempts[:-1],
                                                       contract=contract)
    answer = {field: ids[:1] for field, ids in attempts[-1]['answer'].items()}
    attempts[-1] = recorded_row(request, answer, len(attempts))
    coverage = {'model_pin': COVERAGE_PIN, 'attempts': attempts,
                'contract': contract}
    return memo, sources, coverage


def coverage_v4_fixture():
    from tests.research.test_diligence_coverage import recorded_row, PIN as COVERAGE_PIN
    memo, sources, _ = coverage_v2_fixture()
    sources[2]['passage'] = sources[2]['passage'] + '\n' + '\n'.join(
        f'Synthetic team member {number}: ' + 'Listed experience and responsibilities. ' * 4
        for number in range(1, 6))
    categories = {'S1': ['product_and_customers', 'market_and_competition'],
                  'S2': ['risks', 'market_and_competition'], 'S3': ['team_and_governance'],
                  'S4': ['financial_evidence'], 'S5': ['legal_and_compliance']}
    attempts = []
    for request in coverage_engine.frozen_coverage_requests(sources, COVERAGE_PIN,
                                                            contract=coverage_engine.CONTRACT_V4):
        answer = {sid: {'disposition': 'relevant', 'writing_utility': 'substantive',
            'utility_evidence_id': next(iter(row['evidence_spans'])),
            'category_support': {category: next(iter(row['evidence_spans'])) for category in categories[sid]},
            'reason': 'Recorded synthetic diligence topic and complete text.'}
            for sid, row in request[2]['sources'].items()}
        attempts.append(recorded_row(request, answer, len(attempts) + 1))
    request = coverage_engine.pending_coverage_request(sources, COVERAGE_PIN, attempts,
                                                       contract=coverage_engine.CONTRACT_V4)
    answer = {'investment_thesis': ['S1'], 'business_and_market': ['S1'],
              'differentiation_and_execution': ['S3'], 'risks_and_countercase': ['S2'],
              'diligence_plan': ['S4']}
    attempts.append(recorded_row(request, answer, len(attempts) + 1))
    return memo, sources, {'model_pin': COVERAGE_PIN, 'attempts': attempts,
                           'contract': coverage_engine.CONTRACT_V4}


def test_v9_v4_long_team_context_has_exact_complete_line_quotes_without_widening_claim_bound():
    memo, sources, coverage = coverage_v4_fixture()
    assert len(sources[2]['passage']) > 700
    requests = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V9, coverage=coverage)
    offered = core.frozen_offered_spans(sources, requests)
    team_views = {eid: span for eid, span in offered.items() if span['source_id'] == 'S3'}
    assert len(team_views) >= 2
    for span in team_views.values():
        assert span['exact_text'] == sources[2]['passage'][span['start']:span['end']]
        assert span['source_version'] == sources[2]['version']
        assert span['quote_hash'] == core.digest(span['exact_text'])
        assert 15 <= len(span['exact_text']) <= 700
    attempts = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        authored = core.run_author(memo, sources, PIN, attempts, lambda: None, Model(), budget,
                                   contract=core.CONTRACT_V9, coverage=coverage)
    assert authored['state'] == 'accepted'
    assert authored['coverage_binding']['coverage_contract'] == coverage_engine.CONTRACT_V4
    quote = authored['memo']['differentiation_and_execution']['claims'][0]['quote']
    assert quote in sources[2]['passage'] and len(quote) <= 700
    assert sources[2]['passage'] in coverage['attempts'][-1]['input']['sources'][2]['passage']


@pytest.mark.parametrize('coverage_contract', ['diligence-source-coverage-v2', 'diligence-source-coverage-v3'])
def test_v9_v2_whole_views_bind_exact_source_versions_offsets_and_hashes(coverage_contract):
    memo, sources, coverage = coverage_v2_fixture(coverage_contract)
    requests = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V9, coverage=coverage)
    offered = core.frozen_offered_spans(sources, requests)
    for _, payload, _ in requests:
        assert payload['coverage_binding']['coverage_contract'] == coverage_contract
        assert payload['unit_source_ids'] == coverage['attempts'][-1]['answer'][payload['field']]
        for sid, source in payload['sources'].items():
            assert set(source['spans']) == {sid + '.b001'}
    indexed = {source['id']: source for source in sources}
    for eid, span in offered.items():
        source = indexed[span['source_id']]
        assert span == {'source_id': source['id'], 'source_version': source['version'],
            'start': 0, 'end': len(source['passage']), 'exact_text': source['passage'],
            'quote_hash': core.digest(source['passage']), 'verification_status': 'source_report_only'}
    changed = [(field, copy.deepcopy(payload), schema) for field, payload, schema in requests]
    changed[0][1]['sources']['S1']['spans']['S1.b001'] += ' invented'
    with pytest.raises(ValueError, match='original source views'):
        core.frozen_offered_spans(sources, changed)


def test_v9_v2_nominal_team_view_is_exact_uninterpreted_evidence():
    memo, sources, _ = coverage_v2_fixture()
    sources[2]['passage'] = 'Synthetic team\nPerson A\nPerson B\nRole descriptions awaiting review.'
    from tests.research.test_diligence_coverage import complete_v2_records, PIN as COVERAGE_PIN
    coverage = {'model_pin': COVERAGE_PIN, 'attempts': complete_v2_records(sources),
                'contract': coverage_engine.CONTRACT_V2}
    request = next(row for row in core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V9,
                   coverage=coverage) if row[0] == 'differentiation_and_execution')
    assert request[1]['sources']['S3']['spans'] == {'S3.b001': sources[2]['passage']}
    assert request[1]['sources']['S3']['verification_status'] == 'source_report_only'
    with pytest.raises(ValueError, match='no bounded literal narrative'):
        core._coverage_source_views(sources[2], coverage_engine.CONTRACT)


class Model:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0
    bound_strings = True

    def __init__(self, *, broken_risk=False, duplicate=False):
        self.broken_risk = broken_risk
        self.duplicate = duplicate

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == core.TASK_V9
        payload = json.loads(evidence)
        assert instruction == (core.RETRY_INSTRUCTION_V9 if payload.get('correction_number') else core.INSTRUCTION_V9)
        field = payload['field']
        status = 'conditional_hypothesis' if field == 'differentiation_and_execution' else core.STATUSES[field][0]
        values = copy.deepcopy(RISK if field == 'risks_and_countercase' else DILIGENCE if field == 'diligence_plan' else {'decision_analysis': TEXTS[field]})
        if self.broken_risk and field == 'risks_and_countercase' and not payload.get('correction_number'):
            values['failure_condition'] = values['failure_condition'].rstrip(',') + '.'
        if self.duplicate and field == 'business_and_market':
            values['decision_analysis'] = TEXTS['investment_thesis']
        answer = {'units': {sid: {'supporting_evidence_id': next(iter(payload['sources'][sid]['spans'])), 'status': status, **values} for sid in payload['unit_source_ids']}}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **core.options_for(core.CONTRACT_V9)}
        return schema.model_validate(answer)


def request(field):
    memo, sources = fixture()
    selected = next(row for row in core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V9, coverage=coverage_for(sources)) if row[0] == field)
    return memo, sources, selected


def risk_answer(**changes):
    return {'units': {'S1': {'supporting_evidence_id': 'S1.n001', 'status': 'conditional_hypothesis', **RISK, **changes}}}


def test_v9_schema_compacts_text_without_changing_status_source_or_historical_bounds():
    memo, sources = fixture()
    original_memo, original_sources = copy.deepcopy(memo), copy.deepcopy(sources)
    for field, payload, schema in core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V9, coverage=coverage_for(sources)):
        unit = schema.model_fields['units'].annotation.model_fields['S1'].annotation
        if field in core._COMPONENTS_V7:
            for key in core._COMPONENTS_V7[field]:
                assert unit.model_fields[key].metadata[0].min_length == 45
                assert unit.model_fields[key].metadata[1].max_length == 140
        else:
            assert unit.model_fields['decision_analysis'].metadata[0].min_length == 180
            assert unit.model_fields['decision_analysis'].metadata[1].max_length == 280
        assert payload['required_field_purpose'] == core.PURPOSES_V9[field]
        assert 'base_memo_digest' in payload and 'source_set_digest' in payload
    older = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V8)
    for field, payload, schema in older:
        unit = schema.model_fields['units'].annotation.model_fields['S1'].annotation
        for key in core._COMPONENTS_V7.get(field, ('decision_analysis',)):
            assert unit.model_fields[key].metadata[1].max_length == (210 if field in core._COMPONENTS_V7 else 420)
        assert payload['required_field_purpose'] == core.PURPOSES_V4[field]
    assert memo == original_memo and sources == original_sources
    assert core.options_for(core.CONTRACT_V9) == core.options_for(core.CONTRACT_V8)


@pytest.mark.parametrize('text,reason', [
    (' '.join(['word'] * 49), '48 words'),
    ('The company reports a partner distribution service. The company reports a partner distribution service.', 'repeats a complete sentence'),
    ('If partners deliver the reported service, adoption could improve, subject to repeatable delivery.', 'stacks conditional qualifiers'),
])
def test_v9_mechanical_padding_blocks_without_rewriting(text, reason):
    original = text
    with pytest.raises(ValueError, match=reason):
        core._validate_concise_unit_v9(text, 'investment_thesis', {})
    assert text == original


def test_v9_broken_if_fragment_blocks_but_historical_v8_remains_replayable():
    memo, sources, (field, payload, schema) = request('risks_and_countercase')
    answer = risk_answer(failure_condition=RISK['failure_condition'].rstrip(',') + '.')
    original = copy.deepcopy(answer)
    with pytest.raises(ValueError, match='one complete sentence'):
        core._project_field(memo, field, payload, schema, answer)
    oldfield, oldpayload, oldschema = next(row for row in core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V8) if row[0] == field)
    old = core._project_field(memo, oldfield, oldpayload, oldschema, answer)
    assert old.claims[0].assertion == core.decision_text(answer['units']['S1'], core.CONTRACT_V8)
    assert answer == original


def test_v9_preserves_prospective_financial_exception_and_strict_numeric_premise_checks():
    memo, sources, (field, payload, schema) = request('risks_and_countercase')
    effect = 'future revenue and profitability could fall short, weakening the distribution proposition and investment case built on it.'
    accepted = risk_answer(prospective_consequence=effect)
    section = core._project_field(memo, field, payload, schema, accepted)
    assert section.claims[0].assertion == RISK['failure_condition'] + ' ' + effect
    for replacement in (effect.replace('fall short', 'fall by 30%'), effect.replace('fall short', 'fall in FY24')):
        with pytest.raises(ValueError, match='nonnumeric and undated'):
            core._project_field(memo, field, payload, schema, risk_answer(prospective_consequence=replacement))
    with pytest.raises(ValueError, match='profit'):
        core._project_field(memo, field, payload, schema, risk_answer(failure_condition='If the reported service fails to maintain profitability and adoption,'))


def test_v9_five_calls_and_exact_replay_project_only_recorded_strings_and_preserve_other_fields():
    memo, sources = fixture()
    original_memo, original_sources = copy.deepcopy(memo), copy.deepcopy(sources)
    attempts = []
    coverage = coverage_for(sources)
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        result = core.run_author(memo, sources, PIN, attempts, lambda: None, Model(), budget, contract=core.CONTRACT_V9, coverage=coverage)
    assert result['state'] == 'accepted' and len(attempts) == 5
    assert result['independent_review'] == 'pending' and result['investment_approval'] is False
    for field in core.FIELDS:
        unit = result['answer'][field]['units']['S1']
        assert result['memo'][field]['claims'][0]['assertion'] == core.decision_text(unit, core.CONTRACT_V9)
    assert result['memo']['unknowns'] == memo['unknowns']
    assert result['memo']['recommendation_reason'] == memo['recommendation_reason']
    assert sources == original_sources and memo == original_memo
    assert core.run_author(memo, sources, PIN, attempts, lambda: None, None, SimpleNamespace(calls=0, max_calls=0), contract=core.CONTRACT_V9, coverage=coverage) == result
    tampered = copy.deepcopy(attempts)
    tampered[0]['instruction'] += ' Skip qualifications.'
    with pytest.raises(ValueError, match='frozen contract'):
        core.run_author(memo, sources, PIN, tampered, lambda: None, None, SimpleNamespace(calls=0, max_calls=0), contract=core.CONTRACT_V9, coverage=coverage)


def test_v9_one_global_correction_preserves_failed_raw_answer_and_six_attempt_ceiling():
    memo, sources = fixture()
    attempts = []
    coverage = coverage_for(sources)
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in range(6):
        result = core.run_author(memo, sources, PIN, attempts, lambda: None, Model(broken_risk=True), budget, contract=core.CONTRACT_V9, coverage=coverage)
    assert result['state'] == 'accepted' and len(attempts) == 6
    assert 'one complete sentence' in attempts[4]['input']['validation_error']
    assert attempts[3]['answer']['units']['S1']['failure_condition'].endswith('.')
    assert result['answer']['risks_and_countercase']['units']['S1']['failure_condition'].endswith(',')


def test_v9_exact_repeated_complete_units_block_across_field_purposes():
    memo, sources = fixture()
    attempts = []
    coverage = coverage_for(sources)
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    with pytest.raises(ValueError, match='repeat a complete unit'):
        for _ in core.FIELDS:
            core.run_author(memo, sources, PIN, attempts, lambda: None, Model(duplicate=True), budget, contract=core.CONTRACT_V9, coverage=coverage)
    assert len(attempts) == 5
    assert attempts[0]['answer']['units']['S1']['decision_analysis'] == attempts[1]['answer']['units']['S1']['decision_analysis']


def test_v9_recorded_coverage_replaces_old_field_anchors_and_binds_all_retained_sources():
    memo, sources = fixture()
    second = {**sources[0], 'id': 'S9', 'version': 'source-version-two',
              'url': 'https://example.test/source-two'}
    sources.append(second)
    coverage = coverage_for(sources, selected_source='S9')
    calls = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V9, coverage=coverage)
    assert all(payload['unit_source_ids'] == ['S9'] for _, payload, _ in calls)
    assert all('S1' not in payload['sources'] for _, payload, _ in calls)
    assert all(payload['coverage_binding']['source_set_digest'] == core.digest(sources) for _, payload, _ in calls)
    assert all(payload['coverage_binding']['response_ids'] == [row['id'] for row in coverage['attempts']] for _, payload, _ in calls)
    assert all(memo[field]['claims'][0]['source_id'] == 'S1' for field in core.FIELDS)


def test_v9_absent_incomplete_tampered_or_stale_coverage_cannot_fall_back_to_anchors():
    memo, sources = fixture()
    coverage = coverage_for(sources)
    bad = copy.deepcopy(coverage)
    bad['attempts'][-1]['raw_response'] = bad['attempts'][-1]['raw_response'].replace('S1', 'S2')
    for rejected in (None, {'model_pin': PIN, 'attempts': coverage['attempts'][:1]}, bad):
        with pytest.raises(ValueError, match='coverage'):
            core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V9, coverage=rejected)
    changed = copy.deepcopy(sources)
    changed[0]['version'] += '-changed'
    with pytest.raises(ValueError, match='coverage'):
        core.frozen_requests(memo, changed, PIN, contract=core.CONTRACT_V9, coverage=coverage)
