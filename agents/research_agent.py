"""
Market Research Agent — architecture doc §5.4.

Two distinct kinds of finding, deliberately never blended into the same
confidence tier as a cited financial figure from the deal's own documents
(§10.5's explicit rule -- these are supporting/corroborating signal, not
independent verification of the company's self-reported numbers):

1. Live lookups against the zero-budget, ToS-legitimate sources in §10.1:
   GitHub (OSS traction), HN/Algolia (qualitative mentions), SEC EDGAR
   (public-company context/comps), Wikipedia (structured background). No
   API key required for any of these; SEC EDGAR requires a descriptive
   User-Agent identifying the actual requester, per its own published
   policy -- see SEC_EDGAR_CONTACT below.

2. RAG over a small local corpus of hand-authored sector notes (FAISS +
   bge-large via Ollama, matching the model choice in §5.4). Phase 0 has
   no real multi-deal corpus yet -- research_corpus/sector_notes.json seeds
   a handful of general SaaS/hardware benchmark notes to prove the
   retrieval mechanism works. This should grow into a real corpus of
   prior-deal sector notes over time, not stay hardcoded (§5.4's actual
   intent is retrieval over "a corpus of prior deals/sector notes").

Every finding carries source_url/source_type/retrieved_at (internal notes
use source_url=None and cite the note id in source_type's counterpart
instead) -- the same provenance discipline §7 requires of extracted fields.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
import ollama
import requests

from schemas import ResearchFinding

# SEC EDGAR's fair-access policy and Wikimedia's User-Agent policy both
# require a descriptive User-Agent identifying the actual requester
# (https://www.sec.gov/os/webmaster-faq#developers,
# https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)
# -- a generic library UA gets blocked outright (confirmed: Wikipedia
# returns 403 for requests' default UA). This defaults to a clearly-fake
# placeholder on purpose: fill in RESEARCH_AGENT_CONTACT with a real
# org/contact-email before relying on this beyond local smoke-testing,
# rather than silently sending someone's personal information to a third
# party without them choosing to.
RESEARCH_AGENT_CONTACT = os.environ.get(
    "RESEARCH_AGENT_CONTACT", "DealAutomationPhase0 REPLACE-ME@example.com"
)

CORPUS_PATH = Path(__file__).parent.parent / "research_corpus" / "sector_notes.json"
EMBED_MODEL = "bge-large"

HTTP_TIMEOUT = 8


def _placeholder_contact_warning() -> Optional[str]:
    if "REPLACE-ME" in RESEARCH_AGENT_CONTACT:
        return (
            "RESEARCH_AGENT_CONTACT is still the placeholder value -- SEC EDGAR and "
            "Wikipedia both require a real identifying contact in the User-Agent, not "
            "a generic string. Set the RESEARCH_AGENT_CONTACT env var before relying "
            "on those lookups beyond local testing."
        )
    return None


# --- Live source connectors --------------------------------------------
# Each connector fails soft: a network error, rate limit, or empty result
# returns [] rather than raising, so one flaky source never takes down the
# whole research pass. Real failures are still worth surfacing to a human
# eventually, just not by crashing the agent.

def fetch_github_signal(tenant_id: str, deal_id: str, company_name: str) -> list[ResearchFinding]:
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            # `in:name` requires the company name to appear in the repo's own
            # name, not just anywhere in its README/description -- without
            # this, a plain keyword search sorted by stars surfaces whatever
            # popular unrelated repo happens to mention the term (verified:
            # searching "anthropic" without this returned langchain, not any
            # Anthropic repo). Default relevance sort (no explicit `sort`
            # param) also beats sorting by raw star count for the same reason.
            params={"q": f"{company_name} in:name", "per_page": 3},
            headers={"Accept": "application/vnd.github+json"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except requests.RequestException:
        return []

    findings = []
    for repo in items:
        findings.append(ResearchFinding(
            tenant_id=tenant_id,
            deal_id=deal_id,
            topic="oss_traction",
            content=(
                f"GitHub repo {repo['full_name']}: {repo.get('stargazers_count', 0)} stars, "
                f"{repo.get('forks_count', 0)} forks, last pushed {repo.get('pushed_at', 'unknown')}. "
                f"{repo.get('description') or ''}".strip()
            ),
            source_url=repo.get("html_url"),
            source_type="github",
        ))
    return findings


def fetch_hn_mentions(tenant_id: str, deal_id: str, company_name: str) -> list[ResearchFinding]:
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": company_name, "tags": "story", "hitsPerPage": 3},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except requests.RequestException:
        return []

    findings = []
    for hit in hits:
        title = hit.get("title") or ""
        if company_name.lower() not in title.lower():
            continue  # Algolia's search is fuzzy; keep only real title mentions
        findings.append(ResearchFinding(
            tenant_id=tenant_id,
            deal_id=deal_id,
            topic="qualitative_mentions",
            content=f"HN story: \"{title}\" ({hit.get('points', 0)} points, {hit.get('num_comments', 0)} comments)",
            source_url=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            source_type="hackernews",
        ))
    return findings


def fetch_edgar_mentions(tenant_id: str, deal_id: str, company_name: str) -> list[ResearchFinding]:
    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={"q": f'"{company_name}"'},
            headers={"User-Agent": RESEARCH_AGENT_CONTACT},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
    except (requests.RequestException, ValueError):
        return []

    findings = []
    for hit in hits[:3]:
        source = hit.get("_source", {})
        names = ", ".join(source.get("display_names", []))
        findings.append(ResearchFinding(
            tenant_id=tenant_id,
            deal_id=deal_id,
            topic="public_company_context",
            content=(
                f"Mentioned in an SEC filing by {names}: form {', '.join(source.get('root_forms', []))}, "
                f"filed {source.get('file_date')}."
            ),
            source_url=f"https://www.sec.gov/Archives/edgar/data/{hit.get('_id', '').split(':')[0].lstrip('0') or '0'}",
            source_type="sec_edgar",
        ))
    return findings


def fetch_wikipedia_summary(tenant_id: str, deal_id: str, company_name: str) -> list[ResearchFinding]:
    try:
        resp = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(company_name)}",
            headers={"User-Agent": RESEARCH_AGENT_CONTACT},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    extract = data.get("extract")
    if not extract:
        return []

    return [ResearchFinding(
        tenant_id=tenant_id,
        deal_id=deal_id,
        topic="background",
        content=extract,
        source_url=data.get("content_urls", {}).get("desktop", {}).get("page"),
        source_type="wikipedia",
    )]


# --- Sector-notes RAG (FAISS + bge-large) -------------------------------

class SectorNotesIndex:
    """Small local corpus, embedded and indexed in memory. Rebuilds on each
    process start rather than persisting to disk -- fine at this corpus
    size (single digits to low hundreds of notes); revisit if the corpus
    grows large enough that re-embedding on every startup gets slow."""

    def __init__(self, corpus_path: Path = CORPUS_PATH):
        import faiss  # deferred import: only needed if this class is used

        with open(corpus_path) as f:
            self.notes = json.load(f)

        embeddings = [
            ollama.embed(model=EMBED_MODEL, input=note["text"]).embeddings[0]
            for note in self.notes
        ]
        matrix = np.array(embeddings, dtype="float32")
        faiss.normalize_L2(matrix)  # cosine similarity via normalized inner product
        self.index = faiss.IndexFlatIP(matrix.shape[1])
        self.index.add(matrix)

    def query(self, tenant_id: str, deal_id: str, query_text: str, top_k: int = 2) -> list[ResearchFinding]:
        import faiss

        query_vec = np.array([ollama.embed(model=EMBED_MODEL, input=query_text).embeddings[0]], dtype="float32")
        faiss.normalize_L2(query_vec)
        scores, indices = self.index.search(query_vec, min(top_k, len(self.notes)))

        findings = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            note = self.notes[idx]
            findings.append(ResearchFinding(
                tenant_id=tenant_id,
                deal_id=deal_id,
                topic=f"sector_benchmark:{note['sector']}",
                content=note["text"],
                source_url=None,
                source_type="internal_sector_notes",
            ))
        return findings


def research_deal(
    tenant_id: str,
    deal_id: str,
    company_name: str,
    sector_query: Optional[str] = None,
    sector_index: Optional[SectorNotesIndex] = None,
) -> list[ResearchFinding]:
    """Run every connector for one deal. `sector_query` should describe what
    to benchmark against (e.g. "SaaS Series A burn multiple and runway") --
    pass an already-built `sector_index` to avoid re-embedding the corpus
    on every call within one process."""
    findings: list[ResearchFinding] = []
    findings += fetch_github_signal(tenant_id, deal_id, company_name)
    findings += fetch_hn_mentions(tenant_id, deal_id, company_name)
    findings += fetch_edgar_mentions(tenant_id, deal_id, company_name)
    findings += fetch_wikipedia_summary(tenant_id, deal_id, company_name)

    if sector_query:
        index = sector_index or SectorNotesIndex()
        findings += index.query(tenant_id, deal_id, sector_query)

    return findings
