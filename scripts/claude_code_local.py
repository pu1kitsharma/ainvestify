"""Run a tools-disabled Claude Code reviewer against existing loopback Ollama.

No project files, private inputs, user Claude settings or hosted fallback are
provided. This explicit command starts inference; preflight does not.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.inference.endpoint_policy import validate_endpoint

PROMPT = ('Act as a software review agent. For a Python workbook-writing tool and '
          'a resumable six-call agent loop, list five concrete boundary tests for '
          'path containment, duplicate tool calls, formula errors, time budgets '
          'and crash recovery. Use no company examples. Do not call tools.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Local inference redirects are forbidden')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly start one local review')
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--endpoint', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    endpoint = validate_endpoint(args.endpoint)
    if endpoint.endswith('/v1'):
        raise ValueError('Use the Ollama origin, without /v1')
    executable = shutil.which('claude')
    if not executable:
        raise RuntimeError('Claude Code is not installed; no installation attempted')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(endpoint + '/api/tags', timeout=3) as response:
        body = response.read(1024*1024 + 1)
        if len(body) > 1024*1024:
            raise ValueError('Local model inventory exceeds limit')
        models = [m['name'] for m in json.loads(body)['models']]
    if args.model not in models:
        raise ValueError('Requested model is not installed; no download attempted')
    if not args.run:
        print(json.dumps({'status': 'ready_not_run', 'endpoint': endpoint, 'model': args.model}))
        return
    with tempfile.TemporaryDirectory(prefix='local-claude-review-') as directory:
        # Do not inherit cloud credentials, proxies, provider switches or hooks.
        env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'LANG') if k in os.environ}
        env.update(HOME=directory, CLAUDE_CONFIG_DIR=directory,
                   ANTHROPIC_BASE_URL=endpoint, ANTHROPIC_API_KEY='local-only',
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
                   DISABLE_TELEMETRY='1', DISABLE_ERROR_REPORTING='1',
                   CLAUDE_CODE_DISABLE_AUTO_MEMORY='1')
        command = [executable, '--bare', '--safe-mode', '--restricted',
                   '--setting-sources', '', '--strict-mcp-config',
                   '--mcp-config', '{"mcpServers":{}}', '--tools', '',
                   '--no-session-persistence', '--model', args.model,
                   '--effort', 'low', '-p', PROMPT]
        sandbox = '/usr/bin/sandbox-exec'
        if not Path(sandbox).is_file():
            raise RuntimeError('OS network confinement unavailable; local Claude run blocked')
        parts = urlsplit(endpoint)
        if parts.hostname != '127.0.0.1' or parts.scheme != 'http' or not parts.port:
            raise ValueError('Claude network confinement requires explicit IPv4 loopback port')
        profile = ('(version 1)(allow default)(deny network*)'
                   f'(allow network-outbound (remote ip "127.0.0.1:{parts.port}"))')
        command = [sandbox, '-p', profile, *command]
        def limits():
            import resource
            resource.setrlimit(resource.RLIMIT_FSIZE, (2*1024*1024, 2*1024*1024))
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(command, cwd=directory, env=env,
                stdout=stdout, stderr=stderr, start_new_session=True, preexec_fn=limits)
            try:
                returncode = process.wait(timeout=120)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read(2*1024*1024).decode('utf-8', errors='replace')
            error = stderr.read(2*1024*1024).decode('utf-8', errors='replace')
        print(json.dumps({'status': 'completed' if returncode == 0 else 'failed',
                          'endpoint': endpoint, 'model': args.model,
                          'returncode': returncode, 'stdout': output, 'stderr': error}))
        if returncode:
            raise SystemExit(returncode)


if __name__ == '__main__':
    main()
