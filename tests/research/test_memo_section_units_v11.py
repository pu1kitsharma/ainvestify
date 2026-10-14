"""Fresh concise author/full-context review preserve earlier exact contracts."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core, memo_section_review as review
from tests.research.test_memo_quote_premises_v10 import Author as Author10, Reviewer as Reviewer9, authored_fixture
from tests.research.test_memo_section_units_v9 import PIN, fixture, coverage_for
from tests.research.test_memo_section_review import REVIEW_PIN


class Author11(Author10):
    compact_prompt = True
    require_full_context = True

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == core.TASK_V11 and instruction == core.INSTRUCTION_V11
        result = super().generate_for_task(core.TASK_V10, core.INSTRUCTION_V10, evidence, schema, attempt=attempt)
        self.last_route.update(core.OPTIONS_V11, prompt_tokens=1500)
        return result


class Reviewer10(Reviewer9):
    max_tokens = 600
    compact_prompt = True
    require_full_context = True

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == review.TASK_V10 and instruction == review.INSTRUCTION_V10
        result = super().generate_for_task(review.TASK_V9, review.INSTRUCTION_V9, evidence, schema, attempt=attempt)
        self.last_route.update(review.OPTIONS_V10, prompt_tokens=1700)
        return result


def fresh_authored():
    memo, sources, coverage, _ = authored_fixture()
    rows = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        result = core.run_author(memo, sources, PIN, rows, lambda: None, Author11(), budget,
                                 contract=core.CONTRACT_V11, coverage=coverage)
    assert result['state'] == 'accepted' and len(rows) == 5
    return memo, sources, coverage, rows, result


def test_v11_target_one_point_and_chosen_quote_labels_keep_old_hard_bounds():
    memo, sources = fixture()
    coverage = coverage_for(sources)
    old = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V10, coverage=coverage)
    fresh = core.frozen_requests(memo, sources, PIN, contract=core.CONTRACT_V11, coverage=coverage)
    for required in ('Target 24–32 words', 'at most ONE quantitative fact', 'including measures in hypotheses', 'adjacent table relationships'):
        assert required in core.INSTRUCTION_V11
    assert core.INSTRUCTION_V10 != core.INSTRUCTION_V11
    for (field, old_payload, old_schema), (_, payload, schema) in zip(old, fresh):
        assert old_payload['sources'] == payload['sources']
        for key in core._COMPONENTS_V7.get(field, ('decision_analysis',)):
            older = old_schema.model_fields['units'].annotation.model_fields['S1'].annotation.model_fields[key]
            newer = schema.model_fields['units'].annotation.model_fields['S1'].annotation.model_fields[key]
            assert older.metadata == newer.metadata
            assert 'Target 24–32 words' in newer.description and 'Target 24–32 words' not in older.description
    field, payload, schema = fresh[0]
    response = Author11().generate_for_task(core.TASK_V11, core.INSTRUCTION_V11, json.dumps(payload), schema).model_dump(mode='json')
    response['units']['S1']['decision_analysis'] = (
        'If the reported partner service could reduce costs, customers could receive a distinct offering through partners. '
        'Adoption evidence would determine whether that distribution mechanism merits investment diligence.')
    with pytest.raises(ValueError, match='cost'):
        core._project_field(memo, field, payload, schema, response)
    with pytest.raises(ValueError, match='48 words'):
        core._validate_concise_unit_v9(' '.join(['word'] * 49), field, {})


def test_v11_full_context_receipt_required_on_author_exact_replay():
    memo, sources, coverage, rows, accepted = fresh_authored()
    assert core.run_author(memo, sources, PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=core.CONTRACT_V11, coverage=coverage) == accepted
    for value in (None, 4098, 8000):
        changed = copy.deepcopy(rows)
        changed[0]['routing']['prompt_tokens'] = value
        with pytest.raises(ValueError, match='context integrity'):
            core.run_author(memo, sources, PIN, changed, lambda: None, None,
                SimpleNamespace(calls=0, max_calls=0), contract=core.CONTRACT_V11, coverage=coverage)


def test_v11_requires_review10_and_five_reviews_keep_old_flags_and_context_receipts():
    memo, sources, coverage, _, authored = fresh_authored()
    with pytest.raises(ValueError, match='versioned author|mandatory v10'):
        review.frozen_requests(memo, sources, authored, PIN, REVIEW_PIN, contract=review.CONTRACT_V9, coverage=coverage)
    rows = []
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    for _ in core.FIELDS:
        result = review.run_review(memo, sources, authored, PIN, REVIEW_PIN, rows, lambda: None,
            Reviewer10(), budget, contract=review.CONTRACT_V10, coverage=coverage)
    assert result['state'] == 'accepted' and len(rows) == 5
    assert all(row['routing']['max_tokens'] == 600 and row['routing']['require_full_context'] for row in rows)
    assert review.run_review(memo, sources, authored, PIN, REVIEW_PIN, rows, lambda: None,
        None, SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V10, coverage=coverage) == result
    changed = copy.deepcopy(rows)
    changed[0]['routing']['prompt_tokens'] = 4098
    with pytest.raises(ValueError, match='context integrity'):
        review.run_review(memo, sources, authored, PIN, REVIEW_PIN, changed, lambda: None,
            None, SimpleNamespace(calls=0, max_calls=0), contract=review.CONTRACT_V10, coverage=coverage)
