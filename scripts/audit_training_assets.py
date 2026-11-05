"""Inventory local JSONL assets without exposing private prompts or answers.

This stages metadata, not training examples. Explicit holdouts stay held out;
neither a filename nor source-use permission creates an approved target answer.
No model is loaded, weights updated, split changed, or network request made.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from scripts import build_memo_gold_sft as gold
from training.private_storage import private_path

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_ROWS = 100_000


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def _kind(row):
    if not isinstance(row, dict):
        return 'non_object'
    if row.get('task') in gold.TASKS and 'target' in row:
        return 'memo_candidate'
    if 'reason' in row and ('origin' in row or 'response_id' in row):
        return 'exclusion_log'
    if 'checks' in row and 'case_id' in row:
        return 'scorer_answer_key'
    if 'case_id' in row and 'input' in row and 'environment' in row:
        return 'task_fixture'
    if 'messages' in row or 'text' in row:
        return 'unqualified_chat_or_text'
    if any(key in row for key in ('observation', 'call', 'tool', 'response_bytes')):
        return 'trajectory_or_observation'
    if 'kind' in row and 'version' in row:
        return 'local_protocol_event'
    if all(key in row for key in ('case_id', 'sample', 'reward', 'attempt')):
        return 'sampled_reward_record'
    return 'unknown'


def _lineage(row):
    """Opaque keys bind company, evidence family and copied source holdouts."""
    if not isinstance(row, dict):
        return set()
    result = set()
    company = row.get('company_key') or row.get('deal_id')
    if isinstance(company, str) and company.strip():
        result.add(_hash(['company', company.strip().casefold()]))
    for field in ('evidence_family_ids', 'source_sha256'):
        values = row.get(field)
        if isinstance(values, list):
            result.update(_hash([field, value.strip().casefold()]) for value in values
                          if isinstance(value, str) and value.strip())
    sources = row.get('source_bundle')
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            for field in ('url', 'passage'):
                text = source.get(field)
                if isinstance(text, str) and text.strip():
                    result.add(_hash([field, ' '.join(text.split())]))
    return result


def audit(source_root: Path, output: Path, *, private_root: Path) -> dict:
    """Write an immutable metadata-only report under an explicit private root."""
    source_root = private_path(source_root, root=private_root, repo_root=gold.ROOT)
    output = private_path(output, root=private_root, repo_root=gold.ROOT)
    if not source_root.is_dir() or output.exists() or output.is_relative_to(source_root):
        raise ValueError('Source must exist; output must be new and outside the source tree')
    files, records, seen_rows = [], [], set()
    counts, splits, rights, review_gates, target_checks = (Counter() for _ in range(5))
    lineage_splits = defaultdict(set)
    for path in sorted(source_root.rglob('*.jsonl')):
        if path.is_symlink() or not path.resolve().is_relative_to(source_root):
            raise ValueError('JSONL symlink or path escape is not permitted')
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('JSONL exceeds bounded intake file size')
        file_id = _hash(path.relative_to(source_root).as_posix())
        digest, file_counts, file_rows = hashlib.sha256(), Counter(), 0
        with path.open('rb') as handle:
            while True:
                raw = handle.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_LINE_BYTES:
                    raise ValueError('JSONL exceeds bounded intake line size')
                digest.update(raw)
                if not raw.strip():
                    continue
                if len(records) >= MAX_ROWS:
                    raise ValueError('Intake exceeds bounded row count')
                file_rows += 1
                try:
                    row = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    row = None
                    kind = 'invalid_json'
                else:
                    kind = _kind(row)
                counts[kind] += 1
                file_counts[kind] += 1
                row_hash = _hash(row) if row is not None else hashlib.sha256(raw).hexdigest()
                duplicate = row_hash in seen_rows
                seen_rows.add(row_hash)
                split = row.get('split') if isinstance(row, dict) else None
                split = split if split in gold.SPLITS else 'unspecified'
                splits[split] += 1
                lineage = _lineage(row)
                if split != 'unspecified':
                    for key in lineage:
                        lineage_splits[key].add(split)
                provenance = row.get('provenance') if isinstance(row, dict) else None
                provenance = provenance if isinstance(provenance, dict) else {}
                permission = provenance.get('rights_status', row.get('rights_status')
                                            if isinstance(row, dict) else None)
                rights['approved' if permission in ('private_training_approved',
                                                    'public_training_approved') else 'not_approved'] += 1
                declared = provenance.get('adjudication') == 'approved'
                reviewers = provenance.get('reviewer_ids')
                dual = (isinstance(reviewers, list) and len({item for item in reviewers
                        if isinstance(item, str) and item.strip()}) >= 2)
                review_gates['approved_two_reviewers' if declared and dual else 'missing_approval_or_reviewers'] += 1
                target_valid, fully_valid = False, False
                if kind == 'memo_candidate':
                    try:
                        gold.validate_target(row)
                        target_valid = True
                    except Exception:
                        # Exception messages may include untrusted private values.
                        pass
                    target_checks['runtime_target_pass' if target_valid else 'runtime_target_fail'] += 1
                    try:
                        gold._validate(row)
                        fully_valid = True
                    except Exception:
                        pass
                records.append({'file_id': file_id, 'row': file_rows, 'kind': kind,
                                'split': split, 'duplicate': duplicate,
                                'runtime_target_valid': target_valid,
                                'all_gold_row_gates_pass': fully_valid,
                                '_lineage': lineage})
        files.append({'file_id': file_id, 'sha256': digest.hexdigest(),
                      'rows': file_rows, 'kinds': dict(file_counts)})
    candidates, heldout, collision, eligible = 0, 0, 0, 0
    for record in records:
        lineage = record.pop('_lineage')
        crosses = any(len(lineage_splits[key]) > 1 for key in lineage)
        has_holdout = any(lineage_splits[key] & {'valid', 'test'} for key in lineage)
        record['cross_split_lineage'] = crosses
        record['weight_update_eligible'] = bool(
            record['kind'] == 'memo_candidate' and record['all_gold_row_gates_pass'] and
            record['split'] == 'train' and lineage and not has_holdout and not
            record['duplicate'])
        if record['kind'] == 'memo_candidate':
            candidates += 1
            heldout += record['split'] in ('valid', 'test')
        collision += crosses
        eligible += record['weight_update_eligible']
    summary = {'contract': 'local-training-intake-v1', 'files': len(files),
               'rows': len(records), 'kinds': dict(counts), 'explicit_splits': dict(splits),
               'rights': dict(rights), 'review': dict(review_gates),
               'memo_target_checks': dict(target_checks), 'memo_candidates': candidates,
               'memo_holdout_rows': heldout, 'duplicate_rows': sum(r['duplicate'] for r in records),
               'cross_split_lineage_rows': collision, 'weight_update_eligible_rows': eligible,
               'corpus_export_ready': False, 'weight_updates_started': False,
               'production_model_roles_changed': False, 'release_qualified': False,
               'notes': ['Only explicit row splits count; filenames do not assign splits.',
                         'Scorer keys, exclusions and trajectories are not adjudicated targets.',
                         'Synthetic fixture rights are not training approval.',
                         'Eligible row counts do not replace corpus-wide exporter and review gates.']}
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    gold._write_private(output / 'summary.json', json.dumps(summary, indent=2) + '\n')
    gold._write_private(output / 'files.json', json.dumps(files, indent=2) + '\n')
    gold._write_private(output / 'rows.jsonl', ''.join(json.dumps(row) + '\n' for row in records))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--private-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = audit(args.source_root, args.output, private_root=args.private_root)
    except Exception:
        # Avoid echoing Pydantic/JSON errors containing private source values.
        parser.exit(1, 'Intake failed; no corpus is eligible. Check private paths and input bounds locally.\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
