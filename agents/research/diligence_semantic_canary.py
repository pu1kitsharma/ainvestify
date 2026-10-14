"""Fictional held-out boundary checks; never a company answer or release gate."""
from __future__ import annotations

import json
from pathlib import Path
import re

from agents.inference.model_authorship import digest
from agents.research import diligence_coverage as coverage


CONTRACT_V1 = 'diligence-semantic-canary-v1'
CONTRACT_V2 = 'diligence-semantic-canary-v2'
CONTRACT = CONTRACT_V2
TASK_V1 = 'diligence_semantic_boundary_canary_v1'
TASK_V2 = 'diligence_semantic_boundary_canary_v2'
TASK = TASK_V2
FIXTURE = Path(__file__).resolve().parents[2] / 'evals/investment_preparation/diligence-semantic-canary-v1.json'
FIXTURES = {CONTRACT_V1: FIXTURE, CONTRACT_V2: FIXTURE.with_name('diligence-semantic-canary-v2.json')}
OPTIONS = {
    'thinking': True, 'reasoning_budget': 192, 'max_tokens': 892,
    # Qwen's native thinking guidance uses 0.6; freeze before any live record.
    'context_tokens': 4096, 'temperature': 0.6, 'bound_strings': True,
    'compact_prompt': True, 'require_full_context': True, 'factual_sampling': True,
    'bounded_thinking_contract': 'local-bounded-thinking-v1',
}
FULL_THINKING_9B = 'qwen3.5-9b-full-thinking-v1'
PROFILES = {FULL_THINKING_9B: {
    'model': 'qwen3.5:9b',
    'options': {**OPTIONS, 'reasoning_budget': 1024, 'max_tokens': 1724,
                'context_tokens': 6144, 'temperature': 1.0},
    'sampling': {'top_p': 0.95, 'top_k': 20, 'min_p': 0,
                 'presence_penalty': 0, 'repeat_penalty': 1},
}}
QUALIFIED_BOUNDARIES = [
    'heading_and_contact', 'product_vs_market', 'financial_and_market',
    'plan_vs_adverse_risk', 'capital_vs_sales', 'omission_vs_explicit_unknown',
]
UNTESTED_POSITIVE_CATEGORIES = ['identity', 'team_and_governance', 'legal_and_compliance', 'opposing_evidence']


def canary_fixture(contract=CONTRACT):
    if contract not in FIXTURES:
        raise ValueError('Unknown synthetic canary contract')
    value = json.loads(FIXTURES[contract].read_text())
    cases = value['cases']
    if (value['contract'] != contract or len(cases) != 10 or
            len({case['id'] for case in cases}) != 10):
        raise ValueError('Synthetic canary fixture contract changed')
    categories = set(coverage.CATEGORIES)
    for case in cases:
        expected = case['expected']
        if (set(expected) != {'kinds', 'required', 'allowed'} or
                not set(expected['required']) <= set(expected['allowed']) <= categories or
                not expected['kinds'] or not set(expected['kinds']) <= {
                    'information', 'structured_information', 'heading_only', 'contact_only'}):
            raise ValueError('Every synthetic case needs complete category allowances')
    return value


def _batch_sources(cases, first):
    return [{'id': 'S' + str(index), 'url': 'https://example.invalid/canary/' + str(index),
             'title': 'Fictional input ' + str(index), 'passage': case['passage'],
             'version': digest(case['passage']), 'attribution': 'Fictional qualification input'}
            for index, case in enumerate(cases, first)]


def canary_options(pin, *, contract=CONTRACT, profile=None):
    if profile is None:
        return dict(OPTIONS)
    if (contract != CONTRACT_V2 or profile not in PROFILES or
            pin.get('name') != PROFILES[profile]['model']):
        raise ValueError('Synthetic capacity profile requires its exact model and V2 contract')
    return dict(PROFILES[profile]['options'])


def frozen_canary_requests(pin, *, contract=CONTRACT, profile=None):
    """Five two-source requests; independent expectations never enter prompts."""
    fixture = canary_fixture(contract)
    options = canary_options(pin, contract=contract, profile=profile)
    requests = []
    for checkpoint, first in enumerate(range(0, len(fixture['cases']), 2), 1):
        cases = fixture['cases'][first:first + 2]
        sources = _batch_sources(cases, first + 1)
        _, instruction, offered, schema = coverage.frozen_coverage_requests(
            sources, pin, contract=coverage.CONTRACT_V18, adjudicator_pin=pin)[0]
        payload = {
            'contract': contract, 'checkpoint': checkpoint, 'model_pin': dict(pin),
            'options': dict(options), 'groups': offered['groups'],
            'category_aliases': offered['category_aliases'],
            'category_definitions': offered['category_definitions'],
            'financial_evidence_scope': offered['financial_evidence_scope'],
            'processing_metadata': {'S' + str(index): case['processing_metadata']
                for index, case in enumerate(cases, first + 1) if 'processing_metadata' in case},
            'input_binding_digest': digest({'fixture_digest': digest(fixture), 'sources': sources,
                'model_pin': pin, 'options': options, 'checkpoint': checkpoint,
                'schema': schema.model_json_schema()}),
        }
        if profile is not None:
            payload['profile'] = profile
            payload['expected_sampling'] = dict(PROFILES[profile]['sampling'])
        requests.append((TASK_V1 if contract == CONTRACT_V1 else TASK_V2, instruction, payload, schema))
    return requests


def score_required_statuses(answer, expected, aliases, absent='N'):
    """Claude-authored generic scorer, corrected to the actual E001 wire type.

    Expectations are independently audited fictional controls, outside inference.
    This helper never repairs model output or supplies production topic decisions.
    """
    fixed_fields = ('kind', 'use', 'proof', 'why')
    failures = []
    if not isinstance(answer, dict):
        return ['answer is not an object']
    for gid in sorted(set(expected) - set(answer)):
        failures.append('%s: group missing' % gid)
    for gid in sorted(set(answer) - set(expected)):
        failures.append('%s: unexpected group' % gid)
    known_keys = set(fixed_fields) | set(aliases)
    for gid in sorted(set(expected) & set(answer)):
        group, exp = answer[gid], expected[gid]
        if not isinstance(group, dict):
            failures.append('%s: group is not an object' % gid)
            continue
        for field in fixed_fields:
            if field not in group:
                failures.append('%s: field missing: %s' % (gid, field))
        for key in sorted(set(group) - known_keys):
            failures.append('%s: unknown key: %s' % (gid, key))
        if group.get('kind') not in exp['kinds']:
            failures.append('%s: kind not in expected kinds' % gid)
        present = set()
        for alias in sorted(aliases):
            if alias not in group:
                failures.append('%s: alias missing: %s' % (gid, alias))
                continue
            status = group[alias]
            if not isinstance(status, str):
                failures.append('%s: invalid status type: %s' % (gid, alias))
            elif status != absent:
                if re.fullmatch(r'E[0-9]{3}', status) is None or int(status[1:]) < 1:
                    failures.append('%s: invalid status value: %s' % (gid, alias))
                else:
                    present.add(aliases[alias])
        for category in sorted(set(exp['required']) - present):
            failures.append('%s: required category absent: %s' % (gid, category))
        for category in sorted(present - set(exp['allowed'])):
            failures.append('%s: category not allowed: %s' % (gid, category))
        allowed_uses = ({'relevant', 'context_only'} if group.get('kind') in {
            'information', 'structured_information'} else {'irrelevant', 'context_only'})
        if group.get('use') not in allowed_uses:
            failures.append('%s: unambiguous control remains unresolved or unusable' % gid)
    return failures


def evaluate_canary(pin, attempts, *, contract=CONTRACT, profile=None):
    """Replay actual raw model answers and score all ten category choices."""
    from agents.inference.local_models import validate_bounded_thinking_receipts, bounded_thinking_input_binding
    options = canary_options(pin, contract=contract, profile=profile)
    fixture, requests = canary_fixture(contract), frozen_canary_requests(pin, contract=contract, profile=profile)
    base = {'contract': contract, 'model_pin': dict(pin), 'fixture_digest': digest(fixture),
            'options': dict(options), 'qualified_boundaries': QUALIFIED_BOUNDARIES,
            'untested_positive_categories': UNTESTED_POSITIVE_CATEGORIES,
            'private_context_qualification': 'not_established', 'investor_approval': 'not_established',
            'attempt_digest': digest(attempts), 'completed_checkpoints': 0, 'scored_cases': []}
    if profile is not None:
        base['profile'] = profile
    if len(attempts) > 5 or len({row.get('id') for row in attempts}) != len(attempts):
        return {**base, 'state': 'blocked', 'reason': 'canary_response_identity_or_call_bound'}
    failures = []
    try:
        for index, row in enumerate(attempts):
            request = requests[index]
            if row.get('model') != pin['name'] or row.get('routing', {}).get('model') != pin['name']:
                raise ValueError('Canary model role changed')
            if profile is not None and row.get('routing', {}).get('sampling') != PROFILES[profile]['sampling']:
                raise ValueError('Canary capacity profile sampling changed')
            answer = coverage._check_row(row, request)
            known_binding = bounded_thinking_input_binding(request[1], request[2], request[3],
                compact_prompt=options['compact_prompt'], bound_strings=options['bound_strings'])
            validate_bounded_thinking_receipts(row['routing'], raw_response=row['raw_response'],
                                               expected_input_binding=known_binding)
            cases = fixture['cases'][index * 2:index * 2 + 2]
            sources = _batch_sources(cases, index * 2 + 1)
            parsed_sources, _, _ = coverage._inputs(sources, pin)
            coverage._project_direct_statuses_v18(parsed_sources,
                coverage.frozen_blind_source_groups(parsed_sources), answer)
            expected = {gid: cases[number]['expected']
                        for number, gid in enumerate(request[2]['groups'])}
            errors = score_required_statuses(answer, expected, request[2]['category_aliases'])
            failures.extend('checkpoint_%s: %s' % (index + 1, error) for error in errors)
            base['scored_cases'].extend(case['id'] for case in cases)
            base['completed_checkpoints'] = index + 1
    except (ValueError, KeyError, TypeError) as exc:
        return {**base, 'state': 'blocked', 'reason': 'canary_exact_replay_failed', 'detail': str(exc)}
    if failures:
        return {**base, 'state': 'blocked', 'reason': 'synthetic_semantic_boundaries_failed', 'failures': failures}
    if len(attempts) < len(requests):
        return {**base, 'state': 'needs_call', 'next_checkpoint': len(attempts) + 1}
    return {**base, 'state': 'qualified_synthetic_boundaries'}
