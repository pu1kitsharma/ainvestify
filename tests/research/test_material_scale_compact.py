"""Offline contract tests for compact synthetic material scale diagnostic."""
import json

import pytest

from scripts import evaluate_local_material_scale_compact as probe
from agents.inference.model_authorship import digest


def rows():
    return [
        {'sentence_id': 'intro_deck.slide_1.sentence_1', 'sentence': 'A registry reports a round [S1].',
         'source_spans': [{'exact_span': '[S1] A registry reports a round.'},
                          {'exact_span': '[S1] The status is unknown.'}]},
        {'sentence_id': 'intro_deck.slide_1.sentence_2', 'sentence': 'The round status is unknown [S1].',
         'source_spans': [{'exact_span': '[S1] The status is unknown.'}]},
    ]


def test_shared_span_table_preserves_exact_row_scope_and_reduces_repetition():
    input_rows = rows()
    before = json.dumps(input_rows)
    payload = probe.compact_payload('intro_deck', input_rows,
                                    {'name': 'local', 'digest': 'fixed'}, 'source')
    assert payload['probe_contract'] == probe.CONTRACT
    assert payload['memo_spans'] == {
        'e01': '[S1] A registry reports a round.',
        'e02': '[S1] The status is unknown.',
    }
    assert [row['span_ids'] for row in payload['rows']] == [['e01', 'e02'], ['e02']]
    assert json.dumps(input_rows) == before
    assert set(probe.compact_schema('intro_deck', input_rows).model_json_schema()['required']) == {
        'r01', 'r02'}


def test_compact_scale_reports_unknown_and_invalid_clause_without_silent_pass():
    source = {'source_digest': 'source', 'rows': {'intro_deck': rows(), 'pitch_deck': rows()}}
    answer = {'r01': {'classification': 'supported_as_source_report',
                      'challenged_clause': None, 'reason': 'The registry span says the same thing.'},
              'r02': {'classification': 'insufficient_evidence',
                      'challenged_clause': 'The round status is unknown',
                      'reason': 'The span does not establish this point.'}}
    attempts = [{'id': f'response_{i}', 'input': {'deck': deck}, 'answer': answer,
                 'raw_response': 'raw', 'elapsed_seconds': 1}
                for i, deck in enumerate(source['rows'], 1)]
    card = probe.score(source, attempts, {'name': 'local', 'digest': 'fixed'})
    assert card['decision'] == 'incomplete_fail_closed'
    assert card['row_count'] == 4 and card['model_calls'] == 2
    assert [row['outcome'] for row in card['rows']] == [
        'answered', 'unbound_challenged_clause', 'answered', 'unbound_challenged_clause']
    assert not card['investor_material_accepted']


def test_recorded_source_replay_tolerates_later_files_but_rejects_changed_input():
    recorded = {name: 'hash' for name in probe.INPUT_FILES}
    source = {'source_files': {**recorded, 'later_review.json': 'new'},
              'source_digest': 'later'}
    profile = {'source_files': recorded, 'source_digest': digest(recorded)}
    projected = probe.recorded_source(source, profile)
    assert projected['source_files'] == recorded
    assert projected['source_digest'] == digest(recorded)
    source['source_files']['intro.pptx'] = 'tampered'
    with pytest.raises(ValueError, match='source files changed'):
        probe.recorded_source(source, profile)


@pytest.mark.parametrize('deck', ['memo', '', 'pitch_deck'])
def test_deck_and_row_caps(deck):
    candidate = rows() * (17 if deck == 'pitch_deck' else 1)
    with pytest.raises(ValueError, match='cap'):
        probe.compact_payload(deck, candidate, {'name': 'local', 'digest': 'fixed'}, 'source')
