"""Equivalent names for geographic filtering; never infer a company's location."""
import re

GROUPS = [ {'united states', 'usa', 'us', 'u.s.', 'united states of america'},
           {'united kingdom', 'uk', 'u.k.', 'great britain'},
           {'united arab emirates', 'uae'}, {'south korea', 'republic of korea'} ]
WORLD = {'', 'global', 'worldwide', 'anywhere', 'any region', 'all regions'}

def aliases(region):
    region = (region or '').strip().casefold()
    return next((group for group in GROUPS if region in group), {region})

def matches_location(region, text):
    return (region or '').strip().casefold() in WORLD or any(
        re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I) for name in aliases(region))
