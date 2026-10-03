"""The model selects exact evidence; code only checks and binds its words."""
import pytest
from pydantic import ValidationError

from agents.research.fieldwise_memo import (RecommendationPatch,
    RecommendationReview, bind_recommendation, decision_context)
from agents.research.investment_memo import Claim, Source


def test_model_selected_plan_quote_is_exact_and_its_words_are_preserved():
    passage = ('Example Labs plans to operate 50 stations across the region. '
               'The page also lists a 6 month target for installation.')
    source = Source(id='S1', url='https://example.org/plan', title='Plan',
                    passage=passage, version='version123', attribution='Example')
    claim = Claim(source_id='S1', quote='Example Labs plans to operate 50 stations across the region.',
                  assertion='Example Labs plans to operate 50 stations.')
    context = decision_context([claim], [source])
    selected = next(i for i, option in enumerate(context[0]['quote_options'])
                    if option.startswith('Example Labs plans'))
    sentence = 'The company plans to operate 50 stations, which calls for evidence of commissioned capacity before treating this target as current reach.'
    patch = RecommendationPatch.model_validate({'recommendation': 'defer_pending_evidence',
        'recommendation_reason': [
            {'claim_index': 0, 'quote_option': selected, 'text': sentence},
            {'claim_index': 0, 'quote_option': selected, 'text': sentence}]})
    decision, reason, bound = bind_recommendation(patch, [claim], context,
                                                  as_of_date='2026-10-02')
    assert decision == 'defer_pending_evidence'
    assert bound[0].quote in passage
    assert bound[0].assertion == sentence
    assert reason == f'{sentence} [S1] {sentence} [S1]'


def test_model_cannot_round_number_or_invent_source_index_in_prose():
    source = Source(id='S1', url='https://example.org/round', title='Round',
                    passage='The company reports a funding event amount of 3330000 USD.',
                    version='version123', attribution='Example')
    claim = Claim(source_id='S1', quote=source.passage,
                  assertion='The company reports a 3330000 USD funding event.')
    context = decision_context([claim], [source])
    text = 'The rounded 3.3 million USD funding amount needs independent confirmation before it can support the capitalization case.'
    patch = RecommendationPatch.model_validate({'recommendation': 'defer_pending_evidence',
        'recommendation_reason': [{'claim_index': 0, 'quote_option': 0, 'text': text}] * 2})
    with pytest.raises(ValueError, match='numbers absent'):
        bind_recommendation(patch, [claim], context, as_of_date='2026-10-02')


def test_excerpt_silence_cannot_become_a_company_absence_claim():
    source = Source(id='S1', url='https://example.org/plan', title='Plan',
                    passage='Example Labs plans to operate 50 stations across the region.',
                    version='version123', attribution='Example')
    claim = Claim(source_id='S1', quote=source.passage,
                  assertion='Example Labs plans to operate 50 stations.')
    context = decision_context([claim], [source])
    text = ('The 50 station plan is an intention, with no deployment timeline '
            'or current operational metrics provided for this network.')
    patch = RecommendationPatch.model_validate({'recommendation': 'defer_pending_evidence',
        'recommendation_reason': [{'claim_index': 0, 'quote_option': 0, 'text': text}] * 2})
    with pytest.raises(ValueError, match='inferred absence'):
        bind_recommendation(patch, [claim], context, as_of_date='2026-10-02')


def test_review_cannot_pass_while_reporting_issues():
    with pytest.raises(ValidationError, match='zero issues'):
        RecommendationReview.model_validate({'verdict': 'pass',
            'issues': [{'line_index': 0, 'defect': 'The source quote does not support the stated date.'}],
            'decision_reasoning': 'The cited date is unsupported, so the recommendation requires revision.'})
