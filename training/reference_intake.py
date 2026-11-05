"""Private reference lineage and review preparation, without assigning gold labels.

New source-use permission and historical evaluation reservations are independent.
Exact source declarations are evidence; filename substrings/company aliases are
never used to infer a company or invent an evaluation split.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import unicodedata

from training.private_storage import private_path

ROOT = Path(__file__).resolve().parents[1]
MAX_JSON = 8 * 1024 * 1024
MAX_SOURCE = 128 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(path):
    path = Path(path)
    if path.is_symlink() or not 0 < path.stat().st_size <= MAX_JSON:
        raise ValueError('Reference metadata must be bounded regular files')
    return json.loads(path.read_bytes())


def _name(value):
    # Compare complete declared basenames, never company-name substrings.
    return unicodedata.normalize('NFKC', value.replace('\\', '/').rsplit('/', 1)[-1]).strip().casefold()


def prior_reservations(archive_manifest):
    """Read only verified original-source declarations in an imported gold tree."""
    manifest = _json(archive_manifest)
    archive = Path(archive_manifest).resolve().parent
    files = manifest.get('files')
    if not isinstance(files, dict):
        raise ValueError('Archive inventory is missing file hashes')
    reservations = []
    for relative, entry in files.items():
        parts = Path(relative).parts
        # Existing private acceptance gold is reserved, even when not adjudicated.
        # No declaration is inferred from arbitrary prose or an answer-key value.
        if 'gold' not in parts or parts[-1] != 'facts.json':
            continue
        path = (archive / relative).resolve()
        if not path.is_relative_to(archive) or path.is_symlink():
            raise ValueError('Archived source declaration escaped its approved root')
        if not 0 < path.stat().st_size <= MAX_JSON:
            raise ValueError('Archived source declaration exceeds metadata bounds')
        raw = path.read_bytes()
        if len(raw) > MAX_JSON or sha(raw) != entry.get('sha256'):
            raise ValueError('Archived source declaration no longer matches import receipt')
        facts = json.loads(raw)
        sources = facts.get('sources')
        if not isinstance(sources, dict):
            continue
        family = sha(str(Path(relative).parent.as_posix()).encode())
        for value in sources.values():
            if isinstance(value, dict) and isinstance(value.get('file'), str):
                reservations.append({'family_id': family,
                    'declared_filename': _name(value['file']),
                    'declaration_path': relative,
                    'declaration_sha256': entry['sha256'],
                    'reservation': 'historical_acceptance_gold'})
    return reservations, files


def classify_sources(sources, reservations, archived_files):
    """Return metadata only. Unmatched sources remain unassigned, not test-only."""
    rows = []
    for source in sources:
        source_name = _name(source['original_name'])
        exact = [relative for relative, record in archived_files.items()
                 if record.get('sha256') == source['sha256']]
        names = {source_name, *(_name(relative) for relative in exact)}
        matches = [item for item in reservations if item['declared_filename'] in names]
        families = sorted({item['family_id'] for item in matches})
        reserved = bool(matches)
        status = ('reserved_holdout_family' if len(families) == 1 else
                  'conflicting_historical_families' if families else 'unadjudicated_reference')
        rows.append({'source_id': source['source_id'], 'source_sha256': source['sha256'],
            'format': source['format'], 'size_bytes': source['size_bytes'],
            'source_family_ids': families, 'family_status': status,
            'exact_archived_byte_matches': exact,
            'historical_source_declarations': matches,
            'version_status': ('exact_archived_bytes' if exact else
                'historical_declaration_version_unresolved' if reserved else 'new_version_unassigned'),
            'split': 'test' if reserved else 'unassigned',
            'source_use_permission': 'private_training_approved',
            'answer_adjudication': 'not_performed',
            'weight_update_eligible': False,
            'training_candidate_eligible_after_review': not reserved,
            'next_action': ('preserve_for_frozen_evaluation_only' if reserved else
                            'resolve_company_family_then_generate_local_bound_targets')})
    return rows


def _write(path, value, *, jsonl=False):
    raw = (''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in value) if jsonl
           else json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)


def prepare_reference_review(reference_manifest, archive_manifest, output, *, private_root,
                             archive_root, source_use_approval_id):
    """Create an immutable private family ledger and actionable review packet.

    The approval ID records the actual operator/user source-use authorization;
    it never supplies reviewer identities, answer approvals or redistribution.
    """
    if not isinstance(source_use_approval_id, str) or not source_use_approval_id.strip():
        raise ValueError('Explicit current source-use approval reference is required')
    reference_manifest = private_path(reference_manifest, root=private_root, repo_root=ROOT)
    archive_manifest = private_path(archive_manifest, root=archive_root, repo_root=ROOT)
    output = private_path(output, root=private_root, repo_root=ROOT)
    if output.exists():
        raise ValueError('Review packets are immutable; use a new output directory')
    reference = _json(reference_manifest)
    sources = reference.get('sources')
    if not isinstance(sources, list) or not sources or len(sources) > 100:
        raise ValueError('Bounded reference source inventory is required')
    seen = set()
    for source in sources:
        if not isinstance(source, dict) or source.get('source_id') in seen:
            raise ValueError('Duplicate or invalid reference source identity')
        seen.add(source['source_id'])
        path = private_path(source['private_path'], root=private_root, repo_root=ROOT)
        if path.is_symlink() or not 0 < path.stat().st_size <= MAX_SOURCE:
            raise ValueError('Private source is not a bounded regular file')
        raw = path.read_bytes()
        if len(raw) != source['size_bytes'] or sha(raw) != source['sha256']:
            raise ValueError('Private original changed after import')
    reservations, archived = prior_reservations(archive_manifest)
    ledger = classify_sources(sources, reservations, archived)
    requests = []
    for row in ledger:
        heldout = row['split'] == 'test'
        requests.append({'request_id': 'review-' + row['source_sha256'][:24],
            'source_id': row['source_id'], 'source_sha256': row['source_sha256'],
            'source_family_ids': row['source_family_ids'], 'split': row['split'],
            'purpose': 'holdout_version_and_evaluation_review' if heldout else 'local_training_target_preparation',
            'required_actions': (['verify_original_version', 'retain_frozen_evaluation_reservation',
                                  'do_not_generate_training_derivatives'] if heldout else
                                 ['resolve_company_and_document_family', 'freeze_independent_evaluation_families',
                                  'generate_local_model_targets_with_exact_source_spans',
                                  'validate_runtime_schema_numbers_and_bindings',
                                  'obtain_independent_target_adjudication']),
            'target_status': 'not_generated', 'review_status': 'pending',
            'source_use_approval_id': source_use_approval_id,
            'weights_updated': False})
    summary = {'contract': 'private-reference-training-preparation-v1',
        'reference_manifest_sha256': sha(reference_manifest.read_bytes()),
        'archive_manifest_sha256': sha(archive_manifest.read_bytes()),
        'source_use_authorized': True, 'source_use_approval_id': source_use_approval_id,
        'source_permission_is_not_target_adjudication': True,
        'source_count': len(ledger), 'family_status_counts': dict(Counter(row['family_status'] for row in ledger)),
        'exact_archived_byte_source_count': sum(bool(row['exact_archived_byte_matches']) for row in ledger),
        'historically_declared_source_count': sum(bool(row['historical_source_declarations']) for row in ledger),
        'reserved_family_count': len({key for row in ledger for key in row['source_family_ids']}),
        'new_unassigned_source_count': sum(row['split'] == 'unassigned' for row in ledger),
        'trainable_reviewed_targets': 0, 'targets_generated': 0, 'weights_updated': False,
        'production_routing_changed': False, 'release_qualified': False}
    missing, parent = [], output
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir(mode=0o700)
    _write(output / 'source-family-ledger.json', ledger)
    _write(output / 'review-requests.jsonl', requests, jsonl=True)
    _write(output / 'summary.json', summary)
    return summary
