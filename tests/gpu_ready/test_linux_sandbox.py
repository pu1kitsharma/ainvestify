import subprocess
from pathlib import Path

import pytest

from agents.tools import recalc
from delivery import isolation, libreoffice


class Proc:
    def __init__(self, code=0):
        self.returncode, self.pid = code, 4242

    def communicate(self, timeout=None):
        return b'out', b'err'


def linux(monkeypatch, bwrap='/usr/bin/bwrap'):
    monkeypatch.setattr(isolation.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(isolation, 'bwrap_binary', lambda: bwrap)


def test_backend_selection_by_platform(monkeypatch):
    monkeypatch.setattr(isolation.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(isolation, 'bwrap_binary', lambda: None)
    assert isolation.isolation_backend() is None
    assert isolation.isolation_available() == (False, 'private_process_isolation_unavailable')
    monkeypatch.setattr(isolation, 'bwrap_binary', lambda: '/usr/bin/bwrap')
    assert isolation.isolation_backend() == 'bwrap'
    monkeypatch.setattr(isolation.platform, 'system', lambda: 'Windows')
    assert isolation.isolation_backend() is None


def test_no_backend_never_starts_a_process(monkeypatch, tmp_path):
    monkeypatch.setattr(isolation.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(isolation, 'bwrap_binary', lambda: None)
    monkeypatch.setattr(isolation.subprocess, 'Popen', lambda *a, **k: pytest.fail('unsandboxed process started'))
    with pytest.raises(RuntimeError, match='private_process_isolation_unavailable'):
        isolation.run_private(['/bin/true'], tmp_path)


def test_bwrap_command_shape(tmp_path):
    job = tmp_path / 'job'
    job.mkdir()
    ro = tmp_path / 'office'
    ro.mkdir()
    argv, env = isolation.build_bwrap_command(['/usr/bin/soffice', '--headless'], job, bwrap='/usr/bin/bwrap', project=Path('/proj'),
                                              extra_read=[ro], local_ipc=True, prefixes=[str(tmp_path)])
    assert argv[0] == '/usr/bin/bwrap'
    for flag in ('--unshare-all', '--die-with-parent', '--new-session', '--clearenv'):
        assert flag in argv
    assert '--share-net' not in argv                       # network namespace stays unshared
    assert argv[argv.index('--tmpfs') + 1] == '/tmp' and '--proc' in argv and '--dev' in argv
    # job is the only writable bind; everything else is read-only
    binds = [argv[i + 1] for i, a in enumerate(argv) if a == '--bind']
    assert binds == [str(job)]
    ro_binds = [argv[i + 1] for i, a in enumerate(argv) if a == '--ro-bind']
    assert str(ro) in ro_binds and str(job) not in ro_binds and '/' not in ro_binds
    assert argv.index('--tmpfs') < argv.index('--bind')    # a job under /tmp survives the tmpfs
    assert argv[-3:] == ['--', '/usr/bin/soffice', '--headless'] or argv[-2:] == ['/usr/bin/soffice', '--headless']
    assert env['HOME'] == str(job) and 'PATH' in env and not any('TOKEN' in k or 'KEY' in k for k in env)


def test_local_model_refused_on_linux(tmp_path):
    with pytest.raises(RuntimeError, match='local_model_unsupported'):
        isolation.build_bwrap_command(['x'], tmp_path, bwrap='b', project=Path('/p'), local_model=True)


def test_literal_capabilities_must_be_canonical(tmp_path):
    real = tmp_path / 'f'
    real.write_text('x')
    link = tmp_path / 'l'
    link.symlink_to(real)
    with pytest.raises(ValueError):
        isolation.build_bwrap_command(['x'], tmp_path, bwrap='b', project=Path('/p'), extra_read_literals=[link])
    argv, _ = isolation.build_bwrap_command(['x'], tmp_path, bwrap='b', project=Path('/p'), extra_read_literals=[real], prefixes=[])
    assert str(real) in argv


def test_run_private_linux_uses_bwrap_and_reports_failure(monkeypatch, tmp_path):
    linux(monkeypatch)
    seen = {}

    def popen(argv, **kw):
        seen['argv'], seen['kw'] = argv, kw
        return Proc(0)
    monkeypatch.setattr(isolation.subprocess, 'Popen', popen)
    assert isolation.run_private(['/usr/bin/true'], tmp_path) == b'out'
    assert seen['argv'][0] == '/usr/bin/bwrap' and '/usr/bin/sandbox-exec' not in seen['argv'] and seen['kw']['start_new_session'] is True
    monkeypatch.setattr(isolation.subprocess, 'Popen', lambda *a, **k: Proc(3))
    with pytest.raises(RuntimeError, match='private_worker_failed'):
        isolation.run_private(['/usr/bin/false'], tmp_path)
    assert (tmp_path / 'worker-error.txt').read_text().startswith('exit=3')


def test_run_private_linux_timeout_kills_group(monkeypatch, tmp_path):
    linux(monkeypatch)
    killed = []

    class Slow(Proc):
        calls = 0

        def communicate(self, timeout=None):
            Slow.calls += 1
            if Slow.calls == 1:
                raise subprocess.TimeoutExpired('bwrap', 1)
            return b'', b''
    monkeypatch.setattr(isolation.subprocess, 'Popen', lambda *a, **k: Slow())
    monkeypatch.setattr(isolation.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(TimeoutError, match='private_worker_timeout'):
        isolation.run_private(['sleep', '9'], tmp_path, timeout=1)
    assert killed and killed[0][0] == 4242


def test_macos_path_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(isolation.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(isolation.Path, 'exists', lambda self: True if str(self) == '/usr/bin/sandbox-exec' else Path.stat(self) and True)
    monkeypatch.setattr(isolation.subprocess, 'Popen', lambda argv, **k: (_ for _ in ()).throw(AssertionError(argv)) if argv[0] != '/usr/bin/sandbox-exec' else Proc(0))
    assert isolation.run_private(['/usr/bin/true'], tmp_path) == b'out'
    assert (tmp_path / 'worker.sb').is_file()


# ---- LibreOffice discovery -------------------------------------------------------------------
def test_find_binary_env_then_path(tmp_path):
    exe = tmp_path / 'soffice'
    exe.write_text('#!/bin/sh')
    assert libreoffice.find_binary(environ={'LIBREOFFICE_BINARY': str(exe)}, system='Linux') == exe
    assert libreoffice.find_binary(environ={'LIBREOFFICE_BINARY': str(tmp_path / 'nope')}, system='Linux') is None   # explicit but wrong: no silent fallback
    assert libreoffice.find_binary(environ={}, system='Linux', which=lambda n: str(exe) if n == 'soffice' else None) == exe
    assert libreoffice.find_binary(environ={}, system='Windows') is None


def test_find_binary_linux_missing(monkeypatch):
    monkeypatch.setattr(libreoffice, 'LINUX_CANDIDATES', ())
    assert libreoffice.find_binary(environ={}, system='Linux', which=lambda n: None) is None


def test_read_roots_per_platform(tmp_path):
    prog = tmp_path / 'lo' / 'program'
    prog.mkdir(parents=True)
    exe = prog / 'soffice'
    exe.write_text('x')
    link = tmp_path / 'bin-soffice'
    link.symlink_to(exe)
    assert libreoffice.office_read_roots(link, system='Linux') == ((tmp_path / 'lo').resolve(),)
    assert libreoffice.sandbox_binary(link, system='Linux') == exe.resolve()
    app = Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')
    assert libreoffice.office_read_roots(app, system='Darwin') == (Path('/Applications/LibreOffice.app'),)


def test_recalc_availability_follows_isolation_and_binary(monkeypatch):
    monkeypatch.setattr(isolation, 'isolation_available', lambda: (False, 'private_process_isolation_unavailable'))
    assert recalc.availability() == (False, 'private_process_isolation_unavailable')
    monkeypatch.setattr(isolation, 'isolation_available', lambda: (True, 'available'))
    monkeypatch.setattr(libreoffice, 'find_binary', lambda *a, **k: None)
    assert recalc.availability() == (False, 'libreoffice_unavailable')
    monkeypatch.setattr(libreoffice, 'find_binary', lambda *a, **k: Path('/usr/bin/soffice'))
    assert recalc.availability() == (True, 'available')


def test_recalc_is_unrun_not_unsandboxed_on_linux_without_bwrap(monkeypatch):
    from tests.tools.synthetic_books import build
    monkeypatch.setattr(isolation.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(isolation, 'bwrap_binary', lambda: None)
    monkeypatch.setattr(isolation.subprocess, 'Popen', lambda *a, **k: pytest.fail('unsandboxed'))
    report = recalc.compare_libreoffice_to_engine(build({'S': {'A1': 1, 'A2': '=A1+1'}}))
    assert report['status'] == 'UNRUN' and report['passed'] is False and report['mandatory_unrun'] is True


def test_recalc_runs_through_run_private_with_linux_roots(monkeypatch, tmp_path):
    from tests.tools.synthetic_books import build
    prog = tmp_path / 'lo' / 'program'
    prog.mkdir(parents=True)
    exe = prog / 'soffice'
    exe.write_text('x')
    monkeypatch.setattr(isolation.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(recalc.platform, 'system', lambda: 'Linux')
    monkeypatch.setenv('LIBREOFFICE_BINARY', str(exe))
    monkeypatch.setattr(isolation, 'isolation_available', lambda: (True, 'available'))
    captured = {}

    def fake_run(args, job, **kw):
        captured.update(args=args, kw=kw)
        raise RuntimeError('private_worker_failed')
    monkeypatch.setattr(isolation, 'run_private', fake_run)
    report = recalc.recalculate_with_libreoffice(build({'S': {'A1': 1, 'A2': '=A1+1'}}))
    assert report['status'] == 'failed'
    assert captured['args'][0] == exe.resolve() and captured['kw']['extra_read'] == ((tmp_path / 'lo').resolve(),)
    assert captured['kw']['local_ipc'] is True
