"""Synthetic checks for the local challenge role; no company data or network calls."""
import json
from copy import deepcopy

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudget
from agents.research.investment_memo import (Challenge, Memo, Source, renderable_sections,
                                             validate_challenge, validate_memo)
from agents.research.evidence_ledger import cited_assertions, ledger_targets, source_sha256
from agents.research.staged_memo import LEDGER_REVIEW, reviewer_ledger_view, run_stage
from scripts.private_investment_memo_worker import validate_saved_model_roles
from tests.research.test_investment_memo import FakeLocalModel, SOURCE, draft, passing_review

RECORD = json.dumps({'entity': 'Example Labs', 'round': 'Seed', 'status': 'unknown',
                     'amount': {'original': '100000', 'currency': 'USD'}})
REGISTRY = Source(id='S2', url='https://example.invalid/registry', title='Example registry',
                  passage=RECORD, version='registry-v1', attribution='Synthetic registry')
SOURCES = [SOURCE, REGISTRY]
PHRASE = 'the size of the reported round is undisclosed'
EXCERPT = '"amount": {"original": "100000"'
FIRST = ('recommendation', 'recommendation_reason', 'recommendation_claims',
         'investment_thesis', 'business_and_market', 'unknowns')
SECOND = ('differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')


def contradicted_draft():
    """Passes source binding, yet says a value the cited JSON reports is undisclosed."""
    whole = draft()
    whole['risks_and_countercase'] = {
        'heading': 'Risks and countercase',
        'analysis': ('The registry lists a financing entry whose completion is unconfirmed, and '
                     + PHRASE + ' [S2]. The countercase is that the listing may not reflect '
                     'money the company actually holds, so the entry cannot support a view on '
                     'runway or investor commitment until primary records are obtained.'),
        'claims': [{'source_id': 'S2', 'quote': RECORD,
                    'assertion': 'The registry record reports a Seed entry of USD 100000 '
                                 'with unknown status.'}]}
    validate_memo(Memo.model_validate(whole), SOURCES)
    return whole


ASSERTION = ('The registry lists a financing entry whose completion is unconfirmed, and '
             + PHRASE)
AMOUNT_SPAN = '"amount": {"original": "100000", "currency": "USD"}'
NO_AMOUNT = REGISTRY.model_copy(update={'passage': json.dumps(
    {'entity': 'Example Labs', 'round': 'Seed', 'status': 'unknown'})})


def mapping(*claims_per_assertion):
    """A recorded label set: one list of (field, polarity) per assertion."""
    return {'mappings': [{'assertion': index,
                          'claims': [{'field': field, 'polarity': polarity}
                                     for field, polarity in claims]}
                         for index, claims in enumerate(claims_per_assertion)]}


# What the text says, whatever the record holds. First the cited prose (completion in
# doubt, size absent), then the field's claim row (status called unknown).
CLAIM_LABEL = [('status', 'not_reported')]
# The middle entry is the field's prose after its citation, which makes no record claim.
LABELS = mapping([('closing', 'not_reported'), ('amount', 'not_reported')], [], CLAIM_LABEL)
# After the rewrite: two prose sentences citing the record, then the claim row.
RELABELLED = mapping([('amount', 'reported')],
                     [('closing', 'not_reported'), ('cash_receipt', 'not_reported')], CLAIM_LABEL)
QUIET = mapping([], [], [])


def issue(**changes):
    return {'field': 'risks_and_countercase', 'source_id': 'S2',
            'kind': 'contradiction', 'memo_phrase': PHRASE, 'source_excerpt': EXCERPT,
            'defect': 'The cited registry record reports an amount that the prose calls undisclosed.',
            **changes}


def challenge(*issues):
    return {'verdict': 'revise' if issues else 'no_material_defect', 'issues': list(issues),
            'coverage_check': 'Compared each memo field with both complete retained passages.'}


CORRECTION = {'sentences': [
    'The cited registry record reports a funding figure of 100000 in its amount field, so the '
    'memo should treat the round size as source-reported and not as undisclosed.',
    'Diligence should obtain the dated primary financing record to verify whether the reported '
    'round closed and whether the funds were actually received by the company.']}


NOTE = 'The synthetic review note is long enough to satisfy the schema.'
THESIS_PHRASE = 'The source describes a scheduling tool and one pilot'


def evidence_review(blocking=(), advisory=()):
    """An answer to the evidence-bound review contract."""
    return {'blocking': list(blocking), 'advisory': list(advisory), 'review_note': NOTE}


def finding(**changes):
    return {'field': 'investment_thesis', 'source_id': 'S1', 'kind': 'unsupported_fact',
            'memo_phrase': THESIS_PHRASE, 'source_excerpt': '',
            'defect': 'The phrase states a pilot count that the cited passage does not give.',
            **changes}


def models(labels, corrections=(), reviews=(), whole=None):
    whole = whole or contradicted_draft()
    return {'draft_model': FakeLocalModel([{k: whole[k] for k in FIRST},
                                           {k: whole[k] for k in SECOND}]),
            'challenge_model': FakeLocalModel(labels),
            'prose_model': FakeLocalModel(corrections),
            'review_model': FakeLocalModel(reviews)}


def wide():
    return PreparationBudget(105, max_calls=12, max_requests=14)


def run(attempts, roles, sources=SOURCES, **kwargs):
    kwargs.setdefault('budget', wide())
    return run_stage('Example Labs', sources, attempts, lambda: None,
                     as_of_date='2026-10-03', **roles, **kwargs)


def tasks(attempts):
    return [row['task'] for row in attempts]


def control_draft():
    """The same prose and claim, citing a record that has no amount field."""
    whole = contradicted_draft()
    claim = whole['risks_and_countercase']['claims'][0]
    claim['quote'] = NO_AMOUNT.passage
    claim['assertion'] = 'The registry record lists a Seed entry with unknown status.'
    validate_memo(Memo.model_validate(whole), [SOURCE, NO_AMOUNT])
    return whole


def test_whole_memo_challenge_issue_must_quote_memo_and_source_exactly():
    memo = Memo.model_validate(contradicted_draft())
    validate_challenge(Challenge.model_validate(challenge(issue())), memo, SOURCES)
    for bad, message in ((issue(source_excerpt='"amount": {"original": "250000"'), 'source_excerpt'),
                         (issue(memo_phrase='the round size is a secret'), 'memo_phrase'),
                         (issue(source_id='S9'), 'source_id')):
        with pytest.raises(ValueError, match=message):
            validate_challenge(Challenge.model_validate(challenge(bad)), memo, SOURCES)
    assert Challenge.model_validate(challenge(issue(defect='x' * 1200)))
    with pytest.raises(ValueError, match='defect'):
        Challenge.model_validate(challenge(issue(defect='x' * 1201)))


def test_defect_reported_amount_called_absent_is_located_rewritten_and_reviewed():
    whole = contradicted_draft()
    roles = models([LABELS, RELABELLED], [CORRECTION], [evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'accepted'
    assert result['independent_review'] == 'pending'
    assert result['acceptance_scope'] == 'local_model_checks_only'
    assert tasks(attempts) == ['investment_memo_part_a', 'investment_memo_part_b',
        'investment_memo_claim_mapping', 'investment_memo_challenge_field_risks_and_countercase',
        'investment_memo_claim_mapping', 'investment_memo_review']
    accepted = result['accepted']
    memo = accepted['memo']
    for field in whole:
        if field != 'risks_and_countercase':
            assert memo[field] == whole[field]
    assert memo['risks_and_countercase']['claims'] == whole['risks_and_countercase']['claims']
    assert PHRASE not in memo['risks_and_countercase']['analysis']

    map_row, field_row, remap_row, review_row = attempts[2:]
    # The mapping model saw only the structured-cited assertion and field labels:
    # no record value, but the exact record version and hash.
    supplied = map_row['input']
    # The cited span, the prose after the citation, and the claim row.
    assert [(item['kind'], item['text']) for item in supplied['assertions']] == [
        ('prose', ASSERTION),
        ('prose', whole['risks_and_countercase']['analysis'].split('[S2]. ')[1].rstrip('.') + '.'),
        ('claim', whole['risks_and_countercase']['claims'][0]['assertion'])]
    assert AMOUNT_SPAN not in json.dumps(supplied) and 'memo' not in supplied
    assert supplied['cited_sources'] == {'S2': {'version': 'registry-v1',
                                                 'sha256': source_sha256(RECORD)}}
    assert supplied['memo_digest'] == digest(whole) and supplied['purpose'] == 'challenge'
    assert {'amount', 'closing', 'cash_receipt', 'status', 'other'} <= set(supplied['field_labels'])

    bound = accepted['challenge']
    assert bound['contract'] == 'evidence-ledger-v7'
    assert bound['sources']['S2'] == {'version': 'registry-v1', 'structured': True,
                                      'sha256': source_sha256(RECORD)}
    amount = next(fact for fact in bound['facts'] if fact['key'] == 'amount')
    assert amount['span'] == AMOUNT_SPAN == RECORD[amount['span_start']:amount['span_end']]
    assert (amount['value_type'], amount['value_unknown']) == ('object', False)
    conflict = next(row for row in bound['reconciliation'] if row['state'] == 'conflict')
    assert (conflict['field'], conflict['source_id'], conflict['assertion']) == (
        'risks_and_countercase', 'S2', ASSERTION)
    assert conflict['mapping_response_id'] == map_row['id'] and conflict['record_entity'] == 'same'
    # Software settled only the amount; doubt about closing is no conflict.
    assert [(item['label'], item['finding']) for item in conflict['findings']] == [
        ('closing', 'consistent_key_missing'), ('amount', 'conflict_value_reported')]
    assert conflict['findings'][1]['fact']['span'] == AMOUNT_SPAN
    assert bound['coverage'] == {'contract': 'evidence-ledger-v7', 'cited_assertions': 12,
        'structured_claim_assertions': 1,
        'structured_cited_assertions': 3, 'mapped_and_compared': 3, 'conflicts': 1,
        'unresolved_reviewer_required': 0, 'no_direct_conflict_reviewer_required': 2,
        'prose_source_reviewer_required': 10, 'complete': True, 'incomplete_reason': None}
    # The field revision received the conflict as data, bound to ledger and memo.
    patch_input = field_row['input']
    assert 'Do not call that\nreported field absent' in field_row['instruction']
    assert 'reports the status as unknown' not in field_row['instruction']
    assert patch_input['ledger_digest'] == bound['ledger_digest']
    assert patch_input['challenged_memo_digest'] == digest(whole)
    assert patch_input['mapping_response_ids'] == [map_row['id']]
    assert patch_input['ledger_conflicts'][0]['conflicts'][0]['record_key'] == 'amount'
    assert patch_input['ledger_conflicts'][0]['cited_source_id'] == 'S2'
    # The rewritten field was labelled and compared again before the review.
    post = bound['post_correction']
    assert post['mapping_response_ids'] == [remap_row['id']] and post['coverage']['conflicts'] == 0
    assert remap_row['input']['purpose'] == 'post_correction'
    assert remap_row['input']['memo_digest'] == digest(memo) == post['memo_digest']
    # The separate reviewer saw the corrected memo with the ledger and its instruction.
    review_input = review_row['input']
    assert review_input['memo'] == memo and review_input['memo_digest'] == digest(memo)
    assert review_row['instruction'].endswith(LEDGER_REVIEW)
    # A compact view of the final memo only: the old assertion and its conflict are
    # absent, while the digest still binds the complete ledger, rows and patches.
    view = review_input['evidence_ledger']
    assert view == reviewer_ledger_view(bound) and view['binding_digest'] == digest(bound)
    assert 'challenge' not in review_input
    assert PHRASE not in json.dumps(review_input)
    assert all(row['state'] == 'no_direct_conflict_reviewer_required' for row in view['rows'])
    assert [(row['kind'], row['field']) for row in view['rows']] == [
        ('prose', 'risks_and_countercase')] * 2 + [('claim', 'risks_and_countercase')]
    assert all(row['assertion'] in memo['risks_and_countercase']['analysis']
               for row in view['rows'] if row['kind'] == 'prose')
    assert view['assertions_citing_prose_sources'] == 10
    assert {fact['key'] for fact in view['facts']} == {'entity', 'round', 'status', 'amount'}
    assert bound['field_patch_ids'] == {'risks_and_countercase': field_row['id']}
    assert renderable_sections(accepted, SOURCES, attempts)

    before = len(attempts)
    assert run(attempts, models([])) == result and len(attempts) == before


def test_control_same_labels_no_conflict_because_the_record_has_no_amount():
    sources = [SOURCE, NO_AMOUNT]
    whole = control_draft()
    roles = models([LABELS], [], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles, sources=sources)
    assert result['state'] == 'accepted' and result['accepted']['memo'] == whole
    assert tasks(attempts) == ['investment_memo_part_a', 'investment_memo_part_b',
                               'investment_memo_claim_mapping', 'investment_memo_review']
    bound = result['accepted']['challenge']
    row = next(item for item in bound['reconciliation']
               if item['source_id'] == 'S2' and item['kind'] == 'prose')
    # Missing key, and the unknown status stays a fact about status only.
    assert row['state'] == 'no_direct_conflict_reviewer_required'
    assert [(item['label'], item['finding']) for item in row['findings']] == [
        ('closing', 'consistent_key_missing'), ('amount', 'consistent_key_missing')]
    status = next(fact for fact in bound['facts'] if fact['key'] == 'status')
    assert status['value_unknown'] and status['concept'] == 'status'
    assert bound['coverage']['conflicts'] == 0 and bound['post_correction'] is None
    assert bound['field_patch_ids'] == {} and bound['coverage']['complete']
    assert renderable_sections(result['accepted'], sources, attempts)

    # The pair: the identical assertion and the identical recorded labels.
    defect_attempts = []
    run(defect_attempts, models([LABELS, RELABELLED], [CORRECTION], [evidence_review()]))
    assert (defect_attempts[2]['input']['assertions'][0] == attempts[2]['input']['assertions'][0]
            and defect_attempts[2]['answer'] == attempts[2]['answer'] == LABELS)
    assert defect_attempts[2]['input']['cited_sources'] != attempts[2]['input']['cited_sources']


FALSE_CLAIM = 'The registry record lists a Seed entry and does not disclose the round amount.'
CLAIM_FIX = {'assertion': 'The registry record reports a Seed entry with an amount of USD 100000 '
                          'and a status of unknown.'}
ACCURATE_PROSE = (
    'A registry lists a seed financing entry with unknown status [S2]. The entry is a source '
    'report and does not show that the round closed or that the company holds the cash, so the '
    'countercase is that available capital may be lower than the listing implies until primary '
    'financing records are obtained.')


def false_claim_draft():
    """Accurate prose; the rendered claim row is what calls the reported amount absent."""
    whole = contradicted_draft()
    whole['risks_and_countercase']['analysis'] = ACCURATE_PROSE
    whole['risks_and_countercase']['claims'][0]['assertion'] = FALSE_CLAIM
    validate_memo(Memo.model_validate(whole), SOURCES)
    return whole


CLAIM_LABELS = mapping([('status', 'not_reported')], [], [('amount', 'not_reported')])
CLAIM_RELABELLED = mapping([('status', 'not_reported')], [],
                           [('amount', 'reported'), ('status', 'not_reported')])


def rendered(result, attempts):
    return '\n'.join(body for _, body, _ in renderable_sections(result['accepted'], SOURCES,
                                                                  attempts))


def test_false_structured_claim_is_rewritten_before_it_can_be_rendered():
    whole = false_claim_draft()
    roles = models([CLAIM_LABELS, CLAIM_RELABELLED], [CLAIM_FIX], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'accepted' and result['independent_review'] == 'pending'
    assert tasks(attempts) == ['investment_memo_part_a', 'investment_memo_part_b',
        'investment_memo_claim_mapping', 'investment_memo_challenge_claim',
        'investment_memo_claim_mapping', 'investment_memo_review']
    memo = result['accepted']['memo']
    claim = memo['risks_and_countercase']['claims'][0]
    # Only the assertion changed: same source, same exact quote, prose untouched.
    assert claim == {'source_id': 'S2', 'quote': RECORD, 'assertion': CLAIM_FIX['assertion']}
    assert memo['risks_and_countercase']['analysis'] == ACCURATE_PROSE
    assert {key: memo[key] for key in memo if key != 'risks_and_countercase'} == {
        key: whole[key] for key in whole if key != 'risks_and_countercase'}
    bound = result['accepted']['challenge']
    conflict = next(row for row in bound['reconciliation'] if row['state'] == 'conflict')
    assert (conflict['kind'], conflict['claim_index'], conflict['assertion']) == ('claim', 0, FALSE_CLAIM)
    assert bound['claim_patch_ids'] == {'risks_and_countercase#0': attempts[3]['id']}
    assert result['accepted']['challenge_claim_patch_ids'] == bound['claim_patch_ids']
    assert bound['field_patch_ids'] == {} and bound['post_correction']['coverage']['conflicts'] == 0
    # The rewrite task saw the claim's own exact quote and the conflicting record span.
    supplied = attempts[3]['input']
    assert supplied['quote'] == RECORD and supplied['prior_assertion'] == FALSE_CLAIM
    assert supplied['ledger_conflicts'] == [{'field_label': 'amount',
                                            'finding': 'conflict_value_reported', 'record_key': 'amount',
                                            'record_reports_exactly': AMOUNT_SPAN}]
    # What a reader is shown: the corrected claim, never the false one.
    text = rendered(result, attempts)
    assert CLAIM_FIX['assertion'] in text and 'does not disclose the round amount' not in text
    assert FALSE_CLAIM not in json.dumps(attempts[-1]['input'])
    # The false claim is not hidden: it stays in the raw draft and in the ledger record.
    assert attempts[1]['answer']['risks_and_countercase']['claims'][0]['assertion'] == FALSE_CLAIM
    before = len(attempts)
    assert run(attempts, models([])) == result and len(attempts) == before


def test_claim_rewrite_is_source_bound_and_bounded_and_never_software_authored():
    whole = false_claim_draft()
    bad = [{'assertion': 'The registry record reports a Seed entry with an amount of USD 250000.'},
           {'assertion': 'The corrected claim replaces the prior assertion about the amount.'},
           {'assertion': FALSE_CLAIM}]
    roles = models([CLAIM_LABELS], bad, [evidence_review()], whole=whole)
    attempts = []
    with pytest.raises(ValueError, match='claim rewrite retry limit exhausted'):
        run(attempts, roles)
    rewrites = [row for row in attempts if row['task'] == 'investment_memo_challenge_claim']
    assert [row['semantic_validation_error'] for row in rewrites] == [
        "numbers ['250000'] are absent from the exact quote",
        'the assertion refers to an earlier draft, assertion or correction',
        'the conflicting assertion was repeated']
    assert rewrites[1]['input']['validation_issue'] == rewrites[0]['semantic_validation_error']
    assert 'investment_memo_review' not in tasks(attempts)

    # A rewrite that still calls the amount absent is caught by the re-comparison and blocked.
    evasive = {'assertion': 'The registry record lists a Seed entry whose round size is not given.'}
    roles = models([CLAIM_LABELS, CLAIM_LABELS], [evasive], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'blocked' and result['reason'] == 'challenge_conflict_unresolved'
    assert result['unresolved_rows'][0]['kind'] == 'claim'
    assert 'investment_memo_review' not in tasks(attempts)


def test_unrepaired_false_claim_cannot_be_rendered_even_with_a_forged_acceptance():
    whole = false_claim_draft()
    roles = models([CLAIM_LABELS, CLAIM_RELABELLED], [CLAIM_FIX], [evidence_review()], whole=whole)
    attempts = []
    accepted = run(attempts, roles)['accepted']
    forged_memo = deepcopy(accepted['memo'])
    forged_memo['risks_and_countercase']['claims'][0]['assertion'] = FALSE_CLAIM
    with pytest.raises(ValueError):
        renderable_sections({**accepted, 'memo': forged_memo}, SOURCES, attempts)
    with pytest.raises(ValueError, match='exact memo and source set'):
        renderable_sections({**accepted, 'challenge_claim_patch_ids': {}}, SOURCES, attempts)
    # Both the prose and the claim of one field can conflict; both are rewritten.
    both = contradicted_draft()
    both['risks_and_countercase']['claims'][0]['assertion'] = FALSE_CLAIM
    labels = mapping([('amount', 'not_reported')], [], [('amount', 'not_reported')])
    roles = models([labels, RELABELLED], [CLAIM_FIX, CORRECTION], [evidence_review()], whole=both)
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'accepted'
    text = rendered(result, attempts)
    assert PHRASE not in text and 'does not disclose the round amount' not in text
    assert tasks(attempts)[3:5] == ['investment_memo_challenge_claim',
                                    'investment_memo_challenge_field_risks_and_countercase']


def test_structured_ledger_replays_across_finite_phases_without_new_review_repairs():
    whole = contradicted_draft()
    attempts = []
    drafting = models([LABELS, RELABELLED], [CORRECTION], [evidence_review()], whole=whole)
    initial = run(attempts, drafting, phase='draft_only')
    assert initial['state'] == 'draft_ready'
    corrected = run(attempts, models([], whole=whole), phase='correction_only')
    assert corrected['state'] == 'correction_ready'
    ledger = run(attempts, models([LABELS, RELABELLED], [CORRECTION], whole=whole),
                 phase='ledger_only', phase_checkpoint=corrected)
    assert ledger['state'] == 'ledger_ready'
    before = len(attempts)
    reviewed = run(attempts, models([], reviews=[evidence_review()], whole=whole),
                   phase='review_only', phase_checkpoint=ledger)
    assert reviewed['state'] == 'accepted'
    assert [row['task'] for row in attempts[before:]] == ['investment_memo_review']
    rendered(reviewed, attempts)


def test_ledger_targets_include_structured_claim_rows():
    memo = Memo.model_validate(false_claim_draft())
    claims = [target for target in ledger_targets(memo, SOURCES) if target['kind'] == 'claim']
    assert claims == [{'field': 'risks_and_countercase', 'source_id': 'S2', 'assertion': FALSE_CLAIM,
                       'structured': True, 'kind': 'claim', 'claim_index': 0}]
    assert all(target['source_id'] == 'S1' or target['structured']
               for target in ledger_targets(memo, SOURCES))


def test_five_call_passes_reach_the_reviewer_in_two_passes():
    roles = models([LABELS, RELABELLED], [CORRECTION], [evidence_review()])
    attempts = []
    first = run(attempts, roles, budget=PreparationBudget(105, max_calls=5, max_requests=7))
    assert first == {'state': 'needs_resume', 'phase': 'review_pending'} and len(attempts) == 5
    second = run(attempts, roles, budget=PreparationBudget(105, max_calls=5, max_requests=7))
    assert second['state'] == 'accepted' and len(attempts) == 6


def test_ambiguous_or_verification_label_is_explicitly_unresolved_and_never_rewritten():
    whole = contradicted_draft()
    labels = mapping([('amount', 'ambiguous'), ('valuation', 'verified')], [], CLAIM_LABEL)
    roles = models([labels], [], [evidence_review()])
    attempts = []
    result = run(attempts, roles)
    bound = result['accepted']['challenge']
    row = next(item for item in bound['reconciliation']
               if item['source_id'] == 'S2' and item['kind'] == 'prose')
    assert row['state'] == 'unresolved_reviewer_required'
    assert [item['finding'] for item in row['findings']] == [
        'unresolved_ambiguous_mapping', 'unresolved_verification_claim']
    assert bound['coverage']['unresolved_reviewer_required'] == 1
    assert bound['coverage']['conflicts'] == 0 and result['accepted']['memo'] == whole
    assert attempts[-1]['input']['evidence_ledger']['rows'][0]['state'] == 'unresolved_reviewer_required'


def test_record_that_does_not_name_the_company_cannot_prove_a_conflict():
    anonymous = REGISTRY.model_copy(update={'passage': json.dumps(
        {'round': 'Seed', 'status': 'unknown', 'amount': {'original': '100000', 'currency': 'USD'}})})
    whole = contradicted_draft()
    whole['risks_and_countercase']['claims'][0]['quote'] = anonymous.passage
    roles = models([LABELS], [], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles, sources=[SOURCE, anonymous])
    row = next(item for item in result['accepted']['challenge']['reconciliation']
               if item['source_id'] == 'S2' and item['kind'] == 'prose')
    assert row['record_entity'] == 'unstated' and row['state'] == 'unresolved_reviewer_required'
    assert row['findings'][1]['finding'] == 'unresolved_record_entity_unstated'
    assert result['accepted']['memo'] == whole


def test_renderer_rejects_missing_or_altered_ledger_provenance():
    roles = models([LABELS, RELABELLED], [CORRECTION], [evidence_review()])
    attempts = []
    accepted = run(attempts, roles)['accepted']
    stripped = {key: value for key, value in accepted.items() if not key.startswith('challenge')}
    with pytest.raises(ValueError, match='Challenge provenance is incomplete'):
        renderable_sections(stripped, SOURCES, attempts)
    with pytest.raises(ValueError, match='exact memo and source set'):
        renderable_sections({**accepted, 'challenge_field_patch_ids': {}}, SOURCES, attempts)
    for key, value in (('binding_digest', '0' * 64), ('ledger_digest', '0' * 64), ('rows', [])):
        forged = deepcopy(attempts)
        forged[-1]['input']['evidence_ledger'][key] = value
        with pytest.raises(ValueError, match='exact memo and source set'):
            renderable_sections(accepted, SOURCES, forged)
    tampered = deepcopy(attempts)
    tampered[2]['raw_response'] = '{}'
    with pytest.raises(ValueError, match='modified'):
        renderable_sections(accepted, SOURCES, tampered)


def test_mapping_that_stays_incomplete_blocks_before_any_rewrite_or_review():
    empty = {'mappings': []}
    roles = models([empty, empty, empty], [CORRECTION], [evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'blocked' and result['reason'] == 'challenge_coverage_incomplete'
    coverage = result['challenge_coverage']
    assert coverage['complete'] is False and coverage['mapped_and_compared'] == 0
    assert coverage['incomplete_reason'] == 'batch_without_valid_mapping'
    assert coverage['failed_response_ids'] == [row['id'] for row in attempts[2:]]
    assert tasks(attempts)[2:] == ['investment_memo_claim_mapping'] * 3
    assert attempts[3]['input']['previous_response_id'] == attempts[2]['id']
    assert run(attempts, models([]))['state'] == 'blocked' and len(attempts) == 5

    recovered = models([empty, LABELS, RELABELLED], [CORRECTION], [evidence_review()])
    attempts = []
    assert run(attempts, recovered)['state'] == 'accepted'
    assert attempts[3]['input']['retry_base_digest'] == digest(attempts[2]['input'])


def test_conflict_that_survives_the_rewrite_is_blocked_not_reviewed():
    still_absent = mapping([('amount', 'not_reported')], [('closing', 'not_reported')], CLAIM_LABEL)
    roles = models([LABELS, still_absent], [CORRECTION], [evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'blocked' and result['reason'] == 'challenge_conflict_unresolved'
    assert result['unresolved_rows'][0]['findings'][0]['finding'] == 'conflict_value_reported'
    assert result['challenge_coverage']['complete'] is False
    assert 'investment_memo_review' not in tasks(attempts)


def test_rewrite_labelled_reported_but_unverified_is_not_a_surviving_conflict():
    """The saved live failure shape, relabelled with the polarity it lacked."""
    relabelled = mapping([('status', 'reported'), ('amount', 'unverified')],
                         [('closing', 'not_reported'), ('cash_receipt', 'not_reported')], CLAIM_LABEL)
    roles = models([LABELS, relabelled], [CORRECTION], [evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'accepted' and result['independent_review'] == 'pending'
    post = result['accepted']['challenge']['post_correction']
    findings = [item['finding'] for row in post['reconciliation'] for item in row['findings']]
    assert 'consistent_reported_unverified' in findings and post['coverage']['conflicts'] == 0
    assert 'conflict_value_reported' not in findings
    # Status "reported" against a record whose status is unknown is left to the reviewer.
    assert post['coverage']['unresolved_reviewer_required'] == 1
    assert attempts[4]['input']['field_labels'] == attempts[2]['input']['field_labels']
    assert {'not_reported', 'unverified'} <= set(
        attempts[2]['schema']['$defs']['MappedClaim']['properties']['polarity']['enum'])


def test_rewrite_may_state_the_exact_reported_value_bound_to_the_claims_quote():
    """The claim's assertion omits the amount; the amount fact lies inside its exact quote."""
    whole = contradicted_draft()
    whole['risks_and_countercase']['claims'][0]['assertion'] = (
        'The registry record lists a Seed entry for the company with unknown status.')
    exact = {'sentences': [
        'The cited registry record reports an amount of USD 100000 for the Seed entry, which is '
        'a source-reported figure and not an undisclosed amount.',
        CORRECTION['sentences'][1]]}
    roles = models([LABELS, RELABELLED], [exact], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'accepted'
    patch_input = attempts[3]['input']
    # The exact value reached the model, as an allowed number and as the record's own span.
    assert patch_input['allowed_numeric_values'] == ['100000']
    assert patch_input['ledger_conflicts'][0]['conflicts'][0]['record_reports_exactly'] == AMOUNT_SPAN
    assert '100000' in patch_input['claim']['quote']
    assert 'USD 100000' in result['accepted']['memo']['risks_and_countercase']['analysis']
    assert renderable_sections(result['accepted'], SOURCES, attempts)

    # A number that is not the reported fact is still rejected, with bounded feedback.
    wrong = {'sentences': [exact['sentences'][0].replace('100000', '250000'), exact['sentences'][1]]}
    roles = models([LABELS, RELABELLED], [wrong, exact], [evidence_review()], whole=whole)
    attempts = []
    assert run(attempts, roles)['state'] == 'accepted'
    assert "rejected numeric values ['250000']" in attempts[3]['semantic_validation_error']
    assert attempts[4]['input']['previous_response_id'] == attempts[3]['id']


# Shape of the saved live v3 rewrite: correct value, but it talks about the earlier draft.
LEAKED = {'sentences': [
    'The cited registry record reports a funding figure of 100000 in its amount field, which '
    'contradicts the prior assertion that this value was undisclosed.',
    CORRECTION['sentences'][1]]}


def test_rewrite_that_refers_to_the_earlier_draft_is_rejected_and_retried():
    roles = models([LABELS, RELABELLED], [LEAKED, CORRECTION], [evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'accepted'
    leaked, retried = attempts[3], attempts[4]
    assert 'remove language about this analysis' in leaked['semantic_validation_error']
    assert leaked['answer'] == LEAKED and leaked['raw_response']
    assert retried['input']['previous_response_id'] == leaked['id']
    assert 'remove language about this analysis' in retried['input']['validation_issue']
    prose = result['accepted']['memo']['risks_and_countercase']['analysis']
    assert 'prior assertion' not in prose and 'contradicts' not in prose
    assert result['accepted']['challenge']['field_patch_ids'] == {
        'risks_and_countercase': retried['id']}

    # Three leaking answers exhaust the field's bounded attempts; nothing is accepted.
    roles = models([LABELS], [LEAKED] * 3, [evidence_review()])
    attempts = []
    with pytest.raises(ValueError, match='retry limit exhausted'):
        run(attempts, roles)
    assert tasks(attempts).count('investment_memo_challenge_field_risks_and_countercase') == 3
    assert 'investment_memo_review' not in tasks(attempts)


@pytest.mark.parametrize('phrase, leaks', [
    ('which contradicts the prior assertion that this value was undisclosed', True),
    ('unlike the previous draft of this section', True),
    ('the figure was previously described as undisclosed', True),
    ('this correction reflects the registry record', True),
    ('which corrects the earlier wording about the round', True),
    ('the original memo treated the entry as unverified', True),
    # Shape of the saved live timeline rewrite.
    ('the timeline field presents an unresolved discrepancy between the listings', True),
    # Shape of the saved full-draft prose: the retained passages called a "source set".
    ('which conflicts with the seed stage label previously recorded in the source set', True),
    ('the entry conflicts with the seed stage label reported by the registry', False),
    ('the reported timeline presents an unresolved discrepancy between the listings', False),
    ('the company sells field service software to clinics', False),
    ('the prior round was reported at seed stage', False),
    ('a previous funding entry is listed in the registry', False),
    ('the company previously operated under another name', False),
    ('an earlier stage listing may be out of date', False),
    ('diligence should correct for the unverified status of the entry', False),
])
def test_memo_prose_may_not_describe_its_own_drafting(phrase, leaks):
    whole = contradicted_draft()
    whole['diligence_plan']['analysis'] += ' For this entry, ' + phrase + '.'
    if leaks:
        with pytest.raises(ValueError, match='internal workflow language'):
            validate_memo(Memo.model_validate(whole), SOURCES)
    else:
        validate_memo(Memo.model_validate(whole), SOURCES)


# Shape of the saved live block: two valid-length sentences, too short for the field.
SHORT = {'sentences': [
    'The registry record lists a Seed entry for Example Labs with status unknown.',
    'This listing does not establish that the round closed or that funds were received.']}


def test_rewrite_too_short_for_the_field_gets_actionable_feedback_and_a_retry():
    roles = models([LABELS, RELABELLED], [SHORT, CORRECTION], [evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'accepted'
    short, retried = attempts[3], attempts[4]
    assert 'too short for this field' in short['semantic_validation_error']
    assert 'make each sentence substantially longer' in retried['input']['validation_issue']
    assert '[quantity omitted]' not in retried['input']['validation_issue']
    assert 'validation error for MemoPartB' not in retried['input']['validation_issue']
    assert result['accepted']['challenge']['field_patch_ids'] == {
        'risks_and_countercase': retried['id']}
    # Still bounded: three short answers stop the field, and nothing is accepted.
    roles = models([LABELS], [SHORT] * 3, [evidence_review()])
    attempts = []
    with pytest.raises(ValueError, match='retry limit exhausted'):
        run(attempts, roles)
    assert 'investment_memo_review' not in tasks(attempts)


def test_exact_value_is_bound_to_the_cited_quote_not_to_the_whole_source():
    # The claim quotes only the status key, so the amount is outside its exact quote.
    whole = contradicted_draft()
    claim = whole['risks_and_countercase']['claims'][0]
    claim['quote'] = '"status": "unknown"'
    claim['assertion'] = 'The registry record gives the entry status as unknown.'
    memo = Memo.model_validate(whole)
    validate_memo(memo, SOURCES)
    whole['risks_and_countercase']['analysis'] = (
        'The registry record reports an amount of USD 100000 for the entry [S2]. '
        + whole['risks_and_countercase']['analysis'])
    with pytest.raises(ValueError, match='numeric prose is not covered'):
        validate_memo(Memo.model_validate(whole), SOURCES)
    # With the whole record as the claim's exact quote, the same sentence is source-bound.
    claim['quote'] = RECORD
    validate_memo(Memo.model_validate(whole), SOURCES)
    whole['risks_and_countercase']['analysis'] = whole['risks_and_countercase']['analysis'].replace(
        '100000', '250000')
    with pytest.raises(ValueError, match='numeric prose is not covered'):
        validate_memo(Memo.model_validate(whole), SOURCES)
    # A prose passage contributes no such numbers: the earlier rule is unchanged there.
    prose = contradicted_draft()
    prose['investment_thesis']['analysis'] = (
        'The source reports 3 clinics in a pilot [S1]. ' + prose['investment_thesis']['analysis'])
    with pytest.raises(ValueError, match='numeric prose is not covered'):
        validate_memo(Memo.model_validate(prose), SOURCES)


class TimeoutModel:
    """A review role whose call is cancelled at the pass time limit."""
    name = 'offline-test-model'

    def __init__(self):
        self.calls, self.last_response_text, self.last_call = 0, '', {'host': 'test-double'}

    def generate(self, instruction, evidence, schema):
        from agents.preparation.preparation_budget import PreparationBudgetExceeded
        self.calls += 1
        raise PreparationBudgetExceeded('Preparation reached its time limit during inference.')


def test_review_that_times_out_twice_or_stays_invalid_is_blocked_not_passed():
    slow = TimeoutModel()
    roles = {**models([QUIET], [], []), 'review_model': slow}
    attempts = []
    assert run(attempts, roles) == {'state': 'needs_resume', 'phase': 'review_pending'}
    assert run(attempts, roles) == {'state': 'needs_resume', 'phase': 'review_pending'}
    result = run(attempts, roles)
    assert result['state'] == 'blocked' and result['reason'] == 'review_timed_out'
    assert slow.calls == 2 and len(result['review_response_ids']) == 2
    assert run(attempts, roles) == result and slow.calls == 2

    too_long = evidence_review([finding(defect='x' * 1300)])
    roles = models([QUIET], [], [too_long, too_long, evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'blocked' and result['reason'] == 'review_output_invalid'
    assert 'defect' in result['detail'] and result['independent_review'] == 'pending'
    reviews = [row for row in attempts if row['task'] == 'investment_memo_review']
    assert len(reviews) == 2 and all(row['raw_response'] and row['error'] for row in reviews)
    assert 'Schema validation' in reviews[1]['input']['validation_issue']
    # A valid answer on the one allowed retry is used.
    roles = models([QUIET], [], [too_long, evidence_review()])
    attempts = []
    assert run(attempts, roles)['state'] == 'accepted'


def test_review_is_not_started_when_the_pass_cannot_finish_it():
    attempts = []
    roles = models([QUIET], [], [evidence_review()])
    budget = PreparationBudget(105, max_calls=6, max_requests=8)
    budget.started -= 60        # forty-five seconds left: too little for a review
    assert run(attempts, roles, budget=budget) == {'state': 'needs_resume', 'phase': 'review_pending'}
    assert 'investment_memo_review' not in tasks(attempts)
    assert run(attempts, roles)['state'] == 'accepted'


def test_structured_record_that_cannot_be_parsed_blocks_before_any_model_call():
    broken = REGISTRY.model_copy(update={'passage': RECORD + ' trailing text'})
    roles = models([LABELS], [CORRECTION], [evidence_review()])
    attempts = []
    result = run(attempts, roles, sources=[SOURCE, broken])
    assert result['state'] == 'blocked' and result['reason'] == 'challenge_coverage_incomplete'
    assert result['challenge_coverage']['incomplete_reason'] == 'structured_source_unparseable'
    assert tasks(attempts) == ['investment_memo_part_a', 'investment_memo_part_b']


def test_mapping_call_is_not_started_when_the_pass_cannot_finish_it():
    roles = models([LABELS, RELABELLED], [CORRECTION], [evidence_review()])
    attempts = []
    budget = PreparationBudget(105, max_calls=5, max_requests=7)
    budget.started -= 95        # ten seconds left: less than any batch needs
    assert run(attempts, roles, budget=budget) == {'state': 'needs_resume',
                                                   'phase': 'challenge_pending'}
    assert 'investment_memo_claim_mapping' not in tasks(attempts)
    assert run(attempts, roles)['state'] == 'accepted'


def test_mapping_capacity_covers_compact_memo_without_sampling():
    from agents.research.staged_memo import claim_mapping
    from agents.research.evidence_ledger import build_ledger
    from scripts.evaluate_local_memo_harness import load_fixture
    from pathlib import Path
    _, sources = load_fixture(Path(__file__).parents[1] /
        'fixtures/public_memo/stage_order_conflict.synthetic.json')
    ledger = build_ledger(sources)
    base = {'company': 'Harborline Systems', 'as_of_date': '2026-10-03'}
    target = {'field': 'risks_and_countercase', 'kind': 'prose',
              'source_id': 'S2', 'assertion': 'A synthetic source reports a financing label.'}
    budget = PreparationBudget(1, max_calls=1, max_requests=1)
    for count, expected_state in ((26, 'pending'), (33, 'incomplete')):
        result = claim_mapping([target] * count, 'memo-digest', base,
            'source-set-digest', ledger, [], lambda: None, None, budget, 'challenge')
        assert result['state'] == expected_state
        if count == 33:
            assert result['reason'] == 'cited_assertions_exceed_bounded_batches'


def test_revision_that_keeps_the_conflicting_assertion_is_not_accepted():
    kept = {'sentences': [
        ASSERTION + ', which leaves the countercase about committed capital open.',
        CORRECTION['sentences'][1]]}
    roles = models([LABELS], [kept])
    attempts = []
    with pytest.raises(ValueError, match='kept the conflicting assertion'):
        run(attempts, roles)
    assert 'investment_memo_review' not in tasks(attempts)


def test_bound_blocking_finding_gates_and_is_repaired_through_the_field_path():
    patch = {'sentences': [
        'The source reports a clinic scheduling pilot, which could justify further research into buyer needs.',
        'Diligence should obtain dated use records and buyer decisions before treating this pilot as repeatable demand.']}
    roles = models([QUIET], [patch], [evidence_review([finding()]), evidence_review()])
    attempts = []
    first = run(attempts, roles)
    assert first['state'] == 'needs_resume' and first['phase'] == 'review_revision_required'
    assert 'accepted' not in first
    second = run(attempts, roles)
    assert second['state'] == 'accepted' and second['independent_review'] == 'pending'
    assert tasks(attempts)[-2:] == ['investment_memo_review_field_investment_thesis',
                                    'investment_memo_review']
    assert attempts[-2]['input']['review_issues'][0]['kind'] == 'unsupported_fact'
    assert second['accepted']['review_field_patch_ids'].keys() == {'investment_thesis'}
    assert renderable_sections(second['accepted'], SOURCES, attempts)


# Shape of the saved live control review: editorial objections and a claim the
# reviewer talks itself out of, none of it pinned to exact memo and source text.
EDITORIAL = evidence_review(
    blocking=[
        finding(field='recommendation_reason', kind='unsupported_fact',
                memo_phrase='The memo treats missing revenue as a definitive barrier',
                defect='The deferral lacks nuance about why the absence of reported revenue matters.'),
        finding(kind='contradiction', source_excerpt='a pilot proves execution capability',
                defect='The pilot is supposedly evidence of some execution, which the memo understates.'),
        finding(field='diligence_plan', memo_phrase=THESIS_PHRASE, source_id='S2',
                defect='The date relation looked wrong at first; on rechecking it is consistent.')],
    advisory=[{'field': 'investment_thesis',
               'note': 'More depth on why the pilot matters would strengthen the thesis.'},
              {'field': 'overall', 'note': 'Consider adding a competitor comparison section.'}])


BINDING_ERRORS = [
    (0, 'memo_phrase is not an exact phrase of the field prose'),
    (1, 'source_excerpt is not an exact excerpt of the source'),
    (2, 'an unsupported_fact must name a source the field cites')]


def test_malformed_blocking_finding_never_becomes_a_pass():
    """Saved control shape: the reviewer calls something blocking but cannot pin it."""
    roles = models([QUIET], [], [EDITORIAL, EDITORIAL, evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'blocked' and result['reason'] == 'review_blocking_finding_unbound'
    assert 'accepted' not in result and result['independent_review'] == 'pending'
    assert [(item['index'], item['reason']) for item in result['binding_errors']] == BINDING_ERRORS
    reviews = [row for row in attempts if row['task'] == 'investment_memo_review']
    # One saved retry with the binding errors as feedback, then stop: no third call.
    assert len(reviews) == 2 and result['review_response_ids'] == [row['id'] for row in reviews]
    assert all(row['answer'] == EDITORIAL and row['raw_response'] for row in reviews)
    assert 'memo_phrase is not an exact phrase' in reviews[0]['semantic_validation_error']
    assert reviews[1]['input']['previous_response_id'] == reviews[0]['id']
    assert reviews[1]['input']['retry_base_digest'] == digest(reviews[0]['input'])
    assert 'source_excerpt is not an exact excerpt' in reviews[1]['input']['validation_issue']
    # A later pass replays the same block and makes no call.
    assert run(attempts, models([])) == result and len(attempts) == 5


def test_malformed_blocking_finding_can_be_withdrawn_or_bound_on_the_retry():
    whole = contradicted_draft()
    advisory_only = evidence_review(advisory=EDITORIAL['advisory'])
    roles = models([QUIET], [], [EDITORIAL, advisory_only])
    attempts = []
    result = run(attempts, roles)
    # Advisory notes are separate from blocking findings and never gate.
    assert result['state'] == 'accepted' and result['accepted']['memo'] == whole
    assert result['independent_review'] == 'pending'
    assert result['accepted']['review'] == advisory_only
    assert result['accepted']['review_response_id'] == attempts[-1]['id']
    assert result['accepted']['review_summary'] == {'contract': 'source-review-v4',
        'advisory_scope': 'diagnostic_only_not_rendered',
        'blocking_bound': 0, 'blocking_unbound': [], 'advisory_notes': 2}
    # Reviewer notes are diagnostics: none of their text is rendered into the memo.
    shown = '\n'.join(body for _, body, _ in renderable_sections(result['accepted'], SOURCES, attempts))
    assert not any(note['note'] in shown for note in advisory_only['advisory'])
    assert len(advisory_only['advisory']) == 2
    assert attempts[-2]['answer'] == EDITORIAL and attempts[-2]['semantic_validation_error']
    assert renderable_sections(result['accepted'], SOURCES, attempts)
    # The rejected first review cannot be presented as the accepted one.
    forged = {**result['accepted'], 'review': EDITORIAL, 'review_response_id': attempts[-2]['id']}
    with pytest.raises(ValueError, match='exact reviewed model memo'):
        renderable_sections(forged, SOURCES, attempts)

    # Bound on the retry: it gates as a real blocking finding, not as malformed output.
    roles = models([QUIET], [], [EDITORIAL, evidence_review([finding()])])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'needs_resume' and result['phase'] == 'review_revision_required'

    # One bound and one unbound finding together are still malformed output.
    mixed = evidence_review([finding(), EDITORIAL['blocking'][0]])
    roles = models([QUIET], [], [mixed, mixed])
    attempts = []
    assert run(attempts, roles)['reason'] == 'review_blocking_finding_unbound'
    assert not any(task.startswith('investment_memo_review_field_') for task in tasks(attempts))


def test_review_binding_does_not_weaken_the_direct_ledger_conflict_gate():
    """A lenient review cannot pass a memo whose ledger conflict survived."""
    still_absent = mapping([('amount', 'not_reported')], [('closing', 'not_reported')], CLAIM_LABEL)
    roles = models([LABELS, still_absent], [CORRECTION], [evidence_review()])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'blocked' and result['reason'] == 'challenge_conflict_unresolved'
    assert 'investment_memo_review' not in tasks(attempts)

    # A bound contradiction quoting a ledger fact gates like any blocking finding.
    quoted = finding(field='risks_and_countercase', source_id='S2', kind='contradiction',
                     memo_phrase=PHRASE, source_excerpt=AMOUNT_SPAN,
                     defect='The prose calls the round size undisclosed; the record reports it.')
    roles = models([QUIET], [], [evidence_review([quoted])])
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'needs_resume' and result['phase'] == 'review_revision_required'


def test_review_without_a_ledger_keeps_the_earlier_verdict_contract():
    whole = contradicted_draft()
    plain = {'draft_model': FakeLocalModel([{k: whole[k] for k in FIRST},
                                            {k: whole[k] for k in SECOND}]),
             'review_model': FakeLocalModel([passing_review()])}
    attempts = []
    result = run(attempts, plain)
    assert result['state'] == 'accepted' and result['accepted']['review_summary'] is None
    assert attempts[-1]['input']['review_contract'] == 'source-review-v2'
    assert 'challenge' not in attempts[-1]['input']


def test_every_span_of_prose_has_a_ledger_row_including_text_after_the_citation():
    whole = contradicted_draft()
    memo = Memo.model_validate(whole)
    targets = cited_assertions(memo, SOURCES)
    assert targets[0] == {'field': 'risks_and_countercase', 'source_id': 'S2',
                          'assertion': ASSERTION, 'structured': True}
    # Prose written after the marker is attributed to that last citation, not dropped.
    assert targets[1]['source_id'] == 'S2' and targets[1]['assertion'].startswith('The countercase')
    assert len(targets) == 12 and {target['field'] for target in targets} == {
        'recommendation_reason', 'investment_thesis', 'business_and_market',
        'differentiation_and_execution', 'risks_and_countercase', 'diligence_plan'}
    for field in ('investment_thesis', 'risks_and_countercase'):
        spans = [target['assertion'] for target in targets if target['field'] == field]
        prose = whole[field]['analysis']
        assert all(span in prose for span in spans)
        assert sum(len(span) for span in spans) >= len(prose) - 12


# Shape of the saved live miss: the overclaim is written after the citation.
OVERCLAIM = ('A registry lists a seed financing entry [S2], and the company therefore closed the '
             'round and holds the cash to fund its clinic rollout. The countercase is limited to '
             'execution risk, since the financing itself is settled and the registry entry removes '
             'the question of whether capital is available for the plan.')
STATUS_SPAN = '"status": "unknown"'
SETTLED = {'sentences': [
    'The registry record lists a Seed entry whose status the record itself reports as unknown, '
    'so the entry is a source report and not evidence of available capital.',
    CORRECTION['sentences'][1]]}


def test_verified_financing_claim_after_the_citation_conflicts_with_status_unknown():
    whole = contradicted_draft()
    whole['risks_and_countercase']['analysis'] = OVERCLAIM
    validate_memo(Memo.model_validate(whole), SOURCES)
    labels = mapping([('round', 'reported')],
                     [('closing', 'verified'), ('cash_receipt', 'verified')], CLAIM_LABEL)
    relabelled = mapping([('status', 'not_reported')],
                         [('closing', 'not_reported'), ('cash_receipt', 'not_reported')], CLAIM_LABEL)
    roles = models([labels, relabelled], [SETTLED], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles)
    assert result['state'] == 'accepted' and result['independent_review'] == 'pending'
    bound = result['accepted']['challenge']
    conflict = next(row for row in bound['reconciliation'] if row['state'] == 'conflict')
    assert conflict['assertion'].startswith('and the company therefore closed the round')
    assert [(item['label'], item['polarity'], item['finding'], item['fact']['span'])
            for item in conflict['findings']] == [
        ('closing', 'verified', 'conflict_verified_but_status_unknown', STATUS_SPAN),
        ('cash_receipt', 'verified', 'conflict_verified_but_status_unknown', STATUS_SPAN)]
    patch_input = attempts[3]['input']
    assert patch_input['ledger_conflicts'][0]['conflicts'][0]['finding'] == (
        'conflict_verified_but_status_unknown')
    # The instruction is specific to this finding: it asks for "status unknown" and
    # carries none of the reported-value wording that would forbid the word unknown.
    instruction = attempts[3]['instruction']
    assert 'reports the status as unknown' in instruction
    assert 'Do not call that\nreported field absent' not in instruction
    assert 'needs at least 180 characters' in instruction and 'between 110 and 300' in instruction
    assert patch_input['ledger_conflicts'][0]['conflicts'][0]['record_reports_exactly'] == STATUS_SPAN
    text = '\n'.join(body for _, body, _ in renderable_sections(result['accepted'], SOURCES, attempts))
    assert 'closed the round' not in text and 'holds the cash' not in text
    assert 'financing itself is settled' not in text

    # The same claim against a record with no status field is not a software conflict.
    no_status = REGISTRY.model_copy(update={'passage': json.dumps(
        {'entity': 'Example Labs', 'round': 'Seed', 'amount': {'original': '100000', 'currency': 'USD'}})})
    whole['risks_and_countercase']['claims'][0].update(
        quote=no_status.passage, assertion='The registry record reports a Seed entry of USD 100000.')
    roles = models([labels], [], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles, sources=[SOURCE, no_status])
    rows = result['accepted']['challenge']['reconciliation']
    assert not [row for row in rows if row['state'] == 'conflict']
    assert [item['finding'] for row in rows if row['kind'] == 'prose' and row['source_id'] == 'S2'
            for item in row['findings']][1:] == ['unresolved_verification_claim'] * 2


def test_worker_roles_freeze_mapping_calls_to_the_challenge_model():
    roles = {'draft': 'draft:1', 'review': 'review:1', 'corrector': 'fix:1', 'prose': 'prose:1'}
    rows = [{'task': 'investment_memo_claim_mapping', 'model': 'review:1'},
            {'task': 'investment_memo_challenge_field_diligence_plan', 'model': 'prose:1'}]
    validate_saved_model_roles(rows, roles)
    explicit = {**roles, 'challenge': 'challenge:1'}
    with pytest.raises(ValueError, match='frozen role'):
        validate_saved_model_roles(rows, explicit)
    validate_saved_model_roles([{**rows[0], 'model': 'challenge:1'}, rows[1]], explicit)
    with pytest.raises(ValueError, match='incomplete'):
        validate_saved_model_roles([], {**roles, 'other': 'x'})


LISTING = Source(id='S2', url='https://example.invalid/directory', title='Startup directory',
                 passage=json.dumps({'entity': 'Example Labs', 'stage': 'Seed',
                                     'listing_date': '2023-05'}),
                 version='directory-v1', attribution='Synthetic directory')
NOTICE_TEXT = 'Example Labs announced a Series B round in a notice dated 2025-09.'
NOTICE = Source(id='S3', url='https://example.invalid/notice', title='Funding notice',
                passage=NOTICE_TEXT + ' The notice does not state whether the round has closed.',
                version='notice-v1', attribution='Synthetic publisher')
STAGE_SOURCES = [SOURCE, LISTING, NOTICE]
CURRENT = 'it is currently a seed stage prospect'
EVENTS = {'events': [{'source_id': 'S3', 'entity': 'Example Labs', 'stage': 'Series B',
                      'date': '2025-09', 'date_semantics': 'announcement', 'status': 'unknown',
                      'excerpt': NOTICE_TEXT}]}
STAGE_REWRITE = {'sentences': [
    'The directory lists Example Labs at Seed stage as of its 2023-05 listing date, which is a '
    'dated source report and does not establish the present stage.',
    'Diligence should obtain primary financing records before the stage is relied on, because a '
    'dated listing cannot show what has happened since it was made.']}


def stale_draft(analysis, extra_claims=()):
    whole = contradicted_draft()
    whole['risks_and_countercase'] = {
        'heading': 'Risks and countercase', 'analysis': analysis,
        'claims': [{'source_id': 'S2', 'quote': LISTING.passage,
                    'assertion': 'The directory lists Example Labs at Seed stage with a listing '
                                 'date of 2023-05.'}, *extra_claims]}
    validate_memo(Memo.model_validate(whole), STAGE_SOURCES)
    return whole


def test_stale_listing_current_stage_claim_is_challenged_by_a_later_report_from_prose():
    whole = stale_draft(
        'A directory listing describes the company as a seed stage business [S2], so ' + CURRENT
        + ' that fits an early mandate. The countercase is limited to execution, because the '
        'stage is clear and the listing gives no sign that the company has moved beyond its '
        'first institutional round.')
    labels = mapping([('stage', 'reported')], [('stage', 'current')],
                     [('stage', 'reported'), ('date', 'reported')])
    relabelled = mapping([('stage', 'reported'), ('date', 'reported')], [],
                         [('stage', 'reported'), ('date', 'reported')])
    roles = models([labels, EVENTS, relabelled], [STAGE_REWRITE], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles, sources=STAGE_SOURCES)
    assert result['state'] == 'accepted' and result['independent_review'] == 'pending'
    assert tasks(attempts)[2:] == ['investment_memo_claim_mapping', 'investment_memo_source_events',
        'investment_memo_challenge_field_risks_and_countercase', 'investment_memo_claim_mapping',
        'investment_memo_review']
    # Only prose passages were sent for event extraction, each with version and hash.
    assert [(item['source_id'], item['version']) for item in attempts[3]['input']['passages']] == [
        ('S1', 'version123'), ('S3', 'notice-v1')]
    bound = result['accepted']['challenge']
    history = bound['stage_history']
    assert [(event['source_id'], event['origin'], event['date_semantics'], event['status'])
            for event in history['events']] == [
        ('S2', 'structured_record', 'listing_as_of', 'unknown'),
        ('S3', 'model_extracted_from_prose', 'announcement', 'unknown')]
    assert history['events'][1]['response_id'] == attempts[3]['id']
    assert NOTICE.passage[history['events'][1]['excerpt_start']:
                          history['events'][1]['excerpt_end']] == NOTICE_TEXT
    conflict = next(row for row in bound['reconciliation'] if row['state'] == 'conflict')
    assert CURRENT in conflict['assertion']
    finding = conflict['findings'][0]
    assert finding['finding'] == 'conflict_current_but_later_report_differs'
    assert finding['fact']['later_report']['source_id'] == 'S3'
    # The correction is told a later report differs, not what it says, and may not
    # state the present stage or that the later round closed.
    patch = attempts[4]
    assert patch['input']['later_reports'] == [{'source_id': 'S3', 'date_semantics': 'announcement',
                                                'status': 'unknown',
                                                'established_as_this_company': True,
                                                'reports_a_different_stage': True}]
    assert 'Series B' not in json.dumps(patch['input'])
    assert 'Do not state what the present stage is' in patch['instruction']
    prose = result['accepted']['memo']['risks_and_countercase']['analysis']
    assert CURRENT not in prose and 'Series B' not in prose
    assert attempts[-1]['input']['evidence_ledger']['stage_history'][1]['status'] == 'unknown'
    assert renderable_sections(result['accepted'], STAGE_SOURCES, attempts)
    before = len(attempts)
    assert run(attempts, models([]), sources=STAGE_SOURCES) == result and len(attempts) == before
    # The extracted event is bound to its source version and hash, and the saved
    # extraction cannot be altered or replayed against a changed passage.
    event = history['events'][1]
    assert (event['source_version'], event['source_sha256']) == (
        'notice-v1', source_sha256(NOTICE.passage))
    assert attempts[3]['input']['passages'][1]['sha256'] == source_sha256(NOTICE.passage)
    tampered = deepcopy(attempts)
    tampered[3]['raw_response'] = json.dumps({'events': []})
    with pytest.raises(ValueError, match='modified'):
        renderable_sections(result['accepted'], STAGE_SOURCES, tampered)
    forged = deepcopy(result['accepted'])
    forged['challenge']['stage_history']['events'][1]['source_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='exact memo and source set'):
        renderable_sections(forged, STAGE_SOURCES, attempts)


@pytest.mark.parametrize('change, reason', [
    ({'entity': 'Other Labs Holdings'}, 'entity is not written in the passage'),
    ({'date': '2025-02-30'}, 'date is not in the excerpt'),
    ({'status': 'completed'}, 'does not affirmatively say the round closed'),
    ({'date_semantics': 'closing'}, 'does not affirmatively say the round closed'),
    # The notice's own wording: a completion word inside a negated, uncertain sentence.
    ({'status': 'completed', 'excerpt': NOTICE.passage},
     'does not affirmatively say the round closed'),
    ({'stage': 'Series C'}, 'stage label is not in the excerpt'),
])
def test_prose_stage_event_is_rejected_unless_bound_to_the_passage(change, reason):
    whole = stale_draft(
        'A directory listing describes the company as a seed stage business [S2], so ' + CURRENT
        + ' that fits an early mandate. The countercase is limited to execution, because the '
        'stage is clear and the listing gives no sign that the company has moved beyond its '
        'first institutional round.')
    labels = mapping([('stage', 'reported')], [('stage', 'current')], [('stage', 'reported')])
    bad = {'events': [{**EVENTS['events'][0], **change}]}
    relabelled = mapping([('stage', 'reported'), ('date', 'reported')], [],
                         [('stage', 'reported'), ('date', 'reported')])
    roles = models([labels, bad, bad, relabelled], [STAGE_REWRITE], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles, sources=STAGE_SOURCES)
    assert reason in attempts[3]['semantic_validation_error']
    bound = result['accepted']['challenge']
    # An event software cannot bind is never used as evidence, and after two saved
    # calls the history is unavailable. That is no proof of anything: the dated
    # listing still cannot carry "currently", so the field is corrected anyway.
    assert bound['stage_history']['state'] == 'unavailable'
    assert tasks(attempts).count('investment_memo_source_events') == 2
    row = next(item for item in bound['reconciliation'] if CURRENT in item['assertion'])
    assert row['findings'][0]['finding'] == 'conflict_current_but_record_is_dated'
    assert row['findings'][0]['fact']['stage_history'] == 'unavailable'
    patch = next(item for item in attempts if item['task'].startswith('investment_memo_challenge_field_'))
    assert 'later_reports' not in patch['input']
    assert CURRENT not in result['accepted']['memo']['risks_and_countercase']['analysis']


def test_later_report_naming_another_entity_is_kept_and_flagged_not_treated_as_fact():
    other = NOTICE.model_copy(update={'passage': NOTICE.passage.replace(
        'Example Labs announced', 'Example Labs GmbH announced')})
    sources = [SOURCE, LISTING, other]
    whole = contradicted_draft()
    whole['risks_and_countercase'] = {
        'heading': 'Risks and countercase',
        'analysis': 'A directory listing describes the company as a seed stage business [S2], so '
                    + CURRENT + ' that fits an early mandate. The countercase is limited to '
                    'execution, because the stage is clear and the listing gives no sign that the '
                    'company has moved beyond its first institutional round.',
        'claims': [{'source_id': 'S2', 'quote': LISTING.passage,
                    'assertion': 'The directory lists Example Labs at Seed stage with a listing '
                                 'date of 2023-05.'}]}
    labels = mapping([('stage', 'reported')], [('stage', 'current')], [('stage', 'reported')])
    events = {'events': [{**EVENTS['events'][0], 'entity': 'Example Labs GmbH',
                          'excerpt': 'Example Labs GmbH announced a Series B round in a notice '
                                     'dated 2025-09.'}]}
    relabelled = mapping([('stage', 'reported'), ('date', 'reported')], [],
                         [('stage', 'reported'), ('date', 'reported')])
    roles = models([labels, events, relabelled], [STAGE_REWRITE], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles, sources=sources)
    bound = result['accepted']['challenge']
    kept = bound['stage_history']['events'][1]
    assert (kept['entity'], kept['entity_match']) == ('Example Labs GmbH', 'different')
    row = next(item for item in bound['reconciliation'] if CURRENT in item['assertion'])
    # The dated listing alone is the conflict. The other entity's report is attached
    # and flagged as not established; it is not what proves the conflict.
    assert row['findings'][0]['finding'] == 'conflict_current_but_record_is_dated'
    assert row['findings'][0]['fact']['later_report']['entity_match'] == 'different'
    patch = next(item for item in attempts if item['task'].startswith('investment_memo_challenge_field_'))
    assert patch['input']['later_reports'][0]['established_as_this_company'] is False
    assert CURRENT not in result['accepted']['memo']['risks_and_countercase']['analysis']


def test_stale_listing_control_that_calls_nothing_current_is_left_unchanged():
    # Control: the prose reports both sources and calls nothing current. No history call.
    control = stale_draft(
        'A directory listing describes the company as a seed stage business [S2], while a newer '
        'notice reports a later round whose closing is not stated [S3]. The countercase is that '
        'the company may already be beyond an early mandate, so the present stage stays open '
        'until primary financing records are obtained.',
        extra_claims=[{'source_id': 'S3', 'quote': NOTICE_TEXT,
                       'assertion': 'A notice dated 2025-09 reports a Series B round for Example Labs.'}])
    labels = mapping([('stage', 'reported')], [('stage', 'reported'), ('date', 'reported')])
    roles = models([labels], [], [evidence_review()], whole=control)
    attempts = []
    result = run(attempts, roles, sources=STAGE_SOURCES)
    assert result['state'] == 'accepted' and result['accepted']['memo'] == control
    assert 'investment_memo_source_events' not in tasks(attempts)
    assert result['accepted']['challenge']['stage_history'] is None


def test_empty_event_extraction_is_no_proof_and_the_current_claim_is_still_corrected():
    """Saved live v7 shape: `stage: current` labelled, extraction returned no events,
    and the reviewer would have passed it."""
    whole = stale_draft(
        'A directory listing describes the company as a seed stage business [S2], so ' + CURRENT
        + ' that fits an early mandate. The countercase is limited to execution, because the '
        'stage is clear and the listing gives no sign that the company has moved beyond its '
        'first institutional round.')
    labels = mapping([('stage', 'reported')], [('stage', 'current')],
                     [('stage', 'reported'), ('date', 'reported')])
    relabelled = mapping([('stage', 'reported'), ('date', 'reported')], [],
                         [('stage', 'reported'), ('date', 'reported')])
    roles = models([labels, {'events': []}, relabelled], [STAGE_REWRITE], [evidence_review()],
                   whole=whole)
    attempts = []
    result = run(attempts, roles, sources=STAGE_SOURCES)
    assert result['state'] == 'accepted' and result['independent_review'] == 'pending'
    bound = result['accepted']['challenge']
    assert [event['source_id'] for event in bound['stage_history']['events']] == ['S2']
    row = next(item for item in bound['reconciliation'] if CURRENT in item['assertion'])
    assert row['state'] == 'conflict'
    assert row['findings'][0]['finding'] == 'conflict_current_but_record_is_dated'
    text = '\n'.join(body for _, body, _ in renderable_sections(result['accepted'], STAGE_SOURCES,
                                                                attempts))
    assert CURRENT not in text and 'as of its 2023-05 listing date' in text

    # If the rewrite is labelled current again, the memo is blocked before review.
    again = mapping([('stage', 'current')], [], [('stage', 'reported')])
    roles = models([labels, {'events': []}, again], [STAGE_REWRITE], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles, sources=STAGE_SOURCES)
    assert result['state'] == 'blocked' and result['reason'] == 'challenge_conflict_unresolved'
    assert 'investment_memo_review' not in tasks(attempts)


def test_event_whose_entity_is_named_only_elsewhere_in_the_passage_is_not_established():
    multi = NOTICE.model_copy(update={'passage':
        'Example Labs and two other companies appear in this digest. A Series B round was '
        'announced in a notice dated 2025-09. The digest does not say which company raised it.'})
    sources = [SOURCE, LISTING, multi]
    whole = stale_draft(
        'A directory listing describes the company as a seed stage business [S2], so ' + CURRENT
        + ' that fits an early mandate. The countercase is limited to execution, because the '
        'stage is clear and the listing gives no sign that the company has moved beyond its '
        'first institutional round.')
    labels = mapping([('stage', 'reported')], [('stage', 'current')], [('stage', 'reported')])
    relabelled = mapping([('stage', 'reported'), ('date', 'reported')], [],
                         [('stage', 'reported'), ('date', 'reported')])
    events = {'events': [{**EVENTS['events'][0],
                          'excerpt': 'A Series B round was announced in a notice dated 2025-09.'}]}
    roles = models([labels, events, relabelled], [STAGE_REWRITE], [evidence_review()], whole=whole)
    attempts = []
    result = run(attempts, roles, sources=sources)
    bound = result['accepted']['challenge']
    kept = bound['stage_history']['events'][1]
    # Kept with its lineage, but not bound to this company by an excerpt that names it.
    assert kept['entity_match'] == 'unstated' and kept['entity'] == 'Example Labs'
    row = next(item for item in bound['reconciliation'] if CURRENT in item['assertion'])
    assert row['findings'][0]['finding'] == 'conflict_current_but_record_is_dated'
    assert row['findings'][0]['fact']['later_report']['entity_match'] == 'unstated'
    patch = next(item for item in attempts if item['task'].startswith('investment_memo_challenge_field_'))
    assert patch['input']['later_reports'][0]['established_as_this_company'] is False
