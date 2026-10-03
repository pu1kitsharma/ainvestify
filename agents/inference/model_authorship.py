"""Persist model responses and verify exact provenance before publishing prose."""
import hashlib
import json
import time
from copy import deepcopy

from pydantic import ValidationError

from agents.inference.local_models import generate_task
from agents.inference.model_output import decode_model_object
from schemas import utcnow


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def recorded_call(model, task, instruction, payload, schema, attempts, save, attempt=0):
    from agents.inference.subscription_model import TransientSubscriptionError
    try:
        return _recorded_call(model, task, instruction, payload, schema, attempts, save, attempt)
    except TransientSubscriptionError:
        # One retry of the identical public request. Both attempts are recorded
        # and charged to the existing call/time/request budget. No retry for
        # authentication, quota, validation failures or other provider errors.
        return _recorded_call(model, task, instruction, payload, schema, attempts, save, attempt + 1)


def _recorded_call(model, task, instruction, payload, schema, attempts, save, attempt=0):
    row = {'id': 'response_' + str(len(attempts) + 1), 'task': task, 'at': utcnow(),
           'instruction': instruction, 'input': deepcopy(payload), 'schema': schema.model_json_schema()}
    started = time.monotonic()
    model.last_response_text = ''
    try:
        result = generate_task(model, task, instruction, json.dumps(payload, ensure_ascii=False), schema, attempt=attempt)
        row['answer'] = result.model_dump(mode='json')
        raw = decode_model_object(model.last_response_text)
        # No default text, computed prose, sentence deletion or normalization.
        if raw != row['answer']:
            raise ValueError('The accepted object differs from the raw model response.')
        return result, row['id']
    except Exception as exc:
        row['error'] = str(exc)
        if isinstance(exc, ValidationError):
            # Keep parseable but invalid output for model-authored correction.
            # It is never a successful response and cannot be read normally.
            try:
                candidate = decode_model_object(model.last_response_text)
            except (ValueError, TypeError):
                candidate = None
            if isinstance(candidate, dict):
                row['answer'] = candidate
                row['failure_kind'] = 'schema_validation'
        raise
    finally:
        row.update(raw_response=model.last_response_text, elapsed_seconds=round(time.monotonic()-started, 3),
                   routing=dict(getattr(model, 'last_route', None) or getattr(model, 'last_call', {})),
                   model=(getattr(model, 'last_route', {}) or {}).get('model', model.name))
        row['response_hash'] = digest(row['raw_response'])
        attempts.append(row)
        save()


def response_answer(attempts, response_id, *, allow_schema_candidate=False):
    row = next((r for r in attempts if r['id'] == response_id), None)
    if not row or ('error' in row and not (
            allow_schema_candidate and row.get('failure_kind') == 'schema_validation')):
        raise ValueError('No successful model response supports this content.')
    if digest(row['raw_response']) != row['response_hash']:
        raise ValueError('Recorded model response was modified.')
    answer = decode_model_object(row['raw_response'])
    if answer != row['answer']:
        raise ValueError('Saved model answer differs from its original response.')
    return answer
