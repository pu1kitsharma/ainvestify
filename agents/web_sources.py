"""Bounded public HTML collection. No browser, login, proxy, or paid service.

Resolve every hop, reject non-public addresses, and connect to the validated IP
with the original TLS hostname. This prevents DNS rebinding between validation
and connection. robots.txt is respected; it is not a substitute for site terms.
"""
from __future__ import annotations

import io
import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import urllib3

USER_AGENT = "AinvestifyResearch/0.1"
MAX_BYTES = 3_000_000


class SourceError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def normalize_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        if (p.scheme not in {"http", "https"} or not p.hostname or p.username
                or p.password or p.port not in {None, 80, 443}
                or any(ord(c) < 33 for c in url) or "\\" in url or "%" in p.netloc):
            raise ValueError("invalid URL")
        host = p.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if ":" in host:
            host = f"[{host}]"
        port = f":{p.port}" if p.port else ""
        return urlunsplit((p.scheme, host + port, p.path or "/", p.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise SourceError("blocked", "Use a public HTTP(S) URL without credentials or custom ports.") from exc


def public_addresses(url: str) -> list[str]:
    p = urlsplit(normalize_url(url))
    try:
        addresses = list(dict.fromkeys(
            item[4][0] for item in socket.getaddrinfo(
                p.hostname, p.port or (443 if p.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        ))
    except OSError as exc:
        raise SourceError("failed", "Could not resolve source hostname.") from exc
    if not addresses or any(not ipaddress.ip_address(a).is_global or ipaddress.ip_address(a).is_multicast for a in addresses):
        raise SourceError("blocked", "Private, local, and reserved network addresses are not allowed.")
    return addresses


@dataclass
class Page:
    url: str
    title: str
    text: str
    links: list[dict[str, str]] = field(default_factory=list)
    truncated: bool = False
    directory_entries: list[dict[str, str]] = field(default_factory=list)
    # Complete visible HTML blocks, before any preparation context budget.
    # Kept separately from flat text for callers that must not split sentences.
    content_blocks: list[str] = field(default_factory=list)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self.links: list[dict[str, str]] = []
        self.hidden = 0
        self.in_title = False
        self.href = None
        self.anchor: list[str] = []
        self.result_link = False
        self.text_scopes = []
        self.link_navigation = False
        self.content_blocks = []
        self.block_parts = []

    def flush_block(self):
        if self.block_parts:
            self.content_blocks.append(' '.join(self.block_parts))
            self.block_parts = []

    BLOCK_TAGS = {'p','div','section','article','header','footer','main','ul','ol','li',
                  'table','tr','h1','h2','h3','h4','h5','h6','blockquote','br','hr'}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in self.BLOCK_TAGS:
            self.flush_block()
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            # Structural navigation only: never erase an entire footer, which
            # can contain service-entity, tax and pricing qualifications.
            tokens = set(re.split(r'[^a-z0-9]+', ((attributes.get('class') or '')+' '+(attributes.get('id') or '')).lower()))
            navigation = tag == 'nav' or attributes.get('role', '').lower() in {'navigation','menu','menubar'} or bool(tokens & {'navbar','navigation','nav','menu'})
            self.text_scopes.append((tag, navigation))
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "title":
            self.in_title = True
        if tag == "a":
            self.href = attributes.get("href")
            self.anchor = []
            self.result_link = "result__a" in attributes.get("class", "").split()
            self.link_navigation = any(excluded for _, excluded in self.text_scopes)

    def handle_endtag(self, tag):
        if tag in self.BLOCK_TAGS:
            self.flush_block()
        for index in range(len(self.text_scopes)-1, -1, -1):
            if self.text_scopes[index][0] == tag:
                del self.text_scopes[index:]
                break
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.hidden = max(0, self.hidden - 1)
        if self.hidden:
            return
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.href:
            self.links.append({"url": self.href, "label": " ".join(self.anchor),
                               "navigation": self.link_navigation,
                               **({"kind": "search_result"} if self.result_link else {})})
            self.href = None

    def handle_data(self, data):
        if self.hidden:
            return
        value = " ".join(data.split())
        if value:
            ui_label=(self.href or any(tag=='button' for tag,_ in self.text_scopes)) and value.casefold().rstrip(' →↗>') in {'skip to content','open main menu','close menu','log in','sign in','get started','learn more','read more'}
            if not self.in_title and not ui_label and not any(excluded for _, excluded in self.text_scopes):
                self.parts.append(value)
                self.block_parts.append(value)
            if self.in_title:
                self.title.append(value)
            if self.href:
                self.anchor.append(value)


def parse_page(url: str, html: str) -> Page:
    parser = PageParser()
    parser.feed(html)
    parser.flush_block()
    links = []
    seen = set()
    # Keep navigation destinations for discovery, but spend the link budget on
    # body sources first. Menu labels are not company evidence.
    for link in sorted(parser.links, key=lambda link: link.get('navigation', False)):
        try:
            target = normalize_url(urljoin(url, link["url"]))
        except SourceError:
            continue
        if target not in seen:
            links.append({"url": target, "label": link["label"][:200],
                          **({"kind": link["kind"]} if "kind" in link else {})})
            seen.add(target)
    text = " ".join(parser.parts)
    from agents.public_directories import parse_directory_entries
    entries = parse_directory_entries(url, html)
    blocks=[]; size=0
    for block in parser.content_blocks:
        if size+len(block)+bool(blocks)>24000:
            break
        size+=len(block)+bool(blocks);blocks.append(block)
    # A long body catalogue must not hide an observed primary pricing link
    # behind the link cap. Keep body-first discovery order and reserve at most
    # four slots for direct commercial destinations omitted by that cap.
    commercial=[link for link in links[100:] if urlsplit(link['url']).path.strip('/').casefold() in {'pricing','fees','tariff','plans'}][:4]
    selected_links=links[:100-len(commercial)]+commercial
    return Page(url, " ".join(parser.title), text[:24000], selected_links, len(text) > 24000 or len(links) > 100, entries, blocks)


class PublicWebFetcher:
    def __init__(self, read_timeout=5):
        self.read_timeout = read_timeout
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}

    def _request(self, url: str, deadline: float, allow_truncate: bool = False) -> tuple[int, dict, bytes]:
        from agents.preparation_budget import ACTIVE_BUDGET
        budget=ACTIVE_BUDGET.get()
        if budget:deadline=min(deadline,time.monotonic()+budget.remaining())
        addresses = public_addresses(url)
        p = urlsplit(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError("failed", "Source time budget exceeded.")
        interval = max(0, 1 - (time.monotonic() - self.last_request.get(p.netloc, 0)))
        if interval:
            time.sleep(interval)
        self.last_request[p.netloc] = time.monotonic()
        kwargs = dict(host=addresses[0], port=p.port or (443 if p.scheme == "https" else 80),
                      timeout=urllib3.Timeout(connect=min(5, remaining), read=min(self.read_timeout, remaining)),
                      retries=False)
        pool = (urllib3.HTTPSConnectionPool(**kwargs, server_hostname=p.hostname,
                                          assert_hostname=p.hostname, cert_reqs="CERT_REQUIRED")
                if p.scheme == "https" else urllib3.HTTPConnectionPool(**kwargs))
        response = None
        try:
            response = pool.urlopen("GET", urlunsplit(("", "", p.path or "/", p.query, "")),
                                    headers={"Host": p.netloc, "User-Agent": USER_AGENT,
                                             "Accept": "text/html,text/plain;q=0.9", "Accept-Encoding": "identity"},
                                    redirect=False, preload_content=False, assert_same_host=False)
            if response.status != 200:
                return response.status, dict(response.headers), b""
            chunks = []
            size = 0
            while True:
                if time.monotonic() > deadline:
                    raise SourceError("failed", "Source time budget exceeded.")
                chunk = response.read(16384, decode_content=False)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    if allow_truncate:
                        chunks.append(chunk[:MAX_BYTES - (size - len(chunk))])
                        return response.status, {**dict(response.headers), "X-Ainvestify-Truncated": "true"}, b"".join(chunks)
                    raise SourceError("blocked", "Source exceeds the 3 MB page limit.")
                chunks.append(chunk)
            return response.status, dict(response.headers), b"".join(chunks)
        except (urllib3.exceptions.HTTPError, OSError) as exc:
            raise SourceError("failed", "Source connection failed or timed out.") from exc
        finally:
            if response:
                response.close()
            pool.close()

    def _allowed(self, url: str, deadline: float) -> None:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robots:
            robots_url = origin + "/robots.txt"
            for _ in range(4):
                status, headers, body = self._request(robots_url, deadline)
                if status not in {301, 302, 303, 307, 308}:
                    break
                location = headers.get("Location") or headers.get("location")
                if not location:
                    raise SourceError("blocked", "robots.txt redirect has no destination.")
                robots_url = normalize_url(urljoin(robots_url, location))
                # _request validates and pins every redirected destination IP.

            parser = RobotFileParser()
            if status == 404:
                parser.parse([])
            elif status == 200:
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
            else:
                raise SourceError("rate_limited" if status == 429 else "blocked",
                                  f"robots.txt returned HTTP {status}; collection paused for this source.")
            self.robots[origin] = parser
        parser = self.robots[origin]
        if not parser.can_fetch(USER_AGENT, url):
            raise SourceError("blocked", "Source disallows this crawler in robots.txt.")
        delay = parser.crawl_delay(USER_AGENT) or 0
        wait = max(0, delay - (time.monotonic() - self.last_request.get(p.netloc, 0)))
        if wait:
            if wait + 1 >= deadline - time.monotonic():
                raise SourceError("partial", f"Source crawl delay of {delay}s exceeds the remaining request budget.")
            time.sleep(wait)

    def fetch(self, url: str) -> Page:
        url = normalize_url(url)
        deadline = time.monotonic() + 25
        for _ in range(4):
            self._allowed(url, deadline)
            status, headers, body = self._request(url, deadline, allow_truncate=True)
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("Location") or headers.get("location")
                if not location:
                    raise SourceError("failed", "Redirect has no destination.")
                url = normalize_url(urljoin(url, location))
                continue
            if status != 200:
                raise SourceError("rate_limited" if status == 429 else "blocked" if status in {202, 401, 403} else "failed",
                                  f"Source returned HTTP {status}.")
            content_type = headers.get("Content-Type", headers.get("content-type", "")).lower()
            encoding = headers.get("Content-Encoding", headers.get("content-encoding", "identity")).lower()
            if encoding in {"identity", ""} and "application/pdf" in content_type:
                if headers.get("X-Ainvestify-Truncated") == "true":
                    raise SourceError("partial", "PDF exceeds download budget; incomplete PDFs cannot be parsed.")
                return parse_pdf(url, body)
            if encoding not in {"identity", ""} or not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml+xml")):
                raise SourceError("blocked", "Only uncompressed HTML/text pages are supported in this collector.")
            page = parse_page(url, body.decode("utf-8", errors="replace"))
            page.truncated = page.truncated or headers.get("X-Ainvestify-Truncated") == "true"
            if len(page.text) < 80:
                raise SourceError("partial", "No usable page text; this source may require JavaScript or login.")
            return page
        raise SourceError("blocked", "Too many redirects.")


def parse_pdf(url: str, body: bytes) -> Page:
    """Collect bounded public PDF text; scanned documents remain explicit gaps."""
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(body)) as pdf:
            parts = []
            size = 0
            truncated = len(pdf.pages) > 10
            for number, page in enumerate(pdf.pages[:10], 1):
                text = page.extract_text() or ""
                parts.append(f"[PDF page {number}] {text}")
                size += len(text)
                if size >= 24000:
                    truncated = True
                    break
            text = " ".join(" ".join(parts).split())
            if size < 80:
                raise SourceError("partial", "PDF has insufficient selectable text; OCR or company input is needed.")
            title = str((pdf.metadata or {}).get("Title") or "Public document")[:200]
            return Page(url, title, text[:24000], [], truncated)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("partial", "Public PDF could not be parsed.") from exc
