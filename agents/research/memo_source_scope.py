"""Conservative source packet scoping for distinct local-model memo sections.

Only a financing-only passage is omitted from operating/market sections. When
classification is uncertain or every passage would be omitted, retain all
sources. The reviewer and retained source set still receive every source.
"""
from __future__ import annotations

import json
import re

from agents.inference.model_authorship import digest


_FINANCING = re.compile(
    r'\b(?:funding|financing|fundraise|round|series\s+[a-f]|seed|capital|'
    r'cash\s+receipt|transaction\s+completion|investor\s+announcement)\b', re.I)
_OPERATING = re.compile(
    r'\b(?:product|software|service|customer|buyer|market|revenue|pilot|'
    r'distribution|contract|retention|user|sales)\b', re.I)
_OPERATING_KEYS = {'product', 'products', 'service', 'services', 'customers',
                   'buyer', 'market', 'revenue', 'pilot', 'distribution',
                   'contracts', 'retention', 'sales'}
_FUNDING_KEYS = {'funding', 'financing', 'round', 'stage', 'amount', 'status',
                 'closing', 'cash_receipt', 'investor'}


def _financing_only(source):
    passage = source.get('passage', '')
    try:
        record = json.loads(passage)
    except (ValueError, TypeError):
        record = None
    if isinstance(record, dict):
        keys = {str(key).casefold() for key in record}
        if keys & _OPERATING_KEYS:
            return False
        if keys & _FUNDING_KEYS:
            return True
    return bool(_FINANCING.search(passage) and not _OPERATING.search(passage))


def operating_sources(sources):
    """Retain uncertain mixed passages; never return an empty evidence packet."""
    selected = [source for source in sources if not _financing_only(source)]
    return selected or list(sources)


def scoped_packet(payload, *, operating):
    """Bind a narrowed model packet to the complete source snapshot."""
    all_sources = payload['sources']
    selected = operating_sources(all_sources) if operating else all_sources
    return {**payload, 'sources': selected,
            'complete_source_set_digest': digest(all_sources),
            'source_scope': 'operating_evidence' if operating else 'complete_evidence'}


def draft_cards(packet, *, operating):
    """Small model view of bound cards; provenance remains in the frozen packet.

    The section receives every authored finding and exact quote in its selected
    cards. Repeated URLs, hashes and response IDs stay in the packet digest,
    rather than consuming the local model's limited context for each section.
    """
    from agents.research.memo_evidence_packet import section_cards
    selected = section_cards(packet, operating=operating)
    cards = [{key: card[key] for key in (
        'source_id', 'title', 'attribution', 'version', 'findings')}
        for card in selected]
    complete = packet['coverage']['source_ids']
    chosen = [card['source_id'] for card in cards]
    scope = {'scope': 'operating_evidence' if operating else 'complete_evidence',
             'complete_source_ids': complete,
             'selected_source_ids': chosen,
             'omitted_source_ids': [source_id for source_id in complete
                                    if source_id not in chosen]}
    return cards, scope
