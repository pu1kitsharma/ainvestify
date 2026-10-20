"""Tiny stdlib fake of an OpenAI-compatible vLLM server (tests only, loopback socket)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = 'T0ken-' + 'x' * 30


def completion(model='banker-base', content='ok', calls=None, finish=None, prompt=5, completion_tokens=7):
    return {'id': 'cmpl-1', 'model': model,
            'choices': [{'index': 0, 'finish_reason': finish or ('tool_calls' if calls else 'stop'),
                         'message': {'role': 'assistant', 'content': content, 'tool_calls': calls or []}}],
            'usage': {'prompt_tokens': prompt, 'completion_tokens': completion_tokens, 'total_tokens': prompt + completion_tokens}}


class FakeServer:
    def __init__(self):
        self.requests, self.responses, self.dynamic = [], [], None   # dynamic(request)->(status, bytes) overrides the queue     # responses: (status, bytes) queue; last one repeats
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self):
                length = int(self.headers.get('Content-Length') or 0)
                body = self.rfile.read(length) if length else b''
                outer.requests.append({'method': self.command, 'path': self.path, 'headers': dict(self.headers), 'body': body})
                if outer.dynamic:
                    status, data = outer.dynamic(outer.requests[-1])
                else:
                    status, data = outer.responses[0] if len(outer.responses) == 1 else outer.responses.pop(0)
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            do_POST = do_GET = _reply

        self.httpd = HTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base_url(self):
        return 'http://localhost:%d' % self.port

    def reply(self, obj, status=200):
        self.responses = [(status, obj if isinstance(obj, bytes) else json.dumps(obj).encode())]
