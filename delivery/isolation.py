"""Fail-closed macOS subprocess boundary for private parsing/rendering.

Only immutable code/runtime locations and one job directory are readable. No
network rule is granted. Other OS adapters must be qualified before use.
"""
from __future__ import annotations
import json
import os
import platform
from pathlib import Path
import signal
import subprocess
import sys


def run_private(command, job_directory, *, timeout=120, extra_read=(), local_ipc=False, local_model=False):
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").exists():
        raise RuntimeError("private_process_isolation_unavailable")
    job = Path(job_directory).resolve()
    if not job.is_dir():
        raise ValueError("A private job directory is required")
    project = Path(__file__).resolve().parents[1]
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
    proc = subprocess.Popen(["/usr/bin/sandbox-exec","-f",str(profile),*map(str,command)],
        cwd=job,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGKILL)
        proc.communicate()
        raise TimeoutError("private_worker_timeout")
    if proc.returncode:
        # Diagnostics are private job artifacts, never public logs or API errors.
        (job/"worker-error.txt").write_bytes(f"exit={proc.returncode}\n".encode()+stderr[:32768]+stdout[:32768])
        raise RuntimeError("private_worker_failed")
    return stdout
