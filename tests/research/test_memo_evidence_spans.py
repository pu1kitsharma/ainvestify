"""Evidence packet v2: the model selects exact candidate spans instead of transcribing quotes.

Public synthetic sources and a scripted double only; no local model is called.
"""
import hashlib
import json
import re
from copy import deepcopy

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget, preparation_budget
from agents.research import memo_evidence_packet as packet_module
from agents.research.investment_memo import Source
from agents.research.memo_evidence_packet import (INSTRUCTION_V2, RETRY_FEEDBACK, TASK,
                                                  build_evidence_packet, candidate_spans,
                                                  compact_section_cards,
                                                  replay_evidence_packet, section_cards)
from tests.research.test_memo_evidence_packet import (CARDS, DIGEST, SOURCES, Double, capable,
                                                      once, source)

V1, V2, V3 = ('memo-evidence-packet-v1', 'memo-evidence-packet-v2',
              'memo-evidence-packet-v3')
# Text as a PDF extractor leaves it: wrapped lines, runs of spaces, a tab, a
# non-breaking space, a soft-hyphenated word and a blank line between paragraphs.
PDF = ('Example Labs  describes a scheduling\ntool for clinics and a pilot\twith one clinic.  '
       'The pilot began in March 2025 and covers 3 sites.\n\n'
       'The company page reports no rev-\nenue or customer figures.   '
       'It does not state whether the pilot was paid.')
RECORD = json.dumps({'company': 'Example Labs', 'label': 'Seed', 'date': '2025-06',
                     'amount': 'USD 100000', 'status': 'unknown'}, separators=(',', ':'))
PDF_SOURCES = [source('S1', PDF), source('S2', RECORD),
               source('S3', 'A public directory lists Example Labs under clinic software '
                            'without a headcount. The entry was retrieved in 2026.')]
PDF_DIGEST = digest([item.model_dump() for item in PDF_SOURCES])


def chosen(text, ids, status='source_reported'):
    return {'status': status, 'finding': text, 'candidate_ids': ids}


SELECTED = {
    'S1': [chosen('The source describes a scheduling tool for clinics and one clinic pilot.',
                  ['S1.c01']),
           chosen('The company page does not state whether the pilot was paid.', ['S1.c04'],
                  'unknown')],
    'S2': [chosen('A registry lists a seed entry dated 2025-06 for USD 100000, status unknown.',
                  ['S2.c01'])],
    'S3': [chosen('A directory places the company under clinic software.', ['S3.c01'])],
}


def selecting(payload):
    return {item['id']: {'findings': deepcopy(SELECTED[item['id']])} for item in payload['sources']}


def build(model, attempts, *, sources=PDF_SOURCES, source_set_digest=PDF_DIGEST, calls=6,
          contract=None):
    budget = PreparationBudget(105, max_calls=calls)
    selected_contract = contract if contract is not None else (None if attempts else V2)
    with preparation_budget(budget):
        return build_evidence_packet(model, sources, attempts, lambda: None, budget,
                                     source_set_digest=source_set_digest,
                                     contract=selected_contract)


def with_card(source_id, findings):
    return lambda payload: {key: {'findings': findings} if key == source_id else value
                            for key, value in selecting(payload).items()}


def test_candidate_spans_are_exact_complete_and_keep_irregular_pdf_whitespace():
    spans = candidate_spans(PDF_SOURCES[0])
    assert [span['id'] for span in spans] == ['S1.c01', 'S1.c02', 'S1.c03', 'S1.c04']
    assert [span['text'] for span in spans] == [
        'Example Labs  describes a scheduling\ntool for clinics and a pilot\twith one clinic.',
        'The pilot began in March 2025 and covers 3 sites.',
        'The company page reports no rev-\nenue or customer figures.',
        'It does not state whether the pilot was paid.']
    # Byte for byte in the passage, in order, and together the whole passage.
    position = 0
    for span in spans:
        position = PDF.index(span['text'], position) + len(span['text'])
    squeeze = lambda value: re.sub(r'\s+', '', value)
    assert squeeze(''.join(span['text'] for span in spans)) == squeeze(PDF)
    # A short structured record is one span: the complete record.
    assert candidate_spans(PDF_SOURCES[1]) == [{'id': 'S2.c01', 'text': RECORD}]


@pytest.mark.parametrize('passage', [
    # No sentence end at all, and one sentence far longer than a quote can hold.
    'Example Labs synthetic words without any full stop ' * 30,
    'The synthetic source lists ' + 'many, ' * 300 + 'items.',
    # More sentences than can be listed: repacked into longer spans, nothing dropped.
    ' '.join(f'Synthetic sentence number {index} of the page.' for index in range(1, 90)),
    # Fragments too short to quote join a neighbour.
    'Yes. No. Example Labs describes a scheduling tool for clinics. Ok. It has one pilot. End.',
    # A JSON record too long for one span is still listed whole, in pieces.
    json.dumps({f'field_{index}': 'synthetic value ' * 6 for index in range(12)}),
    'A line.\n\n\n   Another paragraph of the synthetic page follows here.\r\n\r\nThird part ends',
])
def test_any_passage_is_listed_completely_within_the_bounds(passage):
    item = source('S7', passage[:4000])
    spans = candidate_spans(item)
    squeeze = lambda value: re.sub(r'\s+', '', value)
    assert squeeze(''.join(span['text'] for span in spans)) == squeeze(item.passage)
    assert 1 <= len(spans) <= 40 and len({span['id'] for span in spans}) == len(spans)
    assert all(span['text'] in item.passage and len(span['text']) <= 700 for span in spans)
    assert sum(len(span['text']) < 15 for span in spans) <= 1
    assert candidate_spans(item) == spans                       # deterministic


def test_v2_packet_inserts_the_exact_selected_spans_under_the_models_findings():
    attempts, model = [], Double(selecting)
    packet = build(model, attempts)
    assert packet['packet_contract'] == V2 and packet['source_set_digest'] == PDF_DIGEST
    assert packet['coverage'] == {'complete': True, 'source_count': 3, 'card_count': 3,
                                  'source_ids': ['S1', 'S2', 'S3'], 'unknown_only_source_ids': []}
    first = packet['cards'][0]
    # The finding and status are the model's; the quote is the passage's own bytes.
    assert first['findings'] == [
        {'status': 'source_reported', 'candidate_ids': ['S1.c01'],
         'finding': 'The source describes a scheduling tool for clinics and one clinic pilot.',
         'quotes': ['Example Labs  describes a scheduling\ntool for clinics and a pilot\twith '
                    'one clinic.']},
        {'status': 'unknown', 'candidate_ids': ['S1.c04'],
         'finding': 'The company page does not state whether the pilot was paid.',
         'quotes': ['It does not state whether the pilot was paid.']}]
    for card, item in zip(packet['cards'], PDF_SOURCES):
        assert all(quote in item.passage for row in card['findings'] for quote in row['quotes'])
        assert card['passage_sha256'] == hashlib.sha256(item.passage.encode()).hexdigest()
        assert (card['title'], card['attribution'], card['version']) == (
            item.title, item.attribution, item.version)
    assert packet['cards'][1]['findings'][0]['quotes'] == [RECORD]
    # What the model was sent: every span of every source, and no place to type a quote.
    instruction, payload, schema = model.seen[0]
    assert instruction == INSTRUCTION_V2 and 'do not transcribe quotes' in instruction
    assert [item['id'] for item in payload['sources']] == ['S1', 'S2', 'S3']
    assert payload['sources'][0] == {
        'id': 'S1', 'title': 'Synthetic title S1', 'attribution': 'Synthetic publisher S1',
        'passage_sha256': hashlib.sha256(PDF.encode()).hexdigest(),
        'candidates': candidate_spans(PDF_SOURCES[0])}
    text = json.dumps(schema.model_json_schema())
    assert '"quotes"' not in text and '"quote"' not in text
    definitions = schema.model_json_schema()['$defs']
    assert definitions['SelectedFinding_S1']['properties']['candidate_ids']['items']['enum'] == [
        'S1.c01', 'S1.c02', 'S1.c03', 'S1.c04']
    assert definitions['SelectedFinding_S2']['properties']['candidate_ids']['items'][
        'const'] == 'S2.c01'
    assert set(definitions['SelectedFinding_S1']['required']) == {
        'status', 'finding', 'candidate_ids'}
    assert schema.model_json_schema()['required'] == ['S1', 'S2', 'S3']
    assert model.calls == 1 == len(attempts) and attempts[0]['task'] == TASK
    # Exact replay with no inference; section cards work on a v2 packet unchanged.
    saved = json.dumps(attempts)
    assert replay_evidence_packet(PDF_SOURCES, attempts, source_set_digest=PDF_DIGEST) == packet
    idle = Double(selecting)
    assert build(idle, attempts) == packet and idle.calls == 0 and json.dumps(attempts) == saved
    assert [card['source_id'] for card in section_cards(packet, operating=True)] == ['S1', 'S3']


def test_a_quote_the_model_could_not_transcribe_exactly_binds_under_v2_and_fails_under_v1():
    """The live failure category: a quote typed with ordinary spaces is not in the PDF text."""
    typed = 'a scheduling tool for clinics and a pilot with one clinic'
    assert typed not in PDF
    transcribing = lambda payload: {item['id']: {'findings': [{
        'status': 'source_reported', 'quotes': [typed if item['id'] == 'S1' else
                                                item['passage'][:60]],
        'finding': 'The source describes the listed synthetic company in its own words.'}]}
        for item in payload['sources']}
    attempts = []
    assert build(Double(transcribing), attempts, contract=V1) is None
    again = Double(transcribing)
    with pytest.raises(ValueError, match='retry exhausted; raw responses are retained'):
        build(again, attempts)                      # continues under the recorded v1 contract
    assert 'S1 quote is not an exact excerpt' in again.seen[0][1]['validation_issue']
    # The same source under v2: the model points at the span and the bytes are the passage's.
    packet = build(Double(selecting), [])
    assert typed not in packet['cards'][0]['findings'][0]['quotes'][0]
    assert re.sub(r'\s+', ' ', packet['cards'][0]['findings'][0]['quotes'][0]).endswith(
        'a scheduling tool for clinics and a pilot with one clinic.')


@pytest.mark.parametrize('bad, issue, kind', [
    # Another source's candidate, an ID that does not exist, or a bare number.
    (with_card('S1', [chosen('The source describes a scheduling tool for clinics.', ['S2.c01'])]),
     "S1.*candidate_ids.*Input should be 'S1.c01'", 'schema_validation'),
    (with_card('S3', [chosen('A directory places the company under clinic software.',
                             ['S3.c09'])]), "S3.*candidate_ids", 'schema_validation'),
    (with_card('S1', [chosen('The source describes a scheduling tool for clinics.', [1])]),
     'S1.*candidate_ids', 'schema_validation'),
    # A whole source left out, or a card filed under a source that was not supplied.
    (lambda payload: {key: value for key, value in selecting(payload).items() if key != 'S2'},
     'S2', 'schema_validation'),
    (lambda payload: {**selecting(payload), 'S9': {'findings': SELECTED['S3']}}, 'S9',
     'schema_validation'),
    # A transcribed quote is not accepted in any form.
    (with_card('S1', [{**chosen('The source describes a scheduling tool for clinics.',
                                ['S1.c01']), 'quotes': ['a scheduling tool for clinics']}]),
     'quotes', 'schema_validation'),
    # Valid shape, rejected by binding: a reported finding with no span, the same span
    # twice, and a number or date that the selected span does not contain.
    (with_card('S1', [chosen('The source describes a scheduling tool for clinics.', [])]),
     'S1 reports a finding without an exact quote', None),
    (with_card('S1', [chosen('The source describes a scheduling tool for clinics.',
                             ['S1.c01', 'S1.c01'])]), 'selects one twice', None),
    (with_card('S1', [chosen('The source says the pilot began in March 2025 at 3 sites.',
                             ['S1.c01'])]), 'absent from its exact quote: 03, 2025, 3', None),
    (with_card('S2', [chosen('Whether the USD 250000 round closed is not stated.', [],
                             'unknown')]), 'absent from its exact quote: 250000', None),
    (with_card('S1', [chosen('The source describes a scheduling tool for clinics [S1].',
                             ['S1.c01'])]), 'citation marker', None),
])
def test_a_wrong_candidate_or_source_id_is_rejected_then_corrected_once(bad, issue, kind):
    attempts, model = [], Double(once(0, bad, selecting))
    assert build(model, attempts) is None and model.calls == 1
    assert attempts[0]['raw_response'] and attempts[0].get('failure_kind') == kind
    packet = build(model, attempts)
    assert packet['coverage']['complete'] and model.calls == 2
    retry = attempts[1]
    assert retry['instruction'] == INSTRUCTION_V2 + '\n' + RETRY_FEEDBACK
    assert re.search(issue, retry['input']['validation_issue'], re.S)
    assert retry['input']['retry_base_digest'] == digest(attempts[0]['input'])
    assert retry['input']['sources'] == attempts[0]['input']['sources']
    assert packet['cards'][0]['findings'][0]['quotes'][0] in PDF
    assert replay_evidence_packet(PDF_SOURCES, attempts, source_set_digest=PDF_DIGEST) == packet
    # A second rejection fails closed; nothing is selected on the model's behalf.
    stuck = []
    assert build(Double(lambda payload: bad(payload)), stuck) is None
    with pytest.raises(ValueError, match='retry exhausted; raw responses are retained'):
        build(Double(lambda payload: bad(payload)), stuck)
    assert len(stuck) == 2


def test_numbers_and_dates_are_bound_to_the_selected_spans():
    dated = [chosen('The source says the pilot began in March 2025 and covers 3 sites.',
                    ['S1.c02']),
             chosen('The source describes one clinic pilot that began in March 2025.',
                    ['S1.c01', 'S1.c02'])]
    packet = build(Double(with_card('S1', dated)), [])
    assert packet['cards'][0]['findings'][1]['quotes'] == [
        candidate_spans(PDF_SOURCES[0])[0]['text'], candidate_spans(PDF_SOURCES[0])[1]['text']]


def test_fresh_contract_selector_and_replay_from_the_recorded_contract():
    assert packet_module.FRESH_PACKET_CONTRACT == V3
    assert packet_module.PACKET_CONTRACTS == (V1, V2, V3)
    # The v2 helper pins its historical contract; the production fresh default is v3.
    default, named, old = [], [], []
    assert build(Double(selecting), default)['packet_contract'] == V2
    assert build(Double(selecting), named, contract=V2) == build(Double(selecting), default)
    assert default[0]['input'] == named[0]['input']
    v1_packet = build(Double(capable), old, sources=SOURCES, source_set_digest=DIGEST, contract=V1)
    assert v1_packet['packet_contract'] == V1 and v1_packet['cards'][0]['findings'] == CARDS['S1']
    # Replay takes the contract from the saved rows, whatever the fresh default is.
    assert replay_evidence_packet(SOURCES, old, source_set_digest=DIGEST) == v1_packet
    idle = Double(selecting)
    assert build(idle, old, sources=SOURCES, source_set_digest=DIGEST) == v1_packet
    assert idle.calls == 0
    # A saved extraction cannot be continued or re-read under the other contract.
    with pytest.raises(ValueError, match='recorded under another contract'):
        build(Double(selecting), old, sources=SOURCES, source_set_digest=DIGEST, contract=V2)
    with pytest.raises(ValueError, match='recorded under another contract'):
        build(Double(capable), default, contract=V1)
    with pytest.raises(ValueError, match='Unknown recorded evidence packet contract'):
        build(Double(selecting), [], contract='memo-evidence-packet-v9')
    relabelled = json.loads(json.dumps(default))
    relabelled[0]['input']['packet_contract'] = V1
    with pytest.raises(ValueError, match='differs from its frozen batch'):
        replay_evidence_packet(PDF_SOURCES, relabelled, source_set_digest=PDF_DIGEST)
    # Nothing recorded yet: replay has nothing to infer and reports an incomplete packet.
    assert replay_evidence_packet(PDF_SOURCES, [], source_set_digest=PDF_DIGEST) is None


def test_recorded_v1_requests_are_byte_identical():
    batch = packet_module.packet_batches(SOURCES)[0]
    assert digest(packet_module.INSTRUCTION) == (
        '00e12dbe66fbeeec6c885c24bb6c90e232a869c13bc321a51deeb938605f92de')
    assert digest(packet_module.batch_schema(batch).model_json_schema()) == (
        '0e2ea7935b0405dc734929938cd16a2a60ba3324d2f91d7e95c669d8d08f4e9a')
    assert digest(packet_module.batch_payload(batch, 0, 2, DIGEST)) == (
        '38b3c0eda37734b7d1c6c39cc76981aba21d25b0c6f4d1f1cd38393dcd8e6856')


def test_v3_model_selects_only_a_span_and_status_then_replays_exact_source_text():
    long_source = source('S1', ('Synthetic passage ' +
                                'reports observed operations ' * 20).strip())
    sources = [long_source, PDF_SOURCES[1]]
    source_digest = digest([item.model_dump() for item in sources])
    selected = lambda payload: {item['id']: {'findings': [
        {'status': 'source_reported', 'candidate_id': item['candidates'][0]['id']}]}
        for item in payload['sources']}
    attempts = []
    packet = build(Double(selected), attempts, sources=sources,
                   source_set_digest=source_digest, contract=V3)
    assert packet['packet_contract'] == V3 and packet['coverage']['complete']
    assert packet['cards'][0]['findings'][0]['finding'] == long_source.passage
    assert len(packet['cards'][0]['findings'][0]['finding']) > 300
    assert packet['cards'][0]['findings'][0]['quotes'] == [long_source.passage]
    assert replay_evidence_packet(sources, attempts, source_set_digest=source_digest) == packet
    assert section_cards(packet, operating=False)[0]['findings'][0]['finding'] == long_source.passage
    compact, scope = compact_section_cards(packet, operating=False)
    assert len(compact) == 2 and scope['complete_source_ids'] == ['S1', 'S2']
    assert scope['packet_digest'] == packet['packet_digest']
    assert compact[0]['evidence'] == [{'status': 'source_reported',
                                       'quote': long_source.passage}]
    assert 'finding' not in compact[0]['evidence'][0]
    changed = deepcopy(packet)
    changed['cards'][0]['findings'][0]['quotes'][0] = 'altered'
    with pytest.raises(ValueError, match='digest changed'):
        compact_section_cards(changed, operating=False)
    assert set(attempts[0]['answer']['S1']['findings'][0]) == {'status', 'candidate_id'}
    assert packet_module.FRESH_PACKET_CONTRACT == V3


@pytest.mark.parametrize('change, message', [
    (lambda rows: rows[0].__setitem__('raw_response', rows[0]['raw_response'].replace(
        'S1.c01', 'S1.c02')), 'response was modified'),
    (lambda rows: rows[0]['answer']['S1']['findings'][0].__setitem__(
        'candidate_ids', ['S1.c02']), 'differs'),
    (lambda rows: rows[0]['input']['sources'][0]['candidates'][0].__setitem__(
        'text', 'Example Labs describes a scheduling tool for clinics.'),
     'differs from its frozen batch'),
    (lambda rows: rows[0]['input']['sources'][0]['candidates'].pop(),
     'differs from its frozen batch'),
    (lambda rows: rows[0]['input']['sources'][0].__setitem__('passage_sha256', '0' * 64),
     'differs from its frozen batch'),
    (lambda rows: rows[0].__setitem__('instruction', packet_module.INSTRUCTION),
     'differs from its frozen batch'),
    (lambda rows: rows[0]['schema']['$defs']['SelectedFinding_S1']['properties'][
        'candidate_ids']['items']['enum'].append('S1.c09'), 'differs from its frozen batch'),
])
def test_v2_replay_rejects_an_altered_record(change, message):
    attempts = []
    build(Double(selecting), attempts)
    altered = json.loads(json.dumps(attempts))
    change(altered)
    with pytest.raises(ValueError, match=message):
        replay_evidence_packet(PDF_SOURCES, altered, source_set_digest=PDF_DIGEST)
    # A changed passage is a different source set: the saved spans do not carry over.
    moved = [source('S1', PDF.replace('3 sites', '9 sites')), *PDF_SOURCES[1:]]
    assert replay_evidence_packet(moved, attempts, source_set_digest=digest(
        [item.model_dump() for item in moved])) is None
