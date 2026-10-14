"""Qualitative retrieval keeps exact source lineage without untyped amounts."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_source_unit_author as author
from agents.research.investment_memo import Source
from tests.research.test_memo_source_unit_author_v4 import fixture, PIN, TABLE


def test_qualitative_exact_prefix_offsets_preserve_original_dates_entities_and_amounts():
    source = Source(id='S1', url='https://example.test/source', title='Synthetic table',
        version='a' * 64, attribution='Source report, unverified',
        passage='Partnership schedule\\nPotential USD Mn\\nDevice 3 Partner Nov-21 Live at dealer level 0.34 0.93\\nDevice 2 Partner 2018 Pilot 0.40 0.93')
    original = source.passage
    snippets = author._qualitative_spans(source)
    assert snippets and len(snippets) <= 6
    texts = [span['exact_text'] for span in snippets.values()]
    assert 'Device 3 Partner Nov-21 Live at dealer level' in texts
    assert 'Device 2 Partner 2018 Pilot' in texts
    for eid, span in snippets.items():
        assert eid.startswith('S1.q')
        assert span['exact_text'] == original[span['start']:span['end']]
        assert 15 <= len(span['exact_text']) <= 700
        assert '0.34' not in span['exact_text'] and '0.40' not in span['exact_text']
        assert 'USD' not in span['exact_text']
    assert source.passage == original and '0.34 0.93' in source.passage


def test_qualitative_schema_evidence_view_and_lineage_are_recomputed_not_trusted():
    memo, sources, proof = fixture()
    base, _, requests, _ = author.frozen_unit_requests(memo, sources, proof, PIN, contract=author.CONTRACT_V5)
    unit = next(row for row in requests if row[0] == 'r_S4')
    _, payload, schema = unit
    assert payload['metric_basis'] == 'qualitative_only'
    assert all('.q' in eid for eid in payload['sources']['S4']['spans'])
    assert payload['sources']['S4']['spans'] == base['sources']['S4']['spans']
    obj = {'recommendation': 'defer_pending_evidence', 'supporting_evidence_id': 'S4.q001',
        'metric_basis': 'named_source_metric', 'reported_scope': 'mixed',
        'standalone_text': 'The source reports partnership scheduling as a company description rather than independently verified current performance.'}
    with pytest.raises(ValueError):
        schema.model_validate(obj)
    obj['metric_basis'] = 'qualitative_only'
    obj['supporting_evidence_id'] = 'S1.e001'
    with pytest.raises(ValueError):
        schema.model_validate(obj)
    spans = author.frozen_offered_spans(sources, requests)
    for span in spans.values():
        source = next(s for s in sources if s['id'] == span['source_id'])
        assert span['exact_text'] == source['passage'][span['start']:span['end']]
    changed = [(uid, copy.deepcopy(request), sch) for uid, request, sch in requests]
    next(request for uid, request, _ in changed if uid == 'r_S4')['sources']['S4']['spans']['S4.q001'] = 'Invented replacement text'
    with pytest.raises(ValueError, match='differs from original'):
        author.frozen_offered_spans(sources, changed)


class Model:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == author.TASK_V5 and instruction == author.INSTRUCTION_V5
        payload = json.loads(evidence)
        if payload['unit_id'].startswith('r_'):
            sid = payload['unit_source_ids'][0]
            text = ('The source reports partnership scheduling as a company description rather than independently verified current performance.'
                    if sid == 'S4' else 'The registry source reports uncertain completion status and current cash availability; dated records would help inform further diligence.')
            obj = {'recommendation': 'defer_pending_evidence', 'supporting_evidence_id': next(iter(payload['sources'][sid]['spans'])),
                'metric_basis': payload['metric_basis'], 'reported_scope': 'current_description', 'standalone_text': text}
        else:
            obj = {'question': 'What operating cash is currently available to the company?',
                'conditional_importance': 'If reviewed cash records were available, they would help assess operating runway.',
                'requested_records': 'Reviewed bank and account records showing current operating cash availability.',
                'requested_time_basis': 'current'}
        self.last_response_text = json.dumps(obj)
        self.last_route = {'model': self.name, **author.OPTIONS_V2}
        return schema.model_validate(obj)


def test_four_source_units_project_q_quotes_and_replay_all_original_raw_records():
    memo, sources, proof = fixture()
    rows, model = [], Model()
    for _ in range(4):
        record = author.run_author(memo, sources, proof, PIN, rows, lambda: None, model,
            PreparationBudget(105, max_calls=6, max_requests=6), contract=author.CONTRACT_V5)
    assert record['state'] == 'accepted'
    clause = record['answer']['recommendation_units']['S4']
    assert clause['metric_basis'] == 'qualitative_only' and '.q' in clause['supporting_evidence_id']
    claim = next(c for c in record['memo']['recommendation_claims'] if c['source_id'] == 'S4')
    assert claim['quote'] in TABLE and '0.34' not in claim['quote']
    assert sources[-1]['passage'] == TABLE
    _, _, requests, _ = author.frozen_unit_requests(memo, sources, proof, PIN, contract=author.CONTRACT_V5)
    assert record['offered_evidence_spans'] == author.frozen_offered_spans(sources, requests)
    assert author.run_author(memo, sources, proof, PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=author.CONTRACT_V5) == record
