"""Synthetic source-local Part B flow and saved-response replay."""
import json

import pytest

from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research.memo_bound_section_flow import (replay_section, run_section,
                                                     saved_section_ids)


QUOTE_A = ('A synthetic registry reports that Example Labs operates a clinic '
           'pilot; it gives no customer contract or financial result.')
QUOTE_B = ('The synthetic publisher lists an unresolved delivery audit and '
           'offers no audited service level record for the pilot.')
SENTENCE_A = ('The cited publisher reports a clinic pilot, which requires a '
              'primary operating record before the delivery claim can be weighed.')
SENTENCE_B = ('The cited publisher leaves contract proof unresolved, so a '
              'customer record would be material to the investment decision.')


def _payload(field='risks_and_countercase', *, version='v9'):
    return {'company': 'Example Labs', 'field': field,
            'draft_contract': 'part-b-sections-' + version,
            'complete_source_set_digest': 'snapshot-digest',
            'sources': [{'source_id': 'S1', 'evidence': [
                {'quote_id': 'S1.q1', 'quote': QUOTE_A, 'status': 'source_reported'}]},
                {'source_id': 'S2', 'evidence': [
                    {'quote_id': 'S2.q1', 'quote': QUOTE_B, 'status': 'source_reported'}]}]}


class ScriptedModel:
    name = 'synthetic-scripted'

    def __init__(self, *, bad_number=False, long_sentence=False,
                 numeric_sentence=False, numeric_assertion=False,
                 very_long_sentence=False, name=None):
        self.last_response_text = ''
        self.calls = []
        self.bad_number = bad_number
        self.long_sentence = long_sentence
        self.numeric_sentence = numeric_sentence
        self.numeric_assertion = numeric_assertion
        self.very_long_sentence = very_long_sentence
        if name:
            self.name = name

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        data = json.loads(evidence)
        self.calls.append((task, data))
        if task.endswith('_select'):
            answer = {'heading': 'Operating risk and verification',
                      'quote_ids': ['S1.q1', 'S2.q1']}
        else:
            assertion = ('The source reports 47 completed contracts.' if self.bad_number
                         else 'The source reports a pilot with unresolved proof.' )
            if self.numeric_assertion:
                assertion = 'The source reports one clinic pilot.'
            first = (SENTENCE_A[:-1] + ', while the retained record leaves '
                     'contract proof unresolved for primary verification.'
                     if self.long_sentence else SENTENCE_A)
            if self.very_long_sentence:
                first = (SENTENCE_A[:-1] + ', while the retained record leaves '
                         'contract proof unresolved for primary verification '
                         'and the decision must await primary records before '
                         'treating that report as evidence.')
            if self.numeric_sentence:
                first = first.replace('a clinic pilot', 'a 47 clinic pilot')
            answer = {'assertion': assertion,
                      'sentences': [first, SENTENCE_B]}
        self.last_response_text = json.dumps(answer)
        return schema.model_validate(answer)


def test_two_selected_quotes_are_authored_in_separate_source_local_calls():
    model, attempts = ScriptedModel(), []
    with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
        result = run_section(model, 'risks_and_countercase', _payload(),
                             attempts, lambda: None, budget)
    section, ids = result
    assert [claim.quote for claim in section.claims] == [QUOTE_A, QUOTE_B]
    assert section.analysis.count('[S1]') == 2
    assert section.analysis.count('[S2]') == 2
    assert len(ids['authors']) == 2
    assert len(model.calls) == 3
    for task, supplied in model.calls[1:]:
        assert task.endswith(('_author_0', '_author_1'))
        assert supplied['exact_quote'] in {QUOTE_A, QUOTE_B}
        assert 'sources' not in supplied
        assert (QUOTE_B if supplied['exact_quote'] == QUOTE_A else QUOTE_A) not in json.dumps(supplied)
    assert replay_section('risks_and_countercase', _payload(), attempts, ids) == section
    assert saved_section_ids('risks_and_countercase', _payload(), attempts) == ids
    assert saved_section_ids('risks_and_countercase', _payload(), attempts[:-1]) is None
    tampered = [dict(row) for row in attempts]
    tampered[-1]['raw_response'] += ' '
    with pytest.raises(ValueError, match='raw response changed'):
        saved_section_ids('risks_and_countercase', _payload(), tampered)
    altered = _payload()
    altered['sources'][0]['evidence'][0]['quote'] += ' changed'
    with pytest.raises(ValueError):
        replay_section('risks_and_countercase', altered, attempts, ids)


def test_numeric_defect_is_retained_but_never_projected():
    model, attempts = ScriptedModel(bad_number=True), []
    with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
        result = run_section(model, 'risks_and_countercase', _payload(),
                             attempts, lambda: None, budget)
    assert result is None
    assert attempts[-1]['failure_kind'] == 'schema_validation'
    assert '47 completed contracts' in attempts[-1]['raw_response']


def test_v10_accepts_longer_source_local_sentence_and_preserves_v9_replay():
    old_model, old_attempts = ScriptedModel(), []
    with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
        old_section, old_ids = run_section(old_model, 'risks_and_countercase',
                                           _payload(), old_attempts, lambda: None, budget)
    fresh_model, fresh_attempts = ScriptedModel(long_sentence=True), []
    with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
        fresh_section, fresh_ids = run_section(fresh_model, 'risks_and_countercase',
                                               _payload(version='v10'), fresh_attempts,
                                               lambda: None, budget)
    assert len(fresh_model.calls[1][1]['exact_quote']) == len(QUOTE_A)
    assert 150 < len(fresh_attempts[1]['answer']['sentences'][0]) <= 240
    assert all('_v10_' in row['task'] for row in fresh_attempts)
    assert all('_v9_' in row['task'] for row in old_attempts)
    assert replay_section('risks_and_countercase', _payload(), old_attempts, old_ids) == old_section
    assert saved_section_ids('risks_and_countercase', _payload(version='v10'),
                             fresh_attempts) == fresh_ids
    assert replay_section('risks_and_countercase', _payload(version='v10'),
                          fresh_attempts, fresh_ids) == fresh_section
    with pytest.raises(ValueError):
        replay_section('risks_and_countercase', _payload(), fresh_attempts, fresh_ids)


def test_v11_numeric_free_analysis_and_all_older_replays():
    saved = []
    for version in ('v9', 'v10', 'v11'):
        model, attempts = ScriptedModel(long_sentence=version != 'v9'), []
        with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
            section, ids = run_section(model, 'risks_and_countercase',
                                       _payload(version=version), attempts,
                                       lambda: None, budget)
        assert saved_section_ids('risks_and_countercase', _payload(version=version),
                                 attempts) == ids
        saved.append((version, section, ids, attempts))
    assert all(replay_section('risks_and_countercase', _payload(version=version),
                              attempts, ids) == section
               for version, section, ids, attempts in saved)
    assert all('_v11_' in row['task'] for row in saved[-1][3])
    numeric_model, numeric_attempts = ScriptedModel(numeric_sentence=True), []
    with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
        result = run_section(numeric_model, 'risks_and_countercase',
                             _payload(version='v11'), numeric_attempts,
                             lambda: None, budget)
    assert result is None
    assert numeric_attempts[-1]['failure_kind'] == 'schema_validation'


def test_v12_keeps_figures_only_in_exact_quote_and_replays_older_versions():
    for version in ('v9', 'v10', 'v11', 'v12'):
        model, attempts = ScriptedModel(long_sentence=version != 'v9'), []
        payload = _payload(version=version)
        with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
            section, ids = run_section(model, 'risks_and_countercase', payload,
                                       attempts, lambda: None, budget)
        assert saved_section_ids('risks_and_countercase', payload, attempts) == ids
        assert replay_section('risks_and_countercase', payload, attempts, ids) == section
        assert all('_' + version + '_' in row['task'] for row in attempts)
    defective, attempts = ScriptedModel(numeric_assertion=True), []
    with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
        result = run_section(defective, 'risks_and_countercase',
                             _payload(version='v12'), attempts,
                             lambda: None, budget)
    assert result is None
    assert attempts[-1]['failure_kind'] == 'schema_validation'
    assert 'one clinic pilot' in attempts[-1]['raw_response']


def test_v13_uses_distinct_selector_and_author_models_with_longer_sentence():
    selector = ScriptedModel(name='synthetic-9b')
    author = ScriptedModel(very_long_sentence=True, name='synthetic-14b')
    attempts, payload = [], _payload(version='v13')
    with preparation_budget(PreparationBudget(max_seconds=10, max_calls=3)) as budget:
        section, ids = run_section(author, 'risks_and_countercase', payload,
                                   attempts, lambda: None, budget,
                                   selector_model=selector)
    assert len(selector.calls) == 1
    assert len(author.calls) == 2
    assert all('_v13_' in row['task'] for row in attempts)
    assert attempts[0]['model'] == 'synthetic-9b'
    assert all(row['model'] == 'synthetic-14b' for row in attempts[1:])
    assert 240 < len(attempts[1]['answer']['sentences'][0]) <= 300
    assert saved_section_ids('risks_and_countercase', payload, attempts) == ids
    assert replay_section('risks_and_countercase', payload, attempts, ids) == section
