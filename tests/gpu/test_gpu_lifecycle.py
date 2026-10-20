import pytest
from agents.inference.spend_guard import GpuSpendLedger
from delivery.gpu_lifecycle import (GpuLifecycle, DryRunRunner, EventLog, State, GpuLifecycleError, SubprocessRunner,
                                    requeue_from_checkpoint)

RATE = {'machine': 'm', 'inr_per_hour': 175.0, 'verify_before_use': False}


class T:
    def __init__(self): self.now = 1_800_000_000.0
    def __call__(self): return self.now
    def sleep(self, s): self.now += s


class FakeRunner:
    def __init__(self, status='TERMINATED', fail=()):
        self.status, self.cmds, self.fail = status, [], set(fail)
    def __call__(self, argv):
        self.cmds.append(argv)
        verb = next(v for v in ('describe', 'start', 'stop') if v in argv)
        if verb in self.fail: return 1, ''
        if verb == 'start': self.status = 'RUNNING'
        if verb == 'stop': self.status = 'TERMINATED'
        return 0, (self.status + '\n') if verb == 'describe' else ''


def make(tmp_path, runner=None, dry=True, **kw):
    t = T()
    led = GpuSpendLedger(tmp_path / 'l.db', clock=lambda: __import__('datetime').datetime.fromtimestamp(t.now, __import__('datetime').timezone.utc))
    ev = EventLog(tmp_path / 'e.db')
    gl = GpuLifecycle(project='p', zone='z', instance='vm', ledger=led, rates=RATE, events=ev, runner=runner or DryRunRunner(echo=False),
                      clock=t, sleep=t.sleep, dry_run=dry, **kw)
    return gl, t, led, ev


def test_dry_run_default_prints_commands_and_runs_state_machine(tmp_path, capsys):
    gl, t, led, ev = make(tmp_path, runner=DryRunRunner(echo=True))
    gl.start('r1', 2)
    assert gl.state == State.RUNNING
    out = capsys.readouterr().out
    assert '[dry-run] would run: gcloud compute instances start vm --zone z --project p' in out
    gl.stop('manual'); assert gl.state == State.STOPPED
    assert [e[2] for e in ev.all()] == ['start_requested', 'healthy', 'stop_requested', 'stopped']


def test_real_runner_refused_in_dry_run_and_dry_runner_refused_for_real(tmp_path):
    with pytest.raises(GpuLifecycleError):
        make(tmp_path, runner=SubprocessRunner())
    with pytest.raises(GpuLifecycleError):
        make(tmp_path, dry=False)


def test_real_mode_needs_plan_file_and_verified_rates(tmp_path):
    gl, *_ = make(tmp_path, runner=FakeRunner(), dry=False)
    with pytest.raises(GpuLifecycleError):
        gl.start('r', 1)
    plan = tmp_path / 'plan.md'; plan.write_text('approved')
    gl.rates = {**RATE, 'verify_before_use': True}
    with pytest.raises(Exception):
        gl.start('r', 1, run_plan_ref=str(plan))
    gl.rates = RATE
    gl.start('r', 1, run_plan_ref=str(plan)); assert gl.state == State.RUNNING


def test_idle_stop_settles_ledger(tmp_path):
    gl, t, led, ev = make(tmp_path, runner=FakeRunner(), idle_timeout=900)
    gl.start('r', 4)
    t.now += 899; assert gl.tick() == 'none'
    gl.work_started(); t.now += 5000; assert gl.tick() == 'none'  # busy never idles out
    gl.work_finished(); t.now += 901
    assert gl.tick() == 'idle_stop' and gl.state == State.STOPPED
    assert led.usage()['hours'] == pytest.approx((899 + 5000 + 901) / 3600)


def test_reservation_exhaustion_stops(tmp_path):
    gl, t, led, ev = make(tmp_path, runner=FakeRunner(), idle_timeout=10**9)
    gl.start('r', 1)
    gl.work_started(); t.now += 3601
    assert gl.tick() == 'budget_stop'


def test_start_refused_when_ledger_over_and_vm_not_started(tmp_path):
    runner = FakeRunner()
    gl, *_ = make(tmp_path, runner=runner)
    with pytest.raises(Exception):
        gl.start('r', 200)
    assert not any('start' in c for c in runner.cmds)


def test_unhealthy_timeout_stops_vm(tmp_path):
    runner = FakeRunner()
    gl, t, led, ev = make(tmp_path, runner=runner, health_check=lambda: False, startup_timeout=60)
    with pytest.raises(GpuLifecycleError):
        gl.start('r', 1)
    assert gl.state == State.STOPPED and runner.status == 'TERMINATED' and not led.open_reservations()


def test_stop_failure_does_not_claim_stopped(tmp_path):
    runner = FakeRunner(fail={'stop'})
    gl, t, led, ev = make(tmp_path, runner=runner)
    gl.start('r', 1)
    with pytest.raises(GpuLifecycleError):
        gl.stop('x')
    assert led.open_reservations() == ['r'] and gl.state == State.STOPPING


class FakeJobs:
    def __init__(self): self.calls = []
    def checkpoint(self, conn, job, data, state='running'):
        if job['id'] == 'expired': raise ValueError('Job cancelled, expired or claimed by another worker')
        self.calls.append((job['id'], data, state))


def test_preemption_settles_and_requeues_from_checkpoint(tmp_path):
    runner = FakeRunner()
    gl, t, led, ev = make(tmp_path, runner=runner)
    gl.start('r', 4)
    t.now += 1800
    runner.status = 'TERMINATED'  # spot reclaim, we did not ask for it
    jobs = FakeJobs()
    job_list = [{'id': 'j1', 'checkpoint': {'k': 1}}, {'id': 'expired', 'checkpoint': {}}]
    assert gl.tick(preempt_kwargs=dict(conn=None, jobs_api=jobs, jobs=job_list, checkpoint_ref='gs://b/ckpt/20')) == 'preempted'
    assert gl.state == State.PREEMPTED
    assert jobs.calls == [('j1', {'k': 1, 'gpu_checkpoint': 'gs://b/ckpt/20', 'gpu_preempted': True}, 'queued')]
    assert led.usage()['hours'] == pytest.approx(0.5)
    actions = [e[2] for e in ev.all()]
    assert 'preempted' in actions and 'requeued' in actions
    assert 'not_requeued' in str(ev.all()[-1][3]['outcome']['expired'])
    gl.start('r2', 1); assert gl.state == State.RUNNING  # restart needs a fresh reservation


def test_requeue_against_real_jobs_module_signature():
    import inspect
    from delivery import jobs
    assert 'state' in inspect.signature(jobs.checkpoint).parameters
    assert callable(requeue_from_checkpoint)
