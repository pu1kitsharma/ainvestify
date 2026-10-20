"""Deterministic checks of supplied observations, never company answer generation.

Keys must be independently adjudicated. Boolean observations are declarations,
not workbook inspection or proof of live formulas/recalculation. Text semantics,
layout and banker judgment remain outside these reward contracts.
"""
import hashlib
import json
import math

CONTRACTS = {
    'E1': ('historical_cells', 'citations'),
    'E2': ('reported_totals', 'live_formulas', 'no_calculation_hardcodes'),
    'E3': ('future_actuals', 'assumption_citations', 'scenarios'),
    'E4': ('flags',),
    'E5': ('cash_need', 'maximum_draw', 'funding_buffer', 'recalc_clean'),
    'E6': ('text_cell_agreement', 'comparison_direction', 'sections'),
    'E7': ('source_figures', 'source_citations', 'cagr'),
}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _check(observed, key):
    kind = key.get('kind')
    expected = key.get('expected')
    if kind == 'numeric':
        tolerance = key.get('absolute_tolerance', 0)
        if not _finite(expected) or not _finite(tolerance) or tolerance < 0:
            raise ValueError('Numeric key needs finite value and nonnegative absolute tolerance')
        return float(_finite(observed) and abs(observed - expected) <= tolerance), {}
    if kind == 'exact':
        if type(expected) not in (str, bool, int, float) or (type(expected) in (int, float) and not _finite(expected)):
            raise ValueError('Exact key needs finite scalar')
        return float(type(observed) is type(expected) and observed == expected), {}
    if kind == 'set':
        if not isinstance(expected, list) or any(not isinstance(x, str) for x in expected) or len(set(expected)) != len(expected):
            raise ValueError('Set key needs unique string IDs')
        if not isinstance(observed, list) or any(not isinstance(x, str) for x in observed) or len(set(observed)) != len(observed):
            return 0.0, {'precision': 0.0, 'recall': 0.0}
        actual, wanted = set(observed), set(expected)
        matched = len(actual & wanted)
        precision = matched / len(actual) if actual else float(not wanted)
        recall = matched / len(wanted) if wanted else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return f1, {'precision': precision, 'recall': recall}
    raise ValueError('Unsupported answer-key check kind')


def score_case(prediction, answer_key):
    """A missing/unsupported mandatory check prevents a complete reward."""
    env = answer_key.get('environment')
    if env not in CONTRACTS:
        raise ValueError('Unknown environment')
    case_id = answer_key.get('case_id')
    if not isinstance(case_id, str) or not case_id:
        raise ValueError('Answer key needs case_id')
    if prediction.get('case_id') != case_id or prediction.get('environment') != env:
        raise ValueError('Prediction identity differs from answer key')
    checks = answer_key.get('checks', {})
    if not isinstance(checks, dict):
        raise ValueError('Answer key checks must be an object')
    observations = prediction.get('observations', {})
    if not isinstance(observations, dict):
        raise ValueError('Observations must be an object')
    results = {}
    for name in CONTRACTS[env]:
        key = checks.get(name)
        observed = observations.get(name)
        if not isinstance(key, dict):
            results[name] = {'status': 'missing_answer_key', 'reward': 0.0}
        elif key.get('status') == 'unsupported':
            results[name] = {'status': 'unsupported', 'reward': 0.0}
        elif key.get('status') != 'available':
            raise ValueError('Key check status must be available or unsupported')
        else:
            # Validate available keys even when observations are absent.
            value, details = _check(None if not isinstance(observed, dict) else observed.get('value'), key)
            if not isinstance(observed, dict) or observed.get('status') == 'missing':
                status, value = 'missing_observation', 0.0
            elif observed.get('status') == 'unsupported':
                status, value = 'unsupported', 0.0
            elif observed.get('status') != 'observed':
                raise ValueError('Observation status must be observed, missing or unsupported')
            else:
                status = 'matched' if value == 1 else 'mismatch'
            results[name] = {'status': status, 'reward': value, **details}
    return {'case_id': case_id, 'environment': env, 'checks': results,
            'reward': sum(x['reward'] for x in results.values()) / len(results),
            'all_checks_matched': all(x['status'] == 'matched' for x in results.values()),
            'semantic_review': 'unsupported', 'investor_acceptance': False,
            'evidence_scope': 'supplied_observations_only'}


def evaluate(predictions, answer_keys):
    """Include unanswered cases; reject duplicate or unexpected prediction IDs."""
    def index(rows):
        result = {}
        for row in rows:
            identity = row.get('case_id')
            if not isinstance(identity, str) or not identity or identity in result:
                raise ValueError('Missing or duplicate case_id')
            result[identity] = row
        return result
    keys, proposed = index(answer_keys), index(predictions)
    if not keys or set(proposed) - set(keys):
        raise ValueError('Empty answer key or unexpected prediction case')
    cases = [score_case(proposed.get(identity, {'case_id': identity,
                     'environment': key['environment']}), key) for identity, key in keys.items()]
    digest = hashlib.sha256(json.dumps(answer_keys, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {'contract': 'agentic-banker-offline-rewards-v1', 'answer_key_sha256': digest,
            'cases': cases, 'mean_reward': sum(x['reward'] for x in cases) / len(cases),
            'investor_acceptance': False, 'weights_trained': False,
            'limitations': ['No model run', 'No artifact inspection', 'No semantic or human review']}
