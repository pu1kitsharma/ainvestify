"""Bounded synthetic-only outbound tunnel probe; never exposes the application."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloudflared', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 180 or not re.fullmatch('[0-9a-f]{64}', args.sha256):
        parser.error('Require a verified binary digest and duration at most 180 seconds')
    with args.cloudflared.open('rb') as binary:
        digest = hashlib.file_digest(binary, 'sha256').hexdigest()
    if digest != args.sha256:
        parser.error('cloudflared binary digest mismatch')
    args.report_dir.mkdir(parents=True, exist_ok=False)
    token = secrets.token_hex(16)
    route = '/.well-known/route-canary/' + token
    body = ('outbound-route-canary:' + token + '\n').encode('ascii')
    observations: list[bool] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            match = self.path == route
            content = body if match else b'Not found\n'
            if match:
                observations.append(True)
            self.send_response(200 if match else 404)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(content)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = False

        def get_request(self):
            peer, address = super().get_request()
            peer.settimeout(2)
            return peer, address

        def handle_error(self, *_args):
            pass

    report = {'synthetic_only': True, 'application_exposed': False,
              'router_or_firewall_changed': False, 'duration_seconds': args.seconds}
    receipt = args.report_dir / 'receipt.json'
    process = None
    published = False
    exited_early = False
    with Server(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={'poll_interval': .1}, daemon=True)
        thread.start()
        try:
            logfile = args.report_dir / 'cloudflared.log'
            process = subprocess.Popen([
                str(args.cloudflared.resolve()), 'tunnel', '--no-autoupdate',
                '--protocol', 'http2', '--url', f'http://127.0.0.1:{server.server_port}',
                '--metrics', '127.0.0.1:0', '--logfile', str(logfile.resolve()),
            ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, cwd=args.report_dir.resolve())
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline and process.poll() is None:
                if not published and logfile.exists():
                    match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',
                                      logfile.read_text(encoding='utf-8', errors='replace'))
                    if match:
                        report.update(url=match.group(0) + route,
                                      expected_body=body.decode('ascii'), active=True)
                        receipt.write_text(json.dumps(report, indent=2), encoding='utf-8')
                        print(json.dumps(report), flush=True)
                        published = True
                time.sleep(.2)
            exited_early = process.poll() is not None
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            server.shutdown()
            thread.join(timeout=2)
            report.update(active=False, canary_requests_seen=len(observations),
                          child_stopped=process is None or process.poll() is not None,
                          url_published=published, exited_early=exited_early,
                          child_exit_code=None if process is None else process.poll(),
                          requires_independent_exact_nonce_fetch=True)
            receipt.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report), flush=True)
    if not published or exited_early or not observations:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
