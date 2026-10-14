"""Use complete private document evidence for local, durable draft generation.

Reference documents are evidence, never instructions or automatic gold labels.
This diagnostic cannot create a room, release an artifact or change saved data.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from delivery import document_generation_stage as stage
from delivery.isolation import run_private
from scripts.private_reference_generation_worker import installed_digest

PROJECT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = PROJECT / 'runtime_qualification/private_acceptance'


def _private_path(path):
    path = stage._no_links(Path(path).absolute())
    if not path.is_relative_to(PRIVATE_ROOT) or path == PRIVATE_ROOT:
        raise ValueError('Use an ignored private diagnostic directory')
    return path


def _checked_manifest(path):
    path = _private_path(path)
    receipts = {'document_evidence_manifest.json':'document_manifest_receipt.json',
        'document_evidence_manifest_ocr.json':'document_manifest_ocr_receipt.json',
        'document_evidence_manifest_visual_text.json':'document_manifest_visual_text_receipt.json'}
    if path.name not in receipts:
        raise ValueError('Use an isolated original document manifest')
    manifest = stage._read(path)
    receipt = stage._read(path.parent / receipts[path.name])
    binding = manifest['binding']
    original = path.parent / ('source.' + binding['format'])
    if (receipt['binding'] != binding or receipt['manifest_sha256'] != hashlib.sha256(path.read_bytes()).hexdigest()
            or receipt['manifest_digest'] != manifest['manifest_digest']
            or original.is_symlink() or hashlib.sha256(original.read_bytes()).hexdigest() != binding['source_sha256']):
        raise ValueError('Private original/manifest/receipt bytes changed')
    if path.name == 'document_evidence_manifest_ocr.json':
        from agents.research.document_evidence_manifest import attach_document_ocr
        from delivery.document_ocr import replay_document_ocr
        native_path = path.parent / 'document_evidence_manifest.json'
        native, _ = _checked_manifest(native_path)
        ocr_root = _private_path(receipt['ocr_root'])
        ocr_receipt = stage._read(ocr_root / 'ocr_receipt.json')
        if (receipt['native_manifest_sha256'] != hashlib.sha256(native_path.read_bytes()).hexdigest()
                or receipt['ocr_receipt_sha256'] != hashlib.sha256((ocr_root / 'ocr_receipt.json').read_bytes()).hexdigest()
                or ocr_receipt['output_sha256'] != hashlib.sha256((ocr_root / 'ocr_result.json').read_bytes()).hexdigest()
                or ocr_receipt['request_sha256'] != hashlib.sha256((ocr_root / 'ocr_request.json').read_bytes()).hexdigest()):
            raise ValueError('Private OCR provenance changed')
        # Reconstruct from checked raw OCR and complete source/raster receipts.
        # A rewritten page projection/derived manifest is not its own proof.
        pages = replay_document_ocr(ocr_root)
        if pages['source_sha256'] != binding['source_sha256']:
            raise ValueError('Private OCR original source changed')
        keys = ('page','source_sha256','image_sha256','engine','coordinate_system','language_correction','observations')
        wrappers = [{key: row[key] for key in keys} for row in pages['pages']]
        if attach_document_ocr(native, wrappers, expected_binding=binding) != manifest:
            raise ValueError('Private OCR manifest is not an exact observation projection')
    if path.name == 'document_evidence_manifest_visual_text.json':
        from agents.research.document_evidence_manifest import attach_document_visual_text
        native_path = path.parent / 'document_evidence_manifest.json'
        native, _ = _checked_manifest(native_path)
        parser = PROJECT / 'agents/research/emf_text.py'
        parser_manifest = PROJECT / 'agents/research/document_evidence_manifest.py'
        if (binding['format'] != 'pptx' or
                receipt.get('media_text_profile') != 'native-pptx-visual-text-v1' or
                receipt.get('native_manifest_sha256') != hashlib.sha256(native_path.read_bytes()).hexdigest() or
                receipt.get('parser_source_sha256') != hashlib.sha256(parser.read_bytes()).hexdigest() or
                receipt.get('manifest_source_sha256') != hashlib.sha256(parser_manifest.read_bytes()).hexdigest()):
            raise ValueError('Private native visual text provenance changed')
        if attach_document_visual_text(native, original.read_bytes(), expected_binding=binding) != manifest:
            raise ValueError('Private native visual text is not an exact original observation projection')
    return manifest, {'manifest_path': str(path), 'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'original_path': str(original), 'original_sha256': binding['source_sha256']}


def _check_run_provenance(root):
    provenance = stage._read(root / 'source_provenance.json')
    body, _, _ = stage._load_run(root)
    if ([item.get('original_sha256') for item in provenance.get('sources', [])] !=
            [source['source_id'] for source in body['inventory']['sources']]):
        raise ValueError('Private source provenance inventory changed')
    for item in provenance['sources']:
        _, current = _checked_manifest(Path(item['manifest_path']))
        if current != item:raise ValueError('Private source evidence changed after freeze')
    return provenance


def _adoption_read_literals(root, *, verified_source_provenance=None):
    """Only checked lineage files; no parent-directory descendant capability."""
    if (root / 'private_document_prefix_adoption.json').exists():
        return _document_adoption_read_literals(root, verified_source_provenance=verified_source_provenance)
    if not (root / 'source_map_prefix_adoption.json').exists():
        return []
    reads, visited, current = set(), set(), root
    while True:
        if current in visited or len(visited) >= 16:
            raise ValueError('Private source-map adoption lineage is cyclic or too deep')
        visited.add(current)
        _check_run_provenance(current)
        proof = stage._read(current / 'source_provenance.json')
        for item in proof['sources']:
            reads.update((_private_path(item['manifest_path']), _private_path(item['original_path'])))
        receipt = current / 'source_map_prefix_adoption.json'
        if not receipt.exists():break
        parent = _private_path(stage._read(receipt)['parent_directory'])
        reads.update((parent, parent / 'request.json', parent / 'source_provenance.json'))
        for path in parent.glob('response_*.json'):
            reads.update((path, parent / ('call_' + path.stem.split('_')[1] + '.started.json')))
        if (parent / 'source_map_prefix_adoption.json').exists():
            reads.add(parent / 'source_map_prefix_adoption.json')
        current = parent
    return sorted(reads, key=str)


def _document_adoption_read_literals(root, *, verified_source_provenance=None):
    """Expose exact replay files for recorded source/plan prefixes."""
    if verified_source_provenance is None:
        verified_source_provenance = _check_run_provenance(root)
    checked_sources = list(verified_source_provenance['sources'])
    reads, visited, current = set(), set(), root
    while True:
        if current in visited or len(visited) >= 8:
            raise ValueError('Private document adoption lineage is cyclic or too deep')
        visited.add(current)
        # Root load already checked every ancestry receipt, raw, intent, budget
        # and source proof. Reconstruct each distinct native derivative once.
        proof = stage._read(current / 'source_provenance.json')
        for item in proof['sources']:
            if item not in checked_sources:
                _, observed = _checked_manifest(Path(item['manifest_path']))
                if observed != item:
                    raise ValueError('Private source evidence changed in ancestry')
                checked_sources.append(item)
            manifest = _private_path(item['manifest_path'])
            reads.update((manifest, _private_path(item['original_path'])))
            receipts = {'document_evidence_manifest.json': 'document_manifest_receipt.json',
                'document_evidence_manifest_visual_text.json': 'document_manifest_visual_text_receipt.json'}
            if manifest.name not in receipts:
                raise ValueError('Document prefix lineage requires native or native-visual manifests')
            reads.add(manifest.parent / receipts[manifest.name])
            if manifest.name == 'document_evidence_manifest_visual_text.json':
                reads.update((manifest.parent / 'document_evidence_manifest.json',
                    manifest.parent / 'document_manifest_receipt.json'))
        receipt = current / 'private_document_prefix_adoption.json'
        if not receipt.exists():
            break
        reads.add(receipt)
        parent = _private_path(stage._read(receipt)['parent_directory'])
        reads.update((parent, parent / 'request.json', parent / 'source_provenance.json'))
        for pattern in ('response_*.json', 'call_*.started.json', 'budget_*.started.json', 'budget_*.completed.json'):
            reads.update(parent.glob(pattern))
        current = parent
    return sorted(reads, key=str)


def run(output, phase, *, manifests=(), kind='intro_deck', author='qwen3.5:9b',
        reviewer='qwen3.5:9b', mandate='', catalog_encoding='complete-unit-handles-v1',
        source_map_output_tokens=None, source_map_profile=None, reuse_source_map_prefix=None,
        qualification_context_profile=None, source_coverage_reviewer=None, planner=None,
        streaming_transport_contract=None, planning_schema_profile=None, planning_context_profile=None,
        source_context_profile=None, source_index_encoding=None, material_context_profile=None,
        reuse_document_prefix=None, source_reader=None, planning_assignment_profile=None,
        document_page_repair_profile=None):
    root = _private_path(output)
    if phase == 'prepare':
        checked = [_checked_manifest(path) for path in manifests]
        if not checked:raise ValueError('At least one isolated private manifest is required')
        if document_page_repair_profile is not None and (kind != 'intro_deck' or
                planning_schema_profile != 'selected-physical-plan-v5' or
                document_page_repair_profile != 'scope-feedback-once-v1'):
            raise ValueError('Page repair requires the selected intro profile')
        if planning_assignment_profile is not None and (planning_schema_profile != 'selected-physical-plan-v5' or
                planning_assignment_profile not in {'page-topics-v1','single-source-outline-v2'}):
            raise ValueError('Planning assignment requires the selected reading profile')
        document_parent = None
        if reuse_document_prefix is not None:
            if reuse_source_map_prefix is not None or planning_schema_profile != 'selected-physical-plan-v5':
                raise ValueError('Document prefix reuse requires the explicit selected source flow')
            document_parent = _private_path(reuse_document_prefix)
            _check_run_provenance(document_parent)
        if source_reader is not None and (planning_schema_profile != 'selected-physical-plan-v5' or planner is None):
            raise ValueError('Separate source reader requires the selected flow and explicit planner')
        if source_context_profile is not None and (planning_schema_profile != 'selected-physical-plan-v5' or
                source_context_profile != 'complete-local-source-32k-v1'):
            raise ValueError('Source context requires the selected reading profile')
        if source_index_encoding is not None and (planning_schema_profile != 'selected-physical-plan-v5' or
                source_index_encoding != 'bound-selected-refs-v2'):
            raise ValueError('Source index encoding requires the selected reading profile')
        if material_context_profile is not None and (planning_schema_profile != 'selected-physical-plan-v5' or
                source_context_profile != 'complete-local-source-32k-v1' or
                material_context_profile != 'complete-local-materials-32k-v1'):
            raise ValueError('Material context requires the measured selected-source profile')
        if planner is not None and (catalog_encoding not in {'complete-document-literals-v2','complete-document-literals-v3'} or
                                   qualification_context_profile != 'complete-literal-context-v2'):
            raise ValueError('A separate planner requires the explicit compact full-literal flow')
        if streaming_transport_contract is not None and (catalog_encoding not in {'complete-document-literals-v2','complete-document-literals-v3'} or
                qualification_context_profile != 'complete-literal-context-v2' or
                streaming_transport_contract != 'local-stream-observation-v1'):
            raise ValueError('Streaming observations require the explicit compact full-literal flow')
        if planning_schema_profile is not None and (catalog_encoding not in {'complete-document-literals-v2','complete-document-literals-v3'} or
                qualification_context_profile != 'complete-literal-context-v2' or
                planning_schema_profile not in {'compact-anchor-pages-v1','compact-anchor-pages-v2','finite-physical-plan-v3','indexed-physical-plan-v4','selected-physical-plan-v5'}):
            raise ValueError('Compact planning requires the explicit compact full-literal flow')
        if planning_context_profile is not None and (catalog_encoding != 'complete-document-literals-v3' or
                planning_schema_profile not in {'compact-anchor-pages-v2','finite-physical-plan-v3','indexed-physical-plan-v4','selected-physical-plan-v5'} or
                planning_context_profile != 'complete-local-32k-v1'):
            raise ValueError('Larger planning context requires the explicit dense finite profile')
        budgets = profiles = None
        prefix_count, parent = 0, None
        if source_map_output_tokens is not None or source_map_profile is not None or reuse_source_map_prefix is not None:
            from agents.research import document_generation as generation
            if catalog_encoding != generation.CATALOG_ENCODING_V3:
                raise ValueError('Source-map options require the explicit complete-page flow')
            inventory = generation.evidence_inventory([m for m, _ in checked], catalog_encoding=catalog_encoding)
            count = len(inventory['source_map_topology'])
            budgets = [source_map_output_tokens or (1600 if source_map_profile in
                {'unit-ids-v2', 'unit-ids-bound-v3'} else 900)] * count
            profiles = [source_map_profile or 'quoted-v1'] * count
            if reuse_source_map_prefix is not None:
                parent = _private_path(reuse_source_map_prefix)
                _check_run_provenance(parent)
                prefix_count, previous, parent_body = stage.verified_source_map_prefix(parent)
                if prefix_count < 1:
                    raise ValueError('No complete verified source-map prefix is available to reuse')
                if (parent_body['inventory'] != inventory or parent_body['kind'] != kind
                        or parent_body['mandate'] != mandate or parent_body['author_pin']['name'] != author
                        or prefix_count > count):
                    raise ValueError('Private source-map prefix belongs to a different source/mandate/author')
                for index in range(prefix_count):
                    budgets[index] = previous[index][2]['options']['max_tokens']
                    profiles[index] = {'document_source_map_v1': 'quoted-v1',
                        'document_source_map_v2': 'unit-ids-v2',
                        'document_source_map_v3': 'unit-ids-bound-v3'}[previous[index][0]]
        kwargs = {}
        if document_page_repair_profile is not None:
            kwargs['document_page_repair_profile'] = document_page_repair_profile
        if planning_assignment_profile is not None:
            kwargs['planning_assignment_profile'] = planning_assignment_profile
        if planner is not None:
            kwargs['planner_pin'] = {'name':planner, 'digest':installed_digest(planner)}
        if source_reader is not None:
            kwargs['source_reader_pin'] = {'name':source_reader, 'digest':installed_digest(source_reader)}
        if streaming_transport_contract is not None:
            kwargs['streaming_transport_contract'] = streaming_transport_contract
        if planning_schema_profile is not None:
            kwargs['planning_schema_profile'] = planning_schema_profile
        if planning_context_profile is not None:
            kwargs['planning_context_profile'] = planning_context_profile
        if source_context_profile is not None:
            kwargs['source_context_profile'] = source_context_profile
        if source_index_encoding is not None:
            kwargs['source_index_encoding'] = source_index_encoding
        if material_context_profile is not None:
            kwargs['material_context_profile'] = material_context_profile
        if budgets is not None:
            kwargs.update(source_map_token_budgets=budgets, source_map_profiles=profiles)
        if qualification_context_profile is not None:
            expected_profiles={'complete-source-maps-v1':'complete-page-context-v1',
                               'complete-document-literals-v1':'complete-literal-context-v2',
                               'complete-document-literals-v2':'complete-literal-context-v2',
                               'complete-document-literals-v3':'complete-literal-context-v2'}
            if expected_profiles.get(catalog_encoding) != qualification_context_profile:
                raise ValueError('Qualification context requires its exact explicit catalog flow')
            kwargs['qualification_context_profile'] = qualification_context_profile
        elif catalog_encoding in {'complete-document-literals-v1','complete-document-literals-v2','complete-document-literals-v3'}:
            raise ValueError('The complete literal catalog requires the explicit complete-literal-context-v2 profile')
        if source_coverage_reviewer is not None:
            if qualification_context_profile != 'complete-page-context-v1':
                raise ValueError('A separate source reviewer requires the complete-page context profile')
            kwargs['source_coverage_reviewer_pin'] = {'name': source_coverage_reviewer,
                'digest': installed_digest(source_coverage_reviewer)}
        result = stage.prepare_document_generation(root, [m for m, _ in checked],
            {'name': author, 'digest': installed_digest(author)},
            {'name': reviewer, 'digest': installed_digest(reviewer)}, kind, mandate=mandate,
            catalog_encoding=catalog_encoding, **kwargs)
        stage._write_new(root / 'source_provenance.json', {'sources': [p for _, p in checked]})
        if parent is not None:
            adopted = stage.adopt_source_map_prefix(root, parent, count=prefix_count)
            result.update(adopted_source_maps=adopted['adopted_model_responses'],
                          new_model_calls_for_adoption=0)
        if document_parent is not None:
            from delivery.document_prefix_adoption import adopt_document_prefix
            adopted = adopt_document_prefix(root, document_parent)
            result.update(adopted_document_responses=adopted['adopted_model_responses'],
                          new_model_calls_for_adoption=0)
        return result
    verified_provenance = _check_run_provenance(root)
    if phase not in ('advance', 'verify', 'export'):raise ValueError('Unknown diagnostic phase')
    boundary = {}
    reads = _adoption_read_literals(root, verified_source_provenance=verified_provenance)
    if reads:boundary['extra_read_literals'] = reads
    try:
        raw = run_private([sys.executable, PROJECT / 'scripts/private_reference_generation_worker.py', root, phase],
            root, timeout=118, extra_read=[PROJECT / 'agents', PROJECT / 'schemas.py'],
            local_model=phase == 'advance', **boundary)
    except (RuntimeError, TimeoutError) as exc:
        return {'state': 'blocked', 'reason': 'private_document_worker_failed',
                'error_type': type(exc).__name__, 'diagnostic_path': str(root)}
    return json.loads(raw)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--planning-assignment-profile', choices=('page-topics-v1','single-source-outline-v2'))
    parser.add_argument('--document-page-repair-profile', choices=('scope-feedback-once-v1',))
    parser.add_argument('--phase', choices=('prepare','advance','verify','export'), required=True)
    parser.add_argument('--manifest', type=Path, action='append', default=[])
    parser.add_argument('--kind', choices=('intro_deck','pitch_deck','investment_memo'), default='intro_deck')
    parser.add_argument('--author', default='qwen3.5:9b')
    parser.add_argument('--reviewer', default='qwen3.5:9b')
    parser.add_argument('--planner', help='Optional separate installed planner for the compact full-literal flow')
    parser.add_argument('--source-reader', help='Optional installed reader separate from the selected-flow global planner')
    parser.add_argument('--streaming-transport-contract', choices=('local-stream-observation-v1',),
                        help='Preserve actual partial local response and performance receipts')
    parser.add_argument('--planning-schema-profile', choices=('compact-anchor-pages-v1','compact-anchor-pages-v2','finite-physical-plan-v3','indexed-physical-plan-v4','selected-physical-plan-v5'),
                        help='Use concise model-authored multi-topic pages with whole-page evidence anchors')
    parser.add_argument('--planning-context-profile', choices=('complete-local-32k-v1',),
                        help='Use measured 32K context for dense finite planning only')
    parser.add_argument('--source-context-profile', choices=('complete-local-source-32k-v1',),
                        help='Use measured 32K context for complete selected-source reading')
    parser.add_argument('--source-index-encoding', choices=('bound-selected-refs-v2',),
                        help='Use a lossless compact selected-source index for planning')
    parser.add_argument('--material-context-profile', choices=('complete-local-materials-32k-v1',),
                        help='Use measured complete-source context for author and reviewer roles')
    parser.add_argument('--reuse-document-prefix', type=Path,
                        help='Reuse exact successful source/plan records with checked provenance')
    parser.add_argument('--mandate', default='')
    parser.add_argument('--catalog-encoding', choices=('complete-unit-handles-v1','complete-unit-handles-v2',
                                                       'complete-source-maps-v1','complete-document-literals-v1',
                                                       'complete-document-literals-v2','complete-document-literals-v3'),
                        default='complete-unit-handles-v1')
    parser.add_argument('--source-map-output-tokens', type=int, choices=(900,1600))
    parser.add_argument('--source-map-profile', choices=('quoted-v1','unit-ids-v2','unit-ids-bound-v3'))
    parser.add_argument('--reuse-source-map-prefix', type=Path)
    parser.add_argument('--qualification-context-profile', choices=('complete-page-context-v1','complete-literal-context-v2'))
    parser.add_argument('--source-coverage-reviewer', help='Separate installed local model for source coverage review')
    args = parser.parse_args()
    print(json.dumps(run(args.output,args.phase,manifests=args.manifest,kind=args.kind,
                         author=args.author,reviewer=args.reviewer,mandate=args.mandate,
                         catalog_encoding=args.catalog_encoding,
                         source_map_output_tokens=args.source_map_output_tokens,
                         source_map_profile=args.source_map_profile,
                         reuse_source_map_prefix=args.reuse_source_map_prefix,
                         qualification_context_profile=args.qualification_context_profile,
                         source_coverage_reviewer=args.source_coverage_reviewer,planner=args.planner,
                         streaming_transport_contract=args.streaming_transport_contract,
                         planning_schema_profile=args.planning_schema_profile,
                         planning_context_profile=args.planning_context_profile,
                         source_context_profile=args.source_context_profile,
                         source_index_encoding=args.source_index_encoding,
                         material_context_profile=args.material_context_profile,
                         reuse_document_prefix=args.reuse_document_prefix, source_reader=args.source_reader,
                         planning_assignment_profile=args.planning_assignment_profile,
                         document_page_repair_profile=args.document_page_repair_profile)))
