import json
import subprocess
import sys
from argparse import Namespace
from types import SimpleNamespace

import pytest

sys.path.insert(0, 'scripts')
import gpu_preflight as pf  # noqa: E402
from tests.selfhosted.fake_openai import TOKEN, FakeServer  # noqa: E402


def smi(stdout, code=0):
    return lambda *a, **k: SimpleNamespace(returncode=code, stdout=stdout, stderr='')


def test_nvidia_smi_parse_and_failures():
    ok = pf.check_nvidia_smi(smi('NVIDIA A100-SXM4-80GB, 81920, 550.54\n'), which=lambda n: '/usr/bin/nvidia-smi')
    assert ok['status'] == 'PASS' and ok['gpus'][0]['memory_gb'] == 80.0
    assert pf.check_nvidia_smi(which=lambda n: None)['status'] == 'FAIL'
    assert pf.check_nvidia_smi(smi('', 9), which=lambda n: '/x')['status'] == 'FAIL'
    assert pf.check_nvidia_smi(smi('garbage'), which=lambda n: '/x')['status'] == 'FAIL'

    def boom(*a, **k): raise subprocess.TimeoutExpired('nvidia-smi', 30)
    assert pf.check_nvidia_smi(boom, which=lambda n: '/x')['status'] == 'FAIL'


def fake_torch(available=True):
    cuda = SimpleNamespace(is_available=lambda: available, device_count=lambda: 1 if available else 0)
    return SimpleNamespace(cuda=cuda, version=SimpleNamespace(cuda='12.4'), __version__='2.5.1')


def test_torch_cuda():
    assert pf.check_torch_cuda(lambda n: fake_torch())['status'] == 'PASS'
    assert pf.check_torch_cuda(lambda n: fake_torch(False))['status'] == 'FAIL'

    def missing(n): raise ImportError(n)
    assert pf.check_torch_cuda(missing)['status'] == 'FAIL'


def test_packages_missing_is_warn_not_pass():
    r = pf.check_packages(('a', 'b'), finder=lambda n: object() if n == 'a' else None, version=lambda n: '1.0')
    assert r['status'] == 'WARN' and r['missing'] == ['b'] and r['present'] == {'a': '1.0'}
    assert pf.check_packages(('a',), finder=lambda n: object(), version=lambda n: '1')['status'] == 'PASS'


def test_disk(tmp_path):
    usage = lambda p: SimpleNamespace(free=50 * 1024 ** 3)
    assert pf.check_disk(tmp_path, 100, usage)['status'] == 'FAIL'
    assert pf.check_disk(tmp_path, 40, usage)['status'] == 'PASS'


def test_sandbox_and_office_reported_not_assumed():
    out = pf.check_sandbox(lambda: (False, 'private_process_isolation_unavailable'), lambda: None)
    assert [c['status'] for c in out] == ['WARN', 'WARN'] and 'UNRUN' in out[1]['detail']
    out = pf.check_sandbox(lambda: (True, 'available'), lambda: '/usr/bin/soffice')
    assert [c['status'] for c in out] == ['PASS', 'PASS']


def test_token_never_printed():
    r = pf.check_token({'SELFHOSTED_TOKEN': TOKEN})
    assert r['status'] == 'PASS' and TOKEN not in json.dumps(r)
    r = pf.check_token({'SELFHOSTED_TOKEN': 'short'})
    assert r['status'] == 'FAIL' and 'short' not in r['detail']


def test_vllm_reachability_private_only_and_expected_models():
    with FakeServer() as server:
        server.reply({'data': [{'id': 'banker-base'}, {'id': 'qc_associate'}]})
        env = {'SELFHOSTED_BASE_URL': server.base_url, 'SELFHOSTED_TOKEN': TOKEN, 'SELFHOSTED_ALLOWED_HOSTS': 'localhost'}
        ok = pf.check_vllm(['banker-base', 'qc_associate'], env)
        assert ok['status'] == 'PASS' and server.requests[0]['method'] == 'GET' and server.requests[0]['path'] == '/v1/models'
        assert server.requests[0]['headers']['Authorization'] == 'Bearer ' + TOKEN
        missing = pf.check_vllm(['nope'], env)
        assert missing['status'] == 'FAIL' and 'nope' in missing['detail']
        server.reply(b'', status=503)
        assert pf.check_vllm([], env)['status'] == 'FAIL'
    assert pf.check_vllm([], {})['status'] == 'FAIL'
    r = pf.check_vllm([], {'SELFHOSTED_BASE_URL': 'http://8.8.8.8:8000', 'SELFHOSTED_TOKEN': TOKEN})
    assert r['status'] == 'FAIL' and TOKEN not in json.dumps(r)


def test_run_plan_requires_named_approver(tmp_path):
    assert pf.check_run_plan(None)['status'] == 'FAIL'
    assert pf.check_run_plan(tmp_path / 'missing.md')['status'] == 'FAIL'
    blank = tmp_path / 'plan.md'
    blank.write_text('| Approver (named person, not an agent) | |\n')
    assert pf.check_run_plan(blank)['status'] == 'FAIL'
    blank.write_text('| Approver (named person, not an agent) | A. Person |\n')
    assert pf.check_run_plan(blank)['status'] == 'PASS'


def test_ledger(tmp_path):
    assert pf.check_ledger(None)['status'] == 'FAIL'
    assert pf.check_ledger(tmp_path / 'nope.db')['status'] == 'FAIL'
    from agents.inference.spend_guard import GpuSpendLedger
    path = tmp_path / 'ledger.db'
    GpuSpendLedger(path)
    assert pf.check_ledger(path)['status'] == 'PASS'


def test_main_exit_codes_and_gcp_requirements(capsys):
    def runner(args):
        base = [pf.result('x', 'PASS')]
        return base + ([pf.result('run_plan', 'FAIL')] if args.mode == 'gcp' else [])
    assert pf.main(['--mode', 'local'], runner=runner) == 0
    assert pf.main(['--mode', 'gcp'], runner=runner) == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])['passed'] is False


def test_run_all_local_makes_no_cloud_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, 'check_nvidia_smi', lambda: pf.result('nvidia_smi', 'FAIL'))
    monkeypatch.setattr(pf, 'check_torch_cuda', lambda: pf.result('torch_cuda', 'FAIL'))
    monkeypatch.delenv('SELFHOSTED_BASE_URL', raising=False)
    checks = pf.run_all(Namespace(mode='local', disk_path=str(tmp_path), min_disk_gb=1, expect_model=[], run_plan=None, ledger=None))
    names = [c['check'] for c in checks]
    assert 'run_plan' in names and next(c for c in checks if c['check'] == 'run_plan')['status'] == 'SKIP'
