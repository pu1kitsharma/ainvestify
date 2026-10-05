"""One pinned local comparison of a frozen private memo field-review packet."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import recorded_call
from agents.preparation.preparation_budget import (
    PreparationBudget, PreparationBudgetExceeded, preparation_budget,
)
from agents.research.memo_final_review import CONTRACT_V4, TASK_V4, frozen_calls_v2


def _atomic(path: Path, value) -> None:
    if path.exists():
        raise ValueError('Private field comparison already recorded')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def main() -> None:
    root = Path.cwd()
    task_bytes = (root / 'task.json').read_bytes()
    request = json.loads(task_bytes)
    profile = json.loads((root / 'model.json').read_text())
    if (hashlib.sha256(task_bytes).hexdigest() != profile['task_file_sha256'] or
            profile.get('model') != 'qwen3.5:9b' or
            len(profile.get('model_digest', '')) != 64 or
            profile.get('seconds') != 105 or
            (root / 'attempts.json').exists() or request.get('task') != TASK_V4):
        raise ValueError('Frozen field comparison contract is invalid')
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
        installed = {row['name']: row.get('digest') for row in
                     json.load(response)['models']}
    if installed.get(profile['model']) != profile['model_digest']:
        raise ValueError('Installed local field comparison model changed')
    basis = request['basis']
    calls = frozen_calls_v2(basis['memo'], basis['sources'],
                            basis['ledger_binding_digest'], profile['model'],
                            profile['model_digest'], basis['company'],
                            basis['as_of_date'], version=CONTRACT_V4)
    field_index = request['field_index']
    if (not isinstance(field_index, int) or field_index < 0 or
            field_index >= len(calls)):
        raise ValueError('Frozen field index is invalid')
    _, payload, schema = calls[field_index]
    if payload != request['input'] or schema.model_json_schema() != request['schema']:
        raise ValueError('Frozen field packet differs from exact source bundle')
    attempts: list[dict] = []

    def save() -> None:
        if len(attempts) != 1:
            raise ValueError('Private field comparison exceeded one recorded call')
        _atomic(root / 'attempts.json', attempts)

    model = LocalModel(profile['model'], thinking=False, max_tokens=450,
                       context_tokens=8192, temperature=0)
    state, reason = 'blocked', 'model_or_schema_error'
    try:
        with preparation_budget(PreparationBudget(105, max_calls=1,
                                                   max_requests=1)):
            recorded_call(model, request['task'], request['instruction'],
                          payload, schema, attempts, save)
        state, reason = 'bound', None
    except PreparationBudgetExceeded:
        reason = 'time_limit'
    except Exception:
        reason = 'model_or_schema_error'
    _atomic(root / 'result.json', {'state': state, 'reason': reason,
                                  'attempt_count': len(attempts),
                                  'release_status': 'diagnostic_only_no_release'})


if __name__ == '__main__':
    main()
