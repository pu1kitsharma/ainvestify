"""Versioned, bounded relation batches over synthetic source reports."""
import json

from agents.research import material_relation_review as relation
from scripts.private_material_review_worker import review_materials
from tests.research.test_material_relation_review import (DEFECT, DECKS, Reviewer,
    capable, judged, request)


def _request(root, decks=DECKS):
    return request(root, decks, contract='semantic_v12', options=relation.BATCH_OPTIONS)


def _finish(root, model):
    for _ in relation.batch_calls(json.loads((root / 'material_review_request.json').read_text())):
        result = review_materials(root, model)
        if result['state'] != 'needs_resume':
            return result
    return result


def test_v12_batches_exact_rows_and_raw_replay(tmp_path):
    frozen = _request(tmp_path)
    calls = relation.batch_calls(frozen)
    assert [c[0] for c in calls] == ['intro_deck.batch_01', 'pitch_deck.batch_01']
    assert all(1 <= len(c[3]['rows']) <= 3 for c in calls)
    assert all(set(c[4].model_json_schema()['required']) ==
               {row['row_id'] for row in c[3]['rows']} for c in calls)
    model = Reviewer(options=relation.BATCH_OPTIONS)
    result = _finish(tmp_path, model)
    assert result['state'] == 'accepted' and result['review']['verdict'] == 'pass'
    assert result['review']['findings'] == [] and model.calls == len(calls)
    saved = (tmp_path / 'material_review_attempts.json').read_bytes()
    assert review_materials(tmp_path, Reviewer(options=relation.BATCH_OPTIONS)) == result
    assert (tmp_path / 'material_review_attempts.json').read_bytes() == saved


def test_v12_defect_binds_only_its_planted_sentence(tmp_path):
    _request(tmp_path, DEFECT)
    result = _finish(tmp_path, Reviewer(options=relation.BATCH_OPTIONS))
    assert result['state'] == 'blocked' and result['reason'] == 'model_relation_review_blocked'
    finding, = result['review']['findings']
    assert finding['sentence_id'] == 'pitch_deck.slide_1.sentence_2'
    assert finding['relation'] == relation.UNSUPPORTED
    assert finding['challenged_clause'] in finding['sentence']


def test_v12_malformed_batch_blocks_without_another_call(tmp_path):
    _request(tmp_path)
    model = Reviewer(policy=lambda payload: {**capable(payload),
        next(iter(capable(payload))): judged('unsupported_assertion', 'elsewhere')},
        options=relation.BATCH_OPTIONS)
    result = review_materials(tmp_path, model)
    assert result['state'] == 'blocked' and result['reason'] == 'material_relation_review_malformed'
    assert result['response_id'] == 'response_1'
    assert review_materials(tmp_path, model) == result and model.calls == 1


def test_v12_multiple_batches_per_deck_are_finite(tmp_path):
    body = ' '.join(f'It reports a product observation number {i} [S2].' for i in range(1, 11))
    # Source-matched rows are all complete; the call count is ceil(10/3)+one pitch call.
    sections = [['Product', body, '[S2] https://example.invalid/company'],
                ['Funding', 'It reports no completed funding transaction [S1].',
                 '[S1] https://example.invalid/registry']]
    decks = {'intro_deck': [['Product', body, '[S2] source', 'statement']],
             'pitch_deck': [['Funding', 'It reports no completed funding transaction [S1].',
                             '[S1] source', 'evidence']]}
    frozen = request(tmp_path, decks, contract='semantic_v12',
                     options=relation.BATCH_OPTIONS, sections=sections)
    assert [c[0] for c in relation.batch_calls(frozen)] == [
        'intro_deck.batch_01', 'intro_deck.batch_02', 'intro_deck.batch_03',
        'intro_deck.batch_04', 'pitch_deck.batch_01']


def test_v13_one_sentence_call_preserves_all_exact_spans_and_replays(tmp_path):
    frozen = request(tmp_path, DECKS, contract='semantic_v13',
                     options=relation.SENTENCE_OPTIONS)
    calls = relation.sentence_calls(frozen)
    assert len(calls) == 4
    assert all(call[3]['source_span_count'] == len(call[3]['source_spans']) for call in calls)
    assert all(call[3]['sentence'] == call[2]['sentence'] for call in calls)
    for _, _, row, payload, schema in calls:
        assert sorted(s['exact_span'] for s in payload['source_spans']) == sorted(
            s['exact_span'] for s in row['source_spans'])
        assert schema.model_json_schema()['required'] == [row['row_id']]
    model = Reviewer(policy=lambda payload: {payload['row_id']: judged()},
                     options=relation.SENTENCE_OPTIONS)
    result = [review_materials(tmp_path, model) for _ in calls][-1]
    assert result['state'] == 'accepted' and model.calls == len(calls)
    assert review_materials(tmp_path, model) == result and model.calls == len(calls)


def test_v13_invalid_one_sentence_blocks_without_retry(tmp_path):
    request(tmp_path, DECKS, contract='semantic_v13', options=relation.SENTENCE_OPTIONS)
    model = Reviewer(policy=lambda payload: {payload['row_id']: judged(
        'unsupported_assertion', 'elsewhere')}, options=relation.SENTENCE_OPTIONS)
    result = review_materials(tmp_path, model)
    assert result['state'] == 'blocked' and result['reason'] == 'material_relation_review_malformed'
    assert review_materials(tmp_path, model) == result and model.calls == 1
