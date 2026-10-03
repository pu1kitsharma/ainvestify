"""Private, loopback-only workbook evidence analysis with durable raw attempt files.

Run inside one private job directory. It reads only that directory:

    request.json   {"workbook": "<file name in this directory>",
                    "workbook_sha256": "<hex>", "as_of_date": "YYYY-MM-DD"}
    model.json     {"profiles": {"financial": "<installed local model>"}}
    budget.json    optional {"seconds": <1-105>}

and writes `binding.json`, `attempts.json`, `passes.json` and `result.json`
there, each atomically. The result is partial cell-level evidence. It never
validates financial statements, and production financial validation stays
blocked whatever this worker returns.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

from agents.analysis.workbook_reconciliation import (CONTRACT, MAX_BYTES, SCOPE, TASK,
                                                     analyze_workbook)
from agents.inference.local_models import LocalModel
from agents.inference.model_authorship import digest
from agents.inference.model_routing import validate_local_model_name
from agents.preparation.preparation_budget import (PreparationBudget, PreparationBudgetExceeded,
                                                   preparation_budget)

MAX_PASSES = 3
CALLS_PER_PASS = 3
MODEL_OPTIONS = {'thinking': False, 'temperature': 0, 'max_tokens': 1500, 'context_tokens': 16384}
RESULT_STATUS = {'artifact_status': 'diagnostic_partial_evidence_no_release',
                 'independent_review': 'pending'}


class RequestError(ValueError):
    """The job directory does not hold a usable, unchanged request."""


def atomic_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + '.tmp')
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _load(path: Path, default=None):
    if not path.exists():
        if default is None:
            raise RequestError(f'{path.name}_missing')
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise RequestError(f'{path.name}_unreadable') from exc


def read_request(root: Path) -> dict:
    """The exact request: workbook bytes and hash, as-of date and frozen model profile."""
    request = _load(root / 'request.json')
    if not isinstance(request, dict) or set(request) != {'workbook', 'workbook_sha256', 'as_of_date'}:
        raise RequestError('request_needs_exactly_workbook_sha256_and_as_of_date')
    name = request['workbook']
    if (not isinstance(name, str) or Path(name).name != name or name.startswith('.')
            or not name.lower().endswith(('.xlsx', '.xlsm'))):
        raise RequestError('workbook_must_be_a_file_name_in_the_job_directory')
    workbook = root / name
    if workbook.is_symlink() or not workbook.is_file():
        raise RequestError('workbook_file_missing')
    if workbook.stat().st_size > MAX_BYTES:
        raise RequestError('workbook_exceeds_size_limit')
    content = workbook.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != request['workbook_sha256']:
        raise RequestError('workbook_hash_differs_from_request')
    try:
        date.fromisoformat(request['as_of_date'])
    except (TypeError, ValueError) as exc:
        raise RequestError('as_of_date_is_not_an_iso_date') from exc
    profile = _load(root / 'model.json')
    roles = profile.get('profiles') if isinstance(profile, dict) else None
    if not isinstance(roles, dict) or set(roles) != {'financial'}:
        raise RequestError('model_profile_needs_exactly_one_financial_role')
    model = roles['financial']
    try:
        validate_local_model_name(model)
    except ValueError as exc:
        raise RequestError('financial_model_is_not_a_local_model_name') from exc
    seconds = _load(root / 'budget.json', {'seconds': 105}).get('seconds')
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 1 <= seconds <= 105:
        raise RequestError('budget_seconds_must_be_between_1_and_105')
    binding = {'contract': CONTRACT, 'task': TASK, 'workbook_sha256': actual,
               'as_of_date': request['as_of_date'], 'model': model,
               'model_options': MODEL_OPTIONS, 'max_passes': MAX_PASSES,
               'calls_per_pass': CALLS_PER_PASS}
    binding['request_digest'] = digest(binding)
    return {'content': content, 'binding': binding, 'seconds': seconds}


def run(root: Path, model_factory=LocalModel) -> dict:
    """One bounded pass. Saved responses are replayed; a finished job makes no call."""
    root = Path(root).resolve()
    try:
        request = read_request(root)
    except RequestError as exc:
        result = {'state': 'blocked', 'reason': str(exc), **SCOPE, **RESULT_STATUS}
        atomic_json(root / 'result.json', result)
        return result
    binding = request['binding']
    stamp = {'request_digest': binding['request_digest'], 'model_profile': {
        'financial': binding['model'], 'options': MODEL_OPTIONS}, **RESULT_STATUS}

    def finish(result: dict) -> dict:
        result = {**result, **SCOPE, **stamp}
        atomic_json(root / 'result.json', result)
        return result

    # The first pass fixes the request. Later passes must present the same one.
    saved_binding = _load(root / 'binding.json', {})
    if saved_binding and saved_binding != binding:
        return finish({'state': 'blocked', 'reason': 'request_differs_from_bound_request',
                       'bound_request_digest': saved_binding.get('request_digest')})
    if not saved_binding:
        atomic_json(root / 'binding.json', binding)
    attempts = _load(root / 'attempts.json', [])
    if not isinstance(attempts, list) or any(
            row.get('task') != TASK or row.get('model') != binding['model']
            or row.get('input', {}).get('workbook_sha256') != binding['workbook_sha256']
            or row.get('input', {}).get('as_of_date') != binding['as_of_date']
            for row in attempts):
        return finish({'state': 'blocked', 'reason': 'saved_response_outside_bound_request'})
    passes = _load(root / 'passes.json', {'request_digest': binding['request_digest'], 'passes': []})
    if passes.get('request_digest') != binding['request_digest']:
        return finish({'state': 'blocked', 'reason': 'pass_record_outside_bound_request'})

    def save():
        atomic_json(root / 'attempts.json', attempts)

    def analyse(model, budget):
        with preparation_budget(budget):
            return analyze_workbook(request['content'], as_of_date=binding['as_of_date'],
                                    model=model, attempts=attempts, save=save, budget=budget)

    try:
        # Replay first, with no model: a finished or blocked job never calls inference.
        outcome = analyse(None, PreparationBudget(request['seconds'], max_calls=CALLS_PER_PASS,
                                                  max_requests=CALLS_PER_PASS + 2))
        if outcome['state'] == 'needs_resume':
            if len(passes['passes']) >= MAX_PASSES:
                return finish({**outcome, 'state': 'blocked', 'reason': 'pass_limit_reached',
                               'passes_used': len(passes['passes'])})
            budget = PreparationBudget(request['seconds'], max_calls=CALLS_PER_PASS,
                                       max_requests=CALLS_PER_PASS + 2)
            before = len(attempts)
            try:
                outcome = analyse(model_factory(binding['model'], **MODEL_OPTIONS), budget)
            except PreparationBudgetExceeded:
                outcome = {'state': 'needs_resume', 'phase': 'bounded_time_or_call_limit'}
            finally:
                save()
                passes['passes'].append({'pass': len(passes['passes']) + 1,
                                         'attempt_ids': [row['id'] for row in attempts[before:]],
                                         'budget': budget.snapshot()})
                atomic_json(root / 'passes.json', passes)
    except (ValueError, RuntimeError) as exc:
        # The raw failure stays in the private attempts file; only its kind is reported.
        save()
        return finish({'state': 'blocked', 'reason': type(exc).__name__,
                       'detail': str(exc)[:200]})
    if outcome['state'] == 'analysed':
        # Named for what it is: findings on partial cell-level evidence.
        outcome = {**outcome, 'state': 'partial_evidence', 'analysis_state': 'analysed'}
    return finish({**outcome, 'passes_used': len(passes['passes']),
                   'attempt_count': len(attempts)})


def main():
    if len(sys.argv) != 1:
        raise SystemExit('private_financial_worker takes no arguments; it runs in its job directory')
    run(Path.cwd())


if __name__ == '__main__':
    main()
