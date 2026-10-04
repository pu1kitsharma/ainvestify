"""One pinned local comparison of a saved private memo causal-review batch."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

from pydantic import ConfigDict, Field, create_model

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import recorded_call
from agents.preparation.preparation_budget import (
    PreparationBudget, PreparationBudgetExceeded, preparation_budget,
)
from agents.research.memo_causal_review import ConsequenceJudgment, TASK_V2


def _atomic(path: Path, payload) -> None:
    if path.exists():
        raise ValueError('Private causal comparison already recorded')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False))
    temporary.replace(path)


def main() -> None:
    root = Path.cwd()
    task_bytes = (root / 'task.json').read_bytes()
    request = json.loads(task_bytes)
    profile = json.loads((root / 'model.json').read_text())
    if (hashlib.sha256(task_bytes).hexdigest() != profile['task_file_sha256'] or
            profile.get('model') not in {'qwen3:14b', 'qwen3.5:9b'} or
            len(profile.get('model_digest', '')) != 64 or
            profile.get('seconds') != 105 or
            (root / 'attempts.json').exists() or request.get('task') != TASK_V2):
        raise ValueError('Frozen causal comparison contract is invalid')
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
        installed = {row['name']: row.get('digest') for row in
                     json.load(response)['models']}
    if installed.get(profile['model']) != profile['model_digest']:
        raise ValueError('Installed local causal comparison model changed')
    payload = request['input']
    schema = create_model('MemoCausal_v2_' + payload['batch_id'],
                          __config__=ConfigDict(extra='forbid'),
                          **{row['row_id']: (ConsequenceJudgment, Field(...))
                             for row in payload['rows']})
    if schema.model_json_schema() != request['schema']:
        raise ValueError('Frozen causal comparison schema changed')
    attempts: list[dict] = []

    def save() -> None:
        if len(attempts) != 1:
            raise ValueError('Private causal comparison exceeded one recorded call')
        _atomic(root / 'attempts.json', attempts)

    model = LocalModel(profile['model'], thinking=False, max_tokens=1400,
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
