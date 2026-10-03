"""Synthetic-only battle-test fixtures with counterfactual pairs.

A fixture labels expected decision properties (a verdict, a flagged field, an
allowed status, an allowed label). It never contains expected prose, and no
expected value is sent to a model.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field

from agents.research.investment_memo import (Memo, Source, Strict, challenge_field_prose,
                                             validate_memo, validate_sources)

FIXTURE_ROOT = Path(__file__).resolve().parent / 'fixtures'
SUITES = ('challenge', 'reconciliation', 'claim_coverage')
PAIRS = ('reported_vs_verified_amount', 'reported_amount_called_absent',
         'reported_amount_called_absent_in_claim',
         'reversed_stage_chronology', 'stale_listing_vs_newer_announcement',
         'distinct_legal_entities', 'missing_finances', 'contradictory_source')
Variant = Literal['defect', 'control']
Pair = Literal[PAIRS]
_PROSE_FIELDS = ('recommendation_reason', 'investment_thesis', 'business_and_market',
                 'differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')


class ExpectedFlag(Strict):
    """Where the planted defect is: a location label, never expected model prose."""
    field: Literal[_PROSE_FIELDS]
    # `claim`: the defect is in a claim row's assertion, which the reader is
    # shown beside its excerpt, not in the field's prose.
    location: Literal['prose', 'claim'] = 'prose'
    memo_span: str = Field(min_length=8, max_length=240,
        description="Exact span of the stimulus prose or claim assertion that states the defect.")
    source_spans: dict[str, str] = Field(min_length=1, max_length=3,
        description="Source id -> exact passage span that shows the defect.")
    kinds: list[Literal['contradiction', 'omission', 'unsupported']] = Field(min_length=1)


class ChallengeExpected(Strict):
    verdict: Literal['revise', 'no_material_defect']
    flag: Optional[ExpectedFlag] = None


class ChallengeCase(Strict):
    id: str = Field(pattern=r'^[a-z0-9_]{3,60}$')
    pair: Pair
    variant: Variant
    company: str = Field(min_length=1, max_length=200)
    as_of_date: str
    sources: list[Source]
    memo: Memo
    expected: ChallengeExpected


class Candidate(Strict):
    id: str = Field(pattern=r'^C[1-9]$')
    records: list[Source] = Field(min_length=1, max_length=4)


class ReconciliationExpected(Strict):
    allowed_selection: list[str] = Field(min_length=1)
    allowed_status: dict[str, list[Literal['investigate', 'defer', 'exclude']]]


class ReconciliationCase(Strict):
    id: str = Field(pattern=r'^[a-z0-9_]{3,60}$')
    pair: Pair
    variant: Variant
    as_of_date: str
    mandate: dict
    candidates: list[Candidate] = Field(min_length=2, max_length=4)
    expected: ReconciliationExpected

    @property
    def sources(self):
        return [record for candidate in self.candidates for record in candidate.records]


class Statement(Strict):
    id: str = Field(pattern=r'^T[1-9][0-9]?$')
    text: str = Field(min_length=20, max_length=300)
    pair: Pair
    variant: Variant
    allowed_labels: list[Literal['supported', 'unsupported', 'contradicted']] = Field(min_length=1)


class CoverageCase(Strict):
    id: str = Field(pattern=r'^[a-z0-9_]{3,60}$')
    company: str = Field(min_length=1, max_length=200)
    as_of_date: str
    sources: list[Source]
    statements: list[Statement] = Field(min_length=2, max_length=10)


def _merge_sources(base: list[dict], changes: list[dict]) -> list[dict]:
    """A case replaces or adds whole sources by id; `"passage": null` removes one."""
    merged = {row['id']: row for row in base}
    for row in changes:
        if row.get('passage') is None:
            merged.pop(row['id'], None)
        else:
            merged[row['id']] = {**merged.get(row['id'], {}), **row}
    return sorted(merged.values(), key=lambda row: int(row['id'][1:]))


def _expand_quotes(memo: dict, sources: list[dict]) -> dict:
    """`"quote": "@S2"` stands for the whole passage of S2, kept byte-exact."""
    passages = {row['id']: row['passage'] for row in sources}
    memo = json.loads(json.dumps(memo))
    groups = [memo['recommendation_claims']] + [memo[field]['claims'] for field in _PROSE_FIELDS[1:]]
    for claims in groups:
        for claim in claims:
            if claim['quote'].startswith('@'):
                claim['quote'] = passages[claim['quote'][1:]]
    return memo


def _check_sources(sources: list[Source], as_of_date: str) -> None:
    date.fromisoformat(as_of_date)
    validate_sources(sources)
    for source in sources:
        if not source.url.startswith('https://example.invalid/'):
            raise ValueError('Synthetic fixture sources require example.invalid URLs')


def _check_pairs(units) -> None:
    variants = {}
    for unit in units:
        variants.setdefault(unit.pair, set()).add(unit.variant)
    incomplete = sorted(pair for pair, seen in variants.items() if seen != {'defect', 'control'})
    if incomplete:
        raise ValueError(f'Counterfactual pairs need a defect and a control variant: {incomplete}')


def load_fixture(path: Path):
    """Return (suite, cases) for one shipped synthetic fixture file."""
    path = Path(path).resolve()
    if not path.is_relative_to(FIXTURE_ROOT) or not path.name.endswith('.synthetic.json'):
        raise ValueError('Battle fixtures must be .synthetic.json files in the harness fixture folder')
    data = json.loads(path.read_text())
    if set(data) - {'base'} != {'classification', 'suite', 'cases'} or data['classification'] != 'synthetic':
        raise ValueError('Fixture needs classification "synthetic", suite and cases')
    suite, base = data['suite'], data.get('base', {})
    if suite not in SUITES:
        raise ValueError('Unknown battle suite')
    cases = []
    for row in data['cases']:
        if suite == 'challenge':
            sources = _merge_sources(base['sources'], row.get('sources', []))
            memo = _expand_quotes({**base['memo'], **row.get('memo_patch', {})}, sources)
            case = ChallengeCase(id=row['id'], pair=row['pair'], variant=row['variant'],
                company=base['company'], as_of_date=base['as_of_date'],
                sources=sources, memo=memo, expected=row['expected'])
            # The challenge role runs after source binding, so every stimulus
            # memo must already pass the deterministic validator.
            validate_memo(case.memo, case.sources)
            if (case.expected.verdict == 'revise') != (case.expected.flag is not None) or (
                    (case.variant == 'defect') != (case.expected.verdict == 'revise')):
                raise ValueError(f'{case.id}: variant, verdict and flag labels disagree')
            if flag := case.expected.flag:
                passages = {source.id: source.passage for source in case.sources}
                claims = (case.memo.recommendation_claims if flag.field == 'recommendation_reason'
                          else getattr(case.memo, flag.field).claims)
                located = (any(flag.memo_span in claim.assertion for claim in claims)
                           if flag.location == 'claim' else
                           flag.memo_span in challenge_field_prose(case.memo, flag.field)[0])
                if not located or any(
                        span not in passages.get(source_id, '')
                        for source_id, span in flag.source_spans.items()):
                    raise ValueError(f'{case.id}: expected spans must be exact memo and source text')
        elif suite == 'reconciliation':
            case = ReconciliationCase.model_validate({'as_of_date': base['as_of_date'], **row})
            ids = [candidate.id for candidate in case.candidates]
            if (len(set(ids)) != len(ids) or set(case.expected.allowed_status) != set(ids)
                    or not set(case.expected.allowed_selection) <= set(ids) | {'none'}):
                raise ValueError(f'{case.id}: expected labels must cover every candidate exactly')
        else:
            case = CoverageCase.model_validate({'company': base['company'],
                'as_of_date': base['as_of_date'], **row})
            if len({item.id for item in case.statements}) != len(case.statements):
                raise ValueError(f'{case.id}: statement ids must be distinct')
        _check_sources(case.sources, case.as_of_date)
        cases.append(case)
    if len({case.id for case in cases}) != len(cases) or not 1 <= len(cases) <= 24:
        raise ValueError('Fixture needs 1-24 distinct case ids')
    _check_pairs([item for case in cases for item in case.statements]
                 if suite == 'claim_coverage' else cases)
    return suite, cases
