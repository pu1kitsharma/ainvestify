"""Version binding for the synthetic material repair diagnostic."""

from agents.inference.model_authorship import digest
from scripts.evaluate_local_material_repair_harness import (
    _bound_review_request,
    _re_review_request,
)


def test_historical_review_request_replays_without_contract_upgrade():
    base = {'input_revision': 'synthetic-r1', 'review_model': {'name': 'local'}}
    historical = {**base, 'digest': digest(base)}

    assert _bound_review_request(base, historical) == historical


def test_versioned_review_request_replays_only_its_recorded_contract():
    base = {'input_revision': 'synthetic-r1', 'review_model': {'name': 'local'}}
    versioned = {**base, 'review_contract': 'semantic_v7'}
    recorded = {**versioned, 'digest': digest(versioned)}

    assert _bound_review_request(base, recorded) == recorded
    assert _bound_review_request(base, {**recorded, 'review_contract': 'other'}) != recorded


def test_new_re_review_has_semantic_v10_with_exact_digest():
    base = {'input_revision': 'synthetic-r1', 'review_model': {'name': 'local'}}
    request = _re_review_request(base)

    assert request['review_contract'] == 'semantic_v10'
    assert request['digest'] == digest({k: v for k, v in request.items() if k != 'digest'})
    assert 'review_contract' not in base
