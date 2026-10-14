'''Integrity validation of model-authored rationale judgments.

This module is NOT a semantic adjudicator. It never decides whether a sentence
is actually supported, never infers or corrects a relation, and never applies
keyword or substring heuristics to prose. The model alone chooses each
sentence relation. This code only verifies that the answer is well formed,
covers exactly the payload sentences, and that every cited excerpt is an exact
contiguous slice of the cited source passage. Rows whose model-chosen relation
is unsupported or insufficient_evidence are reported as blocking.
'''
from typing import Any, Dict, List

RELATIONS = (
    'supported_fact',
    'scoped_gap',
    'conditional_question',
    'unsupported',
    'insufficient_evidence',
)
DILIGENCE_STATUSES = ('answered', 'open', 'not_applicable')
EVIDENCE_BOUND = frozenset({'supported_fact', 'scoped_gap'})
BLOCKING_RELATIONS = frozenset({'unsupported', 'insufficient_evidence'})
ROW_KEYS = frozenset({'relation', 'source_id', 'source_excerpt', 'reason'})
ANSWER_KEYS = frozenset({'judgments', 'diligence_status'})
SOURCE_KEYS = ('id', 'passage', 'version', 'attribution')
MIN_REASON_CHARS = 20
MAX_REASON_CHARS = 600


def _nonempty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must be a non-empty string')
    return value


def _index_sources(payload: Dict[str, Any]) -> Dict[str, str]:
    '''Return {source_id: passage} for selected sources, validating structure.'''
    sources = payload.get('sources')
    if not isinstance(sources, list):
        raise ValueError('payload.sources must be a list')
    by_id: Dict[str, str] = {}
    for index, source in enumerate(sources):
        label = 'payload.sources[' + str(index) + ']'
        if not isinstance(source, dict):
            raise ValueError(label + ' must be an object')
        missing = [key for key in SOURCE_KEYS if key not in source]
        if missing:
            raise ValueError(label + ' missing keys: ' + ', '.join(missing))
        source_id = _nonempty_str(source['id'], label + '.id')
        passage = _nonempty_str(source['passage'], label + '.passage')
        version = source['version']
        if isinstance(version, bool) or not isinstance(version, (str, int)):
            raise ValueError(label + '.version must be a string or integer')
        if isinstance(version, str) and not version.strip():
            raise ValueError(label + '.version must not be blank')
        _nonempty_str(source['attribution'], label + '.attribution')
        if source_id in by_id:
            raise ValueError('duplicate source id: ' + source_id)
        by_id[source_id] = passage

    selected = payload.get('selected_source_ids')
    if not isinstance(selected, list):
        raise ValueError('payload.selected_source_ids must be a list')
    chosen: Dict[str, str] = {}
    for source_id in selected:
        _nonempty_str(source_id, 'selected source id')
        if source_id in chosen:
            raise ValueError('duplicate selected source id: ' + source_id)
        if source_id not in by_id:
            raise ValueError('selected source id not in sources: ' + source_id)
        chosen[source_id] = by_id[source_id]
    return chosen


def _check_sentences(payload: Dict[str, Any]) -> Dict[str, str]:
    sentences = payload.get('sentences')
    if not isinstance(sentences, dict) or not sentences:
        raise ValueError('payload.sentences must be a mapping')
    for sentence_id, text in sentences.items():
        _nonempty_str(sentence_id, 'sentence id')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('sentence text must be a string: ' + sentence_id)
    return sentences


def _check_row(sentence_id: str, row: Any, passages: Dict[str, str]) -> None:
    label = 'judgment ' + sentence_id
    if not isinstance(row, dict):
        raise ValueError(label + ' must be an object')
    keys = set(row)
    if keys != ROW_KEYS:
        missing = sorted(ROW_KEYS - keys)
        extra = sorted(str(k) for k in keys - ROW_KEYS)
        raise ValueError(label + ' bad keys; missing=' + str(missing) + ' extra=' + str(extra))

    relation = row['relation']
    if not isinstance(relation, str) or relation not in RELATIONS:
        raise ValueError(label + ' has invalid relation')

    source_id = row['source_id']
    if source_id is not None:
        if not isinstance(source_id, str) or source_id not in passages:
            raise ValueError(label + ' cites a source id that is not selected')

    excerpt = row['source_excerpt']
    if not isinstance(excerpt, str):
        raise ValueError(label + ' source_excerpt must be a string')
    if excerpt and not excerpt.strip():
        raise ValueError(label + ' source_excerpt must not be only whitespace')

    reason = row['reason']
    if not isinstance(reason, str):
        raise ValueError(label + ' reason must be a string')
    if not MIN_REASON_CHARS <= len(reason) <= MAX_REASON_CHARS:
        raise ValueError(label + ' reason length must be 20 to 600 characters')
    if not reason.strip():
        raise ValueError(label + ' reason must not be blank')

    if relation in EVIDENCE_BOUND:
        if source_id is None:
            raise ValueError(label + ' requires a source id for ' + relation)
        if not excerpt:
            raise ValueError(label + ' requires a source excerpt for ' + relation)
    if excerpt:
        if source_id is None:
            raise ValueError(label + ' has an excerpt but no source id')
        if excerpt not in passages[source_id]:
            raise ValueError(label + ' excerpt is not an exact slice of the source passage')


def validate_judgments(payload: Dict[str, Any], answer: Dict[str, Any]) -> List[Dict[str, Any]]:
    '''Validate answer integrity and return blocking judgment dicts.

    Raises ValueError for any malformed, incomplete, extra, or unbound data.
    Blocking entries are those whose model-chosen relation is unsupported or
    insufficient_evidence. diligence_status is validated but never blocks.
    '''
    if not isinstance(payload, dict):
        raise ValueError('payload must be an object')
    if not isinstance(answer, dict):
        raise ValueError('answer must be an object')

    passages = _index_sources(payload)
    sentences = _check_sentences(payload)

    if set(answer) != ANSWER_KEYS:
        raise ValueError('answer keys must be exactly judgments and diligence_status')
    status = answer['diligence_status']
    if not isinstance(status, str) or status not in DILIGENCE_STATUSES:
        raise ValueError('invalid diligence_status')
    judgments = answer['judgments']
    if not isinstance(judgments, dict):
        raise ValueError('answer.judgments must be a mapping')

    missing = [sid for sid in sentences if sid not in judgments]
    extra = [str(sid) for sid in judgments if sid not in sentences]
    if missing or extra:
        raise ValueError('judgment coverage mismatch; missing=' + str(missing) + ' extra=' + str(extra))

    blocking: List[Dict[str, Any]] = []
    for sentence_id, sentence in sentences.items():
        row = judgments[sentence_id]
        _check_row(sentence_id, row, passages)
        if row['relation'] in BLOCKING_RELATIONS:
            blocking.append({
                'focus_sentence_id': sentence_id,
                'exact_sentence': sentence,
                'source_id': row['source_id'],
                'reason': row['reason'],
                'verdict': row['relation'],
            })
    return blocking
