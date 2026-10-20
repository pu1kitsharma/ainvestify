"""Standalone MLX generation worker. Run with the MLX venv python, not the repo venv.

    python training/mlx_infer.py request.json response.json

request: {model, adapter|null, prompts:[{messages:[..]} | {raw:"text"}], max_tokens,
temperature, seed}.  Imports mlx_lm lazily so `import training.mlx_infer` is safe anywhere.
"""
import json
import sys


def run(request):
    import mlx.core as mx
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler
    mx.random.seed(int(request.get('seed', 0)))
    model, tokenizer = load(request['model'], adapter_path=request.get('adapter') or None)
    sampler = make_sampler(temp=float(request.get('temperature', 0.0)))
    outputs = []
    for prompt in request['prompts']:
        if 'raw' in prompt:
            text = prompt['raw']
        else:
            text = tokenizer.apply_chat_template(prompt['messages'], tokenize=False,
                                                 add_generation_prompt=True)
        outputs.append(generate(model, tokenizer, prompt=text, max_tokens=int(request.get('max_tokens', 256)),
                                sampler=sampler, verbose=False))
    return {'outputs': outputs, 'adapter': request.get('adapter') or None}


if __name__ == '__main__':
    with open(sys.argv[1]) as handle:
        req = json.load(handle)
    with open(sys.argv[2], 'w') as handle:
        json.dump(run(req), handle)
