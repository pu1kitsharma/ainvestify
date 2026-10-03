"""Single bounded local slide repair; never rewrites old material or review rows."""
from __future__ import annotations

import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest, recorded_call, response_answer
from agents.preparation.preparation_budget import (PreparationBudget,
    PreparationBudgetExceeded, preparation_budget)
from agents.research.material_repair import (REPAIR_INSTRUCTION,
    DISPUTE_REPAIR_INSTRUCTION, apply_material_repair)
from agents.research.material_slides import StructuredSlidePatch, StructuredDeckSpec


def repair_materials(root: Path, model=None):
    request = json.loads((root / 'material_repair_request.json').read_text())
    payload = {key: value for key, value in request.items() if key != 'digest'}
    if request.get('digest') != digest(payload):
        raise ValueError('Material repair request digest changed')
    attempts_file = root / 'material_repair_attempts.json'
    attempts = json.loads(attempts_file.read_text()) if attempts_file.exists() else []
    if len(attempts) > 1:
        raise ValueError('Material repair exceeded one recorded model response')
    pin = payload['repair_model']
    contract = payload.get('repair_contract', 'review_repair_v1')
    if contract not in {'review_repair_v1', 'review_dispute_v1'}:
        raise ValueError('Unknown material repair contract')
    instruction = (DISPUTE_REPAIR_INSTRUCTION if contract == 'review_dispute_v1'
                   else REPAIR_INSTRUCTION)
    if model is None:
        model = LocalModel(pin['name'], thinking=False, max_tokens=1500,
                           context_tokens=16384, temperature=0)

    def save():
        temporary = attempts_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(attempts, ensure_ascii=False))
        temporary.replace(attempts_file)

    if not attempts:
        seconds = json.loads((root / 'material_repair_budget.json').read_text())['seconds']
        budget = PreparationBudget(seconds, max_calls=1, max_requests=1)
        try:
            with preparation_budget(budget):
                recorded_call(model, 'material_review_slide_repair', instruction,
                              payload, StructuredSlidePatch, attempts, save)
        except PreparationBudgetExceeded:
            return {'state': 'blocked', 'reason': 'material_repair_pass_budget_exhausted'}
        except Exception:
            if not attempts:
                raise
    row = attempts[0]
    if (row.get('task') != 'material_review_slide_repair' or
            row.get('instruction') != instruction or
            row.get('schema') != StructuredSlidePatch.model_json_schema() or
            row.get('input') != payload or row.get('model') != pin['name'] or
            any(row.get('routing', {}).get(key) != value
                for key, value in pin['options'].items())):
        raise ValueError('Material repair response differs from frozen contract')
    if digest(row.get('raw_response')) != row.get('response_hash'):
        raise ValueError('Material repair raw response was modified')
    answer = None if row.get('error') else response_answer(attempts, row['id'])
    try:
        if answer is None:
            raise ValueError(row.get('error', 'No successful repair response'))
        patch = StructuredSlidePatch.model_validate(answer)
        original = StructuredDeckSpec.model_validate(payload['target_deck_spec'])
        disputed = (contract == 'review_dispute_v1' and
                    patch.slide == original.slides[payload['target_slide_index']])
        decks = apply_material_repair(payload, patch)
    except (ValueError, TypeError) as exc:
        return {'state': 'blocked', 'reason': 'material_repair_model_validation_failed',
                'detail': str(exc)[:300]}
    return {'state': 'disputed_without_change' if disputed else 'accepted',
            'request_digest': request['digest'],
            'response_id': row['id'], 'decks': decks}


def main():
    root = Path.cwd()
    result = repair_materials(root)
    (root / 'material_repair_result.json').write_text(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
