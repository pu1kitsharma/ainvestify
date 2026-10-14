'''Frozen bounded source-unit review: dynamic answer schema and judgment validation.

Boundaries:
- Model judgments are recorded input. This module only checks their shape and
  their internal consistency against the frozen unit definitions.
- It never infers company facts, reads authored unit text or the judgment
  `reason` text for meaning, or rewrites prose. The only thing done to `reason`
  is a length check.
- Any doubt becomes a blocker. Judgments and prose are never altered.
- Unit field state is always unresolved. The schema judges wording only and has
  no answered/resolved label.
'''
from typing import Annotated, Any, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    ValidationError,
    create_model,
    model_validator,
)

REQUIRED_FUNCTIONS = ('investment_rationale', 'conditional_importance', 'inquiry', 'record_request')
REQUESTED_TIME_BASES = ('current', 'historical', 'projected', 'not_stated')
REPORTING_BASES = ('historical', 'projected', 'mixed', 'not_stated')
ANSWER_FUNCTIONS = REQUIRED_FUNCTIONS + ('answer_summary', 'draft_critique')
SOURCE_TIME_BASES = REPORTING_BASES + ('not_applicable',)
ASSERTED_TIME_BASES = ('current', 'historical', 'projected', 'mixed', 'unspecified', 'not_applicable')
QUANTIFICATION_SCOPES = ('source_stated', 'source_scoped_gap', 'unproven_absence', 'not_applicable')
RELATIONS = ('supported_fact', 'scoped_gap', 'conditional_question', 'unsupported', 'insufficient_evidence')

FIELD_STATE = 'unresolved'
REASON_MIN, REASON_MAX = 20, 160

# Relations that can pass, by the unit's required function. Non-rationale units
# are questions or requests, so they can only pass as conditional_question.
PASSING_RELATIONS = {
    'investment_rationale': frozenset({'supported_fact', 'scoped_gap'}),
    'conditional_importance': frozenset({'conditional_question'}),
    'inquiry': frozenset({'conditional_question'}),
    'record_request': frozenset({'conditional_question'}),
}
FACTUAL_RELATIONS = frozenset({'supported_fact', 'scoped_gap'})
CONCRETE_BASES = frozenset({'current', 'historical', 'projected'})

ANSWER_LEVEL = 'answer_schema_invalid'

_NonEmpty = Annotated[str, StringConstraints(strict=True, min_length=1)]
_Reason = Annotated[str, StringConstraints(strict=True, min_length=REASON_MIN, max_length=REASON_MAX)]


def _lit(values):
    return Literal[tuple(values)]


# ---- frozen unit definitions -------------------------------------------------

class _Span(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: _NonEmpty
    exact_text: _NonEmpty


class _Card(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reporting_basis: _lit(REPORTING_BASES)
    contains_explicit_incomplete_quantification_claim: StrictBool


class _UnitSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: _NonEmpty
    required_function: _lit(REQUIRED_FUNCTIONS)
    requested_time_basis: _lit(REQUESTED_TIME_BASES)
    evidence_spans: dict[_NonEmpty, _Span]
    source_cards: dict[_NonEmpty, _Card]

    @model_validator(mode='after')
    def _spans_bind_to_cards(self):
        # Every offered span must name a card of its own unit.
        for eid, span in self.evidence_spans.items():
            if span.source_id not in self.source_cards:
                raise ValueError(f'evidence {eid!r} names a source without a card')
        return self


def _parse_units(units):
    if not isinstance(units, dict) or not units:
        raise ValueError('units must be a non-empty dict')
    parsed = {}
    for uid, raw in units.items():
        if not isinstance(uid, str) or not uid:
            raise ValueError('unit ids must be non-empty strings')
        try:
            parsed[uid] = _UnitSpec.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f'invalid unit {uid!r}: {exc.error_count()} error(s)') from exc
    return parsed


# ---- answer schema -------------------------------------------------------------

def _judgment_model(index, spec, *, source_semantics=False):
    offered = tuple(spec.evidence_spans)
    evidence_type = Optional[_lit(offered)] if offered else type(None)
    return create_model(
        f'UnitJudgment{index}',
        __config__=ConfigDict(extra='forbid'),
        function=(_lit(ANSWER_FUNCTIONS), ...),
        evidence_id=(evidence_type, ...),
        source_time_basis=(_lit(SOURCE_TIME_BASES), ...),
        asserted_time_basis=(_lit(ASSERTED_TIME_BASES), ...),
        quantification_scope=(_lit(QUANTIFICATION_SCOPES), ...),
        requires_explicit_quantification_claim=(StrictBool, ...),
        has_unsupported_premise=(StrictBool, ...),
        preserves_time_scope=(StrictBool, ...),
        reason=(_Reason, ...),
        relation=(_lit(RELATIONS), ...),
        **({'preserves_source_attribution': (StrictBool, Field(...,
              description='True only when a reported/promotional source claim stays attributed rather than independently demonstrated.')),
            'has_unsupported_metric_interpretation': (StrictBool, Field(...,
              description='True if wording invents an economic metric label; currency and monetary units alone do not identify revenue, premium, profit or cash.'))}
           if source_semantics else {}),
    )


def build_schema(units: dict, *, compact=False, source_semantics=False):
    '''Return a Pydantic model class (extra=forbid) for one frozen unit set.

    Unit ids are arbitrary strings, so they are carried as field aliases.
    Evidence ids are enumerated per unit: another unit's ids do not parse.
    '''
    specs = _parse_units(units)
    fields, shared = {}, {}
    for i, (uid, spec) in enumerate(specs.items()):
        offered = tuple(spec.evidence_spans)
        if compact:
            if offered not in shared:
                shared[offered] = _judgment_model(i, spec, source_semantics=source_semantics)
            judgment = shared[offered]
        else:
            judgment = _judgment_model(i, spec, source_semantics=source_semantics)
        fields[f'u{i}'] = (judgment, Field(..., alias=uid))
    judgments = create_model('UnitJudgments', __config__=ConfigDict(extra='forbid', serialize_by_alias=True), **fields)
    return create_model(
        'ScopedUnitAnswer',
        __config__=ConfigDict(extra='forbid'),
        judgments=(judgments, ...),
    )


def unit_states(units: dict) -> dict:
    '''Field state is unconditionally unresolved; a valid answer never changes it.'''
    return {uid: FIELD_STATE for uid in _parse_units(units)}


# ---- validation ----------------------------------------------------------------

def _schema_blockers(specs, exc):
    out, seen = [], set()

    def add(uid, reason):
        if (uid, reason) not in seen:
            seen.add((uid, reason))
            out.append({'unit_id': uid, 'reason': reason})

    answer_level = []
    for err in exc.errors():
        loc = tuple(str(p) for p in err['loc'])
        kind = err['type']
        if len(loc) < 2 or loc[0] != 'judgments':
            answer_level.append(f'{ANSWER_LEVEL}:{kind}')
        elif len(loc) == 2:
            if kind == 'missing':
                add(loc[1], 'missing_unit_judgment')
            elif kind == 'extra_forbidden':
                add(loc[1], 'unknown_unit_id')
            else:
                add(loc[1], f'unit_judgment_invalid:{kind}')
        else:
            label = {'missing': 'missing_field', 'extra_forbidden': 'unexpected_field'}.get(kind, 'invalid_field')
            add(loc[1], f'{label}:{loc[2]}')
    # A malformed envelope cannot be attributed to one unit, so block them all.
    for reason in answer_level:
        for uid in specs:
            add(uid, reason)
    return out


def _check_unit(spec, j, *, source_semantics=False, excerpt_time_basis=False):
    found = []
    required = spec.required_function
    relation = j['relation']
    scope = j['quantification_scope']
    requires_claim = j['requires_explicit_quantification_claim']
    factual = relation in FACTUAL_RELATIONS

    if j['function'] != required:
        found.append('function_mismatch')
    if relation not in PASSING_RELATIONS[required]:
        found.append('relation_not_passing_for_required_function')
    if j['has_unsupported_premise']:
        found.append('unsupported_premise')
    if not j['preserves_time_scope']:
        found.append('time_scope_not_preserved')
    if source_semantics:
        if not j['preserves_source_attribution']:
            found.append('source_attribution_not_preserved')
        if j['has_unsupported_metric_interpretation']:
            found.append('unsupported_metric_interpretation')
    if scope == 'unproven_absence':
        found.append('unproven_absence')
    if len(j['reason'].strip()) < REASON_MIN:
        found.append('reason_too_short')

    # Evidence binds only through this unit's own offered span and its own card.
    eid = j['evidence_id']
    span = spec.evidence_spans.get(eid) if eid is not None else None
    card = spec.source_cards.get(span.source_id) if span is not None else None
    if factual and span is None:
        found.append('missing_evidence')
    if span is None:
        if j['source_time_basis'] != 'not_applicable':
            found.append('source_basis_without_evidence')
        if scope in ('source_stated', 'source_scoped_gap'):
            found.append('quantification_scope_without_evidence')
    else:
        basis = j['source_time_basis']
        # Conditional units may decline a basis; fact/gap must match the card.
        allowed = {card.reporting_basis}
        if excerpt_time_basis and card.reporting_basis == 'mixed':
            allowed |= {'historical', 'projected'}
        if (factual or basis != 'not_applicable') and basis not in allowed:
            found.append('source_time_basis_mismatch')

    # Quantification: claims must rest on the unit's own source card flag.
    if requires_claim and not (
        card is not None and card.contains_explicit_incomplete_quantification_claim
    ):
        found.append('quantification_claim_unbacked_by_own_source_card')
    if requires_claim and scope == 'not_applicable':
        found.append('requires_quantification_but_scope_not_applicable')
    if relation == 'supported_fact' and scope == 'source_scoped_gap':
        found.append('supported_fact_with_scoped_gap_scope')

    # Time basis: only factual assertions can launder a plan into an answer.
    if factual:
        asserted = j['asserted_time_basis']
        scoped_distinction = relation == 'scoped_gap' and scope == 'source_scoped_gap'
        if asserted in ('unspecified', 'not_applicable'):
            found.append('asserted_time_basis_unresolved')
        if (
            card is not None
            and ((j['source_time_basis'] if excerpt_time_basis else card.reporting_basis) == 'projected' or
                 card.reporting_basis == 'mixed' and not j['preserves_time_scope'])
            and asserted in ('current', 'historical')
            and not scoped_distinction
        ):
            found.append('projected_source_asserted_as_current_or_historical')
        requested = spec.requested_time_basis
        if (
            requested in CONCRETE_BASES
            and asserted in CONCRETE_BASES
            and asserted != requested
            and relation != 'scoped_gap'
        ):
            found.append('asserted_basis_differs_from_requested')
    return list(dict.fromkeys(found))


def validate_answer(units: dict, answer: Any, *, source_semantics=False, excerpt_time_basis=False) -> list:
    '''Return blocking dicts {unit_id, reason}; an empty list means every unit passes.

    Reasons are stable codes derived from structure only. Inputs are not modified.
    '''
    specs = _parse_units(units)
    schema = build_schema(units, source_semantics=source_semantics)
    try:
        parsed = schema.model_validate(answer)
    except ValidationError as exc:
        return _schema_blockers(specs, exc)
    judgments = parsed.model_dump(by_alias=True)['judgments']
    blockers = []
    for uid, spec in specs.items():
        for reason in _check_unit(spec, judgments[uid], source_semantics=source_semantics, excerpt_time_basis=excerpt_time_basis):
            blockers.append({'unit_id': uid, 'reason': reason})
    return blockers
