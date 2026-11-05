"""Record local training prerequisites without imports, downloads or weight updates."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

from training.private_storage import private_path
from training.reference_intake import ROOT, _write
from training.runtime_qualification import checkpoint_inventory, package_inventory


def qualify(checkpoints, output, *, private_root, reference_summary=None, benchmark_summary=None):
    output = private_path(output, root=private_root, repo_root=ROOT)
    if output.exists():
        raise ValueError('Runtime qualifications are immutable')
    packages = package_inventory()
    memory = {'scope': 'qualification_process_runtime_not_Windows_Ollama_host',
              'total_bytes': None, 'available_bytes': None}
    try:
        memory['total_bytes'] = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                memory['available_bytes'] = int(line.split()[1]) * 1024
    except (AttributeError, OSError, ValueError):
        pass
    gpu = {'status': 'unavailable'}
    binary = shutil.which('nvidia-smi') or '/usr/lib/wsl/lib/nvidia-smi'
    if Path(binary).is_file():
        result = subprocess.run([binary, '--query-gpu=name,memory.total,memory.free,compute_cap',
            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            rows = []
            for line in result.stdout.splitlines():
                values = [value.strip() for value in line.split(',')]
                if len(values) != 4:
                    raise ValueError('Unrecognized GPU metadata')
                rows.append({'name': values[0], 'total_mib': int(values[1]),
                             'free_mib': int(values[2]), 'compute_capability': values[3]})
            gpu = {'status': 'observed', 'devices': rows}
    inventories = []
    for checkpoint in checkpoints:
        checkpoint = Path(checkpoint).resolve()
        if checkpoint.is_relative_to(ROOT) or ROOT.is_relative_to(checkpoint):
            raise ValueError('Private checkpoint metadata must stay outside the source checkout')
        inventories.append(checkpoint_inventory(checkpoint))
    local_models = []
    model_inventory_status = 'unavailable'
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Model inventory exceeds its bound')
        for model in json.loads(raw).get('models', []):
            details = model.get('details') or {}
            local_models.append({'name': model['name'], 'sha256': model.get('digest'),
                'weight_bytes': model.get('size'), 'parameter_size': details.get('parameter_size'),
                'format': details.get('format'), 'quantization': details.get('quantization_level')})
        model_inventory_status = 'observed'
    except (OSError, ValueError):
        pass
    report = {'contract': 'local-training-runtime-qualification-v1',
        'recorded_at': datetime.now(timezone.utc).isoformat(), 'packages': packages,
        'missing_training_packages': [key for key, present in packages.items() if not present],
        'gpu': gpu, 'runtime_memory': memory, 'checkpoints': inventories, 'installed_models': local_models,
        'model_inventory_status': model_inventory_status,
        'checkpoint_capacity_estimates_are_not_qualification': True,
        'required_corpus': 'independently_reviewed_nonholdout_training_and_frozen_validation_test_families',
        'required_conversion': 'qualified_local_Transformers_checkpoint_for_the_exact_architecture_and_tokenizer',
        'training_ready': False, 'weights_updated': False, 'downloads_performed': False,
        'model_routes_changed': False, 'release_qualified': False}
    for key, path in (('reference_preparation', reference_summary), ('synthetic_benchmark', benchmark_summary)):
        if path is not None:
            path = private_path(path, root=private_root, repo_root=ROOT)
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('Qualification metadata exceeds its bound')
            report[key] = json.loads(path.read_bytes())
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write(output / 'report.json', report)
    return {key: report[key] for key in ('contract', 'missing_training_packages', 'gpu',
        'training_ready', 'weights_updated', 'downloads_performed', 'model_routes_changed')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--reference-summary', type=Path)
    parser.add_argument('--benchmark-summary', type=Path)
    args = parser.parse_args()
    try:
        summary = qualify(args.checkpoint, args.output, private_root=args.private_root,
            reference_summary=args.reference_summary, benchmark_summary=args.benchmark_summary)
    except Exception:
        parser.exit(1, 'Runtime qualification failed; inspect approved local metadata.\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
