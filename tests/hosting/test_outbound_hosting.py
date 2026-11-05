"""Opt-in native loopback tests; never use the real API, tunnel or credentials."""
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.live_integration


def test_failed_probe_child_cannot_report_success(tmp_path):
    # Python receives the nonexistent script "tunnel" in a fresh directory.
    # This actual local process fails immediately without any network access.
    binary = Path(sys.executable)
    report = tmp_path / "probe"
    result = subprocess.run([
        sys.executable, "-B", str(ROOT / "scripts/probe_outbound_tunnel.py"),
        "--cloudflared", str(binary), "--sha256", hashlib.sha256(binary.read_bytes()).hexdigest(),
        "--report-dir", str(report), "--seconds", "1",
    ], capture_output=True, text=True, timeout=15)
    receipt = json.loads((report / "receipt.json").read_text())
    assert result.returncode == 2
    assert receipt["child_exit_code"] != 0
    assert receipt["exited_early"] is True
    assert receipt["url_published"] is False
    assert receipt["canary_requests_seen"] == 0
    assert receipt["active"] is False and receipt["child_stopped"] is True
    assert receipt["requires_independent_exact_nonce_fetch"] is True


def test_native_acceptance_proxy_never_forwards_private_or_encoded_routes(tmp_path):
    binary = (ROOT / "deployment/.secrets/caddy/caddy.exe" if os.name == "nt"
              else Path(shutil.which("caddy") or "/nonexistent/caddy"))
    if not binary.is_file():
        pytest.skip("Native Caddy executable unavailable")
    hits = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            hits.append((self.command, self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"synthetic-upstream-only")

        do_POST = do_GET

    with ThreadingHTTPServer(("127.0.0.1", 0), Upstream) as upstream:
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        config_root = ROOT / "deployment/local"
        config = (config_root / "Caddyfile.tunnel-acceptance").read_text()
        config = config.replace(":8081", f":{port}").replace(
            "127.0.0.1:8000", f"127.0.0.1:{upstream.server_port}")
        (tmp_path / "Caddyfile").write_text(config)
        for name in ("routes.caddy", "logging.caddy"):
            text = (config_root / name).read_text().replace(
                "127.0.0.1:8000", f"127.0.0.1:{upstream.server_port}")
            (tmp_path / name).write_text(text)
        web = tmp_path / "dist"
        web.mkdir()
        (web / "index.html").write_text("<!doctype html><title>Synthetic acceptance fixture</title>")
        env = dict(os.environ, INVESTIFY_WEB_ROOT=web.as_posix())
        process = None

        def request(path, *, method="GET", host="investify.fyi"):
            connection = HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request(method, path, headers={"Host": host})
                response = connection.getresponse()
                return response.status, response.read(), response.getheader("Cache-Control")
            finally:
                connection.close()

        try:
            with (tmp_path / "caddy.log").open("wb") as log:
                process = subprocess.Popen([str(binary), "run", "--config", str(tmp_path / "Caddyfile"),
                                           "--adapter", "caddyfile"], cwd=tmp_path, env=env,
                                          stdout=log, stderr=log)
                for _ in range(50):
                    assert process.poll() is None, (tmp_path / "caddy.log").read_text()
                    try:
                        if request("/")[0] == 200:
                            break
                    except OSError:
                        time.sleep(.05)
                else:
                    pytest.fail("Synthetic acceptance proxy did not start")
                allowed = ("/api/health", "/api/auth/config", "/api/auth/login", "/api/auth/callback",
                           "/api/auth/me", "/api/auth/logout")
                for path in allowed:
                    status, body, cache = request(path)
                    assert (status, body, cache) == (200, b"synthetic-upstream-only", "no-store")
                hits.clear()
                blocked = ("/api", "/api/rooms", "/api/auth/local-login", "/api/auth/config/extra",
                           "/api%2Frooms", "/%61pi/rooms", "/api//rooms", "/api/./rooms",
                           "/api/auth/config/../rooms", "/api/auth/config%2F..%2Frooms",
                           "/api%252Frooms", "/api\\rooms")
                observations = {}
                for path in blocked:
                    for method in ("GET", "POST"):
                        status, body, _ = request(path, method=method)
                        observations[f"{method} {path}"] = status
                        if path == "/api%252Frooms":
                            # One decode leaves a literal "%2F", not an API
                            # separator. This stays static/405 and never reaches
                            # the generic imported API reverse_proxy.
                            assert status == (200 if method == "GET" else 405)
                        else:
                            assert status == 503
                        assert b"synthetic-upstream-only" not in body
                        assert hits == [], (path, method, hits)
                assert request("/api/auth/config", host="untrusted.invalid")[0] == 404
                assert hits == []
                (tmp_path / "smoke.json").write_text(json.dumps(observations, indent=2))
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            upstream.shutdown()
            thread.join(timeout=3)
