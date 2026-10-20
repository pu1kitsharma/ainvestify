"""Offline synthetic workbook-to-pack checkpoint. Never calls a model endpoint."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.runtime.loop import AgentRuntime
from agents.tools import WorkbookTools
from agents.tools.pack import PackTools
from agents.tools.export_manifest import verify_export
from agents.tools.registry import build_tool_registry

MODEL = 'scripted:synthetic'
ENDPOINT = 'http://127.0.0.1:11434/v1'


def digest(path):
    hashed = hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            block = stream.read(65536)
            if not block:
                break
            hashed.update(block)
    return hashed.hexdigest()


class ScriptedTransport:
    """Explicit fixture messages, not model-generated answers or training gold."""
    def __init__(self, calls):
        self.calls, self.used = calls, 0

    def __call__(self, *, endpoint, request, timeout):
        self.used += 1
        if self.used > 2:
            raise ValueError('Synthetic two-response script exhausted')
        if self.used == 1:
            calls = [{'id': f'fixture-{index}', 'type': 'function',
                      'function': {'name': name, 'arguments': json.dumps(args)}}
                     for index, (name, args) in enumerate(self.calls)]
            message, reason = {'role': 'assistant', 'content': None, 'tool_calls': calls}, 'tool_calls'
        else:
            message, reason = {'role': 'assistant', 'content': 'Synthetic fixture complete; review required.'}, 'stop'
        return {'model': MODEL, 'choices': [{'message': message, 'finish_reason': reason}],
                'usage': {'total_tokens': 1}}


def run_session(output):
    root = Path(output).resolve()
    root.mkdir(parents=False, exist_ok=False, mode=0o700)
    started = time.monotonic()
    workbook = WorkbookTools(root)
    registry = build_tool_registry(workbook=workbook)
    scripts = [('modeling_analyst', [
        ('wb.add_sheet', {'title': 'Historicals'}),
        ('wb.write', {'sheet': 'Historicals', 'address': 'A1:C3', 'values': [
            ['Period', 'Metric', 'Value'], ['FY1', 'Synthetic revenue', 100], ['FY2', 'Synthetic revenue', 120]]}),
        ('wb.comment', {'sheet': 'Historicals', 'address': 'A1:C3', 'text': 'Synthetic test fixture; no company evidence.'}),
        ('wb.write', {'sheet': 'Historicals', 'address': 'D3', 'values': [['=C3/C2-1']]}),
        ('wb.recalc', {})])]
    statuses, scripted_calls = [], 0

    def run(role, calls, tools):
        nonlocal scripted_calls
        transport = ScriptedTransport(calls)
        runtime = AgentRuntime(endpoint=ENDPOINT, model=MODEL, transport=transport,
                               tools=tools, directory=root / role)
        state = runtime.run(role, 'Run the explicit synthetic fixture. No real company or model.')
        if state['status'] != 'human_review_required':
            raise ValueError('Scripted runtime did not reach a reviewable draft: ' + str(state.get('error')))
        for row in (root / role / 'trajectory.jsonl').read_text().splitlines():
            event = json.loads(row)
            if event.get('kind') == 'tool_observation' and not event['observation']['ok']:
                raise ValueError('A scripted tool failed: ' + str(event['observation']['errors']))
        scripted_calls += transport.used
        statuses.append({'role': role, 'state': state['status'], 'scripted_calls': transport.used})

    for role, calls in scripts:
        run(role, calls, registry)
    refs = [{'workbook_sha256': digest(root / 'model.xlsx'), 'sheet': 'Historicals', 'cell': 'C2'},
            {'workbook_sha256': digest(root / 'model.xlsx'), 'sheet': 'Historicals', 'cell': 'C3'}]
    pack = PackTools(root, workbook='model.xlsx')
    registry = build_tool_registry(workbook=workbook, pack=pack)
    run('deck_designer', [
        ('deck.add_slide', {'layout': 'table'}),
        ('deck.title', {'slide': 1, 'text': 'Synthetic historical observations', 'cell_refs': refs}),
        ('deck.table', {'slide': 1, 'values': [['Period', 'Value'], ['FY1', '100'], ['FY2', '120']], 'cell_refs': refs}),
        ('deck.add_slide', {'layout': 'chart'}),
        ('deck.title', {'slide': 2, 'text': 'Synthetic source values', 'cell_refs': refs}),
        ('deck.chart', {'slide': 2, 'categories': ['FY1', 'FY2'],
                        'series': [{'name': 'Synthetic revenue', 'values': [100, 120]}],
                        'chart_type': 'bar', 'cell_refs': refs})], registry)
    run('im_writer', [('memo.write', {'heading': 'Synthetic fixture',
        'text': 'This document verifies local software plumbing only. Human review is required.',
        'cell_refs': refs})], registry)
    # Host-directed artifact commit, explicitly outside the model role loop.
    exported = registry['pack.export']['call'](stem='synthetic-v1')
    if not exported['ok']:
        raise ValueError('Draft export failed: ' + str(exported['errors']))
    receipt = exported['result']
    verify_export(root, receipt['manifest'], expected_sha256=receipt['manifest_sha256'])
    elapsed = time.monotonic() - started
    if scripted_calls > 6 or elapsed > 120:
        raise ValueError('Scripted session exceeded cumulative checkpoint bounds')
    evidence_files = [root / 'model.xlsx', root / 'workbook.trajectory.jsonl', root / 'pack.trajectory.jsonl']
    evidence_files.extend(sorted(root.glob('*/checkpoint.json')))
    evidence_files.extend(sorted(root.glob('*/trajectory.jsonl')))
    report = {'contract': 'agentic-tool-session/v1', 'status': 'synthetic_tools_passed',
              'actual_model_calls': 0, 'scripted_transport_calls': scripted_calls,
              'model_quality': 'not_assessed', 'training': 'not_run', 'release': 'blocked',
              'calculation': 'bounded_diagnostic_only_no_formula_caches', 'visual_validation': 'not_run',
              'roles': statuses, 'export': receipt,
              'evidence': [{'path': str(path.relative_to(root)), 'sha256': digest(path)} for path in evidence_files]}
    target = root / 'session.json'
    with target.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
    target.chmod(0o600)
    session_hash = digest(target)
    (root / 'session.sha256').write_text(session_hash + '\n')
    return {**report, 'session_sha256': session_hash}


def replay_session(output, *, expected_sha256):
    root = Path(output).resolve(strict=True)
    if digest(root / 'session.json') != expected_sha256:
        raise ValueError('Session manifest changed')
    report = json.loads((root / 'session.json').read_text())
    if report.get('contract') != 'agentic-tool-session/v1' or report.get('actual_model_calls') != 0:
        raise ValueError('Unsupported synthetic session')
    for item in report['evidence']:
        path = (root / item['path']).resolve(strict=True)
        if not path.is_relative_to(root) or digest(path) != item['sha256']:
            raise ValueError('Session evidence changed')
    receipt = report['export']
    result = verify_export(root, receipt['manifest'], expected_sha256=receipt['manifest_sha256'])
    return {**result, 'session_status': 'synthetic_tools_passed', 'actual_model_calls': 0,
            'rerendered': False, 'session_sha256': expected_sha256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    if args.replay and not args.expected_sha256:
        parser.error('--replay requires the independently recorded --expected-sha256')
    result = replay_session(args.output, expected_sha256=args.expected_sha256) if args.replay else run_session(args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
