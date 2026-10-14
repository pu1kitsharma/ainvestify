"""All-source scope precedes five fresh core fields; historical prose is preserved."""
import copy
import json
from types import SimpleNamespace

import pytest

from agents.inference.model_authorship import digest
from agents.research import diligence_coverage, memo_source_unit_review_v3
from agents.research import memo_section_units, memo_section_review
from delivery import source_unit_content_stage as stage
from scripts import private_source_unit_worker as worker
from tests.research.test_memo_section_units_v9 import fixture as source_fixture, CoverageModel, Model as CoreModel
from tests.research.test_memo_section_review_v8 import Model as ReviewModel

SOURCE_PIN = {'name': 'qwen3.5:9b', 'digest': 'a' * 64}
CORE_PIN = {'name': 'qwen3:14b', 'digest': 'c' * 64}


def setup(root, monkeypatch, *, source_count=None):
    memo, sources = source_fixture()
    if source_count is not None:
        template = sources[0]
        sources = [{**template, 'id': 'S' + str(index), 'version': 'source-version-' + str(index),
                    'url': 'https://example.test/source/' + str(index)} for index in range(1, source_count + 1)]
    request = {'flow_contract': worker.FLOW_V5, 'memo': memo, 'sources': sources,
        'characterizer_pin': SOURCE_PIN, 'author_pin': SOURCE_PIN, 'reviewer_pin': SOURCE_PIN,
        'author_contract': 'memo-source-unit-author-v7', 'section_author_contract': 'memo-section-units-author-v9',
        'section_review_contract': 'memo-section-units-review-v8', 'core_author_pin': CORE_PIN,
        'core_reviewer_pin': CORE_PIN, 'coverage_pin': CORE_PIN, 'coverage_contract': diligence_coverage.CONTRACT,
        'coverage_structures': {}, 'coverage_financial_scope': diligence_coverage._financial_scope(None)}
    worker._write(root, 'content_request.json', {**request, 'digest': digest(request)})
    coverage_model, core_model, review_model = CoverageModel(), CoreModel(), ReviewModel()
    coverage_model.name = core_model.name = review_model.name = CORE_PIN['name']
    calls = []

    def source_record(kind, rows, save, model):
        if not rows:
            if model is None:
                return {'state': 'needs_resume'}
            rows.append({'id': kind, 'response_hash': digest(kind)})
            calls.append(kind)
            save()
        if rows != [{'id': kind, 'response_hash': digest(kind)}]:
            raise ValueError('Synthetic legacy source record changed')
        return {'state': 'accepted', 'response_hash': digest(rows), 'request_digest': digest(kind)}

    def characterize(selected, pin, rows, save, model, budget):
        result = source_record('characterize', rows, save, model)
        return {**result, 'contract': worker.evidence.CONTRACT}

    def author(memo, sources, proof, pin, rows, save, model, budget, *, contract):
        return {**source_record('source_author', rows, save, model), 'memo': memo, 'contract': contract}

    groups = ['recommendation', 'u0', 'u1']
    monkeypatch.setattr(memo_source_unit_review_v3, 'frozen_requests', lambda *args: [(key, None, None, None) for key in groups])

    def review(memo, sources, proof, authored, apin, rpin, rows, save, model, budget):
        for index, row in enumerate(rows):
            if row != {'group': groups[index], 'response_hash': digest(groups[index])}:
                raise ValueError('Synthetic source review changed')
        if len(rows) < len(groups) and model is not None:
            group = groups[len(rows)]
            rows.append({'group': group, 'response_hash': digest(group)})
            calls.append('review:' + group)
            save()
        if len(rows) < len(groups):
            return {'state': 'needs_resume', 'batch_id': groups[len(rows)]}
        return {'state': 'accepted', 'response_hash': digest(rows), 'request_digest': digest(groups)}

    monkeypatch.setattr(worker.evidence, 'characterize_sources', characterize)
    monkeypatch.setattr(worker.author_engine, 'run_author', author)
    monkeypatch.setattr(worker.review_engine, 'run_review', review)
    return request, calls, {'coverage_pin': coverage_model, 'core_author_pin': core_model,
        'core_reviewer_pin': review_model, 'characterizer_pin': object(), 'author_pin': object(), 'reviewer_pin': object()}


def invoke(root, phase, models):
    return worker.advance(root, phase, SimpleNamespace(calls=0, max_calls=6, remaining=lambda: 105), models=models)


@pytest.mark.parametrize('coverage_contract', ['diligence-source-coverage-v3', 'diligence-source-coverage-v4',
                                             'diligence-source-coverage-v5', 'diligence-source-coverage-v6',
                                             'diligence-source-coverage-v7', 'diligence-source-coverage-v8', 'diligence-source-coverage-v9', 'diligence-source-coverage-v10', 'diligence-source-coverage-v11'])
def test_flow5_v3_request_and_raw_coverage_bundle_freeze_exact_version(tmp_path, monkeypatch, coverage_contract):
    request, _, _ = setup(tmp_path, monkeypatch)
    request['coverage_contract'] = coverage_contract
    request['digest'] = digest(request)
    worker._validate_flow5_request(request)
    bundle = worker._coverage_bundle(request, {'diligence_coverage_attempts': []})
    assert bundle['contract'] == coverage_contract
    assert bundle['model_pin'] == request['core_author_pin']
    altered = {**request, 'coverage_contract': 'diligence-source-coverage-v999'}
    altered['digest'] = digest({key: value for key, value in altered.items() if key != 'digest'})
    with pytest.raises(ValueError, match='exact frozen'):
        worker._validate_flow5_request(altered)


@pytest.mark.parametrize('author_contract,review_contract', [('memo-section-units-author-v10', 'memo-section-units-review-v9'), ('memo-section-units-author-v11', 'memo-section-units-review-v10'), ('memo-section-units-author-v12', 'memo-section-units-review-v11'), ('memo-section-units-author-v13', 'memo-section-units-review-v12')])
def test_flow5_v10_requires_paired_v9_reviewer_and_keeps_existing_phase_cap(tmp_path, monkeypatch, author_contract, review_contract):
    request, _, _ = setup(tmp_path, monkeypatch)
    request.update(section_author_contract=author_contract,
                   section_review_contract=review_contract,
                   coverage_contract=diligence_coverage.CONTRACT_V5)
    request['digest'] = digest(request)
    worker._validate_flow5_request(request)
    assert worker.CORE_PAIRS_V5 == stage.CORE_PAIRS_V5 and len(worker.PHASES_V5) == 21
    request['section_review_contract'] = 'memo-section-units-review-v8'
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    with pytest.raises(ValueError, match='exact frozen'):
        worker._validate_flow5_request(request)


def test_flow5_all_twenty_one_checkpoints_and_exact_coverage_core_replay(tmp_path, monkeypatch):
    request, calls, models = setup(tmp_path, monkeypatch)
    assert worker.PHASES_V5 == stage.PHASES_V5 and len(worker.PHASES_V5) == 21
    for index, phase in enumerate(worker.PHASES_V5):
        result = invoke(tmp_path, phase, models)
        assert result['state'] == ('accepted' if index == 20 else 'needs_resume')
        if index < 20:
            assert result['next_phase'] == worker.PHASES_V5[index + 1]
    assert calls == ['characterize', 'source_author', 'review:recommendation', 'review:u0', 'review:u1']
    revision = worker.load_source_unit_revision(tmp_path)
    assert len(revision['diligence_coverage_attempts']) == 2  # one classification + one model scope choice
    assert len(revision['memo_section_author_attempts']) == len(revision['memo_section_review_attempts']) == 5
    revised, gate = worker.replay_source_unit_revision(request['memo'], request['sources'], revision)
    assert gate == result['content_review']
    assert gate['coverage_scope'] == 'five_core_sections'
    assert gate['recommendation_and_unknown_source_scope'] == 'legacy_frozen_source_scope'
    assert gate['diligence_coverage']['coverage_complete'] is True
    assert gate['coverage_binding']['financial_evidence_scope']['financial_validation'] == 'not_established'
    assert gate['financial_validation'] == 'not_established' and gate['investment_approval'] is False
    assert revised['recommendation_reason'] == request['memo']['recommendation_reason']
    assert revised['unknowns'] == request['memo']['unknowns']
    assert json.loads((tmp_path / 'diligence_coverage_result.json').read_text()) == gate['diligence_coverage']


@pytest.mark.parametrize('production_role', [False, True])
def test_independent_coverage_model_runs_and_replays_without_rescuing_changed_pin(tmp_path, monkeypatch, production_role):
    request, _, models = setup(tmp_path, monkeypatch)
    request['coverage_pin'] = dict(SOURCE_PIN)
    if production_role:
        request['coverage_role'] = 'challenge'
    request['digest'] = digest({key: value for key, value in request.items() if key != 'digest'})
    worker._write(tmp_path, 'content_request.json', request)
    models['coverage_pin'].name = SOURCE_PIN['name']
    worker._validate_flow5_request(request)
    for phase in worker.PHASES_V5:
        result = invoke(tmp_path, phase, models)
    assert result['state'] == 'accepted'
    revision = worker.load_source_unit_revision(tmp_path)
    revised, gate = worker.replay_source_unit_revision(request['memo'], request['sources'], revision)
    assert gate['coverage_pin'] == SOURCE_PIN and gate['core_author_pin'] == CORE_PIN
    assert gate.get('coverage_role') == ('challenge' if production_role else None)
    assert ('coverage_role' in revision) == production_role
    assert all(row['model'] == SOURCE_PIN['name'] for row in revision['diligence_coverage_attempts'])
    assert all(row['model'] == CORE_PIN['name'] for row in revision['memo_section_author_attempts'])
    assert revised['recommendation_reason'] == request['memo']['recommendation_reason']
    changed = copy.deepcopy(revision)
    changed['coverage_pin'] = dict(CORE_PIN)
    with pytest.raises(ValueError, match='original inputs'):
        worker.replay_source_unit_revision(request['memo'], request['sources'], changed)
    if production_role:
        changed = copy.deepcopy(revision)
        changed['coverage_role'] = 'author'
        with pytest.raises(ValueError, match='original inputs'):
            worker.replay_source_unit_revision(request['memo'], request['sources'], changed)


def test_twenty_two_sources_have_five_classification_calls_then_one_scope_call(tmp_path, monkeypatch):
    _, calls, models = setup(tmp_path, monkeypatch, source_count=22)
    for index, phase in enumerate(worker.COVERAGE_PHASES_V5):
        result = invoke(tmp_path, phase, models)
        attempts = json.loads((tmp_path / 'diligence_coverage_attempts.json').read_text())
        assert len(attempts) == index + 1
        assert result['state'] == 'needs_resume'
    assert calls == []
    coverage = result['diligence_coverage']
    assert coverage['state'] == 'accepted' and coverage['coverage_complete'] is True
    assert len(coverage['judgments']) == 22 and coverage['unassessed_sources'] == []
    assert [len(row['input']['required_source_ids']) for row in attempts[:-1]] == [5, 5, 5, 5, 2]
    assert attempts[-1]['task'] == diligence_coverage.SELECT_TASK


@pytest.mark.parametrize('phase', ['diligence_coverage_2', 'diligence_field_selection', 'source_characterization', 'memo_section_author_investment_thesis'])
def test_skipping_unassessed_coverage_cannot_start_other_source_or_core_work(tmp_path, monkeypatch, phase):
    _, calls, models = setup(tmp_path, monkeypatch, source_count=22)
    result = invoke(tmp_path, phase, models)
    assert result['state'] == 'blocked'
    assert calls == [] and not (tmp_path / 'memo_section_author_attempts.json').exists()


def test_accepted_coverage_prefix_replays_without_repeated_model_calls(tmp_path, monkeypatch):
    _, _, models = setup(tmp_path, monkeypatch, source_count=22)
    for phase in worker.COVERAGE_PHASES_V5:
        invoke(tmp_path, phase, models)
    original = (tmp_path / 'diligence_coverage_attempts.json').read_bytes()
    class NoModel:
        def generate_for_task(self, *args, **kwargs):
            raise AssertionError('Accepted coverage must not infer again')
    models['coverage_pin'] = NoModel()
    for phase in worker.COVERAGE_PHASES_V5:
        assert invoke(tmp_path, phase, models)['state'] == 'needs_resume'
    assert (tmp_path / 'diligence_coverage_attempts.json').read_bytes() == original


def test_raw_tamper_or_missing_coverage_blocks_full_revision_replay(tmp_path, monkeypatch):
    request, _, models = setup(tmp_path, monkeypatch)
    for phase in worker.PHASES_V5:
        invoke(tmp_path, phase, models)
    revision = worker.load_source_unit_revision(tmp_path)
    for variation in ('missing', 'raw', 'scope'):
        changed = copy.deepcopy(revision)
        if variation == 'missing':
            changed['diligence_coverage_attempts'] = []
        elif variation == 'raw':
            changed['diligence_coverage_attempts'][0]['raw_response'] += ' '
        else:
            changed['coverage_financial_scope']['supplied_workbook_inventory_digest'] = 'd' * 64
        with pytest.raises(ValueError, match='coverage|original inputs'):
            worker.replay_source_unit_revision(request['memo'], request['sources'], changed)


def test_new_coverage_transport_failure_is_terminal_and_preserves_raw_failure(tmp_path, monkeypatch):
    _, calls, models = setup(tmp_path, monkeypatch)
    class Broken(CoverageModel):
        name = CORE_PIN['name']
        def generate_for_task(self, *args, **kwargs):
            raise RuntimeError('Synthetic local inference transport failed')
    models['coverage_pin'] = Broken()
    result = invoke(tmp_path, worker.PHASES_V5[0], models)
    assert result['state'] == 'blocked' and result['reason'] == 'diligence_coverage_inference_failed'
    attempts = json.loads((tmp_path / 'diligence_coverage_attempts.json').read_text())
    assert len(attempts) == 1 and attempts[0]['error']
    assert calls == []


def test_fresh_coverage_main_runs_one_call_and_honors_terminal_records(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    worker._write(tmp_path, 'content_budget.json', {'seconds': 105, 'max_calls': 6})
    phases = []
    def advance(root, phase, budget):
        phases.append(phase)
        budget.calls += 1
        return {'state': 'needs_resume', 'next_phase': phase}
    monkeypatch.setattr(worker, 'advance', advance)
    worker.main()
    assert phases == [worker.PHASES_V5[0]]
    worker._write(tmp_path, 'content_result.json', {'state': 'blocked', 'reason': 'prior_failure'})
    worker.main()
    assert phases == [worker.PHASES_V5[0]]


class InvalidFinancialDiligenceModel(CoreModel):
    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        response = super().generate_for_task(task, instruction, evidence, schema, attempt=attempt)
        payload = json.loads(evidence)
        if payload['field'] == 'diligence_plan' and not payload.get('correction_number'):
            answer = response.model_dump(mode='json')
            for unit in answer['units'].values():
                unit['requested_verification_records'] = (
                    'Request revenue records and partner delivery logs to test the reported service and competitive overlap.')
            self.last_response_text = json.dumps(answer)
            return schema.model_validate(answer)
        return response


def prepare_diligence_checkpoint(tmp_path, monkeypatch):
    request, _, models = setup(tmp_path, monkeypatch)
    phase = 'memo_section_author_diligence_plan'
    for prior in worker.PHASES_V5[:worker.PHASES_V5.index(phase)]:
        previous = invoke(tmp_path, prior, models)
    assert previous['next_phase'] == phase
    worker._write(tmp_path, 'content_result.json', previous)
    worker._write(tmp_path, 'content_budget.json', {'seconds': 105, 'max_calls': 6})
    monkeypatch.chdir(tmp_path)
    models['core_author_pin'] = InvalidFinancialDiligenceModel()
    models['core_author_pin'].name = CORE_PIN['name']
    return request, phase, models


def test_main_finishes_invalid_fifth_author_with_existing_sixth_correction_in_same_checkpoint(tmp_path, monkeypatch):
    request, phase, models = prepare_diligence_checkpoint(tmp_path, monkeypatch)
    original = json.loads((tmp_path / 'memo_section_author_attempts.json').read_text())
    real_advance, calls = worker.advance, []
    def advance(root, current, budget):
        calls.append(current)
        return real_advance(root, current, budget, models=models)
    monkeypatch.setattr(worker, 'advance', advance)
    worker.main()
    result = json.loads((tmp_path / 'content_result.json').read_text())
    assert result['state'] == 'needs_resume'
    assert result['next_phase'] == 'memo_section_review_investment_thesis'
    assert calls == [phase, phase]
    rows = json.loads((tmp_path / 'memo_section_author_attempts.json').read_text())
    assert len(rows) == 6 and rows[:4] == original
    assert 'revenue' in rows[4]['raw_response'] and 'revenue' not in rows[5]['raw_response']
    assert rows[5]['input']['correction_number'] == 1
    assert 'revenue' in rows[5]['input']['validation_error']
    accepted = memo_section_units.run_author(request['memo'], request['sources'], CORE_PIN, rows,
        lambda: None, None, worker.EMPTY_BUDGET, contract=memo_section_units.CONTRACT_V9,
        coverage=worker._coverage_bundle(request, worker.load_source_unit_revision(tmp_path)))
    assert accepted['state'] == 'accepted' and len(worker.PHASES_V5) == 21


def test_main_blocks_unfinished_correction_when_existing_checkpoint_has_insufficient_time(tmp_path, monkeypatch):
    _, phase, models = prepare_diligence_checkpoint(tmp_path, monkeypatch)
    real_advance, calls = worker.advance, []
    def advance(root, current, budget):
        calls.append(current)
        result = real_advance(root, current, budget, models=models)
        if len(calls) == 1:
            budget.started -= 90
        return result
    monkeypatch.setattr(worker, 'advance', advance)
    worker.main()
    result = json.loads((tmp_path / 'content_result.json').read_text())
    assert result['state'] == 'blocked' and result['reason'] == 'source_unit_phase_time_limit'
    assert result['next_phase'] == phase
    rows = json.loads((tmp_path / 'memo_section_author_attempts.json').read_text())
    assert len(rows) == 5 and 'revenue' in rows[-1]['raw_response']
    worker.main()
    assert calls == [phase, phase]


def test_main_blocks_same_core_checkpoint_at_existing_call_cap(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    phase = 'memo_section_author_diligence_plan'
    worker._write(tmp_path, 'content_result.json', {'state': 'needs_resume', 'next_phase': phase})
    worker._write(tmp_path, 'content_budget.json', {'seconds': 105, 'max_calls': 6})
    calls = []
    def advance(root, current, budget):
        calls.append(current)
        budget.start_call()
        return {'state': 'needs_resume', 'next_phase': phase}
    monkeypatch.setattr(worker, 'advance', advance)
    worker.main()
    result = json.loads((tmp_path / 'content_result.json').read_text())
    assert len(calls) == 6
    assert result['state'] == 'blocked' and result['reason'] == 'source_unit_phase_call_limit'
