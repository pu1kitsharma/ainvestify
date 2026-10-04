"""One local reviewer call per private material review pass, at most two.

A request frozen as semantic_v11 is reviewed sentence by sentence, one call per deck
(`review_relations`); every earlier contract keeps its recorded path unchanged."""
from __future__ import annotations

import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest, recorded_call, response_answer
from agents.preparation.preparation_budget import (PreparationBudget,
    PreparationBudgetExceeded, preparation_budget)
from agents.research.material_review import (review_instruction, review_schema,
    compact_review_payload, project_review, unbound_block_withdrawn,
    TERMINAL_VALIDATION_BLOCK)
from agents.research.material_relation_review import (DECKS, MAX_SECONDS, RELATION_CONTRACT,
    RELATION_INSTRUCTION, RELATION_OPTIONS, RELATION_TASK, evaluate_attempts, frozen_calls)


def _outcome(request, attempts, row, review):
    """The result for a recorded review that passed validation.

    A `pass` that follows an earlier blocking answer which could not be bound
    is a withdrawal, not a correction. Under the guarded contract it is a
    block, with both response ids kept; the raw answers stay in the attempts.
    """
    withdrawn = unbound_block_withdrawn(request, attempts[:attempts.index(row) + 1])
    if review.verdict == 'pass' and withdrawn:
        return {'state': 'blocked', 'reason': 'material_review_block_withdrawn_unbound',
                'response_id': row['id'], 'withdrawn_response_id': withdrawn,
                'review': review.model_dump(mode='json'), 'request_digest': request['digest']}
    return {'state': 'accepted' if review.verdict == 'pass' else 'blocked',
            'reason': None if review.verdict == 'pass' else 'model_review_blocked',
            'response_id': row['id'], 'review': review.model_dump(mode='json'),
            'request_digest': request['digest']}


def review_materials(root: Path, model=None):
    request = json.loads((root / 'material_review_request.json').read_text())
    full = {key: value for key, value in request.items() if key != 'digest'}
    if request.get('digest') != digest(full):
        raise ValueError('Material review request digest changed')
    if request.get('review_contract') == RELATION_CONTRACT:
        # Opt-in: only a request already frozen as semantic_v11 takes this path.
        return review_relations(root, request, model)
    instruction = review_instruction(request)
    schema = review_schema(request)
    payload = compact_review_payload(request)
    attempts_file = root / 'material_review_attempts.json'
    attempts = json.loads(attempts_file.read_text()) if attempts_file.exists() else []
    if len(attempts) > 2:
        raise ValueError('Material review exceeded two recorded attempts')
    model_pin = payload['review_model']
    if model is None:
        model = LocalModel(model_pin['name'], thinking=False, max_tokens=1200,
                           context_tokens=16384, temperature=0)
    seconds = json.loads((root / 'material_review_budget.json').read_text())['seconds']
    budget = PreparationBudget(seconds, max_calls=1, max_requests=1)

    def save():
        temporary = attempts_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(attempts, ensure_ascii=False))
        temporary.replace(attempts_file)

    issue = None
    for row in attempts:
        expected = payload if row is attempts[0] else {
            **payload, 'retry_base_digest': digest(payload),
            'previous_response_id': attempts[0]['id'],
            'previous_answer': attempts[0].get('answer'),
            'validation_issue': issue}
        if (row.get('task') != 'material_semantic_review' or row.get('input') != expected or
                row.get('instruction') != instruction or
                row.get('schema') != schema.model_json_schema() or
                row.get('model') != model_pin['name'] or
                any(row.get('routing', {}).get(key) != value
                    for key, value in model_pin['options'].items())):
            raise ValueError('Recorded material review differs from frozen contract')
        if digest(row.get('raw_response')) != row.get('response_hash'):
            raise ValueError('Recorded material review response was modified')
        try:
            candidate = project_review(schema.model_validate(
                response_answer(attempts, row['id'])), request)
        except (ValueError, TypeError) as exc:
            issue = str(exc)[:400]
        else:
            if row is not attempts[-1]:
                raise ValueError('Material review continues after valid response')
            return _outcome(request, attempts, row, candidate)
    if len(attempts) >= 2:
        return {'state': 'blocked', 'reason': 'bounded_material_review_validation_exhausted'}
    call_payload = payload if not attempts else {
        **payload, 'retry_base_digest': digest(payload),
        'previous_response_id': attempts[0]['id'],
        'previous_answer': attempts[0].get('answer'),
        'validation_issue': issue}
    try:
        with preparation_budget(budget):
            recorded_call(model, 'material_semantic_review', instruction,
                          call_payload, schema, attempts, save)
    except PreparationBudgetExceeded:
        return {'state': 'needs_resume', 'reason': 'material_review_pass_budget_exhausted'}
    except Exception:
        if not attempts:
            raise
    return review_materials_replay(root, request, attempts)


def review_materials_replay(root, request, attempts):
    """Re-enter without inference to evaluate the newly saved raw response."""
    if not attempts:
        return {'state': 'needs_resume', 'reason': 'material_review_no_response'}
    row = attempts[-1]
    if row.get('error'):
        if len(attempts) >= 2 and request.get('review_contract') in TERMINAL_VALIDATION_BLOCK:
            return {'state': 'blocked', 'reason': 'bounded_material_review_validation_exhausted'}
        return {'state': 'blocked' if len(attempts) >= 2 else 'needs_resume',
                'reason': 'material_review_model_error'}
    try:
        review = project_review(review_schema(request).model_validate(
            response_answer(attempts, row['id'])), request)
    except (ValueError, TypeError):
        if len(attempts) >= 2 and request.get('review_contract') in TERMINAL_VALIDATION_BLOCK:
            return {'state': 'blocked', 'reason': 'bounded_material_review_validation_exhausted'}
        return {'state': 'blocked' if len(attempts) >= 2 else 'needs_resume',
                'reason': 'material_review_model_validation_failed'}
    return _outcome(request, attempts, row, review)


def review_relations(root: Path, request, model=None):
    """semantic_v11: one recorded call per deck, one call per pass, never a retry.

    A restart replays the saved raw attempts and calls only a deck that has no
    recorded attempt. Any recorded attempt that cannot be bound blocks.
    """
    calls = frozen_calls(request)                       # raises before any inference
    attempts_file = root / 'material_review_attempts.json'
    attempts = json.loads(attempts_file.read_text()) if attempts_file.exists() else []
    result, deck = evaluate_attempts(request, attempts)
    if result:
        return result
    if model is None:
        model = LocalModel(request['review_model']['name'], **RELATION_OPTIONS)
    seconds = json.loads((root / 'material_review_budget.json').read_text())['seconds']
    budget = PreparationBudget(min(seconds, MAX_SECONDS), max_calls=1, max_requests=1)

    def save():
        temporary = attempts_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(attempts, ensure_ascii=False))
        temporary.replace(attempts_file)

    recorded = len(attempts)
    payload, schema = calls[deck]
    try:
        with preparation_budget(budget):
            recorded_call(model, RELATION_TASK, RELATION_INSTRUCTION, payload, schema,
                          attempts, save)
    except Exception:
        if len(attempts) == recorded:                   # nothing was recorded for this deck
            raise
    result, deck = evaluate_attempts(request, attempts)
    return result or {'state': 'needs_resume',
                      'reason': 'material_relation_review_next_deck',
                      'next_deck': deck, 'decks_recorded': list(DECKS[:len(attempts)])}


def main():
    root = Path.cwd()
    result = review_materials(root)
    (root / 'material_review_result.json').write_text(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
