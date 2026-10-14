import pytest

from agents.research.rationale_scope import validate_scope_judgments


def judgment(**overrides):
    base = {
        'evidence_id': 'ev-1',
        'source_time_basis': 'historical',
        'asserted_time_basis': 'historical',
        'quantification_scope': 'source_stated',
        'reason': 'Synthetic reason.',
        'relation': 'supported_fact',
    }
    base.update(overrides)
    return base


def answer(**judgments):
    return {'judgments': judgments}


# --- controls: internally consistent answers ---

def test_consistent_historical_passes():
    assert validate_scope_judgments(answer(a=judgment())) is None


def test_projected_report_with_explicit_projected_passes():
    j = judgment(source_time_basis='projected', asserted_time_basis='projected')
    assert validate_scope_judgments(answer(a=j)) is None


def test_explicitly_mixed_report_with_explicit_mixed_passes():
    j = judgment(source_time_basis='mixed', asserted_time_basis='mixed')
    assert validate_scope_judgments(answer(a=j)) is None


def test_scoped_gap_with_source_scoped_gap_passes():
    j = judgment(relation='scoped_gap', quantification_scope='source_scoped_gap')
    assert validate_scope_judgments(answer(a=j)) is None


def test_conditional_question_without_evidence_passes():
    j = judgment(relation='conditional_question', evidence_id=None)
    assert validate_scope_judgments(answer(a=j)) is None


@pytest.mark.parametrize('relation', ['unsupported', 'insufficient_evidence'])
def test_non_passing_relations_may_carry_flagged_contradictions(relation):
    j = judgment(
        relation=relation,
        evidence_id=None,
        source_time_basis='projected',
        asserted_time_basis='historical',
        quantification_scope='unproven_absence',
    )
    assert validate_scope_judgments(answer(a=j)) is None


# --- classifier contradictions ---

@pytest.mark.parametrize(
    'relation', ['supported_fact', 'scoped_gap', 'conditional_question']
)
def test_passing_relation_with_unproven_absence_rejected(relation):
    j = judgment(relation=relation, quantification_scope='unproven_absence')
    with pytest.raises(ValueError, match='unproven_absence'):
        validate_scope_judgments(answer(a=j))


def test_projected_source_historical_sentence_rejected():
    j = judgment(source_time_basis='projected', asserted_time_basis='historical')
    with pytest.raises(ValueError, match='projected'):
        validate_scope_judgments(answer(a=j))


def test_mixed_source_historical_sentence_rejected():
    j = judgment(source_time_basis='mixed', asserted_time_basis='historical')
    with pytest.raises(ValueError, match='mixed'):
        validate_scope_judgments(answer(a=j))


@pytest.mark.parametrize('source', ['projected', 'mixed'])
@pytest.mark.parametrize('asserted', ['unspecified', 'not_stated'])
def test_supported_fact_on_projected_or_mixed_needs_explicit_basis(source, asserted):
    j = judgment(source_time_basis=source, asserted_time_basis=asserted)
    with pytest.raises(ValueError, match='explicit'):
        validate_scope_judgments(answer(a=j))


def test_unspecified_basis_allowed_for_non_supported_fact_on_projected():
    j = judgment(
        relation='conditional_question',
        evidence_id=None,
        source_time_basis='projected',
        asserted_time_basis='unspecified',
    )
    assert validate_scope_judgments(answer(a=j)) is None


@pytest.mark.parametrize('relation', ['supported_fact', 'scoped_gap'])
def test_null_evidence_rejected_when_required(relation):
    j = judgment(relation=relation, evidence_id=None)
    with pytest.raises(ValueError, match='evidence_id'):
        validate_scope_judgments(answer(a=j))


# --- no prose inference ---

def test_reason_text_never_changes_the_verdict():
    # Prose that sounds like a contradiction must not trigger one.
    j = judgment(reason='This is a projected figure and an unproven absence.')
    assert validate_scope_judgments(answer(a=j)) is None


def test_reason_text_cannot_rescue_a_declared_contradiction():
    j = judgment(
        source_time_basis='projected',
        asserted_time_basis='historical',
        reason='Explicitly projected, scoped, and qualified.',
    )
    with pytest.raises(ValueError):
        validate_scope_judgments(answer(a=j))


# --- structure ---

@pytest.mark.parametrize('bad', [None, [], 'x', {}, {'judgments': {}}, {'judgments': []}])
def test_bad_top_level_or_empty_judgments_rejected(bad):
    with pytest.raises(ValueError):
        validate_scope_judgments(bad)


@pytest.mark.parametrize(
    'field',
    [
        'evidence_id',
        'source_time_basis',
        'asserted_time_basis',
        'quantification_scope',
        'reason',
        'relation',
    ],
)
def test_missing_required_field_rejected(field):
    j = judgment()
    del j[field]
    with pytest.raises(ValueError, match=field):
        validate_scope_judgments(answer(a=j))


@pytest.mark.parametrize(
    'field,value',
    [
        ('source_time_basis', 'unspecified'),  # only valid for asserted
        ('asserted_time_basis', 'future'),
        ('quantification_scope', 'Source_Stated'),
        ('relation', 'maybe'),
        ('relation', ['supported_fact']),
        ('source_time_basis', None),
    ],
)
def test_invalid_enum_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        validate_scope_judgments(answer(a=judgment(**{field: value})))


@pytest.mark.parametrize('evidence_id', ['', '   ', 5, ['ev-1']])
def test_bad_evidence_id_type_rejected(evidence_id):
    with pytest.raises(ValueError, match='evidence_id'):
        validate_scope_judgments(answer(a=judgment(evidence_id=evidence_id)))


@pytest.mark.parametrize('reason', ['', '  ', None, 3])
def test_bad_reason_rejected(reason):
    with pytest.raises(ValueError, match='reason'):
        validate_scope_judgments(answer(a=judgment(reason=reason)))


def test_unknown_field_rejected():
    with pytest.raises(ValueError, match='unknown field'):
        validate_scope_judgments(answer(a=judgment(verdict='ok')))


def test_non_mapping_judgment_rejected():
    with pytest.raises(ValueError, match='mapping'):
        validate_scope_judgments({'judgments': {'a': 'nope'}})


def test_errors_name_the_offending_id_and_collect_all():
    good = judgment()
    bad1 = judgment(quantification_scope='unproven_absence')
    bad2 = judgment(source_time_basis='mixed', asserted_time_basis='historical')
    with pytest.raises(ValueError) as exc:
        validate_scope_judgments(answer(ok=good, bad1=bad1, bad2=bad2))
    msg = str(exc.value)
    assert 'bad1' in msg and 'bad2' in msg and 'ok:' not in msg
