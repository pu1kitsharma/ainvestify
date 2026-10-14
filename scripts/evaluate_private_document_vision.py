"""Private local visual-table reading with immutable source and call journals.

This component proposes source-bound table structure. It never releases investor
materials, verifies financials, writes company values or changes saved rooms.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.research import document_generation as dg
from delivery import document_generation_stage as stage
from delivery.isolation import run_private
from scripts.evaluate_reference_generation import _checked_manifest, _private_path
from scripts.private_reference_generation_worker import installed_digest


def sha(path):
    path = stage._no_links(Path(path).absolute())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_request(manifest_path, raster_receipt_path, page, model_pin, vision_context_profile=None,
                   matrix_schema_profile=None, prior_proposal_directory=None, feedback_encoding=None):
    from agents.inference.local_document_vision import frozen_table_request, proposal_feedback
    manifest, provenance = _checked_manifest(manifest_path)
    raster_path = _private_path(raster_receipt_path)
    raster = stage._read(raster_path)
    render_path = raster_path.parent / 'render_receipt.json'
    render = stage._read(render_path)
    pdf = raster_path.parent / 'source_render.pdf'
    if (raster.get('contract') != 'complete-original-pptx-page-rasters-v1' or
            raster['source_sha256'] != manifest['binding']['source_sha256'] or
            raster['render_receipt_sha256'] != sha(render_path) or
            raster['rendered_pdf_sha256'] != sha(pdf) or
            render['source_sha256'] != raster['source_sha256'] or
            render['rendered_pdf_sha256'] != raster['rendered_pdf_sha256']):
        raise ValueError('Private original/raster provenance changed')
    rows = raster['images']
    if ([row['page'] for row in rows] != list(range(1, raster['complete_page_count'] + 1)) or
            type(page) is not int or not 1 <= page <= len(rows)):
        raise ValueError('Complete original physical page binding required')
    image_path = _private_path(rows[page - 1]['path'])
    if image_path.parent != raster_path.parent or rows[page - 1]['image_sha256'] != sha(image_path):
        raise ValueError('Private selected raster bytes changed')
    inventory = dg.evidence_inventory([manifest], catalog_encoding=dg.CATALOG_ENCODING_V6)
    groups = inventory['source_map_topology']
    if len(groups) != len(rows) or groups[page - 1]['page_or_slide'] != page:
        raise ValueError('Raster and original physical inventory disagree')
    group = dg._source_map_page_view(inventory, groups[page - 1])
    binding = {'source_sha256': raster['source_sha256'], 'source_page_or_slide': page,
        'rendered_pdf_sha256': raster['rendered_pdf_sha256'],
        'image_sha256': rows[page - 1]['image_sha256'],
        'raster_engine': raster['raster_engine'],
        'renderer_engine': {'name': render['renderer'],
                            'binary_sha256': render['renderer_binary_sha256']},
        'render_receipt_sha256': sha(render_path)}
    extra = {}
    if feedback_encoding is not None and (feedback_encoding != 'coordinate-diagnostics-columns-v2' or
            prior_proposal_directory is None or matrix_schema_profile != 'coordinate-native-matrix-v3'):
        raise ValueError('Feedback encoding requires a recorded coordinate repair proposal')
    prior_proof = None
    if prior_proposal_directory is not None:
        if matrix_schema_profile != 'coordinate-native-matrix-v3':
            raise ValueError('Model feedback requires the coordinate matrix profile')
        prior = _private_path(prior_proposal_directory)
        saved = stage._read(prior / 'request.json')
        if saved['source_provenance'].get('prior_proposal_directory') is not None:
            raise ValueError('One bounded visual repair is permitted; nested repairs are blocked')
        old_body, old_request = _load(prior)
        old_row = stage._read(prior / 'response_1.json')
        old_intent = stage._read(prior / 'call_1.started.json')
        old_budget = stage._read(prior / 'budget_1.completed.json')
        if (old_intent.get('run_binding_digest') != old_body['run_binding_digest'] or
                old_intent.get('request_digest') != dg.canonical_digest(dg.request_json(old_request)) or
                old_budget.get('max_seconds') != 105 or old_budget.get('max_calls') != 1 or
                old_budget.get('max_requests') != 6 or old_budget.get('calls') != 1 or
                type(old_budget.get('requests')) is not int or not 1 <= old_budget['requests'] <= 6 or
                not 0 < old_budget.get('elapsed_seconds', 106) <= 105):
            raise ValueError('Prior model proposal lacks completed bounded-call proof')
        extra['prior_proposal_feedback'] = proposal_feedback(old_request, old_row, image_path.read_bytes(),
            **({'feedback_encoding':feedback_encoding} if feedback_encoding is not None else {}))
        prior_proof = {'prior_proposal_directory': str(prior),
            'prior_request_sha256': sha(prior / 'request.json'),
            'prior_response_sha256': sha(prior / 'response_1.json'),
            'prior_intent_sha256': sha(prior / 'call_1.started.json'),
            'prior_budget_sha256': sha(prior / 'budget_1.completed.json')}
    request = frozen_table_request(image_path.read_bytes(), group, model_pin, raster_binding=binding,
        **({'vision_context_profile':vision_context_profile} if vision_context_profile is not None else {}),
        **({'matrix_schema_profile':matrix_schema_profile} if matrix_schema_profile is not None else {}),
        **({'feedback_encoding':feedback_encoding} if feedback_encoding is not None else {}), **extra)
    proof = {'manifest': provenance, 'raster_receipt_path': str(raster_path),
        'raster_receipt_sha256': sha(raster_path), 'image_path': str(image_path),
        'page': page, 'raster_binding': binding}
    if prior_proof is not None:proof.update(prior_proof)
    return request, proof


def _load(root):
    body = stage._read(root / 'request.json')
    unsigned = {key: value for key, value in body.items() if key != 'run_binding_digest'}
    if body.get('contract') != 'private-local-visual-table-journal-v1' or body['run_binding_digest'] != dg.canonical_digest(unsigned):
        raise ValueError('Private visual request changed')
    if any(type(body.get(key)) is not int or body[key] != value for key, value in
           (('maximum_seconds',105),('maximum_calls',1),('maximum_requests',6))):
        raise ValueError('Private visual finite limits changed')
    proof = body['source_provenance']
    request, current = source_request(Path(proof['manifest']['manifest_path']),
        Path(proof['raster_receipt_path']), proof['page'], body['model_pin'], body.get('vision_context_profile'),
        body.get('matrix_schema_profile'), proof.get('prior_proposal_directory'), body.get('feedback_encoding'))
    if current != proof or dg.request_json(request) != body['model_request']:
        raise ValueError('Private visual source or frozen model request changed')
    return body, request


def inside(root, phase):
    from agents.inference.local_document_vision import LocalDocumentVision, replay_table
    from agents.inference.model_authorship import recorded_call
    from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
    body, request = _load(root)
    image = Path(body['source_provenance']['image_path']).read_bytes()
    response = root / 'response_1.json'
    if response.exists():
        row = stage._read(response)
        intent = stage._read(root / 'call_1.started.json')
        if (intent.get('run_binding_digest') != body['run_binding_digest'] or
                intent.get('request_digest') != dg.canonical_digest(dg.request_json(request)) or
                intent.get('model_pin') != body['model_pin'] or row.get('id') != 'response_1'):
            raise ValueError('Private vision intent and response disagree')
        completed = root / 'budget_1.completed.json'
        if not completed.exists():
            return {'state': 'blocked', 'reason': 'unresolved_visual_budget_completion', 'recorded_model_calls': 1}
        budget = stage._read(completed)
        if (budget.get('max_seconds') != 105 or budget.get('max_calls') != 1 or
                budget.get('max_requests') != 6 or budget.get('calls') != 1 or
                type(budget.get('requests')) is not int or not 1 <= budget['requests'] <= 6):
            raise ValueError('Private vision completed budget changed')
        if 'error' in row:
            return {'state': 'blocked', 'reason': 'local_vision_inference_failed',
                'recorded_model_calls': 1, 'local_error': row['error']}
        elapsed = budget.get('elapsed_seconds')
        if (type(elapsed) not in (float,int) or not math.isfinite(elapsed) or not 0 < elapsed <= 105):
            raise ValueError('Private vision successful call exceeded finite budget')
        table = replay_table(request, row, image)
        return {'state': 'source_table_proposal', 'table': table,
            'financial_validation': 'not_established', 'investor_approval': 'not_established'}
    if (root / 'call_1.started.json').exists():
        return {'state': 'blocked', 'reason': 'unresolved_visual_call_intent'}
    if phase != 'advance':
        return {'state': 'needs_call', 'phase': 'local_visual_table_reading'}
    pin = body['model_pin']
    if installed_digest(pin['name']) != pin['digest']:
        raise ValueError('Installed private vision model changed')
    query = urllib.request.Request('http://127.0.0.1:11434/api/show',
        data=json.dumps({'model': pin['name']}).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(query, timeout=8) as result:
        if 'vision' not in json.load(result).get('capabilities', []):
            raise ValueError('Installed local model has no vision capability')
    stage._write_new(root / 'call_1.started.json', {'run_binding_digest': body['run_binding_digest'],
        'request_digest': dg.canonical_digest(dg.request_json(request)), 'model_pin': pin})
    budget = PreparationBudget(105, max_calls=1, max_requests=6)
    stage._write_new(root / 'budget_1.started.json', budget.snapshot())
    rows = []
    task, instruction, payload, schema = request
    model = LocalDocumentVision(pin['name'], image_bytes=image, **payload['options'])
    try:
        with preparation_budget(budget):
            recorded_call(model, task, instruction, payload, schema, rows,
                          lambda: stage._write_new(response, rows[-1]))
    except Exception:
        pass
    finally:
        stage._write_new(root / 'budget_1.completed.json', budget.snapshot())
    try:
        result = inside(root, 'verify')
    except Exception as exc:
        result = {'state': 'blocked', 'reason': 'visual_source_binding_failed', 'error_type': type(exc).__name__}
    stage._write_new(root / 'checkpoint_1.json', result)
    return result


def run(root, phase, *, manifest=None, raster_receipt=None, page=None, model='qwen3.5:4b',
        vision_context_profile=None, matrix_schema_profile=None, prior_proposal_directory=None,
        feedback_encoding=None):
    root = _private_path(root)
    if phase == 'prepare':
        pin = {'name': model, 'digest': installed_digest(model)}
        request, proof = source_request(manifest, raster_receipt, page, pin, vision_context_profile,
                                        matrix_schema_profile, prior_proposal_directory, feedback_encoding)
        root.mkdir(mode=0o700)
        body = {'contract': 'private-local-visual-table-journal-v1', 'model_pin': pin,
            'source_provenance': proof, 'model_request': dg.request_json(request),
            'maximum_seconds': 105, 'maximum_calls': 1, 'maximum_requests': 6}
        if vision_context_profile is not None:
            body['vision_context_profile'] = vision_context_profile
        if matrix_schema_profile is not None:
            body['matrix_schema_profile'] = matrix_schema_profile
        if feedback_encoding is not None:
            body['feedback_encoding'] = feedback_encoding
        body['run_binding_digest'] = dg.canonical_digest(body)
        stage._write_new(root / 'request.json', body)
        return {'state': 'prepared', 'source_page': page, 'financial_validation': 'not_established'}
    body, _ = _load(root)
    proof = body['source_provenance']; m = Path(proof['manifest']['manifest_path']); raster = Path(proof['raster_receipt_path'])
    reads = [m.parent, raster.parent, *m.parent.glob('document_manifest*receipt.json'),
        *m.parent.glob('document_evidence_manifest*.json'), Path(proof['manifest']['original_path']),
        raster, raster.parent / 'render_receipt.json', raster.parent / 'source_render.pdf', Path(proof['image_path'])]
    if proof.get('prior_proposal_directory') is not None:
        prior = Path(proof['prior_proposal_directory'])
        reads.extend([prior, *[prior / name for name in ('request.json','response_1.json',
                       'call_1.started.json','budget_1.completed.json')]])
    raw = run_private([sys.executable, Path(__file__).absolute(), '--output', root,
        '--phase', phase, '--inside'], root, timeout=118,
        extra_read=[Path(__file__).resolve().parents[1] / 'agents', Path(__file__).resolve().parents[1] / 'schemas.py'],
        extra_read_literals=reads, local_model=phase == 'advance')
    return json.loads(raw)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('prepare','advance','verify'), required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--raster-receipt', type=Path)
    parser.add_argument('--page', type=int)
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--vision-context-profile', choices=('complete-local-visual-32k-v1',))
    parser.add_argument('--matrix-schema-profile', choices=('complete-native-matrix-v2','coordinate-native-matrix-v3'))
    parser.add_argument('--prior-proposal', type=Path, help='One actual local proposal for bounded model-authored spatial repair')
    parser.add_argument('--feedback-encoding', choices=('coordinate-diagnostics-columns-v2',))
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    result = inside(_private_path(args.output), args.phase) if args.inside else run(args.output, args.phase,
        manifest=args.manifest, raster_receipt=args.raster_receipt, page=args.page, model=args.model,
        vision_context_profile=args.vision_context_profile, matrix_schema_profile=args.matrix_schema_profile,
        prior_proposal_directory=args.prior_proposal, feedback_encoding=args.feedback_encoding)
    print(json.dumps(result))
