"""Finite local-only material drafting over an exact accepted memo projection."""
from __future__ import annotations

import json
from pathlib import Path

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest, recorded_call
from agents.preparation.preparation_budget import PreparationBudget, PreparationBudgetExceeded, preparation_budget
from agents.research.material_slides import replay_material_rows, render_sections


TASKS = ('intro_deck', 'pitch_deck')


def draft_materials(root: Path, model=None):
    request = json.loads((root / 'material_request.json').read_text())
    if request.get('digest') != digest({key: value for key, value in request.items()
                                        if key != 'digest'}):
        raise ValueError('Material request digest changed')
    sections = request['sections']
    if not isinstance(sections, list) or not 1 <= len(sections) <= 30:
        raise ValueError('Accepted memo section count invalid')
    attempts_file = root / 'material_attempts.json'
    attempts = json.loads(attempts_file.read_text()) if attempts_file.exists() else []
    if model is None:
        profile = json.loads((root / 'model.json').read_text())
        model = LocalModel(profile['profiles']['draft'], thinking=False,
                           max_tokens=2600, context_tokens=16384, temperature=0)
    seconds = json.loads((root / 'material_budget.json').read_text())['seconds']
    budget = PreparationBudget(seconds, max_calls=1, max_requests=1)

    def save():
        temporary = attempts_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(attempts, ensure_ascii=False))
        temporary.replace(attempts_file)

    outputs = {}
    for kind in TASKS:
        payload = {'kind': kind, 'input_revision': request['input_revision'],
                   'source_hash': request['source_hash'], 'memo_digest': request['memo_digest'],
                   'sections': sections}
        version = request.get('replay_contracts', {}).get(kind, 'current')
        state = replay_material_rows(kind, payload, attempts, sections,
                                     contract_version=version)
        if state['state'] != 'accepted':
            if state['state'] == 'blocked':
                return {'state': 'blocked', 'reason': f'{kind}_validation_retry_exhausted'}
            if budget.calls >= budget.max_calls:
                return {'state': 'needs_resume', 'reason': 'next_bounded_material_call'}
            try:
                with preparation_budget(budget):
                    recorded_call(model, state['task'], state['instruction'],
                        state['payload'], state['schema'], attempts, save)
            except PreparationBudgetExceeded:
                return {'state': 'needs_resume', 'reason': 'material_pass_budget_exhausted'}
            except Exception:
                # recorded_call persists the raw failure. Replay determines the
                # next bounded action; never substitute a software-authored slide.
                if not attempts or attempts[-1].get('task') != state['task']:
                    raise
            state = replay_material_rows(kind, payload, attempts, sections,
                                         contract_version=version)
            if state['state'] != 'accepted':
                return {'state': 'blocked' if state['state'] == 'blocked' else 'needs_resume',
                        'reason': f'{kind}_model_validation_failed'}
        outputs[kind] = {'response_id': state['response_ids'][-1],
                         'response_ids': state['response_ids'],
                         'sections': render_sections(state['spec'], sections)}
    return {'state': 'accepted', 'source_hash': request['source_hash'],
            'memo_digest': request['memo_digest'], 'decks': outputs,
            'attempt_count': len(attempts)}


def main():
    root = Path.cwd()
    result = draft_materials(root)
    (root / 'material_result.json').write_text(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
