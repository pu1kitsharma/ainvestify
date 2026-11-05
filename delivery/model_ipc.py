"""Bounded, job-lifetime Unix relay to literal loopback Ollama; never a TCP server.

Private Linux workers retain their separate network namespace. Only this socket
inode is mounted into a worker. No prompts, response bodies or headers are logged.
This transport is opt-in until native host qualification, not release acceptance.
"""
from __future__ import annotations

from contextlib import contextmanager
import http.client
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import platform
import re
import select
import socket
import socketserver
import stat
import tempfile
import threading
import time

CONTRACT = 'unix-ollama-v1'
SANDBOX_SOCKET = '/run/investify/ollama.sock'
SOCKET_ENV = 'PRIVATE_OLLAMA_SOCKET'
MAX_BODY = 8 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
READ_PATHS = frozenset(('/api/tags', '/api/ps'))
POST_PATHS = frozenset(('/api/chat', '/api/generate', '/api/show', '/api/embed', '/api/embeddings'))


def validate_socket(path):
    path = Path(path).absolute()
    if platform.system() != 'Linux' or path.resolve() != path or path.is_symlink():
        raise ValueError('A canonical Linux model socket is required')
    info = path.stat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Model socket ownership or permissions differ from the private contract')
    return path


def admit_request(method, path, body):
    if (method == 'GET' and path in READ_PATHS and body == b''):
        return
    if method != 'POST' or path not in POST_PATHS or not 0 < len(body) <= MAX_BODY:
        raise ValueError('Unsupported local model operation')
    try:
        data = json.loads(body)
        model = data.get('model')
    except (ValueError, AttributeError, UnicodeError) as exc:
        raise ValueError('Invalid model request') from exc
    if (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,190}', model)
            or 'cloud' in model.casefold()):
        raise ValueError('A local installed model identifier is required')


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *args):
        pass

    def setup(self):
        self.request.settimeout(max(.01, self.server.deadline - time.monotonic()))
        self.server.track(self.request)
        super().setup()

    def finish(self):
        try:
            super().finish()
        finally:
            self.server.untrack(self.request)

    def do_GET(self):
        self._relay()

    def do_POST(self):
        self._relay()

    def _fail(self, status):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()

    def _relay(self):
        upstream = None
        upstream_socket = None
        disconnect_monitor = None
        finished = threading.Event()
        started = False
        try:
            # No chunked upload, duplicate framing, proxy or credential headers.
            lengths = self.headers.get_all('Content-Length', [])
            if (self.headers.get('Transfer-Encoding') or len(lengths) > 1
                    or self.headers.get('Host') != '127.0.0.1:11434'
                    or any(self.headers.get(key) for key in ('Authorization', 'Cookie', 'Proxy-Authorization', 'Expect'))
                    or sum(len(k) + len(v) for k, v in self.headers.items()) > 16384):
                return self._fail(400)
            length = int(lengths[0]) if lengths else 0
            if not 0 <= length <= MAX_BODY:
                return self._fail(413)
            body = self.rfile.read(length)
            if len(body) != length:
                return self._fail(400)
            admit_request(self.command, self.path, body)
            remaining = self.server.claim()
            upstream = self.server.connection_factory('127.0.0.1', 11434, timeout=remaining)
            upstream.connect()
            upstream_socket = upstream.sock
            self.server.track(upstream_socket)
            if upstream_socket is not None:
                # A cancelled SDK stream must cancel Ollama even before its
                # first response byte. Merely catching BrokenPipe on write
                # would leave a thinking/loading model running until deadline.
                def watch_disconnect():
                    while not finished.wait(.05):
                        try:
                            readable, _, _ = select.select([self.connection], [], [], 0)
                            if readable and self.connection.recv(1, socket.MSG_PEEK) == b'':
                                upstream_socket.shutdown(socket.SHUT_RDWR)
                                return
                        except OSError:
                            return
                disconnect_monitor = threading.Thread(target=watch_disconnect, daemon=True)
                disconnect_monitor.start()
            upstream.request(self.command, self.path, body=body or None,
                             headers={'Content-Type': 'application/json', 'Connection': 'close'})
            response = upstream.getresponse()
            if 300 <= response.status < 400:
                return self._fail(502)  # Never follow or forward redirects.
            if response.getheader('Content-Encoding') not in (None, 'identity'):
                return self._fail(502)
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type') or 'application/json')
            self.send_header('Connection', 'close')
            self.end_headers()
            started = True
            received = 0
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_RESPONSE or time.monotonic() >= self.server.deadline:
                    raise TimeoutError('Model IPC response exceeded its limit')
                self.wfile.write(chunk)
                self.wfile.flush()
        except (ValueError, RuntimeError):
            if not started:
                self._fail(403)
        except (OSError, http.client.HTTPException):
            if not started:
                try:
                    self._fail(502)
                except OSError:
                    pass
        finally:
            finished.set()
            if upstream is not None:
                self.server.untrack(upstream_socket)
                upstream.close()
            if disconnect_monitor is not None:
                disconnect_monitor.join(timeout=.2)
            self.close_connection = True


class _Server(getattr(socketserver, 'UnixStreamServer', socketserver.TCPServer)):
    # Serial handling bounds concurrency; the deadline also closes a stalled peer.
    def handle_error(self, request, client_address):
        pass

    def track(self, sock):
        if sock is not None:
            with self.lock:
                self.sockets.add(sock)

    def untrack(self, sock):
        with self.lock:
            self.sockets.discard(sock)

    def close_connections(self):
        with self.lock:
            peers = tuple(self.sockets)
        for peer in peers:
            try:
                peer.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            peer.close()

    def claim(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self.calls >= 6:
            raise RuntimeError('Model IPC budget exhausted')
        self.calls += 1
        return remaining


@contextmanager
def model_relay(*, timeout, _connection_factory=http.client.HTTPConnection):
    from agents.preparation.preparation_budget import DOCUMENT_STEP_MAX_SECONDS
    if platform.system() != 'Linux' or not 0 < timeout <= DOCUMENT_STEP_MAX_SECONDS:
        raise ValueError('Linux model IPC requires a bounded job of at most 900 seconds')
    with tempfile.TemporaryDirectory(prefix='iv-ipc-', dir='/tmp') as directory:
        os.chmod(directory, 0o700)
        path = Path(directory) / 'ollama.sock'
        server = _Server(str(path), _Handler)
        os.chmod(path, 0o600)
        server.lock, server.sockets = threading.Lock(), set()
        server.deadline, server.calls = time.monotonic() + timeout, 0
        server.connection_factory = _connection_factory
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        timer = threading.Timer(timeout, server.close_connections)
        timer.daemon = True
        thread.start()
        timer.start()
        try:
            yield validate_socket(path)
        finally:
            server.close_connections()
            server.shutdown()
            server.server_close()
            timer.cancel()
            thread.join(timeout=2)
