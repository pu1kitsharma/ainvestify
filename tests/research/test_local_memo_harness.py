import json

import pytest

from scripts import evaluate_local_memo_harness as harness


def fixture(tmp_path, *, classification='synthetic', url='https://example.invalid/evidence'):
    path = tmp_path / ('fixture.' + classification + '.json')
    path.write_text(json.dumps({
        'classification': classification, 'rights_reviewed': True,
        'company': 'Example Labs', 'as_of_date': '2026-10-03',
        'sources': [{'id': 'S1', 'url': url, 'title': 'Example evidence',
                     'passage': 'Example Labs reports a product launch but gives no verified revenue figure.',
                     'version': 'version-1', 'attribution': 'Synthetic fixture'}]}))
    return path


def names():
    return {role: 'installed:latest' for role in harness.ROLES}


def test_fixture_refuses_unreviewed_and_non_synthetic_url(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    path = fixture(tmp_path)
    data = json.loads(path.read_text())
    data['rights_reviewed'] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='rights-reviewed'):
        harness.load_fixture(path)
    path = fixture(tmp_path, url='https://private.example/file')
    with pytest.raises(ValueError, match='example.invalid'):
        harness.load_fixture(path)


def test_profile_requires_installed_exact_model_digest():
    with pytest.raises(ValueError, match='not installed'):
        harness.pin_roles(names(), {})
    pinned = harness.pin_roles(names(), {'installed:latest': 'sha256:abc'})
    assert pinned['review']['digest'] == 'sha256:abc'


def test_fixture_path_must_be_allowlisted(tmp_path):
    with pytest.raises(ValueError, match='allowlist'):
        harness.load_fixture(fixture(tmp_path))


def test_three_passes_preserve_attempts_and_never_promote(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    class FakeModel:
        def __init__(self, name, **kwargs):
            self.name = name

    monkeypatch.setattr(harness, 'LocalModel', FakeModel)
    monkeypatch.setattr(harness, 'installed_models', lambda: {'installed:latest': 'sha256:abc'})

    def fake_stage(company, sources, attempts, save, **kwargs):
        assert kwargs['budget'].max_calls == 5
        attempts.append({'id': f'response_{len(attempts)+1}', 'task': 'investment_memo_part_a',
                         'model': 'installed:latest', 'raw_response': '{"rejected":true}',
                         'error': 'source validation failed'})
        save()
        return {'state': 'needs_resume', 'phase': 'isolated_field_retry_pending'}

    monkeypatch.setattr(harness, 'run_stage', fake_stage)
    output = tmp_path / 'diagnostic'
    report = harness.evaluate(fixture(tmp_path), output, names(), seconds=1,
                              operator_attested=True)
    assert report['workflow_state'] == 'needs_resume'
    assert report['attempt_count'] == 3
    assert report['pass_count'] == 3
    assert report['review_status'] == 'not_reached'
    assert report['artifact_status'] == 'diagnostic_only_no_promotion'
    assert json.loads((output / 'profile.json').read_text())['calls_per_pass'] == 5
    assert len(json.loads((output / 'attempts.json').read_text())) == 3
    assert len(json.loads((output / 'passes.json').read_text())) == 3
    with pytest.raises(FileExistsError):
        harness.evaluate(fixture(tmp_path), output, names(), seconds=1,
                         operator_attested=True)


def test_phase_split_keeps_three_correction_passes_after_slow_drafting(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(harness, 'installed_models', lambda: {'installed:latest': 'sha256:abc'})
    monkeypatch.setattr(harness, 'LocalModel', lambda name, **kwargs: object())
    seen = []
    def stage(company, sources, attempts, save, **kwargs):
        seen.append(kwargs['phase'])
        if len(seen) == 3:
            return {'state': 'draft_ready', 'draft': {'part_a_response_id': 'a',
                'part_b_response_id': 'b'}}
        return {'state': 'needs_resume', 'phase': 'synthetic_pending'}
    monkeypatch.setattr(harness, 'run_stage', stage)
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'phase-split', names(),
                              passes=3, seconds=1, phase_split=True,
                              operator_attested=True)
    assert seen == ['draft_only'] * 3 + ['correction_only'] * 3
    assert report['workflow_state'] == 'awaiting_input'
    assert report['reason'] == 'bounded_correction_only_attempts_exhausted'
    assert report['pass_count'] == 6
    assert report['phase_pass_counts']['ledger_only'] == 0
    rows = json.loads((tmp_path / 'phase-split/passes.json').read_text())
    assert [row['phase_attempt'] for row in rows] == [1, 2, 3, 1, 2, 3]


def test_phase_split_hands_exact_checkpoints_through_finite_ledger_review(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(harness, 'installed_models', lambda: {'installed:latest': 'sha256:abc'})
    monkeypatch.setattr(harness, 'LocalModel', lambda name, **kwargs: object())
    seen = []
    correction = {'state': 'correction_ready', 'corrected_memo_digest': 'corrected',
                  'source_set_digest': 'sources', 'as_of_date': '2026-10-03'}
    ledger = {'state': 'ledger_ready', **{key: value for key, value in correction.items()
              if key != 'state'}, 'ledger_binding_digest': 'ledger',
              'final_memo_digest': 'final'}

    def stage(company, sources, attempts, save, **kwargs):
        seen.append((kwargs['phase'], kwargs['phase_checkpoint']))
        if kwargs['phase'] == 'draft_only':
            return {'state': 'draft_ready', 'draft': {'part_a_response_id': 'a',
                                                     'part_b_response_id': 'b'}}
        if kwargs['phase'] == 'correction_only':
            return correction
        if kwargs['phase'] == 'ledger_only':
            assert kwargs['phase_checkpoint'] is correction
            return ledger
        assert kwargs['phase_checkpoint'] is ledger
        return {'state': 'blocked', 'reason': 'synthetic_review_stop'}

    monkeypatch.setattr(harness, 'run_stage', stage)
    output = tmp_path / 'four-phases'
    report = harness.evaluate(fixture(tmp_path), output, names(), seconds=1,
                              phase_split=True, operator_attested=True)
    assert [phase for phase, _ in seen] == [
        'draft_only', 'correction_only', 'ledger_only', 'review_only']
    assert report['phase_pass_counts'] == {'draft_only': 1, 'correction_only': 1,
                                          'ledger_only': 1, 'review_only': 1}
    rows = json.loads((output / 'passes.json').read_text())
    assert rows[2]['checkpoint_digest'] == harness.digest(correction)
    assert rows[3]['checkpoint_digest'] == harness.digest(ledger)


def test_five_ledger_passes_are_bounded_and_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(harness, 'installed_models', lambda: {'installed:latest': 'sha256:abc'})
    monkeypatch.setattr(harness, 'LocalModel', lambda name, **kwargs: object())
    correction = {'state': 'correction_ready', 'corrected_memo_digest': 'corrected',
                  'source_set_digest': 'sources', 'as_of_date': '2026-10-03'}
    def stage(company, sources, attempts, save, **kwargs):
        if kwargs['phase'] == 'draft_only':
            return {'state': 'draft_ready', 'draft': {'part_a_response_id': 'a',
                                                     'part_b_response_id': 'b'}}
        if kwargs['phase'] == 'correction_only':
            return correction
        assert kwargs['phase'] == 'ledger_only'
        assert kwargs['phase_checkpoint'] is correction
        return {'state': 'needs_resume', 'phase': 'synthetic_ledger_timeout'}
    monkeypatch.setattr(harness, 'run_stage', stage)
    output = tmp_path / 'five-ledger-passes'
    report = harness.evaluate(fixture(tmp_path), output, names(), seconds=1,
                              phase_split=True, operator_attested=True)
    assert report['phase_limits']['ledger_only'] == 5
    assert report['phase_pass_counts'] == {'draft_only': 1, 'correction_only': 1,
                                          'ledger_only': 5, 'review_only': 0}
    assert report['reason'] == 'bounded_ledger_only_attempts_exhausted'
    assert [row['phase_attempt'] for row in json.loads((output / 'passes.json').read_text())
            if row['job_phase'] == 'ledger_only'] == [1, 2, 3, 4, 5]
    with pytest.raises(ValueError, match='finite phase caps'):
        harness.evaluate(fixture(tmp_path), tmp_path / 'too-many-ledger-passes', names(),
                         seconds=1, phase_split=True, operator_attested=True,
                         ledger_passes=6)


def test_replay_copies_frozen_attempts_without_draft_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(harness, 'installed_models', lambda: {'installed:latest': 'sha256:abc'})
    calls = []
    class FakeModel:
        def __init__(self, name, **kwargs):
            pass
        def generate_for_task(self, *args, **kwargs):
            calls.append('model')
            raise AssertionError('Replay must use saved draft responses')
    monkeypatch.setattr(harness, 'LocalModel', FakeModel)
    def stage(company, sources, attempts, save, **kwargs):
        if kwargs['phase'] == 'draft_only':
            if not attempts:
                attempts.extend([{'id': 'a', 'task': 'investment_memo_part_a',
                                  'model': 'installed:latest', 'raw_response': '{}'},
                                 {'id': 'b', 'task': 'investment_memo_part_b',
                                  'model': 'installed:latest', 'raw_response': '{}'}])
                save()
            return {'state': 'draft_ready'}
        if kwargs['phase'] == 'correction_only':
            return {'state': 'correction_ready', 'corrected_memo_digest': 'c',
                    'source_set_digest': 's', 'as_of_date': '2026-10-03'}
        assert kwargs['phase'] == 'ledger_only'
        return {'state': 'needs_resume', 'phase': 'synthetic_ledger_timeout'}
    monkeypatch.setattr(harness, 'run_stage', stage)
    source = tmp_path / 'old-run'
    source_report = harness.evaluate(fixture(tmp_path), source, names(), seconds=1,
        phase_split=True, operator_attested=True, ledger_passes=3)
    assert source_report['workflow_state'] == 'awaiting_input'
    raw_before = (source / 'attempts.json').read_bytes()
    fresh = tmp_path / 'new-run'
    report = harness.evaluate(fixture(tmp_path), fresh, names(), seconds=1,
        phase_split=True, operator_attested=True, ledger_passes=5, replay_from=source)
    assert report['phase_pass_counts']['ledger_only'] == 5
    assert report['reason'] == 'bounded_ledger_only_attempts_exhausted'
    assert calls == []
    assert (source / 'attempts.json').read_bytes() == raw_before
    assert json.loads((fresh / 'profile.json').read_text())['replay_from']['prior_ledger_cap'] == 3
    assert json.loads((fresh / 'passes.json').read_text())[0]['attempt_ids'] == []

    def attempted_redraft(company, sources, attempts, save, **kwargs):
        kwargs['draft_model'].generate_for_task('investment_memo_part_a', '', '', object)
    monkeypatch.setattr(harness, 'run_stage', attempted_redraft)
    refused = harness.evaluate(fixture(tmp_path), tmp_path / 'refused-redraft', names(),
        seconds=1, phase_split=True, operator_attested=True, ledger_passes=5,
        replay_from=source)
    assert refused['workflow_state'] == 'blocked'
    assert 'Saved draft replay attempted fresh local inference' in refused['failure_detail']
    assert calls == []

    profile_path = source / 'profile.json'
    profile = json.loads(profile_path.read_text())
    profile['models']['draft']['digest'] = 'sha256:tampered'
    profile_path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match='model or bounded pass configuration'):
        harness.evaluate(fixture(tmp_path), tmp_path / 'rejected-model', names(), seconds=1,
            phase_split=True, operator_attested=True, ledger_passes=5, replay_from=source)
    assert not (tmp_path / 'rejected-model').exists()
    profile_path.write_text(json.dumps({**profile, 'models': json.loads(
        (fresh / 'profile.json').read_text())['models']}))
    (source / 'attempts.json').write_text(json.dumps([{'id': 'tampered',
        'task': 'investment_memo_part_a', 'model': 'installed:latest'}]))
    with pytest.raises(ValueError, match='pass ledger does not match'):
        harness.evaluate(fixture(tmp_path), tmp_path / 'rejected-attempts', names(), seconds=1,
            phase_split=True, operator_attested=True, ledger_passes=5, replay_from=source)
    assert not (tmp_path / 'rejected-attempts').exists()


def test_harness_routes_distinct_part_b_model(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(harness, 'installed_models', lambda: {
        'installed:latest': 'sha256:a', 'partb:latest': 'sha256:b'})

    class FakeModel:
        def __init__(self, name, **kwargs):
            self.name = name

    def fake_stage(*args, **kwargs):
        assert kwargs['draft_model'].name == 'installed:latest'
        assert kwargs['part_b_model'].name == 'partb:latest'
        assert kwargs['challenge_model'].name == 'installed:latest'
        return {'state': 'blocked', 'reason': 'synthetic_test_stop'}

    monkeypatch.setattr(harness, 'LocalModel', FakeModel)
    monkeypatch.setattr(harness, 'run_stage', fake_stage)
    role_names = {**names(), 'draft_b': 'partb:latest'}
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'split', role_names,
                              seconds=1, operator_attested=True)
    assert report['workflow_state'] == 'blocked'
    assert json.loads((tmp_path / 'split/profile.json').read_text())['models']['draft_b']['digest'] == 'sha256:b'


def test_pass_cap_precedes_fixture_or_inference(tmp_path):
    with pytest.raises(ValueError, match='three passes'):
        harness.evaluate(tmp_path / 'missing', tmp_path / 'out', names(), passes=4)


def test_requires_operator_attestation_before_any_read(tmp_path):
    with pytest.raises(ValueError, match='operator must attest'):
        harness.evaluate(tmp_path / 'missing', tmp_path / 'out', names())


def test_review_rejection_reports_pre_review_source_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(harness, 'installed_models', lambda: {'installed:latest': 'sha256:abc'})
    monkeypatch.setattr(harness, 'LocalModel', lambda name, **kwargs: object())
    monkeypatch.setattr(harness.Memo, 'model_validate', lambda value: value)
    monkeypatch.setattr(harness, 'validate_memo', lambda memo, sources: None)

    def rejected_review(company, sources, attempts, save, **kwargs):
        attempts.append({'id': 'response_1', 'task': 'investment_memo_review',
                         'model': 'installed:latest', 'input': {'memo': {'checked': True}},
                         'answer': {'verdict': 'revise', 'issues': [{'field': 'risk'}]}})
        save()
        return {'state': 'needs_resume', 'phase': 'review_revision_required'}

    monkeypatch.setattr(harness, 'run_stage', rejected_review)
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'review_reject', names(),
                              passes=1, seconds=1, operator_attested=True)
    assert report['source_validation'] == 'pass'
    assert report['review_status'] == 'revise'


def test_accepted_run_without_challenge_is_blocked_and_never_promoted(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(harness, 'installed_models', lambda: {'installed:latest': 'sha256:abc'})
    monkeypatch.setattr(harness, 'LocalModel', lambda name, **kwargs: object())
    monkeypatch.setattr(harness.Memo, 'model_validate', lambda value: value)
    monkeypatch.setattr(harness, 'validate_memo', lambda memo, sources: None)
    note = 'The synthetic review note is long enough for the schema.'
    review = {'verdict': 'pass', 'issues': [], 'recommendation_check': note,
              'source_check': note, 'reasoning_check': note}

    def stage(accepted):
        def run(company, sources, attempts, save, **kwargs):
            assert kwargs['challenge_model'] is not None
            return {'state': 'accepted', 'accepted': accepted}
        return run

    monkeypatch.setattr(harness, 'run_stage', stage({'memo': {}, 'review': review}))
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'unchallenged', names(),
                              passes=1, seconds=1, operator_attested=True)
    assert report['workflow_state'] == 'blocked'
    assert report['reason'] == 'challenge_role_did_not_run'
    assert report['evaluation_state'] == 'blocked'

    # A digest field without a complete, conflict-free ledger record is not a challenge.
    monkeypatch.setattr(harness, 'run_stage', stage(
        {'memo': {}, 'review': review, 'challenged_memo_digest': '0' * 64}))
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'digest-only', names(),
                              passes=1, seconds=1, operator_attested=True)
    assert report['reason'] == 'challenge_role_did_not_run' and report['evaluation_state'] == 'blocked'
    ledger = {'coverage': {'complete': True, 'conflicts': 1},
              'post_correction': {'coverage': {'conflicts': 1}}}
    monkeypatch.setattr(harness, 'run_stage', stage(
        {'memo': {}, 'review': review, 'challenged_memo_digest': '0' * 64, 'challenge': ledger}))
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'conflicting', names(),
                              passes=1, seconds=1, operator_attested=True)
    assert report['reason'] == 'challenge_ledger_incomplete_or_conflicting'
    ledger = {'coverage': {'complete': True, 'conflicts': 0}, 'post_correction': None}
    monkeypatch.setattr(harness, 'run_stage', stage(
        {'memo': {}, 'review': review, 'challenged_memo_digest': '0' * 64, 'challenge': ledger}))
    # Accepted by the stage but not replayable by the renderer: not a draft-to-render pass.
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'unrendered', names(),
                              passes=1, seconds=1, operator_attested=True)
    assert report['render_validation'].startswith('fail') and report['rendered_sections'] == 0
    assert report['evaluation_state'] == 'blocked' and report['independent_review'] == 'pending'

    monkeypatch.setattr(harness, 'renderable_sections',
                        lambda accepted, sources, attempts: [('Heading', 'Body text', 'refs')] * 8)
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'challenged', names(),
                              passes=1, seconds=1, operator_attested=True)
    assert report['render_validation'] == 'pass' and report['rendered_sections'] == 8
    assert report['independent_review'] == 'pending'
    profile = json.loads((tmp_path / 'challenged/profile.json').read_text())
    assert profile['model_options']['draft'] == {'thinking': False, 'temperature': 0,
                                                 'max_tokens': 1400, 'context_tokens': 16384}
    assert report['evaluation_state'] == 'local_review_passed_independent_review_pending'
    assert report['acceptance_scope'] == 'local_model_checks_only'
    assert report['artifact_status'] == 'diagnostic_only_no_promotion'


def test_rejected_review_of_an_invalid_memo_is_reported_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, 'FIXTURE_ROOTS', (tmp_path,))
    monkeypatch.setattr(harness, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(harness, 'installed_models', lambda: {'installed:latest': 'sha256:abc'})
    monkeypatch.setattr(harness, 'LocalModel', lambda name, **kwargs: object())

    def invalid_reviewed(company, sources, attempts, save, **kwargs):
        attempts.append({'id': 'response_1', 'task': 'investment_memo_review',
                         'model': 'installed:latest', 'input': {'memo': {'not': 'a memo'}},
                         'answer': {'blocking': [], 'advisory': [], 'review_note': 'x' * 30}})
        save()
        return {'state': 'needs_resume', 'phase': 'review_revision_required'}

    monkeypatch.setattr(harness, 'run_stage', invalid_reviewed)
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'invalid-memo', names(),
                              passes=1, seconds=1, operator_attested=True)
    assert report['source_validation'].startswith('fail')
    assert report['review_status'] == 'unbindable_reviewed_memo_invalid'
    assert report['render_validation'] == 'not_reached' and report['independent_review'] == 'pending'
    assert report['evaluation_state'] == 'needs_resume'

    # A memo that parses but fails source binding gets the same treatment: a clean
    # review of it is never reported as a pass.
    monkeypatch.setattr(harness.Memo, 'model_validate', lambda value: value)
    def unbound(memo, sources):
        raise ValueError('claim quote is absent from its retained source')
    monkeypatch.setattr(harness, 'validate_memo', unbound)
    called = []
    monkeypatch.setattr(harness, 'review_outcome', lambda *args: called.append(args) or (True, [], {}))
    report = harness.evaluate(fixture(tmp_path), tmp_path / 'unbound-memo', names(),
                              passes=1, seconds=1, operator_attested=True)
    assert report['source_validation'] == 'fail: claim quote is absent from its retained source'
    assert report['review_status'] == 'unbindable_reviewed_memo_invalid' and not called
