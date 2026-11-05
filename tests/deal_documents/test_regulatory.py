"""Synthetic issuer disclosures; the evidence checks also run without app dependencies."""
from copy import deepcopy
import datetime
import importlib.util
from io import BytesIO
import unittest
from unittest.mock import Mock

from delivery.deal_documents import compliance


def fact(number, metric, statement, **extra):
    return {'id': f'S.f{number}', 'source': 'S', 'document': 'Synthetic company records', 'location': f'page {number}',
            'metric': metric, 'statement': statement, 'value': '', 'unit': '', 'period': '', 'segment': '',
            'basis': 'company_claim', 'topic': 'regulatory', **extra}


def issuer(country, *facts):
    return {'facts': [fact(1, 'Country of incorporation', f'Country of incorporation: {country}'), *facts],
            'workbook_cells': []}


def checklist(base):
    return {row['key']: row for row in compliance.disclosure_checklist(base)}


class RegulatoryEvidenceTests(unittest.TestCase):
    def test_indian_legend_names_rules_and_distribution_restrictions(self):
        base = issuer('India')
        notices = dict(compliance.notices('Synthetic issuer', base, datetime.date(2030, 1, 1)))
        legend = notices['Regulatory legend — draft for counsel']
        for text in ('Draft legend for counsel', 'Companies Act 2013 section 42', 'Rule 14', 'PAS-4',
                     '200 persons per financial year', 'each kind of security', 'qualified institutional buyers',
                     'employee stock option schemes', 'No public advertisement', 'SEBI', 'FEMA', 'non-resident'):
            self.assertIn(text, legend)
        self.assertNotIn('Regulation D', legend)
        self.assertNotRegex(legend, r'(?i)(?:document|memorandum) complies|is compliant')
        self.assertIn('not investment, legal, tax or regulatory advice', legend)
        self.assertEqual(len(notices), 4)

    def test_us_506b_has_no_solicitation_and_conditional_information_rights(self):
        base = issuer('United States', fact(2, 'Offering exemption', 'Offering exemption: Rule 506(b)'))
        legend = compliance.regulatory_notice(base)[1]
        for text in ('Securities Act of 1933', 'Regulation D', 'Rule 506(b)', 'No general solicitation',
                     'accredited investor', 'non-accredited', 'Rule 502(b)', 'restricted', 'resale'):
            self.assertIn(text, legend)
        self.assertNotIn('Companies Act', legend)
        self.assertNotIn('PAS-4', legend)
        self.assertIn('information_rights', checklist(base))
        self.assertNotIn('verification', checklist(base))

    def test_us_506c_requires_verification_and_does_not_prohibit_solicitation(self):
        base = issuer('United States', fact(2, 'Offering exemption', 'Offering exemption: Rule 506(c)'))
        legend = compliance.regulatory_notice(base)[1]
        self.assertIn('All purchasers must be accredited', legend)
        self.assertIn('reasonable steps to verify', legend)
        self.assertIn('General solicitation is permitted only subject', legend)
        self.assertNotIn('No general solicitation', legend)
        self.assertIn('verification', checklist(base))
        self.assertNotIn('information_rights', checklist(base))

    def test_us_without_route_does_not_choose_an_exemption(self):
        base = issuer('United States')
        legend = compliance.regulatory_notice(base)[1]
        self.assertIn('counsel must select Rule 506(b) or Rule 506(c)', legend)
        self.assertEqual(checklist(base)['exemption']['status'], 'outstanding')
        self.assertIn('information_rights', checklist(base))
        self.assertIn('verification', checklist(base))

    def test_conflicting_and_tentative_routes_remain_outstanding(self):
        cases = [
            [fact(2, 'Offering exemption', 'Rule 506(b) or Rule 506(c)')],
            [fact(2, 'Offering exemption', 'Proposed Rule 506(c)')],
            [fact(2, 'Offering exemption', 'Not relying on Rule 506(c)')],
            [fact(2, 'Offering exemption', 'Rule 506(b)'), fact(3, 'Offering route', 'Rule 506(c)')],
            [fact(2, 'Offering exemption', 'Rule 504')],
        ]
        for facts in cases:
            with self.subTest(facts=facts):
                base = issuer('United States', *facts)
                self.assertEqual(compliance.offering_route(base)[0], 'unknown')
                self.assertEqual(checklist(base)['exemption']['status'], 'outstanding')

    def test_unknown_jurisdiction_asks_and_has_no_country_legend(self):
        base = {'facts': [], 'workbook_cells': []}
        legend = compliance.regulatory_notice(base)[1]
        self.assertIn('provide the issuer incorporation jurisdiction and certificate', legend)
        self.assertNotIn('Companies Act', legend)
        self.assertNotIn('Regulation D', legend)
        rows = checklist(base)
        self.assertEqual(rows['jurisdiction']['status'], 'outstanding')
        self.assertEqual(rows['applicability']['status'], 'outstanding')
        self.assertNotIn('pas4', rows)
        self.assertNotIn('exemption', rows)

    def test_currency_headquarters_markets_and_peers_do_not_select_jurisdiction(self):
        for item in (
            fact(1, 'Revenue', 'Revenue is 90 currency units.', value='90', unit='currency units'),
            fact(1, 'Headquarters', 'Headquarters: India'),
            fact(1, 'Customers', 'The company has customers in the United States.'),
            fact(1, 'Country of incorporation', 'India', topic='competition'),
            fact(1, 'Country of incorporation', 'United States', entity='Peer'),
            fact(1, 'Country of incorporation', 'India', segment='Subsidiary'),
            fact(1, 'Governing law', 'The investment agreement is governed by Indian law.'),
            fact(1, 'Jurisdiction', 'Jurisdiction: India', topic='regulatory'),
        ):
            with self.subTest(item=item):
                self.assertEqual(compliance.jurisdiction({'facts': [item]})['country'], 'unknown')

    def test_explicit_incorporation_statement_and_delaware_are_evidence(self):
        for text, expected in (('The issuer is incorporated in India.', 'IN'),
                               ('The company was incorporated under the Companies Act 2013.', 'IN'),
                               ('The issuer is incorporated in Delaware.', 'US')):
            base = {'facts': [fact(1, 'Legal status', text, topic='company')]}
            self.assertEqual(compliance.jurisdiction(base)['country'], expected)

    def test_generic_companies_act_unsupported_or_negated_country_remains_unknown(self):
        for country in ('Companies Act', 'Singapore', 'Not India', 'Proposed incorporation in India',
                        'Canada; subsidiary in India', 'Canada and India', 'India or United States', 'India and United States',
                        'India or Canada', 'India and Canada'):
            self.assertEqual(compliance.jurisdiction(issuer(country))['country'], 'unknown')

    def test_incorporation_clause_does_not_use_operating_markets(self):
        base = {'facts': [fact(1, 'Legal status', 'The issuer is incorporated in India and operates in the United States.', topic='company')]}
        self.assertEqual(compliance.jurisdiction(base)['country'], 'IN')

    def test_conflicting_country_evidence_is_retained_for_resolution(self):
        base = issuer('India', fact(2, 'Issuer jurisdiction', 'Issuer jurisdiction: United States'))
        chosen = compliance.jurisdiction(base)
        self.assertEqual(chosen['country'], 'unknown')
        self.assertEqual([f['id'] for f in chosen['evidence']], ['S.f1', 'S.f2'])
        self.assertEqual(checklist(base)['jurisdiction']['status'], 'outstanding')

    def test_uncited_ambiguous_ocr_or_forecast_evidence_is_not_accepted(self):
        for field, value in (('document', ''), ('location', ''), ('id', ''), ('ambiguity', 'unreadable'),
                             ('ocr_only', True), ('cell_error', True), ('basis', 'projection'), ('basis', 'target')):
            base = issuer('India')
            base['facts'][0][field] = value
            with self.subTest(field=field):
                self.assertEqual(compliance.jurisdiction(base)['country'], 'unknown')

    def test_checklist_uses_specific_cited_disclosures_and_retains_missing_items(self):
        proceeds = fact(2, 'Use of proceeds', 'Use of proceeds: fund production equipment.')
        base = issuer('India', proceeds, fact(3, 'Revenue', 'Revenue: 90 units.', value='90', topic='historical_financials'))
        rows = checklist(base)
        self.assertEqual(rows['proceeds']['status'], 'supplied')
        self.assertEqual(rows['proceeds']['evidence'], [proceeds])
        self.assertIn('counsel review', rows['proceeds']['detail'])
        self.assertEqual(rows['financials']['status'], 'outstanding')
        self.assertEqual(rows['pas4']['status'], 'outstanding')
        self.assertTrue(all(row['supplier'] for row in rows.values()))
        self.assertEqual(len(rows), len(compliance.disclosure_checklist(base)))

    def test_explicit_nil_and_pending_litigation_are_supplied_not_assumed(self):
        for text in ('No outstanding litigation or regulatory action.', 'Litigation pending before the court.'):
            base = issuer('India', fact(2, 'Litigation and regulatory actions', text))
            self.assertEqual(checklist(base)['litigation']['status'], 'supplied')
        self.assertEqual(checklist(issuer('India'))['litigation']['status'], 'outstanding')

    def test_placeholder_disclosures_are_outstanding(self):
        for value in ('unknown', 'pending', 'TBD', 'to be provided', 'not available', 'will be supplied', 'to be prepared'):
            base = issuer('India', fact(2, 'Use of proceeds', 'Use of proceeds: ' + value))
            with self.subTest(value=value):
                self.assertEqual(checklist(base)['proceeds']['status'], 'outstanding')

    def test_fema_and_sebi_applicability_are_never_assumed(self):
        rows = checklist(issuer('India'))
        for key in ('fema', 'sebi'):
            self.assertEqual(rows[key]['status'], 'outstanding')
        self.assertNotIn('fema', checklist(issuer('United States')))
        questions = dict(compliance.counsel_questions(issuer('United States')))
        self.assertNotIn('foreign_investment', questions)
        self.assertNotIn('SEBI', str(questions))

    def test_workbook_evidence_is_accepted_and_input_is_not_modified(self):
        base = {'facts': [], 'workbook_cells': issuer('India')['facts']}
        before = deepcopy(base)
        self.assertEqual(compliance.jurisdiction(base)['country'], 'IN')
        compliance.notices('Synthetic issuer', base)
        compliance.disclosure_checklist(base)
        self.assertEqual(base, before)


APP_DEPENDENCIES = all(importlib.util.find_spec(name) for name in ('ollama', 'pdfplumber', 'pptx', 'reportlab', 'openpyxl'))


@unittest.skipUnless(APP_DEPENDENCIES, 'Page integration needs ollama, pdfplumber, python-pptx, reportlab and openpyxl')
class RegulatoryPageTests(unittest.TestCase):
    def test_schedule_is_built_paginated_and_never_written_by_a_model(self):
        from delivery.deal_documents import pages
        for country in ('India', 'United States', 'Unknown'):
            base = issuer(country)
            built = pages.build(base)
            schedules = [page for page in built if page.get('family') == 'regulatory_checklist']
            self.assertTrue(schedules)
            self.assertTrue(all(page['schedule'] for page in schedules))
            self.assertEqual(sum(len(page['exhibits']['grid']['rows']) for page in schedules),
                             len(compliance.disclosure_checklist(base)))
            self.assertTrue(all(set(page['cells']) <= {'S.f1'} for page in schedules))
            model = Mock()
            self.assertEqual(pages.write_all(model, base, schedules), schedules)
            model.json.assert_not_called()
            self.assertFalse(any(page.get('family') == 'regulatory_checklist'
                                 for deck in pages.decks(built).values() for page in deck))

    def test_legal_references_and_cited_numbers_survive_ledger_tie_out(self):
        from delivery.deal_documents import ledger, pages
        base = issuer('India', fact(2, 'Use of proceeds', 'Use of proceeds: 40 units for equipment.', value='40', unit='units'))
        built = pages.build(base)
        schedules = [page for page in built if page.get('family') == 'regulatory_checklist']
        report = ledger.tie_out({'memo': schedules}, base)
        self.assertFalse(report['exceptions'], report['exceptions'])
        self.assertTrue(report['occurrences'])

    def test_schedule_and_legends_render_as_editable_office_content(self):
        from pptx import Presentation
        from delivery.deal_documents import pages
        for country in ('India', 'United States', 'Unknown'):
            base = issuer(country, fact(2, 'Use of proceeds', 'Use of proceeds: equipment and working capital.'))
            schedules = [page for page in pages.build(base) if page.get('family') == 'regulatory_checklist']
            data = pages.render('Synthetic issuer', compliance.notices('Synthetic issuer', base), schedules, base, 'Draft')
            deck = Presentation(BytesIO(data))
            # The schedule pages sit among the summary, contents and dividers; each must appear as its own editable table.
            tables = [[[cell.text for cell in row.cells] for row in shape.table.rows] for slide in deck.slides for shape in slide.shapes if shape.has_table]
            for page in schedules:
                self.assertIn([page['exhibits']['grid']['header'], *page['exhibits']['grid']['rows']], tables)

    def test_gate_keeps_missing_disclosures_blocking_and_supplied_evidence_for_counsel(self):
        base = issuer('India', fact(2, 'Use of proceeds', 'Use of proceeds: equipment.'))
        result = compliance.assess([], base)
        checks = {check['key']: check for check in result['checks']}
        self.assertEqual(checks['schedule_proceeds']['status'], 'counsel')
        self.assertEqual(checks['schedule_pas4']['status'], 'fail')
        self.assertIn('schedule_pas4', result['blockers'])
        self.assertTrue(checks['schedule_proceeds']['evidence'])
        unknown = compliance.assess([], {'facts': [], 'workbook_cells': []})
        self.assertIn('schedule_jurisdiction', unknown['blockers'])


if __name__ == '__main__':
    unittest.main()
