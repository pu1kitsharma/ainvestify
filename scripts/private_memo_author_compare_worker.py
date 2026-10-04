"""One isolated, digest-pinned local model comparison on a frozen memo author task.

The request is copied from a prior private diagnostic. This worker never reads
the original documents, changes an earlier response, or creates a deal record.
Its only company text output is the ignored private raw attempt file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

from pydantic import ValidationError

from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import recorded_call
from agents.preparation.preparation_budget import (
    PreparationBudget, PreparationBudgetExceeded, preparation_budget,
)
from agents.research.memo_bound_author import author_schema_v9


def _atomic(path: Path, payload) -> None:
    if path.exists():
        raise ValueError('Private comparison already has a recorded result')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False))
    temporary.replace(path)


def main() -> None:
    root = Path.cwd()
    request_bytes = (root / 'task.json').read_bytes()
    request = json.loads(request_bytes)
    profile = json.loads((root / 'model.json').read_text())
    if (hashlib.sha256(request_bytes).hexdigest() != profile['task_file_sha256'] or
            profile.get('model') != 'qwen3:14b' or
            not isinstance(profile.get('model_digest'), str) or
            len(profile['model_digest']) != 64 or
            profile.get('seconds') != 105 or
            (root / 'attempts.json').exists()):
        raise ValueError('Frozen private comparison contract is invalid')
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
        installed = {row['name']: row.get('digest') for row in
                     json.load(response)['models']}
    if installed.get(profile['model']) != profile['model_digest']:
        raise ValueError('Installed local model differs from frozen comparison')
    payload = request['input']
    schema = author_schema_v9(payload['quote'], payload['sentence_count'])
    if schema.model_json_schema() != request['schema']:
        raise ValueError('Frozen source-local author schema changed')
    if not request['task'].endswith('_source_2_v4'):
        raise ValueError('Comparison task is not the frozen source-local author')

    attempts: list[dict] = []

    def save() -> None:
        if len(attempts) != 1:
            raise ValueError('Private comparison exceeded one recorded call')
        _atomic(root / 'attempts.json', attempts)

    model = LocalModel(profile['model'], thinking=False, max_tokens=1400,
                       context_tokens=16384, temperature=0)
    state = 'blocked'
    reason = 'model_or_schema_error'
    try:
        with preparation_budget(PreparationBudget(105, max_calls=1,
                                                   max_requests=1)):
            recorded_call(model, request['task'], request['instruction'],
                          payload, schema, attempts, save)
        state, reason = 'bound', None
    except PreparationBudgetExceeded:
        reason = 'time_limit'
    except ValidationError:
        reason = 'schema_validation'
    except (RuntimeError, ValueError):
        reason = 'model_or_schema_error'
    _atomic(root / 'result.json', {'state': state, 'reason': reason,
                                  'attempt_count': len(attempts),
                                  'release_status': 'diagnostic_only_no_release'})


if __name__ == '__main__':
    main()
