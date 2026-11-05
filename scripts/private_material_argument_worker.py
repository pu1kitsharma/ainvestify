"""One bounded, unreleased historical source-argument diagnostic in confinement."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agents.inference.local_models import LocalModel
    from agents.inference.model_authorship import recorded_call
    from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
    from agents.research import document_generation as generation
    from delivery import material_argument as argument
    from delivery.rendering import render_argument_memo
    from delivery.inspection import inspect_export_pair

    root = Path.cwd()
    def write(name, value):
        content = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True,
            ensure_ascii=False, allow_nan=False).encode()
        with os.fdopen(os.open(root / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), 'wb') as f:
            f.write(content); f.flush(); os.fsync(f.fileno())
        return hashlib.sha256(content).hexdigest()

    config = json.loads((root / 'config.json').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    request = argument.frozen_argument_request(manifest, config['pages'], config['model_pin'],
                                              mandate=config['mandate'])
    if config['request_digest'] != generation.canonical_digest(generation.request_json(request)):
        raise ValueError('Frozen argument worker request changed')
    bindings = argument.source_unit_bindings(manifest, config['pages'])
    if generation.canonical_digest(bindings) != request[2]['source_unit_bindings_digest']:
        raise ValueError('Original source-unit map changed')
    write('source-unit-bindings.json', bindings)
    write('author-request.json', generation.request_json(request))
    if config.get('operation') == 'compact_review_only':
        return compact_review_only(root, config, request, write)
    if config.get('operation') == 'correct_and_compact_review':
        return correct_and_compact_review(root, config, request, write)
    if config.get('operation') is not None:
        raise ValueError('Unsupported private argument operation')
    budget = PreparationBudget(max_seconds=115, max_calls=6, max_requests=6)
    attempts, exports = [], []
    report = {'contract': argument.CONTRACT, 'state': 'blocked', 'release_status': 'draft_only',
        'semantic_review': 'not_run', 'financial_validation': 'not_established',
        'reviewer_relationship': 'same_model_nonindependent',
        'human_release': 'not_established', 'source_manifest_digest': manifest['manifest_digest'],
        'source_pages': config['pages']}
    def save():
        write('response-' + str(len(attempts)) + '.json', attempts[-1])
    try:
        with preparation_budget(budget):
            model = LocalModel(config['model_pin']['name'], **request[2]['options'])
            recorded_call(model, *request, attempts, save)
            section = argument.replay_argument(request, attempts[-1])
            projected = argument.renderable_argument(request, attempts[-1])
            for fmt in ('docx', 'pdf'):
                content = render_argument_memo('Historical reference argument diagnostic', [projected], format=fmt)
                exports.append({'format': fmt, 'sha256': write('argument.' + fmt, content), 'bytes': len(content)})
            inspection = inspect_export_pair((root / 'argument.docx').read_bytes(), 'docx',
                                             (root / 'argument.pdf').read_bytes())
            write('pair-inspection.json', inspection)
            report.update(state='authored_draft', block_count=len(section['blocks']),
                role_counts={role: sum(b['role'] == role for b in section['blocks'])
                             for role in sorted({b['role'] for b in section['blocks']})},
                body_characters=len(projected[1]),
                distinct_cited_units=len({q['unit_id'] for b in section['blocks'] for q in b['evidence']}),
                supplied_units=len(request[2]['units']), exports=exports,
                export_pair_status=inspection['pair_status'],
                editable_text_status=inspection['editable_text_status'],
                visual_quality='not_established')
            if inspection['pair_status'] != 'pass':
                raise ValueError('Argument exported pair requires review')
            if budget.remaining() >= 25:
                review_request = argument.frozen_compact_argument_review_request(request, attempts[-1], config['model_pin'])
                write('review-request.json', generation.request_json(review_request))
                report['semantic_review'] = 'attempted_incomplete'
                reviewer = LocalModel(config['model_pin']['name'], **review_request[2]['options'])
                recorded_call(reviewer, *review_request, attempts, save)
                review = argument.replay_compact_argument_review(review_request, attempts[-1])
                ids = [item['block_id'] for item in review_request[2]['block_inventory']]
                votes = [review[bid] for bid in ids] + [review['section_coherence']]
                report.update(semantic_review='local_model_' + review['overall_verdict'],
                    reviewed_blocks=len(ids), coherence_reviewed=True,
                    vote_counts={v: sum(item['verdict'] == v for item in votes)
                                 for v in ('pass', 'revise', 'unassessed')})
    except Exception as exc:
        # Full exception/raw output retained privately; metadata is not an answer.
        write('failure.json', {'type': type(exc).__name__, 'message': str(exc)})
        report.update(failure_type=type(exc).__name__, failure_retained=True)
    finally:
        report.update(usage=budget.snapshot(), model_pin=config['model_pin'],
                      request_digest=config['request_digest'], recorded_responses=len(attempts))
        write('report.json', report)


def compact_review_only(root, config, author_request, write):
    """Review an immutable successful author record; no author invocation/export."""
    from agents.inference.local_models import LocalModel
    from agents.inference.model_authorship import recorded_call
    from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
    from agents.research import document_generation as generation
    from delivery import material_argument as argument

    if json.loads((root / 'accepted-author-request.json').read_text()) != generation.request_json(author_request):
        raise ValueError('Original accepted author request changed')
    raw_record = (root / 'accepted-author-response.json').read_bytes()
    if hashlib.sha256(raw_record).hexdigest() != config['author_record_sha256']:
        raise ValueError('Original accepted author record bytes changed')
    author_row = json.loads(raw_record)
    if author_row['response_hash'] != config['author_response_hash']:
        raise ValueError('Original author response identity changed')
    review_request = argument.frozen_compact_argument_review_request(author_request, author_row,
                                                                     config['reviewer_pin'])
    if generation.canonical_digest(generation.request_json(review_request)) != config['review_request_digest']:
        raise ValueError('Frozen independent review source/draft binding changed')
    write('review-request.json', generation.request_json(review_request))
    budget = PreparationBudget(max_seconds=105, max_calls=1, max_requests=1)
    attempts = []
    report = {'contract': argument.COMPACT_REVIEW_CONTRACT, 'state': 'blocked',
        'semantic_review': 'attempted_incomplete', 'author_regenerated': False,
        'reviewer_relationship': review_request[2]['reviewer_relationship'],
        'author_response_hash': author_row['response_hash'],
        'author_request_digest': config['request_digest'],
        'review_request_digest': config['review_request_digest'],
        'original_source_map_digest': author_request[2]['source_unit_bindings_digest'],
        'block_count': len(author_row['answer']['blocks']), 'release_status': 'draft_only',
        'financial_validation': 'not_established', 'human_release': 'not_established'}
    def save():
        write('review-response-' + str(len(attempts)) + '.json', attempts[-1])
    try:
        with preparation_budget(budget):
            reviewer = LocalModel(config['reviewer_pin']['name'], **review_request[2]['options'])
            recorded_call(reviewer, *review_request, attempts, save)
            review = argument.replay_compact_argument_review(review_request, attempts[-1])
            ids = [item['block_id'] for item in review_request[2]['block_inventory']]
            votes = [review[bid] for bid in ids] + [review['section_coherence']]
            report.update(state='review_complete', semantic_review='local_model_' + review['overall_verdict'],
                reviewed_blocks=len(ids), coherence_reviewed=True,
                vote_counts={v: sum(item['verdict'] == v for item in votes)
                             for v in ('pass', 'revise', 'unassessed')},
                category_counts={c: sum(item['category'] == c for item in votes)
                                 for c in sorted({item['category'] for item in votes})})
    except Exception as exc:
        write('failure.json', {'type': type(exc).__name__, 'message': str(exc)})
        report.update(failure_type=type(exc).__name__, failure_retained=True)
    finally:
        report.update(usage=budget.snapshot(), model_pin=config['reviewer_pin'],
                      recorded_responses=len(attempts))
        write('report.json', report)


def correct_and_compact_review(root, config, author_request, write):
    """One model-authored revision with unchanged non-scope blocks, then review."""
    from agents.inference.local_models import LocalModel
    from agents.inference.model_authorship import recorded_call
    from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
    from agents.research import document_generation as generation
    from delivery import material_argument as argument
    from delivery.rendering import render_argument_memo
    from delivery.inspection import inspect_export_pair

    if json.loads((root / 'accepted-author-request.json').read_text()) != generation.request_json(author_request):
        raise ValueError('Original accepted author request changed')
    author_bytes = (root / 'accepted-author-response.json').read_bytes()
    review_bytes = (root / 'accepted-blocking-review-response.json').read_bytes()
    if (hashlib.sha256(author_bytes).hexdigest() != config['author_record_sha256'] or
            hashlib.sha256(review_bytes).hexdigest() != config['blocking_review_record_sha256']):
        raise ValueError('Original author/critique record bytes changed')
    author_row, review_row = json.loads(author_bytes), json.loads(review_bytes)
    retained_review = json.loads((root / 'accepted-blocking-review-request.json').read_text())
    blocking_request = argument.frozen_compact_argument_review_request(author_request, author_row,
        config['blocking_reviewer_pin'], review_contract=retained_review[2]['contract'])
    if retained_review != generation.request_json(blocking_request):
        raise ValueError('Actual blocking review request changed')
    correction_request = argument.frozen_argument_patch_request(author_request, author_row,
        blocking_request, review_row, config['model_pin'])
    if generation.canonical_digest(generation.request_json(correction_request)) != config['correction_request_digest']:
        raise ValueError('Frozen correction request changed')
    write('correction-request.json', generation.request_json(correction_request))
    budget = PreparationBudget(max_seconds=115, max_calls=6, max_requests=6)
    attempts = []
    report = {'contract': argument.PATCH_CONTRACT, 'state': 'blocked',
        'semantic_review': 'not_run', 'release_status': 'draft_only',
        'reviewer_relationship': ('same_model_nonindependent' if
            config['reviewer_pin']['name'] == config['model_pin']['name'] or
            config['reviewer_pin']['digest'] == config['model_pin']['digest'] else 'separate_model_unqualified'),
        'original_author_response_hash': author_row['response_hash'],
        'blocking_review_response_hash': review_row['response_hash'],
        'original_source_map_digest': author_request[2]['source_unit_bindings_digest'],
        'financial_validation': 'not_established', 'visual_quality': 'not_established',
        'human_release': 'not_established'}
    def save():
        write('response-' + str(len(attempts)) + '.json', attempts[-1])
    try:
        with preparation_budget(budget):
            model = LocalModel(config['model_pin']['name'], **correction_request[2]['options'])
            recorded_call(model, *correction_request, attempts, save)
            correction_row = attempts[-1]
            section = argument.replay_argument(correction_request, correction_row)
            projected = argument.renderable_argument(correction_request, correction_row)
            compiled = argument._project_argument_patch(correction_request, correction_row['answer'])
            unchanged = {f'B{i}': generation.canonical_digest(old)
                for i, (old, new) in enumerate(zip(author_row['answer']['blocks'],
                                                   compiled['blocks']), 1) if old == new}
            lineage = {'original_author_response_hash': author_row['response_hash'],
                'blocking_review_response_hash': review_row['response_hash'],
                'correction_response_hash': correction_row['response_hash'],
                'correction_request_digest': config['correction_request_digest'],
                'patch_scope': compiled['recorded_patch_scope'],
                'unchanged_original_block_digests': unchanged,
                'new_section_digest': generation.canonical_digest({key: compiled[key]
                                                                 for key in ('title', 'blocks')})}
            write('revision-lineage.json', lineage)
            write('projected-section.json', {'projection_contract': argument.PATCH_CONTRACT,
                'raw_patch_response_hash': correction_row['response_hash'],
                'section': {key: compiled[key] for key in ('title', 'blocks')}})
            exports = []
            for fmt in ('docx', 'pdf'):
                content = render_argument_memo('Historical reference argument diagnostic', [projected], format=fmt)
                exports.append({'format': fmt, 'sha256': write('corrected-argument.' + fmt, content), 'bytes': len(content)})
            inspection = inspect_export_pair((root / 'corrected-argument.docx').read_bytes(), 'docx',
                                             (root / 'corrected-argument.pdf').read_bytes())
            write('pair-inspection.json', inspection)
            report.update(state='revised_draft', patch_scope=lineage['patch_scope'],
                unchanged_blocks=list(unchanged), body_characters=len(projected[1]),
                new_section_digest=lineage['new_section_digest'], exports=exports,
                export_pair_status=inspection['pair_status'], editable_text_status=inspection['editable_text_status'])
            if inspection['pair_status'] != 'pass':
                raise ValueError('Corrected argument exported pair requires review')
            if budget.remaining() >= 25:
                fresh = argument.frozen_compact_argument_review_request(correction_request,
                                                                       correction_row, config['reviewer_pin'])
                write('fresh-review-request.json', generation.request_json(fresh))
                report['semantic_review'] = 'attempted_incomplete'
                reviewer = LocalModel(config['reviewer_pin']['name'], **fresh[2]['options'])
                recorded_call(reviewer, *fresh, attempts, save)
                result = argument.replay_compact_argument_review(fresh, attempts[-1])
                ids = [item['block_id'] for item in fresh[2]['block_inventory']]
                votes = [result[bid] for bid in ids] + [result['section_coherence']]
                report.update(semantic_review='local_model_' + result['overall_verdict'],
                    reviewed_blocks=len(ids), coherence_reviewed=True,
                    vote_counts={v: sum(item['verdict'] == v for item in votes)
                                 for v in ('pass', 'revise', 'unassessed')},
                    category_counts={c: sum(item['category'] == c for item in votes)
                                     for c in sorted({item['category'] for item in votes})})
            else:
                report['semantic_review'] = 'not_run_remaining_budget_insufficient'
    except Exception as exc:
        write('failure.json', {'type': type(exc).__name__, 'message': str(exc)})
        report.update(failure_type=type(exc).__name__, failure_retained=True)
    finally:
        report.update(usage=budget.snapshot(), model_pin=config['model_pin'],
                      recorded_responses=len(attempts))
        write('report.json', report)


if __name__ == '__main__':
    main()
