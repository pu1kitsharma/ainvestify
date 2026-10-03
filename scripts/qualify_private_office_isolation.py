"""Synthetic canary for the Office worker's existing private Seatbelt boundary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from delivery.isolation import run_private


CANARY = '''import json, pathlib, socket, sys
outside, sibling, unix_path = sys.argv[1:]
result = {}
def attempt(name, action):
    try:
        action()
        result[name] = 'allowed'
    except Exception as exc:
        result[name] = type(exc).__name__
attempt('outside_write', lambda: pathlib.Path(outside).write_text('synthetic'))
attempt('sibling_read', lambda: pathlib.Path(sibling).read_text())
attempt('tcp_outbound', lambda: socket.create_connection(('127.0.0.1', 9), timeout=.5))
attempt('unix_outside', lambda: (lambda s: (s.connect(unix_path), s.close()))(socket.socket(socket.AF_UNIX)))
attempt('tcp_bind', lambda: (lambda s: (s.bind(('127.0.0.1', 0)), s.close()))(socket.socket()))
print(json.dumps(result))
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output report already exists")
    with tempfile.TemporaryDirectory(prefix="office-canary-", dir="/private/tmp") as directory:
        root = Path(directory)
        job = root / "job"
        job.mkdir()
        sibling = root / "sibling.txt"
        sibling.write_text("synthetic canary only")
        outside = root / "outside.txt"
        unix_path = root / "outside.sock"
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(unix_path))
        listener.listen(1)
        script = job / "canary.py"
        script.write_text(CANARY)
        try:
            raw = run_private([sys.executable, script, outside, sibling,
                               unix_path], job, timeout=10, local_ipc=True)
        finally:
            listener.close()
        checks = json.loads(raw)
        checks["outside_write_absent"] = not outside.exists()
    passed = all(value == "PermissionError" for name, value in checks.items()
                 if name != "outside_write_absent") and checks["outside_write_absent"]
    report = {"scope": "synthetic_office_policy_canary", "passed": passed,
              "private_office_qualified": False, "checks": checks}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
