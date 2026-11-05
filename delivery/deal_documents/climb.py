"""Hill climbing: keep rewriting a section or slide while agents find it can be better, and keep only what improves.

Each round, a writer rewrites every part still below target from what the agents
said about it. A fact checker and a separate investor scorer assess the
candidate, and code compares it with the best version so far. A candidate that is
not better is thrown away, so a part can only improve. Accuracy ranks first:
code-found problems, then fact-check issues, and only then the scorer's opinion,
so polish can never be bought with a wrong sentence.

The scorer is a model opinion and varies between readings, so a candidate must
beat the best by MIN_GAIN to count, and the climb ends at the target, at the pass
budget, or as soon as a round improves nothing.
"""
from __future__ import annotations

import difflib
import os

from delivery.deal_documents.llm import ModelResponseError, RecordedModel
from delivery.deal_documents.review import fact_check

# On a real run the fact-checker caught an error the revision then failed to fix, and nothing checked again. Each round checks the fix.
PASSES = int(os.environ.get('DEAL_DOCUMENTS_CLIMB_PASSES', '2'))
TARGET = int(os.environ.get('DEAL_DOCUMENTS_CLIMB_TARGET', '85'))
MIN_GAIN = 3
CRITERIA = ['evidence', 'investor_relevance', 'voice', 'balance', 'clarity']

SCORE_SYSTEM = """You are a partner at a growth fund scoring one part of a company's fundraising document. Score what is on the page, as you would before deciding whether to read on. Be strict: 3 is competent, 4 is what a good investment bank delivers, 5 is rare.

Score each from 0 to 5:
- evidence: claims rest on specific figures, periods and named sources
- investor_relevance: each point says what it means for the investment; nothing is padding
- voice: it presents the business factually for an investor; it neither sells nor reads as a critique of the company's documents
- balance: positives and limits are both stated at their true weight
- clarity: direct, no repetition, easy to read quickly

Quote the weakest sentence exactly, and give one specific change that would raise the score most, using only what the text already supports. Write compact JSON on one line, without indentation."""


def _schema():
    return {'type': 'object', 'additionalProperties': False, 'required': CRITERIA + ['weakest', 'change'],
            'properties': {**{name: {'type': 'integer', 'minimum': 0, 'maximum': 5} for name in CRITERIA},
                           'weakest': {'type': 'string', 'maxLength': 280}, 'change': {'type': 'string', 'maxLength': 320}}}


def unit_text(unit):
    return '\n\n'.join(paragraph['text'] for paragraph in unit['paragraphs'] if paragraph['kind'] != 'question')


def _version_text(unit):
    return '\n'.join([unit.get('headline', ''), *(paragraph.get('text', '') for paragraph in unit['paragraphs'])])


def score_unit(model: RecordedModel, unit, document):
    """The investor scorer's reading: 0 to 100, with its weakest sentence and the change it would make."""
    result = model.json(f'score-{unit["section"]}', 'score', SCORE_SYSTEM,
                        f'DOCUMENT: {document}\nPART: {unit["title"]}\n\n{unit_text(unit)}', _schema())
    return {'overall': round(100 * sum(result[name] for name in CRITERIA) / (5 * len(CRITERIA))),
            'criteria': {name: result[name] for name in CRITERIA}, 'weakest': result['weakest'], 'change': result['change']}


def evaluate(model: RecordedModel, unit, index, document, human_notes=''):
    """Every agent's reading of one candidate. A failed agent is recorded and the candidate is not credited for it."""
    if not unit['paragraphs']:
        return {'problems': len(unit['problems']) or 1, 'issues': 0, 'found': [], 'score': None, 'failures': ['nothing to assess']}
    failures, found, score = [], [], None
    try:
        found = [issue for issue in fact_check(model, unit, index, human_notes) if issue['quote_verified']]
    except ModelResponseError as exc:
        failures.append(f'fact check: {exc}')
    try:
        score = score_unit(model, unit, document)
    except ModelResponseError as exc:
        failures.append(f'scorer: {exc}')
    return {'problems': len(unit['problems']), 'issues': len(found), 'found': found, 'score': score, 'failures': failures}


def _points(assessment):
    return (assessment['score'] or {}).get('overall', 0)


def better(candidate, best):
    """True when the candidate beats the best so far. Accuracy first; the scorer only decides between equals."""
    if candidate['failures']:
        return False
    if candidate['problems'] != best['problems']:
        return candidate['problems'] < best['problems']
    if candidate['issues'] != best['issues']:
        return candidate['issues'] < best['issues']
    return _points(candidate) >= _points(best) + MIN_GAIN


def finished(assessment):
    """Nothing wrong and at target: no more rewriting is worth its cost."""
    return not assessment['problems'] and not assessment['issues'] and _points(assessment) >= TARGET


def rewrite_notes(assessment):
    """What the next writer is told, from what the agents found."""
    notes = [f'- [fact checker] "{issue["quote"]}": {issue["problem"]}. Change: {issue["fix"]}' for issue in assessment['found']]
    score = assessment['score']
    if score:
        low = [name.replace('_', ' ') for name, value in score['criteria'].items() if value <= 3]
        notes.append(f'- [investor scorer, {score["overall"]}/100; weakest on {", ".join(low) or "nothing specific"}] '
                     f'"{score["weakest"]}": {score["change"]}')
    return '\n'.join(notes)


def climb(parts, assess, rewrite, on_pass, passes=None, on_round=None):
    """Climb every part. `assess(part, round)` and `rewrite(part, notes, round)` run through the caller's steps.

    `parts` is {key: part}. Returns ({key: best part}, {key: its assessment}, the history). Rounds, not parts,
    are the unit of work, so independent agents can run concurrently and models switch only between rounds.
    """
    passes = PASSES if passes is None else passes
    best = dict(parts)
    assessed = dict(zip(best, assess(list(best.items()), 0)))
    history = [{'round': 0, 'kept': sorted(best), 'dropped': [],
                'scores': {key: (value['score'] or {}).get('overall') for key, value in assessed.items()}}]
    if on_round:
        on_round(history[-1])
    for number in range(1, passes + 1):
        todo = [key for key, assessment in assessed.items() if not finished(assessment) and best[key]['paragraphs']]
        if not todo:
            break
        on_pass(number, todo)
        candidates = dict(zip(todo, rewrite([(key, best[key], rewrite_notes(assessed[key])) for key in todo], number)))
        usable = {key: part for key, part in candidates.items() if part['state'] != 'failed' and part['paragraphs']}
        readings = dict(zip(usable, assess(list(usable.items()), number)))
        kept = [key for key, reading in readings.items() if better(reading, assessed[key])]
        changes = {key: {'before_score': (assessed[key]['score'] or {}).get('overall'),
                         'candidate_score': (readings[key]['score'] or {}).get('overall') if key in readings else None,
                         'kept': key in kept,
                         'diff': '\n'.join(difflib.unified_diff(_version_text(best[key]).splitlines(), _version_text(candidates[key]).splitlines(),
                                                               fromfile='previous', tofile='candidate', lineterm='')),
                         'reason': 'Accuracy first, then investor score with the minimum gain' if key in readings else 'Candidate failed validation'}
                   for key in candidates}
        for key in kept:
            best[key], assessed[key] = {**usable[key], 'climbed': number}, readings[key]
        history.append({'round': number, 'kept': sorted(kept), 'dropped': sorted(set(todo) - set(kept)),
                        'scores': {key: (value['score'] or {}).get('overall') for key, value in assessed.items()}, 'changes': changes})
        if on_round:
            on_round(history[-1])
        if not kept:
            break
    return best, assessed, history
