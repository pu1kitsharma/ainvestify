"""Exact-file draft receipts adapted from Claude Code's generic implementation.

Upstream must replay each projected page. This binds exported bytes and metadata;
it does not inspect content, qualify the renderer or grant any approval.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
import re

from agents.inference.model_authorship import digest
from agents.research.document_generation import GenerationError, canonical_digest


CONTRACT = 'evidence-document-export-v1'
FORMATS = {'intro_deck': {'pptx', 'pdf'}, 'pitch_deck': {'pptx', 'pdf'},
           'investment_memo': {'docx', 'pdf'}}


def _hash(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise GenerationError('exact_document_export_digest_required')
    return value


def freeze_draft_export(inventory_revision, kind, plan_response, page_receipts,
                        renderer_sections, artifacts):
    """Bind exact replay projections to matching editable/PDF bytes, still drafts."""
    _hash(inventory_revision)
    if kind not in FORMATS:
        raise GenerationError('exact_document_export_kind_required')
    if (not isinstance(plan_response, dict) or not isinstance(plan_response.get('raw_response'), str) or
            not plan_response['raw_response'] or not isinstance(plan_response.get('id'), str) or
            not plan_response['id'] or _hash(plan_response.get('response_hash')) != digest(plan_response['raw_response'])):
        raise GenerationError('exact_document_export_plan_raw_hash_changed')
    if (not isinstance(page_receipts, list) or not 1 <= len(page_receipts) <= 40 or
            not isinstance(renderer_sections, list) or len(renderer_sections) != len(page_receipts)):
        raise GenerationError('exact_document_export_page_receipts_and_sections_required')
    seen, receipt_pages, reviewed = {plan_response['id']}, [], True
    for number, receipt in enumerate(page_receipts, 1):
        if (not isinstance(receipt, dict) or receipt.get('page_id') != f'P{number}' or
                not isinstance(receipt.get('author_response_id'), str) or not receipt['author_response_id']):
            raise GenerationError('exact_document_export_author_receipt_required')
        _hash(receipt.get('author_response_hash'))
        ids = [receipt['author_response_id']]
        rid, rhash = receipt.get('review_response_id'), receipt.get('review_response_hash')
        if (rid is None) != (rhash is None):
            raise GenerationError('exact_document_export_incomplete_review_receipt')
        if rid is not None:
            if not isinstance(rid, str) or not rid:
                raise GenerationError('exact_document_export_review_id_required')
            _hash(rhash)
            ids.append(rid)
        else:
            reviewed = False
        if len(set(ids)) != len(ids) or set(ids) & seen:
            raise GenerationError('exact_document_export_duplicate_model_response')
        seen.update(ids)
        receipt_pages.append(deepcopy(receipt))
    if not isinstance(artifacts, list):
        raise GenerationError('exact_document_export_artifacts_required')
    files = []
    for item in artifacts:
        if (not isinstance(item, dict) or set(item) != {'format', 'content'} or
                not isinstance(item['content'], bytes) or not item['content']):
            raise GenerationError('exact_document_export_bytes_required')
        files.append({'format': item['format'], 'sha256': hashlib.sha256(item['content']).hexdigest(),
                      'byte_count': len(item['content'])})
    formats = [item['format'] for item in files]
    if len(set(formats)) != len(formats) or set(formats) != FORMATS[kind]:
        raise GenerationError('exact_document_export_matching_editable_pdf_required')
    body = {'contract': CONTRACT, 'kind': kind, 'inventory_revision': inventory_revision,
        'sections_digest': canonical_digest(renderer_sections), 'section_count': len(renderer_sections),
        'plan_response_id': plan_response['id'], 'plan_response_hash': plan_response['response_hash'],
        'model_response_hash_scheme': 'legacy_json_record_digest', 'page_receipts': receipt_pages,
        'files': sorted(files, key=lambda item: item['format']),
        'content_review': 'recorded_unqualified' if reviewed else 'not_run_or_partial',
        'financial_validation': 'not_established', 'regulatory_approval': 'not_established',
        'investor_approval': 'not_established', 'release_status': 'draft_only'}
    return {**body, 'export_revision': canonical_digest(body)}
