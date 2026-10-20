import pytest
from agents.inference.endpoint_policy import (validate_selfhosted_endpoint, load_bearer_token, resolve_selfhosted_route,
                                               ollama_host, validate_endpoint)
from agents.inference.model_routing import parse_model_route, validate_local_model_name

TOKEN = 'x' * 32


@pytest.mark.parametrize('url', ['http://10.20.0.5:8000', 'http://192.168.1.9:8000/v1', 'http://172.16.4.4:8000/'])
def test_private_addresses_admitted(url):
    assert validate_selfhosted_endpoint(url).startswith('http://')


@pytest.mark.parametrize('url', ['https://api.anthropic.com', 'http://8.8.8.8:8000', 'http://169.254.169.254', 'http://10.0.0.1@8.8.8.8',
    'http://gpu.internal:8000', 'http://10.0.0.1:8000/x', 'http://10.0.0.1?a=b', 'http://34.100.1.1:8000', 'ftp://10.0.0.1'])
def test_public_hosted_or_ambiguous_rejected(url):
    with pytest.raises(ValueError):
        validate_selfhosted_endpoint(url)


def test_allowlisted_internal_name_only(monkeypatch):
    with pytest.raises(ValueError):
        validate_selfhosted_endpoint('http://gpu.internal:8000')
    monkeypatch.setenv('SELFHOSTED_ALLOWED_HOSTS', 'gpu.internal')
    assert validate_selfhosted_endpoint('http://gpu.internal:8000') == 'http://gpu.internal:8000'
    monkeypatch.setenv('SELFHOSTED_ALLOWED_HOSTS', 'api.anthropic.com,deepseek.internal')
    for bad in ('https://api.anthropic.com', 'http://deepseek.internal'):
        with pytest.raises(ValueError):
            validate_selfhosted_endpoint(bad)


def test_token_from_file_and_never_in_repr(tmp_path):
    f = tmp_path / 't'; f.write_text(TOKEN + '\n')
    assert load_bearer_token(environ={'SELFHOSTED_TOKEN_FILE': str(f)}) == TOKEN
    route = resolve_selfhosted_route('selfhosted:banker-base', base_url='http://10.0.0.5:8000', token=TOKEN)
    assert TOKEN not in repr(route) and TOKEN not in str(route)
    assert route.headers() == {'Authorization': 'Bearer ' + TOKEN}
    for env in ({}, {'SELFHOSTED_TOKEN': 'short'}, {'SELFHOSTED_TOKEN_FILE': str(tmp_path / 'missing')}):
        with pytest.raises(ValueError):
            load_bearer_token(environ=env)


def test_parse_model_route_and_hosted_names_still_rejected(monkeypatch):
    monkeypatch.setenv('SELFHOSTED_BASE_URL', 'http://10.0.0.5:8000')
    monkeypatch.setenv('SELFHOSTED_TOKEN', TOKEN)
    kind, route = parse_model_route('selfhosted:banker-base')
    assert kind == 'selfhosted' and route.model == 'banker-base'
    assert parse_model_route('qwen3:8b') == ('ollama', 'qwen3:8b')
    with pytest.raises(ValueError):  # selfhosted names never pass as plain Ollama names
        validate_local_model_name('selfhosted:banker-base')
    for bad in ('anthropic-api:claude', 'deepseek-api:x', 'claude-pro-sonnet', 'llama3:cloud'):
        with pytest.raises(ValueError):
            parse_model_route(bad)
    monkeypatch.setenv('SELFHOSTED_BASE_URL', 'https://api.anthropic.com')
    with pytest.raises(ValueError):
        parse_model_route('selfhosted:banker-base')


def test_ollama_host_default_and_env():
    assert ollama_host({}) == 'http://127.0.0.1:11434'
    assert ollama_host({'OLLAMA_HOST': '0.0.0.0:11434'}) == 'http://127.0.0.1:11434'
    assert ollama_host({'OLLAMA_HOST': '10.1.2.3:11434'}) == 'http://10.1.2.3:11434'
    assert ollama_host({'OLLAMA_HOST': '127.0.0.1'}) == 'http://127.0.0.1:11434'
    for bad in ('8.8.8.8:11434', 'https://api.anthropic.com'):
        with pytest.raises(ValueError):
            ollama_host({'OLLAMA_HOST': bad})
