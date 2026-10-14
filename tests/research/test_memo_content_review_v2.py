"""Exact recorded sentence coverage and historical replay remain release gates."""
import json
import pytest
from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_content_review as review, memo_content_review_v2 as v2
from agents.research import memo_content_repair as repair
from tests.research.test_memo_causal_review import sample

CONTRACT = {'version': v2.CONTRACT, 'model_name': 'qwen3.5:9b', 'model_digest': 'b'*64}
PIN = {'name': 'qwen3:14b', 'digest': 'a'*64}

class Reviewer:
    name = CONTRACT['model_name']
    def __init__(self, flaw=None):
        self.__dict__.update(v2.OPTIONS)
        self.flaw = flaw
    def generate_for_task(self, task, instruction, evidence, schema, **kwargs):
        payload = json.loads(evidence)
        source = payload['sources'][0]
        answers = {key: {'relation': 'conditional_question', 'source_id': None,
                        'source_excerpt': '', 'reason': 'The wording is an open diligence question.'}
                   for key in payload['sentences']}
        if self.flaw == payload['field_path']:
            key = next(iter(answers))
            answers[key] = {'relation': 'unsupported', 'source_id': source['id'],
                            'source_excerpt': source['passage'][:40],
                            'reason': 'The assertion exceeds the retained source scope.'}
        answer = {'judgments': answers, 'diligence_status': 'open'}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **v2.OPTIONS}
        return schema.model_validate(answer)

def reviews(memo, sources, flaw=None):
    attempts = []
    model = Reviewer(flaw)
    for _ in range(1+len(memo['unknowns'])):
        review.review_memo_content(memo, sources, attempts, lambda: None, model,
            PreparationBudget(60, max_calls=10, max_requests=10), contract=CONTRACT)
    return attempts, review.evaluate_attempts(memo, sources, attempts, CONTRACT)[0]

def test_open_diligence_does_not_override_complete_sentence_judgments():
    memo, sources = sample()
    attempts, result = reviews(memo, sources)
    assert result['state'] == 'accepted'
    assert result['investment_approval'] is False
    assert all(row['diligence_status'] == 'open' for row in result['assessments'])
    assert review.evaluate_attempts(memo, sources, attempts, CONTRACT)[0] == result
    attempts[0]['answer']['diligence_status'] = 'answered'
    with pytest.raises(ValueError):
        review.evaluate_attempts(memo, sources, attempts, CONTRACT)

def test_unsupported_sentence_blocks_and_all_sentences_retained():
    memo, sources = sample()
    attempts, result = reviews(memo, sources, 'unknowns[0].why_it_matters')
    assert result['state'] == 'blocked'
    finding = result['findings'][0]
    assert finding['field_path'] == 'unknowns[0].why_it_matters'
    assert finding['sentence_findings'][0]['exact_sentence'] in memo['unknowns'][0]['why_it_matters']
    payload, schema = review.frozen_calls(memo, sources, CONTRACT)[0][1:]
    answer = attempts[0]['answer']
    answer['judgments'].pop(next(iter(answer['judgments'])))
    with pytest.raises(ValueError):
        schema.model_validate(answer)

def test_v3_repair_preserves_original_review_digest_and_stable_evidence():
    memo, sources = sample()
    _, result = reviews(memo, sources, 'unknowns[0].why_it_matters')
    path = result['findings'][0]['field_path']
    changed = json.loads(json.dumps(memo))
    changed['unknowns'][1]['why_it_matters'] = 'The supplied record leaves this diligence question open.'
    packet = {'contract': repair.CONTRACT_V3, 'field_path': path,
              'base_memo_digest': digest(changed), 'review_memo_digest': digest(memo),
              'model_name': PIN['name'], 'model_digest': PIN['digest'],
              'review_response_id': result['findings'][0]['response_id'],
              'review_response_hash': result['findings'][0]['response_hash']}
    _, _, payload, _ = repair.frozen_request(changed, sources, packet, result)
    assert payload['review_memo_digest'] != payload['base_memo_digest']
    assert payload['review_memo_digest'] == result['memo_digest']
    altered = {**packet, 'review_memo_digest': digest(changed)}
    with pytest.raises(ValueError):
        repair.frozen_request(changed, sources, altered, result)


def test_bound_span_contract_requires_model_choice_and_rejects_missing_support():
    from agents.research.rationale_judgments import validate_judgments
    memo, sources = sample()
    contract = {**CONTRACT, 'version': v2.FRESH_CONTRACT}
    _, payload, schema = review.frozen_calls(memo, sources, contract)[0]
    spans = payload['evidence_spans']
    for entry in spans.values():
        source = next(row for row in sources if row['id'] == entry['source_id'])
        assert source['passage'][entry['start']:entry['end']] == entry['exact_text']
    chosen = next(iter(spans))
    answer = {'judgments': {key: {'relation': 'supported_fact', 'evidence_id': chosen,
              'reason': 'The selected source supports this factual assertion.'}
              for key in payload['sentences']}, 'diligence_status': 'open'}
    schema.model_validate(answer)
    assert validate_judgments(payload, v2.bind_judgments(payload, answer)) == []
    key = next(iter(answer['judgments']))
    answer['judgments'][key]['evidence_id'] = None
    with pytest.raises(ValueError, match='requires a source'):
        validate_judgments(payload, v2.bind_judgments(payload, answer))
    answer['judgments'][key]['evidence_id'] = 'invented'
    with pytest.raises(ValueError):
        schema.model_validate(answer)


def test_late_call_waits_without_consuming_or_recording_a_failed_attempt():
    memo, sources = sample()
    attempts = []
    budget = PreparationBudget(20, max_calls=1, max_requests=1)
    outcome = review.review_memo_content(memo, sources, attempts, lambda: None,
                                        Reviewer(), budget, contract=CONTRACT)
    assert outcome['state'] == 'needs_resume'
    assert attempts == [] and budget.calls == 0
    _, blocked = reviews(memo, sources, 'unknowns[0].why_it_matters')
    class NeverCalled:
        name = PIN['name']
        def generate(self, *args, **kwargs):
            raise AssertionError('Insufficient time must not start a repair')
    outcome, _ = repair.revise_memo_content(memo, sources, review_result=blocked,
        repair_attempts=attempts, save_repairs=lambda: None, author=NeverCalled(),
        author_pin=PIN, repair_budget=PreparationBudget(30, max_calls=1, max_requests=1))
    assert outcome['state'] == 'needs_resume' and not attempts
