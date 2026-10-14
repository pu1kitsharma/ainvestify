"""Structural and internal-consistency validation for scope judgments.

This module only checks declared fields against each other. It never reads
`reason` (or any other prose) to infer or rewrite a semantic field. Matching
reasons and exact source text to evidence is the job of a separate binder.
"""

from collections.abc import Mapping

SOURCE_TIME_BASES = frozenset(
    {'historical', 'projected', 'mixed', 'not_stated', 'not_applicable'}
)
ASSERTED_TIME_BASES = SOURCE_TIME_BASES | {'unspecified'}
QUANTIFICATION_SCOPES = frozenset(
    {'source_stated', 'source_scoped_gap', 'unproven_absence', 'not_applicable'}
)
RELATIONS = frozenset(
    {
        'supported_fact',
        'scoped_gap',
        'conditional_question',
        'unsupported',
        'insufficient_evidence',
    }
)

PASSING_RELATIONS = frozenset({'supported_fact', 'scoped_gap', 'conditional_question'})
EVIDENCE_REQUIRED_RELATIONS = frozenset({'supported_fact', 'scoped_gap'})

_REQUIRED_FIELDS = (
    'evidence_id',
    'source_time_basis',
    'asserted_time_basis',
    'quantification_scope',
    'reason',
    'relation',
)
_ENUM_FIELDS = {
    'source_time_basis': SOURCE_TIME_BASES,
    'asserted_time_basis': ASSERTED_TIME_BASES,
    'quantification_scope': QUANTIFICATION_SCOPES,
    'relation': RELATIONS,
}


def _structural_errors(jid, judgment):
    errors = []
    if not isinstance(judgment, Mapping):
        return [f'{jid}: judgment must be a mapping']

    for field in _REQUIRED_FIELDS:
        if field not in judgment:
            errors.append(f'{jid}: missing required field {field!r}')
    for field in judgment:
        if field not in _REQUIRED_FIELDS:
            errors.append(f'{jid}: unknown field {field!r}')

    for field, allowed in _ENUM_FIELDS.items():
        if field not in judgment:
            continue
        value = judgment[field]
        if not isinstance(value, str) or value not in allowed:
            errors.append(f'{jid}: invalid {field} {value!r}')

    if 'evidence_id' in judgment:
        evidence_id = judgment['evidence_id']
        if evidence_id is not None and (
            not isinstance(evidence_id, str) or not evidence_id.strip()
        ):
            errors.append(f'{jid}: evidence_id must be null or a non-empty string')

    if 'reason' in judgment:
        reason = judgment['reason']
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f'{jid}: reason must be a non-empty string')

    return errors


def _consistency_errors(jid, judgment):
    errors = []
    relation = judgment['relation']
    source = judgment['source_time_basis']
    asserted = judgment['asserted_time_basis']
    passing = relation in PASSING_RELATIONS

    if relation in EVIDENCE_REQUIRED_RELATIONS and judgment['evidence_id'] is None:
        errors.append(f'{jid}: {relation} requires a non-null evidence_id')

    if passing and judgment['quantification_scope'] == 'unproven_absence':
        errors.append(
            f'{jid}: {relation} cannot rest on quantification_scope unproven_absence'
        )

    if passing and asserted == 'historical':
        if source == 'projected':
            errors.append(
                f'{jid}: source is projected but the sentence asserts historical'
            )
        elif source == 'mixed':
            errors.append(
                f'{jid}: source is mixed but the sentence asserts historical '
                '(unqualified aggregate)'
            )

    if (
        relation == 'supported_fact'
        and source in ('projected', 'mixed')
        and asserted in ('unspecified', 'not_stated')
    ):
        errors.append(
            f'{jid}: supported_fact on a {source} source needs an explicit '
            'asserted_time_basis'
        )

    return errors


def validate_scope_judgments(answer):
    """Validate an answer's scope judgments; return None when consistent.

    Raises ValueError listing every problem found.
    """
    if not isinstance(answer, Mapping):
        raise ValueError('answer must be a mapping')
    judgments = answer.get('judgments')
    if not isinstance(judgments, Mapping) or not judgments:
        raise ValueError('answer.judgments must be a non-empty mapping')

    errors = []
    for jid, judgment in judgments.items():
        if not isinstance(jid, str) or not jid.strip():
            errors.append(f'judgment id must be a non-empty string, got {jid!r}')
            continue
        structural = _structural_errors(jid, judgment)
        if structural:
            errors.extend(structural)
            continue
        errors.extend(_consistency_errors(jid, judgment))

    if errors:
        raise ValueError('; '.join(errors))
    return None
