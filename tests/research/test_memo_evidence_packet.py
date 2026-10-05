"""The memo evidence packet: batches, binding, coverage, replay and section scope.

Public synthetic sources and a scripted double only; no local model is called.
"""
import json
from copy import deepcopy

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import (PreparationBudget, PreparationBudgetExceeded,
                                                   preparation_budget)
from agents.research import memo_evidence_packet as packet_module
from agents.research.investment_memo import Source
from agents.research.memo_evidence_packet import (INSTRUCTION, RETRY_FEEDBACK, TASK,
                                                  build_evidence_packet, packet_batches,
                                                  replay_evidence_packet, section_cards)

PASSAGES = {
    'S1': 'Example Labs describes a scheduling tool for clinics and a pilot with one clinic.',
    'S2': json.dumps({'company': 'Example Labs', 'label': 'Seed', 'date': '2025-06',
                      'amount': 'USD 100000', 'status': 'unknown'}, separators=(',', ':')),
    'S3': 'The company page reports no revenue or customer figures for the scheduling product.',
    'S4': 'A public directory lists Example Labs under clinic software without a headcount.',
    'S5': 'An investor announcement mentions a seed round for Example Labs without an amount.',
}


def source(source_id, passage=None):
    return Source(id=source_id, url=f'https://example.invalid/{source_id.lower()}',
                  title=f'Synthetic title {source_id}', passage=passage or PASSAGES[source_id],
                  version=f'synthetic-{source_id.lower()}-v1',
                  attribution=f'Synthetic publisher {source_id}')


SOURCES = [source(source_id) for source_id in PASSAGES]
DIGEST = digest([item.model_dump() for item in SOURCES])


def finding(text, quotes, status='source_reported'):
    return {'status': status, 'finding': text, 'quotes': quotes}


CARDS = {
    'S1': [finding('The source describes a scheduling tool for clinics and one clinic pilot.',
                   ['a scheduling tool for clinics and a pilot with one clinic'])],
    'S2': [finding('A registry lists a seed entry dated 2025-06 whose status is unknown.',
                   [PASSAGES['S2']])],
    'S3': [finding('The company page reports no revenue or customer figures.',
                   ['reports no revenue or customer figures']),
           finding('Whether the pilot led to any paid use is not stated by the page.',
                   [], 'unknown')],
    'S4': [finding('A directory places the company under clinic software.',
                   ['lists Example Labs under clinic software'])],
    'S5': [finding('An announcement mentions a seed round and gives no amount.',
                   ['mentions a seed round for Example Labs without an amount'])],
}


def capable(payload):
    return {item['id']: {'findings': deepcopy(CARDS[item['id']])} for item in payload['sources']}


class Double:
    name = 'offline-test-model'

    def __init__(self, policy=capable):
        self.policy, self.calls, self.seen = policy, 0, []
        self.last_response_text, self.last_call = '', {'host': 'test-double'}

    def generate(self, instruction, evidence, schema):
        self.calls += 1
        payload = json.loads(evidence)
        self.seen.append((instruction, payload, schema))
        answer = self.policy(payload)
        if isinstance(answer, Exception):
            raise answer
        self.last_response_text = answer if isinstance(answer, str) else json.dumps(answer)
        return schema.model_validate_json(self.last_response_text)


def build(model, attempts, *, calls=6, sources=SOURCES, source_set_digest=DIGEST, saves=None,
          contract='memo-evidence-packet-v1'):
    """These tests cover the recorded v1 contract; v2 is in test_memo_evidence_spans.py."""
    budget = PreparationBudget(105, max_calls=calls)
    with preparation_budget(budget):
        return build_evidence_packet(
            model, sources, attempts, (lambda: saves.append(len(attempts))) if saves is not None
            else (lambda: None), budget, source_set_digest=source_set_digest,
            contract=contract), budget


def once(batch_index, answer, otherwise=capable):
    """Answer one batch's FIRST attempt with `answer`; everything else capably."""
    def policy(payload):
        if payload['batch_index'] == batch_index and 'retry_index' not in payload:
            return answer(payload) if callable(answer) else answer
        return otherwise(payload)
    return policy


def test_batches_hold_two_or_three_complete_passages_and_cover_every_source_in_order():
    for count in range(1, 12):
        sources = [source(f'S{index}', PASSAGES['S1']) for index in range(1, count + 1)]
        batches = packet_batches(sources)
        assert [item.id for batch in batches for item in batch] == [item.id for item in sources]
        assert all(1 <= len(batch) <= 3 for batch in batches)
        if count >= 2:
            assert all(len(batch) >= 2 for batch in batches)        # 4 -> 2+2, 7 -> 3+2+2
    assert [len(batch) for batch in packet_batches(SOURCES)] == [3, 2]
    # Long passages share a call only while the bound holds; none is ever cut.
    long = [source(f'S{index}', 'Example Labs synthetic passage. ' * 120) for index in range(1, 6)]
    batches = packet_batches(long)
    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert all(sum(len(item.passage) for item in batch) <= 9000 for batch in batches)
    payload = packet_module.batch_payload(batches[0], 0, 3, 'digest')
    assert [item['passage'] for item in payload['sources']] == [long[0].passage, long[1].passage]


def test_packet_has_one_model_authored_card_per_source_bound_to_exact_quotes():
    attempts, saves, model = [], [], Double()
    packet, budget = build(model, attempts, saves=saves)
    assert packet['packet_contract'] == 'memo-evidence-packet-v1'
    assert packet['source_set_digest'] == DIGEST
    assert [card['source_id'] for card in packet['cards']] == ['S1', 'S2', 'S3', 'S4', 'S5']
    assert packet['coverage'] == {'complete': True, 'source_count': 5, 'card_count': 5,
                                  'source_ids': ['S1', 'S2', 'S3', 'S4', 'S5'],
                                  'unknown_only_source_ids': []}
    for card, item in zip(packet['cards'], SOURCES):
        # Source identity is bound by code; findings and quotes are the model's, unchanged.
        assert (card['title'], card['attribution'], card['version'], card['url']) == (
            item.title, item.attribution, item.version, item.url)
        assert card['findings'] == CARDS[item.id]
        assert all(quote in item.passage for row in card['findings'] for quote in row['quotes'])
    assert packet['cards'][2]['findings'][1]['status'] == 'unknown'
    # Two bounded calls, each saved as it was recorded, with complete passages.
    assert model.calls == budget.calls == 2 == len(attempts) and saves == [1, 2]
    assert [row['task'] for row in attempts] == [TASK, TASK]
    assert [[item['id'] for item in row['input']['sources']] for row in attempts] == [
        ['S1', 'S2', 'S3'], ['S4', 'S5']]
    assert attempts[0]['input']['sources'][1] == SOURCES[1].model_dump()
    assert all(row['raw_response'] and row['response_hash'] == digest(row['raw_response'])
               and row['instruction'] == INSTRUCTION for row in attempts)
    assert packet['response_ids'] == ['response_1', 'response_2']
    assert packet['batches'][1] == {'batch_index': 1, 'source_ids': ['S4', 'S5'],
                                    'response_id': 'response_2'}
    assert packet['independent_review'] == 'pending'
    # The schema requires exactly the batch's source IDs.
    schema = model.seen[0][2].model_json_schema()
    assert schema['required'] == ['S1', 'S2', 'S3'] and schema['additionalProperties'] is False


def test_replay_and_rebuild_return_the_same_packet_without_inference():
    attempts = []
    packet, _ = build(Double(), attempts)
    saved = json.dumps(attempts)
    assert replay_evidence_packet(SOURCES, attempts, source_set_digest=DIGEST) == packet
    idle = Double()
    again, budget = build(idle, attempts)
    assert again == packet and idle.calls == 0 == budget.calls and json.dumps(attempts) == saved
    # Dumped source dicts, as the stage payload carries them, bind identically.
    dumped = [item.model_dump() for item in SOURCES]
    assert replay_evidence_packet(dumped, attempts, source_set_digest=digest(dumped)) == packet
    assert packet['packet_digest'] == digest({key: value for key, value in packet.items()
                                              if key != 'packet_digest'})
    # A build from dicts alone records the same requests and yields the same packet.
    from_dicts, model = [], Double()
    built, _ = build(model, from_dicts, sources=dumped, source_set_digest=digest(dumped))
    assert built == packet and model.calls == 2
    assert [row['input'] for row in from_dicts] == [row['input'] for row in attempts]
    assert dumped == [item.model_dump() for item in SOURCES]            # caller input untouched
    with pytest.raises(ValueError):
        build(Double(), [], sources=[{**dumped[0], 'extra': 'x'}],
              source_set_digest=digest([{**dumped[0], 'extra': 'x'}]))


def test_a_pass_without_enough_calls_yields_and_a_later_pass_continues():
    attempts, model = [], Double()
    first, budget = build(model, attempts, calls=1)
    assert first is None and model.calls == 1 == len(attempts)
    assert replay_evidence_packet(SOURCES, attempts, source_set_digest=DIGEST) is None
    second, _ = build(model, attempts, calls=1)
    assert second['coverage']['complete'] and model.calls == 2
    assert [row['input']['batch_index'] for row in attempts] == [0, 1]
    # A pass that reaches its time limit before the call also yields, with no retry spent.
    late = Double(lambda payload: PreparationBudgetExceeded('This preparation pass reached its '
                                                           'time limit. Saved work is retained.'))
    fresh = []
    result, _ = build(late, fresh)
    assert result is None and len(fresh) == 1 and not fresh[0]['raw_response']


def drop(source_id):
    return lambda payload: {key: value for key, value in capable(payload).items()
                            if key != source_id}


def with_card(source_id, findings):
    """A capable answer, except that one source's card is replaced where it is asked for."""
    return lambda payload: {key: {'findings': findings} if key == source_id else value
                            for key, value in capable(payload).items()}


@pytest.mark.parametrize('bad, issue', [
    # A missing source, an unknown source ID, or an empty card: the schema refuses it.
    (drop('S2'), 'S2'),
    (lambda payload: {**capable(payload), 'S9': {'findings': deepcopy(CARDS['S1'])}}, 'S9'),
    (with_card('S1', []), 'S1'),
    # A quote that is paraphrased, taken from another source, or too short.
    (with_card('S1', [finding('The source describes a scheduling tool for clinics.',
                              ['a scheduling product for clinics and one pilot'])]),
     'S1 quote is not an exact excerpt'),
    (with_card('S1', [finding('The source reports no revenue or customer figures.',
                              ['reports no revenue or customer figures'])]),
     'S1 quote is not an exact excerpt'),
    (with_card('S3', [finding('The company page reports no revenue figures at all.',
                              ['no revenue'])]), 'String should have at least|S3 quote'),
    # A reported finding with no quote, a finding carrying a citation marker, and a
    # numeric finding on a structured record that quotes only a fragment of it.
    (with_card('S1', [finding('The source describes a scheduling tool for clinics.', [])]),
     'S1 reports a finding without an exact quote'),
    (with_card('S1', [finding('The source describes a scheduling tool for clinics [S1].',
                              ['a scheduling tool for clinics'])]), 'citation marker'),
    (with_card('S2', [finding('A registry lists a seed entry dated 2025-06 for USD 100000.',
                              ['"amount":"USD 100000"'])]), 'complete record'),
    # A number or date that the finding's own quote does not contain, in a reported
    # finding, in an unknown one, or pooled from the source's other finding.
    (with_card('S1', [finding('The source describes a pilot with 12 clinics using the tool.',
                              ['a scheduling tool for clinics and a pilot with one clinic'])]),
     'S1 finding states a number or date absent from its exact quote: 12'),
    (with_card('S3', [finding('Whether revenue passed USD 50000 in 2025 is not stated.', [],
                              'unknown')]), 'absent from its exact quote: 2025, 50000'),
    (with_card('S3', [finding('The company page reports no revenue or customer figures.',
                              ['reports no revenue or customer figures']),
                      finding('The page was published in March 2024 with no figures.',
                              ['for the scheduling product'])]), 'absent from its exact quote'),
    ('The sources look fine and need no cards.', 'JSON|json|valid'),
])
def test_an_answer_that_does_not_bind_gets_one_corrected_attempt_on_a_new_pass(bad, issue):
    import re
    attempts, model = [], Double(once(0, bad))
    first, _ = build(model, attempts)
    # The pass yields after the rejected answer; its raw text is kept.
    assert first is None and model.calls == 1 and attempts[0]['raw_response']
    second, _ = build(model, attempts)
    assert second['coverage']['complete'] and model.calls == 3
    retry = attempts[1]
    assert retry['instruction'] == INSTRUCTION + '\n' + RETRY_FEEDBACK
    assert retry['input']['retry_base_digest'] == digest(attempts[0]['input'])
    assert retry['input']['previous_response_id'] == attempts[0]['id']
    assert re.search(issue, retry['input']['validation_issue'])
    # The same complete passages again, and the rejected answer when there was one.
    assert retry['input']['sources'] == attempts[0]['input']['sources']
    assert retry['input'].get('previous_answer') == attempts[0].get('answer')
    assert second['batches'][0]['response_id'] == retry['id']
    assert second['cards'][0]['findings'] == CARDS['S1']
    assert replay_evidence_packet(SOURCES, attempts, source_set_digest=DIGEST) == second


def test_two_rejected_answers_fail_closed_and_are_never_tried_a_third_time():
    always_bad = lambda payload: (drop('S2')(payload) if payload['batch_index'] == 0
                                  else capable(payload))
    attempts, model = [], Double(always_bad)
    assert build(model, attempts)[0] is None
    # The corrected attempt also fails: the packet fails closed at once.
    with pytest.raises(ValueError, match='retry exhausted; raw responses are retained'):
        build(model, attempts)
    assert model.calls == 2 == len(attempts)
    for _ in range(2):
        with pytest.raises(ValueError, match='retry exhausted; raw responses are retained'):
            build(Double(), attempts)
        with pytest.raises(ValueError, match='retry exhausted'):
            replay_evidence_packet(SOURCES, attempts, source_set_digest=DIGEST)
    assert len(attempts) == 2 and all(row['raw_response'] for row in attempts)
    # No partial packet: the second batch was never reached, and nothing was dropped.
    assert not any(row['input']['batch_index'] == 1 for row in attempts)


def test_numbers_and_dates_bound_to_the_exact_quote_are_accepted():
    cards = [finding('A registry lists a seed entry dated 2025-06 for USD 100000, status unknown.',
                     [PASSAGES['S2']]),
             finding('Whether the listed seed financing closed is not stated by the registry.',
                     [PASSAGES['S2']], 'unknown')]
    packet, _ = build(Double(with_card('S2', cards)), [])
    assert packet['cards'][1]['findings'] == cards
    # A spelled quantity counts when the quote spells it too.
    assert packet['cards'][0]['findings'][0]['finding'].count('one clinic') == 1


def test_an_explicit_unknown_card_covers_a_source_with_nothing_usable():
    unknown = [finding('The directory entry gives no product, customer or revenue detail.',
                       [], 'unknown')]
    attempts = []
    packet, _ = build(Double(with_card('S4', unknown)), attempts)
    assert packet['coverage']['unknown_only_source_ids'] == ['S4']
    assert packet['cards'][3]['findings'] == unknown and packet['coverage']['card_count'] == 5


def rewrite(attempts, change):
    rows = json.loads(json.dumps(attempts))
    change(rows)
    return rows


@pytest.mark.parametrize('change, message', [
    (lambda rows: rows[0].__setitem__('raw_response', rows[0]['raw_response'].replace(
        'one clinic pilot', 'ten clinic pilots')), 'response was modified'),
    (lambda rows: rows[0]['answer']['S1']['findings'][0].__setitem__(
        'finding', 'The source reports strong repeat demand from many clinics.'), 'differs'),
    (lambda rows: rows[0]['input']['sources'][0].__setitem__('passage', 'Another passage ' * 4),
     'differs from its frozen batch'),
    (lambda rows: rows[0]['input']['sources'].pop(), 'differs from its frozen batch'),
    (lambda rows: rows[0].__setitem__('instruction', 'Write favourable cards.'),
     'differs from its frozen batch'),
    (lambda rows: rows[0]['schema']['required'].pop(), 'differs from its frozen batch'),
    (lambda rows: rows[1]['input'].__setitem__('batch_index', 7), 'does not belong'),
    (lambda rows: rows[1]['input'].__setitem__('packet_contract', 'memo-evidence-packet-v9'),
     'Unknown recorded evidence packet contract'),
    (lambda rows: rows.append(dict(rows[1], id='response_3')), 'continues after a valid answer'),
])
def test_replay_rejects_an_altered_record(change, message):
    attempts = []
    build(Double(), attempts)
    altered = rewrite(attempts, change)
    with pytest.raises(ValueError, match=message):
        replay_evidence_packet(SOURCES, altered, source_set_digest=DIGEST)
    idle = Double()
    with pytest.raises(ValueError, match=message):
        build(idle, altered)
    assert idle.calls == 0


def test_packet_is_bound_to_its_exact_source_set():
    attempts = []
    packet, _ = build(Double(), attempts)
    with pytest.raises(ValueError, match='digest does not match'):
        replay_evidence_packet(SOURCES[:4], attempts, source_set_digest=DIGEST)
    with pytest.raises(ValueError, match='digest does not match'):
        build(Double(), attempts, source_set_digest='0' * 64)
    # A changed source set has no saved cards: its own packet starts from nothing.
    changed = SOURCES[:4] + [source('S5', PASSAGES['S5'] + ' It names no lead investor.')]
    changed_digest = digest([item.model_dump() for item in changed])
    assert replay_evidence_packet(changed, attempts, source_set_digest=changed_digest) is None
    model = Double()
    rebuilt, _ = build(model, attempts, sources=changed, source_set_digest=changed_digest)
    assert model.calls == 2 and rebuilt['source_set_digest'] == changed_digest
    assert rebuilt['packet_digest'] != packet['packet_digest']
    # The first set's packet is still exactly replayable from the same attempts.
    assert replay_evidence_packet(SOURCES, attempts, source_set_digest=DIGEST) == packet


def test_section_cards_scope_is_explicit_and_never_changes_the_packet():
    attempts = []
    packet, _ = build(Double(), attempts)
    before = deepcopy(packet)
    everything = section_cards(packet, operating=False)
    assert everything == packet['cards'] and everything is not packet['cards']
    operating = section_cards(packet, operating=True)
    # The two financing-only cards are left out; the adverse and unknown operating
    # card (no revenue; paid use not stated) is kept.
    assert [card['source_id'] for card in operating] == ['S1', 'S3', 'S4']
    manifest = {'scope': 'operating_evidence',
                'complete_source_ids': ['S1', 'S2', 'S3', 'S4', 'S5'],
                'selected_source_ids': ['S1', 'S3', 'S4'],
                'omitted_financing_only_source_ids': ['S2', 'S5']}
    assert all(card['section_scope'] == manifest for card in operating)
    assert operating[1]['findings'] == CARDS['S3']
    # Copies: editing what a section was given cannot reach the packet.
    operating[0]['findings'][0]['finding'] = 'changed'
    everything[0]['title'] = 'changed'
    operating[0]['section_scope']['selected_source_ids'].clear()
    assert packet == before and 'section_scope' not in packet['cards'][0]
    assert section_cards(packet, operating=True)[1]['section_scope'] == manifest


def test_section_cards_fall_back_to_all_and_keep_uncertain_cards():
    financing = [source('S1', PASSAGES['S5']), source('S2', PASSAGES['S2'])]
    cards = {'S1': CARDS['S5'], 'S2': CARDS['S2']}
    model = Double(lambda payload: {item['id']: {'findings': deepcopy(cards[item['id']])}
                                    for item in payload['sources']})
    packet, _ = build(model, [], sources=financing,
                      source_set_digest=digest([item.model_dump() for item in financing]))
    fallback = section_cards(packet, operating=True)
    assert [card['source_id'] for card in fallback] == ['S1', 'S2']
    assert fallback[0]['section_scope'] == {
        'scope': 'complete_evidence_fallback', 'complete_source_ids': ['S1', 'S2'],
        'selected_source_ids': ['S1', 'S2'], 'omitted_financing_only_source_ids': []}
    # An unquoted unknown, or a card that mixes financing with operating evidence, stays.
    attempts = []
    mixed = with_card('S5', [finding('The announcement mentions a seed round and names no customer.',
                                     ['mentions a seed round for Example Labs'])])
    unquoted = lambda payload: {**mixed(payload), **({'S2': {'findings': [finding(
        'Whether the listed seed financing closed is not stated by the registry.', [],
        'unknown')]}} if any(item['id'] == 'S2' for item in payload['sources']) else {})}
    packet, _ = build(Double(unquoted), attempts)
    assert [card['source_id'] for card in section_cards(packet, operating=True)] == [
        'S1', 'S2', 'S3', 'S4', 'S5']
    # A packet whose cards and coverage disagree is refused, not scoped.
    broken = {**packet, 'cards': packet['cards'][:-1]}
    with pytest.raises(ValueError, match='do not match its coverage'):
        section_cards(broken, operating=True)


def test_a_call_is_not_started_when_the_pass_has_too_little_time_left():
    from agents.research.memo_evidence_packet import extraction_call_has_time

    def run(elapsed, attempts, model):
        budget = PreparationBudget(105, max_calls=6)
        budget.started -= elapsed                       # this much of the pass is already used
        with preparation_budget(budget):
            return build_evidence_packet(model, SOURCES, attempts, lambda: None, budget,
                                         source_set_digest=DIGEST,
                                         contract='memo-evidence-packet-v1'), budget

    # A few seconds left and no measurement: below the 30s default, so no call, no row.
    attempts, model = [], Double()
    result, budget = run(98, attempts, model)
    assert result is None and model.calls == 0 == budget.calls and attempts == []
    # Enough time by default: the first batch runs.
    result, _ = run(60, attempts, Double(lambda payload: capable(payload)))
    assert len(attempts) == 2 and result['coverage']['complete']

    # Measured: an earlier call of this task by this model took 60s, so 50s is not enough
    # for the next batch, while 70s is. Another model's timing is not used.
    measured, model = [], Double()
    run(0, measured, Double(once(1, PreparationBudgetExceeded('time limit'))))
    measured[:] = measured[:1]
    measured[0]['elapsed_seconds'] = 60
    result, budget = run(55, measured, model)
    assert result is None and model.calls == 0 and len(measured) == 1
    result, _ = run(35, measured, model)
    assert result['coverage']['complete'] and model.calls == 1
    slow = [{'task': TASK, 'model': 'another-model', 'elapsed_seconds': 100}]
    budget = PreparationBudget(105, max_calls=2)
    budget.started -= 60
    assert extraction_call_has_time(slow, budget, model) is True
    assert extraction_call_has_time([{**slow[0], 'model': model.name}], budget, model) is False
    # An exhausted call count or an expired pass never starts a call.
    budget.calls = 2
    assert extraction_call_has_time([], budget, model) is False
    expired = PreparationBudget(105, max_calls=2)
    expired.started -= 200
    assert extraction_call_has_time([], expired, model) is False
    # Small synthetic budgets are not gated by time.
    assert extraction_call_has_time(slow, PreparationBudget(5, max_calls=1), model) is True
