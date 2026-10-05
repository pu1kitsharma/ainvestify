"""Offline finite heading/body fit diagnostic checks."""

from scripts import evaluate_local_heading_fit_probe as probe


def fixture():
    body = 'Audited financial statements are missing from the supplied evidence [S1].'
    cases = {
        'synthetic_pair': [{'row_id': 'h01', 'heading': 'Financial Evidence Gap', 'body': body},
                           {'row_id': 'h02', 'heading': 'Market Context', 'body': body}],
        'intro_deck': [{'row_id': 'h01', 'heading': 'Market Context', 'body': body}],
        'pitch_deck': [{'row_id': 'h01', 'heading': 'Financial Unknowns', 'body': body}],
    }
    return {'source_digest': 'fixed'}, cases


def test_heading_pair_has_shared_body_required_rows_and_three_calls():
    source, cases = fixture()
    expected = probe.expected_calls(source, cases, {'name': 'local', 'digest': 'fixed'})
    assert [name for name, _, _ in expected] == [
        'synthetic_pair', 'intro_deck', 'pitch_deck']
    pair = expected[0][1]['rows']
    assert pair[0]['body'] == pair[1]['body']
    assert pair[0]['heading'] != pair[1]['heading']
    assert set(expected[0][2].model_json_schema()['required']) == {'h01', 'h02'}


def test_heading_pair_requires_clean_fit_and_defect_rejection():
    source, cases = fixture()
    attempts = [
        {'id': 'response_1', 'input': {'case': 'synthetic_pair'}, 'raw_response': 'raw',
         'answer': {'h01': {'fit': True, 'reason': 'This is financial evidence.'},
                    'h02': {'fit': False, 'reason': 'This is not market context.'}}},
        {'id': 'response_2', 'input': {'case': 'intro_deck'}, 'raw_response': 'raw',
         'answer': {'h01': {'fit': False, 'reason': 'The heading is about markets.'}}},
        {'id': 'response_3', 'input': {'case': 'pitch_deck'}, 'raw_response': 'raw',
         'answer': {'h01': {'fit': True, 'reason': 'Financial unknowns are described.'}}},
    ]
    assert probe.score(source, cases, attempts, {})['pair_decision'] == 'go'
    attempts[0]['answer']['h02']['fit'] = True
    assert probe.score(source, cases, attempts, {})['pair_decision'] == 'no_go'
