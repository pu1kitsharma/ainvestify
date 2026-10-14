"""Independent core author checkpoints retain exact role and shared call plan."""
import copy
from types import SimpleNamespace
import pytest
from agents.inference.model_authorship import digest
from agents.research import memo_section_units, memo_section_review
from delivery import source_unit_content_stage as stage
from scripts import private_source_unit_worker as worker
from tests.research.test_private_source_unit_worker_v3 import fixture as previous_fixture

CORE_PIN = {'name': 'qwen3:14b', 'digest': 'c' * 64}


def fixture(root, monkeypatch, contract='memo-section-units-author-v4', section_review_contract=None):
    request, calls = previous_fixture(root, monkeypatch, contract)
    request.update(flow_contract=worker.FLOW_V4, core_author_pin=CORE_PIN)
    if contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8'}:
        request['core_reviewer_pin'] = CORE_PIN.copy()
    if section_review_contract is not None:
        request['section_review_contract'] = section_review_contract
    worker._write(root, 'content_request.json', {**request, 'digest': digest(request)})
    def author(memo, sources, pin, rows, save, model, budget, *, contract):
        assert contract == request['section_author_contract']
        if len(rows) > 6: raise ValueError('Shared author call cap exceeded')
        for index, row in enumerate(rows):
            if row != {'field': memo_section_units.FIELDS[index], 'pin': pin}:
                raise ValueError('Core author response role changed')
        if len(rows) < len(memo_section_units.FIELDS) and model is not None:
            assert model is CORE_MODEL
            field = memo_section_units.FIELDS[len(rows)]
            calls.append('section_author:' + field)
            rows.append({'field': field, 'pin': copy.deepcopy(pin)})
            save()
        if len(rows) < len(memo_section_units.FIELDS):
            return {'state': 'needs_resume', 'pending_field': memo_section_units.FIELDS[len(rows)]}
        return {'state': 'accepted', 'memo': memo, 'contract': contract,
                'response_hash': digest(rows), 'request_digest': digest({'core_pin': pin, 'contract': contract})}
    monkeypatch.setattr(memo_section_units, 'run_author', author)
    original = memo_section_review.run_review
    def review(memo, sources, authored, apin, *args, **kwargs):
        assert kwargs == ({'contract': section_review_contract} if section_review_contract is not None else {})
        assert apin == CORE_PIN
        if contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8'}:
            assert args[0] == request['core_reviewer_pin']
            if args[-2] is not None: assert args[-2] is CORE_REVIEW_MODEL
        result = original(memo, sources, authored, apin, *args)
        return {**result, **({'contract':section_review_contract} if section_review_contract is not None else {})}
    monkeypatch.setattr(memo_section_review, 'run_review', review)
    return request, calls


CORE_MODEL = object()
CORE_REVIEW_MODEL = object()


def invoke(root, phase):
    return worker.advance(root, phase, SimpleNamespace(calls=0, max_calls=6, remaining=lambda: 105),
        models={**{key: object() for key in ('characterizer_pin', 'author_pin', 'reviewer_pin')},
                'core_author_pin': CORE_MODEL, 'core_reviewer_pin': CORE_REVIEW_MODEL})


@pytest.mark.parametrize('contract', ['memo-section-units-author-v3', 'memo-section-units-author-v4', 'memo-section-units-author-v5', 'memo-section-units-author-v6', 'memo-section-units-author-v7', 'memo-section-units-author-v8'])
def test_all_fifteen_checkpoints_bind_separate_author_and_exact_gate(tmp_path, monkeypatch, contract):
    request, calls = fixture(tmp_path, monkeypatch, contract)
    assert worker.PHASES_V4 == stage.PHASES_V4
    for index, phase in enumerate(worker.PHASES_V4):
        result = invoke(tmp_path, phase)
        assert len(calls) == index + 1
        assert result['state'] == ('accepted' if index == 14 else 'needs_resume')
        if index < 14: assert result['next_phase'] == worker.PHASES_V4[index + 1]
    revision = worker.load_source_unit_revision(tmp_path)
    assert len(revision['memo_section_author_attempts']) == 5
    assert len(revision['memo_section_review_attempts']) == 5
    revised, gate = worker.replay_source_unit_revision(request['memo'], request['sources'], revision)
    assert gate == result['content_review']
    assert gate['core_author_pin'] == CORE_PIN and gate['section_author_contract'] == contract
    assert gate['final_memo_digest'] == digest(revised)
    if contract in {'memo-section-units-author-v7', 'memo-section-units-author-v8'}:
        assert gate['core_reviewer_pin'] == CORE_PIN
        changed_review = copy.deepcopy(revision); changed_review['core_reviewer_pin']['digest'] = 'd' * 64
        with pytest.raises(ValueError):
            worker.replay_source_unit_revision(request['memo'], request['sources'], changed_review)
    assert len(calls) == 15
    changed = copy.deepcopy(revision)
    changed['core_author_pin']['digest'] = 'd' * 64
    with pytest.raises(ValueError):
        worker.replay_source_unit_revision(request['memo'], request['sources'], changed)
    missing = copy.deepcopy(revision); del missing['core_author_pin']
    with pytest.raises(ValueError, match='bind its original inputs|frozen core role|Unknown source-unit revision contract'):
        worker.replay_source_unit_revision(request['memo'], request['sources'], missing)


def test_author_checkpoint_cannot_skip_unfinished_field(tmp_path, monkeypatch):
    _, calls = fixture(tmp_path, monkeypatch)
    for phase in worker.PHASES_V4[:5]: invoke(tmp_path, phase)
    result = invoke(tmp_path, 'memo_section_author_business_and_market')
    assert result['state'] == 'blocked' and 'skipped an unfinished core field' in result['detail']
    assert len(calls) == 5


def test_core_review_cannot_skip_author_coverage(tmp_path, monkeypatch):
    _, calls = fixture(tmp_path, monkeypatch)
    for phase in worker.PHASES_V4[:6]: invoke(tmp_path, phase)
    result = invoke(tmp_path, 'memo_section_review_investment_thesis')
    assert result['state'] == 'blocked' and 'complete author coverage' in result['detail']
    assert len(calls) == 6


def test_missing_core_role_is_rejected_before_inference(tmp_path, monkeypatch):
    request, calls = fixture(tmp_path, monkeypatch)
    del request['core_author_pin']
    worker._write(tmp_path, 'content_request.json', {**request, 'digest': digest(request)})
    with pytest.raises(ValueError, match='frozen core role'):
        invoke(tmp_path, worker.PHASES_V4[0])
    assert calls == []


def test_author_checkpoints_preserve_shared_six_attempt_ceiling(monkeypatch):
    monkeypatch.setattr(memo_section_units, 'frozen_requests', lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match='six-call phase contract'):
        memo_section_units.run_author({}, [], CORE_PIN,
            [{'task': memo_section_units.TASK_V4}] * 7, lambda: None, None,
            SimpleNamespace(calls=0, max_calls=6, remaining=lambda: 105),
            contract=memo_section_units.CONTRACT_V4)
    assert memo_section_units.options_for(memo_section_units.CONTRACT_V4)['bound_strings'] is True
    assert 'bound_strings' not in memo_section_units.options_for(memo_section_units.CONTRACT_V3)


def test_literal_author_contract_cannot_downgrade_to_old_flow(tmp_path, monkeypatch):
    request, calls = fixture(tmp_path, monkeypatch, 'memo-section-units-author-v5')
    request['flow_contract'] = worker.FLOW_V3
    del request['core_author_pin']
    worker._write(tmp_path, 'content_request.json', {**request, 'digest': digest(request)})
    with pytest.raises(ValueError, match='cannot downgrade'):
        invoke(tmp_path, worker.PHASES_V3[0])
    assert calls == []


def test_structured_core_requires_reviewer_pin_before_any_call(tmp_path, monkeypatch):
    request, calls = fixture(tmp_path, monkeypatch, 'memo-section-units-author-v7')
    del request['core_reviewer_pin']
    worker._write(tmp_path, 'content_request.json', {**request, 'digest': digest(request)})
    with pytest.raises(ValueError, match='exact independent reviewer role'):
        invoke(tmp_path, worker.PHASES_V4[0])
    assert calls == []


def test_structured_core_review_constructs_separate_model_with_bounded_v5_options(tmp_path, monkeypatch):
    _, calls = fixture(tmp_path, monkeypatch, 'memo-section-units-author-v7')
    for phase in worker.PHASES_V4[:10]: invoke(tmp_path, phase)
    constructed = []
    def local_model(name, **options):
        constructed.append((name, options))
        return CORE_REVIEW_MODEL
    monkeypatch.setattr(worker, 'LocalModel', local_model)
    result = worker.advance(tmp_path, worker.PHASES_V4[10],
        SimpleNamespace(calls=0, max_calls=6, remaining=lambda: 105),
        models={key: object() for key in ('characterizer_pin', 'author_pin', 'reviewer_pin')})
    assert result['state'] == 'needs_resume'
    assert constructed == [(CORE_PIN['name'], memo_section_review.options_for('memo-section-units-author-v7'))]
    assert constructed[0][1]['bound_strings'] is True
    assert constructed[0][1]['max_tokens'] == 700
    assert len(calls) == 11


def test_explicit_narrative_review_contract_binds_all_checkpoints_and_exact_replay(tmp_path, monkeypatch):
    request, calls = fixture(tmp_path, monkeypatch, 'memo-section-units-author-v8',
                             section_review_contract='memo-section-units-review-v7')
    for phase in worker.PHASES_V4:
        result = invoke(tmp_path, phase)
    assert result['state'] == 'accepted'
    revision = worker.load_source_unit_revision(tmp_path)
    assert revision['section_review_contract'] == 'memo-section-units-review-v7'
    _, gate = worker.replay_source_unit_revision(request['memo'], request['sources'], revision)
    assert gate == result['content_review']
    assert gate['section_review_contract'] == 'memo-section-units-review-v7'
    assert len(calls) == 15
    changed = copy.deepcopy(revision); changed['section_review_contract'] = 'memo-section-units-review-v6'
    with pytest.raises(ValueError):
        worker.replay_source_unit_revision(request['memo'], request['sources'], changed)
