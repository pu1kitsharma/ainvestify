"""Private content review, model-authored repair and re-review of an accepted memo.

Isolated diagnostic beside an accepted private memo. It never edits the original
memo, its raw attempts, or the supplied originals, and its acceptance is only
`local_model_checks_only`: independent review stays pending. Invoke once per
bounded pass (`prepare`, repeated `advance`, then `verify`).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from agents.inference.model_authorship import digest
from agents.research import memo_content_repair as repair
from agents.research import memo_content_review as review
from agents.research.investment_memo import Source
from delivery.isolation import run_private
from scripts.evaluate_private_acceptance import OUTPUT_ROOT
from scripts.evaluate_private_material_acceptance import (_installed_digest, _replace,
                                                          _write_new)

PROJECT = Path(__file__).resolve().parents[1]
MAX_PASSES = 80


def _memo_inputs(memo_root: Path):
    root = memo_root.resolve()
    if not root.is_relative_to(OUTPUT_ROOT.resolve()) or root == OUTPUT_ROOT.resolve():
        raise ValueError('Memo is outside private acceptance diagnostics')
    request = json.loads((root / 'request.json').read_text())
    profile = json.loads((root / 'model.json').read_text())
    result = json.loads((root / 'result.json').read_text())
    if (result.get('state') != 'accepted' or
            result.get('acceptance_scope') != 'local_model_checks_only' or
            result.get('independent_review') != 'pending'):
        raise ValueError('An exact locally accepted private memo is required')
    return root, request, profile, result['accepted']


def load_revision(content_root: Path) -> dict:
    """Frozen record for `replay_content_revision`, from the recorded files."""
    request = json.loads((content_root / 'content_request.json').read_text())
    def rows(name):
        path = content_root / name
        return json.loads(path.read_text()) if path.exists() else []
    later = []
    for number in range(2, repair.MAX_ROUNDS + 1):
        entry = {'repair_attempts': rows(f'content_repair_attempts_{number}.json'),
                 'rereview_attempts': rows(f'content_rereview_attempts_{number}.json')}
        if entry['repair_attempts'] or entry['rereview_attempts']:
            later.append(entry)
    record = {'contract': repair.REVISION_CONTRACT,
              'review_contract': request['review_contract'],
              'author_pin': request['author_pin'],
              'base_memo_digest': digest(request['memo']),
              'review_attempts': rows('content_review_attempts.json'),
              'repair_attempts': rows('content_repair_attempts.json'),
              'rereview_attempts': rows('content_rereview_attempts.json')}
    if later:
        record['later_rounds'] = later
    return record


def run(memo_root: Path, output: Path, phase: str, *, review_model: str | None = None) -> dict:
    memo_dir, request, profile, accepted = _memo_inputs(memo_root)
    root = output.resolve()
    if (not root.is_relative_to(OUTPUT_ROOT.resolve()) or root == memo_dir or
            root.parent != memo_dir.parent):
        raise ValueError('Content output must be beside its private memo diagnostic')
    if phase == 'prepare':
        reviewer = review_model or profile['profiles'].get('challenge') or profile['profiles']['review']
        author = profile['profiles']['author']
        body = {'memo': accepted['memo'], 'sources': request['sources'],
                'memo_root': str(memo_dir),
                'review_contract': {'version': review.CONTRACT, 'model_name': reviewer,
                                    'model_digest': _installed_digest(reviewer)},
                'author_pin': {'name': author, 'digest': _installed_digest(author)}}
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        _write_new(root / 'content_request.json', {**body, 'digest': digest(body)})
        return {'state': 'prepared', 'diagnostic_path': str(root)}
    saved = json.loads((root / 'content_request.json').read_text())
    if saved['memo'] != accepted['memo'] or saved['sources'] != request['sources']:
        raise ValueError('Frozen private memo changed')
    if phase == 'advance':
        for name, expected in ((saved['review_contract']['model_name'],
                                saved['review_contract']['model_digest']),
                               (saved['author_pin']['name'], saved['author_pin']['digest'])):
            if _installed_digest(name) != expected:
                raise ValueError('Installed local model differs from frozen digest')
        history_file = root / 'content_passes.json'
        history = json.loads(history_file.read_text()) if history_file.exists() else []
        if len(history) >= MAX_PASSES or any(row['state'] == 'started' for row in history[:-1]):
            raise ValueError('Bounded content revision cannot continue')
        if history and history[-1]['state'] not in {'needs_resume', 'worker_error'}:
            raise ValueError('Content revision already ended')
        history.append({'pass': len(history) + 1, 'state': 'started'})
        (_replace if history_file.exists() else _write_new)(history_file, history)
        budget_file = root / 'content_budget.json'
        (_replace if budget_file.exists() else _write_new)(budget_file, {'seconds': 105})
        try:
            run_private([sys.executable, PROJECT / 'scripts/private_memo_content_worker.py'],
                        root, timeout=118, extra_read=(PROJECT / 'agents', PROJECT / 'schemas.py'),
                        local_model=True)
            result = json.loads((root / 'content_result.json').read_text())
        except RuntimeError:
            history[-1]['state'] = 'worker_error'
            _replace(history_file, history)
            return {'state': 'worker_error', 'passes': len(history),
                    'diagnostic_path': str(root), 'independent_review': 'pending'}
        history[-1]['state'] = result['state']
        _replace(history_file, history)
        return {'state': result['state'], 'reason': result.get('reason'),
                'passes': len(history), 'diagnostic_path': str(root),
                'independent_review': 'pending'}
    if phase == 'verify':
        sources = [Source.model_validate(row) for row in saved['sources']]
        revised, record = repair.replay_content_revision(
            saved['memo'], sources, load_revision(root))
        return {**record, 'diagnostic_path': str(root),
                'acceptance_scope': 'local_model_checks_only'}
    raise ValueError('Unknown content revision phase')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('memo_root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('phase', choices=('prepare', 'advance', 'verify'))
    parser.add_argument('--review-model', help='Installed local model for the content reviewer')
    args = parser.parse_args()
    print(json.dumps(run(args.memo_root, args.output, args.phase,
                         review_model=args.review_model), ensure_ascii=False))


if __name__ == '__main__':
    main()
