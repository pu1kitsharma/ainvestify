'''Synthetic tests for scoped_unit_review. CompanyQ is an arbitrary fixture name.'''
import copy

import pytest

from agents.research.scoped_unit_review import build_schema, unit_states, validate_answer

JUDGMENT_FIELDS = {
    'function', 'evidence_id', 'source_time_basis', 'asserted_time_basis', 'quantification_scope',
    'requires_explicit_quantification_claim', 'has_unsupported_premise', 'preserves_time_scope', 'reason', 'relation',
}


def card(basis, flag=False):
    return {'reporting_basis': basis, 'contains_explicit_incomplete_quantification_claim': flag}


def span(source_id, text='CompanyQ synthetic excerpt.'):
    return {'source_id': source_id, 'exact_text': text}


def make_units():
    return {
        'rat': {
            'text': 'CompanyQ revenue grew in the last reported year.',
            'required_function': 'investment_rationale',
            'requested_time_basis': 'historical',
            'evidence_spans': {'rat_hist': span('S_hist'), 'rat_plan': span('S_plan')},
            'source_cards': {'S_hist': card('historical'), 'S_plan': card('projected')},
        },
        'proj': {
            'text': 'CompanyQ plans a new facility.',
            'required_function': 'investment_rationale',
            'requested_time_basis': 'projected',
            'evidence_spans': {'proj_plan': span('S_plan')},
            'source_cards': {'S_plan': card('projected')},
        },
        'gap': {
            'text': 'CompanyQ customer count is only partly quantified.',
            'required_function': 'investment_rationale',
            'requested_time_basis': 'current',
            'evidence_spans': {'gap_mixed': span('S_mixed'), 'gap_hist': span('S_hist')},
            'source_cards': {'S_mixed': card('mixed', True), 'S_hist': card('historical', False)},
        },
        'cond': {
            'text': 'If CompanyQ expands, margins may matter.',
            'required_function': 'conditional_importance',
            'requested_time_basis': 'not_stated',
            'evidence_spans': {'cond_plan': span('S_plan')},
            'source_cards': {'S_plan': card('projected')},
        },
        'inq': {
            'text': 'What is CompanyQ churn?',
            'required_function': 'inquiry',
            'requested_time_basis': 'current',
            'evidence_spans': {},
            'source_cards': {},
        },
        'req': {
            'text': 'Please provide CompanyQ contracts.',
            'required_function': 'record_request',
            'requested_time_basis': 'not_stated',
            'evidence_spans': {},
            'source_cards': {},
        },
    }


def judgment(**over):
    base = {
        'function': 'conditional_importance',
        'evidence_id': None,
        'source_time_basis': 'not_applicable',
        'asserted_time_basis': 'not_applicable',
        'quantification_scope': 'not_applicable',
        'requires_explicit_quantification_claim': False,
        'has_unsupported_premise': False, 'preserves_time_scope': True,
        'reason': 'Structured judgment recorded for this unit.',
        'relation': 'conditional_question',
    }
    base.update(over)
    return base


def make_answer():
    return {'judgments': {
        'rat': judgment(function='investment_rationale', evidence_id='rat_hist',
                        source_time_basis='historical', asserted_time_basis='historical',
                        relation='supported_fact'),
        'proj': judgment(function='investment_rationale', evidence_id='proj_plan',
                         source_time_basis='projected', asserted_time_basis='projected',
                         relation='supported_fact'),
        'gap': judgment(function='investment_rationale', evidence_id='gap_mixed',
                        source_time_basis='mixed', asserted_time_basis='current',
                        quantification_scope='source_scoped_gap',
                        requires_explicit_quantification_claim=True, relation='scoped_gap'),
        'cond': judgment(function='conditional_importance'),
        'inq': judgment(function='inquiry'),
        'req': judgment(function='record_request'),
    }}


def reasons(units, answer, uid):
    return {b['unit_id'] and b['reason'] for b in validate_answer(units, answer) if b['unit_id'] == uid}


@pytest.fixture
def units():
    return make_units()


@pytest.fixture
def answer():
    return make_answer()


# ---- schema ------------------------------------------------------------------

def test_baseline_passes_schema_and_validation(units, answer):
    build_schema(units).model_validate(answer)


def test_excerpt_time_basis_version_preserves_mixed_source_subset_and_rejects_plan_as_history():
    spec = make_units()['rat']
    spec['requested_time_basis'] = 'not_stated'
    spec['source_cards']['S_hist'] = card('mixed')
    units = {'rat': spec}
    answer = {'judgments': {'rat': make_answer()['judgments']['rat']}}
    assert validate_answer(units, answer)  # Frozen legacy semantics remain exact.
    assert validate_answer(units, answer, excerpt_time_basis=True) == []
    answer['judgments']['rat']['source_time_basis'] = 'projected'
    assert any(b['reason'] == 'projected_source_asserted_as_current_or_historical'
               for b in validate_answer(units, answer, excerpt_time_basis=True))
    spec['source_cards']['S_hist'] = card('historical')
    assert any(b['reason'] == 'source_time_basis_mismatch'
               for b in validate_answer(units, answer, excerpt_time_basis=True))


def test_compact_schema_shares_only_identical_evidence_enums(units, answer):
    units['same_offer'] = copy.deepcopy(units['cond'])
    answer['judgments']['same_offer'] = copy.deepcopy(answer['judgments']['cond'])
    original = build_schema(units).model_json_schema()
    assert original == build_schema(units, compact=False).model_json_schema()
    compact = build_schema(units, compact=True)
    definitions = compact.model_json_schema()['$defs']
    refs = definitions['UnitJudgments']['properties']
    assert refs['same_offer']['$ref'] == refs['cond']['$ref']
    assert refs['rat']['$ref'] != refs['proj']['$ref']
    assert compact.model_validate(answer).model_dump(mode='json') == answer
    bad = copy.deepcopy(answer)
    bad['judgments']['same_offer']['evidence_id'] = 'proj_plan'
    with pytest.raises(ValueError):
        compact.model_validate(bad)
    assert len(str(compact.model_json_schema())) < len(str(original))


@pytest.mark.parametrize('field,value,reason', [
    ('preserves_source_attribution', False, 'source_attribution_not_preserved'),
    ('has_unsupported_metric_interpretation', True, 'unsupported_metric_interpretation'),
])
def test_source_semantics_classifications_block_false_positive_relation(units, answer, field, value, reason):
    for row in answer['judgments'].values():
        row.update(preserves_source_attribution=True, has_unsupported_metric_interpretation=False)
    assert validate_answer(units, answer, source_semantics=True) == []
    answer['judgments']['rat'][field] = value
    assert {'unit_id': 'rat', 'reason': reason} in validate_answer(units, answer, source_semantics=True)


def test_source_semantics_fields_are_required_without_changing_historical_schema(units, answer):
    assert validate_answer(units, answer) == []
    assert validate_answer(units, answer, source_semantics=True)
    assert validate_answer(units, answer) == []


def test_schema_has_exactly_the_judgment_fields_and_no_state_label(units):
    js = build_schema(units).model_json_schema()
    defs = [d for d in js['$defs'].values() if 'relation' in d.get('properties', {})]
    assert len(defs) == len(units)
    for d in defs:
        assert set(d['properties']) == JUDGMENT_FIELDS
        assert set(d['required']) == JUDGMENT_FIELDS
        assert d['additionalProperties'] is False


def test_extra_forbidden_everywhere(units, answer):
    a = copy.deepcopy(answer)
    a['extra'] = 1
    assert {b['reason'] for b in validate_answer(units, a)} >= {'answer_schema_invalid:extra_forbidden'}
    a = copy.deepcopy(answer)
    a['judgments']['ghost'] = judgment()
    assert {'unit_id': 'ghost', 'reason': 'unknown_unit_id'} in validate_answer(units, a)
    a = copy.deepcopy(answer)
    a['judgments']['inq']['state'] = 'answered'
    assert {'unit_id': 'inq', 'reason': 'unexpected_field:state'} in validate_answer(units, a)


@pytest.mark.parametrize('field', sorted(JUDGMENT_FIELDS))
def test_every_field_is_required(units, answer, field):
    del answer['judgments']['inq'][field]
    assert {'unit_id': 'inq', 'reason': f'missing_field:{field}'} in validate_answer(units, answer)


@pytest.mark.parametrize('field,values', [
    ('function', ['investment_rationale', 'conditional_importance', 'inquiry', 'record_request',
                  'answer_summary', 'draft_critique']),
    ('source_time_basis', ['historical', 'projected', 'mixed', 'not_stated', 'not_applicable']),
    ('asserted_time_basis', ['current', 'historical', 'projected', 'mixed', 'unspecified', 'not_applicable']),
    ('quantification_scope', ['source_stated', 'source_scoped_gap', 'unproven_absence', 'not_applicable']),
    ('relation', ['supported_fact', 'scoped_gap', 'conditional_question', 'unsupported',
                  'insufficient_evidence']),
])
def test_enum_domains(units, answer, field, values):
    schema = build_schema(units)
    for value in values:
        answer['judgments']['inq'][field] = value
        schema.model_validate(answer)
    answer['judgments']['inq'][field] = 'bogus'
    assert {'unit_id': 'inq', 'reason': f'invalid_field:{field}'} in validate_answer(units, answer)


def test_evidence_enum_is_per_unit_and_nullable(units, answer):
    schema = build_schema(units)
    for value in (None, 'rat_hist', 'rat_plan'):
        answer['judgments']['rat']['evidence_id'] = value
        schema.model_validate(answer)
    answer['judgments']['inq']['evidence_id'] = 'rat_hist'  # inq offers nothing
    assert {'unit_id': 'inq', 'reason': 'invalid_field:evidence_id'} in validate_answer(units, answer)


def test_strict_types_and_reason_bounds(units, answer):
    for field, bad in [('has_unsupported_premise', 'false'), ('preserves_time_scope', 'false'), ('requires_explicit_quantification_claim', 0),
                       ('reason', 'x' * 19), ('reason', 'x' * 161), ('reason', None)]:
        a = copy.deepcopy(answer)
        a['judgments']['inq'][field] = bad
        assert {'unit_id': 'inq', 'reason': f'invalid_field:{field}'} in validate_answer(units, a)
    for ok in ('x' * 20, 'x' * 160):
        answer['judgments']['inq']['reason'] = ok
        assert validate_answer(units, answer) == []


def test_whitespace_padded_reason_is_blocked(units, answer):
    answer['judgments']['inq']['reason'] = ' ' * 10 + 'short text'
    assert reasons(units, answer, 'inq') == {'reason_too_short'}


def test_arbitrary_unit_ids_do_not_collide_with_internal_names(answer):
    base = make_units()
    units = {'weird id/1': base['inq'], 'u0': base['req']}
    a = {'judgments': {'weird id/1': judgment(function='inquiry'), 'u0': judgment(function='record_request')}}
    assert validate_answer(units, a) == []
    swapped = {'judgments': {'weird id/1': judgment(function='record_request'),
                             'u0': judgment(function='inquiry')}}
    assert {b['unit_id'] for b in validate_answer(units, swapped)} == {'weird id/1', 'u0'}


def test_bad_unit_definitions_raise(units):
    for mutate in (
        lambda u: u['rat']['evidence_spans'].update(bad=span('S_missing')),
        lambda u: u['rat'].update(extra_key=1),
        lambda u: u['rat'].update(required_function='answer_summary'),
        lambda u: u['rat']['source_cards']['S_hist'].update(reporting_basis='current'),
        lambda u: u['rat'].pop('text'),
    ):
        u = copy.deepcopy(units)
        mutate(u)
        with pytest.raises(ValueError):
            build_schema(u)
    with pytest.raises(ValueError):
        build_schema({})


# ---- coverage ----------------------------------------------------------------

def test_missing_unit_and_malformed_envelope(units, answer):
    del answer['judgments']['req']
    assert validate_answer(units, answer) == [{'unit_id': 'req', 'reason': 'missing_unit_judgment'}]
    for bad in ('nope', None, {}, {'judgments': []}):
        got = validate_answer(units, bad)
        assert {b['unit_id'] for b in got} == set(units)
        assert all(b['reason'].startswith('answer_schema_invalid') for b in got)


def test_validation_does_not_modify_input(units, answer):
    answer['judgments']['rat']['has_unsupported_premise'] = True
    before, units_before = copy.deepcopy(answer), copy.deepcopy(units)
    assert validate_answer(units, answer)
    assert answer == before and units == units_before


# ---- function / relation -------------------------------------------------------

@pytest.mark.parametrize('uid', ['rat', 'proj', 'gap', 'cond', 'inq', 'req'])
@pytest.mark.parametrize('wrong', ['answer_summary', 'draft_critique'])
def test_non_passing_functions_block_every_unit(units, answer, uid, wrong):
    answer['judgments'][uid]['function'] = wrong
    assert 'function_mismatch' in reasons(units, answer, uid)


def test_wrong_function_between_valid_functions(units, answer):
    answer['judgments']['cond']['function'] = 'inquiry'
    assert reasons(units, answer, 'cond') == {'function_mismatch'}


def test_unknown_importance_cannot_be_falsely_answered(units, answer):
    answer['judgments']['cond'] = judgment(
        function='answer_summary', evidence_id='cond_plan', source_time_basis='projected',
        asserted_time_basis='current', relation='supported_fact')
    got = reasons(units, answer, 'cond')
    assert {'function_mismatch', 'relation_not_passing_for_required_function'} <= got
    assert set(unit_states(units).values()) == {'unresolved'}


@pytest.mark.parametrize('uid,relation', [
    ('cond', 'supported_fact'), ('cond', 'scoped_gap'), ('inq', 'supported_fact'),
    ('req', 'scoped_gap'), ('rat', 'conditional_question'),
    ('rat', 'unsupported'), ('rat', 'insufficient_evidence'), ('inq', 'unsupported'),
])
def test_relation_must_match_required_function(units, answer, uid, relation):
    answer['judgments'][uid]['relation'] = relation
    assert 'relation_not_passing_for_required_function' in reasons(units, answer, uid)


@pytest.mark.parametrize('relation', ['supported_fact', 'scoped_gap'])
def test_fact_and_gap_need_evidence(units, answer, relation):
    answer['judgments']['rat'].update(evidence_id=None, source_time_basis='not_applicable', relation=relation)
    assert 'missing_evidence' in reasons(units, answer, 'rat')


# ---- time basis ------------------------------------------------------------------

@pytest.mark.parametrize('asserted', ['current', 'historical'])
def test_future_source_cannot_pass_as_current_or_historical(units, answer, asserted):
    answer['judgments']['proj']['asserted_time_basis'] = asserted
    assert 'projected_source_asserted_as_current_or_historical' in reasons(units, answer, 'proj')
    answer['judgments']['rat'].update(evidence_id='rat_plan', source_time_basis='projected',
                                      asserted_time_basis=asserted)
    assert 'projected_source_asserted_as_current_or_historical' in reasons(units, answer, 'rat')


def test_mixed_source_asserted_as_current_without_scope_is_blocked(units, answer):
    answer['judgments']['gap'].update(relation='supported_fact', quantification_scope='source_stated',
                                      requires_explicit_quantification_claim=False, preserves_time_scope=False)
    assert 'projected_source_asserted_as_current_or_historical' in reasons(units, answer, 'gap')


def test_scoped_distinction_allows_mixed_source_current_wording(units, answer):
    assert reasons(units, answer, 'gap') == set()


def test_declared_mixed_wording_on_projected_source_passes(units, answer):
    answer['judgments']['rat'].update(evidence_id='rat_plan', source_time_basis='projected',
                                      asserted_time_basis='mixed')
    assert reasons(units, answer, 'rat') == set()


@pytest.mark.parametrize('asserted', ['unspecified', 'not_applicable'])
def test_factual_unit_must_state_a_basis(units, answer, asserted):
    answer['judgments']['rat']['asserted_time_basis'] = asserted
    assert 'asserted_time_basis_unresolved' in reasons(units, answer, 'rat')


def test_source_basis_must_match_own_card(units, answer):
    answer['judgments']['rat']['source_time_basis'] = 'projected'
    assert 'source_time_basis_mismatch' in reasons(units, answer, 'rat')
    answer['judgments']['rat']['source_time_basis'] = 'not_applicable'
    assert 'source_time_basis_mismatch' in reasons(units, answer, 'rat')


def test_conditional_may_decline_basis_but_must_match_if_given(units, answer):
    answer['judgments']['cond']['evidence_id'] = 'cond_plan'
    assert reasons(units, answer, 'cond') == set()
    answer['judgments']['cond']['source_time_basis'] = 'historical'
    assert reasons(units, answer, 'cond') == {'source_time_basis_mismatch'}
    answer['judgments']['cond']['source_time_basis'] = 'projected'
    assert reasons(units, answer, 'cond') == set()


def test_asserted_basis_differing_from_request_is_blocked_unless_gap(units, answer):
    answer['judgments']['rat'].update(evidence_id='rat_plan', source_time_basis='projected',
                                      asserted_time_basis='projected')
    assert 'asserted_basis_differs_from_requested' in reasons(units, answer, 'rat')


# ---- contradictory flags -----------------------------------------------------------

def test_unsupported_premise_and_unproven_absence_never_pass(units, answer):
    answer['judgments']['rat']['has_unsupported_premise'] = True
    assert 'unsupported_premise' in reasons(units, answer, 'rat')
    answer['judgments']['inq']['has_unsupported_premise'] = True
    assert 'unsupported_premise' in reasons(units, answer, 'inq')
    answer['judgments']['req']['quantification_scope'] = 'unproven_absence'
    assert 'unproven_absence' in reasons(units, answer, 'req')


@pytest.mark.parametrize('over,code', [
    ({'source_time_basis': 'historical'}, 'source_basis_without_evidence'),
    ({'quantification_scope': 'source_stated'}, 'quantification_scope_without_evidence'),
    ({'requires_explicit_quantification_claim': True}, 'quantification_claim_unbacked_by_own_source_card'),
])
def test_flags_that_claim_a_source_need_evidence(units, answer, over, code):
    answer['judgments']['inq'].update(over)
    assert code in reasons(units, answer, 'inq')


@pytest.mark.parametrize('over,code', [
    ({'quantification_scope': 'not_applicable'}, 'requires_quantification_but_scope_not_applicable'),
    ({'relation': 'supported_fact'}, 'supported_fact_with_scoped_gap_scope'),
])
def test_contradictory_quantification_flags(units, answer, over, code):
    answer['judgments']['gap'].update(over)
    assert code in reasons(units, answer, 'gap')


# ---- own-source evidence ---------------------------------------------------------------

def test_evidence_from_another_unit_is_rejected(units, answer):
    answer['judgments']['rat']['evidence_id'] = 'proj_plan'
    assert {'unit_id': 'rat', 'reason': 'invalid_field:evidence_id'} in validate_answer(units, answer)


def test_quantification_claim_needs_own_card_flag(units, answer):
    # gap_hist is a real offered span, but its card does not state incompleteness.
    answer['judgments']['gap'].update(evidence_id='gap_hist', source_time_basis='historical')
    assert 'quantification_claim_unbacked_by_own_source_card' in reasons(units, answer, 'gap')


def test_quantification_claim_without_evidence_is_blocked(units, answer):
    answer['judgments']['gap'].update(evidence_id=None, source_time_basis='not_applicable')
    got = reasons(units, answer, 'gap')
    assert {'missing_evidence', 'quantification_claim_unbacked_by_own_source_card'} <= got


def test_card_flag_alone_does_not_force_a_claim(units, answer):
    answer['judgments']['gap'].update(
        quantification_scope='source_stated', requires_explicit_quantification_claim=False,
        relation='scoped_gap', asserted_time_basis='projected')
    assert reasons(units, answer, 'gap') == set()


# ---- no keyword reading -------------------------------------------------------------------

def test_reason_and_unit_text_are_not_read_for_meaning(units, answer):
    loud = 'answered resolved supported by evidence; no evidence; projected current'
    for uid in answer['judgments']:
        answer['judgments'][uid]['reason'] = loud
    for u in units.values():
        u['text'] = 'answered resolved: projected plan stated as current fact'
    assert validate_answer(units, answer) == []
    answer['judgments']['rat']['has_unsupported_premise'] = True
    answer['judgments']['rat']['reason'] = 'fully supported, no unsupported premise at all'
    assert reasons(units, answer, 'rat') == {'unsupported_premise'}


def test_schema_dump_preserves_raw_unit_aliases(units, answer):
    assert build_schema(units).model_validate(answer).model_dump(mode='json') == answer


def test_mixed_source_dated_history_with_preserved_scope_is_reviewable(units, answer):
    units['gap']['requested_time_basis'] = 'not_stated'
    answer['judgments']['gap'].update(relation='supported_fact', quantification_scope='source_stated',
        requires_explicit_quantification_claim=False, asserted_time_basis='historical', preserves_time_scope=True)
    assert reasons(units, answer, 'gap') == set()
