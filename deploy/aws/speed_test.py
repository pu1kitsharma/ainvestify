"""Speed of the model server at the pipeline's real settings, on synthetic text. Sends no company data."""
import json
import sys
import urllib.request

MODEL = sys.argv[1] if len(sys.argv) > 1 else 'qwen3.8:latest'
HOST = 'http://127.0.0.1:11434'
SCHEMA = {'type': 'object', 'required': ['headline', 'paragraphs'], 'properties': {
    'headline': {'type': 'string'}, 'paragraphs': {'type': 'array', 'items': {'type': 'string'}}}}
FACTS = '\n'.join(f'F{n} [historical] Widget line {n % 17}: sales of {n * 3 % 97}.{n % 10} million in period {n % 8} for region {n % 5}.' for n in range(1, 900))


def call(extra):
    body = {'model': MODEL, 'stream': False, 'format': SCHEMA, 'think': False,
            'messages': [{'role': 'system', 'content': 'You are an analyst. Write compact JSON on one line.'},
                         {'role': 'user', 'content': f'{FACTS}\n\nWrite a headline and three 80-word paragraphs on the trends above. {extra}'}],
            'options': {'temperature': 0.4, 'top_p': 0.8, 'top_k': 20, 'num_ctx': 40960, 'num_predict': 700}}
    request = urllib.request.Request(f'{HOST}/api/chat', json.dumps(body).encode(), {'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(request, timeout=1800))


for label, extra in (('cold', ''), ('warm, same prompt start', 'Be brief.')):
    result = call(extra)
    prompt, output = result.get('prompt_eval_count', 0), result.get('eval_count', 0)
    prefill, decode = result.get('prompt_eval_duration', 0) / 1e9, result.get('eval_duration', 0) / 1e9
    print(f'{label}: {prompt} prompt tokens in {prefill:.1f}s, {output} output tokens at {output / max(decode, .001):.1f} tok/s, '
          f'total {result.get("total_duration", 0) / 1e9:.1f}s')
print(json.load(urllib.request.urlopen(f'{HOST}/api/ps'))['models'][0]['size_vram'] / 2**30, 'GiB on the GPU')
