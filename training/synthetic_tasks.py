"""Fictional E4 reconciliation-flag tasks for plumbing runs. Not financial content.

Every company, number and sentence is invented. Cases are deliberately easy to
copy from the prompt so a 0.5B model has a chance of a non-zero reward; that makes
them a test of the pipeline, not of banking skill.
"""
import hashlib

FLAGS = ['units', 'comparator', 'period', 'currency', 'rounding', 'scope']
_PHRASES = {
    'units': 'the sheet mixes thousands and millions',
    'comparator': 'the peer set uses a different comparator',
    'period': 'one column covers a 53-week period',
    'currency': 'the segment note is stated in another currency',
    'rounding': 'subtotals differ by rounding',
    'scope': 'a divested unit is still included',
}
# A worked example with THREE flags: every real case has one, so copying it scores 0.
EXAMPLE_ANSWER = {'observations': {'flags': {'status': 'observed', 'value': ['units', 'period', 'currency']}}}
INSTRUCTION = ('Copy the id of every [flag:<id>] tag in the reviewer notes into the value list. '
               'Do not add ids that are not tagged.')


def _pairs(n):
    return [(FLAGS[(i * 5 + i // 6) % 6],) for i in range(n)]


def _row(case_id, split, deal, flags, private=False, family=None):
    notes = '; '.join('[flag:%s] %s' % (f, _PHRASES[f]) for f in flags)
    text = 'Fictional reviewer notes for %s: %s.' % (deal, notes)
    key = {'case_id': case_id, 'environment': 'E4',
           'checks': {'flags': {'status': 'available', 'kind': 'set', 'expected': sorted(flags)}}}
    row = {'case_id': case_id, 'split': split, 'deal_id': deal, 'company_key': deal, 'sector': 'sector-' + split,
           'evidence_family_ids': [family or 'family-' + case_id],
           'source_sha256': [hashlib.sha256(text.encode()).hexdigest()],
           'rights_status': 'private_training_approved' if private else 'public_training_approved',
           'private': private, 'synthetic_fiction': True,
           'input': {'case_id': case_id, 'environment': 'E4', 'instruction': INSTRUCTION, 'example_answer_for_a_different_case': EXAMPLE_ANSWER,
                                'source_text': text},
           'answer_key': key}
    if private:
        row.pop('sector'), row.pop('company_key'), row.pop('evidence_family_ids'), row.pop('source_sha256')
    return row


def synthetic_rows(n_train=8):
    pairs = _pairs(n_train + 4)
    public = []
    for i in range(n_train):
        public.append(_row('syn-train-%d' % i, 'train', 'fictional-co-train-%d' % i, pairs[i]))
    for j, split in enumerate(('valid', 'valid', 'test', 'test')):
        public.append(_row('syn-%s-%d' % (split, j), split, 'fictional-co-%s-%d' % (split, j), pairs[n_train + j]))
    private = [_row('syn-private-train', 'train', 'fictional-private-omega', ('units',), private=True),
               _row('syn-private-heldout', 'test', 'fictional-private-sigma', ('period',), private=True)]
    return public, private


def canary_facts():
    """Invented numbers. `seen` appear in a training example; `unseen` never do."""
    return {
        'seen': [{'id': 'canary-seen-1', 'prefix': 'Fictional Quillon Ltd closed the year with recurring revenue of ',
                  'secret': '7,318,442'}],
        'unseen': [{'id': 'canary-unseen-1', 'prefix': 'Fictional Brackwater Inc closed the year with recurring revenue of ',
                    'secret': '4,906,157'}],
    }
