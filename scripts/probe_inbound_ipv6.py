"""At most two minutes of synthetic IPv6 HTTP; never serves application/files."""
import argparse
import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--arm-file', type=Path)
    parser.add_argument('--external-report', type=Path)
    args = parser.parse_args()
    address = ipaddress.ip_address(args.address)
    if address.version != 6 or not address.is_global or not 1 <= args.seconds <= 120 or not re.fullmatch('[0-9a-f]{32}', args.token):
        parser.error('Require one global IPv6, a 32-hex canary token and a maximum 120-second duration')
    path = '/.well-known/investify-route/' + args.token
    response = ('investify-inbound-canary:' + args.token + '\n').encode()
    observed = []
    # The network probe starts only AFTER Windows grants its temporary rule;
    # time spent waiting for the OS elevation prompt consumes no probe window.
    if args.arm_file:
        arm_deadline = time.monotonic() + 300
        armed = False
        while time.monotonic() < arm_deadline:
            try:
                receipt = json.loads(args.arm_file.read_text(encoding='utf-8-sig'))
                expires = datetime.fromisoformat(receipt['expires_utc'].replace('Z', '+00:00'))
                armed = (receipt.get('enabled') is True and receipt.get('address') == str(address)
                         and receipt.get('port') == 80
                         and (expires - datetime.now(timezone.utc)).total_seconds() > args.seconds)
            except (OSError, ValueError, KeyError):
                armed = False
            if armed:
                break
            time.sleep(.25)
        if not armed:
            raise SystemExit('No valid temporary firewall grant; no listener started')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            content = response if self.path == path else b'Not found\n'
            if self.path == path:
                observed.append(True)
            self.send_response(200 if self.path == path else 404)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(content)

    class Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6
        daemon_threads = True
        allow_reuse_address = False

        def server_bind(self):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            super().server_bind()

        def get_request(self):
            peer, address = super().get_request()
            peer.settimeout(2)
            return peer, address

        def handle_error(self, *unused):
            pass

    with Server((str(address), 80), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        thread.start()
        print(json.dumps({'synthetic_canary_ready': True, 'address': str(address), 'port': 80}), flush=True)
        try:
            deadline = time.monotonic() + args.seconds
            if args.external_report:
                report = {'synthetic_only': True, 'address': str(address), 'port': 80,
                          'inbound_verified': False}
                def fetch(url):
                    request = urllib.request.Request(url, headers={'Accept': 'application/json'})
                    with urllib.request.urlopen(request, timeout=5) as result:
                        return json.loads(result.read(262144))
                try:
                    target = f'http://[{address}]{path}'
                    request = fetch('https://check-host.net/check-http?' + urllib.parse.urlencode(
                        {'host': target, 'max_nodes': 3}))
                    result = {}
                    for _ in range(4):
                        time.sleep(2)
                        result = fetch('https://check-host.net/check-result/' + request['request_id'])
                        if result and all(value is not None for value in result.values()):
                            break
                    report.update(request=request, results=result, canary_requests_seen=len(observed))
                    report['inbound_verified'] = bool(observed)
                except Exception as error:
                    report['unqualified_reason'] = type(error).__name__
                with args.external_report.open('x', encoding='utf-8') as output:
                    json.dump(report, output, indent=2)
                print(json.dumps(report), flush=True)
            time.sleep(max(0, deadline - time.monotonic()))
        finally:
            server.shutdown()
            thread.join(timeout=2)


if __name__ == '__main__':
    main()
