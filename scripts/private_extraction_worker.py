"""Isolated local inference entry point; no DB, source directory or API secret."""
from __future__ import annotations
import hashlib
from pathlib import Path
import sys


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agents.inference.local_ollama import local_chat
    from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
    from delivery.extraction import CONTRACT, digest, load_json, validate_response, write_json
    from delivery.storage import read_source_bytes
    from schemas import Document
    job = Path.cwd()
    raw = read_source_bytes(job / 'request.json')
    request = load_json(raw)
    if (request.get('contract') != CONTRACT or type(request.get('max_seconds')) not in (int, float)
            or not 0 < request['max_seconds'] <= 120):
        raise ValueError('Unsupported private extraction request')
    document = Document.model_validate(request['document'])
    call_raw = read_source_bytes(job / 'model-request.json')
    if (digest(document.model_dump(mode='json')) != request['document_sha256']
            or hashlib.sha256(call_raw).hexdigest() != request['model_request_sha256']):
        raise ValueError('Private extraction worker input changed')
    call = load_json(call_raw)
    required = {'model', 'messages', 'format', 'options', 'keep_alive', 'stream', 'tools'}
    if (set(call) not in (required, required | {'think'})
            or call['model'] != request['model'] or call['stream'] is not False
            or call['tools'] != [] or call['keep_alive'] != 0
            or 'think' in call and call['think'] is not False):
        raise ValueError('Unsupported private extraction model request')
    budget = PreparationBudget(max_seconds=request['max_seconds'], max_calls=6, max_requests=6)
    response_hash = None
    def record(response):
        nonlocal response_hash
        value = response.model_dump(mode='json') if hasattr(response, 'model_dump') else response
        response_hash = write_json(job / 'raw-response.json', value)
    try:
        with preparation_budget(budget):
            budget.start_call()
            local_chat(**call, timeout_seconds=budget.remaining(), response_recorder=record)
    finally:
        usage_hash = write_json(job / 'usage.json', budget.snapshot())
    response = load_json(read_source_bytes(job / 'raw-response.json'))
    result = validate_response(response, request['model'], document, request['extracted_at'], call)
    write_json(job / 'result.json', {'contract': CONTRACT, 'request_sha256': hashlib.sha256(raw).hexdigest(),
        'document_sha256': request['document_sha256'], 'model_request_sha256': request['model_request_sha256'],
        'response_sha256': response_hash, 'usage_sha256': usage_hash, 'result': result.model_dump(mode='json')})


if __name__ == '__main__':
    main()
