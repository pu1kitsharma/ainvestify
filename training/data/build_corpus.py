"""Assign sector-held-out splits, validate with training.envs.splits, write tasks/keys/manifest.

Synthetic fixtures are never rights-approved. With plumbing_only=True they are relabelled
approved IN MEMORY for the leakage validator only; the manifest then states that the corpus is
plumbing-only and counts zero real companies toward the coverage gate.
"""
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from training.envs.splits import validate_splits

from . import source_registry, xbrl_tasks

GATE = {'companies': 20, 'evidence_families': 50, 'sectors': 3}
SOURCE_ID = 'sec_edgar_companyfacts'


def assign_sector_splits(sectors):
    """Sector-disjoint: the splits validator requires sectors not to cross splits."""
    ordered = sorted(set(sectors), key=lambda s: hashlib.sha256(s.encode()).hexdigest())
    if len(ordered) < 3:
        raise ValueError('Need at least three sectors for sector-held-out train/valid/test splits')
    mapping = {ordered[0]: 'test', ordered[1]: 'valid'}
    mapping.update({s: 'train' for s in ordered[2:]})
    return mapping


def build(companies, out_dir, plumbing_only=False, enabled_path=source_registry.ENABLED_FILE):
    """companies: [(companyfacts_dict, {company_key, sector, origin})]."""
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError('Refusing to overwrite existing output directory')
    split_of = assign_sector_splits([m['sector'] for _, m in companies])
    pairs = []
    for facts, meta in companies:
        meta = dict(meta)
        meta['rights_status'] = source_registry.effective_rights(SOURCE_ID, enabled_path) if meta['origin'] == 'sec_edgar' else 'synthetic_fixture'
        pairs += [(dict(t, split=split_of[meta['sector']]), k) for t, k in xbrl_tasks.build_company_tasks(facts, meta)]
    real = [t for t, _ in pairs if t['origin'] == 'sec_edgar']
    approved = [t for t in real if t['rights_status'] == 'public_training_approved']
    validated = None
    check_rows = [dict(t, rights_status='public_training_approved') if (plumbing_only and t['origin'] != 'sec_edgar') else t for t, _ in pairs]
    eligible = [r for r in check_rows if r['rights_status'] == 'public_training_approved']
    if eligible:
        validated = validate_splits(eligible)
    ids = [k['case_id'] for _, k in pairs]
    assert len(ids) == len(set(ids)), 'duplicate case ids'
    out_dir.mkdir(parents=True)
    task_path, key_path = out_dir / 'tasks.jsonl', out_dir / 'keys.jsonl'
    task_path.write_text(''.join(json.dumps(t, sort_keys=True) + '\n' for t, _ in pairs))
    key_path.write_text(''.join(json.dumps(k, sort_keys=True) + '\n' for _, k in pairs))
    os.chmod(key_path, 0o600)
    real_companies = {t['company_key'] for t in approved}
    real_families = {f for t in approved for f in t['evidence_family_ids']}
    real_sectors = {t['sector'] for t in approved}
    manifest = {
        'contract': 'c1-public-task-manifest-v1', 'plumbing_only': plumbing_only,
        'counts_by_environment': dict(sorted(Counter(t['environment'] for t, _ in pairs).items())),
        'counts_by_sector': dict(sorted(Counter(t['sector'] for t, _ in pairs).items())),
        'counts_by_split': dict(sorted(Counter(t['split'] for t, _ in pairs).items())),
        'counts_by_environment_and_split': {e: dict(Counter(t['split'] for t, _ in pairs if t['environment'] == e)) for e in sorted({t['environment'] for t, _ in pairs})},
        'origins': dict(Counter(t['origin'] for t, _ in pairs)),
        'tasks_sha256': hashlib.sha256(task_path.read_bytes()).hexdigest(), 'keys_sha256': hashlib.sha256(key_path.read_bytes()).hexdigest(),
        'split_validation': validated,
        'coverage_vs_gate': {
            'gate': GATE, 'real_rights_approved': {'companies': len(real_companies), 'evidence_families': len(real_families), 'sectors': len(real_sectors)},
            'shortfall': {'companies': max(0, GATE['companies'] - len(real_companies)), 'evidence_families': max(0, GATE['evidence_families'] - len(real_families)),
                          'sectors': max(0, GATE['sectors'] - len(real_sectors))},
            'gate_met': len(real_companies) >= 20 and len(real_families) >= 50 and len(real_sectors) >= 3,
            'note': 'Only SEC-origin companies whose source is human-enabled AND rights-approved count. Synthetic fixtures count as zero.'},
        'limitations': ['Keys are arithmetic/reported facts, not independently adjudicated gold', 'E3 scenarios and E6 sections are unsupported (zero reward)',
                        'Not a memo-writing corpus; does not satisfy MEMO_GOLD_CORPUS reviewer requirements']}
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    return manifest


def load_fixtures(fixture_dir=None):
    d = Path(fixture_dir or Path(__file__).with_name('fixtures'))
    return [(json.loads((d / (m['company_key'] + '.companyfacts.json')).read_text()), m) for m in json.loads((d / 'index.json').read_text())]
