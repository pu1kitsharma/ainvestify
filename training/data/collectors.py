"""EDGAR companyfacts/submissions collector and a disabled SEBI interface.

Fails closed: no request is made unless the source is listed in enabled_sources.json
AND RESEARCH_AGENT_CONTACT ('Org contact@email') is set. The contact string is the only
identity ever sent; no default or invented identity exists. Every response is cached
by content hash with an index line.
"""
import hashlib
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import source_registry

CACHE_DIR = Path(__file__).resolve().parents[2] / 'runtime_qualification' / 'public_cache'


class SourceDisabledError(RuntimeError):
    pass


def contact_from_env(environ=None):
    value = (environ if environ is not None else os.environ).get('RESEARCH_AGENT_CONTACT', '').strip()
    if not re.fullmatch(r'\S.* \S+@\S+\.\S+', value):
        return None
    return value


class EdgarCollector:
    def __init__(self, cache_dir=CACHE_DIR, environ=None, enabled_path=source_registry.ENABLED_FILE,
                 opener=None, clock=time.monotonic, sleeper=time.sleep):
        self.cache_dir, self.environ, self.enabled_path = Path(cache_dir), environ, enabled_path
        self.opener = opener or self._urlopen
        self.clock, self.sleeper, self._last = clock, sleeper, None

    @staticmethod
    def _urlopen(request):
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()

    def _guard(self, source_id):
        if not source_registry.is_enabled(source_id, self.enabled_path):
            raise SourceDisabledError('%s is not in enabled_sources.json' % source_id)
        contact = contact_from_env(self.environ)
        if contact is None:
            raise SourceDisabledError('RESEARCH_AGENT_CONTACT is unset or malformed; live SEC calls refused')
        return contact

    def _fetch(self, source_id, url):
        contact = self._guard(source_id)
        minimum = 1.0 / source_registry.SOURCES[source_id]['max_requests_per_second']
        now = self.clock()
        if self._last is not None and now - self._last < minimum:
            self.sleeper(minimum - (now - self._last))
        self._last = self.clock()
        request = urllib.request.Request(url, headers={'User-Agent': contact, 'Accept': 'application/json'})
        body = self.opener(request)
        digest = hashlib.sha256(body).hexdigest()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / (digest + '.json')
        if not path.exists():
            path.write_bytes(body)
        with open(self.cache_dir / 'index.jsonl', 'a') as handle:
            handle.write(json.dumps({'url': url, 'sha256': digest, 'source': source_id,
                                     'retrieved_at': datetime.now(timezone.utc).isoformat()}) + '\n')
        return json.loads(body), digest

    def companyfacts(self, cik):
        return self._fetch('sec_edgar_companyfacts', 'https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json' % int(cik))

    def submissions(self, cik):
        return self._fetch('sec_edgar_submissions', 'https://data.sec.gov/submissions/CIK%010d.json' % int(cik))


class SebiDocumentFetcher:
    """Interface only. Even when enabled there is deliberately no implementation yet."""

    def __init__(self, enabled_path=source_registry.ENABLED_FILE):
        self.enabled_path = enabled_path

    def fetch(self, document_url):
        if not source_registry.is_enabled('sebi_drhp_rhp_index', self.enabled_path):
            raise SourceDisabledError('sebi_drhp_rhp_index is not enabled')
        raise NotImplementedError('SEBI fetching needs a human terms/robots review and an implementation')
