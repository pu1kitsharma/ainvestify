#!/usr/bin/env python3
"""Read-only GPU host pre-flight. Makes NO cloud calls, starts no model, downloads nothing.

    python scripts/gpu_preflight.py --mode local --expect-model banker-base [--min-disk-gb 200]
    python scripts/gpu_preflight.py --mode gcp --run-plan deployment/gpu_plans/run-1.md --ledger <sqlite>

Checks: nvidia-smi, torch/CUDA, ML packages, free disk, sandbox (bwrap) and LibreOffice presence,
self-hosted token (never printed), vLLM reachability on a PRIVATE address (GET /v1/models through the
same endpoint policy the runtime uses) with expected model/adapter names, and (gcp mode) an approved
run-plan file plus the spend ledger. Exit 0 when nothing FAILed; WARN/SKIP are reported, not hidden.
"""
import argparse
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PACKAGES = ('torch', 'transformers', 'peft', 'trl', 'bitsandbytes', 'accelerate', 'datasets', 'vllm')


def result(name, status, detail='', **extra):
    return {'check': name, 'status': status, 'detail': detail, **extra}


def check_nvidia_smi(runner=subprocess.run, which=shutil.which):
    if not which('nvidia-smi'):
        return result('nvidia_smi', 'FAIL', 'nvidia-smi not found: install the NVIDIA driver (see GPU_MACHINE_SETUP.md step 1)')
    try:
        out = runner(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'],
                     capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return result('nvidia_smi', 'FAIL', f'nvidia-smi could not run: {type(exc).__name__}')
    if out.returncode != 0 or not out.stdout.strip():
        return result('nvidia_smi', 'FAIL', 'nvidia-smi returned an error or no GPUs')
    gpus = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(',')]
        if len(parts) != 3 or not parts[1].isdigit():
            return result('nvidia_smi', 'FAIL', 'unparseable nvidia-smi output')
        gpus.append({'name': parts[0], 'memory_gb': round(int(parts[1]) / 1024, 1), 'driver': parts[2]})
    return result('nvidia_smi', 'PASS', f'{len(gpus)} GPU(s)', gpus=gpus)


def check_torch_cuda(importer=importlib.import_module):
    try:
        torch = importer('torch')
    except Exception as exc:  # ImportError or a broken CUDA install
        return result('torch_cuda', 'FAIL', f'torch import failed: {type(exc).__name__}')
    try:
        available = bool(torch.cuda.is_available())
        cuda = getattr(torch.version, 'cuda', None)
        count = torch.cuda.device_count() if available else 0
    except Exception as exc:
        return result('torch_cuda', 'FAIL', f'torch CUDA query failed: {type(exc).__name__}')
    if not available:
        return result('torch_cuda', 'FAIL', 'torch imports but CUDA is not available (CPU-only wheel or driver mismatch)')
    return result('torch_cuda', 'PASS', f'torch {getattr(torch, "__version__", "?")} CUDA {cuda}, {count} device(s)')


def check_packages(names=PACKAGES, finder=importlib.util.find_spec, version=importlib.metadata.version):
    present, missing = {}, []
    for name in names:
        if finder(name) is None:
            missing.append(name)
        else:
            try:
                present[name] = version(name)
            except importlib.metadata.PackageNotFoundError:
                present[name] = 'unknown'
    # vllm is normally installed on the serving host only; the rest are needed for training.
    status = 'PASS' if not missing else 'WARN'
    return result('packages', status, ('missing: ' + ', '.join(missing)) if missing else 'all present', present=present, missing=missing)


def check_disk(path, min_gb, usage=shutil.disk_usage):
    try:
        free_gb = usage(path).free / 1024 ** 3
    except OSError:
        return result('disk_free', 'FAIL', 'path not readable', path=str(path))
    status = 'PASS' if free_gb >= min_gb else 'FAIL'
    return result('disk_free', status, f'{free_gb:.0f} GB free at {path} (need >= {min_gb})', free_gb=round(free_gb, 1))


def check_sandbox(isolation=None, find_office=None):
    if isolation is None:
        from delivery import isolation as module
        isolation = module.isolation_available
    if find_office is None:
        from delivery.libreoffice import find_binary
        find_office = find_binary
    ok, reason = isolation()
    out = [result('sandbox', 'PASS' if ok else 'WARN', 'bubblewrap/sandbox-exec found' if ok else
                  f'{reason}: office recalculation will report UNRUN (apt install bubblewrap)')]
    binary = find_office()
    out.append(result('libreoffice', 'PASS' if binary else 'WARN',
                      str(binary) if binary else 'not found (set LIBREOFFICE_BINARY or install libreoffice-calc); recalculation will be UNRUN'))
    return out


def check_token(environ=None):
    from agents.inference.endpoint_policy import load_bearer_token
    try:
        load_bearer_token(environ=environ)
    except ValueError as exc:
        return result('token', 'FAIL', str(exc))
    return result('token', 'PASS', 'bearer token present (value not shown)')


def check_vllm(expect_models=(), environ=None, client_factory=None):
    from agents.inference.endpoint_policy import load_bearer_token, resolve_selfhosted_route
    from agents.inference.selfhosted_client import SelfHostedClient
    environ = os.environ if environ is None else environ
    base = environ.get('SELFHOSTED_BASE_URL', '')
    if not base:
        return result('vllm_reachable', 'FAIL', 'SELFHOSTED_BASE_URL is not set')
    try:
        token = load_bearer_token(environ=environ)
        allowed = [h for h in environ.get('SELFHOSTED_ALLOWED_HOSTS', '').split(',') if h.strip()]
        route = resolve_selfhosted_route('selfhosted:preflight', base_url=base, token=token, allowed_hosts=allowed)
        client = (client_factory or SelfHostedClient)(route, allowed_hosts=allowed)
        served = client.list_models(timeout=10)
    except Exception as exc:  # policy violation, connection fault, auth failure
        return result('vllm_reachable', 'FAIL', f'{type(exc).__name__}: {str(exc)[:160]}')
    missing = [m for m in expect_models if m not in served]
    if missing:
        return result('vllm_reachable', 'FAIL', 'server up but model/adapter not served: ' + ', '.join(missing), served=served)
    return result('vllm_reachable', 'PASS', f'{len(served)} model(s) served', served=served)


def check_run_plan(path, template_phrase='Approver (named person'):
    if not path:
        return result('run_plan', 'FAIL', '--run-plan required in gcp mode (copy deployment/GPU_RUN_PLAN_TEMPLATE.md and fill it in)')
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return result('run_plan', 'FAIL', 'run plan file missing or empty')
    approver = re.search(r'^\|\s*Approver[^|]*\|\s*([^|]*)\|', p.read_text(errors='replace'), re.M)
    if not approver or not approver.group(1).strip():
        return result('run_plan', 'FAIL', 'run plan has no named approver (an unfilled template is not an approval)')
    return result('run_plan', 'PASS', 'run plan present with a named approver (existence only; the approval itself is not verified)')


def check_ledger(path, opener=None):
    if not path:
        return result('spend_ledger', 'FAIL', '--ledger required in gcp mode')
    if not Path(path).is_file():
        return result('spend_ledger', 'FAIL', 'ledger file missing (it is created by the lifecycle controller, not by this script)')
    try:
        from agents.inference.spend_guard import GpuSpendLedger
        usage = (opener or GpuSpendLedger)(path).usage()
    except Exception as exc:
        return result('spend_ledger', 'FAIL', f'ledger unreadable: {type(exc).__name__}')
    return result('spend_ledger', 'PASS', f"{usage['hours']:.1f} h / INR {usage['inr']} used this month", usage=usage)


def run_all(args, **hooks):
    checks = [check_nvidia_smi(), check_torch_cuda(), check_packages(), check_disk(args.disk_path, args.min_disk_gb),
              *check_sandbox(), check_token(), check_vllm(args.expect_model)]
    if args.mode == 'gcp':
        checks += [check_run_plan(args.run_plan), check_ledger(args.ledger)]
    else:
        checks.append(result('run_plan', 'SKIP', 'local mode: no cloud run plan or ledger required'))
    return checks


def main(argv=None, runner=run_all):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--mode', choices=('local', 'gcp'), default='local')
    ap.add_argument('--expect-model', action='append', default=[], help='served model/adapter name that must be listed (repeatable)')
    ap.add_argument('--min-disk-gb', type=float, default=100)
    ap.add_argument('--disk-path', default=str(REPO))
    ap.add_argument('--run-plan')
    ap.add_argument('--ledger')
    args = ap.parse_args(argv)
    checks = runner(args)
    for c in checks:
        print('%-5s %-16s %s' % (c['status'], c['check'], c['detail']))
    failed = [c['check'] for c in checks if c['status'] == 'FAIL']
    print(json.dumps({'passed': not failed, 'failed': failed}))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
