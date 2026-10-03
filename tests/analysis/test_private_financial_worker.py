"""The private financial worker: exact request binding, atomic files, replay. Synthetic only."""
import hashlib
import json

import pytest

from agents.analysis.workbook_reconciliation import SCOPE, TASK
from agents.preparation.preparation_budget import PreparationBudgetExceeded
from scripts import private_financial_worker as worker
from tests.analysis.test_workbook_reconciliation import (CACHE, MODEL, answer, finding, ids,
                                                         workbook)

MODEL_NAME = 'qwen3.5:9b'


class Scripted:
    def __init__(self, outputs):
        self.outputs, self.calls, self.built = list(outputs), 0, []

    def __call__(self, name, **options):          # stands in for LocalModel(name, **options)
        self.built.append((name, options))
        return self

    name = MODEL_NAME
    last_response_text, last_call = '', {'host': 'test-double'}

    def generate(self, instruction, evidence, schema):
        self.calls += 1
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        self.last_response_text = json.dumps(value)
        return schema.model_validate_json(self.last_response_text)


def never():
    """A factory for a restart that must not infer."""
    return Scripted([AssertionError('no inference expected')])


def job(tmp_path, content=None, **request):
    content = workbook(MODEL, CACHE, hidden=['Inputs']) if content is None else content
    (tmp_path / 'source.xlsx').write_bytes(content)
    (tmp_path / 'request.json').write_text(json.dumps({
        'workbook': 'source.xlsx', 'workbook_sha256': hashlib.sha256(content).hexdigest(),
        'as_of_date': '2026-10-03', **request}))
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'financial': MODEL_NAME}}))
    return content


def good(content):
    cell = ids(content)
    return answer(finding('The workbook shows an Operating result of 18000 for FY2025, resting on '
                          'hidden input cells.', cell['Summary!B4']))


def files(tmp_path):
    return sorted(path.name for path in tmp_path.iterdir())


def test_one_pass_persists_bound_request_raw_attempts_and_a_partial_evidence_result(tmp_path):
    content = job(tmp_path)
    model = Scripted([good(content)])
    result = worker.run(tmp_path, model)
    assert result['state'] == 'partial_evidence' and result['analysis_state'] == 'analysed'
    # Partial cell-level evidence only; production validation stays blocked.
    assert {key: result[key] for key in SCOPE} == SCOPE
    assert 'blocked' in result['production_financial_checkpoint']
    assert result['financial_validation'] == 'not_established'
    assert result['artifact_status'] == 'diagnostic_partial_evidence_no_release'
    assert result['independent_review'] == 'pending'
    assert result['workbook_sha256'] == hashlib.sha256(content).hexdigest()
    assert result['as_of_date'] == '2026-10-03' and result['passes_used'] == 1
    assert result['model_profile'] == {'financial': MODEL_NAME, 'options': worker.MODEL_OPTIONS}
    assert model.built == [(MODEL_NAME, worker.MODEL_OPTIONS)] and model.calls == 1

    binding = json.loads((tmp_path / 'binding.json').read_text())
    assert result['request_digest'] == binding['request_digest']
    assert worker.digest({key: value for key, value in binding.items()
                          if key != 'request_digest'}) == binding['request_digest']
    assert (binding['workbook_sha256'], binding['as_of_date'], binding['model'],
            binding['max_passes'], binding['calls_per_pass']) == (
        result['workbook_sha256'], '2026-10-03', MODEL_NAME, 3, 3)
    attempts = json.loads((tmp_path / 'attempts.json').read_text())
    assert [row['task'] for row in attempts] == [TASK]
    assert attempts[0]['raw_response'] and attempts[0]['response_hash']
    assert json.loads((tmp_path / 'result.json').read_text()) == result
    assert json.loads((tmp_path / 'passes.json').read_text())['passes'][0]['attempt_ids'] == [
        attempts[0]['id']]
    assert files(tmp_path) == ['attempts.json', 'binding.json', 'model.json', 'passes.json',
                               'request.json', 'result.json', 'source.xlsx']     # no .tmp left
    assert all((tmp_path / name).stat().st_mode & 0o777 == 0o600
               for name in ('attempts.json', 'binding.json', 'passes.json', 'result.json'))


def test_restart_replays_saved_responses_without_inference(tmp_path):
    content = job(tmp_path)
    first = worker.run(tmp_path, Scripted([good(content)]))
    before = {name: (tmp_path / name).read_bytes() for name in ('attempts.json', 'passes.json')}
    idle = never()
    again = worker.run(tmp_path, idle)
    assert again == first and idle.calls == 0 and idle.built == []
    assert {name: (tmp_path / name).read_bytes() for name in before} == before
    # An altered saved response is refused, not replayed and not regenerated.
    rows = json.loads((tmp_path / 'attempts.json').read_text())
    rows[0]['raw_response'] = json.dumps(good(content)).replace('18000', '19000')
    (tmp_path / 'attempts.json').write_text(json.dumps(rows))
    tampered = worker.run(tmp_path, never())
    assert tampered['state'] == 'blocked' and tampered['reason'] == 'ValueError'
    assert 'modified' in tampered['detail']


def test_rejected_answer_is_retried_in_the_same_pass_and_both_raw_answers_are_kept(tmp_path):
    content = job(tmp_path)
    cell = ids(content)
    untraced = answer(finding('The workbook shows an Operating result of about 18500 on hidden '
                              'inputs.', cell['Summary!B4']))
    model = Scripted([untraced, good(content)])
    result = worker.run(tmp_path, model)
    assert result['state'] == 'partial_evidence' and result['attempt_count'] == 2
    attempts = json.loads((tmp_path / 'attempts.json').read_text())
    assert "numbers ['18500']" in attempts[0]['semantic_validation_error']
    assert result['response_id'] == attempts[1]['id']
    assert worker.run(tmp_path, never()) == result


def test_bounded_passes_resume_then_stop_at_the_pass_limit(tmp_path):
    content = job(tmp_path)
    cancelled = PreparationBudgetExceeded('Preparation reached its time limit during inference.')
    first = worker.run(tmp_path, Scripted([cancelled]))
    assert first['state'] == 'needs_resume' and first['passes_used'] == 1
    assert 'findings' not in first and first['financial_validation'] == 'not_established'
    # A second pass finishes it using the saved state; the cancelled call left no answer.
    second = worker.run(tmp_path, Scripted([good(content)]))
    assert second['state'] == 'partial_evidence' and second['passes_used'] == 2
    assert worker.run(tmp_path, never()) == second

    # A job that keeps yielding is stopped after three passes without further inference.
    other = tmp_path / 'stuck'
    other.mkdir()
    job(other)
    (other / 'budget.json').write_text(json.dumps({'seconds': 1}))       # never enough for a call
    for used in (1, 2, 3):
        result = worker.run(other, Scripted([good(content)]))
        assert (result['state'], result['passes_used']) == ('needs_resume', used)
    stopped = worker.run(other, never())
    assert stopped['state'] == 'blocked' and stopped['reason'] == 'pass_limit_reached'
    # No call was ever started, so there is no response to keep.
    assert stopped['passes_used'] == 3
    assert json.loads((other / 'attempts.json').read_text()) == []


def test_unsafe_workbook_is_blocked_without_inference_and_stays_blocked(tmp_path):
    stale = workbook(MODEL, {**CACHE, ('Summary', 'B2'): 61000})
    job(tmp_path, stale)
    idle = never()
    result = worker.run(tmp_path, idle)
    assert result['state'] == 'blocked' and result['reason'] == 'stale_or_missing_formula_cache'
    assert idle.calls == 0 and idle.built == [] and not (tmp_path / 'attempts.json').exists()
    assert 'request_digest' in result and result['independent_review'] == 'pending'
    assert worker.run(tmp_path, never()) == result


@pytest.mark.parametrize('change, reason', [
    (lambda root: (root / 'source.xlsx').write_bytes((root / 'source.xlsx').read_bytes() + b' '),
     'workbook_hash_differs_from_request'),
    (lambda root: (root / 'request.json').write_text(json.dumps({
        'workbook': '../source.xlsx', 'workbook_sha256': 'x', 'as_of_date': '2026-10-03'})),
     'workbook_must_be_a_file_name_in_the_job_directory'),
    (lambda root: (root / 'request.json').write_text(json.dumps({
        'workbook': 'source.xlsx', 'workbook_sha256': 'x', 'as_of_date': '2026-10-03',
        'note': 'extra'})), 'request_needs_exactly_workbook_sha256_and_as_of_date'),
    (lambda root: (root / 'model.json').write_text(json.dumps(
        {'profiles': {'financial': 'anthropic-api:claude'}})),
     'financial_model_is_not_a_local_model_name'),
    (lambda root: (root / 'model.json').write_text(json.dumps(
        {'profiles': {'financial': MODEL_NAME, 'review': MODEL_NAME}})),
     'model_profile_needs_exactly_one_financial_role'),
    (lambda root: (root / 'budget.json').write_text(json.dumps({'seconds': 600})),
     'budget_seconds_must_be_between_1_and_105'),
    (lambda root: (root / 'model.json').unlink(), 'model.json_missing'),
])
def test_invalid_request_is_blocked_before_any_inference(tmp_path, change, reason):
    job(tmp_path)
    change(tmp_path)
    idle = never()
    result = worker.run(tmp_path, idle)
    assert result['state'] == 'blocked' and result['reason'] == reason
    assert idle.calls == 0 and idle.built == []
    assert result['financial_validation'] == 'not_established'
    assert not (tmp_path / 'attempts.json').exists()


def test_bad_as_of_date_and_symlinked_workbook_are_refused(tmp_path):
    job(tmp_path, as_of_date='03/10/2026')
    assert worker.run(tmp_path, never())['reason'] == 'as_of_date_is_not_an_iso_date'
    real = tmp_path / 'elsewhere.xlsx'
    real.write_bytes((tmp_path / 'source.xlsx').read_bytes())
    (tmp_path / 'source.xlsx').unlink()
    (tmp_path / 'source.xlsx').symlink_to(real)
    job_request = json.loads((tmp_path / 'request.json').read_text())
    job_request['as_of_date'] = '2026-10-03'
    (tmp_path / 'request.json').write_text(json.dumps(job_request))
    assert worker.run(tmp_path, never())['reason'] == 'workbook_file_missing'


def test_a_changed_request_cannot_reuse_a_bound_job(tmp_path):
    content = job(tmp_path)
    first = worker.run(tmp_path, Scripted([good(content)]))
    saved = (tmp_path / 'attempts.json').read_bytes()

    # A different as-of date is a different request: nothing is replayed or inferred.
    request = json.loads((tmp_path / 'request.json').read_text())
    (tmp_path / 'request.json').write_text(json.dumps({**request, 'as_of_date': '2027-01-01'}))
    changed = worker.run(tmp_path, never())
    assert changed['state'] == 'blocked'
    assert changed['reason'] == 'request_differs_from_bound_request'
    assert changed['bound_request_digest'] == first['request_digest'] != changed['request_digest']
    assert (tmp_path / 'attempts.json').read_bytes() == saved

    # So is a different model, or a different workbook under the same name.
    (tmp_path / 'request.json').write_text(json.dumps(request))
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'financial': 'qwen3.5:4b'}}))
    assert worker.run(tmp_path, never())['reason'] == 'request_differs_from_bound_request'
    (tmp_path / 'model.json').write_text(json.dumps({'profiles': {'financial': MODEL_NAME}}))
    other = workbook(MODEL, CACHE)                      # same figures, inputs not hidden
    (tmp_path / 'source.xlsx').write_bytes(other)
    (tmp_path / 'request.json').write_text(json.dumps({
        **request, 'workbook_sha256': hashlib.sha256(other).hexdigest()}))
    assert worker.run(tmp_path, never())['reason'] == 'request_differs_from_bound_request'

    # Restoring the bound request replays the original result.
    (tmp_path / 'source.xlsx').write_bytes(content)
    (tmp_path / 'request.json').write_text(json.dumps(request))
    assert worker.run(tmp_path, never()) == first


def test_saved_response_from_outside_the_bound_request_is_refused(tmp_path):
    content = job(tmp_path)
    worker.run(tmp_path, Scripted([good(content)]))
    rows = json.loads((tmp_path / 'attempts.json').read_text())
    for change in ({'model': 'another-model'}, {'task': 'some_other_task'}):
        (tmp_path / 'attempts.json').write_text(json.dumps([{**rows[0], **change}]))
        result = worker.run(tmp_path, never())
        assert result['state'] == 'blocked'
        assert result['reason'] == 'saved_response_outside_bound_request'
    foreign = json.loads(json.dumps(rows))
    foreign[0]['input']['workbook_sha256'] = '0' * 64
    (tmp_path / 'attempts.json').write_text(json.dumps(foreign))
    assert worker.run(tmp_path, never())['reason'] == 'saved_response_outside_bound_request'


def test_main_takes_no_arguments_and_runs_in_its_directory(tmp_path, monkeypatch):
    content = job(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(worker, 'LocalModel', Scripted([good(content)]))
    monkeypatch.setattr(worker.sys, 'argv', ['private_financial_worker.py', '--anything'])
    with pytest.raises(SystemExit):
        worker.main()
    assert not (tmp_path / 'result.json').exists()
