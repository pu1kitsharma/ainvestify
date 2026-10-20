"""Start/wait-healthy/run/idle-stop lifecycle for one private GCP GPU VM.

Everything cloud-touching goes through an injected command runner. The default
runner is a DRY RUN: it prints the exact gcloud command it would run and
simulates VM status in memory. Nothing here creates or modifies a resource
unless the caller passes ``dry_run=False`` *and* a ``SubprocessRunner``, an
approved GPU run plan reference, and verified rates.
"""
from __future__ import annotations

import enum
import json
import shlex
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

VM_STOPPED = {'TERMINATED', 'STOPPED', 'SUSPENDED'}
VM_STOPPING = {'STOPPING', 'SUSPENDING'}


class State(str, enum.Enum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    WAITING_HEALTHY = 'waiting_healthy'
    RUNNING = 'running'
    STOPPING = 'stopping'
    PREEMPTED = 'preempted'


class GpuLifecycleError(RuntimeError):
    pass


class DryRunRunner:
    """Prints (and records) commands instead of running them; simulates instance status."""

    def __init__(self, *, echo=True, status='TERMINATED'):
        self.commands, self.status, self.echo = [], status, echo

    def __call__(self, argv):
        self.commands.append(list(argv))
        if self.echo:
            print('[dry-run] would run: ' + ' '.join(shlex.quote(a) for a in argv))
        if 'start' in argv:
            self.status = 'RUNNING'
        elif 'stop' in argv:
            self.status = 'TERMINATED'
        elif 'describe' in argv:
            return 0, self.status + '\n'
        return 0, ''


class SubprocessRunner:
    """Real runner. Never constructed by default or by tests."""

    def __call__(self, argv):
        done = subprocess.run(argv, capture_output=True, text=True, timeout=300, check=False)
        return done.returncode, done.stdout


class EventLog:
    """Append-only record of every start/stop/preemption."""

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS gpu_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, run_id TEXT, action TEXT, detail TEXT)')

    def add(self, ts, run_id, action, **detail):
        with sqlite3.connect(self.path, timeout=10) as c:
            c.execute('INSERT INTO gpu_events(ts,run_id,action,detail) VALUES (?,?,?,?)', (ts, run_id, action, json.dumps(detail, sort_keys=True)))

    def all(self):
        with sqlite3.connect(self.path) as c:
            return [(r[0], r[1], r[2], json.loads(r[3])) for r in c.execute('SELECT ts,run_id,action,detail FROM gpu_events ORDER BY id')]


def requeue_from_checkpoint(conn, jobs_api, jobs, checkpoint_ref):
    """Return fenced jobs to the queue with a pointer to the last GCS checkpoint.

    ``jobs`` are claimed job dicts (with live lease tokens). If a lease has already
    expired, ``jobs.claim`` re-queues it itself (error=worker_lease_expired); the
    failure is reported, not hidden, so the caller can record it.
    """
    outcome = {}
    for job in jobs:
        data = {**job.get('checkpoint', {}), 'gpu_checkpoint': checkpoint_ref, 'gpu_preempted': True}
        try:
            jobs_api.checkpoint(conn, job, data, state='queued')
            outcome[job['id']] = 'requeued'
        except (ValueError, PermissionError) as exc:
            outcome[job['id']] = 'not_requeued: ' + str(exc)[:120]
    return outcome


class GpuLifecycle:
    def __init__(self, *, project, zone, instance, ledger, rates, events, runner=None, health_check=None,
                 idle_timeout=900, startup_timeout=900, poll_seconds=10, clock=time.time, sleep=time.sleep,
                 dry_run=True, requeue=None):
        for name, value in (('project', project), ('zone', zone), ('instance', instance)):
            if not isinstance(value, str) or not value.replace('-', '').replace('_', '').isalnum():
                raise ValueError(f'Invalid {name}')
        if not dry_run and (runner is None or isinstance(runner, DryRunRunner)):
            raise GpuLifecycleError('A non-dry-run lifecycle needs an explicit real runner')
        if dry_run and isinstance(runner, SubprocessRunner):
            raise GpuLifecycleError('Dry-run mode refuses a real runner')
        self.project, self.zone, self.instance = project, zone, instance
        self.ledger, self.rates, self.events = ledger, rates, events
        self.runner = runner or DryRunRunner()
        self.health_check = health_check or (lambda: True)
        self.idle_timeout, self.startup_timeout, self.poll = idle_timeout, startup_timeout, poll_seconds
        self.clock, self.sleep, self.dry_run, self.requeue = clock, sleep, dry_run, requeue
        self.state, self.run_id = State.STOPPED, None
        self._started_at = self._last_activity = None
        self._busy, self._reserved_s, self._lock = 0, 0.0, threading.RLock()

    # -- helpers
    def _gcloud(self, *args):
        return ['gcloud', 'compute', 'instances', *args, self.instance, '--zone', self.zone, '--project', self.project]

    def _log(self, action, **detail):
        self.events.add(datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(), self.run_id, action, dry_run=self.dry_run, **detail)

    def _status(self):
        rc, out = self.runner(self._gcloud('describe') + ['--format=value(status)'])
        if rc != 0:
            raise GpuLifecycleError('Could not read instance status')
        return out.strip()

    # -- lifecycle
    def start(self, run_id, planned_hours, *, run_plan_ref=None):
        with self._lock:
            if self.state not in (State.STOPPED, State.PREEMPTED):
                raise GpuLifecycleError(f'Cannot start from {self.state.value}')
            if not self.dry_run and not (run_plan_ref and Path(run_plan_ref).is_file()):
                raise GpuLifecycleError('A filled GPU run plan file (deployment/GPU_RUN_PLAN_TEMPLATE.md) is required before any GPU start')
            reservation = self.ledger.reserve(run_id, planned_hours, self.rates, require_verified_rate=not self.dry_run)
            self.run_id, self._reserved_s = run_id, planned_hours * 3600
            self.state, self._started_at = State.STARTING, self.clock()
            self._last_activity = self._started_at
            self._log('start_requested', planned_hours=planned_hours, plan=run_plan_ref, reserved_inr=reservation['reserved_inr'])
            rc, _ = self.runner(self._gcloud('start'))
            if rc != 0:
                self._finish('start_failed')
                raise GpuLifecycleError('Instance start command failed; reservation settled at elapsed time')
            self.state = State.WAITING_HEALTHY
            return self.wait_healthy()

    def wait_healthy(self):
        deadline = self.clock() + self.startup_timeout
        while self.clock() < deadline:
            if self._status() == 'RUNNING' and self.health_check():
                self.state, self._last_activity = State.RUNNING, self.clock()
                self._log('healthy')
                return True
            self.sleep(self.poll)
        self._log('unhealthy_timeout')
        self.stop('startup_timeout')
        raise GpuLifecycleError('VM did not become healthy before the startup timeout; it was stopped')

    def work_started(self):
        with self._lock:
            self._busy += 1
            self._last_activity = self.clock()

    def work_finished(self):
        with self._lock:
            self._busy = max(0, self._busy - 1)
            self._last_activity = self.clock()

    def note_activity(self):
        self._last_activity = self.clock()

    def tick(self, preempt_kwargs=None):
        """Call periodically. Returns 'none', 'idle_stop', 'budget_stop' or 'preempted'."""
        with self._lock:
            if self.state != State.RUNNING:
                return 'none'
            status = self._status()
            if status in VM_STOPPED | VM_STOPPING:
                self.handle_preemption(**(preempt_kwargs or {}))
                return 'preempted'
            now = self.clock()
            if now - self._started_at >= self._reserved_s:
                self.stop('reservation_exhausted')
                return 'budget_stop'
            if self._busy == 0 and now - self._last_activity >= self.idle_timeout:
                self.stop('idle_timeout')
                return 'idle_stop'
            return 'none'

    def stop(self, reason):
        with self._lock:
            if self.state in (State.STOPPED, State.PREEMPTED):
                return
            self.state = State.STOPPING
            self._log('stop_requested', reason=reason)
            rc, _ = self.runner(self._gcloud('stop'))
            if rc != 0:
                # Do not claim it stopped. Keep the reservation open at full size.
                self._log('stop_failed', reason=reason)
                raise GpuLifecycleError('Stop command failed; VM may still be billing - stop it manually and settle the ledger')
            self._finish(reason)

    def _finish(self, reason):
        elapsed = max(0.0, self.clock() - (self._started_at or self.clock()))
        self.ledger.settle(self.run_id, elapsed)
        self._log('stopped', reason=reason, elapsed_seconds=round(elapsed, 1))
        self.state, self._busy = State.STOPPED, 0

    def handle_preemption(self, *, conn=None, jobs_api=None, jobs=(), checkpoint_ref=None):
        """Settle spend for the actual uptime, then re-queue leased jobs from the last checkpoint."""
        with self._lock:
            elapsed = max(0.0, self.clock() - (self._started_at or self.clock()))
            self.ledger.settle(self.run_id, elapsed)
            self._log('preempted', elapsed_seconds=round(elapsed, 1), checkpoint=checkpoint_ref)
            self.state, self._busy = State.PREEMPTED, 0
            outcome = {}
            if jobs and jobs_api is not None:
                outcome = (self.requeue or requeue_from_checkpoint)(conn, jobs_api, jobs, checkpoint_ref)
                self._log('requeued', outcome=outcome)
            return outcome
