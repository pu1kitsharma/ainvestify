"""Generic temporal binding authored by Claude Code, adapted for local evidence packets.

Returns recorded selections and exact source spans; never writes company prose.
Semantic source interpretation remains an independent local-model review.
"""
import copy
import re
from typing import Any, Dict, List, Optional, Set

BASES = frozenset(
    ['historical_target', 'dated_target', 'historical_observation', 'dated_observation', 'undated_target', 'undated_report']
)
DATED_BASES = BASES - frozenset(['undated_target', 'undated_report'])

_MONTHS = (
    'January|February|March|April|May|June|July|August|September|October|'
    'November|December|Sept|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec'
)
_B = '(?<![A-Za-z0-9])'
_E = '(?![A-Za-z0-9])'

PERIOD_RE = re.compile(
    _B + '(?:FY[ ]*(?:[0-9]{4}|[0-9]{2})|(?:' + _MONTHS +
    ')(?:[ ]+|[ ]*[/-][ ]*)(?:[0-9]{4}|[0-9]{2})|(?:19|20)[0-9]{2})' + _E,
    re.IGNORECASE,
)


def _fail(reason: str) -> None:
    # Reasons are fixed strings; never include caller-supplied text.
    raise ValueError(reason)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_id(value: Any) -> bool:
    return isinstance(value, str) and value != ''


def period_tokens(text: str) -> Set[str]:
    return {match.group(0) for match in PERIOD_RE.finditer(text)}


def select_temporal_binding(
    claims: List[Dict[str, Any]],
    claim_id: str,
    span_id: str,
    basis: str,
    primary_period: Optional[str],
) -> Dict[str, Any]:
    if not isinstance(claims, list):
        _fail('claims must be a list')
    if not _is_id(claim_id) or not _is_id(span_id):
        _fail('invalid identifier')
    if not isinstance(basis, str) or basis not in BASES:
        _fail('invalid basis')
    if primary_period is not None and not _is_id(primary_period):
        _fail('invalid primary period')

    seen_claims = set()  # type: Set[str]
    seen_spans = {}
    selected = None
    for claim in claims:
        if not isinstance(claim, dict):
            _fail('malformed claim')
        cid = claim.get('id')
        if not _is_id(cid):
            _fail('malformed claim')
        if cid in seen_claims:
            _fail('duplicate identifier')
        seen_claims.add(cid)
        spans = claim.get('temporal_evidence')
        if not isinstance(spans, list):
            _fail('malformed claim')
        owned_ids = set()
        for span in spans:
            if not isinstance(span, dict):
                _fail('malformed span')
            sid = span.get('id')
            if not _is_id(sid):
                _fail('malformed span')
            if sid in owned_ids:
                _fail('duplicate identifier')
            owned_ids.add(sid)
            identity = (span, claim.get('source_id'), claim.get('source_quote'))
            if sid in seen_spans and seen_spans[sid] != identity:
                _fail('duplicate identifier')
            seen_spans[sid] = identity
        if cid == claim_id:
            selected = claim
    if selected is None:
        _fail('claim not found')

    owned = [s for s in selected['temporal_evidence'] if s['id'] == span_id]
    if len(owned) != 1:
        _fail('span not owned by claim')
    span = owned[0]
    if 'claim_id' in span and span['claim_id'] != claim_id:
        _fail('span owner mismatch')

    claim_source = selected.get('source_id')
    span_source = span.get('source_id')
    if not _is_id(claim_source) or not _is_id(span_source):
        _fail('malformed source id')
    if claim_source != span_source:
        _fail('source mismatch')

    quote = selected.get('source_quote')
    if not isinstance(quote, str):
        _fail('malformed source quote')
    start = span.get('start')
    end = span.get('end')
    if not _is_int(start) or not _is_int(end):
        _fail('invalid offsets')
    if start < 0 or end < 0 or start >= end or end > len(quote):
        _fail('invalid offsets')
    exact_text = span.get('exact_text')
    if not isinstance(exact_text, str) or exact_text != quote[start:end]:
        _fail('span text does not match source quote')

    tokens = period_tokens(exact_text)
    if 'period_tokens' in span:
        offered = span['period_tokens']
        if (not isinstance(offered, list) or any(not isinstance(t, str) for t in offered)
                or len(offered) != len(set(offered)) or set(offered) != tokens):
            _fail('period token inventory mismatch')
    if basis in DATED_BASES:
        if primary_period is None or primary_period not in tokens:
            _fail('primary period not found in span')
    else:
        if tokens:
            _fail('undated basis on dated span')
        if primary_period is not None:
            _fail('primary period on undated span')

    return {
        'claim': copy.deepcopy(selected),
        'span': copy.deepcopy(span),
        'basis': basis,
        'primary_period': primary_period,
    }
