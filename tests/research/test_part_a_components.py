import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.part_a_components import (
    COMPONENTS, _component_payload, part_a_bundle_id, replay_part_a_components,
)


def _record(response_id, task, supplied, answer):
    raw = json.dumps(answer)
    return {'id': response_id, 'task': task, 'input': supplied,
            'answer': answer, 'raw_response': raw, 'response_hash': digest(raw)}


def _fixture():
    passage = 'Publisher reports a product pilot with customers; revenue and closing remain unverified.'
    payload = {'company': 'Example Venture', 'as_of_date': '2026-10-03',
               'sources': [{'id': 'S1', 'url': 'https://example.test/report',
                            'title': 'Publisher report', 'passage': passage,
                            'version': '2026-10-01', 'attribution': 'Publisher'}]}
    claim = {'source_id': 'S1', 'quote': passage,
             'assertion': 'The publisher reports a product pilot with customers.'}
    section = {'heading': 'Evidence and limits',
               'analysis': 'The publisher reports a product pilot with customers [S1]. '
                           'This supports a product hypothesis, while independent customer '
                           'proof, revenue records and closing evidence remain unavailable; '
                           'the investment case therefore needs primary diligence.',
               'claims': [claim]}
    recommendation = {'recommendation': 'defer_pending_evidence',
                      'recommendation_reason': 'The publisher reports a product pilot with '
                          'customers [S1]. Primary customer, revenue and financing records '
                          'are needed before advancing this diligence case.',
                      'recommendation_claims': [claim],
                      'unknowns': [
                          {'question': 'Which customers used the pilot and on what terms?',
                           'why_it_matters': 'Customer evidence would test whether the '
                                             'reported pilot has commercial relevance.',
                           'evidence_needed': 'Dated contracts and customer interviews.'},
                          {'question': 'What revenue and financing have been documented?',
                           'why_it_matters': 'Financial records would test the capacity '
                                             'to continue operating and the financing story.',
                           'evidence_needed': 'Signed accounts and financing records.'}]}
    answers = [recommendation, section, {**section, 'heading': 'Market evidence and limits'}]
    attempts = []
    ids = {}
    for i, ((name, task, _), answer) in enumerate(zip(COMPONENTS, answers), 1):
        response_id = f'response_{i}'
        attempts.append(_record(response_id, task, _component_payload(payload, name), answer))
        ids[name] = response_id
    return payload, attempts, ids


def test_part_a_components_exact_raw_replay():
    payload, attempts, ids = _fixture()
    part = replay_part_a_components(attempts, payload, ids)
    assert part.business_and_market.heading == 'Market evidence and limits'
    assert part.recommendation == 'defer_pending_evidence'
    assert part_a_bundle_id(ids).startswith('part_a_bundle_')


def test_part_a_components_reject_changed_source_or_raw():
    payload, attempts, ids = _fixture()
    changed = {**payload, 'as_of_date': '2026-10-04'}
    with pytest.raises(ValueError, match='source snapshot'):
        replay_part_a_components(attempts, changed, ids)
    attempts[1]['raw_response'] = attempts[1]['raw_response'].replace(
        'Evidence and limits', 'Changed and limits')
    with pytest.raises(ValueError, match='modified'):
        replay_part_a_components(attempts, payload, ids)
