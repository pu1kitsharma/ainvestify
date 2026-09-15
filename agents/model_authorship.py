"""Persist model responses and verify exact provenance before publishing prose."""
import hashlib
import json
import time

from agents.local_models import generate_task
from schemas import utcnow


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def recorded_call(model, task, instruction, payload, schema, attempts, save, attempt=0):
    row = {'id': 'response_' + str(len(attempts) + 1), 'task': task, 'at': utcnow(),
           'instruction': instruction, 'input': payload, 'schema': schema.model_json_schema()}
    started = time.monotonic()
    model.last_response_text = ''
    try:
        result = generate_task(model, task, instruction, json.dumps(payload, ensure_ascii=False), schema, attempt=attempt)
        row['answer'] = result.model_dump(mode='json')
        raw = json.loads(model.last_response_text)
        # No default text, computed prose, sentence deletion or normalization.
        if raw != row['answer']:
            raise ValueError('The accepted object differs from the raw model response.')
        return result, row['id']
    except Exception as exc:
        row['error'] = str(exc)
        raise
    finally:
        row.update(raw_response=model.last_response_text, elapsed_seconds=round(time.monotonic()-started, 3),
                   routing=dict(getattr(model, 'last_route', None) or getattr(model, 'last_call', {})),
                   model=(getattr(model, 'last_route', {}) or {}).get('model', model.name))
        row['response_hash'] = digest(row['raw_response'])
        attempts.append(row)
        save()


def response_answer(attempts, response_id):
    row = next((r for r in attempts if r['id'] == response_id), None)
    if not row or row.get('error'):
        raise ValueError('No successful model response supports this content.')
    if digest(row['raw_response']) != row['response_hash']:
        raise ValueError('Recorded model response was modified.')
    answer = json.loads(row['raw_response'])
    if answer != row['answer']:
        raise ValueError('Saved model answer differs from its original response.')
    return answer
