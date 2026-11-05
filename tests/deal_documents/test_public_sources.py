"""Synthetic public publishers; no sockets, models or company-specific fixtures."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from delivery.deal_documents import public_sources as P


SITE = 'https://issuer.example/'
DOC = SITE + 'report.pdf'
ROBOTS = (200, {'Content-Type': 'text/plain'}, b'User-agent: *\nAllow: /\n')
PDF = b'%PDF-1.4\nsynthetic fixture\n%%EOF'


class PublicSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.calls = []
        self.responses = {SITE + 'robots.txt': ROBOTS, DOC: (200, {'Content-Type': 'application/pdf'}, PDF)}
        self.policy = P.Policy('Synthetic Issuer', SITE, terms_reviewed_hosts=('issuer.example',))
        self.env = patch.dict(os.environ, {'RESEARCH_AGENT_CONTACT': 'Synthetic research analyst@operator.example'})
        self.env.start()
        self.addCleanup(self.env.stop)
        sleep_patch = patch.object(P.time, 'sleep')
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def fetch(self, url, address, user_agent, limit, deadline):
        self.calls.append((url, address, user_agent, limit))
        return self.responses[url]

    def collect(self, urls=(DOC,), **kwargs):
        return P.collect(kwargs.pop('policy', self.policy), self.root / 'archive', urls,
                         fetcher=self.fetch, resolver=kwargs.pop('resolver', lambda url: ['93.184.216.34']), **kwargs)

    def test_manifest_exact_bytes_and_identifying_user_agent(self):
        result = self.collect()
        record = result['documents'][0]
        self.assertEqual(record['source_url'], DOC)
        self.assertEqual(record['url'], DOC)
        self.assertEqual(record['publisher'], 'Synthetic Issuer')
        self.assertEqual(record['sha256'], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(record['size_bytes'], len(PDF))
        self.assertEqual(record['type'], 'pdf')
        self.assertTrue(record['retrieved_at'].endswith('+00:00'))
        self.assertEqual((self.root / 'archive' / record['filename']).read_bytes(), PDF)
        self.assertEqual(json.loads((self.root / 'archive/manifest.json').read_text()), result)
        self.assertEqual([call[0] for call in self.calls], [SITE + 'robots.txt', DOC])
        self.assertIn('analyst@operator.example', self.calls[0][2])
        self.assertEqual(self.calls[0][1], '93.184.216.34')

    def test_local_download_keeps_bytes_publisher_time_and_public_notice_without_network(self):
        source = self.root / 'download.pdf'
        source.write_bytes(PDF)
        os.utime(source, (1700000000, 1700000000))
        policy = P.Policy('Synthetic Issuer', SITE)
        with patch.dict(os.environ, {'RESEARCH_AGENT_CONTACT': ''}), \
                patch.object(P, 'Collector', side_effect=AssertionError('No crawler for local files')), \
                patch.object(P, '_request', side_effect=AssertionError('No HTTP')), \
                patch.object(P.socket, 'getaddrinfo', side_effect=AssertionError('No DNS')):
            result = self.collect((), policy=policy, local_files=[(source, DOC)])
        self.assertFalse(result['errors'])
        record = result['documents'][0]
        self.assertEqual(record['source_url'], DOC)
        self.assertEqual(record['url'], DOC)
        self.assertEqual(record['publisher'], policy.company)
        self.assertEqual(record['retrieved_at'], datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat())
        self.assertTrue(record['collected_by_person'])
        self.assertEqual(record['sha256'], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(record['size_bytes'], len(PDF))
        self.assertEqual(record['type'], 'pdf')
        self.assertEqual(record['media_type'], 'application/pdf')
        self.assertEqual(record['notice'], P.PUBLIC_NOTICE)
        self.assertEqual(result['notice'], P.PUBLIC_NOTICE)
        self.assertEqual(result['terms_reviewed_hosts'], [])
        self.assertEqual((self.root / 'archive' / record['filename']).read_bytes(), PDF)
        self.assertEqual(source.read_bytes(), PDF)
        self.assertEqual(json.loads((self.root / 'archive/manifest.json').read_text()), result)
        self.assertFalse(self.calls)

    def test_local_download_accepts_configured_publishers_without_terms_review(self):
        source = self.root / 'download.pdf'
        source.write_bytes(PDF)
        policy = P.Policy('Synthetic Issuer', SITE, publishers={'filings.example': 'Synthetic Publisher'})
        result = self.collect((), policy=policy, local_files=[(source, 'https://filings.example/download?id=1')])
        self.assertFalse(result['errors'])
        self.assertEqual(result['documents'][0]['publisher'], 'Synthetic Publisher')
        self.assertFalse(self.calls)

    def test_local_source_host_policy_is_enforced_before_reading(self):
        source = self.root / 'download.pdf'
        policy = P.Policy('Synthetic Issuer', SITE, publishers={'filings.example': 'Synthetic Publisher'})
        for index, host in enumerate(['other.example', 'issuer.example.other.example', 'unlisted.filings.example']):
            with self.subTest(host=host), patch.object(P, '_read_local', side_effect=AssertionError('Untrusted host')):
                result = P.collect(policy, self.root / f'archive-{index}',
                                   local_files=[(source, f'https://{host}/report.pdf')])
            self.assertFalse(result['documents'])
            self.assertIn('outside the official domain', result['errors'][0]['error'])
        self.assertFalse(self.calls)

    def test_local_official_subdomains_do_not_require_terms_review(self):
        source = self.root / 'download.pdf'
        source.write_bytes(PDF)
        result = self.collect((), policy=P.Policy('Synthetic Issuer', SITE),
                              local_files=[(source, 'https://public.issuer.example/report.pdf')])
        self.assertFalse(result['errors'])
        self.assertEqual(result['documents'][0]['publisher'], 'Synthetic Issuer')
        self.assertFalse(self.calls)

    def test_local_files_share_type_signature_and_size_checks(self):
        cases = [('download.pdf', b'<html>Login</html>', DOC, 'declared file type'),
                 ('download.pdf', b'', DOC, 'declared file type'),
                 ('download.txt', PDF, DOC, 'Only PDF'),
                 ('download.xlsx', PDF, SITE + 'book.xlsx', 'declared file type'),
                 ('download.pdf', PDF, SITE + 'book.xlsx', 'Only PDF'),
                 ('large.pdf', PDF + b'x' * 200, DOC, 'byte limit')]
        policy = P.Policy('Synthetic Issuer', SITE, max_bytes=100)
        for index, (name, body, url, error) in enumerate(cases):
            with self.subTest(name=name, error=error):
                source = self.root / name
                source.write_bytes(body)
                result = P.collect(policy, self.root / f'archive-{index}', local_files=[(source, url)])
                self.assertFalse(result['documents'])
                self.assertIn(error, result['errors'][0]['error'])
                self.assertEqual(list((self.root / f'archive-{index}').iterdir()),
                                 [self.root / f'archive-{index}' / 'manifest.json'])

    def test_local_spreadsheets_use_the_same_supported_types(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as book:
            book.writestr('fixture.txt', 'Package validation belongs to the upload parser')
        for index, suffix in enumerate(['.xlsx', '.xlsm']):
            source = self.root / ('download' + suffix)
            source.write_bytes(buffer.getvalue())
            result = P.collect(P.Policy('Synthetic Issuer', SITE), self.root / f'archive-{index}',
                               local_files=[(source, SITE + 'download?id=1')])
            self.assertFalse(result['errors'])
            self.assertEqual(result['documents'][0]['type'], suffix[1:])
            self.assertEqual(result['documents'][0]['media_type'], P.TYPES[suffix])

    def test_missing_or_non_file_local_inputs_leave_a_partial_manifest(self):
        directory = self.root / 'directory.pdf'
        directory.mkdir()
        valid = self.root / 'download.pdf'
        valid.write_bytes(PDF)
        result = self.collect((), local_files=[(self.root / 'missing.pdf', DOC), (directory, DOC), (valid, DOC)])
        self.assertEqual(len(result['errors']), 2)
        self.assertEqual(len(result['documents']), 1)
        self.assertFalse(self.calls)

    def test_local_and_fetched_files_share_count_total_and_deduplication_limits(self):
        source = self.root / 'download.pdf'
        source.write_bytes(PDF)
        self.policy.max_documents = 1
        with self.assertRaisesRegex(ValueError, 'count limit'):
            self.collect(local_files=[(source, DOC)])
        self.assertFalse((self.root / 'archive').exists())
        self.policy.max_documents = 3
        result = self.collect(local_files=[(source, DOC)])
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['documents']), 1)
        self.assertFalse(result['documents'][0]['collected_by_person'])
        policy = P.Policy('Synthetic Issuer', SITE, max_total_bytes=len(PDF))
        with patch.object(P, '_read_local', wraps=P._read_local) as read:
            result = P.collect(policy, self.root / 'limited-archive', local_files=[(source, DOC), (source, DOC)])
        self.assertEqual(len(result['documents']), 1)
        self.assertIn('Total public', result['errors'][0]['error'])
        self.assertEqual(read.call_count, 1)

    def test_local_inputs_do_not_exempt_automated_hosts_from_terms_review(self):
        source = self.root / 'download.pdf'
        source.write_bytes(PDF)
        result = self.collect(policy=P.Policy('Synthetic Issuer', SITE), local_files=[(source, DOC)])
        self.assertEqual(len(result['documents']), 1)
        self.assertTrue(result['documents'][0]['collected_by_person'])
        self.assertIn('review public access and terms', result['errors'][0]['error'])
        self.assertFalse(self.calls)

    def test_robots_disallow_and_unavailable_fail_closed(self):
        collector = P.Collector(self.policy, fetcher=self.fetch, resolver=lambda url: ['93.184.216.34'])
        for response in [(200, {'Content-Type': 'text/plain'}, b'User-agent: *\nDisallow: /\n'),
                         (403, {}, b''), (429, {}, b''), (503, {}, b''),
                         (200, {'Content-Type': 'text/html'}, b'<html>Sign in</html>')]:
            with self.subTest(response=response):
                self.responses[SITE + 'robots.txt'] = response
                collector.robots.clear()
                with self.assertRaises(ValueError):
                    collector.fetch(DOC, 10000)
        self.assertNotIn(DOC, [call[0] for call in self.calls])

    def test_missing_robots_is_allowed_and_delay_is_observed(self):
        self.responses[SITE + 'robots.txt'] = (404, {}, b'')
        self.assertEqual(len(self.collect()['documents']), 1)
        self.sleep.assert_called()

    def test_large_crawl_delay_abstains(self):
        self.responses[SITE + 'robots.txt'] = (200, {'Content-Type': 'text/plain'},
            b'User-agent: *\nCrawl-delay: 90\nAllow: /\n')
        result = self.collect()
        self.assertFalse(result['documents'])
        self.assertIn('rate limit', result['errors'][0]['error'])

    def test_private_and_mixed_dns_never_reach_fetcher(self):
        collector = P.Collector(self.policy, fetcher=self.fetch,
                                resolver=lambda url: ['93.184.216.34', '127.0.0.1'])
        with self.assertRaises(ValueError):
            collector.fetch(DOC, 1000)
        self.assertFalse(self.calls)
        for address in ['10.1.2.3', '192.168.0.2', '169.254.169.254', '::1', 'fc00::1', '224.0.0.1']:
            with self.subTest(address=address):
                collector.resolver = lambda url: [address]
                with self.assertRaises(ValueError):
                    collector.fetch(DOC, 1000)

    def test_dns_rebinding_is_checked_after_robots(self):
        answers = iter([['93.184.216.34'], ['127.0.0.1']])
        result = self.collect(resolver=lambda url: next(answers))
        self.assertFalse(result['documents'])
        self.assertEqual(len(self.calls), 1)

    def test_url_credentials_ports_and_private_literals_are_refused(self):
        for url in ['file:///a.pdf', 'https://user:secret@issuer.example/a.pdf',
                    'https://issuer.example:22/a.pdf', 'https://127.0.0.1/a.pdf',
                    'https://[::1]/a.pdf', 'https://issuer.example\\@other.example/a.pdf',
                    'https://issuer.example/\r\nHost:x', 'https://issuer%2eexample/a.pdf']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                P.normalize_url(url)

    def test_domain_boundary_and_terms_review_are_required(self):
        for url in ['https://issuer.example.evil.example/a.pdf', 'https://other.example/a.pdf',
                    'https://cdn.issuer.example/a.pdf']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.policy.check(url)
        with patch.dict(os.environ, {'RESEARCH_AGENT_CONTACT': 'REPLACE-ME@example.com'}):
            with self.assertRaises(ValueError):
                P.Collector(self.policy)

    def test_cross_domain_and_downgrade_redirects_are_refused(self):
        collector = P.Collector(self.policy, fetcher=self.fetch, resolver=lambda url: ['93.184.216.34'])
        for location in ['https://other.example/a.pdf', 'http://issuer.example/a.pdf',
                         'http://127.0.0.1/a.pdf', 'https://user:secret@issuer.example/a.pdf']:
            with self.subTest(location=location):
                self.responses[DOC] = (302, {'Location': location}, b'')
                with self.assertRaises(ValueError):
                    collector.fetch(DOC, 10000)
        self.assertTrue(all(call[0] in {DOC, SITE + 'robots.txt'} for call in self.calls))

    def test_regulator_redirect_checks_robots_and_records_actual_publisher(self):
        regulator = 'https://filings.example/'
        target = regulator + 'annual.pdf'
        policy = P.Policy('Synthetic Issuer', SITE, publishers={'filings.example': 'Synthetic Regulator'},
                          terms_reviewed_hosts=('issuer.example', 'filings.example'))
        self.responses[DOC] = (302, {'Location': target}, b'')
        self.responses[regulator + 'robots.txt'] = ROBOTS
        self.responses[target] = (200, {'Content-Type': 'application/pdf'}, PDF)
        result = self.collect(policy=policy)
        self.assertEqual(result['documents'][0]['url'], target)
        self.assertEqual(result['documents'][0]['publisher'], 'Synthetic Regulator')
        self.assertIn(regulator + 'robots.txt', [call[0] for call in self.calls])
        with self.assertRaises(ValueError):
            policy.publisher('https://unlisted.filings.example/a.pdf')

    def test_robots_redirects_cannot_escape_host_policy(self):
        self.responses[SITE + 'robots.txt'] = (302, {'Location': 'http://127.0.0.1/robots.txt'}, b'')
        result = self.collect()
        self.assertFalse(result['documents'])
        self.assertEqual(len(self.calls), 1)

    def test_redirect_loop_is_bounded(self):
        self.responses[DOC] = (302, {'Location': DOC}, b'')
        result = self.collect()
        self.assertFalse(result['documents'])
        self.assertIn('Too many', result['errors'][0]['error'])
        self.assertEqual(sum(call[0] == DOC for call in self.calls), 5)

    def test_size_count_and_total_limits(self):
        policy = P.Policy('Synthetic Issuer', SITE, terms_reviewed_hosts=('issuer.example',), max_documents=1)
        with self.assertRaises(ValueError):
            self.collect((DOC, SITE + 'second.pdf'), policy=policy)
        self.assertFalse(self.calls)
        self.policy.max_bytes = 8
        result = self.collect()
        self.assertFalse(result['documents'])
        self.assertIn('Oversized', result['errors'][0]['error'])

    def test_total_download_budget_and_partial_manifest(self):
        self.policy.max_total_bytes = len(PDF)
        result = self.collect((DOC, SITE + 'other.pdf'))
        self.assertEqual(len(result['documents']), 1)
        self.assertEqual(len(result['errors']), 1)
        self.assertNotIn(SITE + 'other.pdf', [call[0] for call in self.calls])

    def test_failed_stream_cannot_reuse_the_total_byte_budget(self):
        self.policy.max_bytes = self.policy.max_total_bytes = 10
        result = self.collect((DOC, SITE + 'other.pdf'))
        self.assertFalse(result['documents'])
        self.assertEqual(len(result['errors']), 2)
        self.assertIn('Total public', result['errors'][1]['error'])
        self.assertNotIn(SITE + 'other.pdf', [call[0] for call in self.calls])

    def test_gates_encodings_html_and_wrong_signatures_are_rejected(self):
        collector = P.Collector(self.policy, fetcher=self.fetch, resolver=lambda url: ['93.184.216.34'])
        for response in [(401, {}, b''), (403, {}, b''), (402, {}, b''),
                         (200, {'Content-Encoding': 'gzip'}, b'compressed'),
                         (200, {'Content-Length': '1000'}, b'short')]:
            with self.subTest(response=response):
                self.responses[DOC] = response
                with self.assertRaises(ValueError):
                    collector.fetch(DOC, 10000)
        self.responses[DOC] = (200, {'Content-Type': 'text/html'}, b'<html>Sign in</html>')
        self.assertFalse(self.collect()['documents'])

    def test_wrong_document_bytes_are_rejected(self):
        self.responses[DOC] = (200, {'Content-Type': 'application/pdf'}, b'<html>Login</html>')
        self.assertFalse(self.collect()['documents'])

    def test_extensionless_pdf_is_typed_from_response(self):
        url = SITE + 'download?id=synthetic'
        self.responses[url] = self.responses[DOC]
        self.assertEqual(self.collect((url,))['documents'][0]['type'], 'pdf')

    def test_discovery_failure_is_recorded_in_manifest(self):
        self.responses[SITE + 'robots.txt'] = (503, {}, b'')
        result = self.collect(())
        self.assertFalse(result['documents'])
        self.assertIn('503', result['errors'][0]['error'])

    def test_default_transport_pins_tls_and_closes_oversized_response(self):
        response = SimpleNamespace(status=200, headers={}, read=lambda size, **kwargs: b'x' * size)
        closed = []
        response.close = lambda: closed.append('response')
        requests, options = [], []

        def pool_factory(**kwargs):
            options.append(kwargs)
            return SimpleNamespace(urlopen=lambda *args, **kwargs: requests.append((args, kwargs)) or response,
                                   close=lambda: closed.append('pool'))

        urllib3 = ModuleType('urllib3')
        urllib3.Timeout = lambda **kwargs: kwargs
        urllib3.HTTPSConnectionPool = pool_factory
        urllib3.exceptions = SimpleNamespace(HTTPError=type('FakeHTTPError', (Exception,), {}))
        with patch.dict('sys.modules', {'urllib3': urllib3}):
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                P._request(DOC, '93.184.216.34', 'Identifying contact', 10, time.monotonic() + 20)
        self.assertEqual(options[0]['host'], '93.184.216.34')
        self.assertEqual(options[0]['server_hostname'], 'issuer.example')
        self.assertEqual(options[0]['assert_hostname'], 'issuer.example')
        self.assertEqual(options[0]['cert_reqs'], 'CERT_REQUIRED')
        self.assertFalse(requests[0][1]['redirect'])
        self.assertEqual(requests[0][1]['headers']['Host'], 'issuer.example')
        self.assertEqual(closed, ['response', 'pool'])

    def test_spreadsheet_bytes_are_archived_without_parsing_in_fetcher(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as book:
            book.writestr('fixture.txt', 'Isolated upload parser must validate the workbook package')
        url = SITE + 'results.xlsx'
        self.responses[url] = (200, {'Content-Type': P.TYPES['.xlsx']}, buffer.getvalue())
        result = self.collect((url,))
        self.assertEqual(result['documents'][0]['type'], 'xlsx')

    def test_duplicate_bytes_are_not_saved_twice(self):
        url = SITE + 'second.pdf'
        self.responses[url] = self.responses[DOC]
        result = self.collect((DOC, url, DOC))
        self.assertEqual(len(result['documents']), 1)
        self.assertEqual(sum(call[0] == DOC for call in self.calls), 1)

    def test_discovery_uses_only_approved_document_links(self):
        self.responses[SITE] = (200, {'Content-Type': 'text/html'},
            b'<a href="/report.pdf">Report</a><a href="https://other.example/a.pdf">Other</a>'
            b'<a href="/private.docx">Unsupported</a><a href="/login">Login</a>')
        self.assertEqual(len(self.collect(())['documents']), 1)

    def test_discovery_abstains_and_preserves_manifest(self):
        self.responses[SITE] = (200, {'Content-Type': 'text/html'}, b'<html>No document links</html>')
        result = self.collect(())
        self.assertIn('provide official', result['errors'][0]['error'])
        self.assertTrue((self.root / 'archive/manifest.json').is_file())

    def test_does_not_overwrite_an_archive(self):
        self.collect()
        with self.assertRaises(FileExistsError):
            self.collect()

    def test_public_only_and_mixed_disclosures(self):
        public = {'provenance': {'origin': 'public_document'}}
        self.assertEqual(P.public_basis({'facts': [public]}), P.PUBLIC_NOTICE)
        self.assertIn('and other room materials', P.public_basis({'facts': [public, {}]}))
        self.assertIsNone(P.public_basis({'facts': [{}]}))

    def test_import_uses_upload_parser_and_persists_provenance_before_facts(self):
        manifest = self.collect()
        self.check_import(manifest)

    def test_local_import_uses_upload_parser_and_persists_human_provenance(self):
        source = self.root / 'download.pdf'
        source.write_bytes(PDF)
        manifest = self.collect((), local_files=[(source, DOC)])
        self.assertTrue(manifest['documents'][0]['collected_by_person'])
        self.check_import(manifest)

    def check_import(self, manifest):
        documents = []
        room = SimpleNamespace(id='room', lead_id='lead', deal_id='deal')
        lead = SimpleNamespace(company_name=self.policy.company, promoted_deal_id='deal',
                               company_profile=SimpleNamespace(website=SITE))
        deal = SimpleNamespace(document_ids=[], status='new')
        store = SimpleNamespace(get_workspace=lambda tenant, **kwargs: room if tenant == 'tenant' else None,
            get_lead=lambda tenant, lead_id: lead, get_documents_for_deal=lambda tenant, deal_id: documents,
            save_document=documents.append, update_deal=lambda tenant, deal_id, update: update(deal))
        ingestion = ModuleType('delivery.ingestion')
        parsed = []

        def ingest(source, tenant, deal_id):
            parsed.append((source, tenant, deal_id))
            return SimpleNamespace(id='doc', workbook_inventory={})

        ingestion.ingest_upload = ingest
        schemas = ModuleType('schemas')
        schemas.DealStatus = SimpleNamespace(INGESTED='ingested')
        with patch.dict('sys.modules', {'delivery.ingestion': ingestion, 'schemas': schemas}), \
                patch.object(os, 'O_NOFOLLOW', getattr(os, 'O_NOFOLLOW', 0), create=True), \
                patch.object(os, 'O_NONBLOCK', getattr(os, 'O_NONBLOCK', 0), create=True):
            result = P.import_documents(store, 'tenant', 'room', self.root / 'archive')
            self.assertEqual(result, ['doc'])
            self.assertEqual(documents[0].workbook_inventory['public_source'], manifest['documents'][0])
            self.assertEqual(deal.document_ids, ['doc'])
            self.assertEqual(parsed[0][1:], ('tenant', 'deal'))
            self.assertEqual(P.import_documents(store, 'tenant', 'room', self.root / 'archive'), [])
            with self.assertRaises(ValueError):
                P.import_documents(store, 'wrong-tenant', 'room', self.root / 'archive')
            source = self.root / 'archive' / manifest['documents'][0]['filename']
            source.write_bytes(b'%PDF-tampered')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                P.import_documents(store, 'tenant', 'room', self.root / 'archive')
        self.assertEqual(len(parsed), 1)


class PublicSourcesCommandTests(unittest.TestCase):
    def test_repeatable_local_url_pairs_reach_archive_and_existing_import_path(self):
        from scripts import import_public_documents as command
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            first, second = root / 'first.pdf', root / 'second.pdf'
            first.write_bytes(PDF)
            second.write_bytes(PDF + b'\nsecond synthetic document')
            config = root / 'publishers.json'
            config.write_text(json.dumps({'publishers': {'filings.example': 'Synthetic Publisher'}}))
            archive = root / 'archive'
            argv = ['import_public_documents', '--company', 'Synthetic Issuer', '--website', SITE,
                    '--out', str(archive), '--db', str(root / 'synthetic.db'), '--tenant', 'tenant',
                    '--config', str(config), '--local-file', str(first), '--source-url', DOC,
                    '--local-file', str(second), '--source-url', 'https://filings.example/second.pdf']
            store_module = ModuleType('store')
            store_context = MagicMock()
            store_module.Store = MagicMock(return_value=store_context)
            room = SimpleNamespace(id='room', deal_id='deal')
            with patch.object(command.sys, 'argv', argv), \
                    patch.dict('sys.modules', {'store': store_module}), \
                    patch.dict(os.environ, {'RESEARCH_AGENT_CONTACT': ''}), \
                    patch.object(P, 'Collector', side_effect=AssertionError('No crawler')), \
                    patch.object(command, 'research_room', return_value=room), \
                    patch.object(command, 'import_documents', return_value=['doc-1', 'doc-2']) as ingest, \
                    patch.object(command.sys, 'stdout', new_callable=io.StringIO) as output:
                self.assertEqual(command.main(), 0)
                self.assertEqual(json.loads(output.getvalue())['document_ids'], ['doc-1', 'doc-2'])
            ingest.assert_called_once_with(store_context.__enter__.return_value, 'tenant', 'room', archive)
            manifest = json.loads((archive / 'manifest.json').read_text())
            self.assertFalse(manifest['errors'])
            self.assertEqual([record['source_url'] for record in manifest['documents']],
                             [DOC, 'https://filings.example/second.pdf'])
            self.assertEqual([record['publisher'] for record in manifest['documents']],
                             ['Synthetic Issuer', 'Synthetic Publisher'])
            self.assertTrue(all(record['collected_by_person'] for record in manifest['documents']))

    def test_unpaired_local_arguments_fail_before_collection_or_store_access(self):
        from scripts import import_public_documents as command
        base = ['import_public_documents', '--company', 'Synthetic Issuer', '--website', SITE,
                '--out', 'synthetic-archive', '--db', 'synthetic.db', '--tenant', 'tenant']
        for extra in [['--local-file', 'download.pdf'], ['--source-url', DOC],
                      ['--local-file', 'first.pdf', '--local-file', 'second.pdf', '--source-url', DOC]]:
            with self.subTest(extra=extra), patch.object(command.sys, 'argv', base + extra), \
                    patch.object(command.sys, 'stderr', new_callable=io.StringIO) as error, \
                    patch.object(command, 'collect', side_effect=AssertionError('No collection')), \
                    self.assertRaises(SystemExit) as exc:
                command.main()
            self.assertEqual(exc.exception.code, 2)
            self.assertIn('Pair each --local-file', error.getvalue())


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ['pydantic', 'pdfplumber', 'openpyxl', 'ollama']),
                     'Requires application dependencies: pydantic, pdfplumber, openpyxl, ollama')
class ProvenanceIntegrationTests(unittest.TestCase):
    def test_source_loading_and_extraction_keep_bound_provenance(self):
        from delivery.deal_documents import facts, sources
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / 'public.pdf'
            source.write_bytes(PDF)
            provenance = {'origin': 'public_document', 'url': DOC, 'publisher': 'Synthetic Issuer',
                          'sha256': hashlib.sha256(PDF).hexdigest(), 'size_bytes': len(PDF)}
            document = {'filename': source.name, 'type': 'pdf', 'storage_uri': str(source),
                        'workbook_inventory': {'public_source': provenance}}
            db = root / 'facts.db'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE documents (tenant_id TEXT, deal_id TEXT, data TEXT)')
                conn.execute('INSERT INTO documents VALUES (?, ?, ?)', ('tenant', 'deal', json.dumps(document)))
            pdf = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda **kwargs: 'Revenue 12')])
            context = unittest.mock.MagicMock()
            context.__enter__.return_value = pdf
            model = SimpleNamespace(json=lambda *args, **kwargs: {'facts': [
                {'t': 'hist', 'b': 'H', 'm': 'Revenue', 's': '', 'p': '', 'v': '12', 'u': '', 'k': 'text', 'd': ''}]})
            with patch.object(os, 'O_NOFOLLOW', getattr(os, 'O_NOFOLLOW', 0), create=True), \
                    patch.object(os, 'O_NONBLOCK', getattr(os, 'O_NONBLOCK', 0), create=True), \
                    patch.object(sources.pdfplumber, 'open', return_value=context):
                units, sheets = sources.load_sources(str(db), 'tenant', 'deal')
                self.assertEqual(units[0].provenance, provenance)
                accepted, rejected = facts.extract_facts(model, units)
                self.assertEqual(accepted[0]['provenance'], provenance)
                self.assertFalse(rejected)
                self.assertEqual(sources.load_sources(str(db), 'other-tenant', 'deal'), ([], []))
                source.write_bytes(b'%PDF-tampered')
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    sources.load_sources(str(db), 'tenant', 'deal')

    def test_pdf_workbook_facts_and_notices_keep_public_provenance(self):
        from delivery.deal_documents import facts, sources, compliance, pages
        provenance = {'origin': 'public_document', 'url': DOC, 'publisher': 'Synthetic Issuer'}
        unit = sources.Unit('PUBLIC-p1', 'public.pdf', 'page 1', {'text': 'Revenue 12'}, provenance=provenance)
        fact = facts._fact('PUBLIC-p1.1', unit, 'historical_financials', 'historical',
                           'Revenue', '', '', '12', '', 'text', '')
        sheet = sources.Sheet('PUBLIC-s1', 'public.xlsx', 'Results', 'visible',
                              [(1, {'A1': 'Revenue', 'B1': 12})], {'B': 'Period'}, provenance)
        cell = sources.sheet_facts(sheet)[0]
        self.assertEqual(fact['provenance'], provenance)
        self.assertEqual(cell['provenance'], provenance)
        self.assertEqual(sources.sheet_text_cells(sheet, minimum_length=1).provenance, provenance)
        base = {'facts': [fact], 'workbook_cells': [cell]}
        notices = dict(compliance.notices('Synthetic Issuer', base))
        self.assertIn('public information only', notices['Basis of preparation and date of information'])
        self.assertIn('not supplied', notices['Basis of preparation and date of information'])
        self.assertIn('public source:', facts.fact_line(fact))
        page = {'title': 'Revenue', 'brief': '', 'cells': [fact['id']], 'takeaways': [], 'exhibits': {}}
        self.assertIn('public sources', pages.page_spec(page, {fact['id']: fact})['note'])


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ['pydantic', 'pdfplumber', 'openpyxl', 'ollama']), 'application dependencies absent')
def test_an_existing_room_gains_its_deal_only_for_its_stated_website():
    from agents.analysis.operating_workflow import reconcile_workspace
    from delivery.deal_documents.public_sources import adopt_room
    from schemas import CompanyEvidence, CompanyProfile, SourcedLead
    from store import Store
    with tempfile.TemporaryDirectory() as folder, Store(Path(folder) / 'app.db') as store:
        seen = CompanyEvidence(field='name', value='Synthetic Co', quote='Synthetic Co', source_url='https://directory.example/synthetic')
        profile = CompanyProfile(tenant_id='t1', name='Synthetic Co', website='', evidence=[seen])
        store.save_company(profile)
        lead = SourcedLead(tenant_id='t1', company_name='Synthetic Co', company_id=profile.id, company_profile=profile)
        store.save_lead(lead)
        room = reconcile_workspace(store, lead)
        adopted = adopt_room(store, 't1', room, 'https://synthetic.example/')
        saved = store.get_lead('t1', lead.id)
        assert adopted.deal_id and saved.promoted_deal_id == adopted.deal_id and saved.company_profile.website.startswith('https://synthetic.example')
        assert adopt_room(store, 't1', adopted, 'https://synthetic.example/').deal_id == adopted.deal_id  # safe to repeat
        try:
            adopt_room(store, 't1', adopted, 'https://other.example/')
        except ValueError as exc:
            assert 'different official website' in str(exc)
        else:
            raise AssertionError('a second website must be refused')
