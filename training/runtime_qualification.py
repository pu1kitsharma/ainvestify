"""Read-only local training prerequisites and packed-checkpoint diagnostics.

Tensor headers are inspected without materializing weights or importing CUDA.
This module never downloads, converts, trains or claims capacity from VRAM alone.
"""
from collections import Counter
import importlib.util
import json
import math
from pathlib import Path
import struct

TRAINING_PACKAGES = ('torch', 'transformers', 'peft', 'trl', 'bitsandbytes', 'datasets', 'accelerate')
MAX_HEADER = 16 * 1024 * 1024


def checkpoint_inventory(directory):
    directory = Path(directory).resolve()
    config_file = directory / 'config.json'
    if config_file.is_symlink() or not config_file.is_file() or config_file.stat().st_size > 1024 * 1024:
        raise ValueError('Bounded local checkpoint configuration required')
    config = json.loads(config_file.read_bytes())
    quant = config.get('quantization') or config.get('quantization_config') or {}
    bits = quant.get('bits') if isinstance(quant, dict) else None
    files, dtypes, packed, expanded_bytes = 0, Counter(), 0, 0
    for path in sorted(directory.glob('*.safetensors')):
        if path.is_symlink():
            raise ValueError('Checkpoint tensor symlinks are not allowed')
        with path.open('rb') as handle:
            prefix = handle.read(8)
            if len(prefix) != 8:
                raise ValueError('Invalid tensor header')
            size = struct.unpack('<Q', prefix)[0]
            if not 0 < size <= MAX_HEADER or size > path.stat().st_size - 8:
                raise ValueError('Tensor header exceeds supported bounds')
            header = json.loads(handle.read(size))
        files += 1
        for name, tensor in header.items():
            if name == '__metadata__':
                continue
            if not isinstance(tensor, dict) or not isinstance(tensor.get('shape'), list):
                raise ValueError('Invalid tensor metadata')
            shape = tensor['shape']
            if len(shape) > 8 or any(type(value) is not int or value < 0 for value in shape):
                raise ValueError('Invalid tensor shape')
            count = math.prod(shape)
            if count > 10**12:
                raise ValueError('Tensor shape exceeds bounded metadata scope')
            dtype = tensor.get('dtype')
            dtypes[dtype] += 1
            if dtype in ('U32', 'I32') and name.endswith('.weight') and bits in (2, 4, 8):
                packed += 1
                expanded_bytes += count * (32 // bits) * 2
            elif name.endswith('.weight'):
                expanded_bytes += count * 2
    mlx_packed = bool(packed and isinstance(quant, dict) and 'group_size' in quant
                      and 'quant_method' not in quant)
    return {'checkpoint_directory': str(directory), 'model_type': config.get('model_type'),
        'architectures': config.get('architectures', []), 'safetensors_files': files,
        'tensor_dtypes': dict(dtypes), 'packed_weight_tensors': packed,
        'quantization_bits': bits, 'quantization_group_size': quant.get('group_size') if isinstance(quant, dict) else None,
        'checkpoint_format': 'mlx_packed_affine' if mlx_packed else 'unqualified_safetensors',
        'estimated_expanded_bf16_weight_bytes': expanded_bytes,
        'expanded_weight_estimate_excludes_optimizer_gradients_activations': True,
        'cuda_qlora_base_qualified': False,
        'offline_conversion_status': ('requires_qualified_affine_unpack_and_transformers_architecture_mapping'
                                      if mlx_packed else 'not_qualified'),
        'weight_data_loaded': False, 'weights_converted': False}


def package_inventory(finder=importlib.util.find_spec):
    return {name: finder(name) is not None for name in TRAINING_PACKAGES}


def resolve_precision(requested, *, bf16_supported):
    if requested not in ('auto', 'fp16', 'bf16'):
        raise ValueError('Unknown training precision')
    if requested == 'bf16' and not bf16_supported:
        raise ValueError('BF16 is unsupported by the selected CUDA device')
    return 'bf16' if requested == 'bf16' or requested == 'auto' and bf16_supported else 'fp16'
