"""Private child-process HTTP boundary. stdout contains a response, never a key."""
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    body = sys.stdin.read()
    request = urllib.request.Request('https://api.anthropic.com/v1/messages',
        data=body.encode(), headers={'Content-Type': 'application/json',
        'anthropic-version': '2023-06-01', 'x-api-key': os.environ['ANTHROPIC_API_KEY']})
    # No redirects carrying credentials, SDK retries, proxy discovery or
    # alternate endpoints. The parent enforces the whole-job deadline.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=120) as response:
            raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError('oversized')
            parsed = json.loads(raw)
        print(json.dumps(parsed))
    except urllib.error.HTTPError as exc:
        print(json.dumps({'error': 'http_error', 'status': exc.code}))
        return 1
    except Exception:
        print(json.dumps({'error': 'transport_error'}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
