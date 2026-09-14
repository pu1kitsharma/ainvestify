"""Deterministic routing from trusted task metadata, not instructions in scraped pages.

Weights express service preferences, not model accuracy or trained neural weights.
High-stakes preparation/review always requires the reasoning route. No hosted
fallback or automatic model installation is permitted.
"""
import json
import math
import os
import platform
import subprocess
from functools import lru_cache
from dataclasses import dataclass

REASONING_TASKS = {'preparation', 'research', 'readiness', 'investment_case', 'commercial_test', 'funding_outline',
                   'company suitability', 'diligence', 'incubation', 'documents', 'fundraising', 'metric_extraction'}


def _number(name, default, minimum, maximum, integer=False):
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or not minimum <= value <= maximum or integer and not value.is_integer():
        raise ValueError(f'{name} must be between {minimum} and {maximum}' + (' and an integer' if integer else ''))
    return int(value) if integer else value


@lru_cache(maxsize=1)
def machine_memory_gb():
    try:
        if platform.system() == 'Darwin':
            size = int(subprocess.check_output(['sysctl','-n','hw.memsize'], timeout=2))
        else:
            size = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        return size / 1024**3
    except (OSError, ValueError, subprocess.SubprocessError):
        return 16  # Conservative unknown-hardware default; never assume a large GPU.


@dataclass(frozen=True)
class RoutingPolicy:
    fast_model: str = 'phi4-mini'
    reasoning_model: str = 'qwen3:8b'
    review_model: str = 'qwen3:14b'
    escalation_model: str = 'qwen3:14b'
    quality_weight: float = 0.8
    latency_weight: float = 0.2
    reasoning_tokens: int = 8192
    fast_tokens: int = 2200
    context_tokens: int = 16384
    temperature: float = 0.0
    reasoning_temperature: float = 0.6
    resource_profile: str = 'configured'

    @classmethod
    def from_environment(cls, fast_model):
        reasoning = os.environ.get('REASONING_MODEL', 'qwen3:8b')
        compact = machine_memory_gb() < 24
        escalation = os.environ.get('ESCALATION_MODEL', '' if compact else 'qwen3:14b')
        policy = cls(fast_model=fast_model, reasoning_model=reasoning,
                    review_model=os.environ.get('REVIEW_MODEL', escalation or reasoning),
                    escalation_model=escalation,
                    quality_weight=_number('MODEL_QUALITY_WEIGHT', .8, 0, 1),
                    latency_weight=_number('MODEL_LATENCY_WEIGHT', .2, 0, 1),
                    reasoning_tokens=_number('REASONING_MAX_TOKENS', 4096 if compact else 8192, 4096, 16384, True),
                    fast_tokens=_number('FAST_MAX_TOKENS', 2200, 512, 8192, True),
                    context_tokens=_number('MODEL_CONTEXT_TOKENS', 12288 if compact else 16384, 8192, 65536, True),
                    temperature=_number('MODEL_TEMPERATURE', 0, 0, 1),
                    reasoning_temperature=_number('REASONING_TEMPERATURE', 1.0 if reasoning.startswith('qwen3.5:') else .6, .05, 1),
                    resource_profile='under_24gb' if compact else '24gb_or_more')
        if policy.quality_weight + policy.latency_weight == 0:
            raise ValueError('Routing preference weights cannot both be zero')
        for name in (policy.fast_model, policy.reasoning_model, policy.review_model) + ((policy.escalation_model,) if policy.escalation_model else ()):
            if not name or 'cloud' in name.lower():
                raise ValueError('Routing requires installed local models; cloud models are not enabled')
        if policy.context_tokens <= policy.reasoning_tokens:
            raise ValueError('MODEL_CONTEXT_TOKENS must leave room for input beyond the reasoning output budget')
        return policy

    def select(self, task, evidence, *, attempt=0):
        # Only count data volume/shape. Never interpret a page's request to use a
        # cheaper model, disable review, or change inference settings.
        try:
            payload = json.loads(evidence)
        except (ValueError, TypeError):
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        records = max((len(payload[k]) for k in ('sources', 'evidence', 'draft_fields')
                       if isinstance(payload.get(k), (list, dict))), default=0)
        is_review = task.startswith('review:')
        required = task in REASONING_TASKS or is_review or attempt > 0
        complexity = min(1., .15 + min(len(evidence) / 24000, .4) + min(records / 30, .3) + (.25 if required else 0))
        quality = self.quality_weight / (self.quality_weight + self.latency_weight)
        reason = 'quality review' if is_review else 'retry after failed validation' if attempt else 'analytical task' if required else 'input complexity and quality/latency preference'
        use_reasoning = required or complexity >= .8 - .45 * quality
        model = self.review_model if is_review else self.reasoning_model if use_reasoning else self.fast_model
        if self.escalation_model and (attempt or not is_review and complexity >= .8 + .15 * (1-quality)):
            model = self.escalation_model
            if not attempt:
                reason = 'high input complexity and quality preference'
        tokens = min(16384, self.reasoning_tokens + (2048 if attempt else 0)) if use_reasoning else self.fast_tokens
        tokens = min(tokens, self.context_tokens - 4096)
        return {'policy_version':2, 'resource_profile':self.resource_profile, 'task':task, 'model':model, 'thinking':use_reasoning,
                'complexity_score':round(complexity, 3), 'reason':reason, 'attempt':attempt,
                'quality_weight':self.quality_weight, 'latency_weight':self.latency_weight,
                'max_tokens':tokens, 'context_tokens':self.context_tokens,
                'temperature':self.reasoning_temperature if use_reasoning else self.temperature}
