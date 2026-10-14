"""Versioned typed-card view and date/adjacent-scale binding preserve originals."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_source_unit_author as author, rationale_evidence
from tests.research.test_memo_source_unit_author_v4 import fixture, PIN, REVIEW_PIN, Characterizer


def date_fixture():
    memo, sources, _ = fixture()
    sources[-1]['passage'] = 'Partnership schedule\nPotential USD Mn\nDevice 3 Partner Nov-21 Live at dealer level 0.34 0.93'
    memo['recommendation_claims'][-1]['quote'] = sources[-1]['passage']
    rows = []
    result = rationale_evidence.characterize_sources(sources, REVIEW_PIN, rows, lambda: None,
        Characterizer(), PreparationBudget(60, max_calls=2, max_requests=2))
    return memo, sources, {'attempts': rows, 'result': result}


def test_calendar_dates_bind_full_month_year_with_documented_century_pivot():
    check = author.canonical_assertion_numbers
    assert check('Nov-21') == check('November 2021') == {'date:2021-11'}
    assert check('Jan-68') == check('January 2068')
    assert check('Jan-69') == check('January 1969')
    for wrong in ('November 1921', 'October 2021', 'November 2022'):
        assert check(wrong) - check('Nov-21')
    assert check('Nov-21 and Oct-22') == {'date:2021-11', 'date:2022-10'}
    assert check('3 devices Nov-21') == {'3', 'date:2021-11'}
    assert author._numbers('November 2021') - author._numbers('Nov-21')


def test_adjacent_scale_only_does_not_inherit_headers_or_change_original_text():
    check = author.canonical_assertion_numbers
    assert check('Revenue USD 0.34 Mn') == check('Revenue USD 0.34 million') == {'340000'}
    assert check('Revenue 0.34Bn') == check('Revenue 0.34 billion') == {'340000000'}
    assert check('USD Mn\nRevenue 0.34') != check('Revenue 0.34 million')
    assert check('Revenue 0.34 Mn') != check('Revenue 0.34 billion')
    text = 'Revenue USD 0.34 Mn, Nov-21'
    check(text)
    assert text == 'Revenue USD 0.34 Mn, Nov-21'


def test_all_v6_unit_cards_are_typed_only_and_v5_inputs_remain_unchanged():
    memo, sources, proof = date_fixture()
    original = copy.deepcopy(proof)
    _, _, old, _ = author.frozen_unit_requests(memo, sources, proof, PIN, contract=author.CONTRACT_V5)
    _, _, new, _ = author.frozen_unit_requests(memo, sources, proof, PIN, contract=author.CONTRACT_V6)
    assert all('reason' in card for _, request, _ in old for card in request['source_cards'].values())
    assert all(set(card) == {'reporting_basis', 'contains_explicit_incomplete_quantification_claim'}
               for _, request, _ in new for card in request['source_cards'].values())
    assert proof == original
    assert all(request['source_proof_digest'] == author.digest(proof['result']) for _, request, _ in new)
    _, base_schema, units, _ = author.frozen_unit_requests(memo, sources, proof, PIN, contract=author.CONTRACT_V6)
    uid, payload, schema = next(row for row in units if row[0] == 'r_S4')
    eid = next(eid for eid, text in payload['sources']['S4']['spans'].items() if 'Nov-21' in text)
    obj = {'recommendation': 'defer_pending_evidence', 'supporting_evidence_id': eid,
           'metric_basis': 'qualitative_only', 'reported_scope': 'historical',
           'standalone_text': 'The source reports Device 3 Partner as live at dealer level in November 2021, a reported historical status.'}
    author._validate_isolated({'recommendation_source_ids':['S4','S1']}, uid, payload, schema, obj)
    for date in ('October 2021', 'November 1921', 'November 2022'):
        with pytest.raises(ValueError, match='numbers or fiscal years'):
            author._validate_isolated({'recommendation_source_ids':['S4','S1']}, uid, payload, schema,
                {**obj, 'standalone_text': obj['standalone_text'].replace('November 2021', date)})


class Model:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == author.TASK_V6 and instruction == author.INSTRUCTION_V6
        payload = json.loads(evidence)
        if payload['unit_id'].startswith('r_'):
            sid = payload['unit_source_ids'][0]
            spans = payload['sources'][sid]['spans']
            eid = next(eid for eid, text in spans.items() if 'Nov-21' in text) if sid == 'S4' else next(iter(spans))
            text = ('The source reports Device 3 Partner as live at dealer level in November 2021, a reported historical status.' if sid == 'S4'
                else 'The registry source reports uncertain completion status and current cash availability; dated records would help inform further diligence.')
            obj = {'recommendation': 'defer_pending_evidence', 'supporting_evidence_id': eid,
                'metric_basis': payload['metric_basis'], 'reported_scope': 'historical', 'standalone_text': text}
        else:
            obj = {'question': 'What operating cash is currently available to the company?',
                'conditional_importance': 'If reviewed cash records were available, they would help assess operating runway.',
                'requested_records': 'Reviewed bank and account records showing current operating cash availability.',
                'requested_time_basis': 'current'}
        self.last_response_text = json.dumps(obj)
        self.last_route = {'model': self.name, **author.OPTIONS_V2}
        return schema.model_validate(obj)


def test_four_unit_v6_projection_preserves_raw_date_and_exact_response_replay():
    memo, sources, proof = date_fixture()
    original = copy.deepcopy(sources)
    rows = []
    for _ in range(4):
        result = author.run_author(memo, sources, proof, PIN, rows, lambda: None, Model(),
            PreparationBudget(105, max_calls=6, max_requests=6), contract=author.CONTRACT_V6)
    assert result['state'] == 'accepted'
    claim = next(c for c in result['memo']['recommendation_claims'] if c['source_id'] == 'S4')
    assert 'Nov-21' in claim['quote'] and 'November 2021' in claim['assertion']
    assert sources == original
    assert author.run_author(memo, sources, proof, PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=author.CONTRACT_V6) == result
