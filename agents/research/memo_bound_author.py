"""Versioned source-local memo authoring over model-selected exact quote IDs.

The local model selects quotes and writes every assertion and prose sentence.
Software binds its selections to exact packet spans, adds citations and rejects
numbers/dates absent from each selected quote. These schemas are for fresh v8
memo contracts; saved earlier drafts keep their recorded schemas and responses.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, create_model, model_validator

from agents.research.investment_memo import (Claim, Section, Strict, _assertion_numbers,
                                             claim_text_issue)

_CITE = re.compile(r'\[S[1-9][0-9]*\]')


def quote_lookup(cards: list[dict]) -> dict[str, tuple[str, str]]:
    """Bind every offered quote ID to its source and one exact packet span."""
    lookup = {}
    for card in cards:
        source_id = card['source_id']
        for evidence in card['evidence']:
            quote_id, quote = evidence['quote_id'], evidence['quote']
            if (quote_id in lookup or not quote_id.startswith(source_id + '.q') or
                    not isinstance(quote, str) or not 15 <= len(quote) <= 700):
                raise ValueError('Bound quote catalog is ambiguous or out of range')
            lookup[quote_id] = (source_id, quote)
    if not lookup:
        raise ValueError('Bound quote catalog is empty')
    return lookup


def select_schema(payload: dict, kind: Literal['decision', 'section']):
    """Typed selection of one or two exact quote IDs from this section's cards."""
    ids = tuple(quote_lookup(payload['sources']))
    quote_id = Literal.__getitem__(ids)

    def distinct(self):
        if len(set(self.quote_ids)) != len(self.quote_ids):
            raise ValueError('Selected quote IDs must be distinct')
        return self

    fields = {'quote_ids': (list[quote_id], Field(min_length=1, max_length=2))}
    if kind == 'decision':
        fields['recommendation'] = (
            Literal['advance_to_diligence', 'defer_pending_evidence', 'decline'], Field(...))
    elif kind == 'section':
        fields['heading'] = (str, Field(min_length=5, max_length=100))
    else:
        raise ValueError('Unknown bound memo selection kind')
    return create_model('BoundQuoteSelection_v8_' + kind, __base__=Strict,
                        __validators__={'distinct_quote_ids': model_validator(mode='after')(
                            distinct)}, **fields)


def author_schema(quote: str, sentence_count: int):
    """One source-local authored assertion and exact-count sentence list.

    Numeric/citation mistakes are Pydantic validation errors, so a caller can
    preserve the raw answer and offer its single saved schema-feedback retry.
    The exact quote is frozen in the recorded input, not echoed in the answer.
    """
    if not isinstance(quote, str) or not 15 <= len(quote) <= 700:
        raise ValueError('Source-local authoring requires one bounded exact quote')
    if sentence_count not in {1, 2, 3}:
        raise ValueError('Source-local sentence count must be one to three')

    def bound(self):
        statements = [self.assertion, *self.sentences]
        for statement in statements:
            if (claim_text_issue(statement) or _CITE.search(statement) or
                    _assertion_numbers(statement) - _assertion_numbers(quote)):
                raise ValueError('Authored statement exceeds its selected exact quote')
        return self

    sentence = Annotated[str, Field(min_length=60, max_length=150)]
    return create_model(
        f'SourceLocalAuthor_v8_{sentence_count}', __base__=Strict,
        __validators__={'bound_to_exact_quote': model_validator(mode='after')(bound)},
        assertion=(str, Field(min_length=20, max_length=450)),
        sentences=(list[sentence], Field(min_length=sentence_count,
                                         max_length=sentence_count)))


def author_schema_v9(quote: str, sentence_count: int):
    """Wider versioned source-local sentence envelope; saved v8 stays exact."""
    if not isinstance(quote, str) or not 15 <= len(quote) <= 700:
        raise ValueError('Source-local authoring requires one bounded exact quote')
    if sentence_count not in {1, 2, 3}:
        raise ValueError('Source-local sentence count must be one to three')

    def bound(self):
        for statement in [self.assertion, *self.sentences]:
            if (claim_text_issue(statement) or _CITE.search(statement) or
                    _assertion_numbers(statement) - _assertion_numbers(quote)):
                raise ValueError('Authored statement exceeds its selected exact quote')
        return self

    sentence = Annotated[str, Field(min_length=60, max_length=240)]
    return create_model(
        f'SourceLocalAuthor_v9_{sentence_count}', __base__=Strict,
        __validators__={'bound_to_exact_quote': model_validator(mode='after')(bound)},
        assertion=(str, Field(min_length=20, max_length=450)),
        sentences=(list[sentence], Field(min_length=sentence_count,
                                         max_length=sentence_count)))


def author_schema_v10(quote: str, sentence_count: int):
    """Keep figures in exact-quote-bound assertions, not analytic sentences.

    The pattern is exported in JSON Schema so constrained local generation can
    avoid digit tokens before the saved-response validator runs. The source-local
    assertion may retain quote-bound figures; prose omits spelled values too.
    """
    if not isinstance(quote, str) or not 15 <= len(quote) <= 700:
        raise ValueError('Source-local authoring requires one bounded exact quote')
    if sentence_count not in {1, 2, 3}:
        raise ValueError('Source-local sentence count must be one to three')

    def bound(self):
        if (claim_text_issue(self.assertion) or _CITE.search(self.assertion) or
                _assertion_numbers(self.assertion) - _assertion_numbers(quote)):
            raise ValueError('Authored assertion exceeds its selected exact quote')
        for sentence in self.sentences:
            if claim_text_issue(sentence) or _CITE.search(sentence) or _assertion_numbers(sentence):
                raise ValueError('Authored reason must omit numeric and date tokens')
        return self

    sentence = Annotated[str, Field(min_length=60, max_length=240,
                                    pattern=r'^[^0-9]*$')]
    return create_model(
        f'SourceLocalAuthor_v10_{sentence_count}', __base__=Strict,
        __validators__={'bound_to_exact_quote': model_validator(mode='after')(bound)},
        assertion=(str, Field(min_length=20, max_length=450)),
        sentences=(list[sentence], Field(min_length=sentence_count,
                                         max_length=sentence_count)))


def author_schema_v11(quote: str, sentence_count: int):
    """Model authors numeric-free assertions and analysis over an exact quote.

    The exact selected quote and citation remain attached by projection; figures
    remain available there without inviting the small model to transcribe or
    paraphrase quantities in either authored field.
    """
    if not isinstance(quote, str) or not 15 <= len(quote) <= 700:
        raise ValueError('Source-local authoring requires one bounded exact quote')
    if sentence_count not in {1, 2, 3}:
        raise ValueError('Source-local sentence count must be one to three')

    def bound(self):
        for statement in [self.assertion, *self.sentences]:
            if claim_text_issue(statement) or _CITE.search(statement) or _assertion_numbers(statement):
                raise ValueError('Authored statement must omit numeric and date tokens')
        return self

    no_digits = r'^[^0-9]*$'
    sentence = Annotated[str, Field(min_length=60, max_length=240,
                                    pattern=no_digits)]
    return create_model(
        f'SourceLocalAuthor_v11_{sentence_count}', __base__=Strict,
        __validators__={'bound_to_exact_quote': model_validator(mode='after')(bound)},
        assertion=(str, Field(min_length=20, max_length=450, pattern=no_digits)),
        sentences=(list[sentence], Field(min_length=sentence_count,
                                         max_length=sentence_count)))


def author_schema_v12(quote: str, sentence_count: int):
    """Wider source-local author contract for the pinned stronger local role."""
    if not isinstance(quote, str) or not 15 <= len(quote) <= 700:
        raise ValueError('Source-local authoring requires one bounded exact quote')
    if sentence_count not in {1, 2, 3}:
        raise ValueError('Source-local sentence count must be one to three')

    def bound(self):
        for statement in [self.assertion, *self.sentences]:
            if (claim_text_issue(statement) or _CITE.search(statement) or
                    _assertion_numbers(statement) - _assertion_numbers(quote)):
                raise ValueError('Authored statement exceeds its selected exact quote')
        return self

    sentence = Annotated[str, Field(min_length=60, max_length=300)]
    return create_model(
        f'SourceLocalAuthor_v12_{sentence_count}', __base__=Strict,
        __validators__={'bound_to_exact_quote': model_validator(mode='after')(bound)},
        assertion=(str, Field(min_length=20, max_length=450)),
        sentences=(list[sentence], Field(min_length=sentence_count,
                                         max_length=sentence_count)))


def _checked_author(answer, quote: str, sentence_count: int, *, version='v8'):
    schema = {'v8': author_schema, 'v9': author_schema_v9,
              'v10': author_schema_v10, 'v11': author_schema_v11,
              'v12': author_schema_v12}[version]
    return schema(quote, sentence_count).model_validate(answer)


def author_sentence_count(kind: Literal['decision', 'section'], selected_count: int) -> int:
    """Per-quote response size needed for the assembled memo field bounds."""
    if selected_count not in {1, 2}:
        raise ValueError('Source-local authoring selects one or two quotes')
    if kind == 'decision':
        return 2 if selected_count == 1 else 1
    if kind == 'section':
        return 3 if selected_count == 1 else 2
    raise ValueError('Unknown bound memo selection kind')


def _assemble(selection, author_answers: list[dict], lookup: dict,
              *, kind: Literal['decision', 'section'], version='v8'):
    ids = selection.quote_ids
    if len(ids) != len(author_answers) or len(set(ids)) != len(ids):
        raise ValueError('Source-local author responses do not match selected quotes')
    claims, sentences = [], []
    for quote_id, answer in zip(ids, author_answers):
        source_id, quote = lookup[quote_id]
        count = author_sentence_count(kind, len(ids))
        authored = _checked_author(answer, quote, count, version=version)
        claims.append(Claim(source_id=source_id, quote=quote,
                            assertion=authored.assertion.strip()))
        for sentence in authored.sentences:
            value = sentence.strip()
            citation = f' [{source_id}]'
            sentences.append(value[:-1] + citation + value[-1]
                             if value.endswith(('.', '!', '?')) else value + citation + '.')
    return claims, ' '.join(sentences)


def project_decision(selection, author_answers: list[dict], lookup: dict):
    """Build the existing decision component from exact model-authored parts."""
    from agents.research.part_a_components import RecommendationDecision

    claims, reason = _assemble(selection, author_answers, lookup, kind='decision')
    return RecommendationDecision(recommendation=selection.recommendation,
                                  recommendation_reason=reason,
                                  recommendation_claims=claims)


def project_section(selection, author_answers: list[dict], lookup: dict) -> Section:
    """Build thesis, market or Part B section with source-local authored prose."""
    claims, analysis = _assemble(selection, author_answers, lookup, kind='section')
    return Section(heading=selection.heading, analysis=analysis, claims=claims)


def project_decision_v9(selection, author_answers: list[dict], lookup: dict):
    """Versioned decision with a wider, still bounded model-authored reason."""
    from agents.research.part_a_components import RecommendationDecisionV9

    claims, reason = _assemble(selection, author_answers, lookup,
                               kind='decision', version='v9')
    return RecommendationDecisionV9(recommendation=selection.recommendation,
                                    recommendation_reason=reason,
                                    recommendation_claims=claims)


def project_section_v9(selection, author_answers: list[dict], lookup: dict) -> Section:
    claims, analysis = _assemble(selection, author_answers, lookup,
                                 kind='section', version='v9')
    return Section(heading=selection.heading, analysis=analysis, claims=claims)


def project_decision_v10(selection, author_answers: list[dict], lookup: dict):
    """Project source-bound assertions and digit-free model-authored reasons."""
    from agents.research.part_a_components import RecommendationDecisionV9

    claims, reason = _assemble(selection, author_answers, lookup,
                               kind='decision', version='v10')
    return RecommendationDecisionV9(recommendation=selection.recommendation,
                                    recommendation_reason=reason,
                                    recommendation_claims=claims)


def project_section_v10(selection, author_answers: list[dict], lookup: dict) -> Section:
    claims, analysis = _assemble(selection, author_answers, lookup,
                                 kind='section', version='v10')
    return Section(heading=selection.heading, analysis=analysis, claims=claims)


def project_decision_v11(selection, author_answers: list[dict], lookup: dict):
    """Keep exact quoted figures; all substantive prose remains model-authored."""
    from agents.research.part_a_components import RecommendationDecisionV9

    claims, reason = _assemble(selection, author_answers, lookup,
                               kind='decision', version='v11')
    return RecommendationDecisionV9(recommendation=selection.recommendation,
                                    recommendation_reason=reason,
                                    recommendation_claims=claims)


def project_section_v11(selection, author_answers: list[dict], lookup: dict) -> Section:
    claims, analysis = _assemble(selection, author_answers, lookup,
                                 kind='section', version='v11')
    return Section(heading=selection.heading, analysis=analysis, claims=claims)


def project_decision_v12(selection, author_answers: list[dict], lookup: dict):
    """Project stronger-role prose and exact, model-selected source quotes."""
    from agents.research.part_a_components import RecommendationDecisionV12

    claims, reason = _assemble(selection, author_answers, lookup,
                               kind='decision', version='v12')
    return RecommendationDecisionV12(recommendation=selection.recommendation,
                                     recommendation_reason=reason,
                                     recommendation_claims=claims)


def project_section_v12(selection, author_answers: list[dict], lookup: dict) -> Section:
    claims, analysis = _assemble(selection, author_answers, lookup,
                                 kind='section', version='v12')
    return Section(heading=selection.heading, analysis=analysis, claims=claims)
