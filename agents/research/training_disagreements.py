"""Claude Code implementation: compare recorded reviews without adjudicating them."""
import hashlib
import json
from collections import defaultdict

TASK = 'memo_content_review'
VERDICTS = frozenset({'supported_or_conditional', 'unsupported', 'insufficient_evidence'})
_INPUT_KEYS = (
    'field_path', 'sentences', 'context', 'sources', 'complete_source_set_digest',
    'selected_source_ids', 'omitted_source_ids', 'complete_source_ids', 'review_model',
)
_TARGET_KEYS = ('verdict', 'focus_sentence_id', 'source_id', 'reason')


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _require(obj, keys, where):
    if not isinstance(obj, dict):
        raise ValueError(f'{where} must be an object')
    missing = [k for k in keys if k not in obj]
    if missing:
        raise ValueError(f'{where} missing keys: {missing}')


def classify_review_disagreements(records):
    '''Group recorded reviews whose substantive input is identical (review_model excluded).

    Only groups and counts reviewer verdicts; never adjudicates, labels, or echoes
    passages/reasons. Differences in prose, sources, or scope yield separate groups.
    '''
    seen = set()
    buckets = defaultdict(list)
    total = ignored = 0
    for rec in records:
        total += 1
        _require(rec, ('case_id', 'task'), 'record')
        if rec['task'] != TASK:
            ignored += 1
            continue
        _require(rec, ('input', 'target', 'provenance'), 'record')
        cid = rec['case_id']
        if not isinstance(cid, str) or not cid:
            raise ValueError('case_id must be a non-empty string')
        if cid in seen:
            raise ValueError(f'duplicate case_id: {cid}')
        seen.add(cid)
        _require(rec['input'], _INPUT_KEYS, f'{cid}: input')
        _require(rec['target'], _TARGET_KEYS, f'{cid}: target')
        _require(rec['provenance'], ('model_name',), f'{cid}: provenance')
        verdict = rec['target']['verdict']
        if not isinstance(verdict, str) or verdict not in VERDICTS:
            raise ValueError(f'{cid}: unknown verdict')
        model = rec['provenance']['model_name']
        if not isinstance(model, str) or not model:
            raise ValueError(f'{cid}: model_name must be a non-empty string')
        substantive = {k: v for k, v in rec['input'].items() if k != 'review_model'}
        digest = hashlib.sha256(_canon(substantive).encode('utf-8')).hexdigest()
        buckets[digest].append((cid, model, verdict))

    groups = []
    verdict_counts = defaultdict(int)
    for digest in sorted(buckets):
        items = buckets[digest]
        per_model = defaultdict(set)
        for cid, model, verdict in items:
            per_model[model].add(verdict)
            verdict_counts[verdict] += 1
        verdicts = sorted({v for _, _, v in items})
        groups.append({
            'group_digest': digest,
            'case_ids': sorted(c for c, _, _ in items),
            'verdicts': verdicts,
            'model_names': sorted(per_model),
            'mixed_verdicts': len(verdicts) > 1,
            'acceptance_disagreement': ('supported_or_conditional' in verdicts and
                                       len(verdicts) > 1),
            'within_model_disagreement': any(len(v) > 1 for v in per_model.values()),
        })

    summary = {
        'records_total': total,
        'records_ignored': ignored,
        'reviews': total - ignored,
        'groups': len(groups),
        'singleton_groups': sum(len(g['case_ids']) == 1 for g in groups),
        'groups_with_mixed_verdicts': sum(g['mixed_verdicts'] for g in groups),
        'groups_with_acceptance_disagreement': sum(g['acceptance_disagreement'] for g in groups),
        'groups_with_within_model_disagreement': sum(g['within_model_disagreement'] for g in groups),
        'verdict_counts': dict(sorted(verdict_counts.items())),
    }
    return {'groups': groups, 'summary': summary}
