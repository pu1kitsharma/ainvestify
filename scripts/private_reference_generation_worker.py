"""Bounded local document generation/export, invoked through private isolation."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

from agents.research import document_generation as generation
from delivery import document_generation_stage as stage
from delivery.document_generation_export import freeze_draft_export
from delivery.rendering import render_evidence_document


def installed_digest(name):
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=8) as response:
        matches = [item for item in json.load(response).get('models', []) if item.get('name') == name]
    if len(matches) != 1 or re.fullmatch(r'[0-9a-f]{64}', matches[0].get('digest', '')) is None:
        raise ValueError('Exact installed local model is unavailable')
    return matches[0]['digest']


def _retain_bytes(path, content):
    if path.exists():
        if path.is_symlink() or path.read_bytes() != content:
            raise ValueError('Frozen draft export bytes changed')
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(content); output.flush(); os.fsync(output.fileno())


def export_prefix(root):
    """Project complete author records, preserve each exact local review status.

    An incomplete/blocked run exports only its contiguous authored prefix as an
    explicitly partial diagnostic, never an approved investor document.
    """
    body, request, attempts = stage._load_run(root)
    if not attempts:
        return {'state': 'blocked', 'reason': 'no_recorded_document_plan'}
    source_prefix_count = body.get('source_map_count', 0) * (
        2 if body.get('qualification_context_profile') is not None else 1)
    if body.get('planning_schema_profile') in {'indexed-physical-plan-v4','selected-physical-plan-v5'}:
        source_prefix_count = body['source_page_read_count']
        if len(attempts) <= source_prefix_count:
            return {'state': 'blocked', 'reason': 'source_index_has_no_recorded_document_plan',
                    'completed_source_reads': len(attempts)}
    if (body.get('catalog_encoding') == generation.CATALOG_ENCODING_V3
            and len(attempts) <= source_prefix_count):
        progress = stage.replay_document_generation(root,
            tenant_id=body['inventory']['tenant_id'], deal_id=body['inventory']['deal_id'])
        return {'state': 'blocked', 'reason': 'source_map_prefix_has_no_recorded_document_plan',
                'generation_state': progress['state']}
    context = stage._qualification_context_profile(body)
    if context:
        context['reviewer_pin'] = body['reviewer_pin']
    request, plan_row, cursor = generation.document_plan_context(request, body['inventory'], attempts,
        source_map_token_budgets=body.get('source_map_token_budgets'),
        source_map_profiles=body.get('source_map_profiles'), **context)
    plan = generation.replay_document_plan(request, plan_row, body['inventory'])
    sections, receipts = [], []
    for planned in plan['pages']:
        if cursor >= len(attempts):break
        page_request = generation._frozen_page_request_from_page(request, plan_row, planned, body['inventory'],
            **({'material_context_profile':body['material_context_profile']} if 'material_context_profile' in body else {}))
        if body.get('document_page_repair_profile') is not None:
            sequence = generation.document_page_sequence_context(page_request, attempts, cursor,
                body['reviewer_pin'], document_page_repair_profile=body['document_page_repair_profile'])
            authored = sequence.get('author_row')
            if authored is None:
                break
            effective_request = sequence['author_request']
            generation.replay_document_page(effective_request, authored)
            sections.append(generation.renderable_document_page(effective_request, authored))
            receipt = {'page_id':planned['page_id'], 'author_response_id':authored['id'],
                'author_response_hash':authored['response_hash'],
                'author_request_digest':generation.canonical_digest(generation.request_json(effective_request)),
                'review_status':'not_run'}
            reviewed = sequence.get('review_row')
            if reviewed is not None:
                review_request = sequence['review_request']
                review = generation.replay_document_review(review_request, reviewed)
                receipt.update(review_response_id=reviewed['id'], review_response_hash=reviewed['response_hash'],
                    review_request_digest=generation.canonical_digest(generation.request_json(review_request)),
                    review_status=review['verdict'])
            if sequence.get('repair_receipt') is not None:
                receipt['repair_receipt'] = sequence['repair_receipt']
            receipts.append(receipt)
            cursor = sequence['next_cursor']
            if receipt['review_status'] != 'pass' or sequence['state'] == 'blocked':
                break
            continue
        authored = attempts[cursor]
        generation.replay_document_page(page_request, authored)
        sections.append(generation.renderable_document_page(page_request, authored))
        receipt = {'page_id': planned['page_id'], 'author_response_id': authored['id'],
            'author_response_hash': authored['response_hash'],
            'author_request_digest': generation.canonical_digest(generation.request_json(page_request)),
            'review_status': 'not_run'}
        cursor += 1
        blocked = False
        if cursor < len(attempts):
            review_request = generation.frozen_page_review_request(page_request, authored, body['reviewer_pin'],
                **({'material_context_profile':body['material_context_profile']} if 'material_context_profile' in body else {}))
            review = generation.replay_document_review(review_request, attempts[cursor])
            receipt.update(review_response_id=attempts[cursor]['id'],
                review_response_hash=attempts[cursor]['response_hash'],
                review_request_digest=generation.canonical_digest(generation.request_json(review_request)),
                review_status=review['verdict'])
            cursor += 1
            blocked = review['verdict'] != 'pass'
        receipts.append(receipt)
        if blocked:break
    if not sections:
        return {'state': 'blocked', 'reason': 'no_complete_model_authored_page'}
    kind = body['kind']; native = 'docx' if kind == 'investment_memo' else 'pptx'
    renderer_kind = 'investment_memorandum' if kind == 'investment_memo' else kind
    # Title is neutral draft metadata. Every company-specific page title is model-authored.
    title = 'Investor materials draft'
    artifacts = [{'format': fmt, 'content': render_evidence_document(title, sections,
        kind=renderer_kind, format=fmt)} for fmt in (native, 'pdf')]
    byte_receipt = freeze_draft_export(body['inventory']['inventory_revision'], kind, plan_row,
                                receipts, sections, artifacts)
    progress = stage.replay_document_generation(root,
        tenant_id=body['inventory']['tenant_id'], deal_id=body['inventory']['deal_id'])
    receipt = dict(contract='private-reference-export-checkpoint-v1', byte_receipt=byte_receipt,
        generation_state=progress['state'], planned_pages=len(plan['pages']),
        authored_pages=len(sections), complete_draft=progress['state'] == 'draft_complete',
        content_review='blocked' if any(r['review_status'] == 'revise' for r in receipts)
            else 'local_model_only_unqualified' if all(r['review_status'] == 'pass' for r in receipts)
            else 'not_run_or_partial', financial_validation='not_established',
        regulatory_approval='not_established', investor_approval='not_established', release_status='draft_only')
    if body.get('catalog_encoding') == generation.CATALOG_ENCODING_V3:
        receipt['source_map_status'] = 'proposed_unreviewed'
        receipt['source_map_receipts'] = [{'response_id': row['id'], 'response_hash': row['response_hash'],
            'request_digest': generation.canonical_digest([row['task'], row['instruction'], row['input'], row['schema']])}
            for row in attempts[:body['source_map_count']]]
        receipt['plan_request_digest'] = generation.canonical_digest(generation.request_json(request))
        if body.get('qualification_context_profile') is not None:
            receipt['qualification_context_profile'] = body['qualification_context_profile']
            receipt['source_coverage_reviewer_pin'] = body.get('source_coverage_reviewer_pin', body['reviewer_pin'])
            receipt['page_reviewer_pin'] = body['reviewer_pin']
            receipt['source_map_status'] = 'local_model_proposals_with_recorded_coverage_reviews'
            count = body['source_map_count']
            receipt['source_coverage_review_receipts'] = [{'response_id': row['id'],
                'response_hash': row['response_hash'],
                'request_digest': generation.canonical_digest([row['task'],row['instruction'],row['input'],row['schema']])}
                for row in attempts[count:count*2]]
    if body.get('catalog_encoding') in {generation.CATALOG_ENCODING_V4,generation.CATALOG_ENCODING_V5,generation.CATALOG_ENCODING_V6}:
        receipt.update(
            qualification_context_profile=body['qualification_context_profile'],
            source_map_status='not_performed', source_coverage_review_status='not_performed',
            planning_input_scope='complete_available_original_literals',
            source_reading_status='available_literals_supplied_to_local_planner_unassessed',
            literal_catalog_digest=generation.canonical_digest(request[2]['catalog']),
            source_topology_digest=body['inventory']['source_map_topology_digest'],
            page_reviewer_pin=body['reviewer_pin'])
        if 'planner_pin' in body:
            receipt.update(planner_pin=body['planner_pin'],page_author_pin=body['author_pin'])
        if 'planning_schema_profile' in body:
            receipt['planning_schema_profile'] = body['planning_schema_profile']
        if 'planning_context_profile' in body:
            receipt['planning_context_profile'] = body['planning_context_profile']
        for name in ('source_context_profile','source_index_encoding','material_context_profile','source_reader_pin','planning_assignment_profile','document_page_repair_profile'):
            if name in body:receipt[name] = body[name]
        if body.get('planning_schema_profile') in {'indexed-physical-plan-v4','selected-physical-plan-v5'}:
            receipt.update(planning_input_scope='recorded_local_source_page_index_and_native_table_navigation',
                source_reading_status='all_available_original_pages_exposed_locally_index_unqualified',
                source_page_read_count=body['source_page_read_count'],
                source_page_read_receipts=[{'response_id': row['id'], 'response_hash': row['response_hash'],
                    'request_digest': generation.canonical_digest([row['task'],row['instruction'],row['input'],row['schema']])}
                    for row in attempts[:body['source_page_read_count']]])
            if body['planning_schema_profile'] == 'selected-physical-plan-v5':
                receipt.update(planning_input_scope='recorded_local_source_selections_complete_original_focus_units_and_native_table_navigation')
    # New receipt includes terminal scope; rehash it rather than presenting the
    # narrower generic byte receipt as a release manifest.
    receipt['diagnostic_digest'] = generation.canonical_digest(receipt)
    folder = root / ('draft_prefix_%02d_%s' % (len(sections), receipt['diagnostic_digest'][:12]))
    folder.mkdir(mode=0o700, exist_ok=True)
    for item in artifacts:_retain_bytes(folder / ('draft.' + item['format']), item['content'])
    _retain_bytes(folder / 'export_receipt.json', json.dumps(receipt, sort_keys=True,
        ensure_ascii=False, allow_nan=False).encode())
    return {'state': 'draft_exported', 'authored_pages': len(sections),
        'planned_pages': len(plan['pages']), 'generation_state': progress['state'],
        'content_review': receipt['content_review'], 'release_status': 'draft_only',
        'investor_approval': 'not_established', 'diagnostic_path': str(folder)}


def main(root, phase):
    root = stage._no_links(root)
    body, _, _ = stage._load_run(root)
    scope = {'tenant_id': body['inventory']['tenant_id'], 'deal_id': body['inventory']['deal_id']}
    if phase == 'advance':
        result = stage.advance_document_generation(root, **scope, installed_digest=installed_digest)
    elif phase == 'verify':result = stage.replay_document_generation(root, **scope)
    elif phase == 'export':result = export_prefix(root)
    else:raise ValueError('Unknown private reference generation phase')
    safe = {key: result[key] for key in ('state','phase','page_id','completed_pages','recorded_model_calls',
        'completed_source_maps','completed_source_reviews','source_map_count','source_map_index','source_page_id',
        'completed_source_page_reads','source_page_read_index','source_page_read_id',
        'reason','authored_pages','planned_pages','generation_state','content_review','release_status',
        'investor_approval','diagnostic_path') if key in result}
    print(json.dumps(safe, sort_keys=True))


if __name__ == '__main__':main(Path(sys.argv[1]), sys.argv[2])
