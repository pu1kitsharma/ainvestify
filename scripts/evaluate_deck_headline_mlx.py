"""Score a local MLX model (optionally with a LoRA adapter) on held-out gold slides."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from mlx_lm import generate, load

from agents.research.deck_headline import DeckHeadline, validate_copy
from scripts.build_deck_headline_sft import system_prompt


def norm(text):
    return re.sub(r'\s+', ' ', text).strip().casefold()


def evaluate(model_path, adapter, rows):
    model, tokenizer = load(model_path, adapter_path=adapter)
    results = []
    for row in rows:
        prompt = ('<|im_start|>system\n' + system_prompt() + '<|im_end|>\n<|im_start|>user\n' +
                  row['user'] + '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n')
        raw = generate(model, tokenizer, prompt=prompt, max_tokens=220, verbose=False)
        gold = json.loads(row['assistant'])
        entry = {'id': row['id'], 'raw': raw, 'gold': gold}
        try:
            answer = DeckHeadline.model_validate_json(raw.strip().removesuffix('<|im_end|>'))
            entry['schema_ok'] = True
            page = json.loads(row['user'])['page_text']
            try:
                validate_copy(page, answer)
                entry['copy_ok'] = True
            except ValueError:
                entry['copy_ok'] = False
            entry['heading_exact'] = norm(answer.heading) == norm(gold['heading'])
            entry['message_exact'] = norm(answer.message) == norm(gold['message'])
        except Exception:
            entry.update(schema_ok=False, copy_ok=False, heading_exact=False, message_exact=False)
        results.append(entry)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('model'), parser.add_argument('data', type=Path), parser.add_argument('out', type=Path)
    parser.add_argument('--adapter')
    parser.add_argument('--splits', nargs='+', default=['valid', 'test'])
    args = parser.parse_args()
    rows = [r for s in args.splits for r in json.load(open(args.data / f'{s}.meta.json'))]
    results = evaluate(args.model, args.adapter, rows)
    summary = {k: sum(r[k] for r in results) for k in ('schema_ok', 'copy_ok', 'heading_exact', 'message_exact')}
    summary['n'] = len(results)
    args.out.write_text(json.dumps({'summary': summary, 'results': results}, indent=1, ensure_ascii=False))
    print(summary)
