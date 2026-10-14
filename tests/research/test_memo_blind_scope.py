"""Blind source findings cannot be changed by subsequent memo judgments."""
import copy
import pytest
from agents.research import memo_content_review_v2 as review
from agents.research.rationale_evidence import characterize_sources
from tests.research.test_rationale_evidence import Model, PIN, budget
from tests.research.test_memo_causal_review import sample


def frozen():
    memo, sources = sample()
    base = {'version': review.SCOPE_CONTRACT, 'model_name': PIN['name'], 'model_digest': PIN['digest']}
    ids = {sid for _, payload, _ in review.frozen_calls(memo, sources, base)
           for sid in payload['selected_source_ids']}
    selected = [s for s in sources if s['id'] in ids]
    attempts = []
    result = characterize_sources(selected, PIN, attempts, lambda: None, Model(), budget())
    contract = {**base, 'version': review.BLIND_CONTRACT,
                'source_characterization': {'attempts': attempts, 'result': result}}
    return memo, sources, contract


def test_blind_proof_replays_and_rejects_altered_source_classification():
    memo, sources, contract = frozen()
    calls = review.frozen_calls(memo, sources, contract)
    assert calls and all(p['source_characterization']['response_hash'] for _, p, _ in calls)
    altered = copy.deepcopy(contract)
    card = next(iter(altered['source_characterization']['result']['source_cards'].values()))
    card['reporting_basis'] = 'historical'
    with pytest.raises(ValueError, match='replay'):
        review.frozen_calls(memo, sources, altered)


def test_memo_review_cannot_invent_quantification_statement_or_change_time_basis():
    memo, sources, contract = frozen()
    _, payload, _ = review.frozen_calls(memo, sources, contract)[0]
    eid = next(iter(payload['evidence_spans']))
    row = {'relation': 'scoped_gap', 'evidence_id': eid, 'source_time_basis': 'mixed',
           'requires_explicit_quantification_claim': True}
    with pytest.raises(ValueError, match='no explicit'):
        review.validate_blind_scope(payload, {'judgments': {'s1': row}})
    row['requires_explicit_quantification_claim'] = False
    row['source_time_basis'] = 'historical'
    with pytest.raises(ValueError, match='basis differs'):
        review.validate_blind_scope(payload, {'judgments': {'s1': row}})
    row['source_time_basis'] = 'mixed'
    review.validate_blind_scope(payload, {'judgments': {'s1': row}})


def test_fact_cannot_hide_mixed_source_basis_as_not_applicable():
    memo, sources, contract = frozen()
    _, payload, _ = review.frozen_calls(memo, sources, contract)[0]
    row = {'relation': 'supported_fact', 'evidence_id': next(iter(payload['evidence_spans'])),
           'source_time_basis': 'not_applicable', 'requires_explicit_quantification_claim': False}
    with pytest.raises(ValueError, match='basis differs'):
        review.validate_blind_scope(payload, {'judgments': {'s1': row}})


def test_three_sentence_review_waits_for_sufficient_pass_time():
    from agents.preparation.preparation_budget import PreparationBudget
    memo, sources, contract = frozen()
    memo['recommendation_reason'] = 'The retained synthetic evidence merits further independent review. Current company records remain open for scrutiny. Diligence must resolve the pending questions.'
    attempts = []
    result = review.review_memo_content(memo, sources, attempts, lambda: None, object(),
        PreparationBudget(40, max_calls=1, max_requests=1), contract=contract)
    assert result['state'] == 'needs_resume'
    assert attempts == []


def test_failed_transport_is_not_a_semantic_finding():
    from agents.preparation.preparation_budget import PreparationBudget
    memo, sources, contract = frozen()
    class Failed:
        name = PIN['name']
        def __init__(self):
            self.__dict__.update(review.OPTIONS)
            self.last_call = {'model': self.name, **review.OPTIONS}
        def generate(self, *args): raise RuntimeError('Local request cancelled at deadline')
    attempts = []
    review.review_memo_content(memo, sources, attempts, lambda: None, Failed(),
        PreparationBudget(90, max_calls=1, max_requests=1), contract=contract)
    # All remaining targets are intentionally unrun; replay the failed target.
    result, next_call = review.evaluate_attempts(memo, sources, attempts, contract)
    assert next_call is not None
    assert result['state'] == 'needs_resume'
    # After final target coverage, the worker sees this failure classification;
    # the failed call must never supply a model verdict.
    assert attempts[0].get('answer') is None
    assert result['findings'][0]['review_failure_kind'] == 'transport'
