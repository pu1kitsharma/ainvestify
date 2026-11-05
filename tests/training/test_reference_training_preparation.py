import hashlib
import json
import struct

import pytest

from training.reference_intake import classify_sources, prepare_reference_review
from training.runtime_qualification import checkpoint_inventory, resolve_precision
from training import qlora_train


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def test_declaration_and_bytes_preserve_holdouts_without_reserving_new_sources():
    sources = [{'source_id': 'one', 'original_name': 'Original company deck.pdf',
                'format': 'pdf', 'size_bytes': 3, 'sha256': 'a' * 64},
               {'source_id': 'two', 'original_name': 'Independent new source.pdf',
                'format': 'pdf', 'size_bytes': 3, 'sha256': 'b' * 64}]
    reservations = [{'family_id': 'family-a', 'declared_filename': 'original company deck.pdf',
                     'reservation': 'historical_acceptance_gold'}]
    rows = classify_sources(sources, reservations,
                            {'history/Original company deck.pdf': {'sha256': 'a' * 64}})
    assert rows[0]['split'] == 'test'
    assert rows[0]['version_status'] == 'exact_archived_bytes'
    assert not rows[0]['training_candidate_eligible_after_review']
    assert rows[1]['split'] == 'unassigned'
    assert rows[1]['family_status'] == 'unadjudicated_reference'
    assert rows[1]['training_candidate_eligible_after_review']
    assert not any(row['weight_update_eligible'] for row in rows)
    # A company word appearing in a filename does not establish lineage.
    sources[1]['original_name'] = 'New Original company source.pdf'
    assert classify_sources(sources, reservations, {})[1]['split'] == 'unassigned'


def test_private_preparation_records_permission_separately_and_is_immutable(tmp_path):
    private, archive = tmp_path / 'private', tmp_path / 'archive'
    private.mkdir()
    fact = archive / 'evals' / 'gold' / 'family-a' / 'facts.json'
    fact.parent.mkdir(parents=True)
    fact.write_text(json.dumps({'sources': {'deck': {'file': 'source.pdf'}},
                                'facts': ['do-not-copy-private-source-facts']}))
    archive_manifest = archive / 'import-manifest.json'
    archive_manifest.write_text(json.dumps({'files': {
        fact.relative_to(archive).as_posix(): {'sha256': _sha(fact.read_bytes())}}}))
    source = private / 'source.pdf'
    source.write_bytes(b'private-original-source-content')
    reference = private / 'import-manifest.json'
    reference.write_text(json.dumps({'sources': [{'source_id': 'source-01', 'original_name': source.name,
        'private_path': str(source), 'format': 'pdf', 'size_bytes': source.stat().st_size,
        'sha256': _sha(source.read_bytes())}]}))
    result = prepare_reference_review(reference, archive_manifest, private / 'packet',
        private_root=private, archive_root=archive, source_use_approval_id='actual-session-source-permission')
    assert result['source_use_authorized']
    assert result['reserved_family_count'] == 1
    assert result['trainable_reviewed_targets'] == 0
    request = json.loads((private / 'packet/review-requests.jsonl').read_text())
    assert request['target_status'] == 'not_generated' and request['review_status'] == 'pending'
    assert request['purpose'] == 'holdout_version_and_evaluation_review'
    emitted = ''.join(path.read_text() for path in (private / 'packet').iterdir())
    assert 'private-original-source-content' not in emitted
    assert 'do-not-copy-private-source-facts' not in emitted
    with pytest.raises(ValueError, match='immutable'):
        prepare_reference_review(reference, archive_manifest, private / 'packet',
            private_root=private, archive_root=archive, source_use_approval_id='actual-session-source-permission')
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed after import'):
        prepare_reference_review(reference, archive_manifest, private / 'other-packet',
            private_root=private, archive_root=archive, source_use_approval_id='actual-session-source-permission')


def test_packed_checkpoint_uses_headers_not_weight_allocation(tmp_path):
    (tmp_path / 'config.json').write_text(json.dumps({'model_type': 'synthetic',
        'quantization': {'bits': 4, 'group_size': 64}}))
    header = json.dumps({'layer.weight': {'dtype': 'U32', 'shape': [2, 4],
                                         'data_offsets': [0, 32]}}).encode()
    (tmp_path / 'model.safetensors').write_bytes(struct.pack('<Q', len(header)) + header + bytes(32))
    result = checkpoint_inventory(tmp_path)
    assert result['checkpoint_format'] == 'mlx_packed_affine'
    assert result['estimated_expanded_bf16_weight_bytes'] == 128
    assert result['packed_weight_tensors'] == 1
    assert not result['weight_data_loaded'] and not result['cuda_qlora_base_qualified']


def test_precision_handles_turing_and_never_claims_unsupported_bf16():
    assert resolve_precision('auto', bf16_supported=False) == 'fp16'
    assert resolve_precision('auto', bf16_supported=True) == 'bf16'
    with pytest.raises(ValueError, match='unsupported'):
        resolve_precision('bf16', bf16_supported=False)


def test_training_rejects_download_or_unconverted_mlx_before_importing_stack(tmp_path):
    with pytest.raises(ValueError, match='downloads are disabled'):
        qlora_train.run_training({'base_model': str(tmp_path / 'missing')}, tmp_path)
    (tmp_path / 'config.json').write_text(json.dumps({'quantization': {'bits': 4, 'group_size': 64}}))
    with pytest.raises(ValueError, match='Packed MLX'):
        qlora_train.run_training({'base_model': str(tmp_path)}, tmp_path)
