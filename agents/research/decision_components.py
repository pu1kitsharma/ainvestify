"""Generic component validators authored by Claude Code and locally reviewed.

Only structural bounds and explicit financial-label families are checked here.
Semantic purpose, source truth and present-baseline assumptions require recorded
local review. Projection returns the original component strings exactly.
"""
import re
import unicodedata
from collections.abc import Mapping

_KEYS = {
    'risk': ('failure_condition', 'prospective_consequence'),
    'diligence': ('requested_verification_records', 'decision_relevance'),
}
MIN_COMPONENT_CHARS = 45
MAX_COMPONENT_CHARS = 210
MAX_TOTAL_CHARS = 421

_FAMILY_WORDS = {
    'profit': ('profit', 'profits', 'profitable', 'profitability'),
    'revenue': ('revenue', 'revenues'),
    'income': ('income', 'incomes'),
    'margin': ('margin', 'margins'),
    'ebitda': ('ebitda',),
    'earnings': ('earnings',),
    'cash': ('cash',),
    'funding': ('funding', 'fundings'),
    'valuation': ('valuation', 'valuations'),
    'sales': ('sales',),
    'premium': ('premium', 'premiums'),
    'gwp': ('gwp',),
    'arr': ('arr',),
    'burn': ('burn',),
    'cost': ('cost', 'costs'),
    'expense': ('expense', 'expenses'),
    'payout': ('payout', 'payouts'),
    'tam': ('tam',),
    'arpu': ('arpu',),
    'gmv': ('gmv',),
}
_WORD_FAMILY = {w: f for f, ws in _FAMILY_WORDS.items() for w in ws}
# Alphanumeric tokens; a token directly after 'non-' is skipped (non-profit).
_TOKEN = re.compile(r'(?<![^\W_])(?<!non-)[^\W_]+')
_BAD_CATEGORIES = ('Cc', 'Cf', 'Zl', 'Zp')


def financial_label_families(text):
    if not isinstance(text, str):
        raise ValueError('text must be a string')
    found = set()
    for match in _TOKEN.finditer(text.lower()):
        family = _WORD_FAMILY.get(match.group(0))
        if family:
            found.add(family)
    return found


def validate_financial_label_binding(text, quote):
    if not isinstance(quote, str):
        raise ValueError('quote must be a string')
    missing = financial_label_families(text) - financial_label_families(quote)
    if missing:
        raise ValueError('financial labels not in quote: ' + ', '.join(sorted(missing)))


def _check_component(name, value):
    if not isinstance(value, str):
        raise ValueError(name + ' must be a string')
    if not value.strip():
        raise ValueError(name + ' is blank')
    if any(unicodedata.category(c) in _BAD_CATEGORIES for c in value):
        raise ValueError(name + ' contains control characters')
    if not MIN_COMPONENT_CHARS <= len(value) <= MAX_COMPONENT_CHARS:
        raise ValueError(name + ' length outside %d-%d' % (MIN_COMPONENT_CHARS, MAX_COMPONENT_CHARS))


def validate_decision_components(kind, unit, quote, minimum_characters, *, bind_financial_labels=True):
    if not isinstance(bind_financial_labels, bool):
        raise ValueError('bind_financial_labels must be a bool')
    if not isinstance(kind, str) or kind not in _KEYS:
        raise ValueError('unknown kind')
    if isinstance(minimum_characters, bool) or not isinstance(minimum_characters, int) or minimum_characters < 1:
        raise ValueError('minimum_characters must be a positive integer')
    keys = _KEYS[kind]
    if not isinstance(unit, Mapping) or len(unit) != len(keys) or set(unit) != set(keys):
        raise ValueError('unit must have exactly keys: ' + ', '.join(keys))
    for key in keys:
        _check_component(key, unit[key])
    joined = unit[keys[0]] + ' ' + unit[keys[1]]
    if not minimum_characters <= len(joined) <= MAX_TOTAL_CHARS:
        raise ValueError('joined length outside %d-%d' % (minimum_characters, MAX_TOTAL_CHARS))
    if bind_financial_labels:
        validate_financial_label_binding(joined, quote)
    return joined
