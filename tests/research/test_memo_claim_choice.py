"""A failed numeric claim is repaired by a bounded, source-local model choice."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research.memo_claim_choice import run_claim_choices
from agents.research.staged_memo import MemoPartA, claim_patch_schema, replay_claim_patch
from tests.research.test_investment_memo import SOURCE, draft


class SelectingModel:
    name = 'offline-test-model'
    last_response_text = ''
    last_call = {'host': 'test-double'}

    def __init__(self):
        self.calls = 0
        self.inputs = []

    def generate(self, instruction, evidence, schema):
        self.calls += 1
        payload = json.loads(evidence)
        self.inputs.append(payload)
        self.last_response_text = json.dumps({'option_id': 'o0'})
        return schema.model_validate_json(self.last_response_text)


def invalid_part():
    whole = draft()
    part = MemoPartA.model_validate({key: whole[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'investment_thesis', 'business_and_market', 'unknowns')})
    value = part.model_dump()
    value['recommendation_claims'][0]['assertion'] += ' It reports $5M.'
    value['investment_thesis']['claims'][0]['assertion'] += ' It reports $7M.'
    return MemoPartA.model_validate(value)


def test_choices_are_one_claim_per_call_and_replay_exact_raw():
    part = invalid_part()
    _, targets = claim_patch_schema(part, [SOURCE])
    assert len(targets) == 2
    attempts, model = [], SelectingModel()
    snapshot = digest([SOURCE.model_dump()])
    kwargs = dict(part_label='A', base_response_id='base-response',
                  company='Example Labs', source_set_digest=snapshot,
                  as_of_date='2026-10-04', attempts=attempts, save=lambda: None)
    with preparation_budget(PreparationBudget(105, max_calls=1)) as budget:
        assert run_claim_choices(part, [SOURCE], targets, model=model,
                                 budget=budget, **kwargs) is None
    assert len(attempts) == model.calls == 1
    assert len(model.inputs[0]['options']) > 0
    assert set(model.inputs[0]['target']) == {'field', 'index', 'source_id', 'assertion', 'quote'}
    with preparation_budget(PreparationBudget(105, max_calls=1)) as budget:
        changed, bundle = run_claim_choices(part, [SOURCE], targets, model=model,
                                            budget=budget, **kwargs)
    assert len(attempts) == model.calls == 2
    assert changed.recommendation_claims[0].assertion != part.recommendation_claims[0].assertion
    assert changed.investment_thesis.claims[0].assertion != part.investment_thesis.claims[0].assertion
    raw = json.dumps(attempts)
    replay = replay_claim_patch(part, attempts, task='investment_memo_part_a_claim_patch',
        base_response_id='base-response', company='Example Labs',
        source_set_digest=snapshot, as_of_date='2026-10-04', sources=[SOURCE])
    assert replay == (changed, bundle)
    assert json.dumps(attempts) == raw
    attempts[0]['raw_response'] = '{}'
    with pytest.raises(ValueError, match='changed or failed'):
        replay_claim_patch(part, attempts, task='investment_memo_part_a_claim_patch',
            base_response_id='base-response', company='Example Labs',
            source_set_digest=snapshot, as_of_date='2026-10-04', sources=[SOURCE])
