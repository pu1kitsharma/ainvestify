"""One bounded local-model step of a private memo content review/repair/re-review.

Runs inside the private sandbox. State is recomputed from the three recorded
attempt files on every invocation, so a restart never repeats a saved call and
never extends the finite plan: one review of the accepted memo, at most one
model-authored repair per blocked rationale, and one exact re-review.
"""
from __future__ import annotations

import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import (PreparationBudget,
    PreparationBudgetExceeded, preparation_budget)
from agents.research import memo_content_repair as repair
from agents.research import memo_content_review as review
from agents.research.investment_memo import Memo, Source

def _name(kind, number):
    return f'content_{kind}_attempts' + ('' if number == 1 else f'_{number}') + '.json'


def _load(root, name):
    path = root / name
    return json.loads(path.read_text()) if path.exists() else []


def _saver(root, name, rows):
    def save():
        path = root / name
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(rows, ensure_ascii=False))
        temporary.replace(path)
    return save


def advance(root: Path, reviewer=None, author=None):
    request = json.loads((root / 'content_request.json').read_text())
    if request.get('digest') != digest({k: v for k, v in request.items() if k != 'digest'}):
        raise ValueError('Content revision request digest changed')
    memo = Memo.model_validate(request['memo'])
    sources = [Source.model_validate(row) for row in request['sources']]
    contract, pin = request['review_contract'], request['author_pin']
    seconds = json.loads((root / 'content_budget.json').read_text())['seconds']
    budget = PreparationBudget(seconds, max_calls=1, max_requests=1)
    if reviewer is None:
        reviewer = LocalModel(contract['model_name'], **review.OPTIONS)
    if author is None:
        author = LocalModel(pin['name'], **repair.OPTIONS)
    retry_author = (LocalModel(pin['name'], **repair.OPTIONS_RETRY)
                    if author.__class__ is LocalModel else author)
    rows = {}

    def get(name):
        rows.setdefault(name, _load(root, name))
        return rows[name]

    if len(get(_name('review', 1))) > 1 + len(memo.unknowns):
        raise ValueError('Content revision exceeded its finite call plan')

    def guarded(function):
        try:
            with preparation_budget(budget):
                return function()
        except PreparationBudgetExceeded:
            return None

    result = guarded(lambda: review.review_memo_content(
        memo, sources, get(_name('review', 1)), _saver(root, _name('review', 1), get(_name('review', 1))),
        reviewer, budget, contract=contract))
    if result is None or result['state'] == 'needs_resume':
        return {'state': 'needs_resume', 'reason': 'next_bounded_content_review'}
    current = memo
    for number in range(1, repair.MAX_ROUNDS + 1):
        if result['state'] == 'accepted':
            return {'state': 'accepted', 'revised': number > 1, 'repair_rounds': number - 1,
                    'final_memo_digest': result['memo_digest']}
        repair_name, review_name = _name('repair', number), _name('rereview', number)
        if len(get(repair_name)) > (1 + repair.MAX_RETRIES) * repair.MAX_REPAIRS:
            raise ValueError('Content revision exceeded its finite call plan')
        try:
            outcome, revised = guarded(lambda: repair.revise_memo_content(
                current, sources, review_result=result, repair_attempts=get(repair_name),
                save_repairs=_saver(root, repair_name, get(repair_name)), author=author,
                author_pin=pin, repair_budget=budget, retry_author=retry_author,
                round_number=number)
                ) or ({'state': 'needs_resume'}, None)
        except ValueError as exc:      # terminal: corrections exhausted
            return {'state': 'blocked', 'reason': 'content_repair_terminal',
                    'repair_round': number, 'detail': str(exc)[:300]}
        if outcome['state'] == 'blocked':
            return {'state': 'blocked', 'reason': outcome['reason']}
        if outcome['state'] != 'revised_pending_rereview':
            return {'state': 'needs_resume', 'reason': 'next_bounded_content_repair'}
        result = guarded(lambda: review.review_memo_content(
            revised, sources, get(review_name), _saver(root, review_name, get(review_name)),
            reviewer, budget, contract=contract))
        if result is None or result['state'] == 'needs_resume':
            return {'state': 'needs_resume', 'reason': 'next_bounded_content_rereview'}
        current = revised
    if result['state'] == 'accepted':
        return {'state': 'accepted', 'revised': True, 'repair_rounds': repair.MAX_ROUNDS,
                'final_memo_digest': result['memo_digest']}
    return {'state': 'blocked', 'reason': 'revised_content_not_supported',
            'findings': result['findings']}


def main():
    root = Path.cwd()
    (root / 'content_result.json').write_text(
        json.dumps(advance(root), ensure_ascii=False))


if __name__ == '__main__':
    main()
