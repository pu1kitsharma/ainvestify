"""Versioned finite private source-only generation phases before rendering."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

from agents.inference.model_authorship import digest
from agents.inference.model_routing import validate_local_model_name
from agents.research.investment_memo import Memo, Source
from delivery.isolation import run_private
from delivery.memo_content_stage import PROJECT, _inventory, _write

FLOW = 'memo-source-unit-flow-v1'
PHASES = ('source_characterization', 'source_unit_author', 'source_unit_review')
ROOT_NAME = 'content_units_v1'
FLOW_V2 = 'memo-source-unit-flow-v2'
PHASES_V2 = PHASES + ('memo_section_author', 'memo_section_review')
ROOT_NAME_V2 = 'content_units_v2'
FLOW_V3 = 'memo-source-unit-flow-v3'
PHASES_V3 = ('source_characterization', 'source_unit_author',
             'source_unit_review_recommendation', 'source_unit_review_u0', 'source_unit_review_u1',
             'memo_section_author', 'memo_section_review_investment_thesis',
             'memo_section_review_business_and_market',
             'memo_section_review_differentiation_and_execution',
             'memo_section_review_risks_and_countercase', 'memo_section_review_diligence_plan')
ROOT_NAME_V3 = 'content_units_v3'
FLOW_V4 = 'memo-source-unit-flow-v4'
FIELDS = ('investment_thesis', 'business_and_market', 'differentiation_and_execution',
          'risks_and_countercase', 'diligence_plan')
PHASES_V4 = PHASES_V3[:5] + tuple('memo_section_author_' + field for field in FIELDS) + tuple(
    'memo_section_review_' + field for field in FIELDS)
ROOT_NAME_V4 = 'content_units_v4'
FLOW_V5 = 'memo-source-unit-flow-v5'
FLOW_V6 = 'memo-source-unit-flow-v6'
FLOW_V7 = 'memo-source-unit-flow-v7'
FLOW_V8 = 'memo-source-unit-flow-v8'
FLOW_V9 = 'memo-source-unit-flow-v9'
FLOW_V10 = 'memo-source-unit-flow-v10'
FLOW_V11 = 'memo-source-unit-flow-v11'
FLOW_V12 = 'memo-source-unit-flow-v12'
CORE_PAIRS_V6 = {('memo-section-units-author-v13', 'memo-section-units-review-v12')}
CORE_PAIRS_V5 = {('memo-section-units-author-v9', 'memo-section-units-review-v8'),
                 ('memo-section-units-author-v10', 'memo-section-units-review-v9'),
                 ('memo-section-units-author-v11', 'memo-section-units-review-v10'),
                 ('memo-section-units-author-v12', 'memo-section-units-review-v11'),
                 ('memo-section-units-author-v13', 'memo-section-units-review-v12')}
COVERAGE_PHASES_V5 = tuple('diligence_coverage_' + str(number) for number in range(1, 6)) + ('diligence_field_selection',)
PHASES_V5 = COVERAGE_PHASES_V5 + PHASES_V4
COVERAGE_PHASES_V6 = COVERAGE_PHASES_V5[:5] + ('diligence_source_adjudication', 'diligence_field_selection')
PHASES_V6 = COVERAGE_PHASES_V6 + PHASES_V4
COVERAGE_PHASES_V7 = COVERAGE_PHASES_V5[:5] + tuple(
    'diligence_source_adjudication_' + str(number) for number in range(1, 6)) + ('diligence_field_selection',)
PHASES_V7 = COVERAGE_PHASES_V7 + PHASES_V4
COVERAGE_PHASES_V8 = COVERAGE_PHASES_V7
PHASES_V8 = COVERAGE_PHASES_V8 + PHASES_V4
COVERAGE_PHASES_V9 = COVERAGE_PHASES_V8
PHASES_V9 = COVERAGE_PHASES_V9 + PHASES_V4
COVERAGE_PHASES_V10 = COVERAGE_PHASES_V9[5:]
PHASES_V10 = COVERAGE_PHASES_V10 + PHASES_V4
COVERAGE_PHASES_V11 = COVERAGE_PHASES_V10
PHASES_V11 = COVERAGE_PHASES_V11 + PHASES_V4
COVERAGE_PHASES_V12 = tuple('diligence_source_pair_' + str(number) for number in range(1, 26)) + ('diligence_field_selection',)
PHASES_V12 = COVERAGE_PHASES_V12 + PHASES_V4
ROOT_NAME_V5 = 'content_units_v5'
ROOT_NAME_V6 = 'content_units_v6'
ROOT_NAME_V7 = 'content_units_v7'
ROOT_NAME_V8 = 'content_units_v8'
ROOT_NAME_V9 = 'content_units_v9'
ROOT_NAME_V10 = 'content_units_v10'
ROOT_NAME_V11 = 'content_units_v11'
ROOT_NAME_V12 = 'content_units_v12'


def flow_config(flow_contract):
    if flow_contract == FLOW:
        return PHASES, ROOT_NAME
    if flow_contract == FLOW_V2:
        return PHASES_V2, ROOT_NAME_V2
    if flow_contract == FLOW_V3:
        return PHASES_V3, ROOT_NAME_V3
    if flow_contract == FLOW_V4:
        return PHASES_V4, ROOT_NAME_V4
    if flow_contract == FLOW_V5:
        return PHASES_V5, ROOT_NAME_V5
    if flow_contract == FLOW_V6:
        return PHASES_V6, ROOT_NAME_V6
    if flow_contract == FLOW_V7:
        return PHASES_V7, ROOT_NAME_V7
    if flow_contract == FLOW_V8:
        return PHASES_V8, ROOT_NAME_V8
    if flow_contract == FLOW_V9:
        return PHASES_V9, ROOT_NAME_V9
    if flow_contract == FLOW_V10:
        return PHASES_V10, ROOT_NAME_V10
    if flow_contract == FLOW_V11:
        return PHASES_V11, ROOT_NAME_V11
    if flow_contract == FLOW_V12:
        return PHASES_V12, ROOT_NAME_V12
    raise ValueError('Unknown source unit flow contract')


def _role(profile):
    roles = profile['profiles']
    role = 'challenge' if roles.get('challenge') else 'review'
    name = roles[role]
    validate_local_model_name(name)
    expected = (profile.get('memo_role_model_digests') or {}).get(role)
    if role == 'review':
        expected = expected or profile.get('memo_causal_review_model_digest')
    return name, expected


def _core_role(profile, section_author_contract):
    role = 'author' if section_author_contract in {'memo-section-units-author-v6', 'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} else 'draft'
    name = profile['profiles'][role]
    validate_local_model_name(name)
    expected = (profile.get('memo_role_model_digests') or {}).get(role)
    if role == 'author':
        expected = expected or profile.get('memo_author_model_digest')
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('Independent core author requires exact frozen role digest')
    return name, expected


def _core_review_role(profile):
    name = profile['profiles']['review']
    validate_local_model_name(name)
    expected = (profile.get('memo_role_model_digests') or {}).get('review') or profile.get('memo_causal_review_model_digest')
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('Independent core reviewer requires exact frozen role digest')
    return name, expected


def _coverage_role(profile, role):
    if (not isinstance(role, str) or not role or role not in profile['profiles']):
        raise ValueError('Coverage requires an explicit configured local profile role')
    name = profile['profiles'][role]
    validate_local_model_name(name)
    expected = (profile.get('memo_role_model_digests') or {}).get(role)
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('Coverage requires its own exact frozen role digest')
    return name, expected


def _request(root, accepted, sources, profile, *, create=False, author_contract=None, flow_contract=FLOW, section_author_contract=None, section_review_contract=None, coverage_structures=None, coverage_financial_scope=None, coverage_contract=None, coverage_role=None, coverage_adjudicator_role=None, coverage_batching_contract=None):
    flow_config(flow_contract)
    independent_adjudicator = coverage_contract in {'diligence-source-coverage-v14', 'diligence-source-coverage-v15', 'diligence-source-coverage-v16', 'diligence-source-coverage-v17', 'diligence-source-coverage-v18', 'diligence-source-coverage-v19', 'diligence-source-coverage-v20'}
    if independent_adjudicator:
        if not isinstance(coverage_adjudicator_role, str) or not coverage_adjudicator_role:
            raise ValueError('Independent adjudication requires an explicit configured profile role')
    elif coverage_adjudicator_role is not None:
        raise ValueError('Historical coverage cannot add an adjudicator role')
    if flow_contract == FLOW_V12 and (coverage_contract != 'diligence-source-coverage-v20'
            or (section_author_contract, section_review_contract) not in CORE_PAIRS_V6):
        raise ValueError('Separate source tasks require exact coverage20/core13/reviewer12 contracts')
    if flow_contract == FLOW_V11 and (coverage_contract != 'diligence-source-coverage-v19'
            or (section_author_contract, section_review_contract) not in CORE_PAIRS_V6):
        raise ValueError('Evidence-first interpretation requires exact coverage19/core13/reviewer12 contracts')
    if flow_contract == FLOW_V10 and (coverage_contract != 'diligence-source-coverage-v18'
            or (section_author_contract, section_review_contract) not in CORE_PAIRS_V6):
        raise ValueError('Fixed category decisions require exact coverage18/core13/reviewer12 contracts')
    if flow_contract == FLOW_V9 and (coverage_contract != 'diligence-source-coverage-v17'
            or (section_author_contract, section_review_contract) not in CORE_PAIRS_V6):
        raise ValueError('Supported blind topics require exact coverage17/core13/reviewer12 contracts')
    if flow_contract == FLOW_V8 and (coverage_contract != 'diligence-source-coverage-v16'
            or (section_author_contract, section_review_contract) not in CORE_PAIRS_V6):
        raise ValueError('Blind group assessment requires exact coverage16/core13/reviewer12 contracts')
    if flow_contract == FLOW_V7 and (coverage_contract != 'diligence-source-coverage-v15'
            or (section_author_contract, section_review_contract) not in CORE_PAIRS_V6):
        raise ValueError('Sharded adjudication requires exact coverage15/core13/reviewer12 contracts')
    if flow_contract == FLOW_V6 and (coverage_contract not in {'diligence-source-coverage-v12', 'diligence-source-coverage-v13', 'diligence-source-coverage-v14'}
            or (section_author_contract, section_review_contract) not in CORE_PAIRS_V6):
        raise ValueError('Split adjudication requires exact coverage12/13/14/15/core13/reviewer12 contracts')
    if flow_contract == FLOW_V5 and coverage_contract in {'diligence-source-coverage-v12', 'diligence-source-coverage-v13', 'diligence-source-coverage-v14', 'diligence-source-coverage-v15', 'diligence-source-coverage-v16', 'diligence-source-coverage-v17', 'diligence-source-coverage-v18', 'diligence-source-coverage-v19', 'diligence-source-coverage-v20'}:
        raise ValueError('Split adjudication cannot downgrade to historical FLOW5')
    if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        if (author_contract != 'memo-source-unit-author-v7'
                or (section_author_contract, section_review_contract) not in CORE_PAIRS_V5):
            raise ValueError('All-source coverage flow requires exact v7/v9/v8 authors and reviewer')
    elif section_author_contract in {'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} or coverage_structures is not None or coverage_financial_scope is not None or coverage_contract is not None or coverage_role is not None:
        raise ValueError('All-source coverage cannot downgrade to a historical flow')
    if ((flow_contract in (FLOW_V2, FLOW_V3, FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12) and author_contract != 'memo-source-unit-author-v7') or
            (flow_contract == FLOW and author_contract == 'memo-source-unit-author-v7')):
        raise ValueError('Source unit author contract does not match frozen flow')
    base = {'flow_contract': flow_contract, 'memo': Memo.model_validate(accepted['memo']).model_dump(mode='json'),
            'sources': [Source.model_validate(row).model_dump(mode='json') for row in sources]}
    if flow_contract == FLOW_V11:
        base['coverage_batching_contract'] = coverage_batching_contract or 'source-interpretation-evidence-first-v2'
        if base['coverage_batching_contract'] not in {'source-interpretation-evidence-first-v2', 'source-interpretation-evidence-first-v3', 'source-interpretation-evidence-first-v4', 'source-interpretation-evidence-first-v5'}:
            raise ValueError('Unknown source interpretation batching contract')
    elif flow_contract == FLOW_V12:
        base['coverage_batching_contract'] = coverage_batching_contract or 'source-interpretation-pair-v1'
        if base['coverage_batching_contract'] not in {'source-interpretation-pair-v1', 'source-interpretation-pair-v2'}:
            raise ValueError('Separate source tasks require their exact pair contract')
    elif coverage_batching_contract is not None:
        raise ValueError('Source interpretation version requires FLOW11/12')
    if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        from agents.research.diligence_coverage import CONTRACT
        structures = {} if coverage_structures is None else coverage_structures
        base.update(coverage_contract=coverage_contract or CONTRACT, coverage_structures=structures)
        if coverage_role is not None:
            base['coverage_role'] = coverage_role
        if independent_adjudicator:
            base['coverage_adjudicator_role'] = coverage_adjudicator_role
    if author_contract is not None:
        if author_contract not in {'memo-source-unit-author-v2', 'memo-source-unit-author-v3', 'memo-source-unit-author-v4', 'memo-source-unit-author-v5', 'memo-source-unit-author-v6', 'memo-source-unit-author-v7'}:
            raise ValueError('Unknown source unit author contract')
        base['author_contract'] = author_contract
    if section_author_contract is not None:
        if flow_contract not in (FLOW_V3, FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12) or section_author_contract not in {'memo-section-units-author-v2', 'memo-section-units-author-v3', 'memo-section-units-author-v4', 'memo-section-units-author-v5', 'memo-section-units-author-v6', 'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'}:
            raise ValueError('Unknown section author contract for source unit flow')
        base['section_author_contract'] = section_author_contract
    if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and section_author_contract not in {'memo-section-units-author-v3', 'memo-section-units-author-v4', 'memo-section-units-author-v5', 'memo-section-units-author-v6', 'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'}:
        raise ValueError('Independent author flow requires structured section author')
    if flow_contract not in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and section_author_contract in {'memo-section-units-author-v4', 'memo-section-units-author-v5', 'memo-section-units-author-v6', 'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'}:
        raise ValueError('Bounded section author requires independent author flow')
    if section_review_contract is not None:
        if not ((flow_contract == FLOW_V4 and section_author_contract == 'memo-section-units-author-v8' and section_review_contract == 'memo-section-units-review-v7') or
                (flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and (section_author_contract, section_review_contract) in CORE_PAIRS_V5)):
            raise ValueError('Unknown section reviewer contract for source unit flow')
        base['section_review_contract'] = section_review_contract
    name, expected = _role(profile)
    core_name = core_expected = None
    if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        core_name, core_expected = _core_role(profile, section_author_contract)
    coverage_name, coverage_expected = core_name, core_expected
    adjudicator_name = adjudicator_expected = None
    if independent_adjudicator:
        adjudicator_name, adjudicator_expected = _coverage_role(profile, coverage_adjudicator_role)
    adjudicator_kwargs = ({'adjudicator_pin': {'name': adjudicator_name, 'digest': adjudicator_expected}}
                          if independent_adjudicator else {})
    if flow_contract in {FLOW_V11, FLOW_V12}:
        adjudicator_kwargs['interpretation_contract'] = base['coverage_batching_contract']
    if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        if coverage_role is not None:
            coverage_name, coverage_expected = _coverage_role(profile, coverage_role)
        from agents.research.diligence_coverage import frozen_coverage_requests
        coverage_requests = frozen_coverage_requests(base['sources'], {'name': coverage_name, 'digest': coverage_expected},
                                 structures=base['coverage_structures'], financial_scope=coverage_financial_scope,
                                 contract=base['coverage_contract'], **adjudicator_kwargs)
        base['coverage_financial_scope'] = coverage_requests[0][2]['financial_evidence_scope']
    pin_keys = ('characterizer_pin', 'author_pin', 'reviewer_pin')
    if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        pin_keys += ('core_author_pin',)
    if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        pin_keys += ('coverage_pin',)
    if independent_adjudicator:
        pin_keys += ('coverage_adjudicator_pin',)
    core_review_name = core_review_expected = None
    if section_author_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'}:
        core_review_name, core_review_expected = _core_review_role(profile)
        pin_keys += ('core_reviewer_pin',)
    path = root / 'content_request.json'
    if path.exists():
        request = json.loads(path.read_text())
        if (set(request) != set(base) | set(pin_keys) | {'digest'} or
                request['digest'] != digest({key: value for key, value in request.items() if key != 'digest'}) or
                any(request.get(key) != value for key, value in base.items())):
            raise ValueError('Source unit content request changed')
        pins = [request[key] for key in ('characterizer_pin', 'author_pin', 'reviewer_pin')]
        pin = pins[0]
        if (not isinstance(pin, dict) or set(pin) != {'name', 'digest'} or pin['name'] != name or
                not isinstance(pin['digest'], str) or len(pin['digest']) != 64 or
                any(other != pin for other in pins) or (expected is not None and pin['digest'] != expected)):
            raise ValueError('Source unit roles differ from frozen local profile')
        if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and request['core_author_pin'] != {'name': core_name, 'digest': core_expected}:
            raise ValueError('Core author differs from frozen local core profile')
        if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and request['coverage_pin'] != {'name': coverage_name, 'digest': coverage_expected}:
            raise ValueError('Coverage differs from its frozen local profile role')
        if independent_adjudicator and request['coverage_adjudicator_pin'] != adjudicator_kwargs['adjudicator_pin']:
            raise ValueError('Coverage adjudicator differs from its frozen local profile role')
        if section_author_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} and request['core_reviewer_pin'] != {'name': core_review_name, 'digest': core_review_expected}:
            raise ValueError('Core reviewer differs from frozen local review profile')
        return request
    if not create:
        raise ValueError('Source unit content gate is missing')
    installed = _inventory()
    value = installed.get(name)
    if not isinstance(value, str) or len(value) != 64 or (expected is not None and value != expected):
        raise ValueError('Source unit flow requires installed frozen local review role')
    pin = {'name': name, 'digest': value}
    request = {**base, 'characterizer_pin': pin, 'author_pin': pin, 'reviewer_pin': pin}
    if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
        if installed.get(core_name) != core_expected:
            raise ValueError('Independent core author requires installed frozen local core role')
        request['core_author_pin'] = {'name': core_name, 'digest': core_expected}
        if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
            if installed.get(coverage_name) != coverage_expected:
                raise ValueError('Coverage requires its installed frozen local profile role')
            request['coverage_pin'] = {'name': coverage_name, 'digest': coverage_expected}
    if independent_adjudicator:
        if installed.get(adjudicator_name) != adjudicator_expected:
            raise ValueError('Adjudicator requires its installed frozen local profile role')
        request['coverage_adjudicator_pin'] = adjudicator_kwargs['adjudicator_pin']
    if section_author_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'}:
        if installed.get(core_review_name) != core_review_expected:
            raise ValueError('Independent core reviewer requires installed frozen local review role')
        request['core_reviewer_pin'] = {'name': core_review_name, 'digest': core_review_expected}
    request['digest'] = digest(request)
    _write(path, request)
    return request


def _history(root, *, accepted=False, flow_contract=FLOW):
    phases, _ = flow_config(flow_contract)
    file = root / 'content_passes.json'
    rows = json.loads(file.read_text()) if file.exists() else []
    if not isinstance(rows, list) or len(rows) > len(phases):
        raise ValueError('Source unit flow exceeds its fixed phase passes')
    for number, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or set(row) != {'pass', 'phase', 'state'} or
                type(row['pass']) is not int or row['pass'] != number or row['phase'] != phases[number - 1]):
            raise ValueError('Source unit flow pass history changed')
    if accepted and (len(rows) != len(phases) or [row['state'] for row in rows] != ['needs_resume'] * (len(phases) - 1) + ['accepted']):
        raise ValueError('Source unit acceptance requires completed ordered phases')
    return rows


def replay_source_unit_gate(memo_root, accepted, sources, profile, *, author_contract=None, flow_contract=FLOW, section_author_contract=None, section_review_contract=None, coverage_structures=None, coverage_financial_scope=None, coverage_contract=None, coverage_role=None, coverage_adjudicator_role=None, coverage_batching_contract=None):
    phases, root_name = flow_config(flow_contract)
    root = Path(memo_root) / root_name
    request = _request(root, accepted, sources, profile, author_contract=author_contract, flow_contract=flow_contract,
                       section_author_contract=section_author_contract, section_review_contract=section_review_contract, coverage_structures=coverage_structures, coverage_financial_scope=coverage_financial_scope, coverage_contract=coverage_contract, coverage_role=coverage_role, coverage_adjudicator_role=coverage_adjudicator_role, coverage_batching_contract=coverage_batching_contract)
    result = json.loads((root / 'content_result.json').read_text())
    if result.get('state') != 'accepted':
        raise ValueError('Material requires accepted source unit content gate')
    _history(root, accepted=True, flow_contract=flow_contract)
    from scripts.private_source_unit_worker import load_source_unit_revision, replay_source_unit_revision
    revision = load_source_unit_revision(root)
    if (revision.get('request_digest') != request['digest'] or
            revision.get('contract') != request['flow_contract'] or
            revision.get('author_contract') != request.get('author_contract') or
            revision.get('section_author_contract') != request.get('section_author_contract') or
            revision.get('section_review_contract') != request.get('section_review_contract') or
            any(revision.get(key) != request[key] for key in
                (('characterizer_pin', 'author_pin', 'reviewer_pin', 'core_author_pin', *(('core_reviewer_pin',) if section_author_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} else ())) if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else
                 ('characterizer_pin', 'author_pin', 'reviewer_pin')))):
        raise ValueError('Source unit replay roles differ from frozen production request')
    if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and any(revision.get(key) != request[key] for key in ('coverage_pin', 'coverage_contract', 'coverage_structures', 'coverage_financial_scope', *(('coverage_role',) if 'coverage_role' in request else ()))):
        raise ValueError('All-source coverage replay differs from the frozen production request')
    if flow_contract in {FLOW_V11, FLOW_V12} and revision.get('coverage_batching_contract') != request['coverage_batching_contract']:
        raise ValueError('Atomic coverage replay changed its frozen batching contract')
    if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and revision.get('coverage_role') != request.get('coverage_role'):
        raise ValueError('All-source coverage replay changed its frozen profile role')
    if any(revision.get(key) != request.get(key) for key in ('coverage_adjudicator_role', 'coverage_adjudicator_pin')):
        raise ValueError('All-source coverage replay changed its frozen adjudicator role')
    revised, gate = replay_source_unit_revision(request['memo'], request['sources'], revision)
    revised = Memo.model_validate(revised)
    if flow_contract in {FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and (gate.get('contract') != flow_contract
            or gate.get('coverage_contract') != request['coverage_contract']):
        raise ValueError('Split adjudication gate differs from its frozen flow/coverage contract')
    if flow_contract in {FLOW_V11, FLOW_V12} and gate.get('coverage_batching_contract') != request['coverage_batching_contract']:
        raise ValueError('Atomic source gate changed its frozen batching contract')
    if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and gate.get('core_author_pin') != request['core_author_pin']:
        raise ValueError('Source unit gate changed its frozen core author role')
    if section_author_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} and gate.get('core_reviewer_pin') != request['core_reviewer_pin']:
        raise ValueError('Source unit gate changed its frozen core reviewer role')
    if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and (gate.get('coverage_pin') != request['coverage_pin']
            or gate.get('coverage_role') != request.get('coverage_role')):
        raise ValueError('Source unit gate changed its frozen coverage role')
    if any(gate.get(key) != request.get(key) for key in ('coverage_adjudicator_role', 'coverage_adjudicator_pin')):
        raise ValueError('Source unit gate changed its frozen adjudicator role')
    if section_review_contract is not None and gate.get('section_review_contract') != section_review_contract:
        raise ValueError('Source unit gate changed its frozen section reviewer contract')
    if (section_author_contract is not None and gate.get('section_author_contract') != section_author_contract):
        raise ValueError('Source unit gate changed its frozen section author contract')
    if (result.get('final_memo_digest') != digest(revised.model_dump(mode='json')) or
            result.get('content_review') != gate):
        raise ValueError('Source unit result differs from exact replay')
    return revised, revision, gate


def run_source_unit_pass(memo_root, accepted, sources, profile, *, timeout, author_contract=None, flow_contract=FLOW, section_author_contract=None, section_review_contract=None, coverage_structures=None, coverage_financial_scope=None, coverage_contract=None, coverage_role=None, coverage_adjudicator_role=None, coverage_batching_contract=None):
    started = time.monotonic()
    phases, root_name = flow_config(flow_contract)
    root = Path(memo_root) / root_name
    root.mkdir(mode=0o700, exist_ok=True)
    try:
        request = _request(root, accepted, sources, profile, create=True, author_contract=author_contract, flow_contract=flow_contract,
                       section_author_contract=section_author_contract, section_review_contract=section_review_contract, coverage_structures=coverage_structures, coverage_financial_scope=coverage_financial_scope, coverage_contract=coverage_contract, coverage_role=coverage_role, coverage_adjudicator_role=coverage_adjudicator_role, coverage_batching_contract=coverage_batching_contract)
    except (OSError, TimeoutError):
        return {'state': 'needs_resume', 'reason': 'local_model_inventory_unavailable'}
    except (ValueError, KeyError, TypeError):
        return {'state': 'blocked', 'reason': 'source_unit_request_changed'}
    file = root / 'content_result.json'
    result = json.loads(file.read_text()) if file.exists() else {}
    if result.get('state') not in {'accepted', 'blocked'}:
        history = _history(root, flow_contract=flow_contract)
        phase = result.get('next_phase', phases[0])
        recovering = flow_contract == FLOW_V12 and result.get('reason') == 'interrupted_between_committed_calls'
        if len(history) >= len(phases) and not recovering:
            return {'state': 'blocked', 'reason': 'bounded_source_unit_passes_exhausted'}
        expected_index = len(history) - 1 if recovering else len(history)
        allowed_history = history[:-1] if recovering else history
        if (phase != phases[expected_index] or any(row['state'] != 'needs_resume' for row in allowed_history)
                or recovering and history[-1]['state'] != 'interrupted_between_committed_calls'):
            return {'state': 'blocked', 'reason': 'source_unit_phase_incomplete'}
        remaining = timeout - (time.monotonic() - started)
        if remaining < 10:
            return {'state': 'needs_resume', 'reason': 'room_pass_time_limit'}
        try:
            installed = _inventory()
        except (OSError, TimeoutError):
            return {'state': 'needs_resume', 'reason': 'local_model_inventory_unavailable'}
        pin = request['coverage_adjudicator_pin'] if phase.startswith(('diligence_source_adjudication', 'diligence_source_pair')) and 'coverage_adjudicator_pin' in request else request['coverage_pin'] if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and phase in (COVERAGE_PHASES_V12 if flow_contract == FLOW_V12 else COVERAGE_PHASES_V10 if flow_contract in {FLOW_V10, FLOW_V11, FLOW_V12} else COVERAGE_PHASES_V7 if flow_contract in {FLOW_V7, FLOW_V8, FLOW_V9} else COVERAGE_PHASES_V6 if flow_contract == FLOW_V6 else COVERAGE_PHASES_V5) else request['core_reviewer_pin'] if section_author_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} and phase.startswith('memo_section_review_') else request['core_author_pin'] if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} and phase.startswith('memo_section_author_') else request['reviewer_pin']
        if installed.get(pin['name']) != pin['digest']:
            return {'state': 'blocked', 'reason': 'source_unit_installed_model_changed'}
        seconds = min(105, remaining - 8)
        if recovering:
            from scripts.private_source_unit_worker import source_pair_recovery_budget
            seconds = min(seconds, source_pair_recovery_budget(root, request, result))
        else:
            history.append({'pass': len(history) + 1, 'phase': phase, 'state': 'started'})
        _write(root / 'content_passes.json', history)
        _write(root / 'content_budget.json', {'seconds': seconds, 'max_calls': 6})
        child_started = time.monotonic()
        try:
            run_private([sys.executable, PROJECT / 'scripts/private_source_unit_worker.py'], root,
                        timeout=remaining, extra_read=(PROJECT / 'agents', PROJECT / 'schemas.py'), local_model=True)
            result = json.loads(file.read_text())
        except (TimeoutError, RuntimeError):
            if flow_contract == FLOW_V12:
                from scripts.private_source_unit_worker import record_source_pair_interruption
                interrupted = record_source_pair_interruption(root, request, phase, time.monotonic() - child_started)
                if interrupted['state'] == 'needs_resume':
                    history[-1]['state'] = 'interrupted_between_committed_calls'
                    _write(root / 'content_passes.json', history)
                    _write(file, interrupted)
                    return {**interrupted, 'content_revision_path': str(root), 'content_flow_contract': flow_contract}
            history[-1]['state'] = 'worker_error'
            _write(root / 'content_passes.json', history)
            return {'state': 'blocked', 'reason': 'source_unit_worker_interrupted'}
        history[-1]['state'] = result.get('state')
        _write(root / 'content_passes.json', history)
        if result.get('state') == 'needs_resume' and result.get('next_phase') != phases[min(len(history), len(phases) - 1)]:
            return {'state': 'blocked', 'reason': 'source_unit_phase_incomplete'}
    if result.get('state') != 'accepted':
        pending_result = {'state': 'blocked' if result.get('state') == 'blocked' else 'needs_resume',
                'reason': result.get('reason', 'next_bounded_source_unit_phase'),
                'content_revision_path': str(root), 'content_flow_contract': flow_contract,
                'independent_review': 'pending',
                **({'content_core_author_pin': request['core_author_pin']} if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else {}),
                **({'content_core_reviewer_pin': request['core_reviewer_pin']} if section_author_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} else {}), 'content_phase': result.get('next_phase'),
                **({'content_author_contract': author_contract} if author_contract is not None else {}),
                **({'content_section_review_contract': section_review_contract} if section_review_contract is not None else {}),
                **({'content_section_author_contract': section_author_contract} if section_author_contract is not None else {})}
        if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12}:
            status = result.get('diligence_coverage')
            return {**pending_result, 'content_diligence_coverage': status,
                    'content_coverage_pin': request['coverage_pin'],
                    **({'content_coverage_adjudicator_pin': request['coverage_adjudicator_pin'],
                        'content_coverage_adjudicator_role': request['coverage_adjudicator_role']}
                       if 'coverage_adjudicator_pin' in request else {}),
                    **({'content_coverage_role': request['coverage_role']} if 'coverage_role' in request else {})}
        return pending_result
    revised, revision, gate = replay_source_unit_gate(memo_root, accepted, sources, profile, author_contract=author_contract, flow_contract=flow_contract,
                       section_author_contract=section_author_contract, section_review_contract=section_review_contract, coverage_structures=coverage_structures, coverage_financial_scope=coverage_financial_scope, coverage_contract=coverage_contract, coverage_role=coverage_role, coverage_adjudicator_role=coverage_adjudicator_role, coverage_batching_contract=coverage_batching_contract)
    return {'state': 'accepted', 'memo': revised.model_dump(mode='json'), 'content_revision': revision,
            'content_review': gate, 'content_revision_path': str(root), 'content_flow_contract': flow_contract,
            'independent_review': 'pending',
                **({'content_diligence_coverage': gate['diligence_coverage'], 'content_coverage_pin': request['coverage_pin'],
                    **({'content_coverage_adjudicator_pin': request['coverage_adjudicator_pin'],
                        'content_coverage_adjudicator_role': request['coverage_adjudicator_role']}
                       if 'coverage_adjudicator_pin' in request else {}),
                    **({'content_coverage_role': request['coverage_role']} if 'coverage_role' in request else {})} if flow_contract in {FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else {}),
                **({'content_core_author_pin': request['core_author_pin']} if flow_contract in {FLOW_V4, FLOW_V5, FLOW_V6, FLOW_V7, FLOW_V8, FLOW_V9, FLOW_V10, FLOW_V11, FLOW_V12} else {}),
                **({'content_core_reviewer_pin': request['core_reviewer_pin']} if section_author_contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8', 'memo-section-units-author-v9', 'memo-section-units-author-v10', 'memo-section-units-author-v11', 'memo-section-units-author-v12', 'memo-section-units-author-v13'} else {}),
                **({'content_author_contract': author_contract} if author_contract is not None else {}),
                **({'content_section_review_contract': section_review_contract} if section_review_contract is not None else {}),
                **({'content_section_author_contract': section_author_contract} if section_author_contract is not None else {})}
