"""Fail-closed public corpus split checks; no source collection or private export."""
import json

def validate_splits(rows, private_holdout_companies=()):
    if not rows:
        raise ValueError('Empty corpus')
    holdouts = {x.strip().casefold() for x in private_holdout_companies}
    seen = {field: {} for field in ('company_key', 'sector', 'evidence_family_ids', 'source_sha256')}
    cases, counts = set(), dict.fromkeys(('train', 'valid', 'test'), 0)
    for row in rows:
        split = row.get('split')
        if split not in counts or not row.get('case_id') or row['case_id'] in cases:
            raise ValueError('Invalid split or duplicate/missing case identity')
        cases.add(row['case_id'])
        counts[split] += 1
        if row.get('rights_status') != 'public_training_approved' or row.get('private') is not False:
            raise ValueError('Only explicitly rights-approved public rows are eligible')
        company = row.get('company_key')
        if not isinstance(company, str) or not company.strip():
            raise ValueError('Missing company')
        if company.strip().casefold() in holdouts:
            raise ValueError('Private holdout company excluded from public corpus')
        for field, registry in seen.items():
            values = row.get(field)
            if field not in ('evidence_family_ids', 'source_sha256'):
                values = [values]
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError('Missing split lineage: ' + field)
            for raw in values:
                value = raw.strip().casefold()
                if field == 'source_sha256' and (len(value) != 64 or any(c not in '0123456789abcdef' for c in value)):
                    raise ValueError('Invalid source SHA256')
                if value in registry and registry[value] != split:
                    raise ValueError('Cross-split leakage: ' + field)
                registry[value] = split
    if not all(counts.values()):
        raise ValueError('Train, valid and test rows are required')
    return {'contract': 'agentic-public-splits-v1', 'counts': counts,
            'companies': len(seen['company_key']), 'sectors': len(seen['sector']),
            'evidence_families': len(seen['evidence_family_ids']),
            'coverage_thresholds_met': len(seen['company_key']) >= 20 and len(seen['sector']) >= 3 and len(seen['evidence_family_ids']) >= 50,
            'release_qualified': False}


# ---------------------------------------------------------------------------
# Leave-one-deal-out, private upweighting and private adapter storage policy.
# Pure policy code: no model, no network, no file contents are read.
# ---------------------------------------------------------------------------
import math
from pathlib import Path

PRIVATE_SHARE_CAP = 0.10
# Directories that are git-ignored in this repository and may hold adapters
# trained on (or influenced by) private deal data. Relative to the repo root.
PRIVATE_ADAPTER_ROOTS = ('runtime_qualification', 'evals/agentic_banker/private')
PUBLIC_ADAPTER_ROOT = 'models/adapters'


def _norm(deal):
    if not isinstance(deal, str) or not deal.strip():
        raise ValueError('Deal identity must be a nonempty string')
    return deal.strip().casefold()


def split_training_rows(public_rows, private_rows, held_out_deals=()):
    """Leave-one-deal-out: rows of a held-out deal never reach training.

    Rows need a `deal_id` (public rows may fall back to `company_key`). Returns
    (train_public, train_private, excluded_private, trained_deals). Public rows of
    a held-out deal are an error, not silently dropped: the caller must fix the
    corpus rather than lose coverage unnoticed.
    """
    held = {_norm(d) for d in held_out_deals}
    train_public = []
    for row in public_rows:
        if row.get('private') is not False:
            raise ValueError('Public row marked private')
        deal = _norm(row.get('deal_id') or row.get('company_key'))
        if deal in held:
            raise ValueError('Held-out deal present in public training rows: ' + deal)
        train_public.append(row)
    train_private, excluded = [], []
    for row in private_rows:
        if row.get('private') is not True:
            raise ValueError('Private row must be explicitly marked private')
        (excluded if _norm(row.get('deal_id')) in held else train_private).append(row)
    trained = {_norm(r.get('deal_id') or r.get('company_key')) for r in train_public + train_private}
    return train_public, train_private, excluded, sorted(trained)


def assert_deals_unseen(trained_deals, scored_deals):
    """A deal is never scored by an adapter that trained on it."""
    overlap = {_norm(d) for d in trained_deals} & {_norm(d) for d in scored_deals}
    if overlap:
        raise ValueError('Adapter trained on deal(s) it would be scored on: ' + ', '.join(sorted(overlap)))


def mix_private_examples(public_examples, private_examples, upweight=3, cap=PRIVATE_SHARE_CAP):
    """Upweight private examples by repetition, never exceeding `cap` of the mix.

    Returns (mixed, stats). Public examples keep their order; private ones are
    repeated up to `upweight` times, then truncated so that private/total <= cap.
    The cap wins over the upweight (a tiny public set may admit zero private rows).
    """
    if type(upweight) is not int or not 1 <= upweight <= 20:
        raise ValueError('upweight must be an integer in [1, 20]')
    if not isinstance(cap, (int, float)) or not 0 <= cap <= PRIVATE_SHARE_CAP:
        raise ValueError('private cap may not exceed %.2f' % PRIVATE_SHARE_CAP)
    n = len(public_examples)
    allowed = math.floor(cap * n / (1 - cap)) if cap < 1 else 0
    wanted = [dict(e) for e in private_examples for _ in range(upweight)]
    # Round-robin the repeats so truncation keeps distinct examples before copies.
    ordered = sorted(range(len(wanted)), key=lambda i: (i % upweight, i))
    chosen = [wanted[i] for i in ordered[:allowed]]
    mixed = list(public_examples) + chosen
    share = len(chosen) / len(mixed) if mixed else 0.0
    if share > cap + 1e-12:
        raise ValueError('Internal error: private share exceeds cap')
    return mixed, {'public': n, 'private_available': len(private_examples), 'private_used': len(chosen),
                   'distinct_private_used': len({json.dumps(e, sort_keys=True) for e in chosen}),
                   'upweight': upweight, 'private_share': share, 'cap': cap}


def adapter_destination_ok(path, *, trained_on_private, repo_root):
    """Enforce where adapters may live. Returns the resolved path or raises.

    Private-trained adapters: only under an ignored private root, never under
    models/adapters (Git LFS). Public-only adapters may live in either.
    """
    root = Path(repo_root).resolve()
    target = Path(path).resolve()
    try:
        rel = target.relative_to(root)
    except ValueError:
        if trained_on_private:
            raise ValueError('Private-trained adapter must be inside the repository private roots')
        return target
    rel_text = rel.as_posix()
    in_public = rel_text == PUBLIC_ADAPTER_ROOT or rel_text.startswith(PUBLIC_ADAPTER_ROOT + '/')
    in_private = any(rel_text == r or rel_text.startswith(r + '/') for r in PRIVATE_ADAPTER_ROOTS)
    if trained_on_private and (in_public or not in_private):
        raise ValueError('Private-trained adapters may only be stored under ignored private paths: '
                         + ', '.join(PRIVATE_ADAPTER_ROOTS))
    return target
