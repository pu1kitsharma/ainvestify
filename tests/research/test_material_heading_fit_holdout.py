"""Offline exact-quote heading-fit holdout checks."""

from scripts import evaluate_local_heading_fit_holdout as probe


def test_holdout_separates_topic_fit_from_source_support_and_hides_labels():
    data, fixture_hash = probe.fixture()
    assert [row['expected_fit'] for row in data['rows']] == [True, True, False, True]
    assert data['rows'][0]['body'] == data['rows'][2]['body']
    assert data['rows'][3]['expected_source_support'] is False
    input_ = probe.payload(data, fixture_hash, {'name': 'local', 'digest': 'fixed'})
    assert 'expected_fit' not in str(input_)
    assert 'expected_source_support' not in str(input_)
    assert set(probe.schema().model_json_schema()['required']) == {'h01', 'h02', 'h03', 'h04'}


def test_holdout_requires_every_label_and_both_exact_quotes():
    data, fixture_hash = probe.fixture()
    answer = {row['row_id']: {'fit': row['expected_fit'],
                              'heading_quote': row['heading'], 'body_quote': row['body'],
                              'reason': 'The body subject matches the heading.'}
              for row in data['rows']}
    attempts = [{'id': 'response_1', 'raw_response': 'raw', 'answer': answer}]
    assert probe.score(data, fixture_hash, attempts, {})['decision'] == 'go'
    answer['h04']['fit'] = False
    assert probe.score(data, fixture_hash, attempts, {})['decision'] == 'no_go'
    answer['h04']['fit'] = True
    answer['h02']['body_quote'] = 'a paraphrase'
    card = probe.score(data, fixture_hash, attempts, {})
    assert card['decision'] == 'no_go'
    assert card['rows'][1]['outcome'] == 'unbound_quote'
