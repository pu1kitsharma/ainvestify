"""Five-phase worker scheduling and exact gate binding with deterministic engines."""
import copy
from types import SimpleNamespace
import pytest
from agents.inference.model_authorship import digest
from agents.research import memo_section_units, memo_section_review
from scripts import private_source_unit_worker as worker
from delivery import source_unit_content_stage as stage
from tests.research.test_memo_causal_review import sample

PIN = {'name': 'qwen3.5:9b', 'digest': 'a' * 64}


def fixture(root, monkeypatch, core_status='accepted', partial=False):
    memo, sources = sample()
    request = {'flow_contract': worker.FLOW_V2, 'author_contract': 'memo-source-unit-author-v7',
               'memo': memo, 'sources': sources,
               'characterizer_pin': PIN, 'author_pin': PIN, 'reviewer_pin': PIN}
    worker._write(root, 'content_request.json', {**request, 'digest': digest(request)})
    new_calls = []
    def record(kind, rows, save, model, **fields):
        if not rows:
            if model is None: return {'state': 'needs_resume'}
            new_calls.append(kind)
            raw = {'synthetic_engine': kind}
            rows.append({'id': kind + '_1', 'raw_response': raw, 'response_hash': digest(raw)})
            save()
        if len(rows) != 1 or rows[0]['raw_response'] != {'synthetic_engine': kind} or rows[0]['response_hash'] != digest(rows[0]['raw_response']):
            raise ValueError('Synthetic exact response changed')
        return {'state': 'accepted', 'response_hash': rows[0]['response_hash'],
                'request_digest': digest({'synthetic_engine': kind}), **fields}
    def characterize(sources, pin, rows, save, model, budget):
        return record('characterize', rows, save, model, contract=worker.evidence.CONTRACT)
    def author(memo, sources, proof, pin, rows, save, model, budget, **kwargs):
        assert kwargs['contract'] == 'memo-source-unit-author-v7'
        return record('source_author', rows, save, model, memo=memo, contract=kwargs['contract'])
    def review(memo, sources, proof, authored, apin, rpin, rows, save, model, budget):
        return record('source_review', rows, save, model)
    def section_author(memo, sources, pin, rows, save, model, budget, *, contract='memo-section-units-author-v1'):
        return record('section_author', rows, save, model, memo=memo, contract=contract)
    def section_review(memo, sources, core, apin, rpin, rows, save, model, budget):
        result = record('section_review', rows, save, model,
                        coverage=list(memo_section_units.FIELDS)[:-1] if partial else list(memo_section_units.FIELDS))
        if result['state'] == 'accepted': result['state'] = core_status
        return result
    monkeypatch.setattr(worker.evidence, 'characterize_sources', characterize)
    monkeypatch.setattr(worker.author_engine, 'run_author', author)
    monkeypatch.setattr(worker.review_engine, 'run_review', review)
    monkeypatch.setattr(memo_section_units, 'run_author', section_author)
    monkeypatch.setattr(memo_section_review, 'run_review', section_review)
    return request, new_calls


def invoke(root, phase):
    return worker.advance(root, phase, SimpleNamespace(calls=0, max_calls=6, remaining=lambda: 105),
                          models={key: object() for key in ('characterizer_pin', 'author_pin', 'reviewer_pin')})


def test_all_five_phases_must_finish_before_gate_and_exact_hash_replay(tmp_path, monkeypatch):
    request, calls = fixture(tmp_path, monkeypatch)
    assert worker.phases_for(worker.FLOW_V2) == stage.PHASES_V2
    for number, phase in enumerate(worker.PHASES_V2):
        result = invoke(tmp_path, phase)
        assert len(calls) == number + 1
        if number < 4:
            assert result['state'] == 'needs_resume'
            assert result['next_phase'] == worker.PHASES_V2[number + 1]
        else:
            assert result['state'] == 'accepted'
    record = worker.load_source_unit_revision(tmp_path)
    memo, gate = worker.replay_source_unit_revision(request['memo'], request['sources'], record)
    assert gate == result['content_review']
    assert gate['coverage'] == ['recommendation_reason', 'unknowns', *memo_section_units.FIELDS]
    assert gate['contract'] == worker.FLOW_V2 and gate['final_memo_digest'] == digest(memo)
    assert gate['section_author_response_hash'] == record['memo_section_author_attempts'][0]['response_hash']
    assert gate['section_review_response_hash'] == record['memo_section_review_attempts'][0]['response_hash']
    assert gate['investment_approval'] is False
    assert len(calls) == 5  # Exact replay starts no inference.
    changed = copy.deepcopy(record)
    changed['memo_section_review_attempts'][0]['response_hash'] = 'b' * 64
    with pytest.raises(ValueError, match='response changed'):
        worker.replay_source_unit_revision(request['memo'], request['sources'], changed)
    missing = copy.deepcopy(record); missing['memo_section_review_attempts'] = []
    with pytest.raises(ValueError, match='five core fields'):
        worker.replay_source_unit_revision(request['memo'], request['sources'], missing)


@pytest.mark.parametrize('status,partial', [('blocked', False), ('accepted', True)])
def test_rejected_or_partial_core_review_never_promotes_full_memo(tmp_path, monkeypatch, status, partial):
    request, calls = fixture(tmp_path, monkeypatch, core_status=status, partial=partial)
    for phase in worker.PHASES_V2:
        result = invoke(tmp_path, phase)
    assert result['state'] == 'blocked'
    assert 'content_review' not in result
    record = worker.load_source_unit_revision(tmp_path)
    with pytest.raises(ValueError, match='five core fields'):
        worker.replay_source_unit_revision(request['memo'], request['sources'], record)
    assert len(calls) == 5


def test_core_phase_cannot_skip_required_source_review(tmp_path, monkeypatch):
    _, calls = fixture(tmp_path, monkeypatch)
    invoke(tmp_path, worker.PHASES_V2[0]); invoke(tmp_path, worker.PHASES_V2[1])
    result = invoke(tmp_path, 'memo_section_author')
    assert result['state'] != 'accepted'
    assert calls == ['characterize', 'source_author']


def test_backward_phase_is_rejected_before_spending_a_source_review_call(tmp_path, monkeypatch):
    _, calls = fixture(tmp_path, monkeypatch)
    invoke(tmp_path, worker.PHASES_V2[0]); invoke(tmp_path, worker.PHASES_V2[1])
    worker._write(tmp_path, 'memo_section_author_attempts.json', [{'synthetic_later_phase': True}])
    result = invoke(tmp_path, worker.PHASES_V2[2])
    assert result['state'] == 'blocked' and 'backwards' in result['detail']
    assert calls == ['characterize', 'source_author']
