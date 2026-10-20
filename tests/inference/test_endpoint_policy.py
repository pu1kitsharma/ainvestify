import pytest
from agents.inference.endpoint_policy import validate_endpoint, local_ollama_host


@pytest.mark.parametrize('url', ['https://api.anthropic.com', 'http://localhost:11434',
    'http://169.254.169.254', 'http://0.0.0.0:11434', 'http://8.8.8.8',
    'http://127.0.0.1@8.8.8.8', 'http://127.0.0.1/path',
    'http://127.0.0.1?redirect=x', 'http://127.0.0.1:0', 'http://10.1.2.3'])
def test_local_rejects_non_loopback_and_ambiguous_urls(url):
    with pytest.raises(ValueError):
        validate_endpoint(url)


def test_local_and_explicit_private_admission(monkeypatch):
    assert validate_endpoint('http://[::1]:11434/') == 'http://[::1]:11434'
    assert validate_endpoint('http://10.1.2.3:8000/v1', loopback_only=False).endswith('/v1')
    with pytest.raises(ValueError):
        validate_endpoint('http://169.254.169.254', loopback_only=False)
    monkeypatch.setenv('LOCAL_OLLAMA_HOST', 'https://example.com')
    with pytest.raises(ValueError):
        local_ollama_host()
