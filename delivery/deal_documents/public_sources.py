"""Bounded public-document collection and import through the upload parser.

Operators review site terms and publisher identity; robots permission alone
does not grant reuse rights. No credentials, cookies, proxies or search API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import socket
import stat
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

MAX_BYTES = 32 * 1024 * 1024
REDIRECTS = {301, 302, 303, 307, 308}
TYPES = {'.pdf': 'application/pdf',
         '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         '.xlsm': 'application/vnd.ms-excel.sheet.macroenabled.12'}
PUBLIC_NOTICE = ('Prepared from public information only, collected from company or regulatory publications. '
                 'These materials were not supplied to the preparer or endorsed by the company. '
                 'They have not been independently verified.')


def normalize_url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in {None, 80, 443} or '\\' in value or '%' in parsed.netloc
                or any(ord(char) < 33 or ord(char) == 127 for char in value)):
            raise ValueError()
        host = parsed.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError('Private, loopback and reserved addresses are forbidden')
        netloc = f'[{host}]' if ':' in host else host
        if parsed.port:
            netloc += f':{parsed.port}'
        return urlunsplit((parsed.scheme, netloc, parsed.path or '/', parsed.query, ''))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Use a public HTTP(S) URL without credentials or custom ports') from exc


def _host(value):
    return urlsplit(normalize_url(value)).hostname


def _addresses(url):
    parsed = urlsplit(url)
    return list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(
        parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)))


def _request(url, address, user_agent, limit, deadline):
    import urllib3
    parsed = urlsplit(url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError('Public source time limit exceeded')
    options = dict(host=address, port=parsed.port or (443 if parsed.scheme == 'https' else 80),
                   timeout=urllib3.Timeout(connect=min(5, remaining), read=min(10, remaining)), retries=False)
    pool = (urllib3.HTTPSConnectionPool(**options, server_hostname=parsed.hostname,
                                      assert_hostname=parsed.hostname, cert_reqs='CERT_REQUIRED')
            if parsed.scheme == 'https' else urllib3.HTTPConnectionPool(**options))
    response = None
    try:
        response = pool.urlopen('GET', urlunsplit(('', '', parsed.path, parsed.query, '')),
            headers={'Host': parsed.netloc, 'User-Agent': user_agent, 'Accept-Encoding': 'identity'},
            redirect=False, preload_content=False, assert_same_host=False)
        headers = {key.lower(): value for key, value in response.headers.items()}
        if response.status != 200:
            return response.status, headers, b''
        if int(headers.get('content-length', '0')) > limit:
            raise ValueError('Public source exceeds byte limit')
        chunks, size = [], 0
        while True:
            if time.monotonic() >= deadline:
                raise ValueError('Public source time limit exceeded')
            chunk = response.read(min(65536, limit + 1 - size), decode_content=False)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('Public source exceeds byte limit')
            chunks.append(chunk)
        return response.status, headers, b''.join(chunks)
    except (urllib3.exceptions.HTTPError, OSError) as exc:
        raise OSError('Public source connection failed or timed out') from exc
    finally:
        if response is not None:
            response.close()
        pool.close()


@dataclass
class Policy:
    company: str
    website: str
    # Exact hosts only for regulators/exchanges; no implicit third-party CDN.
    publishers: dict[str, str] = field(default_factory=dict)
    terms_reviewed_hosts: tuple[str, ...] = ()
    max_documents: int = 10
    max_bytes: int = MAX_BYTES
    max_total_bytes: int = 100 * 1024 * 1024

    def __post_init__(self):
        self.website = normalize_url(self.website)
        if not self.company.strip() or not 1 <= self.max_documents <= 50 or not 1 <= self.max_bytes <= MAX_BYTES:
            raise ValueError('Company name and bounded document limits are required')
        if not 1 <= self.max_total_bytes <= 500 * 1024 * 1024:
            raise ValueError('Invalid total byte limit')
        self.domain = _host(self.website).removeprefix('www.')
        def configured_host(host):
            if any(char in host for char in '/?#@'):
                raise ValueError('Configure exact hostnames, without URL paths or credentials')
            return _host('https://' + host)
        self.publishers = {configured_host(host): label for host, label in self.publishers.items()}
        self.terms_reviewed_hosts = tuple(configured_host(host) for host in self.terms_reviewed_hosts)

    def publisher(self, url):
        host = _host(url)
        if host == self.domain or host.endswith('.' + self.domain):
            return self.company
        if host in self.publishers and self.publishers[host].strip():
            return self.publishers[host]
        raise ValueError('Source host is outside the official domain and configured publishers')

    def check(self, url):
        url = normalize_url(url)
        self.publisher(url)
        if _host(url) not in self.terms_reviewed_hosts:
            raise ValueError('Operator must review public access and terms for this exact host')
        return url


class Collector:
    def __init__(self, policy, *, fetcher=None, resolver=None):
        self.policy = policy
        contact = os.environ.get('RESEARCH_AGENT_CONTACT', '').strip()
        if not contact or 'REPLACE-ME' in contact or any(ord(c) < 32 or ord(c) == 127 for c in contact):
            raise ValueError('Set RESEARCH_AGENT_CONTACT to an identifying organization and real contact')
        self.user_agent = f'AinvestifyPublicDocuments/1.0 ({contact})'
        self.fetcher = fetcher or _request
        self.resolver = resolver or _addresses
        self.robots, self.last_request = {}, {}

    def _get(self, url, limit, deadline):
        url = self.policy.check(url)
        addresses = self.resolver(url)
        if not addresses or any(not ipaddress.ip_address(a).is_global or ipaddress.ip_address(a).is_multicast for a in addresses):
            raise ValueError('Private, loopback and reserved addresses are forbidden')
        if time.monotonic() >= deadline:
            raise ValueError('Public source time limit exceeded')
        result = self.fetcher(url, addresses[0], self.user_agent, limit, deadline)
        status, headers, body = result
        headers = {key.lower(): value for key, value in headers.items()}
        if len(body) > limit or headers.get('content-encoding', 'identity').lower() not in {'identity', ''}:
            raise ValueError('Oversized or encoded public source')
        if status == 200 and 'content-length' in headers and int(headers['content-length']) != len(body):
            raise ValueError('Incomplete public source response')
        self.last_request[urlsplit(url).netloc] = time.monotonic()
        return status, headers, body

    def _redirect(self, url, headers):
        if not headers.get('location'):
            raise ValueError('Redirect lacks a destination')
        target = self.policy.check(urljoin(url, headers['location']))
        if urlsplit(url).scheme == 'https' and urlsplit(target).scheme != 'https':
            raise ValueError('HTTPS downgrade is forbidden')
        return target

    def _allowed(self, url, deadline):
        parsed = urlsplit(url)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        if origin not in self.robots:
            robots_url = origin + '/robots.txt'
            for _ in range(5):
                status, headers, body = self._get(robots_url, 512 * 1024, deadline)
                if status in REDIRECTS:
                    robots_url = self._redirect(robots_url, headers)
                    continue
                parser = RobotFileParser()
                if status == 404:
                    parser.parse([])
                elif status == 200 and 'text/plain' in headers.get('content-type', '').lower():
                    parser.parse(body.decode('utf-8', errors='replace').splitlines())
                else:
                    raise ValueError(f'robots.txt unavailable or gated (HTTP {status})')
                self.robots[origin] = parser
                break
            else:
                raise ValueError('Too many robots.txt redirects')
        parser = self.robots[origin]
        if not parser.can_fetch(self.user_agent, url):
            raise ValueError('robots.txt disallows this document')
        rate = parser.request_rate(self.user_agent)
        delay = max(1, parser.crawl_delay(self.user_agent) or 0, rate.seconds / rate.requests if rate else 0)
        wait = delay - (time.monotonic() - self.last_request.get(parsed.netloc, 0))
        if wait > 0:
            if wait >= deadline - time.monotonic():
                raise ValueError('robots.txt rate limit exceeds collection time budget')
            time.sleep(wait)

    def fetch(self, url, limit):
        url = self.policy.check(url)
        deadline = time.monotonic() + 45
        for _ in range(5):
            self._allowed(url, deadline)
            status, headers, body = self._get(url, limit, deadline)
            if status in REDIRECTS:
                url = self._redirect(url, headers)
                continue
            if status != 200:
                raise ValueError(f'Public source unavailable or gated (HTTP {status})')
            return url, headers, body
        raise ValueError('Too many public source redirects')

    def discover(self):
        url, headers, body = self.fetch(self.policy.website, min(self.policy.max_bytes, 1024 * 1024))
        if 'text/html' not in headers.get('content-type', ''):
            return [url] if Path(urlsplit(url).path).suffix.lower() in TYPES else []
        links = []

        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == 'a':
                    href = dict(attrs).get('href')
                    if href:
                        links.append(urljoin(url, href))

        parser = Links()
        parser.feed(body.decode('utf-8', errors='replace'))
        found = []
        for link in links:
            if Path(urlsplit(link).path).suffix.lower() in TYPES:
                try:
                    checked = self.policy.check(link)
                except ValueError:
                    continue
                if checked not in found:
                    found.append(checked)
        return found[:self.policy.max_documents]


def _write_new(path, content):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _read_local(path, limit):
    """Use the downloaded file's modification time, not its archive-copy time."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in TYPES:
        raise ValueError('Only PDF and supported spreadsheet files are accepted')
    if path.is_symlink():
        raise ValueError('Local public document must be a regular unlinked file')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Local public document must be a regular file')
        if info.st_size > limit:
            raise ValueError('Public source exceeds byte limit')
        body = stream.read(limit + 1)
        if len(body) > limit:
            raise ValueError('Public source exceeds byte limit')
        if len(body) != info.st_size:
            raise ValueError('Local public document changed while reading')
    return {'content-type': TYPES[suffix]}, body, datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()


def collect(policy, folder, urls=(), *, local_files=(), fetcher=None, resolver=None):
    """Archive URLs and (local path, public source URL) pairs with bound publishers."""
    urls = list(dict.fromkeys(normalize_url(url) for url in urls))
    local_files = [(Path(path), normalize_url(url)) for path, url in local_files]
    if len(urls) + len(local_files) > policy.max_documents:
        raise ValueError('Public document count limit exceeded')
    collector = Collector(policy, fetcher=fetcher, resolver=resolver) if urls or not local_files else None
    folder = Path(folder).absolute()
    if folder.resolve() != folder or folder.is_symlink():
        raise ValueError('Public archive must be a canonical unlinked directory')
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {'version': 1, 'origin': 'public_document', 'company': policy.company, 'website': policy.website,
                'notice': PUBLIC_NOTICE, 'terms_reviewed_hosts': list(policy.terms_reviewed_hosts),
                'publishers': policy.publishers,
                'documents': [], 'errors': []}
    total, seen = 0, set()
    try:
        if not urls and not local_files:
            urls = collector.discover()
        if not urls and not local_files:
            manifest['errors'].append({'error': 'No document links found; provide official PDF or spreadsheet URLs'})
        for source_url, local_path in [(url, None) for url in urls] + [(url, path) for path, url in local_files]:
            try:
                publisher = policy.publisher(source_url)
                remaining = min(policy.max_bytes, policy.max_total_bytes - total)
                if remaining <= 0:
                    raise ValueError('Total public download byte limit exceeded')
                # A failed stream can have consumed its entire allowance. Keep
                # that reservation on failure rather than granting it again.
                total += remaining
                if local_path is None:
                    url, headers, body = collector.fetch(source_url, remaining)
                    publisher = policy.publisher(url)
                    retrieved_at = datetime.now(timezone.utc).isoformat()
                else:
                    url = source_url
                    headers, body, retrieved_at = _read_local(local_path, remaining)
                total -= remaining - len(body)
                media_type = headers.get('content-type', '').split(';', 1)[0].strip().lower()
                suffix = Path(urlsplit(url).path).suffix.lower()
                if suffix not in TYPES:
                    suffix = next((ext for ext, mime in TYPES.items() if mime == media_type), '')
                if suffix not in TYPES or media_type not in {TYPES[suffix], 'application/octet-stream'}:
                    raise ValueError('Only PDF and supported spreadsheet files are accepted')
                if not body or not body.startswith(b'%PDF-' if suffix == '.pdf' else b'PK\x03\x04'):
                    raise ValueError('Document bytes do not match the declared file type')
                digest = hashlib.sha256(body).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                filename = 'public-' + digest[:16] + suffix
                _write_new(folder / filename, body)
                manifest['documents'].append({'source_url': source_url, 'url': url,
                    'publisher': publisher, 'retrieved_at': retrieved_at,
                    'collected_by_person': local_path is not None,
                    'sha256': digest, 'size_bytes': len(body), 'type': suffix[1:], 'media_type': media_type,
                    'filename': filename, 'origin': 'public_document', 'company': policy.company,
                    'website': policy.website, 'notice': PUBLIC_NOTICE})
            except (ValueError, OSError) as exc:
                manifest['errors'].append({'source_url': source_url, 'error': str(exc)})
    except (ValueError, OSError) as exc:
        manifest['errors'].append({'source_url': policy.website, 'error': str(exc)})
    finally:
        _write_new(folder / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    return manifest


def import_documents(store, tenant_id, room_id, folder):
    """Keep the same isolated parser, document table and deal update as uploads."""
    from delivery.ingestion import ingest_upload
    from delivery.storage import read_source_bytes
    from schemas import DealStatus
    room = store.get_workspace(tenant_id, workspace_id=room_id)
    if not room or not room.deal_id:
        raise ValueError('A room associated with a deal is required')
    lead = store.get_lead(tenant_id, room.lead_id)
    if not lead or lead.promoted_deal_id != room.deal_id:
        raise ValueError('Room company association changed')
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if (manifest['origin'] != 'public_document' or manifest['company'] != lead.company_name
            or not lead.company_profile or manifest['website'] != normalize_url(lead.company_profile.website)):
        raise ValueError('Public archive belongs to another company')
    imported = []
    for record in manifest['documents']:
        filename = record['filename']
        if Path(filename).name != filename or '\\' in filename:
            raise ValueError('Invalid public archive filename')
        source = folder / filename
        raw = read_source_bytes(source)
        if hashlib.sha256(raw).hexdigest() != record['sha256'] or len(raw) != record['size_bytes']:
            raise ValueError('Public archive integrity check failed')
        existing = store.get_documents_for_deal(tenant_id, room.deal_id)
        if any(d.workbook_inventory.get('public_source', {}).get('sha256') == record['sha256'] for d in existing):
            continue
        document = ingest_upload(source, tenant_id, room.deal_id)
        identity = getattr(store, 'authenticated_identity', None)
        if identity is not None:
            from security.identity import has_access
            if not has_access(store.conn, identity.user_id, tenant_id):
                raise PermissionError('Room access revoked during public document ingestion')
        # Document has an extensible metadata container; keep provenance there
        # for PDFs too, so it survives storage and binds the room input revision.
        document.workbook_inventory['public_source'] = record
        store.save_document(document)

        def append(deal):
            deal.document_ids.append(document.id)
            deal.status = DealStatus.INGESTED

        store.update_deal(tenant_id, room.deal_id, append)
        imported.append(document.id)
    return imported


def research_room(store, tenant_id, company, website):
    """Operator-created research room; never assert a company engagement."""
    from agents.core.planner_agent import promote_lead_to_deal
    from agents.analysis.operating_workflow import reconcile_workspace
    from schemas import CompanyProfile, SourcedLead
    website = normalize_url(website)
    if store.get_company_by_website(tenant_id, website):
        raise ValueError('Company already exists; choose its existing room with --room')
    profile = CompanyProfile(tenant_id=tenant_id, name=company, website=website,
        identity_status='unresolved', provenance={'origin': 'public_document', 'notice': PUBLIC_NOTICE})
    store.save_company(profile)
    lead = SourcedLead(tenant_id=tenant_id, company_name=company, company_id=profile.id, company_profile=profile)
    store.save_lead(lead)
    deal = promote_lead_to_deal(store, lead)
    room = reconcile_workspace(store, lead)
    room.deal_id = deal.id
    store.save_workspace(room, expected_revision=room.revision)
    return room


def adopt_room(store, tenant_id, room, website):
    """Give an existing company room the deal its public documents attach to; the operator states the website and no engagement is asserted."""
    from agents.core.planner_agent import promote_lead_to_deal
    lead = store.get_lead(tenant_id, room.lead_id)
    website = normalize_url(website)
    profile = lead.company_profile
    if profile.website and normalize_url(profile.website) != website:
        raise ValueError('This room records a different official website')
    if not profile.website:
        profile.website = website
        store.save_company(profile)
        store.save_lead(lead)
    if not lead.promoted_deal_id:
        promote_lead_to_deal(store, lead)
    room = store.get_workspace(tenant_id, workspace_id=room.id)
    room.deal_id = store.get_lead(tenant_id, lead.id).promoted_deal_id
    store.save_workspace(room, expected_revision=room.revision)
    return room


def public_basis(fact_base):
    evidence = fact_base.get('facts', []) + fact_base.get('workbook_cells', [])
    public = [fact for fact in evidence if fact.get('provenance', {}).get('origin') == 'public_document']
    if not public:
        return None
    if len(public) == len(evidence):
        return PUBLIC_NOTICE
    return ('Prepared from public publications and other room materials. Public sources are marked individually; '
            'those materials were not supplied to the preparer or endorsed by the company. '
            'The materials have not been independently verified.')
