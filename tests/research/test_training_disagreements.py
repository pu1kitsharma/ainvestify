import json

import pytest

from agents.research.training_disagreements import classify_review_disagreements as classify


def rec(cid, model, verdict, **over):
    inp = {
        'field_path': 'memo.thesis',
        'sentences': [{'id': 's1', 'text': 'Alpha.'}],
        'context': 'ctx',
        'sources': [{'id': 'a', 'version': 'v1', 'passages': ['p']}],
        'complete_source_set_digest': 'd1',
        'selected_source_ids': ['a'],
        'omitted_source_ids': ['b'],
        'complete_source_ids': ['a', 'b'],
        'review_model': model,
    }
    inp.update(over)
    return {
        'case_id': cid,
        'task': 'memo_content_review',
        'input': inp,
        'target': {'verdict': verdict, 'focus_sentence_id': 's1', 'source_id': 'a',
                   'reason': 'SECRET-REASON-' + cid},
        'provenance': {'model_name': model},
    }


def test_identical_input_differing_only_by_review_model_is_grouped():
    out = classify([
        rec('c1', 'm1', 'unsupported'),
        rec('c2', 'm2', 'supported_or_conditional'),
    ])
    assert len(out['groups']) == 1
    g = out['groups'][0]
    assert g['case_ids'] == ['c1', 'c2']
    assert g['model_names'] == ['m1', 'm2']
    assert g['verdicts'] == ['supported_or_conditional', 'unsupported']
    assert g['mixed_verdicts'] is True
    assert g['within_model_disagreement'] is False
    assert out['summary']['groups_with_mixed_verdicts'] == 1


@pytest.mark.parametrize('over', [
    {'sentences': [{'id': 's1', 'text': 'Alpha, reworded.'}]},
    {'context': 'other ctx'},
    {'field_path': 'memo.risks'},
    {'sources': [{'id': 'a', 'version': 'v2', 'passages': ['p']}]},
    {'sources': [{'id': 'a', 'version': 'v1', 'passages': ['p changed']}]},
    {'complete_source_set_digest': 'd2'},
    {'selected_source_ids': ['a', 'b'], 'omitted_source_ids': []},
    {'omitted_source_ids': ['b', 'c']},
])
def test_changed_prose_or_source_scope_stays_separate(over):
    out = classify([rec('c1', 'm1', 'unsupported'), rec('c2', 'm2', 'supported_or_conditional', **over)])
    assert len(out['groups']) == 2
    assert all(not g['mixed_verdicts'] for g in out['groups'])
    assert out['summary']['groups_with_mixed_verdicts'] == 0
    assert out['summary']['singleton_groups'] == 2


def test_one_model_contradicting_itself_is_flagged():
    out = classify([
        rec('c1', 'm1', 'unsupported'),
        rec('c2', 'm1', 'insufficient_evidence'),
        rec('c3', 'm2', 'unsupported'),
    ])
    g = out['groups'][0]
    assert g['within_model_disagreement'] is True
    assert g['mixed_verdicts'] is True
    assert out['summary']['groups_with_within_model_disagreement'] == 1


def test_same_model_same_verdict_is_not_disagreement():
    g = classify([rec('c1', 'm1', 'unsupported'), rec('c2', 'm1', 'unsupported')])['groups'][0]
    assert not g['mixed_verdicts'] and not g['within_model_disagreement']


def test_key_order_does_not_change_digest():
    a = rec('c1', 'm1', 'unsupported')
    b = rec('c2', 'm1', 'unsupported')
    b['input'] = dict(reversed(list(b['input'].items())))
    assert len(classify([a, b])['groups']) == 1


def test_other_tasks_ignored():
    other = {'case_id': 'x', 'task': 'something_else'}
    out = classify([other, rec('c1', 'm1', 'unsupported')])
    assert out['summary']['records_ignored'] == 1
    assert out['summary']['reviews'] == 1
    assert out['groups'][0]['case_ids'] == ['c1']


def test_summary_and_groups_do_not_echo_text():
    out = classify([rec('c1', 'm1', 'unsupported')])
    blob = json.dumps(out)
    assert 'SECRET-REASON' not in blob
    assert 'Alpha' not in blob


def test_rejects_unknown_verdict():
    with pytest.raises(ValueError):
        classify([rec('c1', 'm1', 'contradicted')])


def test_rejects_duplicate_case_ids():
    with pytest.raises(ValueError, match='duplicate'):
        classify([rec('c1', 'm1', 'unsupported'), rec('c1', 'm2', 'unsupported')])


@pytest.mark.parametrize('mutate', [
    lambda r: r['input'].pop('sources'),
    lambda r: r['input'].pop('review_model'),
    lambda r: r['target'].pop('reason'),
    lambda r: r['provenance'].pop('model_name'),
    lambda r: r.pop('target'),
    lambda r: r.pop('case_id'),
])
def test_rejects_missing_keys(mutate):
    r = rec('c1', 'm1', 'unsupported')
    mutate(r)
    with pytest.raises(ValueError):
        classify([r])
