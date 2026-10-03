"""Bounded same-origin browser rendering for a model-selected public page.

Every browser request is fulfilled by the existing robots-aware, public-IP-pinned
fetcher. Third-party requests and browser-direct network access are blocked.
This is private room research, not permission to publish a site into shared KB.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit

from agents.discovery.web_sources import PublicWebFetcher, SourceError, normalize_url, parse_page


def render_public_page(url: str):
    from playwright.sync_api import sync_playwright

    url = normalize_url(url)
    if urlsplit(url).scheme != "https":
        raise SourceError("blocked", "Browser source rendering requires HTTPS.")
    origin = urlsplit(url).netloc
    fetcher = PublicWebFetcher(read_timeout=8, min_interval=0)
    deadline = time.monotonic() + 25
    fetched = 0
    total_bytes = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(service_workers="block")

            def guarded_request(route):
                nonlocal fetched, total_bytes
                target = route.request.url
                try:
                    normalized = normalize_url(target)
                    if (route.request.method != "GET" or urlsplit(normalized).scheme != "https"
                            or urlsplit(normalized).netloc != origin
                            or fetched >= 20 or time.monotonic() >= deadline):
                        return route.abort()
                    fetcher._allowed(normalized, deadline)
                    status, headers, body = fetcher._request(normalized, deadline, allow_truncate=False)
                    fetched += 1
                    total_bytes += len(body)
                    if total_bytes > 6_000_000:
                        return route.abort()
                    forwarded = {key: value for key, value in headers.items()
                                 if key.casefold() not in {"transfer-encoding", "content-length", "connection", "content-encoding"}}
                    return route.fulfill(status=status, headers=forwarded, body=body)
                except (SourceError, ValueError):
                    return route.abort()

            page.route("**/*", guarded_request)
            response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
            if not response or response.status != 200 or normalize_url(page.url) != url:
                raise SourceError("partial", "Browser render did not load the selected public URL.")
            page.wait_for_timeout(min(2500, max(0, int((deadline-time.monotonic())*1000))))
            if time.monotonic() >= deadline:
                raise SourceError("partial", "Browser render exceeded its time budget.")
            parsed = parse_page(url, page.content())
            if len(parsed.text) < 80:
                raise SourceError("partial", "Browser render yielded no substantive public page text.")
            return parsed
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError("partial", "Bounded public browser rendering failed.") from exc
        finally:
            browser.close()
