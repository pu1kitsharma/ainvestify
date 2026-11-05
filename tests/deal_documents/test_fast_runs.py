"""Durable progress checks that can also run with the standard-library unittest runner."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from delivery.deal_documents import runs


class FastRunTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.conn = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(self.conn.close)
        self.run = runs.create(self.conn, 'tenant', 'room', 'deal', 'Synthetic Co', self.path, 'local-model')

    def tracker(self):
        runs.queue(self.conn, self.run, 'facts', 'operator')
        run, phase, token = runs.claim(self.conn)
        return runs.Tracker(self.conn, run, phase, token, 'unchanged-version')

    def test_new_runs_default_to_pages_and_existing_runs_keep_their_path(self):
        self.assertEqual(runs.public(self.run)['generation_path'], 'page_first')
        runs.update(self.conn, self.run['id'], lambda data: data.pop('generation_path'))
        existing = runs.get_by_id(self.conn, self.run['id'])
        self.assertEqual(runs.public(existing)['generation_path'], 'prose')
        same = runs.create(self.conn, 'tenant', 'room', 'deal', 'Synthetic Co', self.path, 'local-model')
        self.assertNotIn('generation_path', same['data'])

    def test_explicit_path_changes_require_an_idle_memo_and_approved_facts(self):
        with self.assertRaises(ValueError):
            runs.queue(self.conn, self.run, 'facts', 'operator', generation_path='prose')
        tracker = self.tracker()
        (self.path / 'facts.json').write_text('{}')
        tracker.finish('needs_approval')
        runs.approve(self.conn, runs.get_by_id(self.conn, self.run['id']), 'facts', 'operator', {'by': 'operator'})
        run = runs.get_by_id(self.conn, self.run['id'])
        runs.queue(self.conn, run, 'memo', 'operator', generation_path='prose')
        self.assertEqual(runs.get_by_id(self.conn, run['id'])['data']['generation_path'], 'prose')
        with self.assertRaises(ValueError):
            runs.queue(self.conn, runs.get_by_id(self.conn, run['id']), 'memo', 'operator', generation_path='page_first')
        self.assertEqual(runs.get_by_id(self.conn, run['id'])['data']['generation_path'], 'prose')

    def test_legacy_step_hash_and_file_name_still_resume(self):
        tracker = self.tracker()
        tracker.plan([('write:part', 'Write part', 'write')])
        inputs = ['approved-hash', {'item': 1}]
        digest = hashlib.sha256(json.dumps(['unchanged-version', 'local-model', inputs], sort_keys=True, default=str).encode()).hexdigest()
        path = tracker.cache / 'write_part.json'
        path.write_text(json.dumps({'inputs': digest, 'result': {'state': 'valid'}, 'detail': 'previous', 'seconds': 123}))
        result = tracker.step('write:part', inputs, lambda: self.fail('Legacy cached writing repeated'))
        self.assertEqual(result['state'], 'valid')
        step = runs.get_by_id(self.conn, self.run['id'])['data']['phases']['facts']['steps'][0]
        self.assertTrue(step['cached'])
        self.assertEqual(step['seconds'], 123)

    def test_failed_outputs_remain_retryable_and_visible_as_failed(self):
        tracker = self.tracker()
        tracker.plan([('page', 'Write page', 'page_copy')])
        tracker.step('page', [], lambda: {'failure': 'reader unavailable'})
        phase = runs.get_by_id(self.conn, self.run['id'])['data']['phases']['facts']
        self.assertEqual(phase['steps'][0]['state'], 'failed')
        self.assertFalse((tracker.cache / 'page.json').exists())
        self.assertEqual(tracker.step('page', [], lambda: {'state': 'valid'}), {'state': 'valid'})

    def test_active_call_and_measured_time_survive_refresh(self):
        tracker = self.tracker()
        def call():
            phase = runs.public(runs.get_by_id(self.conn, self.run['id']))['phases']['facts']
            self.assertEqual(next(iter(phase['active_calls'].values()))['name'], 'page-audit')
            return 'result'
        with patch.object(runs.time, 'time', side_effect=[100, 100, 100, 112.5, 112.5]):
            self.assertEqual(tracker.model_call(call, 'page-audit', 'check'), 'result')
        phase = runs.get_by_id(self.conn, self.run['id'])['data']['phases']['facts']
        self.assertFalse(phase['active_calls'])
        timing = phase['call_timings']['check']
        self.assertEqual(timing['samples'], 1)
        self.assertGreater(timing['mean_seconds'], 0)

    def test_failed_call_clears_activity_without_claiming_a_successful_measurement(self):
        tracker = self.tracker()
        def fail():
            raise RuntimeError('model unavailable')
        with self.assertRaises(RuntimeError):
            tracker.model_call(fail, 'page-audit', 'check')
        phase = runs.get_by_id(self.conn, self.run['id'])['data']['phases']['facts']
        self.assertFalse(phase['active_calls'])
        self.assertFalse(phase.get('call_timings'))

    def test_round_updates_are_durable_and_replace_the_same_round(self):
        tracker = self.tracker()
        tracker.round({'round': 0, 'scores': {'part': 60}})
        tracker.round({'round': 1, 'scores': {'part': 80}, 'changes': {'part': {'diff': '-old\n+new'}}})
        tracker.round({'round': 0, 'scores': {'part': 65}})
        rounds = runs.public(runs.get_by_id(self.conn, self.run['id']))['phases']['facts']['rounds']
        self.assertEqual(len(rounds), 2)
        self.assertEqual(next(item for item in rounds if item['round'] == 0)['scores']['part'], 65)

    def test_estimates_distinguish_measured_times_from_starting_assumptions(self):
        estimate = runs.estimate({'state': 'running', 'steps': [
            {'kind': 'page_copy', 'state': 'done', 'seconds': 200},
            {'kind': 'page_copy', 'state': 'pending'}, {'kind': 'page_audit', 'state': 'pending'}]})
        self.assertEqual(estimate['timings']['page_copy']['mean_seconds'], 200)
        self.assertEqual(estimate['timings']['page_copy']['samples'], 1)
        self.assertEqual(estimate['timings']['page_audit']['samples'], 0)
        self.assertIn('starting estimate', estimate['timings']['page_audit']['basis'])
        self.assertIn('variation', estimate['estimate_basis'])


if __name__ == '__main__':
    unittest.main()
