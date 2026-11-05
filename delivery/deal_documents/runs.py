"""Durable state for the phased deal-documents workflow: one run per room, shown in the room UI.

A run has three phases (facts -> memo -> decks). Each phase has a list of steps
with start/finish times, so the UI can show what is happening, how long each
step took and an estimate of the time left. State lives in the app database,
not in the worker process: a page refresh, an API restart or a worker restart
shows the same state, and an interrupted phase is re-queued and resumes from
its last completed step (step outputs are cached in the run directory).

Approvals are bound to the SHA-256 of the phase output. Changing the output
after approval invalidates the approval and blocks the next phase.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import statistics
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS deal_document_runs (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, deal_id TEXT NOT NULL,
 company TEXT NOT NULL, run_dir TEXT NOT NULL, model TEXT NOT NULL, created REAL NOT NULL,
 data TEXT NOT NULL DEFAULT '{}', lease_token TEXT, lease_until REAL, revision INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS one_deal_document_run ON deal_document_runs(tenant_id, workspace_id);
"""
PHASES = ('facts', 'memo', 'decks')
PHASE_TITLES = {'facts': 'Verified fact base', 'memo': 'Investment memorandum', 'decks': 'Pitch and introductory decks'}
# Approval kinds per phase. `operator` unlocks the next phase; the memo also needs a
# recorded compliance sign-off by a qualified person before any external release.
APPROVALS = {'facts': ('operator',), 'memo': ('operator', 'compliance'), 'decks': ('operator',)}
OUTPUTS = {'facts': 'facts.json', 'memo': 'memo.json', 'decks': 'decks.json'}
# Starting estimates (seconds) per step kind, measured on the 6 GB RTX 2060 host with qwen3.8 (27B). The
# run's own completed steps of a kind replace them; other kinds scale by how this run compares with these.
# Page-copy starts with the writing allowance; page-audit starts with two checking allowances until measured.
DEFAULT_SECONDS = {'extract': 120, 'select': 46, 'crosscheck': 465, 'write': 420, 'check': 205, 'review': 1500,
                   'revise': 420, 'question': 300, 'score': 90, 'gate': 2, 'render': 60, 'slide': 500,
                   'page_copy': 420, 'page_audit': 410}
UNKNOWN_SPREAD = .4  # share of a step's expected time it may vary by before enough of its kind are measured
LEASE_SECONDS = 1200  # The worker's heartbeat thread renews it during long model calls.
MAX_INTERRUPTIONS = 3


class RunCancelled(RuntimeError):
    pass


def ensure(conn):
    conn.executescript(SCHEMA)


def _row(conn, tenant_id, workspace_id):
    row = conn.execute('SELECT id,tenant_id,workspace_id,deal_id,company,run_dir,model,created,data,lease_token,lease_until,revision '
                       'FROM deal_document_runs WHERE tenant_id=? AND workspace_id=?', (tenant_id, workspace_id)).fetchone()
    return _record(row)


def _record(row):
    if not row:
        return None
    keys = 'id tenant_id workspace_id deal_id company run_dir model created data lease_token lease_until revision'.split()
    record = dict(zip(keys, row))
    record['data'] = json.loads(record['data'])
    return record


def get(conn, tenant_id, workspace_id):
    ensure(conn)
    return _row(conn, tenant_id, workspace_id)


def get_by_id(conn, run_id):
    ensure(conn)
    row = conn.execute('SELECT id,tenant_id,workspace_id,deal_id,company,run_dir,model,created,data,lease_token,lease_until,revision '
                       'FROM deal_document_runs WHERE id=?', (run_id,)).fetchone()
    return _record(row)


def empty_phase():
    return {'state': 'not_started', 'steps': [], 'approvals': {}, 'interruptions': 0}


def create(conn, tenant_id, workspace_id, deal_id, company, run_dir, model):
    ensure(conn)
    existing = _row(conn, tenant_id, workspace_id)
    if existing:
        return existing
    data = {'phases': {phase: empty_phase() for phase in PHASES}, 'events': [], 'generation_path': 'page_first'}
    conn.execute('INSERT INTO deal_document_runs(id,tenant_id,workspace_id,deal_id,company,run_dir,model,created,data) '
                 'VALUES (?,?,?,?,?,?,?,?,?)', ('ddr_' + secrets.token_hex(12), tenant_id, workspace_id, deal_id, company,
                                                str(run_dir), model, time.time(), json.dumps(data)))
    conn.commit()
    return _row(conn, tenant_id, workspace_id)


def update(conn, run_id, change, *, lease_token=None):
    """Apply `change(data)` atomically. With `lease_token`, only the worker holding the lease may write."""
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute('SELECT data,lease_token FROM deal_document_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise LookupError('run not found')
        if lease_token is not None and row[1] != lease_token:
            raise RunCancelled('lease lost')
        data = json.loads(row[0])
        result = change(data)
        conn.execute('UPDATE deal_document_runs SET data=?, revision=revision+1, lease_until=CASE WHEN ? IS NULL THEN lease_until '
                     'ELSE ? END WHERE id=?', (json.dumps(data), lease_token, time.time() + LEASE_SECONDS, run_id))
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def _event(data, text):
    data.setdefault('events', []).append({'at': time.time(), 'text': text})
    data['events'] = data['events'][-60:]


def output_sha(run_dir, phase):
    path = Path(run_dir) / OUTPUTS[phase]
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def phase_ready(run, phase):
    """None when `phase` may start, otherwise the reason it may not."""
    index = PHASES.index(phase)
    if index == 0:
        return None
    previous = PHASES[index - 1]
    approval = run['data']['phases'][previous]['approvals'].get('operator')
    if not approval:
        return f'Approve the {PHASE_TITLES[previous].lower()} first'
    if approval['sha256'] != output_sha(run['run_dir'], previous):
        return f'The {PHASE_TITLES[previous].lower()} changed after approval; review and approve it again'
    return None


def queue(conn, run, phase, actor, generation_path=None):
    if generation_path not in (None, 'page_first', 'prose'):
        raise ValueError('Unknown generation path')
    if generation_path is not None and phase != 'memo':
        raise ValueError('Choose a generation path for the memorandum phase')
    reason = phase_ready(run, phase)
    if reason:
        raise ValueError(reason)
    def change(data):
        current = data['phases'][phase]
        if current['state'] in ('queued', 'running'):
            raise ValueError(f'{PHASE_TITLES[phase]} is already {current["state"]}')
        if any(data['phases'][other]['state'] in ('queued', 'running') for other in PHASES):
            raise ValueError('Another phase is in progress')
        if generation_path is not None:
            data['generation_path'] = generation_path
        data['phases'][phase] = {**empty_phase(), 'state': 'queued', 'queued_at': time.time(), 'queued_by': actor,
                                 'approvals': {}, 'history': current.get('history', []) + (
                                     [{k: current.get(k) for k in ('state', 'started_at', 'finished_at', 'error', 'rounds', 'page_changes')}]
                                     if current['state'] != 'not_started' else [])[-5:]}
        # Later phases depend on this one; their approvals no longer apply.
        for later in PHASES[PHASES.index(phase) + 1:]:
            if data['phases'][later]['approvals']:
                data['phases'][later]['approvals'] = {}
                data['phases'][later]['stale'] = True
        _event(data, f'{PHASE_TITLES[phase]} queued by {actor}')
    update(conn, run['id'], change)


def request_cancel(conn, run, phase, actor):
    def change(data):
        current = data['phases'][phase]
        if current['state'] == 'queued':
            current.update(state='cancelled', finished_at=time.time())
        elif current['state'] == 'running':
            current['cancel_requested'] = True
        else:
            raise ValueError(f'{PHASE_TITLES[phase]} is not in progress')
        _event(data, f'Stop requested for {PHASE_TITLES[phase].lower()} by {actor}')
    update(conn, run['id'], change)


def approve(conn, run, phase, kind, record):
    """Record an approval of the exact current phase output."""
    if kind not in APPROVALS[phase]:
        raise ValueError(f'{kind} approval does not apply to {phase}')
    sha = output_sha(run['run_dir'], phase)
    if sha is None or run['data']['phases'][phase]['state'] not in ('needs_approval', 'approved'):
        raise ValueError(f'{PHASE_TITLES[phase]} has no completed output to approve')
    def change(data):
        current = data['phases'][phase]
        current['approvals'][kind] = {**record, 'sha256': sha, 'at': time.time()}
        if all(k in current['approvals'] and current['approvals'][k].get('decision', 'approved') == 'approved'
               for k in APPROVALS[phase]):
            current['state'] = 'approved'
        _event(data, f'{PHASE_TITLES[phase]}: {kind} {record.get("decision", "approval")} by {record["by"]}')
    update(conn, run['id'], change)
    return sha


# ------------------------------------------------------------------- worker side

def claim(conn):
    """Take the oldest queued phase; re-queue phases whose worker stopped heartbeating."""
    ensure(conn)
    now = time.time()
    conn.execute('BEGIN IMMEDIATE')
    try:
        rows = conn.execute('SELECT id,data,lease_until FROM deal_document_runs').fetchall()
        for run_id, raw, lease_until in rows:
            data = json.loads(raw)
            changed = False
            for phase in PHASES:
                current = data['phases'][phase]
                if current['state'] == 'running' and (lease_until or 0) < now:
                    current['interruptions'] = current.get('interruptions', 0) + 1
                    current['state'] = 'failed' if current['interruptions'] > MAX_INTERRUPTIONS else 'queued'
                    current['error'] = 'worker_interrupted' if current['state'] == 'failed' else None
                    current['active_calls'] = {}
                    for step in current['steps']:
                        if step.get('state') == 'running':
                            step.update(state='pending', started=None, detail='interrupted; will run again')
                    _event(data, f'{PHASE_TITLES[phase]}: worker stopped; ' +
                           ('resuming from the last completed step' if current['state'] == 'queued' else 'too many interruptions'))
                    changed = True
            if changed:
                conn.execute('UPDATE deal_document_runs SET data=?, lease_token=NULL, lease_until=NULL, revision=revision+1 WHERE id=?',
                             (json.dumps(data), run_id))
        queued = []
        for run_id, raw, _ in conn.execute('SELECT id,data,lease_until FROM deal_document_runs').fetchall():
            data = json.loads(raw)
            for phase in PHASES:
                if data['phases'][phase]['state'] == 'queued':
                    queued.append((data['phases'][phase].get('queued_at', 0), run_id, phase, data))
        if not queued:
            conn.commit()
            return None
        _, run_id, phase, data = min(queued)
        token = secrets.token_hex(16)
        current = data['phases'][phase]
        current['state'] = 'running'
        current['started_at'] = current.get('started_at') or now
        current['resumed_at'] = now
        current.pop('cancel_requested', None)
        _event(data, f'{PHASE_TITLES[phase]} started')
        conn.execute('UPDATE deal_document_runs SET data=?, lease_token=?, lease_until=?, revision=revision+1 WHERE id=?',
                     (json.dumps(data), token, now + LEASE_SECONDS, run_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_by_id(conn, run_id), phase, token


def _incomplete(result):
    return isinstance(result, dict) and (result.get('state') == 'failed' or bool(result.get('failure')) or bool(result.get('failures')))


class Tracker:
    """Records steps of one running phase and caches each step's output in the run directory."""

    def __init__(self, conn, run, phase, token, version):
        self.conn, self.run, self.phase, self.token, self.version = conn, run, phase, token, version
        self.cache = Path(run['run_dir']) / 'steps' / phase
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Steps may run in worker threads (see pipeline.parallel); state updates share one connection.
        self.lock = threading.Lock()

    def _change(self, change):
        def wrapped(data):
            current = data['phases'][self.phase]
            if current.get('cancel_requested'):
                raise RunCancelled('stop requested')
            return change(current, data)
        with self.lock:
            return update(self.conn, self.run['id'], wrapped, lease_token=self.token)

    def plan(self, steps):
        """Declare the steps still to run: [(key, label, kind)]. Completed steps keep their records."""
        def change(current, data):
            known = {step['key']: step for step in current['steps']}
            current['steps'] = [known.get(key) or {'key': key, 'label': label, 'kind': kind, 'state': 'pending'}
                                for key, label, kind in steps]
        self._change(change)

    def add(self, steps, before=None):
        def change(current, data):
            keys = {step['key'] for step in current['steps']}
            new = [{'key': key, 'label': label, 'kind': kind, 'state': 'pending'} for key, label, kind in steps if key not in keys]
            position = next((i for i, step in enumerate(current['steps']) if step['key'] == before), len(current['steps']))
            current['steps'][position:position] = new
        self._change(change)

    def drop(self, key):
        self._change(lambda current, data: current.__setitem__('steps', [s for s in current['steps'] if s['key'] != key]))

    def live_questions(self):
        """The questions as they stand now, so an answer given during a run reaches the steps still to come."""
        row = self.conn.execute('SELECT data FROM deal_document_runs WHERE id=?', (self.run['id'],)).fetchone()
        return json.loads(row[0]).get('questions', [])

    def set_questions(self, questions):
        """Store the questions for the company, keeping every answer already given."""
        def change(current, data):
            merge_questions(data, questions)
        self._change(change)

    def note(self, **fields):
        """Record facts about the phase that the timer needs."""
        self._change(lambda current, data: current.update(fields))

    def round(self, record):
        def change(current, data):
            rounds = current.setdefault('rounds', [])
            rounds[:] = [item for item in rounds if item['round'] != record['round']] + [record]
        self._change(change)

    def model_call(self, fn, name, profile):
        call_id, started = secrets.token_hex(8), time.time()
        def begin(current, data):
            current.setdefault('active_calls', {})[call_id] = {'name': name, 'profile': profile, 'started': started}
        self._change(begin)
        succeeded = False
        try:
            result = fn()
            succeeded = True
            return result
        finally:
            def end(current, data):
                current.get('active_calls', {}).pop(call_id, None)
                if succeeded:
                    timings = current.setdefault('call_timings', {})
                    samples = timings.get(profile, {}).get('seconds', [])[-19:] + [round(time.time() - started, 1)]
                    timings[profile] = {'seconds': samples, 'samples': len(samples), 'mean_seconds': round(statistics.mean(samples)),
                                       'min_seconds': min(samples), 'max_seconds': max(samples)}
            self._change(end)

    def set_readiness(self, readiness):
        def change(current, data):
            data['readiness'] = {**readiness, 'phase': self.phase, 'at': time.time()}
        self._change(change)

    def _set(self, key, **fields):
        def change(current, data):
            step = next(step for step in current['steps'] if step['key'] == key)
            step.update(fields)
        self._change(change)

    def step(self, key, inputs, fn, detail=None):
        """Run fn() unless a cached output for the same inputs and model exists. Returns its JSON-serialisable result."""
        # The model is part of the key: a run moved to another model must not reuse the previous model's drafts.
        digest = hashlib.sha256(json.dumps([self.version, self.run.get('model'), inputs], sort_keys=True,
                                           default=str).encode()).hexdigest()
        path = self.cache / f'{key.replace(":", "_").replace("/", "_")}.json'
        if path.exists():
            saved = json.loads(path.read_text())
            if saved.get('inputs') == digest:
                # Keep the time it took: a restart must not throw away what the estimate has learned.
                timing = {'seconds': saved['seconds']} if saved.get('seconds') else {}
                self._set(key, state='done', cached=True, detail=saved.get('detail'), **timing)
                return saved['result']
        started = time.time()
        self._set(key, state='running', started=started, cached=False, detail=None, seconds=None, finished=None)
        try:
            result = fn()
        except RunCancelled:
            raise
        except Exception as exc:
            self._set(key, state='failed', finished=time.time(), seconds=round(time.time() - started, 1),
                      detail=f'{type(exc).__name__}: {exc}'[:400])
            raise
        summary = detail(result) if detail else None
        seconds = round(time.time() - started, 1)
        # A step that returned a model failure is retried on restart: a dead server must not become a saved result.
        if not _incomplete(result):
            path.write_text(json.dumps({'inputs': digest, 'result': result, 'detail': summary, 'seconds': seconds}, ensure_ascii=False))
            path.chmod(0o600)
        self._set(key, state='failed' if _incomplete(result) else 'done', finished=time.time(), seconds=seconds, detail=summary)
        return result

    def finish(self, state, **fields):
        def change(data):
            current = data['phases'][self.phase]
            current.pop('cancel_requested', None)
            current['active_calls'] = {}
            current.update(state=state, finished_at=time.time(), **fields)
            _event(data, f'{PHASE_TITLES[self.phase]}: {state.replace("_", " ")}')
        update(self.conn, self.run['id'], change)
        self.conn.execute('UPDATE deal_document_runs SET lease_token=NULL, lease_until=NULL WHERE id=?', (self.run['id'],))
        self.conn.commit()


def heartbeat(conn, run_id, token):
    conn.execute('UPDATE deal_document_runs SET lease_until=? WHERE id=? AND lease_token=?', (time.time() + LEASE_SECONDS, run_id, token))
    conn.commit()


# ------------------------------------------------------------------- views

def estimate(phase_state, now=None):
    """Time worked and time left for a phase, from its own measured steps.

    Elapsed counts time the phase actually worked, so an hours-long stop does not inflate it. Time left
    sums each remaining step's expected seconds, using the mean because a total is a sum of steps, and
    the low and high ends widen with how much those step times vary. Saved steps keep their measured
    seconds across restarts.
    """
    now = now or time.time()
    steps = phase_state.get('steps', [])
    measured = {}
    for step in steps:
        if step.get('state') == 'done' and step.get('seconds'):
            measured.setdefault(step['kind'], []).append(step['seconds'])
    # Kinds not yet measured scale with how this run compares with the defaults on the kinds it has run.
    ratios = [statistics.mean(seconds) / DEFAULT_SECONDS[kind] for kind, seconds in measured.items() if DEFAULT_SECONDS.get(kind)]
    speed = statistics.median(ratios) if ratios else 1.0

    def expected(kind):
        return statistics.mean(measured[kind]) if kind in measured else DEFAULT_SECONDS.get(kind, 120) * speed

    def spread(kind):
        seconds = measured.get(kind, [])
        return statistics.stdev(seconds) if len(seconds) >= 3 else expected(kind) * UNKNOWN_SPREAD
    left = variance = 0.0
    worked = sum(step.get('seconds') or 0 for step in steps if step.get('state') in ('done', 'failed'))
    for step in steps:
        if step.get('state') == 'pending':
            left += expected(step['kind'])
            variance += spread(step['kind']) ** 2
        elif step.get('state') == 'running':
            running = now - step.get('started', now)
            worked += running
            # A step past its expected time is still going: assume a little more, not that it is about to end.
            left += max(expected(step['kind']) - running, expected(step['kind']) * .15)
            variance += spread(step['kind']) ** 2
    active = phase_state.get('state') in ('running', 'queued')
    margin = 1.3 * variance ** .5 + left * .1
    # Improvement rounds run only while parts are below target, so they widen the top of the range, not the middle.
    rounds = phase_state.get('climb_rounds', 0) * phase_state.get('climb_parts', 0) * (expected('revise') + expected('score'))
    return {'elapsed_seconds': round(worked), 'remaining_seconds': round(left) if active else 0,
            'remaining_low': round(max(left - margin, 0)) if active else 0, 'remaining_high': round(left + margin + rounds) if active else 0,
            'measured_steps': sum(map(len, measured.values())),
            'steps_done': sum(step.get('state') == 'done' for step in steps), 'steps_total': len(steps),
            'estimate_basis': 'Measured means for the same kind of step in this phase; unmeasured kinds use scaled starting estimates. '
                              'The range includes timing variation and any remaining improvement rounds.',
            'timings': {kind: {'samples': len(measured.get(kind, [])), 'mean_seconds': round(expected(kind)),
                              'basis': 'measured in this phase' if kind in measured else 'starting estimate, scaled to this phase'}
                        for kind in sorted({step['kind'] for step in steps})}}


def merge_questions(data, questions):
    """Replace the open question list; an answered question stays, and a re-raised question keeps its answer."""
    known = {item['id']: item for item in data.get('questions', [])}
    kept = [item for item in known.values() if item.get('answer')]
    fresh = [{**item, 'answer': known.get(item['id'], {}).get('answer')} for item in questions if not known.get(item['id'], {}).get('answer')]
    data['questions'] = kept + fresh


def answer_question(conn, run, question_id, text, by):
    def change(data):
        item = next((item for item in data.get('questions', []) if item['id'] == question_id), None)
        if item is None:
            raise ValueError('Question not found')
        item['answer'] = {'text': text, 'by': by, 'at': time.time()} if text else None
        _event(data, f'Question answered by {by}' if text else f'Answer withdrawn by {by}')
    update(conn, run['id'], change)


def public(run):
    if run is None:
        return None
    now = time.time()
    phases = {}
    for phase in PHASES:
        state = run['data']['phases'][phase]
        approvals = {kind: {k: v for k, v in record.items() if k != 'sha256'} | {
            'current': record.get('sha256') == output_sha(run['run_dir'], phase)} for kind, record in state['approvals'].items()}
        phases[phase] = {**{k: v for k, v in state.items() if k not in ('approvals',)}, 'title': PHASE_TITLES[phase],
                         'approvals': approvals, 'required_approvals': list(APPROVALS[phase]),
                         'blocked_reason': phase_ready(run, phase), **estimate(state, now)}
    return {'id': run['id'], 'company': run['company'], 'model': run['model'], 'created': run['created'], 'now': now,
            'generation_path': run['data'].get('generation_path', 'prose'),
            'worker_alive': (run.get('lease_until') or 0) > now, 'phases': phases, 'events': run['data'].get('events', [])[-20:],
            'questions': run['data'].get('questions', []), 'readiness': run['data'].get('readiness')}
