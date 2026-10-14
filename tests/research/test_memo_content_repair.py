"""Synthetic review -> model-authored repair -> exact re-review of memo rationales."""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_content_repair as repair
from agents.research import memo_content_review as review
from agents.research.investment_memo import Memo, Source
from tests.research.test_memo_causal_review import sample

PIN = {'name': 'qwen3:14b', 'digest': 'a' * 64}
CONTRACT = {'version': review.CONTRACT, 'model_name': 'qwen3.5:9b', 'model_digest': 'b' * 64}
BAD = 'Negative cash flow shows the company relies on outside funding.'


def flawed_memo():
    memo, sources = sample()
    memo['unknowns'][1]['why_it_matters'] = BAD + ' The source gives no cash position.'
    return memo, sources


class Reviewer:
    name = 'qwen3.5:9b'
    thinking = False
    max_tokens = 450
    context_tokens = 8192
    temperature = 0

    def __init__(self):
        self.calls, self.last_response_text, self.last_route = 0, '', {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == review.TASK and instruction == review.INSTRUCTION
        self.calls += 1
        payload = json.loads(evidence)
        flawed = any('relies on outside funding' in text
                     for text in payload['sentences'].values())
        sentence = next(key for key, text in payload['sentences'].items()
                        if ('relies on outside funding' in text) == flawed)
        answer = {'verdict': 'unsupported' if flawed else 'supported_or_conditional',
                  'focus_sentence_id': sentence, 'source_id': payload['selected_source_ids'][0],
                  'reason': 'The sentence infers funding reliance the passage does not state.'}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **review.OPTIONS}
        return schema.model_validate(answer)


class Author:
    name = PIN['name']
    thinking = False
    max_tokens = 1000
    context_tokens = 8192
    temperature = 0

    def __init__(self, text=None):
        self.calls, self.last_response_text, self.last_route = 0, '', {}
        self.text = text or ('The listing does not state how the company funds operations, '
                             'so funding reliance remains an open diligence question.')

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == repair.TASK and instruction == repair.INSTRUCTION
        self.calls += 1
        payload = json.loads(evidence)
        assert payload['field_path'] == 'unknowns[1].why_it_matters'
        assert payload['finding']['verdict'] == 'unsupported'
        answer = {'replacement_sentences': [{'choice_id': 'c01', 'text': self.text}]}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **repair.OPTIONS}
        return schema.model_validate(answer)


def spent():
    budget = PreparationBudget(60, max_calls=1, max_requests=1)
    budget.calls = budget.max_calls
    return budget


def run_review(memo, sources, attempts, model):
    return review.review_memo_content(
        memo, sources, attempts, lambda: None, model,
        PreparationBudget(60, max_calls=10, max_requests=10), contract=CONTRACT)


def blocked_result(memo, sources):
    attempts, model = [], Reviewer()
    result = review.evaluate_attempts(memo, sources, [], CONTRACT)
    while result[1] is not None:
        run_review(memo, sources, attempts, model)
        result = review.evaluate_attempts(memo, sources, attempts, CONTRACT)
    return result[0], attempts


def test_unrepaired_flaw_blocks_and_names_exact_field():
    memo, sources = flawed_memo()
    result, _ = blocked_result(memo, sources)
    assert result['state'] == 'blocked'
    assert repair.blocked_fields(result) == ['unknowns[1].why_it_matters']


def test_model_authored_repair_then_exact_rereview_accepts_and_replays():
    memo, sources = flawed_memo()
    first, _ = blocked_result(memo, sources)
    attempts, author = [], Author()
    outcome, revised = repair.revise_memo_content(
        memo, sources, review_result=first, repair_attempts=attempts,
        save_repairs=lambda: None, author=author, author_pin=PIN,
        repair_budget=PreparationBudget(60, max_calls=4, max_requests=4))
    assert outcome['state'] == 'revised_pending_rereview'
    assert outcome['independent_review'] == 'pending' and author.calls == 1
    assert 'relies on outside funding' not in revised.unknowns[1].why_it_matters
    assert revised.unknowns[0] == Memo.model_validate(memo).unknowns[0]
    assert revised.recommendation_reason == memo['recommendation_reason']
    # Re-review is a fresh exact request over the revised memo.
    second, _ = blocked_result(revised, sources)
    assert second['state'] == 'accepted' and second['memo_digest'] != first['memo_digest']
    # Exact raw replay needs no model and yields the identical memo.
    replay_outcome, replay = repair.revise_memo_content(
        memo, sources, review_result=first, repair_attempts=attempts,
        save_repairs=lambda: None, author=None, author_pin=PIN,
        repair_budget=spent())
    assert replay == revised and replay_outcome == outcome


def test_unusable_first_answer_gets_one_correction_then_is_terminal():
    memo, sources = flawed_memo()
    first, _ = blocked_result(memo, sources)
    bad = Author('Revenue grew 47 percent so funding reliance is clear to everyone here.')
    rows = []
    kwargs = dict(memo=memo, sources=sources, review_result=first, repair_attempts=rows,
                  save_repairs=lambda: None, author_pin=PIN)
    outcome, _ = repair.revise_memo_content(
        kwargs.pop('memo'), kwargs.pop('sources'), author=bad,
        repair_budget=PreparationBudget(60, max_calls=4, max_requests=4), **kwargs)
    assert outcome['state'] == 'needs_resume' and bad.calls == 1
def test_repair_requires_a_blocking_finding_bound_to_this_memo_and_response():
    memo, sources = flawed_memo()
    first, _ = blocked_result(memo, sources)
    packet = {'contract': repair.CONTRACT, 'field_path': 'unknowns[1].why_it_matters',
              'base_memo_digest': digest(Memo.model_validate(memo).model_dump(mode='json')),
              'model_name': PIN['name'], 'model_digest': PIN['digest'],
              'review_response_id': 'response_1', 'review_response_hash': '0' * 64}
    with pytest.raises(ValueError, match='blocking review response'):
        repair.frozen_request(memo, sources, packet, first)
    clean, _ = blocked_result(*sample())
    with pytest.raises(ValueError, match='no blocking finding'):
        repair.revise_memo_content(
            sample()[0], sample()[1], review_result=clean, repair_attempts=[],
            save_repairs=lambda: None, author=None, author_pin=PIN,
            repair_budget=PreparationBudget(60, max_calls=1, max_requests=1))


def test_no_budget_leaves_repair_pending_and_tampered_raw_is_refused():
    memo, sources = flawed_memo()
    first, _ = blocked_result(memo, sources)
    outcome, _ = repair.revise_memo_content(
        memo, sources, review_result=first, repair_attempts=[], save_repairs=lambda: None,
        author=Author(), author_pin=PIN,
        repair_budget=spent())
    assert outcome['state'] == 'needs_resume'
    attempts = []
    repair.revise_memo_content(
        memo, sources, review_result=first, repair_attempts=attempts,
        save_repairs=lambda: None, author=Author(), author_pin=PIN,
        repair_budget=PreparationBudget(60, max_calls=4, max_requests=4))
    attempts[0]['response_hash'] = '0' * 64
    with pytest.raises(ValueError, match='frozen contract'):
        repair.revise_memo_content(
            memo, sources, review_result=first, repair_attempts=attempts,
            save_repairs=lambda: None, author=None, author_pin=PIN,
            repair_budget=spent())


def test_recommendation_repair_attaches_citation_and_model_chooses_decision():
    memo, sources = sample()
    memo['recommendation'] = 'advance_to_diligence'
    memo['recommendation_reason'] = (
        'The registry lists a reported financing round and the company relies on outside '
        'funding because its cash flow is negative, so diligence should advance now [S1].')
    first, _ = blocked_result(memo, sources)
    assert repair.blocked_fields(first) == ['recommendation_reason']

    class ReasonAuthor(Author):
        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            self.calls += 1
            payload = json.loads(evidence)
            assert payload['field_path'] == 'recommendation_reason'
            assert payload['choices']['c01']['source_id'] == 'S1'
            answer = {'recommendation': 'defer_pending_evidence',
                      'replacement_sentences': [
                          {'choice_id': 'c01', 'text': 'The registry entry leaves the financing '
                           'status and current cash availability unknown.'},
                          {'choice_id': 'c01', 'text': 'Diligence should first obtain dated '
                           'transaction and account records before any advance decision is made.'}]}
            self.last_response_text = json.dumps(answer)
            self.last_route = {'model': self.name, **repair.OPTIONS}
            return schema.model_validate(answer)

    outcome, revised = repair.revise_memo_content(
        memo, sources, review_result=first, repair_attempts=[], save_repairs=lambda: None,
        author=ReasonAuthor(), author_pin=PIN,
        repair_budget=PreparationBudget(60, max_calls=4, max_requests=4))
    assert revised.recommendation == 'defer_pending_evidence'
    assert revised.recommendation_reason.count('[S1]') == 2
    assert blocked_result(revised, sources)[0]['state'] == 'accepted'


def test_accepted_memo_renders_with_replayed_content_revision_and_rejects_tampering():
    from agents.research.investment_memo import renderable_sections
    from agents.research.memo_content_review import frozen_calls
    from tests.research.test_memo_section_projection import SOURCES, accepted_v2
    result, attempts, _ = accepted_v2()
    memo = result['memo']
    target = memo['unknowns'][0]['why_it_matters']

    class Flagging(Reviewer):
        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            payload = json.loads(evidence)
            flawed = any(text == target for text in payload['sentences'].values())
            sentence = next(key for key, text in payload['sentences'].items()
                            if (text == target) == flawed)
            answer = {'verdict': 'unsupported' if flawed else 'supported_or_conditional',
                      'focus_sentence_id': sentence,
                      'source_id': payload['selected_source_ids'][0],
                      'reason': 'This sentence goes beyond the retained passage.'}
            self.calls += 1
            self.last_response_text = json.dumps(answer)
            self.last_route = {'model': self.name, **review.OPTIONS}
            return schema.model_validate(answer)

    def walk(subject, rows):
        while True:
            state, call = review.evaluate_attempts(subject, SOURCES, rows, CONTRACT)
            if call is None:
                return state
            run_review(subject, SOURCES, rows, Flagging())

    first_rows = []
    first = walk(memo, first_rows)
    assert repair.blocked_fields(first) == ['unknowns[0].why_it_matters']

    class UnknownAuthor(Author):
        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            self.calls += 1
            answer = {'replacement_sentences': [{'choice_id': 'c01', 'text':
                      'The reviewed record describes only one pilot, so repeatability is open.'}]}
            self.last_response_text = json.dumps(answer)
            self.last_route = {'model': self.name, **repair.OPTIONS}
            return schema.model_validate(answer)

    repair_rows = []
    outcome, revised = repair.revise_memo_content(
        memo, SOURCES, review_result=first, repair_attempts=repair_rows,
        save_repairs=lambda: None, author=UnknownAuthor(), author_pin=PIN,
        repair_budget=PreparationBudget(60, max_calls=4, max_requests=4))
    assert outcome['state'] == 'revised_pending_rereview'
    rereview_rows = []
    assert walk(revised, rereview_rows)['state'] == 'accepted'
    revision = {'contract': repair.REVISION_CONTRACT, 'review_contract': CONTRACT,
                'author_pin': PIN, 'base_memo_digest': digest(Memo.model_validate(memo)
                                                              .model_dump(mode='json')),
                'review_attempts': first_rows, 'repair_attempts': repair_rows,
                'rereview_attempts': rereview_rows}
    plain = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    shown = renderable_sections(result, SOURCES, attempts, projection='reader_v2',
                                content_revision=revision)
    assert shown != plain
    assert any('repeatability is open' in body for _, body, _ in shown)
    assert not any(target in body for _, body, _ in shown)
    revision['rereview_attempts'] = rereview_rows[:-1]
    with pytest.raises(ValueError, match='re-review|incomplete'):
        renderable_sections(result, SOURCES, attempts, projection='reader_v2',
                            content_revision=revision)


def test_private_worker_advances_one_model_call_per_pass_and_resumes_to_replay(tmp_path):
    from scripts import private_memo_content_worker as worker
    from scripts.evaluate_private_memo_content import load_revision
    memo, sources = flawed_memo()
    body = {'memo': memo, 'sources': sources,
            'review_contract': CONTRACT, 'author_pin': PIN}
    (tmp_path / 'content_request.json').write_text(json.dumps({**body, 'digest': digest(body)}))
    (tmp_path / 'content_budget.json').write_text(json.dumps({'seconds': 60}))

    states = []
    for _ in range(12):
        result = worker.advance(tmp_path, Reviewer(), Author())
        states.append(result['state'])
        if result['state'] != 'needs_resume':
            break
    assert states[-1] == 'accepted' and result['revised'] is True
    assert states.count('needs_resume') == len(states) - 1 and len(states) > 2
    calls = sum(len(json.loads((tmp_path / name).read_text()))
                for name in ('content_review_attempts.json', 'content_repair_attempts.json',
                             'content_rereview_attempts.json'))
    assert calls == 3 + 1 + 3                        # review, one repair, re-review
    again = worker.advance(tmp_path, None, None)     # replay: no model call needed
    assert again['state'] == 'accepted'
    revised, record = repair.replay_content_revision(memo, sources, load_revision(tmp_path))
    assert record['revised'] is True and record['final_memo_digest'] == result['final_memo_digest']
