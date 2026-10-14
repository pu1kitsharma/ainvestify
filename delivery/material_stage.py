"""Exact replay gateway for local-model-authored intro and pitch drafts."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from agents.inference.model_authorship import digest
from agents.inference.model_routing import validate_local_model_name
from agents.research.material_slides import replay_material_rows, render_sections
from delivery.investment_memo_stage import memo_directory
from delivery.isolation import run_private


TASKS = ('intro_deck', 'pitch_deck')
RECORDED_DRAFT_CONTRACTS = (
    'structured', 'structured_v2', 'structured_v3', 'structured_v4',
    'structured_v5', 'evidence_v7', 'evidence_v8', 'purpose_v1',
    'purpose_v2', 'purpose_v3', 'purpose_v4', 'purpose_v5', 'purpose_v6',
    'purpose_v7', 'purpose_v8', 'purpose_v9', 'purpose_v10',
    'purpose_v11', 'purpose_v12', 'purpose_v13', 'purpose_v14', 'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18',
)
FRESH_DRAFT_CONTRACT = 'purpose_v11'


def fresh_material_contract(job):
    if job.get("checkpoint",{}).get("workflow_contract") in {"room-v54-typed-temporal-selector","room-v55-compact-material-review","room-v56-inline-material-provenance","room-v57-full-relation-material-review", "room-v58-complete-source-concise-memo", "room-v59-sharded-source-adjudication", "room-v60-blind-group-source-assessment", "room-v61-supported-topic-groups", 'room-v62-explicit-topic-status', 'room-v63-source-quotes'}: return "purpose_v18"
    if job.get("checkpoint",{}).get("workflow_contract") == "room-v53-attributed-period-selector": return "purpose_v17"
    if job.get('checkpoint', {}).get('workflow_contract') in {'room-v51-temporal-material-scope', 'room-v52-compact-material-selector'}: return 'purpose_v16'
    return 'purpose_v15' if job.get('checkpoint', {}).get('workflow_contract') == 'room-v50-complete-narrative-materials' else ('purpose_v14' if job.get('checkpoint', {}).get('workflow_contract') in
            {'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else FRESH_DRAFT_CONTRACT)


def _fresh_core_material_pin(job, memo, draft_contract=None):
    if fresh_material_contract(job) not in {'purpose_v14', 'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
        return None
    if draft_contract is not None and draft_contract != fresh_material_contract(job):
        raise ValueError(f'Fresh room material requires its frozen {fresh_material_contract(job)} contract')
    selected = job.get('checkpoint', {}).get('material_draft_contract')
    if selected is not None and selected != fresh_material_contract(job):
        raise ValueError(f'Fresh room material cannot downgrade its {fresh_material_contract(job)} contract')
    pin = memo.get('content_core_author_pin')
    if (not isinstance(pin, dict) or set(pin) != {'name', 'digest'} or
            not isinstance(pin['digest'], str) or len(pin['digest']) != 64):
        raise ValueError('Fresh material requires exact accepted core author role')
    validate_local_model_name(pin['name'])
    return {**pin, 'options': (COMPACT_MATERIAL_AUTHOR_OPTIONS if job.get('checkpoint', {}).get('workflow_contract') in {'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else MATERIAL_AUTHOR_OPTIONS)}


MATERIAL_AUTHOR_OPTIONS = {'thinking': False, 'max_tokens': 2600,
                           'context_tokens': 16384, 'temperature': 0}


COMPACT_AUTHOR_OPTIONS_CONTRACT = 'material-selector-options-v1'
COMPACT_MATERIAL_AUTHOR_OPTIONS = {'thinking':False,'max_tokens':600,
    'context_tokens':8192,'temperature':0,'bound_strings':True}


def _draft_options(request):
    contract = request.get('author_options_contract')
    if contract is None: return MATERIAL_AUTHOR_OPTIONS
    if contract != COMPACT_AUTHOR_OPTIONS_CONTRACT:
        raise ValueError('Unsupported frozen material author options contract')
    if set(request.get('replay_contracts', {}).values()) not in ({'purpose_v16'}, {'purpose_v17'}, {'purpose_v18'}):
        raise ValueError('Compact selector options require purpose_v16, purpose_v17 or purpose_v18')
    return COMPACT_MATERIAL_AUTHOR_OPTIONS


def _validate_draft_routes(request, attempts):
    if request.get('author_options_contract') is None: return
    expected = _draft_options(request)
    for row in attempts:
        if any(row.get('routing', {}).get(key) != value for key,value in expected.items()):
            raise ValueError('Material raw author route differs from frozen options')


class LocalMaterialModelInventoryUnavailable(RuntimeError):
    pass


def _installed_material_digest(name):
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            installed = {row['name']: row.get('digest') for row in json.load(response)['models']}
    except (OSError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise LocalMaterialModelInventoryUnavailable('Local material model inventory unavailable') from exc
    value = installed.get(name)
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError('Requested local material author is not installed')
    return value


def _draft_model_pin(request, profile):
    pin = request.get('draft_model')
    if pin is None:
        if request.get('author_options_contract') is not None:
            raise ValueError('Compact material author requires frozen model pin')
        return profile['profiles']['draft']
    if (not isinstance(pin, dict) or set(pin) != {'name', 'digest', 'options'} or
            pin['options'] != _draft_options(request) or
            not isinstance(pin['digest'], str) or len(pin['digest']) != 64):
        raise ValueError('Invalid frozen material author pin')
    validate_local_model_name(pin['name'])
    return pin['name']


def _accepted_memo_for_material(root, memo):
    """Replay the accepted memo before freezing any copied sentence options."""
    from agents.research.investment_memo import Source, renderable_sections

    if (any((root / f'content_v{version}').exists() for version in (3, 4, 5)) or
            any((root / name).exists() for name in ('content_units_v12', 'content_units_v11', 'content_units_v10', 'content_units_v1', 'content_units_v2', 'content_units_v3', 'content_units_v4', 'content_units_v5', 'content_units_v6', 'content_units_v7', 'content_units_v8', 'content_units_v9'))) and memo.get('content_review') is None:
        raise ValueError('Material memo cannot omit its content review lineage')
    result = json.loads((root / 'result.json').read_text())
    request = json.loads((root / 'request.json').read_text())
    attempts = json.loads((root / 'attempts.json').read_text())
    profile = json.loads((root / 'model.json').read_text())
    if result.get('state') != 'accepted':
        raise ValueError('Purpose v12 requires an accepted recorded memo')
    sources = [Source.model_validate(row) for row in request['sources']]
    accepted, revision = result['accepted'], None
    if memo.get('content_review') is not None:
        if memo.get('content_flow_contract') is not None:
            from delivery.source_unit_content_stage import FLOW, FLOW_V2, FLOW_V3, FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12, flow_config, replay_source_unit_gate
            if memo['content_flow_contract'] not in (FLOW, FLOW_V2, FLOW_V3, FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12):
                raise ValueError('Unknown material source unit flow')
            coverage_metadata = {}
            if memo['content_flow_contract'] in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
                frozen_coverage = json.loads((root / flow_config(memo['content_flow_contract'])[1] /
                                              'content_request.json').read_text())
                coverage_metadata = {
                    'coverage_contract': frozen_coverage['coverage_contract'],
                    'coverage_structures': frozen_coverage['coverage_structures'],
                    'coverage_financial_scope': frozen_coverage['coverage_financial_scope'],
                    **({'coverage_batching_contract': frozen_coverage['coverage_batching_contract']}
                       if 'coverage_batching_contract' in frozen_coverage else {}),
                    **({'coverage_role': frozen_coverage['coverage_role']} if 'coverage_role' in frozen_coverage else {}),
                    **({'coverage_adjudicator_role': frozen_coverage['coverage_adjudicator_role']}
                       if 'coverage_adjudicator_role' in frozen_coverage else {})}
            revised, revision, lineage = replay_source_unit_gate(root, accepted, sources, profile, flow_contract=memo['content_flow_contract'],
                **({'author_contract': memo['content_author_contract']} if
                   memo.get('content_author_contract') is not None else {}),
                **({'section_author_contract': memo['content_section_author_contract']} if
                   memo.get('content_section_author_contract') is not None else {}),
                **({'section_review_contract': memo['content_section_review_contract']} if memo.get('content_section_review_contract') is not None else {}),
                **coverage_metadata)
            if (memo['content_flow_contract'] in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and
                    memo.get('content_core_author_pin') != lineage.get('core_author_pin')):
                raise ValueError('Material core author role differs from exact replay')
            if (memo['content_flow_contract'] in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and
                    (memo.get('content_coverage_pin') != lineage.get('coverage_pin') or
                     memo.get('content_coverage_role') != lineage.get('coverage_role') or
                     memo.get('content_coverage_adjudicator_pin') != lineage.get('coverage_adjudicator_pin') or
                     memo.get('content_coverage_adjudicator_role') != lineage.get('coverage_adjudicator_role'))):
                raise ValueError('Material coverage role differs from exact replay')
            if memo.get('content_section_author_contract') in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} and memo.get('content_core_reviewer_pin') != lineage.get('core_reviewer_pin'):
                raise ValueError('Material core reviewer role differs from exact replay')
            revision_root = root / flow_config(memo['content_flow_contract'])[1]
        else:
            from delivery.memo_content_stage import replay_content_gate
            version = memo.get('content_review_version', 3)
            if version not in (3, 4, 5):
                raise ValueError('Unknown material memo content gate version')
            replay_options = {'review_version': version} if version in (4, 5) else {}
            repair_contract = memo.get('content_repair_contract')
            if repair_contract is not None:
                from delivery.memo_content_stage import content_repair_contract
                content_repair_contract(version, repair_contract)
                replay_options['repair_contract'] = repair_contract
            revised, revision, lineage = replay_content_gate(root, accepted, sources, profile, **replay_options)
            revision_root = root / f'content_v{version}'
        if (lineage != memo['content_review'] or
                str(revision_root) != memo.get('content_revision_path') or
                revised.recommendation != memo.get('recommendation')):
            raise ValueError('Material memo content lineage differs from exact replay')
        accepted = {**accepted, 'memo': revised.model_dump(mode='json')}
    sections = renderable_sections(result['accepted'], sources, attempts,
        projection=profile.get('section_projection'), **(
            {'content_revision': revision} if revision is not None else {}))
    if [list(row) for row in sections] != memo['sections']:
        raise ValueError('Material memo options differ from exact raw replay')
    return accepted


def _financial_unknown_candidates(root, memo, contract=None):
    from agents.research.material_purpose_draft import financial_unknown_candidates
    if contract == 'purpose_v18':
        from agents.research.material_purpose_draft import financial_unknown_candidates_v18
        return financial_unknown_candidates_v18(_accepted_memo_for_material(root, memo))
    if contract == 'purpose_v17':
        from agents.research.material_purpose_draft import financial_unknown_candidates_v17
        return financial_unknown_candidates_v17(_accepted_memo_for_material(root, memo))
    if contract == 'purpose_v16':
        from agents.research.material_purpose_draft import financial_unknown_candidates_v16
        return financial_unknown_candidates_v16(_accepted_memo_for_material(root, memo))
    if contract == 'purpose_v15':
        from agents.research.material_purpose_draft import financial_unknown_candidates_v15
        return financial_unknown_candidates_v15(_accepted_memo_for_material(root, memo))
    return financial_unknown_candidates(_accepted_memo_for_material(root, memo))


def _memo_sentence_candidates(root, memo):
    from agents.research.material_purpose_draft import memo_sentence_candidates
    return memo_sentence_candidates(_accepted_memo_for_material(root, memo))


def _material_as_of(root):
    from datetime import date
    value = json.loads((root / 'request.json').read_text()).get('as_of_date')
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('Temporal material requires exact frozen ISO as-of date')
    return value


def _memo_assertion_candidates(root, memo, contract=None):
    if contract == "purpose_v18":
        from agents.research.material_purpose_draft import memo_assertion_candidates_v18
        return {**memo_assertion_candidates_v18(_accepted_memo_for_material(root, memo)), "as_of_date":_material_as_of(root)}
    if contract == "purpose_v17":
        from agents.research.material_purpose_draft import memo_assertion_candidates_v17
        return {**memo_assertion_candidates_v17(_accepted_memo_for_material(root, memo)), "as_of_date":_material_as_of(root)}
    if contract == "purpose_v16":
        from agents.research.material_purpose_draft import memo_assertion_candidates_v16
        return {**memo_assertion_candidates_v16(_accepted_memo_for_material(root, memo)),
                'as_of_date':_material_as_of(root)}
    from agents.research.material_purpose_draft import memo_assertion_candidates
    return memo_assertion_candidates(_accepted_memo_for_material(root, memo))


def _recorded_versions(saved_request):
    versions = saved_request.get('replay_contracts')
    if (not isinstance(versions, dict) or set(versions) != set(TASKS) or
            any(versions[kind] not in RECORDED_DRAFT_CONTRACTS for kind in TASKS) or
            versions['intro_deck'] != versions['pitch_deck']):
        raise ValueError('Unknown material replay contract')
    return versions


def _memo_digest(memo):
    payload = {key: memo.get(key) for key in (
        'sections', 'recommendation', 'source_hash', 'part_a_response_id',
        'part_b_response_id', 'review_response_id')}
    if memo.get('content_review') is not None:
        payload['content_review'] = memo['content_review']
        if memo.get('content_flow_contract') is not None:
            payload['content_flow_contract'] = memo['content_flow_contract']
            if memo.get('content_author_contract') is not None:
                payload['content_author_contract'] = memo['content_author_contract']
            if memo.get('content_section_review_contract') is not None:
                payload['content_section_review_contract'] = memo['content_section_review_contract']
            if memo.get('content_core_reviewer_pin') is not None:
                payload['content_core_reviewer_pin'] = memo['content_core_reviewer_pin']
            if memo.get('content_core_author_pin') is not None:
                payload['content_core_author_pin'] = memo['content_core_author_pin']
            if memo.get('content_section_author_contract') is not None:
                payload['content_section_author_contract'] = memo['content_section_author_contract']
            payload['content_revision_path'] = memo.get('content_revision_path')
        if memo.get('content_review_version') in (4, 5):
            payload['content_review_version'] = memo['content_review_version']
            payload['content_revision_path'] = memo.get('content_revision_path')
            if memo.get('content_repair_contract') in {'memo-content-repair-v5', 'memo-content-repair-v6'}:
                payload['content_repair_contract'] = memo['content_repair_contract']
    return digest(payload)


def _require_content_gate(job, root, memo):
    workflow = job.get('checkpoint', {}).get('workflow_contract')
    fresh = workflow in {'room-v27-rationale-content-gate', 'room-v28-scope-content-gate',
                   'room-v29-blind-scope-content-gate', 'room-v30-author-scope-content-gate', 'room-v31-blind-author-content-gate', 'room-v32-source-unit-content-gate', 'room-v33-isolated-source-unit-content-gate', 'room-v34-isolated-source-unit-content-gate', 'room-v35-isolated-source-unit-content-gate', 'room-v36-isolated-source-unit-content-gate', 'room-v37-isolated-source-unit-content-gate', 'room-v38-full-memo-content-gate', 'room-v39-checkpointed-full-memo-gate', 'room-v40-native-claim-full-memo-gate', 'room-v41-structured-section-full-memo-gate', 'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'}
    if fresh or any((root / f'content_v{version}').exists() for version in (3, 4, 5)) or any((root / name).exists() for name in ('content_units_v12', 'content_units_v11', 'content_units_v10', 'content_units_v1', 'content_units_v2', 'content_units_v3', 'content_units_v4', 'content_units_v5', 'content_units_v6', 'content_units_v7', 'content_units_v8', 'content_units_v9')) or memo.get('content_review') is not None:
        if memo.get('content_review') is None:
            raise ValueError('Fresh room materials require accepted memo content review lineage')
        if workflow in {'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'}:
            _fresh_core_material_pin(job, memo)
        if workflow in {'room-v32-source-unit-content-gate', 'room-v33-isolated-source-unit-content-gate', 'room-v34-isolated-source-unit-content-gate', 'room-v35-isolated-source-unit-content-gate', 'room-v36-isolated-source-unit-content-gate', 'room-v37-isolated-source-unit-content-gate', 'room-v38-full-memo-content-gate', 'room-v39-checkpointed-full-memo-gate', 'room-v40-native-claim-full-memo-gate', 'room-v41-structured-section-full-memo-gate', 'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'}:
            from delivery.source_unit_content_stage import FLOW, FLOW_V2, FLOW_V3, FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12
            expected_flow = (FLOW_V11 if workflow == 'room-v63-source-quotes' else FLOW_V10 if workflow == 'room-v62-explicit-topic-status' else FLOW_V9 if workflow == 'room-v61-supported-topic-groups' else FLOW_V8 if workflow == 'room-v60-blind-group-source-assessment' else FLOW_V7 if workflow == 'room-v59-sharded-source-adjudication' else FLOW_V6 if workflow in {'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else FLOW_V4 if workflow in {'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else FLOW_V3 if workflow in {'room-v39-checkpointed-full-memo-gate', 'room-v40-native-claim-full-memo-gate', 'room-v41-structured-section-full-memo-gate', 'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else
                             FLOW_V2 if workflow == 'room-v38-full-memo-content-gate' else FLOW)
            if memo.get('content_flow_contract') != expected_flow:
                raise ValueError('Room material requires its frozen source unit flow')
            expected_author = ('memo-source-unit-author-v7' if workflow in {'room-v38-full-memo-content-gate', 'room-v39-checkpointed-full-memo-gate', 'room-v40-native-claim-full-memo-gate', 'room-v41-structured-section-full-memo-gate', 'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else
                'memo-source-unit-author-v6' if
                workflow == 'room-v37-isolated-source-unit-content-gate' else
                'memo-source-unit-author-v5' if
                workflow == 'room-v36-isolated-source-unit-content-gate' else
                'memo-source-unit-author-v4' if
                workflow == 'room-v35-isolated-source-unit-content-gate' else
                'memo-source-unit-author-v3' if
                workflow == 'room-v34-isolated-source-unit-content-gate' else
                'memo-source-unit-author-v2' if workflow == 'room-v33-isolated-source-unit-content-gate' else None)
            if memo.get('content_author_contract') != expected_author:
                raise ValueError('Room material requires its frozen source unit author contract')
            expected_section_author = ('memo-section-units-author-v13' if workflow in {'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else 'memo-section-units-author-v8' if workflow in {'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else
                'memo-section-units-author-v7' if workflow == 'room-v46-structured-core-decisions' else
                'memo-section-units-author-v6' if workflow == 'room-v45-narrative-section-budget' else
                'memo-section-units-author-v5' if workflow == 'room-v44-literal-narrative-author' else
                'memo-section-units-author-v4' if workflow == 'room-v43-bounded-section-author' else
                'memo-section-units-author-v3' if
                workflow in {'room-v41-structured-section-full-memo-gate', 'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else
                'memo-section-units-author-v2' if
                workflow == 'room-v40-native-claim-full-memo-gate' else None)
            if memo.get('content_section_author_contract') != expected_section_author:
                raise ValueError('Room material requires its frozen section author contract')
            if workflow in {'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} and (not isinstance(memo.get('content_core_author_pin'), dict) or
                    memo.get('content_core_author_pin') != memo['content_review'].get('core_author_pin')):
                raise ValueError('Room material requires its frozen core author role')
            if workflow in {'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} and (not isinstance(memo.get('content_core_reviewer_pin'), dict) or memo['content_core_reviewer_pin'] != memo['content_review'].get('core_reviewer_pin')):
                raise ValueError('Room material requires its frozen core reviewer role')
            expected_section_review = 'memo-section-units-review-v12' if workflow in {'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else 'memo-section-units-review-v7' if workflow in {'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else None
            if memo.get('content_section_review_contract') != expected_section_review:
                raise ValueError('Room material requires its frozen section reviewer contract')
            if workflow in {'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} and memo.get('content_diligence_coverage', {}).get('contract') != ('diligence-source-coverage-v19' if workflow == 'room-v63-source-quotes' else 'diligence-source-coverage-v18' if workflow == 'room-v62-explicit-topic-status' else 'diligence-source-coverage-v17' if workflow == 'room-v61-supported-topic-groups' else 'diligence-source-coverage-v16' if workflow == 'room-v60-blind-group-source-assessment' else 'diligence-source-coverage-v15' if workflow == 'room-v59-sharded-source-adjudication' else 'diligence-source-coverage-v14'):
                raise ValueError('Fresh room material requires its exact adjudicated all-source coverage contract')
            if workflow in {'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} and memo.get('content_coverage_role') != 'challenge':
                raise ValueError('Fresh room material requires its frozen source-classification role')
            if (workflow in {'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'}
                    and (memo.get('content_coverage_adjudicator_role') != 'author'
                         or memo.get('content_coverage_adjudicator_pin') != memo.get('content_core_author_pin'))):
                raise ValueError('Fresh sharded room requires its frozen author-model adjudication role')
            if workflow == 'room-v63-source-quotes':
                if (memo.get('content_diligence_coverage', {}).get('assessment_contract') != 'source-interpretation-evidence-first-v3'
                        or memo.get('content_review', {}).get('coverage_batching_contract') != 'source-interpretation-evidence-first-v3'):
                    raise ValueError('Fresh source-quote room requires its exact frozen V3 interpretation contract')
                if memo.get('content_diligence_coverage', {}).get('financial_evidence_scope') != job['checkpoint'].get('financial_evidence_scope'):
                    raise ValueError('Fresh source-quote room changed its supplied financial source scope')
            _accepted_memo_for_material(root, memo)
            return
        if fresh and memo.get('content_flow_contract') is not None:
            raise ValueError('Historical room material cannot replace its frozen content gate')
        expected = (5 if workflow in {'room-v29-blind-scope-content-gate', 'room-v30-author-scope-content-gate', 'room-v31-blind-author-content-gate', 'room-v32-source-unit-content-gate', 'room-v33-isolated-source-unit-content-gate', 'room-v34-isolated-source-unit-content-gate', 'room-v35-isolated-source-unit-content-gate', 'room-v36-isolated-source-unit-content-gate', 'room-v37-isolated-source-unit-content-gate', 'room-v38-full-memo-content-gate', 'room-v39-checkpointed-full-memo-gate', 'room-v40-native-claim-full-memo-gate', 'room-v41-structured-section-full-memo-gate', 'room-v42-independent-author-checkpoints', 'room-v43-bounded-section-author', 'room-v44-literal-narrative-author', 'room-v45-narrative-section-budget', 'room-v46-structured-core-decisions', 'room-v47-prospective-risk-scope', 'room-v48-narrative-function-review', 'room-v49-batched-material-review', 'room-v50-complete-narrative-materials', 'room-v51-temporal-material-scope', 'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'} else
                    4 if workflow == 'room-v28-scope-content-gate' else 3)
        if fresh and memo.get('content_review_version', 3) != expected:
            raise ValueError('Room material requires its frozen content gate version')
        expected_repair = ('memo-content-repair-v6' if workflow == 'room-v31-blind-author-content-gate' else
                           'memo-content-repair-v5' if workflow == 'room-v30-author-scope-content-gate'
                           else 'memo-content-repair-v4' if expected in (4, 5) else None)
        if fresh and memo.get('content_repair_contract', 'memo-content-repair-v4' if expected in (4, 5) else None) != expected_repair:
            raise ValueError('Room material requires its frozen content repair contract')
        _accepted_memo_for_material(root, memo)


def validate_material_checkpoint(job, memo, material=None):
    """Replay accepted specs before rendering, without calling inference."""
    if memo.get('state') != 'accepted' or not memo.get('source_hash'):
        raise ValueError('Material drafting requires an accepted source-bound memo')
    root = memo_directory(job)
    _require_content_gate(job, root, memo)
    memo_digest = _memo_digest(memo)
    base = {'input_revision': job['input_revision'], 'source_hash': memo['source_hash'],
            'memo_digest': memo_digest, 'sections': memo['sections']}
    request_file = root / 'material_request.json'
    saved_request = json.loads(request_file.read_text())
    versions = _recorded_versions(saved_request)
    required_pin = _fresh_core_material_pin(job, memo)
    if required_pin is not None and (set(versions.values()) != {fresh_material_contract(job)} or saved_request.get('draft_model') != required_pin):
        raise ValueError('Material request differs from frozen room contract and core author role')
    request_base = {**base, 'replay_contracts': versions}
    if 'author_options_contract' in saved_request:
        request_base['author_options_contract'] = saved_request['author_options_contract']
        request_base['as_of_date'] = _material_as_of(root)
    if 'draft_model' in saved_request:
        request_base['draft_model'] = saved_request['draft_model']
    if versions['intro_deck'] in {'purpose_v12', 'purpose_v13', 'purpose_v14', 'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
        request_base['financial_unknown_candidates'] = _financial_unknown_candidates(root, memo, versions['intro_deck'])
    elif 'financial_unknown_candidates' in saved_request:
        raise ValueError('Historical material request has unexpected financial candidates')
    if versions['intro_deck'] in {'purpose_v13', 'purpose_v14'}:
        request_base['memo_sentence_candidates'] = _memo_sentence_candidates(root, memo)
    elif 'memo_sentence_candidates' in saved_request:
        raise ValueError('Historical material request has unexpected sentence candidates')
    if versions['intro_deck'] in {'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
        request_base['memo_assertion_candidates'] = _memo_assertion_candidates(root, memo, versions['intro_deck'])
    elif 'memo_assertion_candidates' in saved_request:
        raise ValueError('Historical material request has unexpected assertion candidates')
    request = {**request_base, 'digest': digest(request_base)}
    if saved_request != request:
        raise ValueError('Accepted memo changed after material drafting began')
    profile = json.loads((root / 'model.json').read_text())
    model_name = _draft_model_pin(saved_request, profile)
    validate_local_model_name(model_name)
    result = json.loads((root / 'material_result.json').read_text())
    if result['state'] != 'accepted':
        raise ValueError('Saved material result is not accepted')
    if result.get('source_hash') != memo['source_hash'] or result.get('memo_digest') != memo_digest:
        raise ValueError('Material result scope changed')
    attempts = json.loads((root / 'material_attempts.json').read_text())
    _validate_draft_routes(saved_request, attempts)
    decks = {}
    for kind in TASKS:
        payload = {**base, 'kind': kind}
        if 'as_of_date' in request_base: payload['as_of_date'] = request_base['as_of_date']
        if versions[kind] in {'purpose_v12', 'purpose_v13', 'purpose_v14', 'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
            payload['financial_unknown_candidates'] = request_base['financial_unknown_candidates']
        if versions[kind] in {'purpose_v13', 'purpose_v14'}:
            payload['memo_sentence_candidates'] = request_base['memo_sentence_candidates']
        if versions[kind] in {'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
            payload['memo_assertion_candidates'] = request_base['memo_assertion_candidates']
        replayed = replay_material_rows(kind, payload, attempts, memo['sections'],
                                        model_name=model_name,
                                        contract_version=versions[kind])
        if (replayed['state'] != 'accepted' or
                replayed['response_ids'] != result['decks'][kind]['response_ids'] or
                replayed['response_ids'][-1] != result['decks'][kind]['response_id']):
            raise ValueError('Material response is not bound to frozen model and inputs')
        rendered = render_sections(replayed['spec'], memo['sections'])
        if [list(section) for section in rendered] != result['decks'][kind]['sections']:
            raise ValueError('Material section projection differs from recorded model response')
        decks[kind] = {'response_id': replayed['response_ids'][-1],
                       'response_ids': replayed['response_ids'], 'sections': rendered}
    if decks['intro_deck']['sections'] == decks['pitch_deck']['sections']:
        raise ValueError('Local model returned duplicate intro and pitch decks')
    expected = {'state': 'accepted', 'source_hash': memo['source_hash'],
            'memo_digest': memo_digest, 'decks': decks,
            'private_attempts_path': str(root / 'material_attempts.json')}
    if material is not None and material != expected:
        raise ValueError('Material checkpoint differs from recorded local responses')
    return expected


def run_material_pass(job, memo, *, timeout, draft_contract=None,
                      draft_model=None):
    if memo.get('state') != 'accepted' or not memo.get('source_hash'):
        raise ValueError('Material drafting requires an accepted source-bound memo')
    draft_contract = draft_contract or fresh_material_contract(job)
    required_pin = _fresh_core_material_pin(job, memo, draft_contract)
    project = Path(__file__).resolve().parents[1]
    root = memo_directory(job)
    _require_content_gate(job, root, memo)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    memo_digest = _memo_digest(memo)
    base = {'input_revision': job['input_revision'], 'source_hash': memo['source_hash'],
            'memo_digest': memo_digest, 'sections': memo['sections']}
    if draft_contract not in {FRESH_DRAFT_CONTRACT, 'structured_v5', 'purpose_v3', 'purpose_v4',
                              'purpose_v5', 'purpose_v6', 'purpose_v7',
                              'purpose_v8', 'purpose_v9', 'purpose_v10',
                              'purpose_v11', 'purpose_v12', 'purpose_v13', 'purpose_v14', 'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
        raise ValueError('Unknown fresh material draft contract')
    request_base = {**base, 'replay_contracts': {
        kind: draft_contract for kind in TASKS}}
    if job.get('checkpoint', {}).get('workflow_contract') in {'room-v52-compact-material-selector', 'room-v53-attributed-period-selector', 'room-v54-typed-temporal-selector', 'room-v55-compact-material-review', 'room-v56-inline-material-provenance', 'room-v57-full-relation-material-review', 'room-v58-complete-source-concise-memo', 'room-v59-sharded-source-adjudication', 'room-v60-blind-group-source-assessment', 'room-v61-supported-topic-groups', 'room-v62-explicit-topic-status', 'room-v63-source-quotes'}:
        request_base.update(author_options_contract=COMPACT_AUTHOR_OPTIONS_CONTRACT, as_of_date=_material_as_of(root))
    request_file = root / 'material_request.json'
    requested_model = draft_model or os.environ.get('LOCAL_MATERIAL_DRAFT_MODEL')
    if required_pin is not None:
        if requested_model is not None and requested_model != required_pin['name']:
            raise ValueError('Material author differs from accepted core author role')
        requested_model = required_pin['name']
        if _installed_material_digest(requested_model) != required_pin['digest']:
            raise ValueError('Installed material author differs from accepted core author digest')
    if requested_model:
        validate_local_model_name(requested_model)
    if request_file.exists():
        existing = json.loads(request_file.read_text())
        versions = _recorded_versions(existing)
        if required_pin is not None and (set(versions.values()) != {fresh_material_contract(job)} or existing.get('draft_model') != required_pin):
            raise ValueError('Material request differs from frozen room contract and core author role')
        old_base = {**base, 'replay_contracts': versions}
        if 'author_options_contract' in existing:
            old_base['author_options_contract'] = existing['author_options_contract']
            old_base['as_of_date'] = _material_as_of(root)
        if versions['intro_deck'] in {'purpose_v12', 'purpose_v13', 'purpose_v14', 'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
            old_base['financial_unknown_candidates'] = _financial_unknown_candidates(root, memo, versions['intro_deck'])
        elif 'financial_unknown_candidates' in existing:
            raise ValueError('Historical material request has unexpected financial candidates')
        if versions['intro_deck'] in {'purpose_v13', 'purpose_v14'}:
            old_base['memo_sentence_candidates'] = _memo_sentence_candidates(root, memo)
        elif 'memo_sentence_candidates' in existing:
            raise ValueError('Historical material request has unexpected sentence candidates')
        if versions['intro_deck'] in {'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
            old_base['memo_assertion_candidates'] = _memo_assertion_candidates(root, memo, versions['intro_deck'])
        elif 'memo_assertion_candidates' in existing:
            raise ValueError('Historical material request has unexpected assertion candidates')
        if 'draft_model' in existing:
            old_base['draft_model'] = existing['draft_model']
        profile = json.loads((root / 'model.json').read_text())
        frozen_name = _draft_model_pin(existing, profile)
        if requested_model and requested_model != frozen_name:
            raise ValueError('Material author model changed after request freeze; new immutable branch required')
        if (existing.get('draft_model') and
                _installed_material_digest(frozen_name) != existing['draft_model']['digest']):
            raise ValueError('Installed material author differs from frozen model digest')
        request = {**old_base, 'digest': digest(old_base)}
        if existing != request:
            raise ValueError('Accepted memo changed after material drafting began')
    else:
        if (root / 'material_attempts.json').exists():
            raise ValueError('Saved material attempts lack a frozen request')
        if draft_contract in {'purpose_v12', 'purpose_v13', 'purpose_v14', 'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
            request_base['financial_unknown_candidates'] = _financial_unknown_candidates(root, memo, draft_contract)
        if draft_contract in {'purpose_v13', 'purpose_v14'}:
            request_base['memo_sentence_candidates'] = _memo_sentence_candidates(root, memo)
        if draft_contract in {'purpose_v15', 'purpose_v16', 'purpose_v17', 'purpose_v18'}:
            request_base['memo_assertion_candidates'] = _memo_assertion_candidates(root, memo, draft_contract)
        if requested_model:
            request_base['draft_model'] = {'name': requested_model,
                'digest': _installed_material_digest(requested_model),
                'options': _draft_options(request_base)}
        request = {**request_base, 'digest': digest(request_base)}
        temporary = request_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(request, ensure_ascii=False))
        temporary.replace(request_file)
    (root / 'material_budget.json').write_text(json.dumps({
        'seconds': max(1, min(105, timeout - 8))}))
    run_private([__import__('sys').executable, project / 'scripts/private_material_worker.py'],
                root, timeout=timeout, extra_read=(project / 'agents', project / 'schemas.py'),
                local_model=True)
    result = json.loads((root / 'material_result.json').read_text())
    if result['state'] != 'accepted':
        return {'state': result['state'], 'reason': result.get('reason', 'materials_incomplete'),
                'source_hash': memo['source_hash'], 'memo_digest': memo_digest}
    return validate_material_checkpoint(job, memo)
