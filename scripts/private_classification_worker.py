"""One constrained text classification over the job's sole Ollama socket."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (1536*1024**2, 1536*1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4*1024**2, 4*1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agents.inference.local_ollama import local_chat, effective_chat_options
    from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
    from delivery.ingestion import _write_new
    job = Path.cwd(); raw = (job/'request.json').read_bytes(); body = json.loads(raw)
    outcome = {'state': 'failed', 'request_sha256': hashlib.sha256(raw).hexdigest()}
    budget = PreparationBudget(110, max_calls=1, max_requests=6)
    try:
        request = body['model_request']
        if (body.get('contract') != 'private-text-classification-v1' or body.get('operation') not in {'prompt', 'directive'}
                or set(request) != {'model', 'messages', 'format', 'options', 'keep_alive', 'stream', 'tools'}
                or request['model'] != 'llama3.2:3b' or request['keep_alive'] != 0
                or request['stream'] is not False or request['tools'] != []
                or request['options'] != effective_chat_options(request['model'], {'temperature': 0.0, 'num_ctx': 8192, 'num_predict': 512})):
            raise ValueError('Unsupported private classifier request')
        def capture(response):
            value = response.model_dump(mode='json') if hasattr(response, 'model_dump') else response
            outcome['response_sha256'] = _write_new(job/'raw-response.json', value)
        with preparation_budget(budget):
            budget.start_call()
            local_chat(**request, response_recorder=capture)
            budget.remaining()
        outcome['state'] = 'complete'
    except Exception as exc:
        outcome['error_type'] = type(exc).__name__
    finally:
        outcome['usage_sha256'] = _write_new(job/'usage.json', budget.snapshot())
        _write_new(job/'outcome.json', outcome)


if __name__ == '__main__': main()
