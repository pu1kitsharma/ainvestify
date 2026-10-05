"""The opt-in semantic_v11 worker path: one call per deck, every sentence a required row.

Synthetic decks and memo only; a scripted double stands in for the reviewer.
"""
import json

import pytest

from agents.inference.model_authorship import digest
from agents.preparation.preparation_budget import PreparationBudgetExceeded
from agents.research import material_relation_review as relation
from scripts import private_material_review_worker as worker
from scripts.private_material_review_worker import review_materials

S1A = 'A registry lists a seed round for Example Labs with unknown status [S1].'
S1B = 'The registry entry does not state that any funds were received [S1].'
S2A = 'Example Labs states that it builds scheduling software for clinics [S2].'
S2B = 'The company page reports no revenue or customer figures [S2].'
SECTIONS = [['Synthetic funding evidence', f'{S1A} {S1B}', '[S1] https://example.invalid/registry'],
            ['Synthetic product evidence', f'{S2A} {S2B}', '[S2] https://example.invalid/company']]
REPORT = 'A registry lists a seed round with unknown status [S1].'
RECEIPT = 'The company received the seed funds in full [S1].'
MIXED = 'The company page and the registry report no revenue and no received funds [S1][S2].'
DECKS = {
    'intro_deck': [['Company overview', f'{S2A} {S2B}', '[S2] Synthetic company page', 'statement']],
    'pitch_deck': [['Funding evidence', REPORT, '[S1] Synthetic registry', 'evidence'],
                   ['What is not known', MIXED, '[S1] [S2] Synthetic sources', 'evidence']],
}
DEFECT = {**DECKS, 'pitch_deck': [['Funding evidence', f'{REPORT} {RECEIPT}',
                                   '[S1] Synthetic registry', 'evidence'], DECKS['pitch_deck'][1]]}
IDS = {'intro_deck': ['intro_deck.slide_1.sentence_1', 'intro_deck.slide_1.sentence_2'],
       'pitch_deck': ['pitch_deck.slide_1.sentence_1', 'pitch_deck.slide_2.sentence_1']}


def judged(relation_='supported_as_source_report', clause=None):
    return {'relation': relation_, 'challenged_clause': clause,
            'reason': 'Compared this sentence with its own listed memo spans.'}


def capable(payload):
    """Answers every required row from that row's own sentence."""
    return {row['row_id']: judged('unsupported_assertion', 'received the seed funds in full')
            if 'received the seed funds in full' in row['sentence'] else judged()
            for row in payload['rows']}


class Reviewer:
    """Records the raw answer before schema validation, as the local adapter does."""
    name = 'qwen3.5:9b'

    def __init__(self, policy=capable, options=None):
        self.policy, self.calls, self.seen = policy, 0, []
        self.options = options or relation.RELATION_OPTIONS
        self.last_response_text, self.last_route = '', {}

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == 'material_relation_review'
        self.calls += 1
        payload = json.loads(evidence)
        self.seen.append((instruction, payload, schema))
        self.last_route = {'model': self.name, **self.options}
        answer = self.policy(payload)
        if isinstance(answer, Exception):
            raise answer
        self.last_response_text = answer if isinstance(answer, str) else json.dumps(answer)
        return schema.model_validate_json(self.last_response_text)


def request(root, decks=DECKS, contract='semantic_v11', options=None, sections=SECTIONS):
    base = {'input_revision': 'synthetic', 'source_hash': 'source', 'memo_digest': 'memo',
            'material_digest': 'material', 'memo_sections': sections, 'decks': decks,
            'review_contract': contract,
            'review_model': {'name': 'qwen3.5:9b', 'digest': 'sha256:synthetic',
                             'options': options or relation.RELATION_OPTIONS}}
    full = {**base, 'digest': digest(base)}
    root.mkdir(parents=True, exist_ok=True)
    (root / 'material_review_request.json').write_text(json.dumps(full))
    (root / 'material_review_budget.json').write_text(json.dumps({'seconds': 90}))
    return full


def attempts(root):
    return json.loads((root / 'material_review_attempts.json').read_text())


def passes(root, model, count=2):
    return [review_materials(root, model) for _ in range(count)]


def on(deck, answer):
    return lambda payload: answer(payload) if payload['deck'] == deck else capable(payload)


def test_every_sentence_is_a_required_row_with_all_spans_of_its_sources(tmp_path):
    full = request(tmp_path, DEFECT)
    calls = relation.frozen_calls(full)
    assert list(calls) == ['intro_deck', 'pitch_deck']
    intro, pitch = calls['intro_deck'][0], calls['pitch_deck'][0]
    assert set(intro) == {'review_contract', 'deck', 'full_request_digest', 'review_model', 'rows'}
    assert intro['review_model'] == {'name': 'qwen3.5:9b', 'digest': 'sha256:synthetic'}
    assert [row['sentence_id'] for row in intro['rows']] == IDS['intro_deck']
    assert [(row['row_id'], row['sentence']) for row in pitch['rows']] == [
        ('r01', REPORT), ('r02', RECEIPT), ('r03', MIXED)]
    # All complete spans of each cited source, exact, with provenance; none of another's.
    span = lambda tag, index, text: {'source_id': tag, 'section_index': index, 'exact_span': text}
    registry = [span('[S1]', 0, S1A), span('[S1]', 0, S1B)]
    page = [span('[S2]', 1, S2A), span('[S2]', 1, S2B)]
    assert pitch['rows'][0]['source_spans'] == registry == pitch['rows'][1]['source_spans']
    assert pitch['rows'][2]['source_spans'] == registry + page
    assert all(row['source_spans'] == page for row in intro['rows'])
    # The model sees a row ID, the sentence and its spans: no heading, slide or expectation.
    assert all(set(row) == {'row_id', 'sentence_id', 'sentence', 'source_spans'}
               for row in intro['rows'] + pitch['rows'])
    # The schema requires exactly the supplied rows and forbids any other.
    schema = calls['pitch_deck'][1].model_json_schema()
    assert schema['required'] == ['r01', 'r02', 'r03'] and schema['additionalProperties'] is False
    assert calls['intro_deck'][1].model_json_schema()['required'] == ['r01', 'r02']
    text = relation.RELATION_INSTRUCTION
    assert all(label in text for label in (
        'supported_as_source_report', 'unsupported_assertion', 'insufficient_evidence',
        'challenged_clause', 'EACH required row'))
    assert not any(word in text.casefold() for word in ('synthetic', 'defect', 'funds', 'registry'))


def test_all_rows_supported_passes_after_one_call_per_deck_and_replays_on_restart(tmp_path):
    full = request(tmp_path)
    model = Reviewer()
    first, second = passes(tmp_path, model)
    # One call per pass: the first pass reviews the intro deck only.
    assert first == {'state': 'needs_resume', 'reason': 'material_relation_review_next_deck',
                     'next_deck': 'pitch_deck', 'decks_recorded': ['intro_deck']}
    assert second['state'] == 'accepted' and second['reason'] is None
    assert second['request_digest'] == full['digest']
    assert second['response_ids'] == {'intro_deck': 'response_1', 'pitch_deck': 'response_2'}
    assert second['response_id'] == 'response_2'
    review = second['review']
    assert review['verdict'] == 'pass' and review['findings'] == []
    assert review['review_contract'] == 'semantic_v11'
    assert [row['sentence_id'] for deck in ('intro_deck', 'pitch_deck')
            for row in review['decks'][deck]['rows']] == IDS['intro_deck'] + IDS['pitch_deck']
    assert all(row['relation'] == 'supported_as_source_report' and row['challenged_clause'] is None
               for deck in review['decks'].values() for row in deck['rows'])
    rows = attempts(tmp_path)
    assert model.calls == 2 == len(rows)
    assert [row['input']['deck'] for row in rows] == ['intro_deck', 'pitch_deck']
    assert all(row['task'] == 'material_relation_review' and row['raw_response']
               and row['response_hash'] == digest(row['raw_response'])
               and row['instruction'] == relation.RELATION_INSTRUCTION for row in rows)
    # A restart replays the raw record exactly, with no inference and no rewrite.
    saved = (tmp_path / 'material_review_attempts.json').read_bytes()
    idle = Reviewer()
    assert review_materials(tmp_path, idle) == second and idle.calls == 0
    assert (tmp_path / 'material_review_attempts.json').read_bytes() == saved
    # A restart between the two decks continues with the pitch deck only.
    again = tmp_path / 'again'
    request(again)
    assert review_materials(again, Reviewer())['state'] == 'needs_resume'
    fresh = Reviewer()
    assert review_materials(again, fresh)['review'] == review
    assert fresh.calls == 1 and fresh.seen[0][1]['deck'] == 'pitch_deck'


def test_unsupported_row_blocks_with_software_bound_text_and_evidence(tmp_path):
    request(tmp_path, DEFECT)
    model = Reviewer()
    first, second = passes(tmp_path, model)
    assert first['state'] == 'needs_resume'
    assert (second['state'], second['reason']) == ('blocked', 'model_relation_review_blocked')
    assert second['response_id'] == 'response_2' and second['review']['verdict'] == 'block'
    finding, = second['review']['findings']
    # The model wrote relation, clause and reason; software bound the rest exactly.
    assert finding == {
        'row_id': 'r02', 'sentence_id': 'pitch_deck.slide_1.sentence_2', 'deck': 'pitch_deck',
        'slide_index': 0, 'heading': 'Funding evidence', 'sentence': RECEIPT,
        'source_spans': [{'source_id': '[S1]', 'section_index': 0, 'exact_span': S1A},
                         {'source_id': '[S1]', 'section_index': 0, 'exact_span': S1B}],
        'relation': 'unsupported_assertion',
        'challenged_clause': 'received the seed funds in full',
        'reason': 'Compared this sentence with its own listed memo spans.'}
    assert attempts(tmp_path)[1]['answer']['r02']['challenged_clause'] in RECEIPT
    idle = Reviewer()
    assert review_materials(tmp_path, idle) == second and idle.calls == 0 and model.calls == 2


def test_insufficient_row_blocks_and_an_intro_block_still_reviews_the_pitch_deck(tmp_path):
    request(tmp_path)
    model = Reviewer(on('intro_deck', lambda payload: {
        **capable(payload), 'r02': judged('insufficient_evidence')}))
    first, second = passes(tmp_path, model)
    assert first['state'] == 'needs_resume' and model.calls == 2
    assert (second['state'], second['reason']) == ('blocked', 'model_relation_review_blocked')
    assert [(item['sentence_id'], item['relation']) for item in second['review']['findings']] == [
        ('intro_deck.slide_1.sentence_2', 'insufficient_evidence')]
    assert len(second['review']['decks']['pitch_deck']['rows']) == 2


def drop(row_id):
    return lambda payload: {key: value for key, value in capable(payload).items() if key != row_id}


@pytest.mark.parametrize('deck, bad, reason, kind', [
    # A missing or extra row, or a wrong label: the dynamic schema rejects the answer.
    ('intro_deck', drop('r02'), 'material_relation_review_malformed', 'schema_validation'),
    ('pitch_deck', drop('r01'), 'material_relation_review_malformed', 'schema_validation'),
    ('pitch_deck', lambda payload: {**capable(payload), 'r09': judged()},
     'material_relation_review_malformed', 'schema_validation'),
    ('intro_deck', lambda payload: {**capable(payload), 'r01': judged('supported')},
     'material_relation_review_malformed', 'schema_validation'),
    ('intro_deck', lambda payload: {'rows': list(capable(payload).values())},
     'material_relation_review_malformed', 'schema_validation'),
    # Valid shape, but the clause is not the sentence's own words, is missing, or is
    # attached to a row the model did not call unsupported.
    ('pitch_deck', lambda payload: {**capable(payload), 'r01': judged(
        'unsupported_assertion', 'the round has closed')}, 'material_relation_review_malformed', None),
    ('pitch_deck', lambda payload: {**capable(payload), 'r01': judged('unsupported_assertion')},
     'material_relation_review_malformed', None),
    ('pitch_deck', lambda payload: {**capable(payload), 'r01': judged('unsupported_assertion', '    ')},
     'material_relation_review_malformed', None),
    ('intro_deck', lambda payload: {**capable(payload), 'r01': judged(clause='scheduling software')},
     'material_relation_review_malformed', None),
    # A clause copied from another row's sentence is a transferred answer.
    ('intro_deck', lambda payload: {**capable(payload), 'r01': judged(
        'unsupported_assertion', 'no revenue or customer figures')},
     'material_relation_review_malformed', None),
    # Not JSON at all, an adapter error, or a call cut off before any answer.
    ('pitch_deck', lambda payload: 'All of these sentences look fine to me.',
     'material_relation_review_malformed', None),
    ('intro_deck', lambda payload: RuntimeError('local adapter failed'),
     'material_relation_review_no_answer', None),
    ('pitch_deck', lambda payload: PreparationBudgetExceeded(
        'Preparation reached its time limit during inference.'),
     'material_relation_review_no_answer', None),
])
def test_malformed_missing_or_absent_answers_fail_closed_and_are_never_retried(
        tmp_path, deck, bad, reason, kind):
    request(tmp_path)
    model = Reviewer(on(deck, bad))
    results = passes(tmp_path, model, 3)
    final = results[-1]
    expected_calls = 1 if deck == 'intro_deck' else 2
    assert (final['state'], final['reason']) == ('blocked', reason)
    assert final['review']['verdict'] == 'block'
    rows = attempts(tmp_path)
    # One recorded attempt per deck at most; the failed deck is never called again,
    # and a failed intro deck stops before the pitch deck.
    assert model.calls == expected_calls == len(rows)
    assert final['response_id'] == rows[-1]['id']
    # A schema-valid answer that does not bind is kept as answered, and still blocks.
    assert bool(rows[-1].get('error')) == (kind is not None or not isinstance(
        bad({'rows': []}), dict))
    assert rows[-1].get('failure_kind') == kind
    assert deck not in final['review']['decks']
    assert results[expected_calls - 1] == final == results[expected_calls]
    # Even a capable model cannot replace the recorded failure.
    idle = Reviewer()
    assert review_materials(tmp_path, idle) == final and idle.calls == 0


def test_only_all_supported_passes_whatever_else_the_model_says(tmp_path):
    for index, relation_ in enumerate(('unsupported_assertion', 'insufficient_evidence')):
        root = tmp_path / str(index)
        request(root)
        model = Reviewer(lambda payload, relation_=relation_: {
            row['row_id']: judged(relation_, row['sentence'][:12]
                                  if relation_ == 'unsupported_assertion' else None)
            for row in payload['rows']})
        final = passes(root, model)[-1]
        assert final['state'] == 'blocked' and len(final['review']['findings']) == 4
    # A lenient model passes the planted sentence: the path reports what the model said.
    root = tmp_path / 'lenient'
    request(root, DEFECT)
    lenient = passes(root, Reviewer(lambda payload: {row['row_id']: judged()
                                                     for row in payload['rows']}))[-1]
    assert lenient['state'] == 'accepted'      # a model limitation, measured by the live gate


def many(count, tag='[S1]'):
    return ' '.join(f'The registry entry is numbered {index} in this synthetic deck {tag}.'
                    for index in range(count))


@pytest.mark.parametrize('change, message', [
    (dict(decks={**DECKS, 'pitch_deck': [['Funding', many(17), '[S1]', 'evidence']]}),
     'sixteen-row bound'),
    (dict(decks={**DECKS, 'intro_deck': []}), 'sixteen-row bound'),
    (dict(decks={**DECKS, 'pitch_deck': [['Funding', 'The round closed last year.', '', 'evidence']]}),
     'citing no source'),
    (dict(decks={**DECKS, 'pitch_deck': [['Funding', 'A filing shows a new round [S3].', '[S3]',
                                         'evidence']]}), 'lacks complete memo evidence'),
    # A memo fragment is not a complete span for its source.
    (dict(sections=[SECTIONS[0], ['Cut off', 'Example Labs states that it builds [S2]', '[S2]']]),
     'lacks complete memo evidence'),
    (dict(sections=[['Long', ' '.join([S1A] + [f'Registry note {index} repeats the unknown status '
                                               f'of the listed round {"x" * 500} [S1].'
                                               for index in range(8)]), '[S1]'], SECTIONS[1]],
          decks={**DECKS, 'pitch_deck': [['Funding', many(8), '[S1]', 'evidence']]}),
     'bounded input size'),
    (dict(options={'thinking': False, 'max_tokens': 1200, 'context_tokens': 16384,
                   'temperature': 0}), 'bounded options'),
    (dict(options={**relation.RELATION_OPTIONS, 'max_tokens': 9000}), 'bounded options'),
])
def test_an_unreviewable_or_unbounded_request_is_refused_before_any_inference(
        tmp_path, change, message):
    request(tmp_path, **change)
    model = Reviewer()
    with pytest.raises(ValueError, match=message):
        review_materials(tmp_path, model)
    assert model.calls == 0 and not (tmp_path / 'material_review_attempts.json').exists()


def test_sixteen_rows_per_deck_is_accepted_within_the_bounds(tmp_path):
    request(tmp_path, {'intro_deck': [['Overview', many(16, '[S2]'), '[S2]', 'statement']],
                       'pitch_deck': [['Funding', many(16), '[S1]', 'evidence']]})
    model = Reviewer()
    final = passes(tmp_path, model)[-1]
    assert final['state'] == 'accepted' and model.calls == 2
    assert [len(schema.model_json_schema()['required']) for _, _, schema in model.seen] == [16, 16]
    assert all(len(json.dumps(payload).encode()) <= relation.MAX_INPUT_BYTES
               for _, payload, _ in model.seen)
    assert (relation.MAX_ROWS_PER_DECK, relation.MAX_SECONDS) == (16, 105)
    assert relation.RELATION_OPTIONS == {'thinking': False, 'max_tokens': 3200,
                                         'context_tokens': 16384, 'temperature': 0}


def test_each_call_runs_alone_under_the_bounded_budget(tmp_path, monkeypatch):
    budgets = []
    real = worker.PreparationBudget
    monkeypatch.setattr(worker, 'PreparationBudget',
                        lambda *args, **kwargs: budgets.append((args, kwargs)) or real(*args, **kwargs))
    request(tmp_path)
    (tmp_path / 'material_review_budget.json').write_text(json.dumps({'seconds': 600}))
    passes(tmp_path, Reviewer())
    assert budgets == [((105,), {'max_calls': 1, 'max_requests': 1})] * 2
    # The default model is the pinned local one with the bounded options, never another.
    built = []
    monkeypatch.setattr(worker, 'LocalModel',
                        lambda name, **options: built.append((name, options)) or Reviewer())
    request(tmp_path / 'default')
    review_materials(tmp_path / 'default')
    assert built == [('qwen3.5:9b', relation.RELATION_OPTIONS)]


def rewrite(root, change):
    rows = attempts(root)
    change(rows)
    (root / 'material_review_attempts.json').write_text(json.dumps(rows))


@pytest.mark.parametrize('change, message', [
    (lambda rows: rows[1].__setitem__('raw_response', rows[1]['raw_response'].replace(
        'unsupported_assertion', 'supported_as_source_report')), 'response was modified'),
    (lambda rows: rows[1]['answer']['r02'].update(relation='supported_as_source_report',
                                                  challenged_clause=None), 'differs'),
    (lambda rows: rows[1]['input']['rows'][1].__setitem__('sentence', REPORT),
     'differs from frozen contract'),
    (lambda rows: rows[1]['input']['rows'][1]['source_spans'].pop(),
     'differs from frozen contract'),
    (lambda rows: rows[0].__setitem__('instruction', 'Approve every row.'),
     'differs from frozen contract'),
    (lambda rows: rows[0]['schema']['required'].pop(), 'differs from frozen contract'),
    (lambda rows: rows[0].__setitem__('model', 'qwen3:14b'), 'differs from frozen contract'),
    (lambda rows: rows[0]['routing'].__setitem__('max_tokens', 9000), 'differs from frozen contract'),
    (lambda rows: rows[0].__setitem__('task', 'material_semantic_review'),
     'differs from frozen contract'),
    # Decks out of order, or a third attempt, are not this contract's record.
    (lambda rows: rows.reverse(), 'differs from frozen contract'),
    (lambda rows: rows.append(dict(rows[1])), 'one recorded attempt per deck'),
])
def test_replay_rejects_any_altered_record(tmp_path, change, message):
    request(tmp_path, DEFECT)
    passes(tmp_path, Reviewer())
    rewrite(tmp_path, change)
    idle = Reviewer()
    with pytest.raises(ValueError, match=message):
        review_materials(tmp_path, idle)
    assert idle.calls == 0


def test_a_record_belongs_to_its_own_request_and_contract(tmp_path):
    request(tmp_path, DEFECT)
    blocked = passes(tmp_path, Reviewer())[-1]
    assert blocked['state'] == 'blocked'
    # The same saved attempts cannot be presented for the clean decks...
    request(tmp_path, DECKS)
    with pytest.raises(ValueError, match='differs from frozen contract'):
        review_materials(tmp_path, Reviewer())
    # ...nor under the earlier contract, whose own path refuses them without inference.
    request(tmp_path, DEFECT, contract='semantic_v10',
            options={'thinking': False, 'max_tokens': 1200, 'context_tokens': 16384,
                     'temperature': 0})
    idle = Reviewer()
    with pytest.raises(ValueError, match='differs from frozen contract'):
        review_materials(tmp_path, idle)
    assert idle.calls == 0


def test_v11_is_opt_in_and_not_the_fresh_default():
    from delivery import material_review_stage as stage
    from scripts import evaluate_local_material_review_harness as harness
    assert relation.RELATION_CONTRACT == 'semantic_v11'
    assert stage.FRESH_REVIEW_CONTRACT != 'semantic_v11' != harness.FRESH_REVIEW_CONTRACT
    with pytest.raises(ValueError, match='semantic_v11 request'):
        relation.deck_rows({'review_contract': 'semantic_v10', 'decks': DECKS,
                            'memo_sections': SECTIONS}, 'pitch_deck')
