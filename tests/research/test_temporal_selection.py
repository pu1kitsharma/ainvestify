import copy

import pytest

from agents.research.temporal_selection import select_temporal_binding, period_tokens

QUOTE = 'Atlas reports a plan.' + chr(10) + 'FY2022 Exit'
FY_AT = QUOTE.index('FY2022')
UNDATED_END = len('Atlas reports a plan.')


def make_claims():
    return [
        {
            'id': 'c1',
            'source_id': 's1',
            'source_quote': QUOTE,
            'temporal_evidence': [
                {
                    'id': 'sp_dated',
                    'source_id': 's1',
                    'start': FY_AT,
                    'end': len(QUOTE),
                    'exact_text': QUOTE[FY_AT:],
                },
                {
                    'id': 'sp_undated',
                    'source_id': 's1',
                    'start': 0,
                    'end': UNDATED_END,
                    'exact_text': QUOTE[:UNDATED_END],
                },
            ],
        },
        {
            'id': 'c2',
            'source_id': 's1',
            'source_quote': QUOTE,
            'temporal_evidence': [
                {
                    'id': 'sp_other',
                    'source_id': 's1',
                    'start': 0,
                    'end': 5,
                    'exact_text': QUOTE[:5],
                }
            ],
        },
    ]


def call(claims, claim_id='c1', span_id='sp_dated', basis='historical_target', primary_period='FY2022'):
    return select_temporal_binding(claims, claim_id, span_id, basis, primary_period)


def assert_generic(exc_info, *secrets):
    msg = str(exc_info.value)
    for secret in ('Atlas', 'FY2022', 'FY2099', 'Exit') + secrets:
        assert secret not in msg


def test_dated_binding_returns_original_selection():
    claims = make_claims()
    result = call(claims)
    assert result['claim'] == claims[0]
    assert result['span'] == claims[0]['temporal_evidence'][0]
    assert result['basis'] == 'historical_target'
    assert result['primary_period'] == 'FY2022'
    assert set(result) == {'claim', 'span', 'basis', 'primary_period'}


def test_historical_observation_basis_ok():
    assert call(make_claims(), basis='historical_observation')['basis'] == 'historical_observation'


def test_input_not_mutated_and_result_is_copy():
    claims = make_claims()
    snapshot = copy.deepcopy(claims)
    result = call(claims)
    assert claims == snapshot
    result['span']['start'] = 999
    result['claim']['temporal_evidence'].clear()
    assert claims == snapshot


def test_legitimate_undated_excerpt():
    result = call(make_claims(), span_id='sp_undated', basis='undated_report', primary_period=None)
    assert result['primary_period'] is None
    assert result['basis'] == 'undated_report'
    result = call(make_claims(), span_id='sp_undated', basis='undated_target', primary_period=None)
    assert result['basis'] == 'undated_target'


def test_undated_excerpt_rejects_nonnull_period():
    with pytest.raises(ValueError) as e:
        call(make_claims(), span_id='sp_undated', basis='undated_report', primary_period='FY2022')
    assert_generic(e)


@pytest.mark.parametrize('basis', ['undated_target', 'undated_report'])
def test_undated_basis_with_dated_excerpt_rejected(basis):
    with pytest.raises(ValueError) as e:
        call(make_claims(), basis=basis, primary_period=None)
    assert_generic(e)


def test_null_period_with_dated_excerpt_rejected():
    with pytest.raises(ValueError) as e:
        call(make_claims(), primary_period=None)
    assert_generic(e)


@pytest.mark.parametrize('period', ['FY2023', 'FY2099', 'fy2022x', '2021', 'FY22', ''])
def test_unrelated_primary_period_rejected(period):
    with pytest.raises(ValueError) as e:
        call(make_claims(), primary_period=period)
    assert_generic(e)


def test_dated_basis_on_undated_excerpt_rejected():
    with pytest.raises(ValueError):
        call(make_claims(), span_id='sp_undated', basis='historical_target', primary_period='FY2022')
    with pytest.raises(ValueError):
        call(make_claims(), span_id='sp_undated', basis='historical_target', primary_period=None)


def test_source_mismatch_rejected():
    claims = make_claims()
    claims[0]['temporal_evidence'][0]['source_id'] = 's2'
    with pytest.raises(ValueError) as e:
        call(claims)
    assert_generic(e, 's2')


def test_span_claim_id_mismatch_rejected():
    claims = make_claims()
    claims[0]['temporal_evidence'][0]['claim_id'] = 'c2'
    with pytest.raises(ValueError):
        call(claims)


def test_span_owned_by_other_claim_rejected():
    with pytest.raises(ValueError):
        call(make_claims(), span_id='sp_other')


def test_unknown_ids_rejected():
    with pytest.raises(ValueError):
        call(make_claims(), claim_id='nope')
    with pytest.raises(ValueError):
        call(make_claims(), span_id='nope')


@pytest.mark.parametrize(
    'start,end',
    [(FY_AT, len(QUOTE) + 1), (-1, 5), (5, 5), (8, 3), (0, 10 ** 6)],
)
def test_out_of_range_offsets_rejected(start, end):
    claims = make_claims()
    span = claims[0]['temporal_evidence'][0]
    span['start'] = start
    span['end'] = end
    with pytest.raises(ValueError) as e:
        call(claims)
    assert_generic(e)


@pytest.mark.parametrize('field,value', [('start', False), ('end', True), ('start', 1.0), ('end', '5'), ('start', None)])
def test_non_int_and_bool_offsets_rejected(field, value):
    claims = make_claims()
    span = claims[0]['temporal_evidence'][1]
    span[field] = value
    with pytest.raises(ValueError):
        call(claims, span_id='sp_undated', basis='undated_report', primary_period=None)


def test_exact_text_must_match_quote_slice():
    claims = make_claims()
    claims[0]['temporal_evidence'][0]['exact_text'] = 'FY2023 Exit'
    with pytest.raises(ValueError):
        call(claims, primary_period='FY2023')


def test_duplicate_claim_ids_rejected():
    claims = make_claims()
    claims[1]['id'] = 'c1'
    with pytest.raises(ValueError):
        call(claims)


def test_duplicate_span_ids_within_selected_claim_rejected():
    claims = make_claims()
    claims[0]['temporal_evidence'][1]['id'] = 'sp_dated'
    with pytest.raises(ValueError):
        call(claims)


def test_duplicate_span_ids_across_claims_rejected():
    claims = make_claims()
    claims[1]['temporal_evidence'][0]['id'] = 'sp_dated'
    with pytest.raises(ValueError):
        call(claims)


def test_invalid_basis_rejected():
    with pytest.raises(ValueError):
        call(make_claims(), basis='achieved')
    with pytest.raises(ValueError):
        call(make_claims(), basis=None)


def test_malformed_inputs_rejected():
    with pytest.raises(ValueError):
        call('not a list')
    with pytest.raises(ValueError):
        call([None])
    with pytest.raises(ValueError):
        call(make_claims(), claim_id='')
    with pytest.raises(ValueError):
        call(make_claims(), primary_period=2022)


@pytest.mark.parametrize(
    'text,period',
    [
        ('Review in FY22 only', 'FY22'),
        ('Review in 2019 only', '2019'),
        ('Review in March 2022 only', 'March 2022'),
        ('Review in Mar/22 only', 'Mar/22'),
        ('Review in Sept-2021 only', 'Sept-2021'),
    ],
)
def test_period_token_forms(text, period):
    claim = {
        'id': 'c',
        'source_id': 's',
        'source_quote': text,
        'temporal_evidence': [{'id': 'p', 'source_id': 's', 'start': 0, 'end': len(text), 'exact_text': text}],
    }
    assert select_temporal_binding([claim], 'c', 'p', 'historical_observation', period)['primary_period'] == period


def test_fiscal_year_digits_do_not_yield_bare_year():
    with pytest.raises(ValueError):
        call(make_claims(), primary_period='2022')


def test_non_period_numbers_are_not_dated():
    text = 'Plan has 1234 items and FY123 label'
    claim = {
        'id': 'c',
        'source_id': 's',
        'source_quote': text,
        'temporal_evidence': [{'id': 'p', 'source_id': 's', 'start': 0, 'end': len(text), 'exact_text': text}],
    }
    result = select_temporal_binding([claim], 'c', 'p', 'undated_report', None)
    assert result['primary_period'] is None


def test_shared_exact_source_span_may_support_distinct_claims():
    claims = make_claims()
    claims[1]['temporal_evidence'] = copy.deepcopy(claims[0]['temporal_evidence'])
    assert call(claims)['span']['id'] == 'sp_dated'


def test_claim_span_token_inventory_must_be_exact():
    claims = make_claims()
    claims[0]['temporal_evidence'][0]['period_tokens'] = ['FY2023']
    with pytest.raises(ValueError):
        call(claims)


def test_month_period_not_reduced_to_year_and_spaced_fiscal_year_retained():
    assert period_tokens('March 2022, FY 2023') == {'March 2022', 'FY 2023'}


@pytest.mark.parametrize('basis', ['historical_target', 'dated_target', 'historical_observation', 'dated_observation'])
def test_all_dated_classes_bind_exact_period(basis):
    assert call(make_claims(), basis=basis)['basis'] == basis
