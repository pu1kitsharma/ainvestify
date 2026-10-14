"""Import saved local-model answers into a private, unadjudicated review queue.

Permission to use source material is recorded separately from answer approval.
No company prose, target answer or model weight is created by this script.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from agents.inference.model_authorship import digest, response_answer
from agents.research import memo_content_review as review
from agents.research import memo_content_repair as repair
from agents.research.investment_memo import Memo, Source, renderable_sections
from scripts import build_memo_gold_sft as gold

PRIVATE_RUNS = gold.ROOT / 'runtime_qualification' / 'private_acceptance'
TASK_NAMES = {review.TASK: 'memo_content_review', repair.TASK: 'memo_content_repair'}


def _family(source):
    match = re.match(r'private://([0-9a-f]{64})/', source['url'])
    return match.group(1) if match else digest({'source_url': source['url']})


def prepare(roots: list[Path], output: Path, *, company_key: str,
            sector: str, approval_id: str, approved_on: str) -> dict:
    base, destination = PRIVATE_RUNS.resolve(), output.resolve()
    if (not destination.is_relative_to(gold.PRIVATE_DATA.resolve()) or
            destination == gold.PRIVATE_DATA.resolve() or destination.exists()):
        raise ValueError('Output must be a new directory under ignored models/data/')
    if not all(isinstance(value, str) and value.strip() for value in
               (company_key, sector, approval_id, approved_on)):
        raise ValueError('Explicit source-use approval and company identity are required')
    requests = set()
    for root in roots:
        root = root.resolve()
        if not root.is_relative_to(base) or not root.is_dir():
            raise ValueError('Input must remain under private acceptance diagnostics')
        requests.update(root.rglob('content_request.json'))
        for path in root.rglob('request.json'):
            profile_path, result_path = path.parent / 'model.json', path.parent / 'result.json'
            if profile_path.is_file() and result_path.is_file():
                profile = json.loads(profile_path.read_text())
                result = json.loads(result_path.read_text())
                if profile.get('memo_draft_contract') == 'memo-cards-v13' and result.get('state') == 'accepted':
                    requests.add(path)
    if not requests:
        raise ValueError('No saved content requests found')
    candidates, excluded, counts = {}, [], Counter()
    for request_path in sorted(requests):
        if not request_path.resolve().is_relative_to(base):
            raise ValueError('Private request symlink escapes approved root')
        request = json.loads(request_path.read_text())
        is_memo = request_path.name == 'request.json'
        if not is_memo and request.get('digest') != digest({k: v for k, v in request.items() if k != 'digest'}):
            raise ValueError('Saved request digest changed')
        sources = [Source.model_validate(row).model_dump(mode='json')
                   for row in request['sources']]
        memo_snapshots = ({digest(request['memo']): request['memo']}
                          if not is_memo and 'memo' in request else {})
        if is_memo:
            profile = json.loads((request_path.parent / 'model.json').read_text())
            result = json.loads((request_path.parent / 'result.json').read_text())
            recorded = json.loads((request_path.parent / 'attempts.json').read_text())
            renderable_sections(result['accepted'], [Source.model_validate(s) for s in sources],
                                recorded, projection=profile.get('section_projection'))
            paths = [request_path.parent / 'attempts.json']
        else:
            paths = sorted(request_path.parent.glob('content_*attempts*.json'))
        for path in paths:
            if not path.resolve().is_relative_to(base):
                raise ValueError('Private attempt symlink escapes approved root')
            rows = json.loads(path.read_text())
            for row in rows:
                counts['recorded_attempts'] += 1
                origin = {'file': str(path.relative_to(base)), 'response_id': row['id'],
                          'response_hash': row.get('response_hash')}
                reason = None
                task = TASK_NAMES.get(row.get('task'))
                if (is_memo and re.fullmatch(r'investment_memo_part_a_.*_source_[12]_v7',
                                             row.get('task', ''))):
                    task = 'memo_source_author'
                if task is None:
                    reason = 'historical_contract'
                elif row.get('error'):
                    reason = 'recorded_failure'
                elif row.get('instruction') != gold.task_instruction(task, row.get('input', {})):
                    reason = 'historical_instruction'
                if reason is None:
                    try:
                        target = response_answer(rows, row['id'])
                        payload = row['input']
                        pin = (profile['profiles']['author'] if is_memo else
                               request['review_contract']['model_name'] if
                               task == 'memo_content_review' else request['author_pin']['name'])
                        if row.get('model') != pin:
                            raise ValueError('model changed')
                        schema = gold._schema(task, payload)
                        if row.get('schema') != schema.model_json_schema():
                            raise ValueError('schema changed')
                        item = {'case_id': digest({'task': task, 'input': payload,
                                                  'target': target}),
                                'company_key': company_key, 'split': 'test',
                                'evidence_family_ids': sorted({_family(s) for s in sources}),
                                'task': task, 'input': payload, 'target': target,
                                'instruction': row['instruction'],
                                'source_bundle': sources,
                                'provenance': {'rights_status': 'private_training_approved',
                                    'source_approval_id': approval_id,
                                    'source_set_digest': digest(sources), 'sector': sector,
                                    'adjudication': 'pending', 'reviewer_ids': [],
                                    'label_origin': 'recorded_local_model',
                                    'model_name': row.get('model'), 'origins': [origin]}}
                        if task == 'memo_content_repair':
                            base_memo = memo_snapshots.get(payload.get('base_memo_digest'))
                            if base_memo is None:
                                raise ValueError('Frozen memo snapshot unavailable')
                            item['base_memo'] = base_memo
                        gold.validate_target(item)
                        if task == 'memo_content_repair':
                            revised = repair._project(Memo.model_validate(base_memo),
                                [Source.model_validate(s) for s in sources], payload, target)
                            snapshot = revised.model_dump(mode='json')
                            memo_snapshots[digest(snapshot)] = snapshot
                    except (ValueError, TypeError, KeyError):
                        reason = 'replay_or_target_validation_failed'
                if reason:
                    counts[reason] += 1
                    excluded.append({**origin, 'reason': reason})
                    continue
                key = item['case_id']
                if key in candidates:
                    candidates[key]['provenance']['origins'].append(origin)
                    counts['duplicate_candidates'] += 1
                else:
                    candidates[key] = item
    items = sorted(candidates.values(), key=lambda item: item['case_id'])
    from agents.research.training_disagreements import classify_review_disagreements
    disagreements = classify_review_disagreements(items)
    manifest = {'contract': 'memo-training-candidates-v1',
                'requests': len(requests), 'counts': dict(counts),
                'candidate_counts': dict(Counter(item['task'] for item in items)),
                'companies': 1, 'default_split': 'test',
                'source_training_approved': True, 'answers_adjudicated': False,
                'trainable_examples': 0, 'weights_trained': False,
                'review_disagreements': disagreements['summary']}
    missing, directory = [], destination
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
    gold._write_private(destination / 'candidates.jsonl', ''.join(
        json.dumps(item, ensure_ascii=False) + '\n' for item in items))
    gold._write_private(destination / 'excluded.jsonl', ''.join(
        json.dumps(item) + '\n' for item in excluded))
    gold._write_private(destination / 'disagreements.json', json.dumps(disagreements, indent=2))
    gold._write_private(destination / 'source_approval.json', json.dumps({
        'approval_id': approval_id, 'approved_on': approved_on,
        'scope': 'Private supplied material and recorded derivatives for local training preparation',
        'approved_by': 'user', 'answer_approval': 'pending',
        'inputs': [str(path.relative_to(base)) for path in sorted(requests)]}, indent=2))
    gold._write_private(destination / 'manifest.json', json.dumps(manifest, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('roots', type=Path, nargs='+')
    parser.add_argument('--company-key', required=True)
    parser.add_argument('--sector', required=True)
    parser.add_argument('--approval-id', required=True)
    parser.add_argument('--approved-on', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.roots, args.output, company_key=args.company_key,
                            sector=args.sector, approval_id=args.approval_id,
                            approved_on=args.approved_on), indent=2))
