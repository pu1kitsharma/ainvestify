"""Synthetic diligence scenarios; core guarantees also run without app dependencies."""
import datetime
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from delivery.deal_documents import diligence as D, runs


class Selector:
    def __init__(self, parts):
        self.parts = parts
        self.calls = []

    def json(self, *args):
        self.calls.append(args)
        return {'parts': self.parts, 'invented_prose': 'Invented amount 99999'}


class DiligenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.base = {'facts': [self.fact('f1', 'Revenue is 18 credits.', '18')],
                     'workbook_cells': [], 'checks': [], 'observations': []}
        self.write_base()
        self.run = runs.create(self.conn, 'tenant', 'room', 'deal', 'Synthetic issuer', self.path, 'local-model')
        self.approve_facts()

    @staticmethod
    def fact(key, statement, value):
        return {'id': key, 'document': 'Source record', 'location': 'page 1', 'statement': statement,
                'metric': 'Revenue', 'period': 'FY2025', 'basis': 'historical', 'entity': 'entity-A',
                'unit': 'credits', 'value': value, 'segment': '', 'case': '', 'ambiguity': ''}

    def write_base(self):
        (self.path / 'facts.json').write_text(json.dumps(self.base), encoding='utf-8')

    def refresh(self):
        self.run = runs.get(self.conn, 'tenant', 'room')

    def approve_facts(self):
        runs.update(self.conn, self.run['id'], lambda data: data['phases']['facts'].update({
            'state': 'approved', 'approvals': {'operator': {'by': 'reviewer', 'sha256': runs.output_sha(self.path, 'facts')}}}))
        self.refresh()

    def catalog(self, scope=''):
        return D.evidence(self.conn, 'tenant', 'room', self.run, scope)

    def links(self):
        return [{'evidence_id': e['evidence_id'], 'evidence_version': e['evidence_version']} for e in self.catalog()]

    def request(self, **overrides):
        body = dict(issue='Reconcile revenue', required_record='Reconciliation schedule', rationale='Review basis',
                    owner='associate', priority='blocker', status='open', origin='requirement',
                    due_date='2025-02-01', blocks=['financials'], accepted_evidence=[], acceptance_note='')
        return {**body, **overrides}

    def draft(self, model=None, scope='', parts=None):
        return D.draft_answer(self.conn, 'tenant', 'room', self.run, 'associate', scope,
            parts or [{'question': 'What is revenue?', 'required_record': 'Revenue schedule'}], model or Selector([['f1']]))

    def event(self, **overrides):
        body = dict(counterparty='party-A', stage='meeting', state='occurred', date='2025-01-02',
                    owner='associate', next_action='Review response', next_date='2025-01-04', evidence=self.links(),
                    review_note='Reviewed supplied dated meeting record.', artifact=None)
        return {**body, **overrides}

    def test_tenant_room_and_history_isolation(self):
        first = D.put_request(self.conn, 'tenant', 'room', 'associate', self.request(), 'same')
        D.put_request(self.conn, 'other', 'room', 'other-owner', self.request(issue='Other tenant'), 'same')
        self.assertEqual(len(D.records(self.conn, 'tenant', 'room', 'request')), 1)
        self.assertEqual(D.records(self.conn, 'tenant', 'other-room', 'request', True), [])
        with self.assertRaises(ValueError):
            D.evidence(self.conn, 'other', 'room', self.run)
        D.put_request(self.conn, 'tenant', 'room', 'reviewer', self.request(owner='reviewer'), 'same', first['version'])
        history = D.records(self.conn, 'tenant', 'room', 'request', True)
        self.assertEqual([r['owner'] for r in history], ['associate', 'reviewer'])
        self.assertEqual(D.records(self.conn, 'other', 'room', 'request')[0]['issue'], 'Other tenant')

    def test_update_requires_current_revision_and_actor(self):
        D.put_request(self.conn, 'tenant', 'room', 'associate', self.request(), 'r')
        with self.assertRaisesRegex(ValueError, 'refresh'):
            D.put_request(self.conn, 'tenant', 'room', 'associate', self.request(), 'r', 0)
        with self.assertRaisesRegex(ValueError, 'actor'):
            D.put_request(self.conn, 'tenant', 'room', ' ', self.request())

    def test_missing_is_not_resolution_and_no_guessed_date(self):
        request = D.put_request(self.conn, 'tenant', 'room', 'associate', self.request(due_date=None))
        self.assertIsNone(request['due_date'])
        for change in ({}, {'acceptance_note': 'Accepted'}, {'accepted_evidence': self.links()}):
            with self.assertRaises(ValueError):
                D.put_request(self.conn, 'tenant', 'room', 'reviewer', self.request(status='resolved', **change))
        with self.assertRaises(ValueError):
            D.put_request(self.conn, 'tenant', 'room', 'reviewer', self.request(due_date='not a date'))

    def test_resolution_reopens_immediately_when_evidence_changes(self):
        request = D.put_request(self.conn, 'tenant', 'room', 'reviewer',
            self.request(status='resolved', accepted_evidence=self.links(), acceptance_note='Reviewed schedule reconciles.'))
        self.assertEqual(D.request_view(self.conn, 'tenant', 'room', self.run)[0]['status'], 'resolved')
        self.base['facts'][0]['value'] = '19'
        self.write_base()
        self.assertEqual(D.request_view(self.conn, 'tenant', 'room', self.run)[0]['status'], 'open')
        self.assertEqual(D.records(self.conn, 'tenant', 'room', 'request')[0]['status'], 'resolved')
        tracker = D.process_view(self.conn, 'tenant', 'room', self.run, today=datetime.date(2025, 2, 2))
        self.assertEqual(tracker['blockers'][0]['id'], request['id'])
        self.assertTrue(tracker['deadlines'][0]['overdue'])

    def test_scoped_retrieval_requires_explicit_current_grant(self):
        self.assertFalse(self.catalog('party-A'))
        item = self.catalog()[0]
        D.grant(self.conn, 'tenant', 'room', self.run, 'reviewer', 'party-A', item['evidence_id'], item['evidence_version'])
        self.assertEqual(len(self.catalog('party-A')), 1)
        self.assertFalse(self.catalog('party-B'))
        self.base['facts'][0]['statement'] = 'Revenue is 19 credits.'
        self.write_base()
        self.approve_facts()
        self.assertFalse(self.catalog('party-A'))

    def test_revocation_invalidates_answer_and_can_be_reversed(self):
        answer = self.draft()
        item = self.catalog()[0]
        D.grant(self.conn, 'tenant', 'room', self.run, 'reviewer', '', item['evidence_id'], item['evidence_version'], False)
        self.assertEqual(D.answer_view(self.conn, 'tenant', 'room', self.run)[0]['status'], 'stale')
        with self.assertRaises(ValueError):
            D.approve_answer(self.conn, 'tenant', 'room', self.run, 'reviewer', answer['id'], 1, 'Reviewed')
        D.grant(self.conn, 'tenant', 'room', self.run, 'reviewer', '', item['evidence_id'], item['evidence_version'])
        self.assertEqual(len(self.catalog()), 1)

    def test_company_statement_retains_author_date_and_qualifiers(self):
        response = {'text': 'Respondent may support one quarter, subject to approval; no commitment.', 'by': 'respondent-A', 'at': 12345}
        runs.update(self.conn, self.run['id'], lambda data: data.update(questions=[{'id': 'q1', 'text': 'Support?', 'answer': response}]))
        self.refresh()
        self.assertEqual(len(self.catalog()), 1)
        candidate = D.evidence(self.conn, 'tenant', 'room', self.run, include_unapproved_statements=True)[1]
        self.assertFalse(candidate['approved_for_scope'])
        D.grant(self.conn, 'tenant', 'room', self.run, 'reviewer', '', candidate['evidence_id'], candidate['evidence_version'])
        answer = self.draft(Selector([['answer:q1']]), parts=[{'question': 'What support may respondent offer?', 'required_record': 'Support letter'}])
        self.assertEqual(answer['claims'][0]['text'], response['text'])
        self.assertEqual(answer['claims'][0]['attribution'], 'respondent-A')
        self.assertEqual(answer['claims'][0]['context']['response_at'], 12345)
        self.assertFalse(answer['evidence'][0]['verified'])

    def test_model_cannot_write_claims_or_numbers_and_approval_is_immutable(self):
        answer = self.draft()
        self.assertEqual(answer['claims'][0]['text'], 'Revenue is 18 credits.')
        self.assertNotIn('99999', json.dumps(answer))
        self.assertEqual(answer['status'], 'draft')
        approved = D.approve_answer(self.conn, 'tenant', 'room', self.run, 'reviewer', answer['id'], 1, 'Reviewed every part')
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(approved['approved_revision'], 1)
        self.assertEqual([a['status'] for a in D.records(self.conn, 'tenant', 'room', 'answer', True)], ['draft', 'approved'])

    def test_unknown_or_malformed_selections_abstain_and_file_requests(self):
        for selection in ([['unknown']], [[{'bad': 1}]], ['f1'], [[]]):
            answer = self.draft(Selector(selection))
            self.assertEqual(answer['status'], 'input_needed')
            self.assertFalse(answer['claims'])
        self.assertEqual(len(D.records(self.conn, 'tenant', 'room', 'request')), 1)
        request = D.records(self.conn, 'tenant', 'room', 'request')[0]
        self.assertEqual(request['required_record'], 'Revenue schedule')
        with self.assertRaises(ValueError):
            D.approve_answer(self.conn, 'tenant', 'room', self.run, 'reviewer', answer['id'], 1, 'Reviewed')

    def test_partial_answer_keeps_missing_parts_open(self):
        answer = self.draft(Selector([['f1'], []]), parts=[
            {'question': 'Revenue?', 'required_record': 'Revenue schedule'},
            {'question': 'Signed financing?', 'required_record': 'Executed financing agreement'}])
        self.assertEqual(len(answer['claims']), 1)
        self.assertEqual(answer['status'], 'input_needed')
        self.assertEqual(answer['residual'][0]['required_record'], 'Executed financing agreement')

    def test_missing_scope_never_reaches_model_and_never_implies_no_debt(self):
        model = Selector([['f1']])
        answer = self.draft(model, 'party-B', [{'question': 'Is there debt?', 'required_record': 'Debt register'}])
        self.assertFalse(model.calls)
        self.assertEqual(answer['status'], 'input_needed')
        self.assertEqual(answer['claims'], [])
        self.assertEqual(answer['residual'][0]['required_record'], 'Debt register')

    def test_conflicting_variants_are_visible_even_if_model_omits_one(self):
        self.base['facts'].append(self.fact('f2', 'Revenue is 23 credits.', '23'))
        self.write_base()
        self.approve_facts()
        answer = self.draft(Selector([['f1']]))
        self.assertEqual({e['evidence_id'] for e in answer['conflicts'][0]}, {'f1', 'f2'})
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            D.approve_answer(self.conn, 'tenant', 'room', self.run, 'reviewer', answer['id'], 1, 'Reviewed')
        D.approve_answer(self.conn, 'tenant', 'room', self.run, 'reviewer', answer['id'], 1, 'Both versions remain disputed', True)

    def test_qualitative_conflicts_do_not_disappear_when_value_is_blank(self):
        self.base['facts'] = [self.fact('f1', 'Support is conditional on approval.', ''),
                              self.fact('f2', 'Support has been declined.', '')]
        for fact in self.base['facts']:
            fact['metric'] = 'Support status'
        self.write_base()
        self.approve_facts()
        answer = self.draft(parts=[{'question': 'What is support status?', 'required_record': 'Support record'}])
        self.assertEqual(len(answer['conflicts'][0]), 2)

    def test_conflict_outside_scope_is_not_leaked(self):
        self.base['facts'].append(self.fact('private', 'Revenue is 23 credits.', '23'))
        self.write_base()
        self.approve_facts()
        item = self.catalog()[0]
        D.grant(self.conn, 'tenant', 'room', self.run, 'reviewer', 'party-A', item['evidence_id'], item['evidence_version'])
        model = Selector([['f1']])
        answer = self.draft(model, 'party-A')
        self.assertFalse(answer['conflicts'])
        self.assertNotIn('23 credits', model.calls[0][3])

    def test_new_conflicting_evidence_invalidates_an_existing_approval(self):
        answer = self.draft()
        D.approve_answer(self.conn, 'tenant', 'room', self.run, 'reviewer', answer['id'], 1, 'Reviewed')
        self.base['facts'].append(self.fact('f2', 'Revenue is 23 credits.', '23'))
        self.write_base()
        self.approve_facts()
        self.assertEqual(D.answer_view(self.conn, 'tenant', 'room', self.run)[0]['status'], 'stale')

    def test_new_accessible_statement_invalidates_previous_answer_context(self):
        response = {'text': 'Revenue differs from the schedule.', 'by': 'management', 'at': 12345}
        runs.update(self.conn, self.run['id'], lambda data: data.update(questions=[{'id': 'q1', 'text': 'Revenue?', 'answer': response}]))
        self.refresh()
        answer = self.draft()
        candidate = D.evidence(self.conn, 'tenant', 'room', self.run, include_unapproved_statements=True)[1]
        D.grant(self.conn, 'tenant', 'room', self.run, 'reviewer', '', candidate['evidence_id'], candidate['evidence_version'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            D.approve_answer(self.conn, 'tenant', 'room', self.run, 'reviewer', answer['id'], 1, 'Reviewed')
        self.assertEqual(D.answer_view(self.conn, 'tenant', 'room', self.run)[0]['status'], 'stale')

    def test_selector_failure_still_creates_an_input_request(self):
        class Unavailable:
            def json(self, *args):
                raise RuntimeError('Local model unavailable')
        answer = self.draft(Unavailable())
        self.assertEqual(answer['status'], 'input_needed')
        self.assertIn('unavailable', answer['failure'])
        self.assertEqual(len(answer['request_ids']), 1)

    def test_blank_approval_is_rejected(self):
        answer = self.draft()
        with self.assertRaisesRegex(ValueError, 'acceptance'):
            D.approve_answer(self.conn, 'tenant', 'room', self.run, 'reviewer', answer['id'], 1, '  ')

    def test_stale_event_can_be_cancelled_without_reapproving_its_old_artifact(self):
        artifact = {'phase': 'facts', 'sha256': runs.output_sha(self.path, 'facts')}
        body = self.event(stage='materials_reviewed', artifact=artifact)
        event = D.put_event(self.conn, 'tenant', 'room', self.run, 'reviewer', body)
        self.base['facts'].append(self.fact('f2', 'Other revenue schedule.', '24'))
        self.write_base()
        D.put_event(self.conn, 'tenant', 'room', self.run, 'reviewer', {**body, 'state': 'cancelled'}, event['id'], 1)
        self.assertFalse(D.process_view(self.conn, 'tenant', 'room', self.run)['deadlines'])

    def test_register_preserves_uncapped_findings_and_deduplicates_linked_questions(self):
        # The upstream collector is a boundary; this test exercises the register's
        # retention and merge rules with more findings than its compact UI shows.
        upstream = ModuleType('delivery.deal_documents.questions')
        upstream.candidates = lambda base: [dict(id=f'F{i}', text=f'Entity A period {i}: reconcile records',
            severity='high', basis='calculation', facts=[]) for i in range(25)]
        runs.update(self.conn, self.run['id'], lambda data: data.update(questions=[{
            'id': 'q1', 'text': 'A merged question', 'why': 'Reconcile', 'severity': 'blocker', 'sections': ['financials'],
            'sources': ['F1'], 'answer': {'text': 'Company response', 'by': 'management', 'at': 123}}]))
        self.refresh()
        (self.path / 'baseline.json').write_text(json.dumps({'missing': {'funding_plan': 'Dated cash schedule'}}))
        with patch.dict(sys.modules, {upstream.__name__: upstream}):
            result = D.sync_requests(self.conn, 'tenant', 'room', self.run, 'worker')
            self.assertEqual(len(result), 26)
            matched = next(r for r in result if 'period 1:' in r['issue'])
            self.assertEqual(matched['priority'], 'blocker')
            self.assertEqual(matched['management_response']['by'], 'management')
            self.assertEqual(matched['status'], 'open')
            count = len(D.records(self.conn, 'tenant', 'room', 'request', True))
            D.sync_requests(self.conn, 'tenant', 'room', self.run, 'worker')
            self.assertEqual(len(D.records(self.conn, 'tenant', 'room', 'request', True)), count)
            self.assertEqual(len(D.records(self.conn, 'tenant', 'other-room', 'request')), 0)

    def test_duplicate_findings_do_not_fail_during_source_updates(self):
        upstream = ModuleType('delivery.deal_documents.questions')
        upstream.candidates = lambda base: [dict(id=f'F{i}', text='Period A: reconcile records',
            severity='high', basis='calculation', facts=[]) for i in range(2)]
        with patch.dict(sys.modules, {upstream.__name__: upstream}):
            D.sync_requests(self.conn, 'tenant', 'room', self.run, 'worker')
            self.assertEqual(len(D.records(self.conn, 'tenant', 'room', 'request')), 1)
            self.base['facts'][0]['statement'] = 'Updated period A source'
            self.write_base()
            D.sync_requests(self.conn, 'tenant', 'room', self.run, 'worker')
            self.assertEqual(len(D.records(self.conn, 'tenant', 'room', 'request', True)), 2)

    def test_unapproved_ambiguous_and_error_evidence_are_ineligible(self):
        for flag in ('ocr_only', 'cell_error', 'ambiguity'):
            self.base['facts'][0][flag] = True
            self.write_base()
            self.approve_facts()
            self.assertFalse(self.catalog())
            self.base['facts'][0].pop(flag)
        self.write_base()
        self.assertFalse(self.catalog())

    def test_sale_and_debt_trackers_do_not_infer_milestones_from_labels(self):
        investors = [{'id': 'party-A', 'investor_name': 'Synthetic counterparty', 'interest_level': 'committed', 'nda_status': 'signed'}]
        for purpose in ('sell_side_advisory', 'debt_advisory'):
            view = D.process_view(self.conn, 'tenant', 'room', self.run, investors, {'purpose': purpose}, datetime.date(2025, 1, 5))
            self.assertEqual(view['counterparties'][0]['stage'], 'unconfirmed')
        D.put_event(self.conn, 'tenant', 'room', self.run, 'associate', self.event(state='planned', evidence=[]))
        view = D.process_view(self.conn, 'tenant', 'room', self.run, investors, today=datetime.date(2025, 1, 5))
        self.assertEqual(view['counterparties'][0]['stage'], 'unconfirmed')
        self.assertTrue(all(d['overdue'] for d in view['deadlines']))
        self.assertEqual(view['deadlines'][0]['owner'], 'associate')

    def test_milestone_requires_evidence_and_sequence_and_current_version(self):
        for stage in ('nda_executed', 'binding_commitment', 'closed'):
            with self.assertRaises(ValueError):
                D.put_event(self.conn, 'tenant', 'room', self.run, 'associate', self.event(stage=stage, evidence=[]))
        D.put_event(self.conn, 'tenant', 'room', self.run, 'associate', self.event())
        with self.assertRaisesRegex(ValueError, 'sequence'):
            D.put_event(self.conn, 'tenant', 'room', self.run, 'associate', self.event(stage='nda_executed', date='2025-01-03'))
        view = D.process_view(self.conn, 'tenant', 'room', self.run)
        self.assertEqual(view['counterparties'][0]['stage'], 'meeting')
        self.base['facts'][0]['statement'] = 'Updated source record'
        self.write_base()
        view = D.process_view(self.conn, 'tenant', 'room', self.run)
        self.assertEqual(view['counterparties'][0]['stage'], 'unconfirmed')
        self.assertFalse(view['counterparties'][0]['timeline'][0]['current'])

    def test_future_events_next_action_dates_and_review_note_are_checked(self):
        for change in ({'date': '2999-01-01', 'next_date': None}, {'next_date': '2024-01-01'}, {'date': '20250102'}, {'review_note': ''}, {'next_action': ''}):
            with self.assertRaises(ValueError):
                D.put_event(self.conn, 'tenant', 'room', self.run, 'associate', self.event(**change))

    def test_approved_reassurance_does_not_establish_committed_funding(self):
        response = {'text': 'We may provide support, subject to approval.', 'by': 'respondent-A', 'at': 12345}
        runs.update(self.conn, self.run['id'], lambda data: data.update(questions=[{'id': 'q1', 'text': 'Support?', 'answer': response}]))
        self.refresh()
        candidate = D.evidence(self.conn, 'tenant', 'room', self.run, include_unapproved_statements=True)[1]
        D.grant(self.conn, 'tenant', 'room', self.run, 'reviewer', '', candidate['evidence_id'], candidate['evidence_version'])
        links = [{'evidence_id': candidate['evidence_id'], 'evidence_version': candidate['evidence_version']}]
        with self.assertRaisesRegex(ValueError, 'supplied records'):
            D.put_event(self.conn, 'tenant', 'room', self.run, 'reviewer', self.event(stage='binding_commitment', evidence=links))

    def test_materials_milestone_requires_exact_approved_draft(self):
        with self.assertRaisesRegex(ValueError, 'exact approved'):
            D.put_event(self.conn, 'tenant', 'room', self.run, 'associate', self.event(stage='materials_reviewed'))
        artifact = {'phase': 'facts', 'sha256': runs.output_sha(self.path, 'facts')}
        event = D.put_event(self.conn, 'tenant', 'room', self.run, 'reviewer', self.event(stage='materials_reviewed', artifact=artifact))
        view = D.process_view(self.conn, 'tenant', 'room', self.run)
        self.assertEqual(view['counterparties'][0]['timeline'][0]['artifact'], artifact)
        with self.assertRaises(ValueError):
            D.put_event(self.conn, 'tenant', 'room', self.run, 'reviewer', self.event(artifact={'phase': 'facts', 'sha256': '0' * 64}))
        D.put_event(self.conn, 'tenant', 'room', self.run, 'reviewer', self.event(state='cancelled'), event['id'], event['version'])
        self.assertEqual(D.process_view(self.conn, 'tenant', 'room', self.run)['counterparties'][0]['stage'], 'unconfirmed')


    @unittest.skipUnless(all(importlib.util.find_spec(m) for m in ('ollama', 'pdfplumber', 'pydantic')), 'application dependencies absent')
    def test_uncapped_findings_missing_inputs_and_answers_sync_without_false_resolution(self):
        self.base['checks'] = [dict(question=f'Period {i}: reconcile total', status='inconsistent',
            left_value=i + 10, right_value=i + 11, difference_pct=5, left_expression=f'f{i}', right_expression=f'g{i}') for i in range(20)]
        self.write_base()
        (self.path / 'baseline.json').write_text(json.dumps({'missing': {'funding_plan': 'Dated cash schedule'}}))
        runs.update(self.conn, self.run['id'], lambda data: data.update(questions=[{
            'id': 'q1', 'text': 'Provide forecast assumptions', 'why': 'Review assumptions', 'severity': 'high', 'sections': ['forecast'],
            'answer': {'text': 'Management supplied a response', 'by': 'management', 'at': 123}}]))
        self.refresh()
        requests = D.sync_requests(self.conn, 'tenant', 'room', self.run, 'reviewer')
        self.assertEqual(sum(r.get('basis') == 'calculation' for r in requests), 20)
        self.assertTrue(any(r['issue'] == 'Dated cash schedule' for r in requests))
        self.assertTrue(any(r.get('management_response') for r in requests))
        self.assertTrue(all(r['status'] == 'open' for r in requests))
        history = D.records(self.conn, 'tenant', 'room', 'request', True)
        D.sync_requests(self.conn, 'tenant', 'room', self.run, 'reviewer')
        self.assertEqual(history, D.records(self.conn, 'tenant', 'room', 'request', True))


if __name__ == '__main__':
    unittest.main()
