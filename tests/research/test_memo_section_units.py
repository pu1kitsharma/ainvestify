"""Synthetic full-section authorship is source-only, bounded and replayable."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_section_units as core
from tests.research.test_memo_causal_review import sample
from tests.research.test_memo_source_unit_author import PIN

TEXT = {
    'investment_thesis': 'If the reported financing can be confirmed as operating capital, the company could merit further investment diligence; the registry report alone does not demonstrate that this conditional case is established.',
    'business_and_market': 'The registry reports a financing entry whose completion status is unknown and whose reported entry does not state current cash availability; this source report is not independent verification of available capital.',
    'differentiation_and_execution': 'The registry reports uncertain transaction completion and does not state current cash availability; confirming completion and available cash could help assess whether the reported position supports execution.',
    'risks_and_countercase': 'If the reported transaction did not complete, anticipated operating capital could fail to materialize and undermine execution; this is a conditional adverse mechanism rather than evidence that the failure occurred.',
    'diligence_plan': 'Request dated transaction and account records to verify the reported completion status and operating capital position; those records would help determine whether the registry entry can support a diligence decision.'}


class Model:
    name = PIN['name']
    thinking = False
    max_tokens = 600
    context_tokens = 8192
    temperature = 0

    def __init__(self, invalid_fields=(), malformed_fields=()):
        self.invalid_fields, self.malformed_fields = invalid_fields, malformed_fields
        self.calls = 0

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        self.calls += 1
        assert task == core.TASK
        payload = json.loads(evidence)
        field = payload['field']
        assert instruction == (core.RETRY_INSTRUCTION if payload.get('correction_number') else core.INSTRUCTION)
        answer = {'units': {sid: {'supporting_evidence_id': next(iter(payload['sources'][sid]['spans'])),
            'status': core.STATUSES[field][0], 'standalone_text': TEXT[field]}
            for sid in payload['unit_source_ids']}}
        if field in self.invalid_fields and not payload.get('correction_number'):
            first = payload['unit_source_ids'][0]
            answer['units'][first]['standalone_text'] = TEXT[field].replace('registry', 'FY99 registry')
        if field in self.malformed_fields and not payload.get('correction_number'):
            answer['units'] = {}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name, **core.OPTIONS}
        return schema.model_validate(answer)


def execute(memo, sources, model, rows=None):
    rows = [] if rows is None else rows
    budget = PreparationBudget(105, max_calls=6, max_requests=6)
    result = None
    for _ in range(6):
        result = core.run_author(memo, sources, PIN, rows, lambda: None, model, budget)
        if result['state'] == 'accepted':
            return result, rows
    return result, rows


def test_five_fields_source_only_no_old_prose_or_assertions_and_countercase_purpose():
    memo, sources = sample()
    for field in core.FIELDS:
        memo[field]['analysis'] = 'Old flawed no financial figures exist statement ' * 5
        memo[field]['claims'][0]['assertion'] = 'OLD_UNTRUSTED_ASSERTION not established.'
    original = copy.deepcopy(memo)
    frozen = core.frozen_requests(memo, sources, PIN)
    for field, payload, schema in frozen:
        serialized = json.dumps(payload)
        assert 'Old flawed' not in serialized and 'OLD_UNTRUSTED' not in serialized
        assert 'source_cards' not in payload and 'source_characterization' not in payload
        assert 'reported INR 2 crore amount' in serialized
        assert all(source['verification_status'] == 'source_report_only' for source in payload['sources'].values())
        assert all(len(span) <= 600 for source in payload['sources'].values() for span in source['spans'].values())
        assert len(payload['unit_source_ids']) <= 2
    risk = next(row for row in frozen if row[0] == 'risks_and_countercase')
    assert 'adverse mechanism' in risk[1]['required_field_purpose']
    bad = {'units': {'S1': {'supporting_evidence_id': 'S1.e001', 'status': 'source_reported', 'standalone_text': TEXT['risks_and_countercase']}}}
    with pytest.raises(ValueError):
        risk[2].model_validate(bad)
    result, rows = execute(memo, sources, Model())
    assert result['state'] == 'accepted' and len(rows) == 5
    assert result['memo']['recommendation_reason'] == memo['recommendation_reason']
    assert result['memo']['unknowns'] == memo['unknowns']
    assert 'no financial figures' not in json.dumps(result['field_patches'])
    assert 'fail to materialize' in result['memo']['risks_and_countercase']['analysis']
    assert memo == original
    assert set(result['field_patches']) == set(result['disjoint_fields']) == set(core.FIELDS)
    for field in core.FIELDS:
        assert result['field_patches'][field] == result['memo'][field]
        assert result['memo'][field]['claims'][0]['assertion'] == rows[list(core.FIELDS).index(field)]['answer']['units']['S1']['standalone_text']
        assert result['memo'][field]['claims'][0]['quote'] == sources[0]['passage']
    assert core.run_author(memo, sources, PIN, rows, lambda: None, None, SimpleNamespace(calls=0,max_calls=0)) == result


def test_one_global_numeric_or_shape_correction_and_never_more_than_six_calls():
    memo, sources = sample()
    model = Model(invalid_fields=['business_and_market'])
    result, rows = execute(memo, sources, model)
    assert result['state'] == 'accepted' and len(rows) == model.calls == 6
    assert 'numbers or dates' in rows[2]['input']['validation_error']
    assert 'previous_invalid_answer' not in rows[2]['input']
    bad_model, bad_rows = Model(invalid_fields=['business_and_market','differentiation_and_execution']), []
    with pytest.raises(ValueError, match='global validation correction exhausted'):
        execute(memo, sources, bad_model, bad_rows)
    assert len(bad_rows) == bad_model.calls == 4
    shaped, shaped_rows = execute(memo, sources, Model(malformed_fields=['investment_thesis']))
    assert shaped['state'] == 'accepted' and len(shaped_rows) == 6
    assert shaped_rows[0]['failure_kind'] == 'schema_validation'


def test_exact_lineage_tamper_no_model_resume_and_transport_terminal():
    memo, sources = sample()
    result, rows = execute(memo, sources, Model())
    assert result['response_hash'] == core.digest([{'id': row['id'], 'response_hash': row['response_hash']} for row in rows])
    for change in ('input','raw','schema','identity'):
        changed = copy.deepcopy(rows)
        if change == 'input': changed[0]['input']['old_analysis'] = 'Untrusted draft'
        if change == 'raw': changed[0]['raw_response'] += ' '
        if change == 'schema': changed[0]['schema']['title'] = 'Other schema'
        if change == 'identity': changed[1]['id'] = changed[0]['id']
        with pytest.raises(ValueError):
            core.run_author(memo, sources, PIN, changed, lambda: None, None, SimpleNamespace(calls=0,max_calls=0))
    pending = core.run_author(memo, sources, PIN, [], lambda: None, None, SimpleNamespace(calls=0,max_calls=0))
    assert pending['state'] == 'needs_resume' and pending['pending_field'] == 'investment_thesis'
    changed = copy.deepcopy(rows[:1]); changed[0]['error'] = 'timed out'; changed[0]['failure_kind'] = 'transport'
    model = Model()
    with pytest.raises(ValueError, match='transport/inference failed'):
        core.run_author(memo, sources, PIN, changed, lambda: None, model, PreparationBudget(105,max_calls=6))
    assert model.calls == 0


def test_original_links_only_scope_at_most_two_own_evidence_and_metric_binding():
    memo, sources = sample()
    for sid in ('S2','S3'):
        memo['business_and_market']['claims'].append({'source_id':sid,'quote':sources[int(sid[1:])-1]['passage'],'assertion':'Prior assertion is untrusted and cannot be author evidence.'})
    field, payload, schema = next(row for row in core.frozen_requests(memo,sources,PIN) if row[0]=='business_and_market')
    assert payload['unit_source_ids'] == ['S1','S2']
    obj = {'units': {sid: {'supporting_evidence_id':sid+'.e001','status':'source_reported','standalone_text':TEXT[field]} for sid in payload['unit_source_ids']}}
    obj['units']['S1']['supporting_evidence_id'] = 'S2.e001'
    with pytest.raises(ValueError): schema.model_validate(obj)
    only = next(row for row in core.frozen_requests(*sample(),PIN) if row[0]=='business_and_market')
    answer = {'units': {'S1': {'supporting_evidence_id':'S1.e001','status':'source_reported',
        'standalone_text':'The registry reports revenue of INR 2 crore and uncertain completion status; this is a source-reported figure rather than independent verification of available operating capital.'}}}
    with pytest.raises(ValueError,match='Economic metric "revenue"'):
        core._project_field(memo,*only,answer)
