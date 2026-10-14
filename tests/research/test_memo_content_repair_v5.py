"""Standalone local repair contract rejects editorial feedback in investor prose."""
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_content_repair as repair
from tests.research.test_memo_causal_review import sample
from tests.research.test_memo_content_repair_v4 import PIN, blocked, frozen


def test_v5_retains_scoped_limits_but_rejects_editorial_critique():
    memo, sources, payload, schema = frozen(repair.CONTRACT_V5)
    assert payload['max_sentences'] == 1 and payload['max_total_characters'] == 220
    assert 'Investor-facing' in payload['audience']
    answer = {'replacement_sentences': [{'choice_id': 'c01', 'text':
              'The assertion about cash availability exceeds the evidence in this passage.'}]}
    with pytest.raises(ValueError, match='comments on a claim'):
        repair._project(memo, sources, payload, schema.model_validate(answer).model_dump())
    answer['replacement_sentences'][0]['text'] = (
        'Current bank records would help assess operating cash available for diligence.')
    revised = repair._project(memo, sources, payload, schema.model_validate(answer).model_dump())
    assert revised.unknowns[1].why_it_matters == answer['replacement_sentences'][0]['text']


def test_v4_editorial_answer_replay_is_not_changed_by_new_v5_validator():
    memo, sources, payload, schema = frozen(repair.CONTRACT_V4)
    text = 'The assertion about cash availability exceeds the evidence in this passage.'
    answer = {'replacement_sentences': [{'choice_id': 'c01', 'text': text}]}
    revised = repair._project(memo, sources, payload, schema.model_validate(answer).model_dump())
    assert revised.unknowns[1].why_it_matters == text
    assert 'audience' not in payload
    assert 'AUDIENCE: investors' not in repair.INSTRUCTION_V4_BLIND


class Author:
    name = PIN['name']
    thinking = False
    max_tokens = 1000
    context_tokens = 8192
    temperature = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == repair.TASK_V5 and instruction == repair.INSTRUCTION_V5
        assert json.loads(evidence)['contract'] == repair.CONTRACT_V5
        answer = {'replacement_sentences': [{'choice_id': 'c01', 'text':
                  'Current bank records would help assess operating cash available for diligence.'}]}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **repair.OPTIONS}
        return schema.model_validate(answer)


def test_opted_v5_raw_author_answer_replays_without_inference():
    memo, sources = sample()
    kwargs = dict(review_result=blocked(memo), repair_attempts=[],
                  save_repairs=lambda: None, author_pin={**PIN, 'repair_contract': repair.CONTRACT_V5})
    first, revised = repair.revise_memo_content(memo, sources, author=Author(),
        repair_budget=PreparationBudget(60, max_calls=2, max_requests=2), **kwargs)
    assert first['state'] == 'revised_pending_rereview'
    assert kwargs['repair_attempts'][0]['task'] == repair.TASK_V5
    replay, same = repair.revise_memo_content(memo, sources, author=None,
        repair_budget=SimpleNamespace(calls=0, max_calls=0), **kwargs)
    assert replay == first and same == revised
