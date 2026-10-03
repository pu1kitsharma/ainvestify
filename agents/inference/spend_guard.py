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
