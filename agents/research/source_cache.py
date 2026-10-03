"""Reusable public HTML snapshots; never private uploads or local file paths."""
from dataclasses import asdict
import json

from pydantic import BaseModel
from agents.discovery.web_sources import Page, PublicWebFetcher, normalize_url
from agents.inference.public_cache import PublicResultCache, cache_key


class PageSnapshot(BaseModel):
    url: str
    title: str
    text: str
    links: list[dict[str, str]]
    truncated: bool
    directory_entries: list[dict[str, str]]
    content_blocks: list[str]


def fetch_public_page(url):
    url = normalize_url(url)
    cache = PublicResultCache('sources', ttl_seconds=86400)
    key = cache_key('html_parser_v1','public_page','visible page blocks',json.dumps({'url':url}),PageSnapshot,{})
    row = cache.get(key,PageSnapshot)
    if row:
        return Page(**PageSnapshot.model_validate_json(row['raw_response']).model_dump())
    page = PublicWebFetcher(read_timeout=8).fetch(url)
    cache.put(key,PageSnapshot(**asdict(page)).model_dump_json(),'html_parser_v1',{})
    return page
