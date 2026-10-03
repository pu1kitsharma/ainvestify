"""Evidence ledger: exact typed facts and label-versus-value comparison. Synthetic only."""
import json

import pytest

from agents.research.evidence_ledger import (LedgerError, build_ledger, compare_claim,
                                             affirms_completion, date_interval, field_labels,
                                             key_concept,
                                             reconcile, source_facts, source_sha256,
                                             structured_stage_events, target_key)
from agents.research.investment_memo import Source

COMPANY = 'Example Labs'


def record(source_id='S2', **fields):
    return Source(id=source_id, url='https://example.invalid/registry', title='Registry',
                  passage=json.dumps({'entity': COMPANY, **fields}),
                  version='registry-v1', attribution='Synthetic registry')


def facts(**fields):
    return source_facts(record(**fields))


def target(source_id='S2', text='The size of the reported round is undisclosed'):
    return {'kind': 'prose', 'field': 'risks_and_countercase', 'source_id': source_id,
            'assertion': text, 'structured': True}


def mapped(*claims, source_id='S2', text=None):
    item = target(source_id, text) if text else target(source_id)
    return {target_key(item): {
        'response_id': 'response_9',
        'claims': [{'field': field, 'polarity': polarity} for field, polarity in claims]}}


def test_facts_are_typed_and_carry_exact_spans_and_source_hash():
    source = record(round='Seed', amount={'original': 100000, 'currency': 'USD'},
                    status='unknown', closed=False)
    by_key = {fact['key']: fact for fact in source_facts(source)}
    for fact in by_key.values():
        assert source.passage[fact['span_start']:fact['span_end']] == fact['span']
        assert fact['source_sha256'] == source_sha256(source.passage)
        assert fact['source_version'] == 'registry-v1'
    assert by_key['amount']['span'] == '"amount": {"original": 100000, "currency": "USD"}'
    assert (by_key['amount']['value_type'], by_key['amount']['concept']) == ('object', 'amount')
    assert by_key['status']['value_unknown'] and not by_key['amount']['value_unknown']
    assert by_key['closed']['value_type'] == 'boolean'
    prose = Source(id='S1', url='https://example.invalid/page', title='Page', version='version-1',
                   passage='Example Labs describes a scheduling tool for clinics.', attribution='x')
    assert source_facts(prose) is None
    ledger = build_ledger([prose, source])
    assert ledger['sources']['S1'] == {'version': 'version-1', 'structured': False,
                                       'sha256': source_sha256(prose.passage)}
    assert ledger['sources']['S2']['structured'] and len(ledger['facts']) == 5
    assert field_labels(ledger)[:2] == ['market_size', 'amount'] and 'closed' in field_labels(ledger)


def test_malformed_or_duplicate_key_record_is_an_error_not_a_guess():
    broken = record(round="Seed").model_copy(update={'passage': '{"entity": "Example Labs", "amount": '})
    with pytest.raises(LedgerError, match='not valid JSON'):
        source_facts(broken)
    listed = record(round="Seed").model_copy(update={'passage': '["a list is not a key/value record", 1]'})
    with pytest.raises(LedgerError, match='key/value record'):
        source_facts(listed)
    repeated = record(round="Seed").model_copy(update={
        'passage': '{"amount": "USD 1", "entity": "Example Labs", "amount": "USD 2"}'})
    with pytest.raises(LedgerError, match='ambiguous'):
        source_facts(repeated)


def test_key_vocabulary_keeps_related_fields_apart():
    assert key_concept('amount') == ('amount', 'head')
    assert key_concept('round_size') == ('amount', 'head')
    assert key_concept('market_size') == ('market_size', 'head')
    assert key_concept('funding_status') == ('status', 'head')
    assert key_concept('operating_status') == ('status', 'head')
    assert key_concept('listing_date') == ('date', 'head') and key_concept('as_of') == ('date', 'head')
    assert key_concept('date_precision') == (None, None)
    assert key_concept('amount_usd') == ('amount', 'mention')
    assert key_concept('cash_received') == ('cash_receipt', 'head')


def test_same_absent_label_gives_different_outcomes_only_because_records_differ():
    reported = compare_claim('amount', 'not_reported', facts(amount='USD 100000', status='unknown'), 'same')
    assert reported[0] == 'conflict_value_reported' and reported[1]['span'] == '"amount": "USD 100000"'
    # Missing key: the status being unknown does not make the amount unknown or reported.
    assert compare_claim('amount', 'not_reported', facts(status='unknown'), 'same') == (
        'consistent_key_missing', None)
    unknown = compare_claim('amount', 'not_reported', facts(amount='undisclosed', status='closed'), 'same')
    assert unknown[0] == 'consistent_value_unknown' and unknown[1]['key'] == 'amount'
    assert compare_claim('status', 'not_reported', facts(amount='USD 1', status='unknown'), 'same')[0] == (
        'consistent_value_unknown')
    assert compare_claim('status', 'not_reported', facts(status='closed'), 'same')[0] == (
        'conflict_value_reported')


@pytest.mark.parametrize('value, finding', [
    ({'original': None, 'currency': 'USD'}, 'consistent_value_unknown'),
    ({'original': 'undisclosed', 'currency': 'USD', 'precision': 'exact'}, 'consistent_value_unknown'),
    ({'currency': 'USD'}, 'consistent_value_unknown'),
    ({'original': 0, 'currency': 'USD'}, 'conflict_value_reported'),
    (0, 'conflict_value_reported'),
    ('0', 'conflict_value_reported'),
    (None, 'consistent_value_unknown'),
    ('', 'consistent_value_unknown'),
    ([], 'consistent_value_unknown'),
])
def test_nested_unknown_amount_and_zero_as_a_reported_value(value, finding):
    assert compare_claim('amount', 'not_reported', facts(amount=value), 'same')[0] == finding


def test_market_size_closing_cash_and_verification_stay_separate_from_amount():
    funded = facts(amount='USD 100000', status='unknown')
    # "Market size is not stated" is not a claim about the funding amount.
    assert compare_claim('market_size', 'not_reported', funded, 'same') == ('consistent_key_missing', None)
    with_market = facts(amount='USD 100000', market_size='USD 5 billion')
    assert compare_claim('market_size', 'not_reported', with_market, 'same')[1]['key'] == 'market_size'
    assert compare_claim('amount', 'not_reported', facts(market_size='USD 5 billion'), 'same') == (
        'consistent_key_missing', None)
    # Doubt about closing or cash receipt is no conflict with a reported amount.
    assert compare_claim('closing', 'not_reported', funded, 'same') == ('consistent_key_missing', None)
    assert compare_claim('cash_receipt', 'not_reported', funded, 'same') == ('consistent_key_missing', None)
    # A record reports; it never verifies. With no status field software leaves a
    # verification claim to the reviewer.
    silent = facts(amount='USD 100000')
    assert compare_claim('amount', 'verified', silent, 'same')[0] == 'unresolved_verification_claim'
    assert compare_claim('closing', 'verified', silent, 'same') == (
        'unresolved_verification_claim', None)
    # When the record itself reports status unknown, "closed" or "received" contradicts it.
    for label in ('closing', 'cash_receipt', 'amount', 'status'):
        finding, fact = compare_claim(label, 'verified', funded, 'same')
        assert finding == 'conflict_verified_but_status_unknown' and fact['key'] == 'status'
    assert compare_claim('closing', 'verified', facts(amount='USD 1', status='closed'), 'same')[0] == (
        'unresolved_verification_claim')
    assert compare_claim('valuation', 'verified', funded, 'same')[0] == 'unresolved_verification_claim'
    assert compare_claim('closing', 'verified', funded, 'unstated')[0] == (
        'unresolved_record_entity_unstated')
    assert compare_claim('amount', 'reported', funded, 'same')[0] == 'consistent_value_reported'


def test_everything_software_cannot_settle_is_an_explicit_unresolved_finding():
    funded = facts(amount='USD 100000')
    assert compare_claim('amount', 'ambiguous', funded, 'same') == (
        'unresolved_ambiguous_mapping', None)
    assert compare_claim('other', 'not_reported', funded, 'same') == (
        'unresolved_field_outside_ledger', None)
    assert compare_claim('amount', 'not_reported', facts(amount_usd=100000), 'same')[0] == (
        'unresolved_related_key')
    assert compare_claim('amount', 'reported', facts(amount='unknown'), 'same')[0] == (
        'unresolved_reported_but_unknown')
    assert compare_claim('valuation', 'reported', funded, 'same') == ('unresolved_no_linked_key', None)
    # The exact record key is a valid label too.
    assert compare_claim('amount_usd', 'not_reported', facts(amount_usd=100000), 'same')[0] == (
        'conflict_value_reported')


@pytest.mark.parametrize('entity, bound, state, finding', [
    ('Example Labs', False, 'conflict', 'conflict_value_reported'),
    ('  example   labs ', False, 'conflict', 'conflict_value_reported'),
    ('Example Labs GmbH', False, 'unresolved_reviewer_required',
     'unresolved_record_names_different_entity'),
    (None, False, 'unresolved_reviewer_required', 'unresolved_record_entity_unstated'),
    # Identity may come from a validated source-to-company binding instead.
    (None, True, 'conflict', 'conflict_value_reported'),
])
def test_only_a_record_established_as_this_companys_can_prove_a_conflict(entity, bound, state, finding):
    fields = {'amount': 'USD 100000'}
    passage = json.dumps({**({'entity': entity} if entity else {}), **fields})
    source = record(round="Seed").model_copy(update={"passage": passage})
    result = reconcile([target()], mapped(('amount', 'not_reported')), build_ledger([source]), COMPANY,
                       bound_sources={'S2'} if bound else frozenset())
    row = result['rows'][0]
    assert row['state'] == state and row['findings'][0]['finding'] == finding
    assert row['record_entity'] == ('bound' if bound else 'same' if state == 'conflict' and entity
                                    else 'different' if entity else 'unstated')
    assert result['coverage']['conflicts'] == int(state == 'conflict')


def test_no_row_is_called_reconciled_and_coverage_fails_closed_without_a_mapping():
    prose = Source(id='S1', url='https://example.invalid/page', title='Page', version='version-1',
                   passage='Example Labs describes a scheduling tool for clinics.', attribution='x')
    ledger = build_ledger([prose, record(amount='USD 100000', status='unknown')])
    quiet = target(text='The registry lists a seed entry for the company')
    targets = [target(), quiet,
               {'kind': 'prose', 'field': 'investment_thesis', 'source_id': 'S1',
                'structured': False, 'assertion': 'The site describes a scheduling tool'},
               # A claim row citing the record is compared exactly like prose.
               {'kind': 'claim', 'claim_index': 0, 'field': 'diligence_plan', 'source_id': 'S2',
                'structured': True, 'assertion': 'The registry record does not give an amount.'}]
    mappings = {**mapped(('amount', 'not_reported'), ('status', 'not_reported')),
                **mapped(text=quiet['assertion']),
                target_key(targets[3]): {'response_id': 'response_9', 'claims': [
                    {'field': 'amount', 'polarity': 'not_reported'}]}}
    result = reconcile(targets, mappings, ledger, COMPANY)
    assert [row['state'] for row in result['rows']] == [
        'conflict', 'no_direct_conflict_reviewer_required', 'prose_source_reviewer_required',
        'conflict']
    assert (result['rows'][3]['kind'], result['rows'][3]['claim_index']) == ('claim', 0)
    assert [item['finding'] for item in result['rows'][0]['findings']] == [
        'conflict_value_reported', 'consistent_value_unknown']
    assert result['rows'][0]['mapping_response_id'] == 'response_9'
    assert result['coverage'] == {'contract': 'evidence-ledger-v7', 'cited_assertions': 3,
        'structured_claim_assertions': 1,
        'structured_cited_assertions': 3, 'mapped_and_compared': 3, 'conflicts': 2,
        'unresolved_reviewer_required': 0, 'no_direct_conflict_reviewer_required': 1,
        'prose_source_reviewer_required': 1, 'complete': True, 'incomplete_reason': None}
    assert not any('reconciled' == row['state'] or 'supported' in row['state']
                   for row in result['rows'])

    missing = reconcile(targets, mapped(('amount', 'not_reported')), ledger, COMPANY)
    assert missing['rows'][1]['state'] == 'unmapped'
    assert missing['coverage']['complete'] is False
    assert missing['coverage']['incomplete_reason'] == 'structured_assertion_without_mapping'
    assert reconcile([], {}, ledger, COMPANY)['coverage']['complete'] is False


def test_reported_but_unverified_is_the_opposite_of_not_reported():
    """Shape of the saved live failure: a rewrite saying the amount "remains unverified"."""
    funded = facts(amount='USD 100000', status='unknown')
    assert compare_claim('amount', 'unverified', funded, 'same')[0] == 'consistent_reported_unverified'
    assert compare_claim('amount', 'not_reported', funded, 'same')[0] == 'conflict_value_reported'
    # Unverified about a field the record does not hold or holds as unknown stays unresolved.
    assert compare_claim('amount', 'unverified', facts(status='unknown'), 'same') == (
        'unresolved_no_linked_key', None)
    assert compare_claim('amount', 'unverified', facts(amount=None), 'same')[0] == (
        'unresolved_reported_but_unknown')
    assert compare_claim('amount', 'unverified', funded, 'unstated')[0] == (
        'unresolved_record_entity_unstated')


def later_event(**changes):
    return {'source_id': 'S3', 'source_version': 'notice-v1', 'source_sha256': 'f' * 64,
            'origin': 'model_extracted_from_prose', 'entity': COMPANY, 'entity_match': 'same',
            'stage': 'Series B', 'stage_key': 'series b', 'date': '2025-09',
            'date_interval': [[2025, 9, 1], [2025, 9, 31]], 'date_semantics': 'announcement',
            'status': 'unknown', 'excerpt': 'announced a Series B round in a notice dated 2025-09',
            **changes}


def test_structured_stage_event_is_bound_to_source_spans_and_date_semantics():
    listing = record(stage='Seed', listing_date='2023-05', status='unknown')
    event, = structured_stage_events(build_ledger([listing]), COMPANY)
    assert (event['source_id'], event['source_version'], event['entity_match']) == (
        'S2', 'registry-v1', 'same')
    assert event['source_sha256'] == source_sha256(listing.passage)
    assert event['stage_span'] == '"stage": "Seed"' and event['date_span'] == '"listing_date": "2023-05"'
    assert event['status_span'] == '"status": "unknown"' and event['status'] == 'unknown'
    assert event['date_semantics'] == 'listing_as_of'
    assert event['date_interval'] == [[2023, 5, 1], [2023, 5, 31]]
    assert date_interval('2025-09-14') == ((2025, 9, 14), (2025, 9, 14))
    assert date_interval('September 2025') is None and date_interval('2025-13') is None
    # Real calendar dates only.
    assert date_interval('2025-02-30') is None and date_interval('2025-00') is None
    assert date_interval('2024-02-29') == ((2024, 2, 29), (2024, 2, 29))
    assert structured_stage_events(build_ledger([record(stage='Seed')]), COMPANY) == []
    closing = structured_stage_events(build_ledger([record(round='Series A', closed_on='2024-03-02')]),
                                      COMPANY)[0]
    assert closing['date_semantics'] == 'closing' and closing['status'] == 'unknown'


def current(history, entity='same', as_of_date='2026-10-03', **fields):
    listing = facts(**{'stage': 'Seed', 'listing_date': '2023-05', **fields})
    return compare_claim('stage', 'current', listing, entity, 'S2', history, as_of_date)


def test_current_stage_claim_is_challenged_by_a_later_dated_report_of_the_same_company():
    finding, fact = current([later_event()])
    assert finding == 'conflict_current_but_later_report_differs'
    assert fact['span'] == '"stage": "Seed"' and fact['record_date'] == '2023-05'
    assert fact['record_date_semantics'] == 'listing_as_of'
    later = fact['later_report']
    # The later report is carried as a report, with its own status and semantics:
    # nothing here says its round closed or that it is the present stage.
    assert (later['source_id'], later['stage'], later['date'], later['status'],
            later['date_semantics'], later['origin']) == (
        'S3', 'Series B', '2025-09', 'unknown', 'announcement', 'model_extracted_from_prose')


@pytest.mark.parametrize('history', [
    [],                                                                  # nothing else found
    None,                                                                # history unavailable
    [later_event(stage='Seed round', stage_key='seed')],                 # later, same stage
    [later_event(date='2023-05', date_interval=[[2023, 5, 1], [2023, 5, 31]])],   # same month
    [later_event(date='2022-01', date_interval=[[2022, 1, 1], [2022, 1, 31]])],   # earlier
    [later_event(source_id='S2')],                                       # the record itself
])
def test_dated_record_never_establishes_the_present_stage_whatever_the_history(history):
    """An empty or unavailable history is no proof: the claim is a conflict on its own."""
    finding, fact = current(history)
    assert finding == 'conflict_current_but_record_is_dated'
    assert fact['record_date'] == '2023-05' and 'later_report' not in fact
    assert fact['stage_history'] == ('unavailable' if history is None else 'built')


def test_current_stage_claim_edges_keep_uncertainty_explicit():
    # A later report naming another entity is attached as such, never as fact.
    finding, fact = current([later_event(entity='Example Labs GmbH', entity_match='different')])
    assert finding == 'conflict_current_but_record_is_dated'
    assert fact['later_report']['entity_match'] == 'different'
    # A record that is not established as this company's proves nothing either way.
    assert current([later_event()], entity='unstated')[0] == 'unresolved_record_entity_unstated'
    # No date at all is no better than an old date.
    undated = compare_claim('stage', 'current', facts(stage='Seed'), 'same', 'S2', [later_event()],
                            '2026-10-03')
    assert undated[0] == 'conflict_current_but_record_is_undated'
    # A record dated in the memo's own month does not contradict "currently".
    assert current([], listing_date='2026-10')[0] == 'unresolved_current_claim_from_same_month_record'
    assert current([], listing_date='2026-09')[0] == 'conflict_current_but_record_is_dated'
    assert compare_claim('amount', 'current', facts(stage='Seed', amount='USD 1'), 'same', 'S2',
                         [later_event()], '2026-10-03')[0] == 'unresolved_current_claim'
    # A stage that is only reported, not called current, is never a conflict here.
    assert compare_claim('stage', 'reported', facts(stage='Seed', listing_date='2023-05'), 'same',
                         'S2', [later_event()], '2026-10-03')[0] == 'consistent_value_reported'


@pytest.mark.parametrize('excerpt, affirmed', [
    ('Example Labs closed its Series B round on 2025-09-14.', True),
    ('The Series B round was completed and the funds were received in 2025-09.', True),
    ('The notice does not state whether the round has closed.', False),
    ('Example Labs announced a Series B round in a notice dated 2025-09.', False),
    ('The round is expected to close in 2025-09.', False),
    ('The round has not yet closed as of 2025-09.', False),
    ('Closing is subject to approval and may be completed in 2025-09.', False),
    ("The company hasn't received the funds from its 2025-09 round.", False),
    ('It is unknown if the 2025-09 round was completed.', False),
])
def test_completion_needs_an_affirmative_excerpt(excerpt, affirmed):
    assert affirms_completion(excerpt) is affirmed
