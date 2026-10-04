"""Offline bounds and pair scoring for the frozen synthetic fresh-draft probe."""

from scripts import evaluate_local_material_fresh_pair as probe


def source():
    control_intro = [{'sentence_id': 'intro_deck.slide_1.sentence_1', 'heading': 'Funding',
                      'sentence': 'The registry lists a round with unknown status [S1].',
                      'source_spans': [{'exact_span': '[S1] The round status is unknown.'}]}]
    defect_intro = [*control_intro,
                    {'sentence_id': 'intro_deck.slide_1.sentence_2', 'heading': 'Funding',
                     'sentence': 'The company received all funds [S1].',
                     'source_spans': [{'exact_span': '[S1] The round status is unknown.'}]}]
    pitch = [{'sentence_id': 'pitch_deck.slide_1.sentence_1', 'heading': 'Product',
              'sentence': 'The company reports a pilot [S2].',
              'source_spans': [{'exact_span': '[S2] A pilot is reported.'}]}]
    return {'source_digest': 'synthetic',
            'control_rows': {'intro_deck': control_intro, 'pitch_deck': pitch},
            'defect_intro_rows': defect_intro,
            'planted_sentence_id': 'intro_deck.slide_1.sentence_2'}


def answer(label, clause=None):
    return {'classification': label, 'challenged_clause': clause,
            'reason': 'The sentence is compared with its cited span.'}


def attempts():
    return [
        {'id': 'response_1', 'input': {'case': 'control_intro'}, 'raw_response': 'raw',
         'answer': {'r01': answer('supported_as_source_report')}},
        {'id': 'response_2', 'input': {'case': 'control_pitch'}, 'raw_response': 'raw',
         'answer': {'r01': answer('supported_as_source_report')}},
        {'id': 'response_3', 'input': {'case': 'defect_intro'}, 'raw_response': 'raw',
         'answer': {'r01': answer('supported_as_source_report'),
                    'r02': answer('unsupported_assertion', 'received all funds')}},
    ]


def test_fresh_pair_has_three_bounded_calls_and_shared_pitch():
    expected = probe.calls(source(), {'name': 'local', 'digest': 'fixed'})
    assert [name for name, _, _ in expected] == [
        'control_intro', 'control_pitch', 'defect_intro']
    assert [len(payload['rows']) for _, payload, _ in expected] == [1, 1, 2]
    assert all(payload['probe_contract'] == probe.CONTRACT for _, payload, _ in expected)
    card = probe.score(source(), attempts(), {'name': 'local', 'digest': 'fixed'})
    assert card['decision'] == 'pair_go' and card['model_calls'] == 3
    assert card['unchanged_pitch_shares_one_judgment']
    assert not card['investor_material_accepted']


def test_versioned_pair_contract_changes_only_the_frozen_input_marker():
    older = probe.calls(source(), {'name': 'local', 'digest': 'fixed'})
    fresh = probe.calls(source(), {'name': 'local', 'digest': 'fixed'},
                        contract=probe.CONTRACT_V2)
    for (_, old, _), (_, new, _) in zip(older, fresh):
        assert old['probe_contract'] == probe.CONTRACT
        assert new['probe_contract'] == probe.CONTRACT_V2
        assert {k: v for k, v in old.items() if k != 'probe_contract'} == {
            k: v for k, v in new.items() if k != 'probe_contract'}
    assert probe.score(source(), attempts(), {}, contract=probe.CONTRACT_V2)[
        'probe_contract'] == probe.CONTRACT_V2


def test_fresh_pair_blocks_unbound_defect_and_changed_control():
    rows = attempts()
    rows[2]['answer']['r02']['challenged_clause'] = 'cash arrived'
    assert probe.score(source(), rows, {})['decision'] == 'pair_no_go'
    rows[2]['answer']['r02']['challenged_clause'] = 'received all funds'
    rows[2]['answer']['r01'] = answer('insufficient_evidence')
    card = probe.score(source(), rows, {})
    assert card['decision'] == 'pair_no_go' and not card['unchanged_intro_labels_stable']


def test_strict_aggregate_requires_every_clean_control_supported():
    base = probe.score(source(), attempts(), {})
    assert probe.strict_scorecard(base)['decision'] == 'pair_go'
    changed = attempts()
    changed[1]['answer']['r01'] = answer('insufficient_evidence')
    raw_card = probe.score(source(), changed, {})
    assert raw_card['decision'] == 'pair_go'  # The prior differential card is preserved.
    strict = probe.strict_scorecard(raw_card)
    assert strict['decision'] == 'pair_no_go'
    assert strict['differential_decision'] == 'pair_go'
    assert strict['clean_control_blocked_sentence_ids'] == ['pitch_deck.slide_1.sentence_1']
