"""Offline checks for the independent synthetic compact holdout."""
import copy

from scripts import evaluate_local_material_scale_holdout as holdout


def test_holdout_fixture_is_independent_and_expectations_stay_out_of_model_input():
    data, fixture_hash = holdout.fixture()
    assert len(fixture_hash) == 64
    assert [r['expected'] for r in data['decks']['intro_deck']] == [
        'supported_as_source_report', 'supported_as_source_report', 'unsupported_assertion']
    assert [r['expected'] for r in data['decks']['pitch_deck']] == [
        'supported_as_source_report', 'supported_as_source_report', 'unsupported_assertion']
    for deck, rows in data['decks'].items():
        payload = holdout.payload(deck, rows, {'name': 'local', 'digest': 'fixed'}, fixture_hash)
        assert payload['probe_contract'] == holdout.CONTRACT
        assert 'expected' not in str(payload)
        assert set(holdout.compact_schema(deck, rows).model_json_schema()['required']) == {
            'r01', 'r02', 'r03'}


def test_holdout_requires_correct_control_and_exact_defect_clause():
    data, fixture_hash = holdout.fixture()
    answers = {}
    for deck, rows in data['decks'].items():
        answers[deck] = {
            f'r{i:02d}': {'classification': row['expected'],
                          'challenged_clause': ('funding received' if deck == 'intro_deck' else
                                                'signed multi-year customer contracts')
                          if row['expected'] == 'unsupported_assertion' else None,
                          'reason': 'This relation follows the cited span.'}
            for i, row in enumerate(rows, 1)}
    # The first invented funding clause is not an exact substring, so it fails closed.
    attempts = [{'id': f'response_{i}', 'input': {'deck': deck}, 'answer': answers[deck],
                 'raw_response': 'raw'} for i, deck in enumerate(data['decks'], 1)]
    card = holdout.score(data, attempts, {'name': 'local', 'digest': 'fixed'}, fixture_hash)
    assert card['decision'] == 'no_go'
    assert sum(r['passed'] for r in card['rows']) == 5
    fixed = copy.deepcopy(attempts)
    fixed[0]['answer']['r03']['challenged_clause'] = 'all INR 5 crore reached'
    card = holdout.score(data, fixed, {'name': 'local', 'digest': 'fixed'}, fixture_hash)
    assert card['decision'] == 'go'
    fixed[1]['answer']['r02']['classification'] = 'insufficient_evidence'
    assert holdout.score(data, fixed, {'name': 'local', 'digest': 'fixed'}, fixture_hash)['decision'] == 'no_go'
