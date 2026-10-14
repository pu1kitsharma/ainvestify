"""Stable retrieval for rationale review; selection does not adjudicate claims.

Only the immutable diligence question and requested records drive retrieval.
Mutable rationale text is excluded so rewriting it cannot change its own evidence
scope. Omitted source IDs must be disclosed by the caller; absence judgments are
limited to the selected exact passages, never the company or complete record.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from agents.research.investment_memo import Source, Unknown

_TOKEN = re.compile(r'[A-Za-z][A-Za-z0-9]*|\d+(?:\.\d+)?')
_STOP = frozenset({'the', 'and', 'for', 'that', 'with', 'this', 'from', 'their',
                   'what', 'which', 'would', 'could', 'should', 'into', 'are',
                   'was', 'were', 'has', 'have', 'had', 'its', 'our', 'your',
                   'company', 'source', 'evidence', 'current', 'reported'})
_STOP_V2 = _STOP | frozenset({'a', 'an', 'in', 'on', 'at', 'of', 'to', 'as',
    'by', 'be', 'is', 'it', 'or', 'but', 'if', 'then', 'than', 'not', 'no',
    'so', 'do', 'does', 'did', 'can', 'will', 'may', 'must', 'been', 'being',
    'these', 'those', 'there', 'here', 'given', 'showing', 'provide', 'specific', 'based'})


def _tokens(value, *, decode_delimiters=False):
    # Serialized table cells can retain literal delimiters. Normalize only for
    # retrieval; exact retained passages and displayed quotes stay byte-bound.
    if decode_delimiters:
        value = re.sub(r'\\[nrt]', ' ', value)
    stop = _STOP_V2 if decode_delimiters else _STOP
    return {token.casefold() for token in _TOKEN.findall(value)
            if len(token) > 1 and token.casefold() not in stop}


def unknown_search_terms(item, *, retrieval_version=2):
    """Non-assertion search terms; never return old question/answer prose."""
    if type(retrieval_version) is not int or retrieval_version not in (1, 2):
        raise ValueError('Unknown rationale retrieval version')
    item = Unknown.model_validate(item)
    query = _tokens(' '.join((item.question, item.evidence_needed)),
                    decode_delimiters=retrieval_version == 2)
    if retrieval_version == 2:
        query = {token for token in query if not token[0].isdigit()
                 and token != 'fy' and not re.fullmatch(r'(?:fy|q)\d{1,4}', token)}
    return sorted(query)


def unknown_source_ids(item, sources, linked_source_ids=(), *, max_sources=5,
                       retrieval_version=1):
    """Select linked passages then the three highest lexical matches.

    Unknown links are not currently persisted in the memo schema, so callers may
    supply original explicit links separately. Links are validated and retained;
    too many links fail instead of silently dropping bound evidence. IDs are
    sorted on return to stabilize request hashes independently of source order.
    """
    item = Unknown.model_validate(item)
    sources = [Source.model_validate(source) for source in sources]
    if not isinstance(max_sources, int) or isinstance(max_sources, bool) or not 1 <= max_sources <= 5:
        raise ValueError('Rationale retrieval requires a source cap between one and five')
    if type(retrieval_version) is not int or retrieval_version not in (1, 2):
        raise ValueError('Unknown rationale retrieval version')
    indexed = {source.id: source for source in sources}
    if not sources or len(indexed) != len(sources):
        raise ValueError('Rationale retrieval requires unique complete source IDs')
    links = tuple(dict.fromkeys(linked_source_ids))
    if any(source_id not in indexed for source_id in links):
        raise ValueError('Unknown rationale links to an absent source')
    if len(links) > max_sources:
        raise ValueError('Unknown rationale has more explicit links than its source cap')
    # A shared reporting period can outrank the actual diligence topic.
    # Time/number binding is checked separately against exact evidence.
    query = set(unknown_search_terms(item, retrieval_version=retrieval_version))
    source_tokens = {source.id: _tokens(source.passage,
                    decode_delimiters=retrieval_version == 2) for source in sources}
    frequencies = Counter(token for values in source_tokens.values() for token in values)
    count = len(sources)
    scored = sorted(sources, key=lambda source: (
        -sum(math.log((count + 1) / (frequencies[token] + 1)) + 1
             for token in query & source_tokens[source.id]), source.id))
    selected = list(dict.fromkeys((*links, *(source.id for source in scored[:3]))))
    return sorted(selected[:max_sources])
