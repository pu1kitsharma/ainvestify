"""Exact evidence reconciliation ledger for cited memo prose.

Code extracts typed key/value facts from structured source records, each with
its exact source span and lineage. A local model labels what each cited
assertion claims: which field it is about and with what polarity (not
reported, reported, reported but unverified, verified), or that the mapping is
ambiguous. Code then compares that
model-authored label with the exact typed value in the ledger. Code never
writes memo prose and never decides a recommendation.

For a claim that a field is not reported, three outcomes are kept apart:

- `conflict_value_reported`: the cited record has that field, with a value;
  (and, for a claim that financing is verified, closed or received,
  `conflict_verified_but_status_unknown` when the record reports its own
  status as unknown);
- `consistent_key_missing`: the cited record has no such field;
- `consistent_value_unknown`: the record has the field and reports it unknown.

The same label therefore leads to different outcomes only because the records
differ. A status of "unknown", or doubt about closing or cash receipt, is a
fact about that field only; it never makes a reported amount absent. An
ambiguous label, a claim of verification, and a field the vocabulary cannot
link to a key are left unresolved for the reviewer, never guessed.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from agents.research.investment_memo import _CITATION

LEDGER_CONTRACT = 'evidence-ledger-v7'
_PROSE_FIELDS = ('recommendation_reason', 'investment_thesis', 'business_and_market',
                 'differentiation_and_execution', 'risks_and_countercase', 'diligence_plan')


class LedgerError(ValueError):
    """A structured source could not be turned into exact facts."""


# Generic vocabulary linking a field label to record keys. Structured keys are
# short tokens, so this is a lookup, not prose matching. Closing and cash
# receipt are separate fields: doubt about them says nothing about an amount.
CONCEPTS = {
    # Listed first so "market_size" is never read as a funding amount.
    'market_size': {'market', 'tam', 'sam', 'som'},
    'amount': {'amount', 'size', 'raised', 'sum', 'proceeds', 'value', 'funding',
               'investment', 'consideration'},
    'date': set(),      # resolved by _DATE_KEY below
    'stage': {'stage', 'round', 'label', 'series'},
    'status': {'status', 'state'},
    'closing': {'closing', 'completion', 'completed'},
    'cash_receipt': {'cash', 'received', 'receipt', 'disbursed'},
    'investor': {'investor', 'investors', 'lead', 'backer', 'backers'},
    'valuation': {'valuation'},
    'revenue': {'revenue', 'revenues', 'sales', 'turnover', 'arr', 'mrr'},
    'headcount': {'headcount', 'employees', 'staff'},
    'jurisdiction': {'jurisdiction', 'country', 'headquarters', 'domicile'},
    'entity': {'entity', 'company', 'name'},
    # A claim about something no listed field covers. Never compared.
    'other': set(),
}
# Keys of a nested value that qualify it without being the value itself.
_QUALIFIER_KEYS = {'currency', 'unit', 'units', 'precision', 'scale', 'denomination', 'type',
                   'basis', 'semantics'}
# `not_reported` says the source lacks the field. `unverified` says the source
# reports it but it is not independently established: the opposite of absent.
# `current` says the value is the company's present state, not merely that a
# dated source reports it.
POLARITIES = ('not_reported', 'reported', 'unverified', 'verified', 'current', 'ambiguous')
_DATE_KEY = re.compile(r'(?:^|_)(?:date|dated|year|month|as_of|closed_on|announced_on)$')
_UNKNOWN_VALUES = {'', 'unknown', 'undisclosed', 'not disclosed', 'not available', 'n/a', 'na',
                   'none', 'null', 'tbd', 'unspecified', 'not stated', 'not reported', '-'}


def source_sha256(passage: str) -> str:
    return hashlib.sha256(passage.encode()).hexdigest()


def _structured_source(source) -> bool:
    """Only a JSON object prefix identifies a typed key/value record.

    PDF text can begin with a bracketed heading, citation, or list. Arrays are
    not key/value records for this ledger, even when the passage happens to be
    valid JSON, so their leading bracket is not a structure marker.
    """
    return source.passage.lstrip().startswith('{')


def key_concept(key: str):
    """(concept, how): `head` when the key's last token names it, `mention` otherwise."""
    tokens = [token for token in re.split(r'[^a-z0-9]+',
              re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', key).casefold()) if token]
    if not tokens:
        return None, None
    if _DATE_KEY.search('_'.join(tokens)):
        return 'date', 'head'
    if set(tokens) & CONCEPTS['market_size']:
        return 'market_size', 'head'
    if tokens[-1] == 'size' and set(tokens) & {'team', 'staff', 'company'}:
        return 'headcount', 'head'
    for concept, keys in CONCEPTS.items():
        if tokens[-1] in keys:
            return concept, 'head'
    for concept, keys in CONCEPTS.items():
        if any(token in keys for token in tokens[:-1]):
            return concept, 'mention'
    return None, None


def _unknown(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in _UNKNOWN_VALUES
    if isinstance(value, dict):
        # {"original": null, "currency": "USD"} reports a currency, not an amount.
        bearing = [item for key, item in value.items()
                   if str(key).casefold() not in _QUALIFIER_KEYS]
        return all(_unknown(item) for item in bearing)
    if isinstance(value, list):
        return not value or all(_unknown(item) for item in value)
    return False


def _value_type(value) -> str:
    return ('null' if value is None else 'boolean' if isinstance(value, bool) else
            'number' if isinstance(value, (int, float)) else 'string' if isinstance(value, str)
            else 'list' if isinstance(value, list) else 'object')


def source_facts(source) -> list[dict] | None:
    """Typed facts of one structured record, or None for a prose passage.

    Every fact carries the exact contiguous span of its key and value and the
    offsets of that span, so a reader can check it against the retained
    passage byte for byte.
    """
    passage = source.passage
    if not _structured_source(source):
        return None
    try:
        record = json.loads(passage)
    except ValueError as exc:
        raise LedgerError(f'{source.id}: structured passage is not valid JSON') from exc
    if not isinstance(record, dict) or not record:
        raise LedgerError(f'{source.id}: structured passage is not a key/value record')
    facts, cursor, decoder = [], 0, json.JSONDecoder()
    sha = source_sha256(passage)
    for key, value in record.items():
        match = re.compile(re.escape(json.dumps(key, ensure_ascii=False)) + r'\s*:\s*').search(
            passage, cursor) or re.compile(re.escape(json.dumps(key)) + r'\s*:\s*').search(
            passage, cursor)
        if not match:
            raise LedgerError(f'{source.id}: key {key!r} has no exact span')
        try:
            decoded, end = decoder.raw_decode(passage, match.end())
        except ValueError as exc:
            raise LedgerError(f'{source.id}: value of {key!r} has no exact span') from exc
        if decoded != value:
            raise LedgerError(f'{source.id}: key {key!r} is ambiguous in the passage')
        concept, how = key_concept(key)
        facts.append({'source_id': source.id, 'source_version': source.version,
                      'source_sha256': sha, 'key': key, 'value': value,
                      'value_type': _value_type(value), 'value_unknown': _unknown(value),
                      'concept': concept, 'concept_match': how,
                      'span': passage[match.start():end],
                      'span_start': match.start(), 'span_end': end})
        cursor = end
    return facts


def build_ledger(sources) -> dict:
    """Facts and source lineage for the whole retained source set."""
    lineage, facts = {}, []
    for source in sources:
        extracted = source_facts(source)
        lineage[source.id] = {'version': source.version,
                              'sha256': source_sha256(source.passage),
                              'structured': extracted is not None}
        facts.extend(extracted or [])
    return {'contract': LEDGER_CONTRACT, 'sources': lineage, 'facts': facts}


def cited_assertions(memo, sources) -> list[dict]:
    """Every span of field prose, with the source it is attributed to.

    A span is the exact prose between the previous citation and the next one,
    attributed to that next citation; adjacent citations share one span. The
    prose after a field's last citation is attributed to that last citation,
    so a statement written after the marker is examined too. Nothing is dropped.
    """
    passages = {source.id: source.passage for source in sources}
    found, seen = [], set()
    for field in _PROSE_FIELDS:
        prose = (memo.recommendation_reason if field == 'recommendation_reason'
                 else getattr(memo, field).analysis)
        previous, last = 0, None
        for citation in _CITATION.finditer(prose):
            span = prose[previous:citation.start()].strip().lstrip('.,;: ').strip()
            previous = citation.end()
            if len(span) < 12:
                span = last
            if not span or (field, span, citation.group(1)) in seen:
                continue
            last = span
            seen.add((field, span, citation.group(1)))
            found.append({'field': field, 'source_id': citation.group(1), 'assertion': span,
                          'structured': passages[citation.group(1)].lstrip().startswith('{')})
        tail = prose[previous:].strip().lstrip('.,;: ').strip()
        cited = _CITATION.findall(prose)
        if len(tail) >= 12 and cited and (field, tail, cited[-1]) not in seen:
            seen.add((field, tail, cited[-1]))
            found.append({'field': field, 'source_id': cited[-1], 'assertion': tail,
                          'structured': passages[cited[-1]].lstrip().startswith('{')})
    # Structured records first, then grouped by source.
    return sorted(found, key=lambda item: (not item['structured'], int(item['source_id'][1:])))


def claim_assertions(memo, sources) -> list[dict]:
    """Every claim row that cites a structured record.

    A claim's assertion is rendered to the reader beside its exact excerpt, so
    it is compared with the record exactly like cited prose. `claim_index`
    locates the row inside its field.
    """
    passages = {source.id: source.passage for source in sources}
    found = []
    for field in _PROSE_FIELDS:
        claims = (memo.recommendation_claims if field == 'recommendation_reason'
                  else getattr(memo, field).claims)
        for index, claim in enumerate(claims):
            if passages[claim.source_id].lstrip().startswith('{'):
                found.append({'field': field, 'source_id': claim.source_id,
                              'assertion': claim.assertion, 'structured': True,
                              'kind': 'claim', 'claim_index': index})
    return found


def ledger_targets(memo, sources, fields=None) -> list[dict]:
    """Cited prose spans and structured claim rows, optionally for some fields only."""
    targets = [{**target, 'kind': 'prose'} for target in cited_assertions(memo, sources)]
    targets += claim_assertions(memo, sources)
    return [target for target in targets if fields is None or target['field'] in fields]


def target_key(target: dict) -> tuple:
    return (target['kind'], target['field'], target.get('claim_index'), target['assertion'],
            target['source_id'])


def field_labels(ledger: dict) -> list[str]:
    """Labels a mapping may use: the generic fields, then the actual record keys."""
    keys = dict.fromkeys(fact['key'] for fact in ledger['facts'])
    return list(dict.fromkeys([*CONCEPTS, *keys]))


def parse_date(value) -> tuple | None:
    """(year, month, day) from an ISO-like date string; day 0 when only a month is given."""
    match = re.fullmatch(r'\s*(\d{4})-(\d{2})(?:-(\d{2}))?\s*', value) if isinstance(value, str) else None
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
    try:
        date(year, month, day or 1)      # a real calendar date, not just digits
    except ValueError:
        return None
    return year, month, day


def stage_key(label) -> str:
    """A stage label reduced to comparable form: "Seed stage" and "seed round" agree."""
    words = re.findall(r'[a-z0-9]+', str(label).casefold())
    return ' '.join(word for word in words if word not in {'stage', 'round', 'financing', 'funding'})


DATE_SEMANTICS = ('listing_as_of', 'announcement', 'closing', 'reported_date')


def date_interval(value) -> tuple | None:
    """The span of days a date string covers: a month covers the whole month."""
    parsed = parse_date(value)
    if parsed is None:
        return None
    year, month, day = parsed
    return ((year, month, day or 1), (year, month, day or 31))


# Words by which a passage says a round is finished. A date or status may be
# read as a closing only when its excerpt says so.
COMPLETION_WORDS = re.compile(r'\b(?:closed|closes|closing|completed|completes|completion|'
                              r'received|disbursed|finali[sz]ed)\b', re.I)
# Negation or uncertainty anywhere in the excerpt: "does not state whether the
# round has closed" contains a completion word and says nothing was completed.
_UNCERTAIN = re.compile(r"\b(?:not|no|never|n't|without|whether|if|unknown|unstated|unclear|"
                        r"unconfirmed|unverified|pending|expected|expects?|plans?|planned|intends?|"
                        r"may|might|could|would|yet|subject\s+to|to\s+be)\b|n't", re.I)


def affirms_completion(excerpt: str) -> bool:
    """Conservative: the excerpt names a completion and carries no negation or doubt."""
    return bool(COMPLETION_WORDS.search(excerpt)) and not _UNCERTAIN.search(excerpt)


def _key_date_semantics(key: str) -> str:
    tokens = set(re.split(r'[^a-z0-9]+', key.casefold()))
    if tokens & {'listing', 'listed', 'as', 'updated', 'observed'}:
        return 'listing_as_of'
    if tokens & {'announced', 'announcement', 'published'}:
        return 'announcement'
    if tokens & {'closed', 'closing', 'completed', 'completion'}:
        return 'closing'
    return 'reported_date'


def structured_stage_events(ledger: dict, company: str, bound_sources=frozenset()) -> list[dict]:
    """Dated stage events taken from structured records, each bound to its source.

    An event carries the source id, version and hash, the entity the record
    names and whether that is this company, and the exact stage, date and
    status spans. `date_semantics` says what the date is a date of. A record
    without both a reported stage and a parseable date contributes nothing.
    """
    by_source = {}
    for fact in ledger['facts']:
        by_source.setdefault(fact['source_id'], []).append(fact)
    events = []
    for source_id, facts in by_source.items():
        head = lambda concept: [fact for fact in facts if fact['concept'] == concept
                                and fact['concept_match'] == 'head' and not fact['value_unknown']]
        stages, dates = head('stage'), [fact for fact in head('date') if parse_date(fact['value'])]
        if not stages or not dates:
            continue
        status = [fact for fact in facts if fact['concept'] == 'status'
                  and fact['concept_match'] == 'head']
        named = [fact for fact in facts if fact['concept'] == 'entity'
                 and fact['concept_match'] == 'head']
        events.append({
            'source_id': source_id, 'source_version': stages[0]['source_version'],
            'source_sha256': stages[0]['source_sha256'], 'origin': 'structured_record',
            'entity': named[0]['value'] if named else None,
            'entity_match': ('bound' if source_id in bound_sources
                             else _same_entity(company, facts)),
            'stage': str(stages[0]['value']), 'stage_key': stage_key(stages[0]['value']),
            'stage_span': stages[0]['span'],
            'date': dates[0]['value'].strip(), 'date_span': dates[0]['span'],
            'date_interval': [list(bound) for bound in date_interval(dates[0]['value'])],
            'date_semantics': _key_date_semantics(dates[0]['key']),
            'status': ('unknown' if not status or status[0]['value_unknown']
                       else str(status[0]['value'])),
            'status_span': status[0]['span'] if status else None})
    return events


def _current_claim(label: str, facts: list[dict], entity: str, source_id: str, history,
                   as_of_date=None):
    """A claim that a stage is the company's present stage, resting on one record.

    A record reports a stage as of its own date; it never establishes the
    present stage. So an unqualified "currently" is a direct conflict whenever
    the record is dated before the memo's as_of month, or carries no date at
    all. This does not depend on finding anything else: an unavailable stage
    history cannot let the claim through. When the history holds a later-dated
    report with a different stage, it is attached. That later report is still
    only a report: it does not prove its round closed, that cash was received,
    or what the present stage is, and when its entity is not established as
    this company it is attached as such, not treated as fact.
    """
    own = [fact for fact in facts if fact['key'] == label] or [
        fact for fact in facts if fact['concept'] == label and fact['concept_match'] == 'head']
    stage = [fact for fact in own if fact['concept'] == 'stage' and not fact['value_unknown']]
    dates = [fact for fact in facts if fact['concept'] == 'date' and fact['concept_match'] == 'head'
             and parse_date(fact['value'])]
    if not stage:
        return 'unresolved_current_claim', (own or [None])[0]
    if _entity_block(entity):
        return _entity_block(entity), stage[0]
    if not dates:
        return 'conflict_current_but_record_is_undated', {
            **stage[0], 'stage_history': 'not_applicable_record_undated'}
    own_end, own_stage = list(date_interval(dates[0]['value'])[1]), stage_key(stage[0]['value'])
    own_packet = {**stage[0], 'record_date': dates[0]['value'], 'record_date_span': dates[0]['span'],
                  'record_date_semantics': _key_date_semantics(dates[0]['key']),
                  'stage_history': 'unavailable' if history is None else 'built'}
    later = sorted((event for event in history or [] if event['source_id'] != source_id
                    and event['date_interval'][0] > own_end and event['stage_key'] != own_stage),
                   key=lambda event: event['date_interval'][0])
    packet = lambda event: {key: event.get(key) for key in (
        'source_id', 'source_version', 'source_sha256', 'origin', 'entity', 'entity_match',
        'stage', 'stage_span', 'date', 'date_span', 'date_semantics', 'status', 'status_span',
        'excerpt', 'response_id')}
    established = [event for event in later if event['entity_match'] in ('same', 'bound')]
    if established:
        return 'conflict_current_but_later_report_differs', {
            **own_packet, 'later_report': packet(established[-1])}
    current_month = parse_date(as_of_date)[:2] if parse_date(as_of_date) else None
    if current_month and tuple(own_end[:2]) >= current_month:
        # The record is dated in the memo's own month: nothing here contradicts "currently".
        return 'unresolved_current_claim_from_same_month_record', own_packet
    if later:
        # A later report exists but is not established as this company's.
        own_packet['later_report'] = packet(later[-1])
    return 'conflict_current_but_record_is_dated', own_packet


def _same_entity(company: str, facts: list[dict]) -> str:
    """`same`, `different` or `unstated`, from the record's own entity field."""
    named = [fact['value'] for fact in facts if fact['concept'] == 'entity'
             and fact['concept_match'] == 'head' and isinstance(fact['value'], str)]
    if not named:
        return 'unstated'
    plain = lambda text: ' '.join(text.casefold().split())
    return 'same' if any(plain(value) == plain(company) for value in named) else 'different'


def _entity_block(entity: str):
    """Why this record cannot settle a claim about the company, if it cannot."""
    return {'different': 'unresolved_record_names_different_entity',
            'unstated': 'unresolved_record_entity_unstated'}.get(entity)


# Fields whose "verified" claim is about the financing having happened.
_SETTLEMENT_LABELS = {'closing', 'cash_receipt', 'status', 'amount'}


def compare_claim(label: str, polarity: str, facts: list[dict], entity: str = 'unstated',
                  source_id: str | None = None, history=None,
                  as_of_date=None) -> tuple[str, dict | None]:
    """Compare one model-authored (field, polarity) label with the cited record.

    `facts` are the typed facts of the record the assertion cites. Returns the
    finding and the fact it rests on. Only a not-reported claim against a reported
    value is a conflict, and only when the record is established as this
    company's: `entity` is `same` (the record names the company) or `bound`
    (a validated source-to-company binding). A record naming another entity,
    or none, proves nothing about this company. Everything software cannot
    settle is an explicit `unresolved_*` finding.
    """
    if polarity == 'ambiguous':
        return 'unresolved_ambiguous_mapping', None
    if label == 'other':
        return 'unresolved_field_outside_ledger', None
    if polarity == 'current':
        return _current_claim(label, facts, entity, source_id, history, as_of_date)
    exact = [fact for fact in facts if fact['key'] == label]
    head = exact or [fact for fact in facts
                     if fact['concept'] == label and fact['concept_match'] == 'head']
    mention = [fact for fact in facts
               if fact['concept'] == label and fact['concept_match'] == 'mention']
    reported = [fact for fact in head if not fact['value_unknown']]
    if polarity == 'verified':
        # A record reports; it does not verify. When the record itself reports
        # its status as unknown, a claim that the financing is verified, closed
        # or received contradicts the record directly. Otherwise the claim is
        # left to the reviewer with the fact.
        status_unknown = [fact for fact in facts if fact['concept'] == 'status'
                          and fact['concept_match'] == 'head' and fact['value_unknown']]
        if status_unknown and label in _SETTLEMENT_LABELS:
            return _entity_block(entity) or 'conflict_verified_but_status_unknown', status_unknown[0]
        return 'unresolved_verification_claim', (reported or head or mention or [None])[0]
    if not head and mention:
        return 'unresolved_related_key', mention[0]
    if polarity == 'not_reported':
        if reported:
            return _entity_block(entity) or 'conflict_value_reported', reported[0]
        return ('consistent_value_unknown', head[0]) if head else ('consistent_key_missing', None)
    if reported:
        # "Reported but unverified" agrees with a record that reports the value.
        return _entity_block(entity) or ('consistent_reported_unverified' if polarity ==
                                         'unverified' else 'consistent_value_reported'), reported[0]
    # Said to be reported, but the record shows it unknown or has no linked key.
    return ('unresolved_reported_but_unknown', head[0]) if head else (
        'unresolved_no_linked_key', None)


def reconcile(targets: list[dict], mappings: dict, ledger: dict, company: str,
              bound_sources=frozenset(), history=None, as_of_date=None) -> dict:
    """Compare every cited assertion with the facts of the record it cites.

    `targets` are the cited prose assertions and the structured claim rows;
    `mappings` gives, for each one that cites a structured record, the
    model-authored labels and the response that authored them. Software settles one thing only: a direct conflict
    between an absence claim and a reported value. Every other row states why
    it still needs the reviewer; none is called reconciled or supported.
    Coverage is complete only when every structured-cited assertion has a
    recorded mapping. `bound_sources` are source ids whose identity as this
    company's record is established by a validated binding outside the record;
    without it a record must name the company itself. `history` is the
    company's dated stage history across sources, or None when it was not
    built; it is used only for claims that a stage is the present stage.
    """
    by_source = {}
    for fact in ledger['facts']:
        by_source.setdefault(fact['source_id'], []).append(fact)
    rows, unmapped = [], 0
    for target in targets:
        row = {'kind': target['kind'], 'field': target['field'],
               'claim_index': target.get('claim_index'), 'source_id': target['source_id'],
               'assertion': target['assertion'], 'findings': []}
        if not ledger['sources'][target['source_id']]['structured']:
            row['state'] = 'prose_source_reviewer_required'
            rows.append(row)
            continue
        mapping = mappings.get(target_key(target))
        if mapping is None:
            row['state'] = 'unmapped'
            unmapped += 1
            rows.append(row)
            continue
        facts = by_source.get(target['source_id'], [])
        row['mapping_response_id'] = mapping['response_id']
        row['record_entity'] = ('bound' if target['source_id'] in bound_sources
                                else _same_entity(company, facts))
        for claim in mapping['claims']:
            finding, fact = compare_claim(claim['field'], claim['polarity'], facts,
                                          row['record_entity'], target['source_id'], history,
                                          as_of_date)
            row['findings'].append({'label': claim['field'], 'polarity': claim['polarity'],
                'finding': finding, 'fact': None if fact is None else {
                    key: fact[key] for key in ('source_id', 'key', 'value_type', 'value_unknown',
                                               'span', 'span_start', 'span_end', 'source_sha256',
                                               'record_date', 'record_date_span',
                                               'record_date_semantics', 'stage_history',
                                               'later_report')
                    if key in fact}})
        kinds = [item['finding'] for item in row['findings']]
        row['state'] = ('conflict' if any(kind.startswith('conflict_') for kind in kinds) else
                        'unresolved_reviewer_required' if any(kind.startswith('unresolved')
                                                              for kind in kinds) else
                        # No direct conflict found. That is not support: the
                        # reviewer still judges what the assertion says.
                        'no_direct_conflict_reviewer_required')
        rows.append(row)
    states = [row['state'] for row in rows]
    structured = sum(state != 'prose_source_reviewer_required' for state in states)
    coverage = {'contract': LEDGER_CONTRACT,
                'cited_assertions': sum(row['kind'] == 'prose' for row in rows),
                'structured_claim_assertions': sum(row['kind'] == 'claim' for row in rows),
                'structured_cited_assertions': structured,
                'mapped_and_compared': structured - unmapped,
                'conflicts': states.count('conflict'),
                'unresolved_reviewer_required': states.count('unresolved_reviewer_required'),
                'no_direct_conflict_reviewer_required':
                    states.count('no_direct_conflict_reviewer_required'),
                'prose_source_reviewer_required': states.count('prose_source_reviewer_required'),
                'complete': bool(rows) and unmapped == 0,
                'incomplete_reason': ('no_cited_assertion' if not rows else
                                      'structured_assertion_without_mapping' if unmapped else None)}
    return {'rows': rows, 'coverage': coverage}


def conflicts(reconciliation: dict, field: str | None = None) -> list[dict]:
    return [row for row in reconciliation['rows'] if row['state'] == 'conflict'
            and (field is None or row['field'] == field)]
