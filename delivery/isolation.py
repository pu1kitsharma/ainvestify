"""Fail-closed subprocess boundary for private parsing/rendering.

macOS: Seatbelt (`sandbox-exec`). Linux: bubblewrap (`bwrap`): all namespaces unshared
(including network), read-only binds of immutable code/runtime locations, tmpfs /tmp,
one writable job directory, die-with-parent. Only immutable code/runtime locations and
one job directory are readable. No network rule is granted. When neither backend exists
the call raises RuntimeError('private_process_isolation_unavailable'); a process is never
started unsandboxed. The Linux backend is unit-tested with fakes only (qualify with
scripts/gpu_preflight.py + a real bwrap run on the target host before relying on it).
"""
from __future__ import annotations
import json
import os
import platform
from pathlib import Path
import shutil
import signal
import subprocess
import sys



# The Unicode PDF renderer opens this application-supplied font directly.
# Keep it a literal file capability, never an application/font-directory grant.
READONLY_RENDER_FONTS = (
    Path('/Applications/LibreOffice.app/Contents/Resources/fonts/truetype/DejaVuSans.ttf'),
    Path('/Applications/LibreOffice.app/Contents/Resources/fonts/truetype/DejaVuSans-Bold.ttf'),
)


def _render_font_literals():
    return [str(font) for font in READONLY_RENDER_FONTS
            if font.is_file() and not font.is_symlink() and font.resolve() == font]

def bwrap_binary():
    """Absolute path of bubblewrap (BWRAP_BINARY override, else PATH), or None."""
    explicit = os.environ.get("BWRAP_BINARY")
    found = explicit if explicit else shutil.which("bwrap")
    return found if found and Path(found).is_file() else None


def isolation_backend():
    """'seatbelt' | 'bwrap' | None, by platform. Never guesses a weaker fallback."""
    system = platform.system()
    if system == "Darwin" and Path("/usr/bin/sandbox-exec").exists():
        return "seatbelt"
    if system == "Linux" and bwrap_binary():
        return "bwrap"
    return None


def isolation_available():
    """(available, reason) without starting anything."""
    return (True, "available") if isolation_backend() else (False, "private_process_isolation_unavailable")


def private_temp_root():
    """Short private temp parent: macOS per-user TMPDIR is too long for LibreOffice's socket name."""
    import tempfile
    return "/private/tmp" if platform.system() == "Darwin" else tempfile.gettempdir()


_LINUX_SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/lib32")
_LINUX_ETC_FILES = ("/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/fonts",
                    "/etc/alternatives", "/etc/localtime")


def build_bwrap_command(command, job, *, bwrap, project, extra_read=(), extra_read_literals=(),
                        local_ipc=False, local_model=False, prefixes=None):
    """Pure construction of the bubblewrap argv (no process started). Returns (argv, env)."""
    if local_model:
        # Seatbelt can allow a single localhost TCP port; bwrap cannot without sharing the host
        # network namespace. Refuse rather than widen the boundary.
        raise RuntimeError("private_process_isolation_local_model_unsupported_on_linux")
    prefixes = prefixes if prefixes is not None else [str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve())]
    argv = [str(bwrap), "--unshare-all", "--die-with-parent", "--new-session", "--clearenv"]
    for entry in _LINUX_SYSTEM_DIRS:
        path = Path(entry)
        if path.is_symlink():
            argv += ["--symlink", os.readlink(entry), entry]
        elif path.exists():
            argv += ["--ro-bind", entry, entry]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for entry in _LINUX_ETC_FILES:
        if Path(entry).exists():
            argv += ["--ro-bind", entry, entry]
    reads = [*prefixes, str(Path(project) / "delivery"), str(Path(project) / "security"),
             str(Path(project) / "scripts"), *[str(Path(p).resolve()) for p in extra_read]]
    for item in extra_read_literals:
        path = Path(item).absolute()
        if path.is_symlink() or path.resolve() != path or not path.exists():
            raise ValueError("Exact private read capability must be canonical and present")
        reads.append(str(path))
    seen = set()
    for path in reads:
        if path in seen or path == "/" or not Path(path).exists():
            continue
        seen.add(path)
        argv += ["--ro-bind", path, path]
    # The job directory is the single writable location (after tmpfs so a job under /tmp survives).
    argv += ["--bind", str(job), str(job), "--chdir", str(job)]
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(job), "TMPDIR": str(job),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(project), "LANG": "C.UTF-8"}
    for key, value in env.items():
        argv += ["--setenv", key, value]
    return argv + ["--", *map(str, command)], env


def _execute(argv, env, job, timeout):
    proc = subprocess.Popen(argv, cwd=job, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise TimeoutError("private_worker_timeout")
    if proc.returncode:
        # Diagnostics are private job artifacts, never public logs or API errors.
        (job/"worker-error.txt").write_bytes(f"exit={proc.returncode}\n".encode()+stderr[:32768]+stdout[:32768])
        raise RuntimeError("private_worker_failed")
    return stdout


def run_private(command, job_directory, *, timeout=120, extra_read=(), extra_read_literals=(),
                local_ipc=False, local_model=False):
    backend = isolation_backend()
    if backend is None:
        raise RuntimeError("private_process_isolation_unavailable")
    job = Path(job_directory).resolve()
    if not job.is_dir():
        raise ValueError("A private job directory is required")
    project = Path(__file__).resolve().parents[1]
    if backend == "bwrap":
        argv, env = build_bwrap_command(command, job, bwrap=bwrap_binary(), project=project, extra_read=extra_read,
                                        extra_read_literals=extra_read_literals, local_ipc=local_ipc, local_model=local_model)
        return _execute(argv, env, job, timeout)
    roots = ["/System/Library", "/System/Volumes/Preboot", "/usr", "/bin", "/sbin",
        "/Library/Developer/CommandLineTools", "/Library/Fonts", "/private/etc", "/private/var/db", "/dev",
        str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve()),
        str(Path.home()/"Library/Python"), str(project/"delivery"), str(project/"security"),
        str(project/"scripts"), str(job), *[str(Path(p).resolve()) for p in extra_read]]
    # No broad project/home access: runtime DB, uploads and other tenant artifacts
    # are deliberately excluded. No HTTP, DNS, hosted credential or model key.
    # Explicit deny rules override allow rules in Seatbelt. Express the allowlist
    # inside the denial's predicate instead of appending overlapping allows.
    readable = f'(literal "/") (literal {json.dumps(str(project))}) ' + " ".join(f"(subpath {json.dumps(p)})" for p in roots)
    readable += ' ' + ' '.join(f'(literal {json.dumps(font)})' for font in _render_font_literals())
    # Provenance replay can require exact immutable files from an earlier private
    # job. Directory literals permit listing, without granting their descendants.
    literal_paths = []
    for item in extra_read_literals:
        path = Path(item).absolute()
        if path.is_symlink() or path.resolve() != path or not path.exists():
            raise ValueError('Exact private read capability must be canonical and present')
        literal_paths.append(str(path))
    readable += ' ' + ' '.join(f'(literal {json.dumps(path)})' for path in literal_paths)
    writable = f'(subpath {json.dumps(str(job))}) (literal "/dev/null")'
    rules = ["(version 1)", "(allow default)", "(deny network*)",
        f"(deny file-read-data (require-not (require-any {readable})))",
        f"(deny file-write* (require-not (require-any {writable})))"]
    if local_ipc:
        rules.remove('(deny network*)')
        rules += [f'(deny network-outbound (require-not (remote unix-socket (subpath {json.dumps(str(job))}))))',
            f'(deny network-inbound (require-not (local unix-socket (subpath {json.dumps(str(job))}))))',
            f'(deny network-bind (require-not (local unix-socket (subpath {json.dumps(str(job))}))))']
    if local_model:
        if local_ipc:raise ValueError('Inference and office workers must remain separate')
        rules.remove('(deny network*)')
        rules += ['(deny network-outbound (require-not (remote tcp "localhost:11434")))',
            '(deny network-inbound)', '(deny network-bind)']
    profile = job / "worker.sb"
    profile.write_text("\n".join(rules))
    env = {"PATH":"/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR":str(job),
        "PYTHONDONTWRITEBYTECODE":"1", "PYTHONPATH":str(project), "LANG":"en_US.UTF-8"}
    argv = ["/usr/bin/sandbox-exec", "-f", str(profile), *map(str, command)]
    return _execute(argv, env, job, timeout)
