"""Compact memo inputs keep exact source evidence while removing duplication."""
import json
import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research.part_a_components import (_component_payload, compact_part_a_result,
                                                replay_part_a_components, part_a_bundle_id)
from agents.research.staged_memo import _part_b_section_payload
from tests.research.test_memo_evidence_packet import Double, source
from tests.research.test_memo_evidence_spans import V3, build
from tests.research.test_investment_memo import SOURCE, draft


def test_v5_memo_sections_receive_compact_exact_span_evidence():
    sources = [source('S1', 'Example Labs describes a scheduling tool for clinics and a pilot.'),
               source('S2', 'A registry lists an Example Labs financing entry whose '
                       'completion status remains unknown.')]
    selected = lambda request: {item['id']: {'findings': [{
        'status': 'source_reported', 'candidate_id': item['candidates'][0]['id']}]}
        for item in request['sources']}
    packet = build(Double(selected), [], sources=sources,
                   source_set_digest=digest([item.model_dump() for item in sources]),
                   contract=V3)
    payload = {'company': 'Example Labs',
               'sources': [item.model_dump() for item in sources],
               'as_of_date': '2026-10-04'}
    recommendation = _component_payload(payload, 'recommendation',
        revision='part-a-components-v6', evidence_packet=packet)
    assert recommendation['component_revision'] == 'part-a-components-v6'
    assert recommendation['evidence_scope']['complete_source_ids'] == ['S1', 'S2']
    assert recommendation['evidence_coverage']['complete'] is True
    assert recommendation['complete_source_set_digest'] == digest(payload['sources'])
    assert [card['source_id'] for card in recommendation['sources']] == ['S1', 'S2']
    for card, retained in zip(recommendation['sources'], sources):
        assert set(card) == {'source_id', 'attribution', 'evidence'}
        assert len(card['evidence']) == 1
        assert card['evidence'][0]['quote'] in retained.passage
        assert 'finding' not in card['evidence'][0]
    assert len(json.dumps(recommendation['sources'])) < len(json.dumps(packet['cards']))

    part_a = {'recommendation': 'defer_pending_evidence',
              'unknowns': [{'question': 'Was the entry completed?'}],
              'investment_thesis': {'heading': 'Conditional thesis'},
              'business_and_market': {'heading': 'Reported product'}}
    diligence = _part_b_section_payload(payload, 'part-a-bound', part_a,
        'diligence_plan', version='part-b-sections-v7', evidence_packet=packet)
    assert diligence['draft_contract'] == 'part-b-sections-v7'
    assert diligence['evidence_scope']['complete_source_ids'] == ['S1', 'S2']
    assert diligence['sources'] == recommendation['sources']


class SplitModel:
    name = 'offline-test-model'
    last_call = {'host': 'test-double'}
    last_response_text = ''

    def __init__(self, memo):
        self.memo = memo
        self.calls = []

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        self.calls.append(task)
        fields = {
            'investment_memo_part_a_recommendation_decision': (
                'recommendation', 'recommendation_reason', 'recommendation_claims'),
            'investment_memo_part_a_recommendation_unknowns': ('unknowns',),
            'investment_memo_part_a_thesis': ('investment_thesis',),
            'investment_memo_part_a_market': ('business_and_market',),
        }[task]
        answer = ({field: self.memo[field] for field in fields}
                  if task.endswith(('recommendation_decision', 'recommendation_unknowns'))
                  else self.memo[fields[0]])
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name}
        return schema.model_validate_json(self.last_response_text)


def test_split_part_a_v7_authors_and_replays_four_bounded_responses():
    source = SOURCE
    data = draft()
    selecting = lambda request: {item['id']: {'findings': [{
        'status': 'source_reported', 'candidate_id': item['candidates'][0]['id']}]}
        for item in request['sources']}
    attempts = []
    build(Double(selecting), attempts, sources=[source],
          source_set_digest=digest([source.model_dump()]), contract=V3)
    payload = {'company': 'Example Labs', 'sources': [source.model_dump()],
               'as_of_date': '2026-10-04'}
    model = SplitModel(data)
    with preparation_budget(PreparationBudget(105, max_calls=4)) as budget:
        ids = compact_part_a_result(model, payload, attempts, lambda: None, budget,
            fresh_revision='part-a-components-v7', packet_contract=V3)
    assert len(ids) == 4 and len(model.calls) == 4
    assert model.calls[:2] == [
        'investment_memo_part_a_recommendation_decision',
        'investment_memo_part_a_recommendation_unknowns']
    assert part_a_bundle_id(ids, revision='part-a-components-v7').startswith('part_a_bundle_')
    restored = replay_part_a_components(attempts, payload, ids)
    assert restored.recommendation == data['recommendation']
    assert restored.unknowns[0].question == data['unknowns'][0]['question']
    saved = json.dumps(attempts)
    idle = SplitModel(data)
    with preparation_budget(PreparationBudget(105, max_calls=4)) as budget:
        assert compact_part_a_result(idle, payload, attempts, lambda: None, budget,
            fresh_revision='part-a-components-v7', packet_contract=V3) == ids
    assert idle.calls == [] and json.dumps(attempts) == saved


def test_bound_v8_part_a_and_part_b_use_saved_quote_ids_and_exact_replay():
    from agents.research.staged_memo import (_part_b_section_schema,
        _part_b_section_answer, PART_B_SECTION_V8)
    from agents.inference.model_authorship import recorded_call

    retained = source('S1', 'Example Labs describes a scheduling tool for clinics and a pilot with one clinic.')
    sources = [retained]
    attempts = []
    selecting = lambda request: {item['id']: {'findings': [{
        'status': 'source_reported', 'candidate_id': item['candidates'][0]['id']}]
        } for item in request['sources']}
    packet = build(Double(selecting), attempts, sources=sources,
        source_set_digest=digest([retained.model_dump()]), contract=V3)
    payload = {'company': 'Example Labs', 'sources': [retained.model_dump()],
               'as_of_date': '2026-10-04'}
    sentence = ('The retained source reports a scheduling tool and a clinic pilot, '
                'while commercial outcomes still require primary operating records.')
    second = ('The pilot is a source-reported statement and does not itself establish '
              'customer adoption or commercial performance.')
    third = ('The reported tool and pilot identify a focused diligence question '
             'about implementation, customer use, and primary records.')
    section = {'heading': 'Reported operations and evidence gaps',
               'claims': [{'quote_id': 'S1.q1', 'assertion':
                           'The source reports a scheduling tool for clinics.'}],
               'analysis_sentences': [{'text': text, 'claim_index': 0}
                                      for text in (sentence, second, third)]}
    responses = {
        'investment_memo_part_a_recommendation_decision_v2': {
            'recommendation': 'defer_pending_evidence',
            'claims': section['claims'],
            'reason_sentences': [{'text': text, 'claim_index': 0}
                                 for text in (sentence, second)]},
        'investment_memo_part_a_recommendation_unknowns': {
            'unknowns': draft()['unknowns'][:2]},
        'investment_memo_part_a_thesis': section,
        'investment_memo_part_a_market': section,
    }

    class BoundModel:
        name = 'offline-bound-test'
        last_call = {'host': 'test-double'}
        last_response_text = ''
        calls = []

        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            self.calls.append(task)
            answer = responses[task]
            self.last_response_text = json.dumps(answer)
            self.last_route = {'model': self.name}
            return schema.model_validate(answer)

    model = BoundModel()
    with preparation_budget(PreparationBudget(105, max_calls=4)) as budget:
        ids = compact_part_a_result(model, payload, attempts, lambda: None, budget,
            fresh_revision='part-a-components-v8', packet_contract=V3)
    assert len(ids) == 4 and len(model.calls) == 4
    part_a = replay_part_a_components(attempts, payload, ids)
    assert part_a.recommendation_claims[0].quote == retained.passage
    assert '[S1]' in part_a.recommendation_reason
    assert part_a.investment_thesis.claims[0].quote == retained.passage

    supplied = _part_b_section_payload(payload, part_a_bundle_id(ids,
        revision='part-a-components-v8'), part_a, 'diligence_plan',
        version=PART_B_SECTION_V8, evidence_packet=packet)
    schema = _part_b_section_schema('diligence_plan', version=PART_B_SECTION_V8,
                                    payload=supplied)
    responses['investment_memo_part_b_diligence_plan'] = {'diligence_plan': section}
    with preparation_budget(PreparationBudget(105, max_calls=1)):
        _, response_id = recorded_call(model, 'investment_memo_part_b_diligence_plan',
            'Write source-bound diligence.', supplied, schema, attempts, lambda: None)
    restored = _part_b_section_answer('diligence_plan', PART_B_SECTION_V8,
                                      supplied, attempts, response_id)
    assert restored['claims'][0]['quote'] == retained.passage
    assert '[S1]' in restored['analysis']
    assert replay_part_a_components(attempts, payload, ids) == part_a


@pytest.mark.parametrize('revision,unknowns_contract', [
    ('part-a-components-v9', None), ('part-a-components-v10', None),
    ('part-a-components-v11', None), ('part-a-components-v12', None),
    ('part-a-components-v13', None), ('part-a-components-v13', 'wide_v1')])
def test_source_local_v9_part_a_replays_selector_and_per_quote_authors(
        revision, unknowns_contract):
    retained = source('S1', 'Example Labs describes a scheduling tool for clinics and a pilot with one clinic.')
    attempts = []
    selecting = lambda request: {item['id']: {'findings': [{
        'status': 'source_reported', 'candidate_id': item['candidates'][0]['id']}]
        } for item in request['sources']}
    build(Double(selecting), attempts, sources=[retained],
          source_set_digest=digest([retained.model_dump()]), contract=V3)
    payload = {'company': 'Example Labs', 'sources': [retained.model_dump()],
               'as_of_date': '2026-10-04'}
    sentences = [
        'The retained source reports a clinic scheduling tool and pilot, while commercial results remain unverified.',
        'This reported pilot gives a focused question for primary diligence about customer use and operating records.',
        'The source identifies a reported offering but does not itself establish paid use or market demand.',
    ]

    class LocalModel:
        name = 'offline-local-test'
        last_call = {'host': 'test-double'}
        last_response_text = ''

        def __init__(self):
            self.calls = []

        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            self.calls.append(task)
            if task.endswith(('_select_v3', '_select_v4', '_select_v5',
                              '_select_v6', '_select_v7')):
                answer = ({'recommendation': 'defer_pending_evidence',
                           'quote_ids': ['S1.q1']} if 'recommendation' in task else
                          {'heading': 'Reported operations and evidence gaps',
                           'quote_ids': ['S1.q1']})
            elif task.endswith(('_source_1_v3', '_source_1_v4', '_source_1_v5',
                                '_source_1_v6', '_source_1_v7')):
                count = json.loads(evidence)['sentence_count']
                answer = {'assertion': 'The source reports a clinic scheduling tool and pilot.',
                          'sentences': sentences[:count]}
            elif task in {'investment_memo_part_a_recommendation_unknowns',
                          'investment_memo_part_a_recommendation_unknowns_v2'}:
                answer = {'unknowns': draft()['unknowns'][:2]}
            else:
                raise AssertionError(task)
            self.last_response_text = json.dumps(answer)
            self.last_route = {'model': self.name}
            return schema.model_validate(answer)

    model = LocalModel()
    author_model = LocalModel() if revision == 'part-a-components-v13' else None
    with preparation_budget(PreparationBudget(105, max_calls=7)) as budget:
        ids = compact_part_a_result(model, payload, attempts, lambda: None, budget,
            fresh_revision=revision, packet_contract=V3,
            author_model=author_model, unknowns_contract=unknowns_contract)
    assert len(model.calls) + len(author_model.calls if author_model else []) == 7
    assert len(ids) == 7
    restored = replay_part_a_components(attempts, payload, ids)
    assert restored.recommendation_claims[0].quote == retained.passage
    assert restored.investment_thesis.claims[0].quote == retained.passage
    assert '[S1]' in restored.business_and_market.analysis
    from agents.research.staged_memo import saved_part_a_components
    assert saved_part_a_components(attempts, payload) == ids
    idle = LocalModel()
    with preparation_budget(PreparationBudget(105, max_calls=7)) as budget:
        assert compact_part_a_result(idle, payload, attempts, lambda: None, budget,
            fresh_revision=revision, packet_contract=V3,
            author_model=LocalModel() if author_model else None,
            unknowns_contract=unknowns_contract) == ids
    assert idle.calls == []


@pytest.mark.parametrize('version', ['part-b-sections-v9', 'part-b-sections-v10',
                                     'part-b-sections-v11', 'part-b-sections-v12',
                                     'part-b-sections-v13'])
def test_source_local_v9_part_b_integrates_saved_sections_and_replay(version):
    from agents.research.staged_memo import (MemoPartA, compact_part_b_result,
        saved_part_b_sections, replay_part_b_sections)

    retained = source('S1', 'Example Labs describes a scheduling tool for clinics and a pilot with one clinic.')
    attempts = []
    selecting = lambda request: {item['id']: {'findings': [{
        'status': 'source_reported', 'candidate_id': item['candidates'][0]['id']}]
        } for item in request['sources']}
    build(Double(selecting), attempts, sources=[retained],
          source_set_digest=digest([retained.model_dump()]), contract=V3)
    payload = {'company': 'Example Labs', 'sources': [retained.model_dump()],
               'as_of_date': '2026-10-04'}
    full = draft()
    part_a = MemoPartA.model_validate({key: full[key] for key in (
        'recommendation', 'recommendation_reason', 'recommendation_claims',
        'unknowns', 'investment_thesis', 'business_and_market')})
    sentences = [
        'The retained source reports a clinic scheduling tool and pilot, while commercial results remain unverified.',
        'This reported pilot gives a focused question for primary diligence about customer use and operating records.',
        'The source identifies a reported offering but does not itself establish paid use or market demand.',
    ]

    class LocalModel:
        name = 'offline-local-part-b'
        last_call = {'host': 'test-double'}
        last_response_text = ''

        def __init__(self):
            self.calls = []

        def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
            self.calls.append(task)
            if task.endswith('_select'):
                answer = {'heading': 'Reported operations and evidence gaps',
                          'quote_ids': ['S1.q1']}
            else:
                answer = {'assertion': 'The source reports a clinic scheduling tool and pilot.',
                          'sentences': sentences}
            self.last_response_text = json.dumps(answer)
            self.last_route = {'model': self.name}
            return schema.model_validate(answer)

    model = LocalModel()
    author_model = LocalModel() if version == 'part-b-sections-v13' else None
    with preparation_budget(PreparationBudget(105, max_calls=6)) as budget:
        ids = compact_part_b_result(model, payload, 'part-a-bound', part_a,
            attempts, lambda: None, budget, fresh_version=version,
            author_model=author_model)
    assert len(model.calls) + len(author_model.calls if author_model else []) == 6
    assert set(ids) == {
        'differentiation_and_execution', 'risks_and_countercase', 'diligence_plan'}
    restored = replay_part_b_sections(attempts, payload, 'part-a-bound', part_a, ids)
    assert restored.diligence_plan.claims[0].quote == retained.passage
    assert '[S1]' in restored.risks_and_countercase.analysis
    assert saved_part_b_sections(attempts, payload, 'part-a-bound', part_a) == ids
