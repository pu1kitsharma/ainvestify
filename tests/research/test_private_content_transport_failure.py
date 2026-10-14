"""Review transport failures block without masquerading as semantic repair tasks."""
import json

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget
from scripts import private_memo_content_worker as worker
from tests.research.test_memo_causal_review import sample


def prepare(tmp_path):
    memo, sources = sample()
    request = {'memo': memo, 'sources': sources,
        'review_contract': {'version': 'memo-content-review-v5',
                            'model_name': 'local-review', 'model_digest': 'a' * 64},
        'author_pin': {'name': 'local-author', 'digest': 'b' * 64,
                       'repair_contract': 'memo-content-repair-v6'}}
    (tmp_path / 'content_request.json').write_text(json.dumps({**request, 'digest': digest(request)}))
    (tmp_path / 'content_budget.json').write_text(json.dumps({'seconds': 105}))
    return memo, request


def failure():
    return {'state': 'blocked', 'contract': 'memo-content-review-v5',
            'findings': [{'field_path': 'recommendation_reason',
                          'verdict': 'invalid_answer', 'review_failure_kind': 'transport',
                          'response_id': 'timed_out_response'}]}


def test_timed_out_review_never_invokes_company_author_repair(tmp_path, monkeypatch):
    _, request = prepare(tmp_path)
    author_calls = []
    monkeypatch.setattr(worker, 'effective_review_contract', lambda *args: request['review_contract'])
    monkeypatch.setattr(worker.review, 'review_memo_content', lambda *args, **kwargs: failure())
    monkeypatch.setattr(worker.repair, 'revise_memo_content', lambda *args, **kwargs: author_calls.append(True))
    result = worker.advance(tmp_path, reviewer=object(), author=object(), characterizer=object(),
        budget=PreparationBudget(105, max_calls=6, max_requests=6))
    assert result['state'] == 'blocked'
    assert result['reason'] == 'content_review_inference_failed'
    assert result['failed_review_response_ids'] == ['timed_out_response']
    assert author_calls == []


def test_failed_rereview_does_not_author_another_round(tmp_path, monkeypatch):
    memo, request = prepare(tmp_path)
    results = iter([{'state': 'blocked', 'findings': [
        {'field_path': 'recommendation_reason', 'verdict': 'unsupported',
         'response_id': 'semantic_response'}]}, failure()])
    author_calls = []
    monkeypatch.setattr(worker, 'effective_review_contract', lambda *args: request['review_contract'])
    monkeypatch.setattr(worker.review, 'review_memo_content', lambda *args, **kwargs: next(results))

    def repair_once(*args, **kwargs):
        author_calls.append(True)
        return {'state': 'revised_pending_rereview'}, memo

    monkeypatch.setattr(worker.repair, 'revise_memo_content', repair_once)
    result = worker.advance(tmp_path, reviewer=object(), author=object(), characterizer=object(),
        budget=PreparationBudget(105, max_calls=6, max_requests=6))
    assert result['reason'] == 'content_review_inference_failed'
    assert author_calls == [True]
