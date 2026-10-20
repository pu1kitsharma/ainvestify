import threading
from datetime import datetime, timezone
import pytest
from agents.inference.spend_guard import GpuSpendLedger, GpuBudgetExceeded, load_gpu_rates

RATE = {'machine': 'm', 'inr_per_hour': 175.0, 'verify_before_use': False}


class Clock:
    def __init__(self): self.t = datetime(2026, 11, 30, 12, tzinfo=timezone.utc)
    def __call__(self): return self.t


def test_shipped_rates_are_unverified_and_refused(tmp_path):
    rates = load_gpu_rates()
    assert rates['verify_before_use'] is True
    with pytest.raises(GpuBudgetExceeded):
        GpuSpendLedger(tmp_path / 'l.db').reserve('r', 1, rates)
    GpuSpendLedger(tmp_path / 'l.db').reserve('r', 1, rates, require_verified_rate=False)  # dry-run only


def test_pool_and_inr_cap(tmp_path):
    led = GpuSpendLedger(tmp_path / 'l.db')
    led.reserve('a', 24, RATE); led.reserve('b', 24, RATE); led.reserve('c', 24, RATE); led.reserve('d', 24, RATE)  # 96h
    with pytest.raises(GpuBudgetExceeded):
        led.reserve('e', 15, RATE)  # 111h > 110h pool
    cheap_pool = GpuSpendLedger(tmp_path / 'm.db')
    expensive = {**RATE, 'inr_per_hour': 400.0}
    cheap_pool.reserve('x', 24, expensive); cheap_pool.reserve('y', 24, expensive)  # 19,200 INR
    with pytest.raises(GpuBudgetExceeded):
        cheap_pool.reserve('z', 8, expensive)  # 22,400 INR > 22,000 although only 56h of 110h
    led.reserve('f', 14, RATE)  # exactly 110h


def test_settle_frees_unused_and_release(tmp_path):
    led = GpuSpendLedger(tmp_path / 'l.db')
    led.reserve('a', 20, RATE)
    led.settle('a', 3600)
    assert led.usage()['hours'] == pytest.approx(1)
    led.reserve('b', 5, RATE); led.release('b')
    assert led.usage()['hours'] == pytest.approx(1)
    with pytest.raises(ValueError):
        led.settle('b', 1)
    with pytest.raises(ValueError):
        led.reserve('a', 1, RATE)  # duplicate run_id


def test_overrun_is_recorded_honestly(tmp_path):
    led = GpuSpendLedger(tmp_path / 'l.db')
    led.reserve('a', 1, RATE); led.settle('a', 7200)
    assert led.usage()['hours'] == pytest.approx(2)


def test_month_rollover(tmp_path):
    clock = Clock()
    led = GpuSpendLedger(tmp_path / 'l.db', clock=clock)
    [led.reserve(f'nov{i}', 20, {**RATE, 'inr_per_hour': 100.0}) for i in range(5)]
    assert led.usage()['hours'] == 100
    clock.t = datetime(2026, 12, 1, 0, 1, tzinfo=timezone.utc)
    assert led.usage()['hours'] == 0
    [led.reserve(f'dec{i}', 20, {**RATE, 'inr_per_hour': 100.0}) for i in range(5)]  # fresh pool
    assert led.usage('2026-11')['hours'] == 100


def test_concurrent_reservations_cannot_exceed_pool(tmp_path):
    path = tmp_path / 'l.db'
    results = []

    def go(i):
        try:
            GpuSpendLedger(path).reserve(f'r{i}', 10, RATE)  # separate instances = separate connections/locks
            results.append(True)
        except GpuBudgetExceeded:
            results.append(False)
    threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sum(results) == 11  # 110h / 10h
    assert GpuSpendLedger(path).usage()['hours'] <= 110
