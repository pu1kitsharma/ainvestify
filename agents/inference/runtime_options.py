"""Explicit local hardware placement; never model, context or budget selection."""
from __future__ import annotations

import os

RTX2060_QWEN35_V1 = 'rtx2060-qwen35-9b-v1'
HARDWARE_PROFILE_ENV = 'LOCAL_OLLAMA_HARDWARE_PROFILE'


def validate_runtime_options(options=None):
    """Copy a small allowlist; prompt/sampling/endpoint overrides are forbidden."""
    if options is None:
        return {}
    if type(options) is not dict or set(options) - {'num_gpu', 'num_batch'}:
        raise ValueError('Runtime options permit only num_gpu and num_batch.')
    for name, value in options.items():
        minimum, maximum = (-1, 256) if name == 'num_gpu' else (1, 512)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f'Runtime option {name} requires an integer between {minimum} and {maximum}.')
    return dict(options)


def hardware_runtime_options(model, context_tokens, *, profile=None):
    """Measured opt-in for this host, with no change to any other model route.

    Ollama 0.40.11 explicitly disables vision-projector GPU offload for a
    partial text-layer request. The 6GB RTX2060 can then hold more text layers.
    This profile was measured on synthetic text, not vision or investor work.
    Larger contexts require a new measurement; never shrink their inputs.
    """
    selected = os.environ.get(HARDWARE_PROFILE_ENV, '') if profile is None else profile
    if selected == '':
        return {}
    if selected != RTX2060_QWEN35_V1:
        raise ValueError('Unknown local Ollama hardware profile.')
    if model != 'qwen3.5:9b':
        return {}
    if type(context_tokens) is not int or not 0 < context_tokens <= 16384:
        raise ValueError('The RTX2060 Qwen3.5 hardware profile requires a measured context of at most 16384 tokens.')
    return {'num_gpu': 33 if context_tokens <= 2048 else 31, 'num_batch': 128}
