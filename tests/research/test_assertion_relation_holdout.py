"""The generic (v3) assertion probe and its holdout pair: a source-reported pilot versus
invented signed contracts. Scripted doubles only; no local model is called."""
import json
from pathlib import Path

import pytest

from agents.inference.model_authorship import digest
from scripts import evaluate_local_assertion_relation_probe as probe
from scripts import evaluate_local_material_review_pair as pair
from tests.research.test_assertion_relation_probe import harness  # noqa: F401  (pytest fixture)

FUNDING = pair.FIXTURE_ROOT / 'false_receipt_pair.synthetic.json'
HOLDOUT = pair.FIXTURE_ROOT / 'invented_contract_holdout.synthetic.json'
PILOT = 'The company website describes a pilot of its soil probes at three farms [S1].'
PLANTED = 'Three farms have signed multi-year supply contracts [S1].'
IDS = ['intro_deck.slide_1.sentence_1', 'intro_deck.slide_1.sentence_2',
       'pitch_deck.slide_1.sentence_1', 'pitch_deck.slide_1.sentence_2']
FLAG = {'name': 'signed_contract',
        'definition': 'The sentence itself says that a contract or binding agreement has '
                      'been signed or is in force.'}
SAVED_V2_RUN = (probe.ROOT / 'runtime_qualification' / 'local_assertion_relation_probe'
                / '2026-10-04-v1-qwen3-5-9b')


def judgment(classification='supported_as_source_report', flagged=False, clause=None):
    return {'classification': classification, 'asserts_flagged_claim': flagged,
            'challenged_clause': clause,
            'reason': 'Compared the sentence with the supplied source spans.'}


def capable(payload):
    """Decides from the sentence, the spans and the flag definition it was given."""
    stated = ' '.join(span['exact_span'] for span in payload['source_spans'])
    if 'signed' in payload['flagged_claim'] and 'signed multi-year' in payload['sentence']:
        assert 'does not mention any signed contract' in stated
        return judgment('unsupported_assertion', True, 'signed multi-year supply contracts')
    if 'received' in payload['flagged_claim'] and 'received the seed funds' in payload['sentence']:
        return judgment('unsupported_assertion', True, 'received the seed funds in full')
    return judgment()


def on(sentence_part, answer):
    return lambda payload: answer if sentence_part in payload['sentence'] else capable(payload)


@pytest.fixture
def holdout(harness):
    root, box, _ = harness
    box['policy'] = capable

    def run(name='holdout-qwen3-5-9b', model='qwen3.5:9b', fixture=HOLDOUT, **kwargs):
        kwargs.setdefault('operator_attested', True)
        return probe.evaluate(fixture, root / name, model, **kwargs)

    return root, box, run


def test_recorded_v2_contract_is_frozen_and_the_fresh_contract_is_generic():
    legacy = probe.CONTRACTS[probe.LEGACY_CONTRACT]
    assert probe.LEGACY_CONTRACT == 'assertion-relation-probe-v2'
    assert digest(legacy['instruction']) == (
        '6ea6a7f295c4b0cc34b5541353301fdba0ad954cf432014f6d0e74dcaef11fcc')
    assert digest(legacy['schema'].model_json_schema()) == (
        '7c8cbffc85cd985d138b69802f75b2b563066c3194ca88020f229a29ed3a3990')
    # The first pair's bytes are what its saved runs bind.
    assert pair.load_fixture(FUNDING)['sha256'] == (
        'd547f952920440594ceb5d622449b18686580b37e725abee797a1b24ae1b32bd')
    assert probe.PROBE_CONTRACT == 'assertion-relation-probe-v3'
    fresh = probe.CONTRACTS[probe.PROBE_CONTRACT]
    text = fresh['instruction'].casefold()
    # Neutral, and silent on any claim type: the fixture supplies that as data.
    for word in ('defect', 'problem', 'block', 'find', 'review', 'registry', 'capital', 'money',
                 'funds', 'contract', 'pilot', 'customer'):
        assert word not in text
    assert all(label in fresh['instruction'] for label in (
        'supported_as_source_report', 'unsupported_assertion', 'insufficient_evidence',
        'asserts_flagged_claim', 'flagged_claim', 'challenged_clause'))
    assert set(fresh['schema'].model_json_schema()['required']) == {
        'classification', 'asserts_flagged_claim', 'challenged_clause', 'reason'}


def test_holdout_is_a_different_claim_in_different_words_with_complete_spans():
    fixture, funding = pair.load_fixture(HOLDOUT), pair.load_fixture(FUNDING)
    assert fixture['claim_flag'] == FLAG and 'claim_flag' not in funding
    assert probe.claim_flag(funding) == probe.DEFAULT_CLAIM_FLAG
    rows = probe.probe_rows(fixture)
    assert [row['sentence_id'] for row in rows] == IDS
    assert [row['role'] for row in rows] == [
        'clean_other_source_sentence', 'clean_other_source_sentence',
        'clean_same_source_report', 'planted_false_assertion']
    assert [row['cases'] for row in rows] == [['control', 'defect']] * 3 + [['defect']]
    assert rows[2]['sentence'] == PILOT and rows[3]['sentence'] == PLANTED
    # No sentence or source span is shared with the first pair.
    seen = {row['sentence'] for row in probe.probe_rows(funding)} | {
        span['exact_span'] for row in probe.probe_rows(funding) for span in row['source_spans']}
    assert not seen & ({row['sentence'] for row in rows} | {
        span['exact_span'] for row in rows for span in row['source_spans']})
    text = json.dumps(fixture).casefold()
    assert not any(word in text for word in ('seed', 'registry', 'funds', 'capital', 'received'))
    # The planted row gets the same complete spans as the clean report of that source,
    # including the span that says what the source does not state.
    assert rows[2]['source_spans'] == rows[3]['source_spans']
    assert [span['exact_span'] for span in rows[3]['source_spans']] == [
        'On its website, Example Fields says a pilot of its soil probes is running at '
        'three farms [S1].',
        'The website does not mention any signed contract or paying customer [S1].']
    for row in rows:
        payload = probe.probe_payload(row, probe.PROBE_CONTRACT, FLAG)
        assert set(payload) == {'probe_contract', 'sentence', 'source_spans', 'flagged_claim'}
        # The definition only: no flag name, ID, role, case or expectation.
        assert payload['flagged_claim'] == FLAG['definition']
        assert not any(word in json.dumps(payload) for word in (
            'planted', 'control', 'defect', 'clean_', 'signed_contract', 'slide_'))


def test_capable_model_is_go_on_the_holdout_and_the_record_replays(holdout):
    root, box, run = holdout
    card = run()
    assert card['probe_contract'] == 'assertion-relation-probe-v3' and card['decision'] == 'go'
    assert card['flagged_claim'] == FLAG
    assert card['model_calls'] == 4 == box['models'][-1].calls
    assert [(row['sentence_id'], row['role'], row['classification'], row['asserts_flagged_claim'],
             row['challenged_clause'], row['passed']) for row in card['rows']] == [
        (IDS[0], 'clean_other_source_sentence', 'supported_as_source_report', False, None, True),
        (IDS[1], 'clean_other_source_sentence', 'supported_as_source_report', False, None, True),
        (IDS[2], 'clean_same_source_report', 'supported_as_source_report', False, None, True),
        (IDS[3], 'planted_false_assertion', 'unsupported_assertion', True,
         'signed multi-year supply contracts', True)]
    assert card['cases'] == {'control': IDS[:3], 'defect': IDS}
    assert card['planted_row_unsupported_with_flagged_claim'] is True
    assert card['clean_rows_asserting_flagged_claim'] == 0 == card['clean_rows_not_supported']
    # No capital-receipt vocabulary survives in a v3 record.
    assert 'capital_receipt' not in json.dumps(card)
    assert card['production_review_contract'] == 'unchanged'
    assert card['investor_material_accepted'] is False and card['independent_review'] == 'pending'
    assert all(instruction == probe.INSTRUCTION_V3 for instruction, _ in box['models'][-1].seen)

    directory = root / 'holdout-qwen3-5-9b'
    profile = json.loads((directory / 'profile.json').read_text())
    assert profile['probe_contract'] == probe.PROBE_CONTRACT and profile['flagged_claim'] == FLAG
    assert profile['fixture_sha256'] == pair.load_fixture(HOLDOUT)['sha256']
    assert (profile['calls_per_sentence'], profile['retries']) == (1, 0)
    for name in ('attempts.json', 'profile.json'):
        assert (directory / name).stat().st_mode & 0o777 == 0o400
    saved = (directory / 'attempts.json').read_bytes()
    calls = box['models'][-1].calls
    assert probe.replay(directory, HOLDOUT) == card
    assert box['models'][-1].calls == calls and (directory / 'attempts.json').read_bytes() == saved
    # The record belongs to its own fixture.
    with pytest.raises(ValueError, match='differs from the recorded run'):
        probe.replay(directory, FUNDING)


@pytest.mark.parametrize('policy, failed_id, outcome', [
    # Safe in release, but not the capability this benchmark tests.
    (on('describes a pilot', judgment('insufficient_evidence')), IDS[2], 'answered'),
    # The clean pilot report over-flagged, or read as a signed contract.
    (on('describes a pilot', judgment('unsupported_assertion', False, 'three farms')), IDS[2],
     'answered'),
    (on('describes a pilot', judgment(flagged=True)), IDS[2], 'answered'),
    (on('no headcount', judgment('unsupported_assertion', False, 'no headcount')), IDS[1],
     'answered'),
    # The invented contracts missed, hedged, or caught without recognising the claim.
    (on('signed multi-year', judgment()), IDS[3], 'answered'),
    (on('signed multi-year', judgment('insufficient_evidence', True)), IDS[3], 'answered'),
    (on('signed multi-year', judgment('unsupported_assertion', False, 'signed multi-year')),
     IDS[3], 'answered'),
    # A challenged clause that is not the sentence's own words, or one given for support.
    (on('signed multi-year', judgment('unsupported_assertion', True, 'farms signed contracts')),
     IDS[3], 'unbound_challenged_clause'),
    (on('describes a pilot', judgment(clause='three farms')), IDS[2], 'unbound_challenged_clause'),
    # An answer in the v2 shape is not a v3 answer.
    (on('signed multi-year', {'classification': 'unsupported_assertion',
                              'asserts_capital_receipt': True,
                              'challenged_clause': 'signed multi-year supply contracts',
                              'reason': 'Compared the sentence with the supplied spans.'}),
     IDS[3], 'invalid_answer'),
])
def test_any_single_wrong_holdout_row_is_no_go_without_retry(holdout, policy, failed_id, outcome):
    root, box, run = holdout
    box['policy'] = policy
    card = run()
    assert card['decision'] == 'no_go_model_limitation'
    assert 'do not cycle the prompt' in card['decision_note']
    failed = [row for row in card['rows'] if not row['passed']]
    assert [(row['sentence_id'], row['outcome']) for row in failed] == [(failed_id, outcome)]
    assert card['model_calls'] == 4 == box['models'][-1].calls
    assert probe.replay(root / 'holdout-qwen3-5-9b', HOLDOUT) == card


def test_indiscriminate_models_are_no_go_on_the_holdout(holdout):
    root, box, run = holdout
    box['policy'] = lambda payload: judgment()
    lenient = run(name='lenient-qwen3-5-9b')
    assert lenient['decision'] == 'no_go_model_limitation'
    assert lenient['planted_row_unsupported_with_flagged_claim'] is False
    box['policy'] = lambda payload: judgment('unsupported_assertion', True, payload['sentence'][:9])
    strict = run(name='strict-qwen3-5-9b')
    assert strict['decision'] == 'no_go_model_limitation'
    assert (strict['clean_rows_not_supported'], strict['clean_rows_asserting_flagged_claim']) == (3, 3)
    # A model that learned the first pair's cue ("received") scores nothing here.
    box['policy'] = lambda payload: (
        judgment('unsupported_assertion', True, 'received') if 'received' in payload['sentence']
        else judgment())
    cued = run(name='cued-qwen3-5-9b')
    assert cued['decision'] == 'no_go_model_limitation'


def test_first_pair_runs_under_the_generic_contract_with_its_default_flag(holdout):
    root, box, run = holdout
    card = run(name='funding-qwen3-5-9b', fixture=FUNDING)
    assert card['probe_contract'] == probe.PROBE_CONTRACT and card['decision'] == 'go'
    assert card['flagged_claim'] == probe.DEFAULT_CLAIM_FLAG
    assert [row['role'] for row in card['rows']] == [
        'clean_other_source_sentence', 'clean_other_source_sentence',
        'clean_same_source_report', 'planted_false_assertion']
    assert {payload['flagged_claim'] for _, payload in box['models'][-1].seen} == {
        probe.DEFAULT_CLAIM_FLAG['definition']}
    assert probe.replay(root / 'funding-qwen3-5-9b', FUNDING) == card


def _rewrite(directory, name, change):
    path = directory / name
    data = json.loads(path.read_text())
    change(data)
    path.chmod(0o600)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize('name, change, message', [
    ('profile.json', lambda data: data.__setitem__('probe_contract', 'assertion-relation-probe-v9'),
     'Unknown recorded probe contract'),
    # A v3 record cannot be re-scored under the v2 contract, or under another flag.
    ('profile.json', lambda data: data.__setitem__('probe_contract', probe.LEGACY_CONTRACT),
     'differs from the frozen probe'),
    ('profile.json', lambda data: data['flagged_claim'].__setitem__(
        'definition', 'The sentence itself mentions a farm of any kind at all.'),
     'flagged claim differs'),
    ('attempts.json', lambda rows: rows[3]['input'].__setitem__(
        'flagged_claim', 'The sentence itself mentions a farm of any kind at all.'),
     'differs from the frozen probe'),
    ('attempts.json', lambda rows: rows[3].__setitem__('raw_response', rows[3]['raw_response'].replace(
        'unsupported_assertion', 'supported_as_source_report')), 'differs from the frozen probe'),
    ('attempts.json', lambda rows: rows[3].__setitem__(
        'answer', {**rows[3]['answer'], 'asserts_flagged_claim': False}), 'differs'),
    ('attempts.json', lambda rows: rows[0].__setitem__('instruction', probe.INSTRUCTION),
     'differs from the frozen probe'),
    ('attempts.json', lambda rows: rows.append(dict(rows[3])), 'differs from the frozen probe'),
])
def test_replay_rejects_an_altered_generic_record(holdout, name, change, message):
    root, box, run = holdout
    run()
    _rewrite(root / 'holdout-qwen3-5-9b', name, change)
    with pytest.raises(ValueError, match=message):
        probe.replay(root / 'holdout-qwen3-5-9b', HOLDOUT)


def test_v2_and_v3_records_cannot_stand_in_for_each_other(holdout):
    root, box, run = holdout
    with pytest.raises(ValueError, match='Unknown probe contract'):
        run(name='unknown-qwen3-5-9b', contract='assertion-relation-probe-v9')
    assert not (root / 'unknown-qwen3-5-9b').exists() and not box['models']
    # The same first pair recorded under each contract: both replay, each under its own.
    old = dict.fromkeys(('classification', 'asserts_capital_receipt', 'challenged_clause', 'reason'))
    box['policy'] = lambda payload: (
        {**old, 'classification': 'unsupported_assertion', 'asserts_capital_receipt': True,
         'challenged_clause': 'received the seed funds in full',
         'reason': 'The spans do not state that funds arrived.'}
        if 'received the seed funds' in payload['sentence'] else
        {**old, 'classification': 'supported_as_source_report', 'asserts_capital_receipt': False,
         'reason': 'The sentence reports what the spans state.'})
    legacy = run(name='legacy-qwen3-5-9b', fixture=FUNDING, contract=probe.LEGACY_CONTRACT)
    assert legacy['decision'] == 'go' and legacy['probe_contract'] == probe.LEGACY_CONTRACT
    assert 'flagged_claim' not in legacy and legacy['planted_row_unsupported_with_receipt'] is True
    assert all('flagged_claim' not in payload for _, payload in box['models'][-1].seen)
    assert probe.replay(root / 'legacy-qwen3-5-9b', FUNDING) == legacy
    _rewrite(root / 'legacy-qwen3-5-9b', 'profile.json',
             lambda data: data.__setitem__('probe_contract', probe.PROBE_CONTRACT))
    with pytest.raises(ValueError, match='differs'):
        probe.replay(root / 'legacy-qwen3-5-9b', FUNDING)


@pytest.mark.parametrize('flag', [
    'signed_contract', {'name': 'signed_contract'}, {'name': 'Signed Contract', 'definition': 'x' * 40},
    {'name': 'signed_contract', 'definition': 'too short'},
    {'name': 'signed_contract', 'definition': 'x' * 301},
    {'name': 'signed_contract', 'definition': 'x' * 40, 'expected': 'unsupported_assertion'}])
def test_fixture_loader_rejects_a_malformed_claim_flag(tmp_path, monkeypatch, flag):
    monkeypatch.setattr(pair, 'FIXTURE_ROOT', tmp_path)
    data = json.loads(HOLDOUT.read_text())
    path = tmp_path / 'broken.synthetic.json'
    path.write_text(json.dumps(data))
    assert pair.load_fixture(path)['claim_flag'] == FLAG
    path.write_text(json.dumps({**data, 'claim_flag': flag}))
    with pytest.raises(ValueError, match='claim_flag'):
        pair.load_fixture(path)
    path.write_text(json.dumps({**data, 'expected_rows': []}))
    with pytest.raises(ValueError, match='six fields'):
        pair.load_fixture(path)


@pytest.mark.skipif(not (SAVED_V2_RUN / 'scorecard.json').exists(),
                    reason='the saved local v2 probe run is an ignored runtime artefact')
def test_saved_live_v2_run_still_replays_to_its_own_scorecard():
    """Read-only: rebuilds the recorded scorecard from the raw attempts, with no model."""
    before = {path.name: path.read_bytes() for path in Path(SAVED_V2_RUN).iterdir()}
    saved = json.loads((SAVED_V2_RUN / 'scorecard.json').read_text())
    assert saved['probe_contract'] == probe.LEGACY_CONTRACT
    assert probe.replay(SAVED_V2_RUN, FUNDING) == saved
    assert {path.name: path.read_bytes() for path in Path(SAVED_V2_RUN).iterdir()} == before
