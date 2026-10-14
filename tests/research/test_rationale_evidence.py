"""Synthetic blind source characterization, immutable binding and bounded replay."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import rationale_evidence as evidence
from tests.research.test_memo_causal_review import sample

PIN = {'name': 'local-synthetic', 'digest': 'a' * 64}


def sources(count=2, passage=None):
    template = sample()[1][0]
    return [{**template, 'id': f'S{i}',
             'passage': passage or 'The source reports historical revenue and a projected exit target.'}
            for i in range(1, count + 1)]


def answer(payload, explicit=False):
    return {source['id']: {
        'reporting_basis': 'mixed',
        'contains_explicit_incomplete_quantification_claim': explicit,
        'explicit_quantification_evidence_id': next(iter(source['spans'])) if explicit else None,
        **({'historical_evidence_id': next(iter(source['spans'])),
            'projected_evidence_id': next(iter(source['spans']))}
           if payload['contract'] == evidence.CONTRACT else {}),
        'reason': 'The source distinguishes reported history from a projected exit target.'}
        for source in payload['sources']}


class Model:
    name = PIN['name']
    thinking = False
    max_tokens = 1400
    context_tokens = 8192
    temperature = 0

    def __init__(self, invalid=False):
        self.invalid, self.calls = invalid, 0

    def generate_for_task(self, task, instruction, text, schema, *, attempt=0):
        payload = json.loads(text)
        assert task == evidence.TASK
        assert 'memo' not in payload and 'sentences' not in payload
        assert instruction == (evidence.INSTRUCTION if not self.calls else evidence.RETRY_INSTRUCTION)
        self.calls += 1
        result = answer(payload)
        if self.invalid and self.calls == 1:
            result['S1']['contains_explicit_incomplete_quantification_claim'] = True
        self.last_response_text = json.dumps(result)
        self.last_route = {'model': self.name, **evidence.OPTIONS}
        return schema.model_validate(result)


def budget():
    return PreparationBudget(60, max_calls=2, max_requests=2)


def test_payload_is_blind_exact_full_source_without_text_duplication():
    retained = sources(6, 'Historical rows\n' + 'x' * 1200 + '\nForecast target')
    payload, _ = evidence.frozen_request(retained, PIN)
    assert set(payload) == {'contract', 'model_name', 'model_digest', 'source_digest', 'sources', 'evidence'}
    for source, original in zip(payload['sources'], retained):
        assert ''.join(source['spans'].values()) == original['passage']
        assert max(map(len, source['spans'].values())) <= 600
        for eid, text in source['spans'].items():
            span = payload['evidence'][eid]
            assert text == original['passage'][span['start']:span['end']]
            assert 'exact_text' not in span


def test_selected_evidence_must_match_explicit_flag_and_own_source():
    payload, schema = evidence.frozen_request(sources(), PIN)
    cards = answer(payload)
    assert evidence._cards(payload, schema, cards) == cards
    cards['S1']['contains_explicit_incomplete_quantification_claim'] = True
    with pytest.raises(ValueError, match='requires evidence'):
        evidence._cards(payload, schema, cards)
    cards['S1']['explicit_quantification_evidence_id'] = 'S2.e001'
    with pytest.raises(ValueError):
        evidence._cards(payload, schema, cards)
    cards['S1']['explicit_quantification_evidence_id'] = 'S1.e001'
    assert evidence._cards(payload, schema, cards) == cards
    cards['S1']['contains_explicit_incomplete_quantification_claim'] = False
    with pytest.raises(ValueError, match='null evidence'):
        evidence._cards(payload, schema, cards)


def test_recorded_model_cards_replay_exactly_and_tampering_blocks():
    retained, rows, model = sources(), [], Model()
    result = evidence.characterize_sources(retained, PIN, rows, lambda: None, model, budget())
    assert result['state'] == 'accepted' and model.calls == 1
    assert evidence.characterize_sources(retained, PIN, rows, lambda: None, None,
                                        SimpleNamespace(calls=0, max_calls=0)) == result
    changed = copy.deepcopy(retained)
    changed[0]['version'] = 'changed-version'
    with pytest.raises(ValueError, match='frozen contract'):
        evidence.characterize_sources(changed, PIN, rows, lambda: None, None, budget())
    rows[0]['routing']['temperature'] = 0.9
    with pytest.raises(ValueError, match='frozen contract'):
        evidence.characterize_sources(retained, PIN, rows, lambda: None, None, budget())


def test_binding_invalid_answer_gets_one_recorded_correction():
    retained, rows, model = sources(), [], Model(invalid=True)
    first = evidence.characterize_sources(retained, PIN, rows, lambda: None, model, budget())
    assert first['state'] == 'needs_resume' and len(rows) == 1
    result = evidence.characterize_sources(retained, PIN, rows, lambda: None, model, budget())
    assert result['state'] == 'accepted' and model.calls == 2
    assert rows[1]['input']['correction_number'] == 1
    assert rows[1]['input']['previous_invalid_answer'] == rows[0]['answer']
    assert evidence.characterize_sources(retained, PIN, rows, lambda: None, None, budget()) == result


def test_no_model_or_budget_stays_pending_and_limits_reject():
    assert evidence.characterize_sources(sources(), PIN, [], lambda: None, None,
                                        SimpleNamespace(calls=0, max_calls=0))['state'] == 'needs_resume'
    spent = budget()
    spent.calls = spent.max_calls
    model = Model()
    assert evidence.characterize_sources(sources(), PIN, [], lambda: None, model, spent)['state'] == 'needs_resume'
    assert model.calls == 0
    with pytest.raises(ValueError, match='unique'):
        evidence.frozen_request(sources(9), PIN)
    with pytest.raises(ValueError, match='text limit'):
        evidence.frozen_request(sources(6, 'x' * 4000), PIN)


def test_raw_hash_and_answer_changes_cannot_be_replayed():
    retained, rows = sources(), []
    evidence.characterize_sources(retained, PIN, rows, lambda: None, Model(), budget())
    rows[0]['answer']['S1']['reporting_basis'] = 'historical'
    with pytest.raises(ValueError, match='original response'):
        evidence.characterize_sources(retained, PIN, rows, lambda: None, None, budget())


def test_schema_malformed_answer_is_preserved_then_corrected_once():
    class SchemaMalformed(Model):
        def generate_for_task(self, task, instruction, text, schema, *, attempt=0):
            if self.calls:
                return super().generate_for_task(task, instruction, text, schema, attempt=attempt)
            self.calls += 1
            payload = json.loads(text)
            result = answer(payload)
            del result['S1']['reporting_basis']
            self.last_response_text = json.dumps(result)
            self.last_route = {'model': self.name, **evidence.OPTIONS}
            return schema.model_validate(result)

    retained, rows, model = sources(), [], SchemaMalformed()
    first = evidence.characterize_sources(retained, PIN, rows, lambda: None, model, budget())
    assert first['state'] == 'needs_resume'
    assert rows[0]['failure_kind'] == 'schema_validation'
    result = evidence.characterize_sources(retained, PIN, rows, lambda: None, model, budget())
    assert result['state'] == 'accepted' and len(rows) == 2


def test_second_invalid_answer_is_terminal_without_extra_inference():
    class AlwaysInvalid(Model):
        def generate_for_task(self, task, instruction, text, schema, *, attempt=0):
            self.calls += 1
            result = answer(json.loads(text))
            result['S1']['contains_explicit_incomplete_quantification_claim'] = True
            self.last_response_text = json.dumps(result)
            self.last_route = {'model': self.name, **evidence.OPTIONS}
            return schema.model_validate(result)

    retained, rows, model = sources(), [], AlwaysInvalid()
    assert evidence.characterize_sources(retained, PIN, rows, lambda: None, model, budget())['state'] == 'needs_resume'
    with pytest.raises(ValueError, match='correction exhausted'):
        evidence.characterize_sources(retained, PIN, rows, lambda: None, model, budget())
    assert model.calls == len(rows) == 2


def test_v2_time_basis_requires_corresponding_exact_source_evidence():
    payload, schema = evidence.frozen_request(sources(), PIN)
    cards = answer(payload)
    for basis, historical, projected in (
        ('historical', 'S1.e001', None),
        ('projected', None, 'S1.e001'),
        ('mixed', 'S1.e001', 'S1.e001'),
        ('not_stated', None, None),
    ):
        cards['S1'].update(reporting_basis=basis, historical_evidence_id=historical,
                           projected_evidence_id=projected)
        assert evidence._cards(payload, schema, cards) == cards
    cards['S1'].update(reporting_basis='mixed', historical_evidence_id=None,
                       projected_evidence_id='S1.e001')
    with pytest.raises(ValueError, match='corresponding'):
        evidence._cards(payload, schema, cards)
    cards['S1']['historical_evidence_id'] = 'S2.e001'
    with pytest.raises(ValueError):
        evidence._cards(payload, schema, cards)


def test_v1_recorded_contract_replays_without_new_evidence_fields():
    from agents.inference.model_authorship import recorded_call

    class Legacy(Model):
        def generate_for_task(self, task, instruction, text, schema, *, attempt=0):
            assert task == evidence.TASK_V1 and instruction == evidence.INSTRUCTION_V1
            result = answer(json.loads(text))
            assert 'historical_evidence_id' not in result['S1']
            self.last_response_text = json.dumps(result)
            self.last_route = {'model': self.name, **evidence.OPTIONS}
            return schema.model_validate(result)

    retained, rows = sources(), []
    payload, schema = evidence.frozen_request(retained, PIN, evidence.CONTRACT_V1)
    recorded_call(Legacy(), evidence.TASK_V1, evidence.INSTRUCTION_V1, payload,
                  schema, rows, lambda: None)
    record = evidence.characterize_sources(retained, PIN, rows, lambda: None, None, budget())
    assert record['contract'] == evidence.CONTRACT_V1
    assert 'historical_evidence_id' not in record['source_cards']['S1']
