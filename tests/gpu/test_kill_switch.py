import base64, importlib.util, json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('kill_switch_main', Path(__file__).parents[2] / 'deploy/gcp/kill_switch/main.py')
ks = importlib.util.module_from_spec(spec); spec.loader.exec_module(ks)
ENV = {'GCP_PROJECT': 'p', 'GPU_ZONE': 'z', 'GPU_INSTANCES': 'vm1, vm2', 'DRY_RUN': 'false'}


def pubsub(cost, budget):
    body = json.dumps({'costAmount': cost, 'budgetAmount': budget}).encode()
    return {'data': base64.b64encode(body).decode()}


def run(event, env=ENV):
    calls = []
    out = ks.handle(event, stop=lambda *a: calls.append(a), env=env)
    return out, calls


def test_below_threshold_does_nothing():
    out, calls = run(pubsub(94, 100))
    assert out['action'] == 'none' and not calls


def test_at_95_percent_stops_all_instances():
    out, calls = run(pubsub(95, 100))
    assert out['action'] == 'stopped' and calls == [('p', 'z', 'vm1'), ('p', 'z', 'vm2')]


def test_nested_pubsub_envelope_and_over_budget():
    ev = {'data': {'message': pubsub(30000, 22000)}}
    out, calls = run(ev)
    assert len(calls) == 2


@pytest.mark.parametrize('bad', [{'costAmount': 'x', 'budgetAmount': 1}, {'budgetAmount': 100}, {'costAmount': 1, 'budgetAmount': 0}])
def test_malformed_fails_safe_to_stop(bad):
    ev = {'data': base64.b64encode(json.dumps(bad).encode()).decode()}
    out, calls = run(ev)
    assert len(calls) == 2


def test_dry_run_default_never_calls_api():
    out, calls = run(pubsub(99, 100), env={'GPU_INSTANCES': 'vm1'})
    assert out['action'] == 'dry_run_stop' and not calls


def test_unconfigured_instances_raises():
    with pytest.raises(RuntimeError):
        ks.handle(pubsub(99, 100), stop=lambda *a: None, env={})
