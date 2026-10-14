"""Network-free read-only PDF/PPTX indexing in one scoped private directory.

Run through delivery.isolation.run_private with only this job and immutable code
readable. The worker never opens a store/API/model or prints extracted contents.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from agents.research.document_evidence_manifest import build_document_manifest, attach_document_emf, attach_document_visual_text, canonical
from delivery.storage import MAX_FILE_BYTES, read_source_bytes


def _retain(path, content):
    if len(content) > MAX_FILE_BYTES:
        raise ValueError('Private document manifest exceeds retained size limit')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if read_source_bytes(path) != content:
            raise ValueError('Immutable private document evidence changed')
        return
    with os.fdopen(descriptor, 'wb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def run(root):
    root = Path(root).absolute()
    if root.is_symlink() or root.resolve() != root or not root.is_dir():
        raise ValueError('Private document job directory is unsafe or linked')
    if root.stat().st_mode & 0o077:
        raise ValueError('Private document job directory must be mode 0700')
    request = json.loads(read_source_bytes(root / 'request.json'))
    if (not isinstance(request, dict) or set(request) not in ({'source', 'binding'},
            {'source','binding','media_text_profile'}) or
            request['source'] not in {'source.pdf', 'source.pptx'}):
        raise ValueError('Exact private document request required')
    fmt = request['source'].split('.')[-1]
    profile=request.get('media_text_profile')
    if 'media_text_profile' in request and (fmt != 'pptx' or profile not in
            {'native-emf-literals-v1','native-pptx-visual-text-v1'}):
        raise ValueError('Explicit native EMF presentation profile required')
    binding = request['binding']
    if (not isinstance(binding, dict) or set(binding) !=
            {'tenant_id', 'deal_id', 'document_id', 'source_sha256', 'format'} or
            binding['format'] != fmt):
        raise ValueError('Exact private document binding required')
    raw = read_source_bytes(root / request['source'])
    if hashlib.sha256(raw).hexdigest() != binding['source_sha256']:
        raise ValueError('Original private document bytes changed')
    manifest = build_document_manifest(raw, fmt, **{key:binding[key]
        for key in ('tenant_id', 'deal_id', 'document_id')})
    if manifest['binding'] != binding:
        raise ValueError('Private document scope changed')
    body = canonical(manifest).encode()
    _retain(root / 'document_evidence_manifest.json', body)
    receipt = {'contract':'private-document-manifest-receipt-v1', 'binding':binding,
        'manifest_sha256':hashlib.sha256(body).hexdigest(),
        'manifest_digest':manifest['manifest_digest'], 'counts':manifest['counts'],
        'semantic_status':'unassessed', 'financial_validation':'not_established',
        'release_status':'diagnostic_only_no_release'}
    _retain(root / 'document_manifest_receipt.json', canonical(receipt).encode())
    if profile is not None:
        combined=profile=='native-pptx-visual-text-v1'
        derived=(attach_document_visual_text if combined else attach_document_emf)(manifest,raw,expected_binding=binding)
        derived_body=canonical(derived).encode()
        stem='visual_text' if combined else 'emf'
        _retain(root / ('document_evidence_manifest_'+stem+'.json'),derived_body)
        parser=Path(__file__).resolve().parents[1]/'agents/research/emf_text.py'
        emf_receipt={'contract':'private-native-emf-manifest-receipt-v1','binding':binding,
            'manifest_sha256':hashlib.sha256(derived_body).hexdigest(),
            'manifest_digest':derived['manifest_digest'],'counts':derived['counts'],
            'media_text_profile':profile,'native_manifest_sha256':hashlib.sha256(body).hexdigest(),
            'parser_source_sha256':hashlib.sha256(parser.read_bytes()).hexdigest(),
            'manifest_source_sha256':hashlib.sha256((parser.parent/'document_evidence_manifest.py').read_bytes()).hexdigest(),
            'text_extraction':'native_binary_literal_records','ocr':'not_performed',
            'semantic_status':'unassessed','financial_validation':'not_established',
            'required_network_access':'denied',
            'release_status':'diagnostic_only_no_release'}
        _retain(root/('document_manifest_'+stem+'_receipt.json'),canonical(emf_receipt).encode())
    if read_source_bytes(root / request['source']) != raw:
        raise ValueError('Private document parser changed original bytes')


if __name__ == '__main__':
    run(Path.cwd())
