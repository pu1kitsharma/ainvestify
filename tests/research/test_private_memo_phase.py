"""Private memo worker phase dispatch; no local model or network calls."""
import json
import sys

from scripts import private_investment_memo_worker as worker


def test_worker_dispatches_durable_draft_phase(tmp_path, monkeypatch):
    from tests.research.test_investment_memo import SOURCE

    (tmp_path / 'request.json').write_text(json.dumps({
        'company': 'Example Labs', 'sources': [SOURCE.model_dump()],
        'as_of_date': '2026-10-03'}))
    (tmp_path / 'model.json').write_text(json.dumps({
        'model': 'local:test', 'profiles': {
            role: 'local:test' for role in
            ('draft', 'draft_b', 'review', 'challenge', 'corrector', 'prose')}}))
    (tmp_path / 'budget.json').write_text(json.dumps({'seconds': 40, 'phase': 'draft_only'}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['private_investment_memo_worker.py'])
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: object())
    observed = {}

    def fake_stage(*args, **kwargs):
        observed['phase'] = kwargs['phase']
        observed['seconds'] = kwargs['budget'].max_seconds
        return {'state': 'draft_ready', 'phase': 'draft_ready', 'draft': {
            'part_a_response_id': 'response_1', 'part_b_response_id': 'response_2'}}

    monkeypatch.setattr(worker, 'run_stage', fake_stage)
    worker.main()
    assert observed == {'phase': 'draft_only', 'seconds': 40.0}
    assert json.loads((tmp_path / 'result.json').read_text())['state'] == 'draft_ready'
    assert json.loads((tmp_path / 'attempts.json').read_text()) == []


def test_worker_passes_frozen_ledger_checkpoint_to_review(tmp_path, monkeypatch):
    from tests.research.test_investment_memo import SOURCE

    (tmp_path / 'request.json').write_text(json.dumps({
        'company': 'Example Labs', 'sources': [SOURCE.model_dump()],
        'as_of_date': '2026-10-03'}))
    (tmp_path / 'model.json').write_text(json.dumps({
        'model': 'local:test', 'profiles': {
            role: 'local:test' for role in
            ('draft', 'draft_b', 'review', 'challenge', 'corrector', 'prose')}}))
    checkpoint = {'state': 'ledger_ready', 'source_set_digest': 'frozen',
                  'as_of_date': '2026-10-03', 'corrected_memo_digest': 'corrected',
                  'ledger_binding_digest': 'ledger', 'final_memo_digest': 'final'}
    (tmp_path / 'budget.json').write_text(json.dumps({
        'seconds': 40, 'phase': 'review_only', 'phase_checkpoint': checkpoint}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['private_investment_memo_worker.py'])
    monkeypatch.setattr(worker, 'LocalModel', lambda *args, **kwargs: object())
    observed = {}

    def fake_stage(*args, **kwargs):
        observed.update(phase=kwargs['phase'], checkpoint=kwargs['phase_checkpoint'])
        return {'state': 'needs_resume', 'phase': 'review_pending'}

    monkeypatch.setattr(worker, 'run_stage', fake_stage)
    worker.main()
    assert observed == {'phase': 'review_only', 'checkpoint': checkpoint}
    assert json.loads((tmp_path / 'result.json').read_text())['phase'] == 'review_pending'
