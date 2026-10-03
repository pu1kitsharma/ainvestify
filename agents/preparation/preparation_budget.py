"""Per-run local inference limits, shared by queueing and answer continuation."""
import os
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar


class PreparationBudgetExceeded(RuntimeError):
    pass


ACTIVE_BUDGET = ContextVar('preparation_inference_budget', default=None)


class PreparationBudget:
    def __init__(self, max_seconds=None, max_calls=24, max_requests=32):
        self.max_seconds = float(max_seconds if max_seconds is not None else os.environ.get('PREPARATION_MAX_SECONDS', '120'))
        if not 0 < self.max_seconds <= 120 or not 0 < max_calls <= 100 or not 0 < max_requests <= 150:
            raise ValueError('Preparation budgets require 0–120 seconds and bounded positive call/request counts.')
        self.max_calls, self.max_requests = max_calls, max_requests
        self.started = time.monotonic()
        self.calls = self.requests = 0
        self.cache_hits = 0
        self.reserved_cost_usd = 0.0
        self.max_cost_usd = .25

    def reserve_cost(self, maximum):
        self.remaining()
        if not math.isfinite(maximum) or maximum < 0 or self.reserved_cost_usd + maximum > self.max_cost_usd:
            raise PreparationBudgetExceeded('Public reasoning reached its $0.25 per-pass cost ceiling; saved work is retained.')
        self.reserved_cost_usd += maximum

    def remaining(self):
        remaining = self.max_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise PreparationBudgetExceeded('This preparation pass reached its time limit. Saved work is retained.')
        return remaining

    def start_call(self):
        self.remaining()
        if self.calls >= self.max_calls:
            raise PreparationBudgetExceeded('This preparation pass reached its model-call limit. Saved work is retained.')
        self.calls += 1

    def start_request(self):
        self.remaining()
        if self.requests >= self.max_requests:
            raise PreparationBudgetExceeded('Preparation reached its inference-request limit, including reasoning continuations.')
        self.requests += 1

    def snapshot(self):
        return {'max_seconds':self.max_seconds, 'max_calls':self.max_calls, 'max_requests':self.max_requests,
                'calls':self.calls, 'requests':self.requests, 'elapsed_seconds':round(time.monotonic()-self.started,3),
                'cache_hits':self.cache_hits,'reserved_cost_usd':self.reserved_cost_usd,'max_cost_usd':self.max_cost_usd}


@contextmanager
def preparation_budget(budget=None):
    budget = budget or ACTIVE_BUDGET.get() or PreparationBudget()
    token = ACTIVE_BUDGET.set(budget)
    try:
        yield budget
    finally:
        ACTIVE_BUDGET.reset(token)
