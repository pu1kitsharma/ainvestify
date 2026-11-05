"""Orchestration regression checks with synthetic model, evidence and renderer doubles."""
import copy
import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from delivery import deal_documents
from delivery.deal_documents import runs


class PageFirstPipelineTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)
        self.conn = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(self.conn.close)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.modules = {}
        for name in ('llm', 'compliance', 'deck_render', 'im', 'pages', 'readings', 'questions', 'decks', 'memo', 'review', 'climb', 'facts', 'ledger'):
            module = types.ModuleType('delivery.deal_documents.' + name)
            self.modules[name] = module
            self.stack.enter_context(patch.object(deal_documents, name, module, create=True))
        self.stack.enter_context(patch.dict(sys.modules, {module.__name__: module for module in self.modules.values()}))
        self.modules['llm'].ModelResponseError = type('ModelResponseError', (Exception,), {})
        self.modules['llm'].RecordedModel = object
        source = Path(__file__).resolve().parents[2] / 'delivery/deal_documents/pipeline.py'
        spec = importlib.util.spec_from_file_location('fast_pipeline_under_test', source)
        self.pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pipeline)
        self.calls, self.renders, self.gates = [], [], []
        self.written_keys = set()
        self.fail_audit = False
        self.plan = [self.page('company'), self.page('risks', grid=True), self.page('highlights', grid=True, schedule=True)]
        self.facts = {'facts': [], 'workbook_cells': [], 'checks': [], 'observations': []}
        (self.path / 'facts.json').write_text(json.dumps(self.facts))
        self.configure_stages()
        run = runs.create(self.conn, 'tenant', 'room', 'deal', 'Synthetic Co', self.path, 'local-model')
        runs.queue(self.conn, run, 'facts', 'operator')
        run, phase, token = runs.claim(self.conn)
        runs.Tracker(self.conn, run, phase, token, 'version').finish('needs_approval')
        runs.approve(self.conn, runs.get_by_id(self.conn, run['id']), 'facts', 'operator', {'by': 'operator'})
        runs.queue(self.conn, runs.get_by_id(self.conn, run['id']), 'memo', 'operator')
        self.run, phase, token = runs.claim(self.conn)
        self.tracker = runs.Tracker(self.conn, self.run, phase, token, 'version')

    @staticmethod
    def page(key, grid=False, schedule=False):
        return {'key': key, 'kind': 'grid' if grid else 'copy', 'brief': 'A supported investment question',
                'topics': [], 'cells': [], 'title': 'Evidence and its limits' if schedule else '',
                'takeaways': [], 'schedule': schedule,
                'exhibits': {'grid': {'header': ['Claim'], 'rows': [['Source-backed row']]}} if grid else {}}

    def configure_stages(self):
        m = self.modules
        m['facts'].numbers_in = lambda text: []
        m['ledger'].tie_out = lambda *args: {'baseline': {}, 'exceptions': [], 'occurrences': []}
        m['ledger'].audit_exports = lambda report, *args: {**report, 'exports': []}
        m['ledger'].markdown = lambda report: 'Numerical source ledger'
        m['ledger'].gate_section = lambda report: {'section': 'number_tie_out', 'title': 'Number tie-out', 'paragraphs': [],
                                                   'problems': [item['detail'] for item in report['exceptions']]}
        m['climb'].score_unit = lambda *args: {'overall': 88}
        m['climb'].better = lambda candidate, previous: not candidate['failures'] and (
            (candidate['problems'], candidate['issues']) < (previous['problems'], previous['issues']) or
            (candidate['problems'], candidate['issues']) == (previous['problems'], previous['issues']) and
            candidate['score']['overall'] >= previous['score']['overall'] + 3)
        m['decks'].tables_from_facts = lambda facts: {}
        m['readings'].build = lambda tables, index: {}
        m['readings'].lines = lambda results: []
        m['memo'].SECTIONS = []
        m['memo'].findings_summary = lambda facts: 'Reconciliation findings'
        m['questions'].candidates = lambda facts: []
        m['questions'].ask = lambda *args: []
        m['questions'].answer_facts = lambda questions: []
        m['questions'].readiness = lambda *args: {'score': 0}
        m['questions'].open_items_markdown = lambda *args: 'Open company questions'
        m['im'].VERSION, m['im'].AUDIT_VERSION = 'thesis-version', 'audit-version'
        def thesis(*args):
            self.calls.append('thesis')
            return {'merits': [], 'dropped': [], 'problems': []}
        m['im'].write_thesis = thesis
        m['im'].merit_lines = lambda *args: []
        m['im'].text_problems = lambda *args: []
        m['pages'].VERSION = 'pages-version'
        m['pages'].SECTIONS = {}
        m['pages'].build = lambda *args: copy.deepcopy(self.plan)
        m['pages'].demonstrations = lambda: []
        m['pages']._context = lambda *args: []
        m['pages']._exhibit_text = lambda page: '\n'.join(' '.join(row) for row in page['exhibits'].get('grid', {}).get('rows', []))
        m['pages'].baseline = lambda pages: {'generated': {'pages': len(pages)}}
        m['pages'].source_line = lambda *args: ''
        m['ledger'].observations = lambda facts: {}
        m['ledger'].canonical = lambda facts: facts
        m['ledger'].digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        def sections(pages):
            return [{'section': page['key'], 'title': page['title'] or page['brief'], 'problems': [],
                     'paragraphs': [{'text': line} for line in [page['title'], *page['takeaways']] if line]}
                    for page in pages]
        m['pages'].as_sections = sections
        def write(model, page, facts, *args, **kwargs):
            if self.written_keys and page['key'] not in self.written_keys:
                self.assertTrue((self.path / 'investment_memorandum.preview.pdf').exists())
            self.written_keys.add(page['key'])
            self.calls.append('write')
            return {**page, 'title': 'Evidence supports the investment question', 'takeaways': ['A bounded conclusion.'], 'problems': []}
        m['pages'].write_copy = write
        def audit(model, page, facts, rewrite, **kwargs):
            self.assertTrue(kwargs['full'])
            self.calls.append('audit')
            if self.fail_audit:
                raise m['llm'].ModelResponseError('audit unavailable')
            return {**page, 'audit': [], 'audit_noted': []}
        m['pages'].audit_copy = audit
        def render(company, notices, pages, *args):
            self.renders.append(copy.deepcopy(pages))
            return json.dumps(pages).encode()
        m['pages'].render = render
        m['deck_render'].to_pdf = lambda data: data
        m['review'].critic = lambda *args: ([], 'Page review complete')
        m['review'].compliance = lambda *args, **kwargs: ([], [])
        m['review'].known_numbers = lambda *args: []
        m['review'].fact_check = lambda *args: []
        m['review'].proposes_unknown_number = lambda *args: False
        m['review'].notes_for = lambda *args: ''
        m['compliance'].notices = lambda *args: [('Draft', 'Not for circulation')]
        def gate(sections, facts, areas, issues, **kwargs):
            self.gates.append(copy.deepcopy(sections))
            return {'blockers': ['evidence_and_labelling'] if any(section['problems'] for section in sections) else [],
                    'counsel_questions': [], 'checks': [], 'assessed_on': 'test'}
        m['compliance'].assess = gate
        m['compliance'].markdown = lambda *args: 'Gate results'

    def execute(self):
        self.pipeline.memo_phase(self.tracker, object(), self.run, None)

    def test_new_path_publishes_before_next_page_and_gates_all_page_copy(self):
        self.execute()
        self.assertEqual(self.calls.count('write'), 2)
        self.assertEqual(self.calls.count('audit'), 3)
        self.assertEqual(self.calls[0], 'thesis')
        self.assertTrue(any(page['takeaways'] == ['PENDING: page copy has not been written.'] for page in self.renders[0]))
        self.assertTrue(all(page['page_status'] == 'audited' for page in self.renders[-1]))
        text = json.dumps(self.gates[-1])
        self.assertIn('Source-backed row', text)
        self.assertIn('A bounded conclusion.', text)
        self.assertEqual({section['section'] for section in self.gates[-1]}, {'company', 'risks', 'highlights', 'number_tie_out'})
        self.assertTrue((self.path / 'source_ledger.json').exists())
        self.assertTrue((self.path / 'investment_memorandum.pdf').exists())

    def test_restart_reuses_each_page_without_repeating_writing_or_audits(self):
        self.execute()
        before = list(self.calls)
        self.execute()
        self.assertEqual(self.calls, before)
        self.assertEqual(len(self.gates), 2)

    def test_numerical_exception_blocks_the_gate(self):
        self.modules['ledger'].tie_out = lambda *args: {'baseline': {}, 'exceptions': [{'detail': 'Planted wrong figure'}], 'occurrences': []}
        self.execute()
        gate = json.loads((self.path / 'compliance.json').read_text())
        self.assertIn('evidence_and_labelling', gate['blockers'])
        self.assertIn('Planted wrong figure', json.dumps(self.gates[-1]))

    def test_source_review_changes_the_cache_inputs_without_changing_approved_facts(self):
        _, before = self.pipeline._fact_base(self.run)
        self.run['data']['baseline_choices'] = {'row': {'source_id': 'S.a', 'reason': 'Reviewed source choice'}}
        facts, after = self.pipeline._fact_base(self.run)
        self.assertNotEqual(before, after)
        self.assertEqual(facts['ledger_review']['selections'], self.run['data']['baseline_choices'])

    def test_a_failed_audit_is_visible_and_blocks_release_then_retries(self):
        self.fail_audit = True
        self.execute()
        gate = json.loads((self.path / 'compliance.json').read_text())
        self.assertIn('evidence_and_labelling', gate['blockers'])
        public = runs.public(runs.get_by_id(self.conn, self.run['id']))
        self.assertTrue(all(page['state'] == 'needs_review' for page in public['phases']['memo']['pages']))
        self.fail_audit = False
        self.execute()
        gate = json.loads((self.path / 'compliance.json').read_text())
        self.assertFalse(gate['blockers'])
        self.assertEqual(self.calls.count('write'), 2)
        self.assertEqual(self.calls.count('audit'), 6)

    def test_missing_path_does_not_enter_the_page_first_executor(self):
        legacy = copy.deepcopy(self.run)
        legacy['data'].pop('generation_path')
        marker = RuntimeError('entered unchanged prose path')
        with patch.object(self.pipeline, 'page_first_phase', side_effect=AssertionError('wrong path')):
            with patch.object(self.pipeline, '_fact_base', side_effect=marker):
                with self.assertRaisesRegex(RuntimeError, 'unchanged prose path'):
                    self.pipeline.memo_phase(self.tracker, object(), legacy, None)

    def test_rerun_preserves_previous_pdf_and_reports_page_changes(self):
        self.execute()
        original = (self.path / 'investment_memorandum.pdf').read_bytes()
        self.tracker.finish('needs_approval')
        runs.queue(self.conn, runs.get_by_id(self.conn, self.run['id']), 'memo', 'operator')
        self.run, phase, token = runs.claim(self.conn)
        self.tracker = runs.Tracker(self.conn, self.run, phase, token, 'version')
        self.plan[-1]['exhibits']['grid']['rows'] = [['Updated source-backed row']]
        self.execute()
        changes = runs.public(runs.get_by_id(self.conn, self.run['id']))['phases']['memo']['page_changes']
        self.assertEqual((self.path / 'superseded' / changes['previous'] / 'investment_memorandum.pdf').read_bytes(), original)
        self.assertIn('Updated source-backed row', changes['changes'][0]['diff'])

    def test_bad_revision_is_discarded_and_its_changes_remain_visible(self):
        self.modules['review'].notes_for = lambda key, *args: 'Correct the claim' if key == 'company' else ''
        original = self.modules['pages'].write_copy
        def write(model, page, facts, shots, profile, notes, **kwargs):
            candidate = original(model, page, facts, shots, profile, notes, **kwargs)
            return {**candidate, 'title': 'Rejected candidate', 'problems': ['unsupported']} if notes else candidate
        self.modules['pages'].write_copy = write
        self.execute()
        final = json.loads((self.path / 'pages.json').read_text())
        self.assertEqual(final[0]['title'], 'Evidence supports the investment question')
        phase = runs.public(runs.get_by_id(self.conn, self.run['id']))['phases']['memo']
        change = phase['rounds'][-1]['changes']['company']
        self.assertFalse(change['kept'])
        self.assertIn('+Rejected candidate', change['diff'])

    def test_model_retries_do_not_double_count_the_outer_call(self):
        class Model:
            def __init__(self, *args):
                pass
            def json(self, name, profile, *args, **kwargs):
                return self.json('retry', profile) if name == 'first' else {'ok': True}
        def execute(tracker, model, run, db_path):
            self.assertEqual(model.json('first', 'check'), {'ok': True})
        with patch.object(self.pipeline, 'RecordedModel', Model), patch.object(self.pipeline, 'memo_phase', execute):
            state = self.pipeline.run_phase(self.conn, self.run, 'memo', self.tracker.token)
        self.assertEqual(state, 'needs_approval')
        phase = runs.public(runs.get_by_id(self.conn, self.run['id']))['phases']['memo']
        self.assertEqual(phase['call_timings']['check']['samples'], 1)
        self.assertFalse(phase['active_calls'])

    def test_page_review_budget_changes_preserve_context_and_schema(self):
        self.modules['llm'].PROFILES = {'review': {'think': True, 'thinking_chars': 8000,
                                                   'options': {'num_ctx': 40960, 'num_predict': 8000}}}
        captured = []
        class Model:
            def __init__(self, *args):
                pass
            def json(self, name, profile, *args, **kwargs):
                captured.append((args, kwargs))
                return {'ok': True}
        schema = {'required': ['every_check']}
        def execute(tracker, model, run, db_path):
            model.json('page-compliance', 'review', 'system', 'evidence', schema)
        with patch.object(self.pipeline, 'RecordedModel', Model), patch.object(self.pipeline, 'memo_phase', execute):
            self.assertEqual(self.pipeline.run_phase(self.conn, self.run, 'memo', self.tracker.token), 'needs_approval')
        args, kwargs = captured[0]
        self.assertIs(args[-1], schema)
        self.assertEqual(kwargs['settings']['options']['num_ctx'], 40960)
        self.assertEqual(kwargs['settings']['options']['num_predict'], 4000)
        self.assertEqual(kwargs['settings']['thinking_chars'], 2400)

    def test_climb_streams_scores_and_keeps_diffs_for_discarded_candidates(self):
        source = Path(__file__).resolve().parents[2] / 'delivery/deal_documents/climb.py'
        spec = importlib.util.spec_from_file_location('fast_climb_under_test', source)
        climb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(climb)
        unit = {'title': 'Part', 'state': 'valid', 'headline': 'Original headline',
                'paragraphs': [{'kind': 'analysis', 'text': 'Original evidence.'}], 'version': 0}
        def assess(items, number):
            return [{'score': {'overall': [60, 80, 79][part['version']], 'criteria': {key: 3 for key in climb.CRITERIA},
                               'weakest': 'Original evidence.', 'change': 'Make the implication clear.'},
                     'problems': 0, 'issues': 0, 'found': [], 'failures': []} for _, part in items]
        def rewrite(items, number):
            return [{**part, 'version': number, 'headline': f'Revised headline {number}',
                     'paragraphs': [{'kind': 'analysis', 'text': f'Revised evidence {number}.'}]} for _, part, _ in items]
        observed = []
        best, assessed, history = climb.climb({'part': unit}, assess, rewrite, lambda *args: None, passes=5, on_round=observed.append)
        self.assertEqual(best['part']['version'], 1)
        self.assertEqual([item['round'] for item in observed], [0, 1, 2])
        self.assertEqual(history[-1]['scores']['part'], 80)
        self.assertEqual(history[-1]['changes']['part']['candidate_score'], 79)
        self.assertIn('+Revised headline 2', history[-1]['changes']['part']['diff'])

    def test_semantic_validation_removes_a_persistent_bad_line_and_blocks_release(self):
        self.modules['im'].text_problems = lambda text, *args: ['wrong period'] if text == 'A bounded conclusion.' else []
        self.execute()
        final = json.loads((self.path / 'pages.json').read_text())
        self.assertNotIn('A bounded conclusion.', json.dumps(final[0]['takeaways']))
        self.assertIn('wrong period', final[0]['problems'])
        self.assertIn('evidence_and_labelling', json.loads((self.path / 'compliance.json').read_text())['blockers'])


if __name__ == '__main__':
    unittest.main()
