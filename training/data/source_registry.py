"""Candidate public sources. Everything is disabled until a human lists it in enabled_sources.json.

Nothing here grants training rights: 'pending_review' means no one has verified terms
for model-training use. Enabling a source is a recorded human decision, not code.
"""
import json
from pathlib import Path

ENABLED_FILE = Path(__file__).with_name('enabled_sources.json')

SOURCES = {
    'sec_edgar_companyfacts': dict(
        name='SEC EDGAR XBRL companyfacts / frames', url='https://data.sec.gov/api/xbrl/',
        terms='SEC fair-access policy: identifying User-Agent required, <=10 req/s (we cap at 5). Filing data is public; '
              'redistribution and model-training terms still need individual human review.',
        rights_status='pending_review', max_requests_per_second=5, requires_contact_env='RESEARCH_AGENT_CONTACT'),
    'sec_edgar_submissions': dict(
        name='SEC EDGAR submissions index', url='https://data.sec.gov/submissions/',
        terms='Same fair-access policy as companyfacts.', rights_status='pending_review',
        max_requests_per_second=5, requires_contact_env='RESEARCH_AGENT_CONTACT'),
    'sec_edgar_filing_documents': dict(
        name='SEC EDGAR filing documents (www.sec.gov/Archives)', url='https://www.sec.gov/Archives/',
        terms='Same fair-access policy; individual exhibits may embed third-party copyrighted material.',
        rights_status='pending_review', max_requests_per_second=5, requires_contact_env='RESEARCH_AGENT_CONTACT'),
    'sebi_drhp_rhp_index': dict(
        name='SEBI DRHP/RHP public document index', url='https://www.sebi.gov.in/',
        terms='Site terms and robots.txt unreviewed; no fetcher implemented beyond a disabled interface.',
        rights_status='pending_review', max_requests_per_second=1, requires_contact_env=None),
    'listed_company_investor_decks': dict(
        name='Listed-company investor presentations', url=None,
        terms='Per-issuer copyright; each issuer needs its own review. No bulk collection.',
        rights_status='pending_review', max_requests_per_second=1, requires_contact_env=None),
}


def enabled_ids(path=ENABLED_FILE):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list) or any(not isinstance(x, str) for x in data):
        raise ValueError('enabled_sources.json must be a list of source ids')
    unknown = set(data) - set(SOURCES)
    if unknown:
        raise ValueError('Unknown enabled source ids: %s' % sorted(unknown))
    return set(data)


def is_enabled(source_id, path=ENABLED_FILE):
    return source_id in SOURCES and source_id in enabled_ids(path)


def effective_rights(source_id, path=ENABLED_FILE):
    """Collection enablement and training rights are separate human decisions.

    Enabling a source never changes its rights_status; a human must edit the
    registry entry to 'public_training_approved' after reviewing its terms.
    """
    if not is_enabled(source_id, path):
        return 'pending_review'
    return SOURCES[source_id]['rights_status']
