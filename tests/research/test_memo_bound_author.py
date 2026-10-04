"""Synthetic source-local authoring and exact quote projection; no model calls."""
import pytest
from pydantic import ValidationError

from agents.research.memo_bound_author import (author_schema, author_schema_v9,
                                               author_schema_v10, author_schema_v11,
                                               author_schema_v12,
                                               author_sentence_count,
                                               project_decision, project_decision_v10,
                                               project_decision_v11,
                                               project_section, quote_lookup, select_schema)

QUOTE = ('A synthetic source reports one clinic pilot and does not report '
         'financial results or customer contracts.')
CARDS = [{'source_id': 'S1', 'attribution': 'Synthetic publisher', 'evidence': [
    {'status': 'source_reported', 'quote_id': 'S1.q1', 'quote': QUOTE}]}]


def _answer(count):
    sentence = ('The selected source reports a clinic pilot, while the record '
                'still needs independent verification before an investment decision.')
    return {'assertion': 'The selected source reports one clinic pilot.',
            'sentences': [sentence] * count}


def test_quote_selection_and_projection_keep_exact_source_text():
    lookup = quote_lookup(CARDS)
    selected = select_schema({'sources': CARDS}, 'decision').model_validate({
        'recommendation': 'defer_pending_evidence', 'quote_ids': ['S1.q1']})
    count = author_sentence_count('decision', len(selected.quote_ids))
    decision = project_decision(selected, [_answer(count)], lookup)
    assert decision.recommendation_claims[0].quote == QUOTE
    assert decision.recommendation_reason.count('[S1]') == 2
    section = select_schema({'sources': CARDS}, 'section').model_validate({
        'heading': 'Operating evidence', 'quote_ids': ['S1.q1']})
    projected = project_section(section, [_answer(author_sentence_count('section', 1))], lookup)
    assert projected.claims[0].quote == QUOTE
    assert projected.analysis.count('[S1]') == 3


def test_source_local_schema_rejects_numeric_drift_with_validation_feedback():
    answer = _answer(2)
    answer['assertion'] = 'The selected source reports 47 signed clinic contracts.'
    with pytest.raises(ValidationError, match='selected exact quote'):
        author_schema(QUOTE, 2).model_validate(answer)
    answer = _answer(2)
    answer['sentences'][0] = ('The selected source guarantees 47 signed clinic '
                              'contracts after the pilot, pending due diligence.')
    with pytest.raises(ValidationError, match='selected exact quote'):
        author_schema(QUOTE, 2).model_validate(answer)


def test_quote_ids_are_source_local_enumerated_and_distinct():
    with pytest.raises(ValidationError):
        select_schema({'sources': CARDS}, 'decision').model_validate({
            'recommendation': 'defer_pending_evidence', 'quote_ids': ['S9.q1']})
    with pytest.raises(ValidationError, match='distinct'):
        select_schema({'sources': CARDS}, 'decision').model_validate({
            'recommendation': 'defer_pending_evidence', 'quote_ids': ['S1.q1', 'S1.q1']})


def test_v10_reason_sentences_exclude_digits_but_assertion_can_bind_source_figures():
    quote = ('The synthetic registry reports 47 clinic pilots and has not '
             'verified repeat orders or financial results.')
    sentence = ('The pilot count is source reported, while repeat ordering and '
                'economic evidence still need independent verification.')
    answer = {'assertion': 'The registry reports 47 clinic pilots.',
              'sentences': [sentence]}
    schema = author_schema_v10(quote, 1)
    assert schema.model_validate(answer).assertion == answer['assertion']
    sentence_schema = schema.model_json_schema()['properties']['sentences']['items']
    assert sentence_schema['pattern'] == '^[^0-9]*$'
    with pytest.raises(ValidationError):
        schema.model_validate({**answer, 'sentences': [sentence + ' 47.']})
    assert author_schema_v9(quote, 1).model_validate(
        {**answer, 'sentences': [sentence + ' 47.']})
    spelled = ('The source reports one pilot, while repeat ordering and '
               'economic evidence still need independent verification.')
    with pytest.raises(ValidationError, match='omit numeric and date tokens'):
        author_schema_v10(QUOTE, 1).model_validate(
            {'assertion': 'The source reports one clinic pilot.',
             'sentences': [spelled]})
    assert author_schema_v9(QUOTE, 1).model_validate(
        {'assertion': 'The source reports one clinic pilot.',
         'sentences': [spelled]})


def test_v10_projection_keeps_model_prose_and_exact_quote():
    lookup = quote_lookup(CARDS)
    selection = select_schema({'sources': CARDS}, 'decision').model_validate({
        'recommendation': 'defer_pending_evidence', 'quote_ids': ['S1.q1']})
    decision = project_decision_v10(selection, [_answer(2)], lookup)
    assert decision.recommendation_claims[0].quote == QUOTE
    assert decision.recommendation_reason.count('[S1]') == 2


def test_v11_omits_all_numeric_paraphrase_but_preserves_selected_quote():
    quote = ('The synthetic registry reports 47 clinic pilots and has not '
             'verified repeat orders or financial results.')
    sentence = ('The pilot observation remains preliminary because the source '
                'does not establish repeated demand or economic performance.')
    answer = {'assertion': 'The registry reports a clinic pilot observation.',
              'sentences': [sentence]}
    schema = author_schema_v11(quote, 1)
    schema.model_validate(answer)
    properties = schema.model_json_schema()['properties']
    assert properties['assertion']['pattern'] == '^[^0-9]*$'
    assert properties['sentences']['items']['pattern'] == '^[^0-9]*$'
    with pytest.raises(ValidationError):
        schema.model_validate({**answer, 'assertion': 'The registry reports 47 clinic pilots.'})
    with pytest.raises(ValidationError, match='omit numeric and date tokens'):
        schema.model_validate({**answer, 'assertion': 'The registry reports one clinic pilot.'})

    selection = select_schema({'sources': CARDS}, 'decision').model_validate({
        'recommendation': 'defer_pending_evidence', 'quote_ids': ['S1.q1']})
    projected = project_decision_v11(selection, [{**answer, 'sentences': [sentence] * 2}],
                                     quote_lookup(CARDS))
    assert projected.recommendation_claims[0].quote == QUOTE
    assert projected.recommendation_reason.count('[S1]') == 2


def test_v12_wider_sentence_still_requires_selected_quote_for_numbers():
    quote = ('The synthetic registry reports 47 clinic pilots and has not '
             'verified repeat orders or financial results.')
    sentence = ('The registry reports 47 clinic pilots, while repeat ordering '
                'and economic evidence still need independent verification. '
                'The source supports a measured activity statement and leaves '
                'important questions about durable demand and margins open '
                'for focused diligence before an investment decision.')
    assert 240 < len(sentence) <= 300
    answer = {'assertion': 'The registry reports 47 clinic pilots.',
              'sentences': [sentence]}
    assert author_schema_v12(quote, 1).model_validate(answer).sentences == [sentence]
    with pytest.raises(ValidationError):
        author_schema_v9(quote, 1).model_validate(answer)
    with pytest.raises(ValidationError, match='selected exact quote'):
        author_schema_v12(quote, 1).model_validate({
            **answer, 'assertion': 'The registry reports 48 clinic pilots.'})
