"""Literal-address endpoint admission; never resolves names or follows redirects."""
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit


def validate_endpoint(url, *, loopback_only=True):
    if not isinstance(url, str) or any(c.isspace() for c in url):
        raise ValueError('A literal private HTTP endpoint is required')
    parts = urlsplit(url)
    if (parts.scheme not in ('http', 'https') or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ('', '/', '/v1', '/v1/')):
        raise ValueError('Unsupported inference endpoint')
    try:
        address = ip_address(parts.hostname or '')
        port = parts.port
    except ValueError as exc:
        raise ValueError('Inference endpoints require literal IP addresses') from exc
    if '%' in (parts.hostname or '') or port == 0:
        raise ValueError('Unsupported inference address or port')
    private = any(address in ip_network(net) for net in
                  ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))
    if not address.is_loopback and (loopback_only or not private):
        raise ValueError('Inference endpoint is outside the permitted private scope')
    return url.rstrip('/')


def local_ollama_host():
    import os
    return validate_endpoint(os.environ.get('LOCAL_OLLAMA_HOST', 'http://127.0.0.1:11434'))


# --- Self-hosted (private GPU) route -------------------------------------------------
# Admitted only for an RFC1918/ULA literal address or an explicitly allow-listed
# internal name (SELFHOSTED_ALLOWED_HOSTS, comma separated). Public addresses,
# metadata addresses, hosted providers and redirects stay rejected.
_RFC1918 = tuple(ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))
_INTERNAL_NAME = __import__('re').compile(r'[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*')
_BLOCKED_NAME_PARTS = ('anthropic', 'deepseek', 'openai', 'googleapis', 'amazonaws', 'azure', 'metadata')


def selfhosted_allowed_hosts(extra=()):
    import os
    names = [n.strip().lower() for n in os.environ.get('SELFHOSTED_ALLOWED_HOSTS', '').split(',') if n.strip()]
    return {n for n in (*names, *(e.lower() for e in extra))}


def validate_selfhosted_endpoint(url, *, allowed_hosts=()):
    """Return a normalized base URL for an OpenAI-compatible private server (e.g. vLLM)."""
    if not isinstance(url, str) or any(c.isspace() for c in url):
        raise ValueError('A private self-hosted HTTP endpoint is required')
    parts = urlsplit(url)
    if (parts.scheme not in ('http', 'https') or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ('', '/', '/v1', '/v1/')):
        raise ValueError('Unsupported self-hosted endpoint')
    host = (parts.hostname or '').lower()
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError('Unsupported self-hosted endpoint port') from exc
    if not host or port == 0 or '%' in host:
        raise ValueError('Unsupported self-hosted endpoint address')
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not any(address in net for net in _RFC1918):
            raise ValueError('Self-hosted endpoint must be a private RFC1918 address')
    else:
        allow = selfhosted_allowed_hosts(allowed_hosts)
        if host not in allow or not _INTERNAL_NAME.fullmatch(host) or any(p in host for p in _BLOCKED_NAME_PARTS):
            raise ValueError('Self-hosted endpoint name is not on the explicit internal allow-list')
    return url.rstrip('/')


def load_bearer_token(*, file_env='SELFHOSTED_TOKEN_FILE', value_env='SELFHOSTED_TOKEN', environ=None):
    """Read the bearer token from a file (preferred) or env var. Never logs or echoes it."""
    import os
    from pathlib import Path
    environ = os.environ if environ is None else environ
    path = environ.get(file_env)
    token = None
    if path:
        try:
            token = Path(path).read_text(encoding='utf-8').strip()
        except OSError as exc:
            raise ValueError('Self-hosted token file could not be read') from exc
    elif environ.get(value_env):
        token = environ[value_env].strip()
    if not token or len(token) < 16 or any(c.isspace() for c in token):
        raise ValueError('A self-hosted bearer token (>=16 chars, no whitespace) is required')
    return token


class SelfHostedRoute:
    """Resolved route; the token is hidden from repr/str so it cannot reach logs."""
    __slots__ = ('model', 'base_url', '_token')

    def __init__(self, model, base_url, token):
        self.model, self.base_url, self._token = model, base_url, token

    def headers(self):
        return {'Authorization': 'Bearer ' + self._token}

    def __repr__(self):
        return f'SelfHostedRoute(model={self.model!r}, base_url={self.base_url!r}, token=<redacted>)'

    __str__ = __repr__


def resolve_selfhosted_route(spec, *, base_url=None, token=None, allowed_hosts=()):
    """`selfhosted:<model>` + SELFHOSTED_BASE_URL (or base_url) -> SelfHostedRoute."""
    import os
    import re
    if not isinstance(spec, str) or not spec.startswith('selfhosted:'):
        raise ValueError('Not a self-hosted route')
    model = spec[len('selfhosted:'):]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}', model) or 'cloud' in model.casefold():
        raise ValueError('Invalid self-hosted model identifier')
    url = validate_selfhosted_endpoint(base_url or os.environ.get('SELFHOSTED_BASE_URL', ''), allowed_hosts=allowed_hosts)
    return SelfHostedRoute(model, url, token if token is not None else load_bearer_token())


def ollama_host(environ=None):
    """OLLAMA_HOST (loopback or RFC1918 only); unset -> historical loopback default."""
    import os
    raw = (os.environ if environ is None else environ).get('OLLAMA_HOST', '').strip()
    if not raw:
        return 'http://127.0.0.1:11434'
    if '://' not in raw:
        raw = 'http://' + raw
    parts = urlsplit(raw)
    if parts.hostname in ('0.0.0.0', '::'):  # server bind address; clients reach loopback
        raw = f'{parts.scheme}://127.0.0.1:{parts.port or 11434}'
    elif parts.port is None and parts.hostname:
        raw = f'{raw.rstrip("/")}:11434'
    return validate_endpoint(raw, loopback_only=False)
