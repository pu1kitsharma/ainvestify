import copy

import pytest

from agents.research.rationale_judgments import validate_judgments

PASSAGE_A = 'Revenue grew 12% in fiscal 2024. Margins were flat.'
PASSAGE_B = 'The filing does not discuss pricing.'
PASSAGE_C = 'Unselected passage text.'
REASON = 'Reason that is long enough to pass.'


def make_payload():
    return {
        'sentences': {
            's1': 'Revenue rose.',
            's2': 'Pricing power is unclear.',
            's3': 'If demand holds, will margins expand?',
        },
        'selected_source_ids': ['A', 'B'],
        'sources': [
            {'id': 'A', 'passage': PASSAGE_A, 'version': 'v1', 'attribution': 'Annual report'},
            {'id': 'B', 'passage': PASSAGE_B, 'version': 2, 'attribution': 'Filing'},
            {'id': 'C', 'passage': PASSAGE_C, 'version': 'v3', 'attribution': 'Other'},
        ],
    }


def row(relation, source_id=None, excerpt='', reason=REASON):
    return {
        'relation': relation,
        'source_id': source_id,
        'source_excerpt': excerpt,
        'reason': reason,
    }


def make_answer(status='answered'):
    return {
        'judgments': {
            's1': row('supported_fact', 'A', 'Revenue grew 12%'),
            's2': row('scoped_gap', 'B', 'does not discuss pricing'),
            's3': row('conditional_question'),
        },
        'diligence_status': status,
    }


def test_clean_answer_has_no_blockers():
    assert validate_judgments(make_payload(), make_answer()) == []


def test_inputs_are_not_mutated():
    payload, answer = make_payload(), make_answer()
    p0, a0 = copy.deepcopy(payload), copy.deepcopy(answer)
    validate_judgments(payload, answer)
    assert payload == p0 and answer == a0


def test_unsupported_blocks_with_expected_shape():
    answer = make_answer()
    answer['judgments']['s2'] = row('unsupported', None, '', 'Model found nothing backing this claim.')
    result = validate_judgments(make_payload(), answer)
    assert result == [{
        'focus_sentence_id': 's2',
        'exact_sentence': 'Pricing power is unclear.',
        'source_id': None,
        'reason': 'Model found nothing backing this claim.',
        'verdict': 'unsupported',
    }]


def test_insufficient_evidence_blocks_and_keeps_bound_source():
    answer = make_answer()
    answer['judgments']['s1'] = row('insufficient_evidence', 'A', 'Margins were flat')
    result = validate_judgments(make_payload(), answer)
    assert len(result) == 1
    assert result[0]['verdict'] == 'insufficient_evidence'
    assert result[0]['source_id'] == 'A'
    assert result[0]['exact_sentence'] == 'Revenue rose.'


def test_blockers_follow_payload_sentence_order():
    answer = make_answer()
    answer['judgments']['s3'] = row('unsupported')
    answer['judgments']['s1'] = row('insufficient_evidence')
    ids = [b['focus_sentence_id'] for b in validate_judgments(make_payload(), answer)]
    assert ids == ['s1', 's3']


def test_scoped_gap_and_conditional_question_do_not_block():
    answer = make_answer()
    answer['judgments']['s1'] = row('scoped_gap', 'A', 'Margins were flat')
    answer['judgments']['s2'] = row('conditional_question', 'B')
    assert validate_judgments(make_payload(), answer) == []


@pytest.mark.parametrize('status', ['answered', 'open', 'not_applicable'])
def test_diligence_status_alone_never_blocks(status):
    assert validate_judgments(make_payload(), make_answer(status)) == []


def test_open_status_does_not_change_blockers():
    answer = make_answer('open')
    answer['judgments']['s3'] = row('unsupported')
    result = validate_judgments(make_payload(), answer)
    assert [b['focus_sentence_id'] for b in result] == ['s3']


@pytest.mark.parametrize('status', ['closed', '', None, 3, 'OPEN'])
def test_invalid_diligence_status_raises(status):
    answer = make_answer()
    answer['diligence_status'] = status
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


def test_relation_is_never_inferred_from_prose():
    payload = make_payload()
    payload['sentences']['s1'] = 'This is unsupported and has insufficient evidence.'
    assert validate_judgments(payload, make_answer()) == []


def test_missing_judgment_raises():
    answer = make_answer()
    del answer['judgments']['s2']
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


def test_extra_judgment_raises():
    answer = make_answer()
    answer['judgments']['s9'] = row('unsupported')
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


def test_renamed_sentence_id_raises():
    answer = make_answer()
    answer['judgments']['s4'] = answer['judgments'].pop('s3')
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


def test_answer_top_level_keys_must_be_exact():
    answer = make_answer()
    answer['note'] = 'extra'
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)
    answer = make_answer()
    del answer['diligence_status']
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


@pytest.mark.parametrize('bad', [None, [], 'x', 5])
def test_non_dict_row_raises(bad):
    answer = make_answer()
    answer['judgments']['s1'] = bad
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


@pytest.mark.parametrize('key', ['relation', 'source_id', 'source_excerpt', 'reason'])
def test_row_missing_key_raises(key):
    answer = make_answer()
    del answer['judgments']['s3'][key]
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


def test_row_extra_key_raises():
    answer = make_answer()
    answer['judgments']['s3']['confidence'] = 0.9
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


@pytest.mark.parametrize('relation', ['Supported_Fact', 'maybe', '', None, 1, ['unsupported']])
def test_invalid_relation_raises(relation):
    answer = make_answer()
    answer['judgments']['s3']['relation'] = relation
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


@pytest.mark.parametrize('reason', ['', 'too short', 'x' * 19, 'x' * 601, None, 12345])
def test_reason_out_of_bounds_raises(reason):
    answer = make_answer()
    answer['judgments']['s3']['reason'] = reason
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


@pytest.mark.parametrize('length', [20, 600])
def test_reason_boundaries_accepted(length):
    answer = make_answer()
    answer['judgments']['s3']['reason'] = 'r' * length
    assert validate_judgments(make_payload(), answer) == []


def test_blank_reason_of_valid_length_raises():
    answer = make_answer()
    answer['judgments']['s3']['reason'] = ' ' * 30
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


@pytest.mark.parametrize('relation', ['supported_fact', 'scoped_gap'])
class TestEvidenceBound:
    def run(self, relation, source_id, excerpt):
        answer = make_answer()
        answer['judgments']['s1'] = row(relation, source_id, excerpt)
        return validate_judgments(make_payload(), answer)

    def test_valid_binding_passes(self, relation):
        assert self.run(relation, 'A', 'Revenue grew 12% in fiscal 2024.') == []

    def test_null_source_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, None, 'Revenue grew 12%')

    def test_empty_excerpt_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, 'A', '')

    def test_whitespace_excerpt_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, 'A', ' ')

    @pytest.mark.parametrize('excerpt', [
        'revenue grew 12%',
        'Revenue grew 13%',
        'Revenue  grew 12%',
        'Revenue grew 12% Margins were flat',
        'Revenue grew 12% in fiscal 2024. Margins were flat. Extra',
        ' Revenue grew 12%.',
    ])
    def test_tampered_or_noncontiguous_excerpt_raises(self, relation, excerpt):
        with pytest.raises(ValueError):
            self.run(relation, 'A', excerpt)

    def test_excerpt_from_other_source_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, 'B', 'Revenue grew 12%')

    def test_unselected_source_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, 'C', 'Unselected passage')

    def test_unknown_source_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, 'Z', 'Revenue grew 12%')

    def test_non_string_source_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, 1, 'Revenue grew 12%')


@pytest.mark.parametrize('relation', ['unsupported', 'insufficient_evidence'])
class TestNegativeRelations:
    def run(self, relation, source_id, excerpt):
        answer = make_answer()
        answer['judgments']['s2'] = row(relation, source_id, excerpt)
        return validate_judgments(make_payload(), answer)

    def test_null_source_and_empty_excerpt_blocks(self, relation):
        result = self.run(relation, None, '')
        assert [b['verdict'] for b in result] == [relation]

    def test_source_without_excerpt_blocks(self, relation):
        result = self.run(relation, 'B', '')
        assert result[0]['source_id'] == 'B'

    def test_bound_excerpt_blocks(self, relation):
        result = self.run(relation, 'B', 'does not discuss')
        assert result[0]['source_id'] == 'B'

    def test_unbound_excerpt_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, 'B', 'invented text')

    def test_excerpt_with_null_source_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, None, 'does not discuss')

    def test_unselected_source_raises(self, relation):
        with pytest.raises(ValueError):
            self.run(relation, 'C', '')


class TestConditionalQuestion:
    def run(self, source_id, excerpt):
        answer = make_answer()
        answer['judgments']['s3'] = row('conditional_question', source_id, excerpt)
        return validate_judgments(make_payload(), answer)

    def test_no_evidence_ok(self):
        assert self.run(None, '') == []

    def test_null_source_with_excerpt_raises(self):
        with pytest.raises(ValueError):
            self.run(None, 'Revenue grew 12%')

    def test_source_with_bound_excerpt_ok(self):
        assert self.run('A', 'Margins were flat') == []

    def test_source_with_unbound_excerpt_raises(self):
        with pytest.raises(ValueError):
            self.run('A', 'Margins were rising')

    def test_unselected_source_raises(self):
        with pytest.raises(ValueError):
            self.run('C', '')


def test_duplicate_source_ids_raise():
    payload = make_payload()
    payload['sources'].append(dict(payload['sources'][0]))
    with pytest.raises(ValueError):
        validate_judgments(payload, make_answer())


def test_duplicate_selected_ids_raise():
    payload = make_payload()
    payload['selected_source_ids'] = ['A', 'A']
    with pytest.raises(ValueError):
        validate_judgments(payload, make_answer())


def test_selected_id_missing_from_sources_raises():
    payload = make_payload()
    payload['selected_source_ids'].append('Q')
    with pytest.raises(ValueError):
        validate_judgments(payload, make_answer())


@pytest.mark.parametrize('field', ['id', 'passage', 'version', 'attribution'])
def test_source_missing_field_raises(field):
    payload = make_payload()
    del payload['sources'][0][field]
    with pytest.raises(ValueError):
        validate_judgments(payload, make_answer())


@pytest.mark.parametrize('field,value', [
    ('id', ''), ('id', 7), ('passage', ''), ('passage', None),
    ('version', None), ('version', True), ('version', ' '),
    ('attribution', ''), ('attribution', 4),
])
def test_source_bad_field_value_raises(field, value):
    payload = make_payload()
    payload['sources'][0][field] = value
    with pytest.raises(ValueError):
        validate_judgments(payload, make_answer())


def test_non_dict_source_raises():
    payload = make_payload()
    payload['sources'].append('not a dict')
    with pytest.raises(ValueError):
        validate_judgments(payload, make_answer())


def test_malformed_payload_shapes_raise():
    for key, bad in [('sentences', ['a']), ('sources', {}), ('selected_source_ids', 'A')]:
        payload = make_payload()
        payload[key] = bad
        with pytest.raises(ValueError):
            validate_judgments(payload, make_answer())
    with pytest.raises(ValueError):
        validate_judgments([], make_answer())
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), [])


def test_non_string_sentence_text_raises():
    payload = make_payload()
    payload['sentences']['s1'] = 5
    with pytest.raises(ValueError):
        validate_judgments(payload, make_answer())


def test_judgments_must_be_mapping():
    answer = make_answer()
    answer['judgments'] = [row('unsupported')]
    with pytest.raises(ValueError):
        validate_judgments(make_payload(), answer)


def test_exact_sentence_comes_from_payload_verbatim():
    payload = make_payload()
    payload['sentences']['s3'] = '  Odd spacing,  kept exactly?  '
    answer = make_answer()
    answer['judgments']['s3'] = row('unsupported')
    result = validate_judgments(payload, answer)
    assert result[0]['exact_sentence'] == '  Odd spacing,  kept exactly?  '
