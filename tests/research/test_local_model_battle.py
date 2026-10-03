"""Offline checks of the local-model battle harness; scripted doubles, no inference."""
import json

import pytest

from agents.research.investment_memo import challenge_field_prose
from evals.local_model_battle import runner
from evals.local_model_battle.fixtures import FIXTURE_ROOT, PAIRS, load_fixture
from evals.local_model_battle.suites import (first_response, score_challenge,
                                             score_claim_coverage, score_reconciliation,
                                             Coverage)

NAME = 'offline:latest'


class Scripted:
    """Answers from the payload alone, like a model: it never sees a fixture label."""
    name = NAME

    def __init__(self, answer):
        self.answer, self.calls = answer, 0
        self.last_response_text, self.last_call = '', {'host': 'test-double'}

    def generate(self, instruction, evidence, schema):
        self.calls += 1
        value = self.answer(json.loads(evidence))
        if isinstance(value, Exception):
            raise value
        self.last_response_text = json.dumps(value)
        return schema.model_validate_json(self.last_response_text)


def cases(suite):
    return {case.id: case for case in load_fixture(FIXTURE_ROOT / f'{suite}.synthetic.json')[1]}


def clean(payload=None):
    return {'verdict': 'no_material_defect', 'issues': [],
            'coverage_check': 'Compared each prose field with every complete passage.'}


def issue_for(case, **changes):
    flag = case.expected.flag
    source_id = next(iter(flag.source_spans))
    return {'field': flag.field, 'source_id': source_id, 'kind': flag.kinds[0],
            'memo_phrase': flag.memo_span, 'source_excerpt': flag.source_spans[source_id],
            'defect': 'The prose states something the cited passage does not support.', **changes}


def revise(*issues):
    return {**clean(), 'verdict': 'revise', 'issues': list(issues)}


def answered(answer):
    return {'state': 'answered', 'response_ids': ['response_1'], 'answer': answer}


def test_shipped_fixtures_are_synthetic_paired_and_cover_every_transformation():
    seen = set()
    for suite in ('challenge', 'reconciliation', 'claim_coverage'):
        for case in cases(suite).values():
            units = getattr(case, 'statements', [case])
            seen.update(unit.pair for unit in units)
            assert all(source.url.startswith('https://example.invalid/') for source in case.sources)
    assert seen == set(PAIRS)
    with pytest.raises(ValueError, match='fixture folder'):
        load_fixture(FIXTURE_ROOT.parent / 'runner.py')


def test_fixture_loader_rejects_unpaired_or_mislabelled_cases(tmp_path, monkeypatch):
    data = json.loads((FIXTURE_ROOT / 'challenge.synthetic.json').read_text())
    monkeypatch.setattr('evals.local_model_battle.fixtures.FIXTURE_ROOT', tmp_path)
    path = tmp_path / 'broken.synthetic.json'
    path.write_text(json.dumps({**data, 'cases': data['cases'][:1]}))
    with pytest.raises(ValueError, match='defect and a control'):
        load_fixture(path)
    moved = json.loads(json.dumps(data))
    moved['cases'][0]['expected']['flag']['memo_span'] = 'a span the memo does not contain'
    path.write_text(json.dumps(moved))
    with pytest.raises(ValueError, match='exact memo and source text'):
        load_fixture(path)
    private = json.loads(json.dumps(data))
    private['base']['sources'][0]['url'] = 'https://example.com/company'
    path.write_text(json.dumps(private))
    with pytest.raises(ValueError, match='example.invalid'):
        load_fixture(path)


def test_challenge_score_separates_exact_detection_from_broad_or_unroutable_issues():
    case = cases('challenge')['absent_amount_defect']
    exact_checks, exact = score_challenge(case, answered(revise(issue_for(case))))
    assert all(check['passed'] for check in exact_checks)
    assert exact['exact_defects_detected'] == 1 and exact['issues_other_than_planted_defect'] == 0

    # Right field and source, but an omission about a different sentence.
    prose = challenge_field_prose(case.memo, 'risks_and_countercase')[0]
    broad = issue_for(case, kind='omission', memo_phrase=prose[-60:],
                      source_excerpt='"round":"Seed"')
    checks, counts = score_challenge(case, answered(revise(broad)))
    by_name = {check['property']: check['passed'] for check in checks}
    assert by_name['verdict'] and not by_name['planted_defect_detected_exactly']
    assert not by_name['no_issue_other_than_the_planted_defect']
    assert counts['field_level_detections'] == 1 and counts['exact_defects_detected'] == 0

    # Exact location, but the excerpt is not source text: it cannot be routed.
    unbound = issue_for(case, source_excerpt='"amount":"USD 999999"')
    checks, counts = score_challenge(case, answered(revise(unbound)))
    assert counts['unroutable_challenges'] == 1 and counts['exact_defects_detected'] == 0

    control = cases('challenge')['absent_amount_control']
    checks, counts = score_challenge(control, answered(revise(issue_for(case))))
    assert counts['false_positive_challenges'] == 1
    assert all(check['passed'] for check in score_challenge(control, answered(clean()))[0])


def test_reconciliation_score_counts_false_positive_suggestions_and_wrongful_exclusions():
    case = cases('reconciliation')['stale_listing_defect']
    def answer(first, second, selected):
        reason = 'Reconciled the supplied records for this candidate.'
        return answered({'selected_candidate_id': selected, 'unresolved_questions': ['Current stage?'],
                         'decisions': [{'candidate_id': 'C1', 'status': first, 'reason': reason},
                                       {'candidate_id': 'C2', 'status': second, 'reason': reason}]})
    checks, counts = score_reconciliation(case, answer('investigate', 'defer', 'C1'))
    assert counts['false_positive_suggestions'] == 1
    assert not all(check['passed'] for check in checks)
    checks, counts = score_reconciliation(case, answer('exclude', 'investigate', 'C2'))
    assert counts == {'candidates_assessed': 2, 'false_positive_suggestions': 0,
                      'wrongful_exclusions': 0}
    assert all(check['passed'] for check in checks)
    finances = cases('reconciliation')['finances_defect']
    assert score_reconciliation(finances, answer('exclude', 'defer', 'none'))[1][
        'wrongful_exclusions'] == 1
    inconsistent = score_reconciliation(case, answer('defer', 'defer', 'C2'))[0]
    assert not inconsistent[1]['passed']


def coverage_answer(case, labels):
    items = []
    for statement in case.statements:
        label = labels(statement)
        source = case.sources[0]
        items.append({'statement_id': statement.id, 'label': label,
                      'source_id': 'none' if label == 'unsupported' else source.id,
                      'source_excerpt': '' if label == 'unsupported' else source.passage[:40],
                      'reason': 'Compared the statement with every passage.'})
    return Coverage.model_validate({'items': items}).model_dump()


def test_coverage_score_counts_unsupported_claims_that_were_passed():
    case = cases('claim_coverage')['financing_statements']
    credulous = score_claim_coverage(case, answered(coverage_answer(case, lambda s: 'supported')))
    assert credulous[1]['unsupported_claims_passed'] == 4
    assert credulous[1]['statements_needing_rejection'] == 4
    careful = score_claim_coverage(case, answered(coverage_answer(
        case, lambda s: s.allowed_labels[0])))
    assert careful[1]['unsupported_claims_passed'] == 0 and careful[1]['unbound_excerpts'] == 0
    assert all(check['passed'] for check in careful[0])
    suspicious = score_claim_coverage(case, answered(coverage_answer(case, lambda s: 'unsupported')))
    assert suspicious[1]['false_alarms_on_supported_claims'] == 4


def run_challenge_suite(tmp_path, monkeypatch, answer, **kwargs):
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    model = Scripted(answer)
    card = runner.evaluate('challenge', tmp_path / 'run', {'challenge': NAME},
                           models={'challenge': model}, **kwargs)
    return card, model


def test_runner_saves_raw_responses_scorecard_and_resumes_without_new_calls(tmp_path, monkeypatch):
    seen = []
    def answer(payload):
        seen.append(payload)
        return clean()
    card, model = run_challenge_suite(tmp_path, monkeypatch, answer)
    assert model.calls == 16 and card['complete'] and card['cases_reached'] == 16
    # No label reaches the model: only the production challenge payload does.
    assert all(set(payload) == {'company', 'sources', 'as_of_date', 'memo', 'memo_digest',
                                'source_set_digest', 'challenge_contract'} for payload in seen)
    assert card['metrics']['defect_cases'] == 8 and card['metrics']['exact_defects_detected'] == 0
    assert card['metrics']['false_positive_challenges'] == 0
    assert card['pairs_passed'] == 0 and len(card['pairs']) == 8
    assert card['artifact_status'] == 'diagnostic_only_no_promotion'
    saved = json.loads((tmp_path / 'run/attempts.json').read_text())
    assert len(saved) == 16 and all(row['raw_response'] and row['response_hash'] for row in saved)
    assert json.loads((tmp_path / 'run/scorecard.json').read_text()) == card

    again, replay = run_challenge_suite(tmp_path, monkeypatch, answer)
    assert replay.calls == 0 and again == card
    with pytest.raises(ValueError, match='different fixture, case set or model profile'):
        runner.evaluate('challenge', tmp_path / 'run', {'challenge': NAME},
                        models={'challenge': replay}, only=['absent_amount_defect'])


def test_runner_retains_attempt_but_does_not_write_card_after_model_digest_change(
        tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    observed = iter(({'offline:latest': 'sha256:first'},
                     {'offline:latest': 'sha256:changed'}))
    monkeypatch.setattr(runner, 'installed_models', lambda: next(observed))
    monkeypatch.setattr(runner, 'LocalModel', lambda *args, **kwargs: Scripted(lambda _: clean()))
    output = tmp_path / 'changed'
    with pytest.raises(ValueError, match='digest changed'):
        runner.evaluate('challenge', output, {'challenge': NAME},
                        only=['absent_amount_control'], max_cases=1)
    attempts = json.loads((output / 'attempts.json').read_text())
    assert len(attempts) == 1 and attempts[0]['raw_response']
    assert not (output / 'scorecard.json').exists()


def test_runner_is_bounded_per_invocation_and_continues_on_the_next(tmp_path, monkeypatch):
    by_memo = {case.memo.model_dump()['risks_and_countercase']['analysis']: case
               for case in cases('challenge').values()
               if case.variant == 'defect' and case.expected.flag.location == 'prose'}
    def answer(payload):
        case = by_memo.get(payload['memo']['risks_and_countercase']['analysis'])
        passages = {source['id'] for source in payload['sources']}
        if case and set(case.expected.flag.source_spans) <= passages and any(
                span in source['passage'] for source in payload['sources']
                for span in case.expected.flag.source_spans.values()):
            return revise(issue_for(case))
        return clean()
    card, model = run_challenge_suite(tmp_path, monkeypatch, answer, max_cases=5)
    assert model.calls == 5 and card['cases_reached'] == 5 and not card['complete']
    card, model = run_challenge_suite(tmp_path, monkeypatch, answer, max_cases=24)
    assert model.calls == 11 and card['complete']
    # The whole-memo call quotes prose only, so the claim-located pair is not found by it.
    assert card['metrics']['exact_defects_detected'] == 7
    assert card['pairs_passed'] == 7 and len(card['pairs']) == 8
    with pytest.raises(ValueError, match='limited to'):
        runner.evaluate('challenge', tmp_path / 'run', {'challenge': NAME}, max_cases=25)
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='ignored runtime_qualification'):
        runner.evaluate('challenge', tmp_path / 'run', {'challenge': NAME}, models={})


def test_first_response_keeps_a_bad_answer_final_and_retries_a_missing_answer_once():
    from agents.research.investment_memo import Challenge
    attempts, payload = [], {'case': 'synthetic'}
    bad = Scripted(lambda _: {'verdict': 'maybe'})
    state, _, _ = first_response(bad, 'task', 'instruction', payload, Challenge, attempts, lambda: None)
    assert state == 'failed_generation'
    assert first_response(bad, 'task', 'instruction', payload, Challenge, attempts,
                          lambda: None)[0] == 'failed_generation'
    assert bad.calls == 1 and len(attempts) == 1

    attempts = []
    down = Scripted(lambda _: RuntimeError('Local Ollama inference is unavailable'))
    for expected in ('needs_resume', 'needs_resume', 'blocked', 'blocked'):
        assert first_response(down, 'task', 'instruction', payload, Challenge, attempts,
                              lambda: None)[0] == expected
    assert down.calls == 2 and len(attempts) == 2


PAIR = ['absent_amount_defect', 'absent_amount_control']
PASS = {'blocking': [], 'advisory': [],
        'review_note': 'Compared each cited phrase of the memo with the ledger facts and passages.'}
REWRITE = {'sentences': [
    'The cited registry record reports a seed entry with unknown status, so the listing is a '
    'source report and not proof that the company holds the money.',
    'Diligence should obtain the dated primary financing record to verify whether the reported '
    'round closed and whether the funds were received by the company.']}


def labeller(payload):
    """A scripted mapper: labels from the assertion text alone, as the model must."""
    def claims(text):
        found = []
        if 'undisclosed' in text or 'does not disclose the round amount' in text:
            found.append({'field': 'amount', 'polarity': 'not_reported'})
        if 'unknown status' in text:
            found.append({'field': 'status', 'polarity': 'not_reported'})
        return found
    return {'mappings': [{'assertion': item['assertion'], 'claims': claims(item['text'])}
                         for item in payload['assertions']]}


CLAIM_PAIR = ['absent_amount_claim_defect', 'absent_amount_claim_control']
CLAIM_REWRITE = {'assertion': 'The registry record reports a Seed entry for Example Labs with an '
                              'amount of USD 100000 and an unknown status.'}


def run_pair(tmp_path, name, mapper=labeller, prose=REWRITE, review=PASS, only=PAIR,
             claim=CLAIM_REWRITE):
    # The prose role serves both tasks; a claim task is recognised by its own payload.
    doubles = {'challenge': Scripted(mapper),
               'prose': Scripted(lambda payload: claim if 'prior_assertion' in payload else prose),
               'review': Scripted(lambda _: review)}
    card = runner.evaluate('ledger_flow', tmp_path / name,
                           {role: NAME for role in doubles}, models=doubles,
                           only=only, max_cases=2)
    return card, doubles


def test_ledger_flow_repairs_a_false_claim_row_and_scores_reader_visible_text(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    card, doubles = run_pair(tmp_path, 'claim', only=CLAIM_PAIR)
    assert card['cases_by_state'] == {'answered': 2} and card['pairs_passed'] == 1
    assert card['metrics']['claim_rows_rewritten'] == 1 and card['metrics']['conflicts_corrected'] == 1
    assert card['metrics']['false_positive_rewrites'] == 0
    assert (doubles['challenge'].calls, doubles['prose'].calls, doubles['review'].calls) == (3, 1, 2)
    rows = json.loads((tmp_path / 'claim/attempts.json').read_text())
    assert [row['task'] for row in rows][:4] == ['investment_memo_claim_mapping',
        'investment_memo_challenge_claim', 'investment_memo_claim_mapping', 'investment_memo_review']
    # The reviewer was shown the corrected claim row, not the false one.
    assert 'does not disclose the round amount' not in json.dumps(rows[3]['input'])
    assert CLAIM_REWRITE['assertion'] in json.dumps(rows[3]['input'])

    # A rewrite that keeps the defect in the rendered claim row fails the reader-text criterion.
    evasive = {'assertion': 'The registry record lists a Seed entry for Example Labs and does not '
                            'disclose the round amount in this listing.'}
    card, _ = run_pair(tmp_path, 'evasive', only=CLAIM_PAIR, claim=evasive)
    assert card['cases'][0]['state'] == 'blocked' and card['pairs_passed'] == 0
    assert card['cases'][0]['reason'] == 'challenge_conflict_unresolved'


def test_ledger_flow_scores_the_pair_through_the_production_step(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    card, doubles = run_pair(tmp_path, 'pair')
    assert card['complete'] and card['cases_by_state'] == {'answered': 2}
    assert card['pairs'] == [{'pair': 'reported_amount_called_absent',
                              'variants': {'defect': True, 'control': True}, 'passed': True}]
    metrics = card['metrics']
    assert metrics['exact_conflicts_located'] == 1 and metrics['conflicts_corrected'] == 1
    assert metrics['false_positive_conflicts'] == 0 and metrics['false_positive_rewrites'] == 0
    assert metrics['cited_assertions'] == 24 and metrics['structured_assertions_mapped'] == 6
    assert metrics['reviews_passed'] == 2 and card['checks_passed'] == card['checks_total']
    # Defect: label, rewrite, re-label, review. Control: label and review only.
    assert (doubles['challenge'].calls, doubles['prose'].calls, doubles['review'].calls) == (3, 1, 2)
    rows = json.loads((tmp_path / 'pair/attempts.json').read_text())
    labels = [row for row in rows if row['task'] == 'investment_memo_claim_mapping'
              and row['input']['purpose'] == 'challenge']
    # The same assertion and the same labels on both sides; only the record hash differs.
    assert labels[0]['input']['assertions'] == labels[1]['input']['assertions']
    assert labels[0]['answer'] == labels[1]['answer']
    assert labels[0]['input']['cited_sources'] != labels[1]['input']['cited_sources']
    assert all('100000' not in json.dumps(row['input']) for row in labels)
    reviews = [row for row in rows if row['task'] == 'investment_memo_review']
    assert all(row['input']['evidence_ledger']['contract'] == 'evidence-ledger-v7' and
               row['input']['review_contract'] == 'source-review-v4' for row in reviews)

    replay, again = run_pair(tmp_path, 'pair')
    assert replay == card and all(model.calls == 0 for model in again.values())


def test_ledger_flow_scores_a_missed_label_and_a_surviving_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    silent = lambda payload: {'mappings': [{'assertion': item['assertion'], 'claims': []}
                                           for item in payload['assertions']]}
    card, _ = run_pair(tmp_path, 'silent', mapper=silent)
    assert card['metrics']['exact_conflicts_located'] == 0 and card['pairs_passed'] == 0
    failed = {check['property'] for check in card['cases'][0]['checks'] if not check['passed']}
    assert failed == {'planted_conflict_located_exactly', 'conflicting_text_rewritten',
                      'no_conflict_after_rewrite', 'reader_visible_text_free_of_planted_defect'}

    # The rewrite is labelled absent again: production blocks it, and so does the score.
    stubborn = lambda payload: {'mappings': [
        {'assertion': item['assertion'], 'claims': [{'field': 'amount', 'polarity': 'not_reported'}]}
        for item in payload['assertions']]}
    card, doubles = run_pair(tmp_path, 'stubborn', mapper=stubborn)
    assert card['cases'][0]['state'] == 'blocked'
    assert card['cases'][0]['reason'] == 'challenge_conflict_unresolved'
    assert card['metrics']['blocked_cases'] == 1 and doubles['review'].calls == 1

    partial = lambda payload: {'mappings': []}
    card, doubles = run_pair(tmp_path, 'partial', mapper=partial)
    assert card['cases_by_state'] == {'blocked': 2} and doubles['review'].calls == 0
    assert all(case['reason'] == 'challenge_coverage_incomplete' for case in card['cases'])


def test_pair_fails_unless_the_final_local_review_passes_with_no_issues(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    bound = {'field': 'investment_thesis', 'source_id': 'S1', 'kind': 'unsupported_fact',
             'memo_phrase': 'The company site describes a scheduling tool for clinics',
             'source_excerpt': '', 'defect': 'The phrase states more than the cited page does.'}
    card, _ = run_pair(tmp_path, 'revise', review={**PASS, 'blocking': [bound]})
    assert card['cases_by_state'] == {'answered': 2} and card['pairs_passed'] == 0
    for case in card['cases']:
        failed = [check for check in case['checks'] if not check['passed']]
        assert [check['property'] for check in failed] == ['final_local_review_passed']
        assert failed[0]['observed']['blocking_fields'] == ['investment_thesis']
    assert card['metrics']['reviews_with_bound_blocking_finding'] == 2
    assert card['metrics']['reviews_passed'] == 0

    # A blocking finding software cannot bind is malformed output: one retry, then a fail.
    editorial = {**PASS, 'blocking': [{**bound, 'memo_phrase': 'The memo lacks nuance on revenue'}],
                 'advisory': [{'field': 'overall', 'note': 'More depth would help the thesis.'}]}
    card, doubles = run_pair(tmp_path, 'editorial', review=editorial)
    assert card['pairs_passed'] == 0 and card['metrics']['reviews_passed'] == 0
    assert card['metrics']['reviews_blocked_on_unbound_finding'] == 2
    assert card['metrics']['review_retries_for_unbound_finding'] == 2
    assert doubles['review'].calls == 4
    observed = next(check for check in card['cases'][1]['checks']
                    if check['property'] == 'final_local_review_passed')['observed']
    assert observed['state'] == 'unbound' and observed['unbound_blocking'][0]['index'] == 0

    # Advisory notes alone never gate.
    card, _ = run_pair(tmp_path, 'advisory', review={**PASS, 'advisory': editorial['advisory']})
    assert card['pairs_passed'] == 1 and card['metrics']['review_advisory_notes'] == 2

    # A blocked flow has no review at all: that fails the same check.
    card, _ = run_pair(tmp_path, 'unlabelled', mapper=lambda payload: {'mappings': []})
    for case in card['cases']:
        review = next(check for check in case['checks']
                      if check['property'] == 'final_local_review_passed')
        assert not review['passed'] and review['observed'].startswith('no_review')

    # Even a fully passing pair accepts nothing.
    card, _ = run_pair(tmp_path, 'passing')
    assert card['pairs_passed'] == 1 and card['independent_review'] == 'pending'
    assert card['acceptance_scope'] == 'software_scored_properties_only_not_investment_quality'
    assert card['artifact_status'] == 'diagnostic_only_no_promotion'
    # Software abstentions are reported apart from the pass checks.
    assert card['metrics']['structured_rows_unresolved_before_rewrite'] == 0
    assert card['metrics']['structured_rows_unresolved_after_rewrite'] == 0
    assert not any('unresolved' in check['property'] for case in card['cases']
                   for check in case['checks'])


def test_prior_contract_counterexample_stays_in_the_scorecard(tmp_path, monkeypatch):
    """A saved per-assertion response that missed the planted defect is kept and labelled."""
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    from agents.inference.model_authorship import digest
    defect = cases('challenge')[PAIR[0]]
    run_pair(tmp_path, 'kept')
    attempts_file = tmp_path / 'kept/attempts.json'
    rows = json.loads(attempts_file.read_text())
    flag = defect.expected.flag
    options = [{'option': index, 'text': text} for index, text in enumerate(
        ['"entity":"Example Labs"', '"round":"Seed"', '"date":"2025-06"',
         '"amount":"USD 100000"', '"status":"unknown"'])]
    answer = {'verdict': 'supported', 'evidence_option': 4, 'reason': 'Status is unknown.'}
    raw = json.dumps(answer)
    rows.append({'id': 'response_prior', 'task': 'investment_memo_challenge_check',
                 'model': NAME, 'raw_response': raw, 'response_hash': digest(raw),
                 'answer': answer, 'elapsed_seconds': 9.26,
                 'input': {'contract': 'focused-challenge-v1', 'field': flag.field,
                           'source_id': 'S2', 'memo_digest': digest(defect.memo.model_dump()),
                           'assertion': 'A registry entry is listed, and ' + flag.memo_span,
                           'evidence_options': options}})
    attempts_file.write_text(json.dumps(rows))
    card, doubles = run_pair(tmp_path, 'kept')
    assert all(model.calls == 0 for model in doubles.values())
    assert card['prior_counterexamples'] == 1
    kept = card['prior_responses'][0]
    assert kept['response_id'] == 'response_prior' and kept['missed_planted_defect'] is True
    assert kept['answer'] == answer and kept['planted_option'] == [3]
    assert kept['contract'] == 'focused-challenge-v1' and kept['case_id'] == PAIR[0]


VERIFIED_PAIR = ['verified_amount_defect', 'verified_amount_control']
OVERCLAIM = 'closed the round and holds the cash'
FIELD_REWRITE = {'sentences': [
    'The registry record lists a Seed entry for Example Labs whose status the record reports as '
    'unknown, so the listing is a source report and not evidence of capital.',
    'Diligence should obtain the dated primary financing record to verify whether the reported '
    'round closed and whether the funds were received by the company.']}


def stage_doubles(mapper, review):
    return {'challenge': Scripted(mapper), 'prose': Scripted(lambda _: FIELD_REWRITE),
            'review': Scripted(review), 'corrector': Scripted(lambda _: FIELD_REWRITE)}


def run_stage_pair(tmp_path, name, mapper, review, only=VERIFIED_PAIR):
    doubles = stage_doubles(mapper, review)
    card = runner.evaluate('memo_flow', tmp_path / name, {role: NAME for role in doubles},
                           models=doubles, only=only, max_cases=2)
    return card, doubles


def silent(payload):
    return {'mappings': [{'assertion': item['assertion'], 'claims': []}
                         for item in payload['assertions']]}


def strict_reviewer(payload):
    """Flags the overclaim with an exact, bound finding while it is in the memo."""
    prose = payload['memo']['risks_and_countercase']['analysis']
    if OVERCLAIM not in prose:
        return PASS
    return {**PASS, 'blocking': [{
        'field': 'risks_and_countercase', 'source_id': 'S2', 'kind': 'unsupported_fact',
        'memo_phrase': 'the company therefore ' + OVERCLAIM, 'source_excerpt': '"status":"unknown"',
        'defect': 'The record reports status unknown; the prose states a closed, funded round.'}]}


def test_memo_flow_runs_review_driven_revision_and_re_review_in_production(tmp_path, monkeypatch):
    """Saved live shape: the ledger labels miss the overclaim and the reviewer binds it."""
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    card, doubles = run_stage_pair(tmp_path, 'review-driven', silent, strict_reviewer)
    assert card['cases_by_state'] == {'answered': 2} and card['pairs_passed'] == 1
    metrics = card['metrics']
    assert metrics['planted_defects_removed'] == 1 and metrics['removed_by_review_revision'] == 1
    assert metrics['removed_by_ledger_rewrite'] == 0 and metrics['false_positive_rewrites'] == 0
    assert card['independent_review'] == 'pending'
    rows = json.loads((tmp_path / 'review-driven/attempts/verified_amount_defect.json').read_text())
    control = json.loads((tmp_path / 'review-driven/attempts/verified_amount_control.json').read_text())
    # The control ran on its own fixture draft, not on the defect's.
    assert [row['task'] for row in control] == ['investment_memo_part_a', 'investment_memo_part_b',
        'investment_memo_claim_mapping', 'investment_memo_review']
    assert OVERCLAIM not in json.dumps(control[1]['answer'])
    defect_tasks = [row['task'] for row in rows[:6]]
    # Fixture drafts, labels, rejecting review, production field revision, re-review.
    assert defect_tasks == ['investment_memo_part_a', 'investment_memo_part_b',
        'investment_memo_claim_mapping', 'investment_memo_review',
        'investment_memo_review_field_risks_and_countercase', 'investment_memo_review']
    assert [row['model'] for row in rows[:2]] == ['fixture-stimulus'] * 2
    assert OVERCLAIM in json.dumps(rows[3]['input']['memo'])
    assert OVERCLAIM not in json.dumps(rows[5]['input']['memo'])
    assert rows[4]['input']['review_response_id'] == rows[3]['id']
    assert doubles['review'].calls == 3 and doubles['prose'].calls == 1
    # The defect needed a second bounded production pass: review, then revision and re-review.
    by_id = {case['id']: case for case in card['cases']}
    assert by_id['verified_amount_defect']['passes_used'] == 2
    assert by_id['verified_amount_control']['passes_used'] == 1
    # Local-model calls are counted across passes; the injected drafts are not model calls.
    assert by_id['verified_amount_defect']['counts']['model_calls'] == 4
    assert by_id['verified_amount_defect']['response_ids'] == [row['id'] for row in rows[2:]]
    assert card['authorship']['draft'] == 'fixture_injected_stimulus_not_model_generated'
    assert 'not end-to-end acceptance' in card['authorship']['scope']
    rendered = [check for check in by_id['verified_amount_defect']['checks']
                if check['property'] == 'rendered_from_exact_recorded_responses']
    assert rendered and rendered[0]['passed']

    replay, again = run_stage_pair(tmp_path, 'review-driven', silent, strict_reviewer)
    assert replay == card and all(model.calls == 0 for model in again.values())


def test_memo_flow_removes_the_overclaim_through_the_ledger_when_it_is_labelled(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    def mapper(payload):
        def claims(text):
            return ([{'field': 'closing', 'polarity': 'verified'}] if OVERCLAIM in text else [])
        return {'mappings': [{'assertion': item['assertion'], 'claims': claims(item['text'])}
                             for item in payload['assertions']]}
    card, doubles = run_stage_pair(tmp_path, 'ledger-driven', mapper, strict_reviewer)
    assert card['pairs_passed'] == 1 and card['metrics']['removed_by_ledger_rewrite'] == 1
    assert card['metrics']['removed_by_review_revision'] == 0
    rows = json.loads((tmp_path / 'ledger-driven/attempts/verified_amount_defect.json').read_text())
    assert [row['task'] for row in rows[2:6]] == ['investment_memo_claim_mapping',
        'investment_memo_challenge_field_risks_and_countercase', 'investment_memo_claim_mapping',
        'investment_memo_review']
    assert rows[3]['input']['ledger_conflicts'][0]['conflicts'][0]['finding'] == (
        'conflict_verified_but_status_unknown')


def test_memo_flow_fails_when_the_overclaim_stays_visible_or_the_stage_does_not_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'OUTPUT_ROOT', tmp_path)
    # Nobody catches it: the stage finishes, and the reader-visible check fails the pair.
    card, _ = run_stage_pair(tmp_path, 'missed', silent, lambda payload: PASS)
    assert card['cases_by_state'] == {'answered': 2} and card['pairs_passed'] == 0
    failed = [check['property'] for check in card['cases'][0]['checks'] if not check['passed']]
    # The exact-span check is what fails here. Ledger and review were both clean, which
    # is exactly the stated limit of this score: neither role noticed the overclaim.
    assert failed == ['planted_span_absent_from_rendered_text']
    assert 'paraphrase' in card['authorship']['score_limits']
    passed = {check['property'] for check in card['cases'][0]['checks'] if check['passed']}
    assert {'final_ledger_complete_with_no_conflict_row',
            'final_local_review_has_no_blocking_finding'} <= passed
    assert card['metrics']['planted_defects_removed'] == 0

    # The reviewer keeps rejecting the revised memo: production stops, nothing is accepted.
    def always(payload):
        # Flags one field, and after its revision flags another: the revised memo is rejected.
        thesis = 'The company site describes a scheduling tool for clinics'
        first = thesis in payload['memo']['investment_thesis']['analysis']
        return {**PASS, 'blocking': [{
            'field': 'investment_thesis' if first else 'business_and_market', 'source_id': 'S1',
            'kind': 'unsupported_fact', 'source_excerpt': '',
            'memo_phrase': thesis if first else 'The site presents the product as scheduling software',
            'defect': 'The phrase states more than the cited page does.'}]}
    card, doubles = run_stage_pair(tmp_path, 'rejected', silent, always)
    assert card['pairs_passed'] == 0 and card['cases_by_state'] == {'blocked': 2}
    assert all('failed independent review' in case['reason'] for case in card['cases'])
    assert doubles['review'].calls == 4
