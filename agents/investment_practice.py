"""Versioned practitioner methods, kept separate from company evidence.

These are original paraphrases and synthetic teaching examples, not trained
weights, copied guides, or facts about a live company. Only selected methods
enter a generation call; retrieval never imports company-specific examples.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'research_corpus' / 'practice'
# Cross-sector financial prose was leaking into unrelated companies. These
# stages use practitioner methods and typed measurements, not a different
# company's economics as a response template.
METHOD_ONLY_STAGES = {'investment_case', 'commercial_test', 'funding_outline'}


@lru_cache(maxsize=1)
def corpus():
    data = json.loads((ROOT / 'methods.json').read_text())
    sources = {s['id'] for s in data['sources']}
    for method in data['methods']:
        if not method['sources'] or not set(method['sources']) <= sources:
            raise ValueError('Practitioner method needs a registered source')
    return data


def practice_context(stage):
    data = corpus()
    methods = [m for m in data['methods'] if stage in m['stages']]
    source_ids = {s for m in methods for s in m['sources']}
    return {
        'version': data['version'],
        'scope': 'Methods only. Not evidence of company traction, fundraising intent, legal compliance or completed work.',
        'methods': [{k: v for k, v in m.items() if k != 'stages'} for m in methods],
        'sources': [s for s in data['sources'] if s['id'] in source_ids],
    }


def practice_manifest(stage):
    context = practice_context(stage)
    examples = json.loads((ROOT / 'teaching_examples.json').read_text())['examples']
    selected = [] if stage in METHOD_ONLY_STAGES else [e for e in examples if e['stage'] == stage and e['split'] == 'train'][:1]
    return {'version': context['version'], 'method_ids': [m['id'] for m in context['methods']],
            'sha256': hashlib.sha256(json.dumps({'context':context, 'teaching':selected}, sort_keys=True).encode()).hexdigest(),
            'teaching_example_ids': [e['id'] for e in selected],
            'sources': context['sources'], 'adaptation': 'retrieved_practice_not_weight_training'}


def practice_instruction(stage, instruction):
    context = practice_context(stage)
    if not context['methods']:
        return instruction
    examples = json.loads((ROOT / 'teaching_examples.json').read_text())['examples']
    example = None if stage in METHOD_ONLY_STAGES else next((e for e in examples if e['stage'] == stage and e['split'] == 'train'), None)
    teaching = ('\nFictional teaching example: learn reasoning and response form only. Its facts and citation IDs do not apply to the target.\n'
                + json.dumps({'input': example['input'], 'response': example['response']}) if example else '')
    return (instruction + '\nApply the following practitioner methods only where relevant to this company and mandate. '
            'Choose the business-specific work and write its actual content. These methods are NOT company facts; '
            'never cite them as proof of traction. Source IDs in your answer must come from company evidence. '
            'Do not copy the framework as a checklist. Proposed work must remain distinct from observed results.\n'
            + json.dumps(context, ensure_ascii=False) + teaching)
