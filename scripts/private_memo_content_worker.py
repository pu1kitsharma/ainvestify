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
        temporary.chmod(0o600)
        temporary.replace(path)
    return save


def _transport_failure(result):
    """A failed inference is not a semantic finding authorizing a prose edit."""
    failed = [finding for finding in result.get('findings', ())
              if finding.get('review_failure_kind') == 'transport']
    if failed:
        return {'state': 'blocked', 'reason': 'content_review_inference_failed',
                'failed_review_fields': [finding['field_path'] for finding in failed],
                'failed_review_response_ids': [finding['response_id'] for finding in failed]}
    return None


def effective_review_contract(root, request, model=None, budget=None):
    """Replay or prepare blind source proof before offering any memo wording.

    A missing model never triggers inference. The caller supplies the same pass
    budget as memo review/repair, so this stage cannot add hidden calls.
    """
    from types import SimpleNamespace
    from agents.research import memo_content_review_v2 as relation_review
    from agents.research import rationale_evidence
    contract = request['review_contract']
    if contract['version'] != relation_review.BLIND_CONTRACT:
        return contract
    if request.get('digest') != digest({key: value for key, value in request.items() if key != 'digest'}):
        raise ValueError('Blind content revision request digest changed')
    if set(contract) != {'version', 'model_name', 'model_digest'}:
        raise ValueError('Private blind request must freeze the unaugmented model role')
    base = {**contract, 'version': relation_review.SCOPE_CONTRACT}
    sources = [Source.model_validate(row) for row in request['sources']]
    calls = relation_review.frozen_calls(request['memo'], sources, base)
    selected_ids = {key for _, payload, _ in calls for key in payload['selected_source_ids']}
    selected = [source for source in sources if source.id in selected_ids]
    name = 'source_characterization_attempts.json'
    attempts = _load(root, name)
    result = rationale_evidence.characterize_sources(
        selected, {'name': contract['model_name'], 'digest': contract['model_digest']},
        attempts, _saver(root, name, attempts), model,
        budget if budget is not None else SimpleNamespace(calls=0, max_calls=0))
    if result['state'] != 'accepted':
        return None
    return {**contract, 'source_characterization': {'attempts': attempts, 'result': result}}


def advance(root: Path, reviewer=None, author=None, *, budget=None, characterizer=None):
    request = json.loads((root / 'content_request.json').read_text())
    if request.get('digest') != digest({k: v for k, v in request.items() if k != 'digest'}):
        raise ValueError('Content revision request digest changed')
    memo = Memo.model_validate(request['memo'])
    sources = [Source.model_validate(row) for row in request['sources']]
    contract, pin = request['review_contract'], request['author_pin']
    seconds = json.loads((root / 'content_budget.json').read_text())['seconds']
    budget = budget or PreparationBudget(seconds, max_calls=1, max_requests=1)
    if contract['version'] in {'memo-content-review-v2', 'memo-content-review-v3', 'memo-content-review-v4', 'memo-content-review-v5'}:
        from agents.research import memo_content_review_v2 as reviewer_contract
    else:
        reviewer_contract = review
    if reviewer is None:
        reviewer = LocalModel(contract['model_name'], **reviewer_contract.OPTIONS)
    if author is None:
        author = LocalModel(pin['name'], **repair.OPTIONS)
    retry_author = (LocalModel(pin['name'], **repair.OPTIONS_RETRY)
                    if author.__class__ is LocalModel else author)
    rows = {}

    def get(name):
        rows.setdefault(name, _load(root, name))
        return rows[name]

    if len(get(_name('review', 1))) > 2 * (1 + len(memo.unknowns)):
        raise ValueError('Content revision exceeded its finite call plan')

    def guarded(function):
        try:
            with preparation_budget(budget):
                return function()
        except PreparationBudgetExceeded:
            return None

    if contract['version'] == 'memo-content-review-v5':
        from agents.research import rationale_evidence
        source_model = characterizer or LocalModel(contract['model_name'], **rationale_evidence.OPTIONS)
        try:
            contract = guarded(lambda: effective_review_contract(root, request, source_model, budget))
        except ValueError as exc:
            return {'state': 'blocked', 'reason': 'source_characterization_terminal',
                    'detail': str(exc)[:300]}
        if contract is None:
            return {'state': 'needs_resume', 'reason': 'next_bounded_source_characterization'}

    result = guarded(lambda: review.review_memo_content(
        memo, sources, get(_name('review', 1)), _saver(root, _name('review', 1), get(_name('review', 1))),
        reviewer, budget, contract=contract))
    failure = _transport_failure(result) if result is not None else None
    if failure is not None:
        return failure
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
        failure = _transport_failure(result) if result is not None else None
        if failure is not None:
            return failure
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
    limits = json.loads((root / 'content_budget.json').read_text())
    max_calls = limits.get('max_calls', 1)
    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or not 1 <= max_calls <= 6:
        raise ValueError('Private content pass permits one to six calls')
    budget = PreparationBudget(min(limits['seconds'], 105), max_calls=max_calls, max_requests=max_calls)
    for _ in range(max_calls):
        before = budget.calls
        result = advance(root, budget=budget)
        if result['state'] != 'needs_resume' or budget.calls == before or budget.calls >= max_calls:
            break
    result_path = root / 'content_result.json'
    result_path.write_text(json.dumps(result, ensure_ascii=False))
    result_path.chmod(0o600)


if __name__ == '__main__':
    main()
