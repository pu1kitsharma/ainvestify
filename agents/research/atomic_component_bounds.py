"""Reject quantified facts in model-authored hypothetical components.

The pure detector was authored by Claude Code from generic coding context and
reviewed locally. It never changes prose or sources, supplies facts, selects
sources, validates arithmetic or grants semantic approval. Financial labels,
comparative premises and field purpose still need their separate exact-source
checks and recorded local review. Only fresh atomic contracts use this guard.
"""
import re

import unicodedata

_STRIP = ''.join(chr(c) for c in (34, 39, 0x201c, 0x201d, 0x2018, 0x2019, 40, 41, 91, 93,
                                  123, 125, 60, 62, 0xab, 0xbb, 46, 44, 59, 58, 33, 63, 0x2026))

_CUR = r'(?:[$€£¥₹]|[A-Z]{2,3}\$|USD|INR|EUR|GBP|JPY|CNY|CAD|AUD|SGD|AED|CHF|HKD|NZD|KRW|ZAR|BRL|MXN|SEK|NOK|DKK|SAR)'

_NUM = re.compile(r'^[~≈<>≤≥+\-−]?' + _CUR + r'?\d[\d,]*(?:\.\d+)?(?:%|bn|mn|tn|cr|lakh|pct|bps|x|k|m|b)?$', re.I)

_CURMAG = re.compile(r'^[~≈<>≤≥+\-−]?' + _CUR + r'\d[\d,]*(?:\.\d+)?[kmb]$', re.I)

_ORD = re.compile(r'^\d+(?:st|nd|rd|th)$', re.I)

_FISCAL = re.compile(r'^(?:FY|CY|[1-4]Q|Q[1-4]|[12]H|H[12])[\x27’]?\d{0,4}$', re.I)

_SPLIT = re.compile(r'[-–—−/:⁄]')

_MONTHS = re.compile(r'\b(?:January|February|March|April|June|July|August|September|October|November|December)\b', re.I)

_RELDATE = re.compile(r'\b(?:last|next|this|prior|previous|current|fiscal)\s+(?:year|quarter|month|half)\b', re.I)

_NUMWORDS = set(('two three four five six seven eight nine ten eleven twelve twenty thirty forty '
                 'fifty sixty seventy eighty ninety hundred thousand million billion trillion '
                 'percent half double triple doubled tripled').split())

def _is_numeric(tok):
    if not tok:
        return False
    for rx in (_NUM, _CURMAG, _ORD, _FISCAL):
        if rx.match(tok):
            return True
    parts = _SPLIT.split(tok)
    return len(parts) > 1 and all(p and (_NUM.match(p) or _ORD.match(p) or _FISCAL.match(p)) for p in parts)

def _is_numword(tok):
    parts = tok.lower().split('-')
    return bool(tok) and all(p in _NUMWORDS for p in parts)

def leak_hits(text):
    # Detection runs on an NFKC copy; the input text is never modified.
    # Whole-token matching only: mixed letter/digit names (letters first or
    # trailing letters outside the suffix list) are not flagged.
    norm = unicodedata.normalize('NFKC', text)
    hits = []
    for raw in norm.split():
        tok = raw.strip(_STRIP)
        if _is_numeric(tok) or _is_numword(tok):
            hits.append(tok)
    for m in _MONTHS.finditer(norm):
        hits.append(m.group(0).lower())
    for m in _RELDATE.finditer(norm):
        hits.append(' '.join(m.group(0).lower().split()))
    return hits

def validate_unquantified_component(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Atomic component must be nonempty model-authored text')
    hits = leak_hits(text)
    if hits:
        raise ValueError('Quantified/date facts belong only in the source premise: ' + ', '.join(hits))
    return text
