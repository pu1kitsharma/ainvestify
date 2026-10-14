"""Bounded retrieval of exact narrative fragments, never category inference.

Lexical indicators select source text, not facts or generated answers. Bare
entity/category lists and numeric tables supply no narrative view. Original
passage bytes-as-text and offsets remain unchanged, including escaped newlines.
"""
import re

from agents.research.investment_memo import Source

_ACTION = re.compile(
    r'\b(?:build(?:s|ing)?|built|distribut(?:e|es|ed|ing)|leverag(?:e|es|ed|ing)|'
    r'enabl(?:e|es|ed|ing)|operat(?:e|es|ed|ing)|provid(?:e|es|ed|ing)|'
    r'offer(?:s|ed|ing)?|run(?:s|ning)?|ran|stay(?:s|ed|ing)?|'
    r'driv(?:e|es|ing|en)|drove|grow(?:s|ing)?|grew|grown|'
    r'claim(?:s|ed|ing)?|report(?:s|ed|ing)?)\b|'
    r'\bno\s+\w|\blimited\s+overlap\b|\bfirst[- ]mover\b', re.I)
_CONNECTOR = re.compile(r'\b(?:a|an|the|and|or|of|to|for|with|through|by|from|as|in|that|which|while|if)\b', re.I)
_NUMERIC = re.compile(r'(?<![A-Za-z])[-+]?\d[\d,.]*(?:%|\b)')
_TABLE_TERMS = re.compile(r'\b(?:FY\d{2,4}|Q[1-4]|USD|INR|EUR|GBP|Mn|Bn|million|billion|'
    r'revenue|sales|premium|GWP|ARR|EBITDA|profit|margin|cash|burn|valuation|income|'
    r'funding|actual|target|projection|projected|potential)\b', re.I)


def _numeric_row(text):
    if not _NUMERIC.search(text):
        return False
    residual = _NUMERIC.sub(' ', _TABLE_TERMS.sub(' ', text))
    # One or two residual row-label words cannot turn a numeric table into prose.
    return len(re.findall(r'[A-Za-z]+', residual)) <= 2


def _bare_list(text):
    words = re.findall(r'[A-Za-z]+', text)
    content = [word for word in words if not _CONNECTOR.fullmatch(word)]
    return bool(content) and all(word[0].isupper() for word in content)


def _continuation(text):
    if not text or _numeric_row(text) or _bare_list(text):
        return False
    if _ACTION.search(text):
        return True
    if any(mark in text for mark in ('|', '•', ',')) or _bare_list(text):
        return False
    return bool(_CONNECTOR.search(text)) and len(re.findall(r'[A-Za-z]+', text)) >= 3


def literal_narrative_views(source):
    """Return <=6 exact 15–600-character fragments with original offsets.

    Each fragment begins on a line with a generic narrative/action/absence
    indicator and includes up to three adjacent narrative continuation lines.
    No fallback opens entity diagrams or financial rows to the author.
    """
    source = Source.model_validate(source)
    passage = source.passage
    separators = list(re.finditer(r'\n|\\n', passage))
    starts = [0, *(match.end() for match in separators)]
    ends = [*(match.start() for match in separators), len(passage)]
    lines = list(zip(starts, ends))
    result, index = {}, 0
    while index < len(lines) and len(result) < 6:
        start, end = lines[index]
        line = passage[start:end]
        if not _ACTION.search(line) or _numeric_row(line) or _bare_list(line):
            index += 1
            continue
        last = index
        while last + 1 < len(lines) and last < index + 3:
            next_start, next_end = lines[last + 1]
            if not _continuation(passage[next_start:next_end]) or next_end - start > 600:
                break
            last += 1
            end = next_end
        if end - start > 600:
            end = start + 600
            boundary = passage.rfind(' ', start, end)
            if boundary > start:
                end = boundary
        while start < end and passage[start].isspace(): start += 1
        while end > start and passage[end - 1].isspace(): end -= 1
        if 15 <= end - start <= 600:
            eid = f'{source.id}.n{len(result) + 1:03d}'
            result[eid] = {'source_id': source.id, 'start': start, 'end': end,
                           'exact_text': passage[start:end]}
        index = last + 1
    if not result:
        raise ValueError('Source has no bounded literal narrative view; category lists and numeric rows are not narrative evidence')
    return result
