"""Persistent conservative spend reservations across jobs and API restarts."""
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import sqlite3

from agents.preparation.preparation_budget import PreparationBudgetExceeded


def reserve_monthly(amount, request_key):
    limit = float(os.environ.get('PUBLIC_REASONING_MONTHLY_USD', '5'))
    if not math.isfinite(limit) or not 0 < limit <= 100 or not math.isfinite(amount) or amount < 0:
        raise ValueError('Public reasoning monthly budget must be finite, positive and at most $100.')
    path = Path(os.environ.get('PUBLIC_REASONING_LEDGER', str(Path(__file__).resolve().parents[2]/'.cache'/'public-spend.sqlite3')))
    path.parent.mkdir(parents=True,exist_ok=True)
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    with sqlite3.connect(str(path),timeout=5) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS reservations (month TEXT, request_key TEXT, amount REAL)')
        conn.execute('BEGIN IMMEDIATE')
        total = conn.execute('SELECT COALESCE(SUM(amount),0) FROM reservations WHERE month=?',(month,)).fetchone()[0]
        if total + amount > limit:
            raise PreparationBudgetExceeded('Public reasoning reached its configured monthly spend reservation ceiling. Saved work is retained.')
        conn.execute('INSERT INTO reservations VALUES (?,?,?)',(month,request_key,amount))
    return {'month':month,'reserved_usd':amount,'monthly_limit_usd':limit}


# --- GPU-seconds x INR ledger (private GPU pool; see deployment/GPU_RUN_PLAN_TEMPLATE.md) ---
import json as _json
import threading as _threading

GPU_POOL_HOURS = 110.0
GPU_HARD_CAP_INR = 22000.0
DEFAULT_RATES_FILE = Path(__file__).resolve().parents[2] / 'deploy' / 'gcp' / 'gpu_rates.json'


class GpuBudgetExceeded(RuntimeError):
    pass


def load_gpu_rates(path=None, machine='a100-80gb-spot'):
    """Rates are estimates, never truth: `verify_before_use` stays true until the user re-checks the GCP calculator."""
    data = _json.loads(Path(path or DEFAULT_RATES_FILE).read_text(encoding='utf-8'))
    rate = data['machines'][machine]
    value = float(rate['inr_per_hour'])
    if not math.isfinite(value) or value <= 0:
        raise ValueError('GPU rate must be finite and positive')
    return {'machine': machine, 'inr_per_hour': value, 'verify_before_use': bool(data.get('verify_before_use', True)),
            'verified_on': data.get('verified_on')}


class GpuSpendLedger:
    """Reserve-before-start ledger. Month is UTC `YYYY-MM`; GCP invoices in its own billing cycle,
    so treat this as a conservative internal guard, not the invoice."""

    def __init__(self, path, *, pool_hours=GPU_POOL_HOURS, cap_inr=GPU_HARD_CAP_INR, clock=None):
        if not 0 < pool_hours <= 1000 or not 0 < cap_inr <= 100000:
            raise ValueError('Unreasonable GPU pool or cap')
        self.path, self.pool_s, self.cap = str(path), pool_hours * 3600, float(cap_inr)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = _threading.Lock()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS gpu_reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, month TEXT NOT NULL,
                run_id TEXT NOT NULL UNIQUE, machine TEXT NOT NULL, rate_inr_per_hour REAL NOT NULL,
                reserved_seconds REAL NOT NULL, actual_seconds REAL, state TEXT NOT NULL, created TEXT NOT NULL, settled TEXT)''')

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        return c

    def month(self):
        return self.clock().strftime('%Y-%m')

    def usage(self, month=None):
        month = month or self.month()
        with self._conn() as c:
            rows = c.execute("SELECT reserved_seconds,actual_seconds,rate_inr_per_hour,state FROM gpu_reservations WHERE month=? AND state!='released'",
                             (month,)).fetchall()
        sec = sum((a if s == 'settled' else r) for r, a, _, s in rows)
        inr = sum((a if s == 'settled' else r) / 3600 * rate for r, a, rate, s in rows)
        return {'month': month, 'seconds': sec, 'hours': sec / 3600, 'inr': round(inr, 2),
                'remaining_hours': max(0, (self.pool_s - sec) / 3600), 'remaining_inr': max(0, round(self.cap - inr, 2))}

    def reserve(self, run_id, hours, rate, *, require_verified_rate=True):
        """Atomically reserve `hours` at `rate` (dict from load_gpu_rates). Raises GpuBudgetExceeded when over."""
        if not isinstance(run_id, str) or not run_id or not math.isfinite(hours) or hours <= 0 or hours > 24:
            raise ValueError('run_id and 0 < hours <= 24 are required')
        if require_verified_rate and rate.get('verify_before_use'):
            raise GpuBudgetExceeded('GPU rate is still marked verify_before_use; confirm it in the GCP calculator first')
        seconds, month = hours * 3600, self.month()
        with self._lock:
            c = self._conn()
            try:
                c.execute('BEGIN IMMEDIATE')  # cross-process write lock
                if c.execute('SELECT 1 FROM gpu_reservations WHERE run_id=?', (run_id,)).fetchone():
                    raise ValueError('run_id already reserved')
                rows = c.execute("SELECT reserved_seconds,actual_seconds,rate_inr_per_hour,state FROM gpu_reservations WHERE month=? AND state!='released'",
                                 (month,)).fetchall()
                used_s = sum((a if s == 'settled' else r) for r, a, _, s in rows)
                used_inr = sum((a if s == 'settled' else r) / 3600 * q for r, a, q, s in rows)
                cost = seconds / 3600 * rate['inr_per_hour']
                if used_s + seconds > self.pool_s + 1e-6:
                    raise GpuBudgetExceeded(f'Monthly GPU pool of {self.pool_s/3600:.0f} h would be exceeded')
                if used_inr + cost > self.cap + 1e-6:
                    raise GpuBudgetExceeded(f'Hard cap of INR {self.cap:.0f} would be exceeded')
                c.execute("INSERT INTO gpu_reservations(month,run_id,machine,rate_inr_per_hour,reserved_seconds,state,created) VALUES (?,?,?,?,?,'reserved',?)",
                          (month, run_id, rate['machine'], rate['inr_per_hour'], seconds, self.clock().isoformat()))
                c.execute('COMMIT')
            except BaseException:
                if c.in_transaction:
                    c.execute('ROLLBACK')
                raise
            finally:
                c.close()
        return {'run_id': run_id, 'month': month, 'reserved_hours': hours, 'reserved_inr': round(cost, 2)}

    def settle(self, run_id, actual_seconds):
        """Record actual usage (capped at nothing: overruns are recorded honestly and count against the month)."""
        if not math.isfinite(actual_seconds) or actual_seconds < 0:
            raise ValueError('actual_seconds must be finite and non-negative')
        with self._lock, self._conn() as c:
            n = c.execute("UPDATE gpu_reservations SET state='settled',actual_seconds=?,settled=? WHERE run_id=? AND state='reserved'",
                          (actual_seconds, self.clock().isoformat(), run_id)).rowcount
        if n != 1:
            raise ValueError('No open reservation for run_id')

    def release(self, run_id):
        """Run never started: free the reservation."""
        with self._lock, self._conn() as c:
            n = c.execute("UPDATE gpu_reservations SET state='released',actual_seconds=0,settled=? WHERE run_id=? AND state='reserved'",
                          (self.clock().isoformat(), run_id)).rowcount
        if n != 1:
            raise ValueError('No open reservation for run_id')

    def open_reservations(self):
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT run_id FROM gpu_reservations WHERE state='reserved'")]
