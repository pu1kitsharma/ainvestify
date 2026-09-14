"""Compare actual local responses before/after practice grounding; no live DB writes.

Automated checks detect named regressions, not investor quality. Raw outputs
are retained for substantive assessment. Evaluation answers never enter prompts.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pydantic import Field, create_model
from typing import Literal
from agents.company_brief import CONTRACTS, INSTRUCTIONS, validate_deliverable
from agents.investment_practice import practice_instruction, practice_manifest
from agents.local_models import LocalModel


def check_response(case, output):
    text = json.dumps(output, ensure_ascii=False).casefold()
    failed = ['missing concept: ' + '/'.join(group) for group in case['checks']['required_any']
              if not any(term.casefold() in text for term in group)]
    failed += ['forbidden assertion or example leakage: ' + term for term in case['checks']['forbidden'] if term.casefold() in text]
    return failed


def run(args):
    cases = json.loads(Path(args.cases).read_text())
    model = LocalModel()
    rows = []
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        if args.case and case['id'] not in args.case:
            continue
        ids = tuple(e['id'] for e in case['input']['evidence'])
        schema = create_model('EvaluationOutput', __base__=CONTRACTS[case['stage']],
                              evidence_ids=(list[Literal[ids]], Field(min_length=1, max_length=4)))
        for mode in args.modes:
            instruction = INSTRUCTIONS[case['stage']]
            if mode == 'practice':
                instruction = practice_instruction(case['stage'], instruction)
            start = time.monotonic()
            model.last_response_text = ''
            row = {'case': case['id'], 'stage': case['stage'], 'mode': mode, 'model': model.name}
            try:
                result = model.generate(instruction, json.dumps(case['input']), schema)
                row['output'] = result.model_dump()
                row['failures'] = check_response(case, row['output'])
                validate_deliverable(result, case['stage'], case['input']['company_name'])
            except Exception as exc:
                row.setdefault('failures', []).append(str(exc))
                row['raw_response'] = model.last_response_text
            row['seconds'] = round(time.monotonic() - start, 2)
            rows.append(row)
            report = {'scope': 'Synthetic regression probes, not expert quality scores or proof of autonomous fundraising.',
                      'practice': practice_manifest('research'), 'results': rows}
            dest.write_text(json.dumps(report, indent=2, ensure_ascii=False))
            print(f"{case['id']} {mode}: {'PASS targeted checks' if not row['failures'] else 'FAIL: '+str(row['failures'])} ({row['seconds']}s)", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', default='evals/investment_preparation/cases.json')
    parser.add_argument('--output', required=True)
    parser.add_argument('--case', action='append')
    parser.add_argument('--modes', nargs='+', choices=['baseline', 'practice'], default=['baseline', 'practice'])
    run(parser.parse_args())
