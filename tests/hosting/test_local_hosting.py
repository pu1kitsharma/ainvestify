"""Offline hosting checks. No model calls, public listeners or source fetches."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import pytest

from scripts import local_hosting as hosting


def production_config():
    return {
        "APP_ENV": "production", "APP_ORIGIN": "https://investify.fyi",
        "ALLOW_LOOPBACK_HTTP": "0", "LOCAL_DEV_PASSWORD_LOGIN": "0",
        "OIDC_CLIENT_ID": "fixture-client", "OIDC_CLIENT_SECRET": "private-fixture-secret",
        "PREPARATION_PROVIDER": "local",
    }


def test_environment_is_literal_and_does_not_execute_or_expand(tmp_path):
    path = tmp_path / "settings"
    path.write_text("# comment\nAPP_ENV=production\nTOKEN='literal#value'\nOTHER=$(not-a-command)\n", encoding="utf-8")
    result = hosting.environment(path, environ={"KEEP": "original", "APP_ENV": "development"})
    assert result == {"KEEP": "original", "APP_ENV": "production", "TOKEN": "literal#value",
                      "OTHER": "$(not-a-command)"}


@pytest.mark.parametrize("body", ["DUP=x\nDUP=private-secret\n", "export KEY=private-secret",
                                  "KEY='private-secret", "KEY=private-secret\x00"])
def test_invalid_environment_errors_do_not_reveal_values(tmp_path, body):
    path = tmp_path / "settings"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError) as error:
        hosting.read_env_file(path)
    assert "private-secret" not in str(error.value)


def test_missing_database_inventory_does_not_create_database(tmp_path):
    path = tmp_path / "absent.db"
    assert hosting.database_inventory(path)["exists"] is False
    assert not path.exists()


def test_explicit_database_path_is_used_for_inventory(tmp_path, monkeypatch):
    configure_report_root(tmp_path, monkeypatch)
    path = tmp_path / 'outside-code' / 'data.db'
    path.parent.mkdir()
    make_database(path, running=True)
    config = production_config()
    config['INVESTIFY_DB_PATH'] = str(path)
    result = hosting.report(config, root=tmp_path, online=False)
    assert result['facts']['database']['running_jobs'] == 1
    assert result['routing_ready'] is False
    assert not (tmp_path / 'deal_automation.db').exists()


def test_server_imports_resolve_explicit_storage_without_creating_files(tmp_path):
    import os
    import subprocess
    import sys
    database = tmp_path / 'private' / 'data.db'
    uploads = tmp_path / 'private' / 'uploads'
    env = dict(os.environ, INVESTIFY_DB_PATH=str(database), PRIVATE_UPLOAD_ROOT=str(uploads))
    code = 'import store; from api.routers.deals import UPLOAD_ROOT; import json; print(json.dumps([str(store.DEFAULT_DB_PATH), str(UPLOAD_ROOT)]))'
    result = subprocess.run([sys.executable, '-B', '-c', code], env=env, cwd=hosting.ROOT,
                            capture_output=True, text=True, timeout=15, check=True)
    assert json.loads(result.stdout) == [str(database), str(uploads)]
    assert not database.exists() and not uploads.exists()


def make_database(path, *, running=False):
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE deals (tenant_id TEXT);
            CREATE TABLE auth_sandboxes (id TEXT);
            CREATE TABLE room_jobs (state TEXT, lease_until REAL);
            INSERT INTO deals VALUES ('orphan'), ('owned');
            INSERT INTO auth_sandboxes VALUES ('owned');
        """)
        connection.execute("INSERT INTO room_jobs VALUES (?,?)",
                           ("running" if running else "queued", time.time() + 100 if running else None))


def test_inventory_is_read_only_and_reports_only_aggregate_metadata(tmp_path):
    path = tmp_path / "source.db"
    make_database(path)
    original = path.read_bytes()
    result = hosting.database_inventory(path)
    assert result["unowned_records"] == 1
    assert result["jobs"] == {"queued": 1}
    assert result["active_leases"] == 0
    assert "orphan" not in json.dumps(result)
    assert path.read_bytes() == original


def test_backup_preserves_source_and_all_records(tmp_path):
    path = tmp_path / "source.db"
    make_database(path)
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    saved = hosting.backup_database(path, tmp_path / "backups")
    assert saved is not None
    with sqlite3.connect(saved) as connection:
        assert connection.execute("SELECT count(*) FROM deals").fetchone()[0] == 2
        assert connection.execute("SELECT state FROM room_jobs").fetchone()[0] == "queued"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


def test_active_jobs_block_backup_without_creating_destination(tmp_path):
    path = tmp_path / "source.db"
    make_database(path, running=True)
    destination = tmp_path / "backups"
    with pytest.raises(RuntimeError, match="Active room jobs"):
        hosting.backup_database(path, destination)
    assert not destination.exists()


def test_preview_never_stops_existing_listeners_or_starts_workers(monkeypatch):
    monkeypatch.setattr(hosting, "port_free", lambda port: False)
    monkeypatch.setattr(hosting.subprocess, "Popen", lambda *a, **k: pytest.fail("started a process"))
    monkeypatch.setattr(hosting, "backup_database", lambda *a: pytest.fail("backed up while busy"))
    with pytest.raises(RuntimeError, match="existing services"):
        hosting.preview(production_config(), seconds=1)


def test_migrated_windows_runtime_never_reports_archived_database_or_forks_api(tmp_path, monkeypatch):
    configure_report_root(tmp_path, monkeypatch)
    monkeypatch.setattr(hosting, 'database_inventory', lambda *a: pytest.fail('Read stale Windows database'))
    monkeypatch.setattr(hosting.subprocess, 'Popen', lambda *a, **k: pytest.fail('Forked Windows API'))
    config = dict(production_config(), LOCAL_API_RUNTIME='wsl')
    result = hosting.report(config, root=tmp_path, online=False)
    assert 'database' not in result['facts'] and result['routing_ready'] is False
    assert any(c['name'] == 'active_runtime_inventory' for c in result['checks'])
    with pytest.raises(RuntimeError, match='migrated to WSL'):
        hosting.preview(config)


def test_frontend_check_supports_explicit_hybrid_web_root(tmp_path, monkeypatch):
    configure_report_root(tmp_path, monkeypatch)
    (tmp_path / 'frontend/dist/index.html').unlink()
    web = tmp_path / 'mounted-frontend'
    web.mkdir()
    (web / 'index.html').write_text('synthetic frontend', encoding='utf-8')
    result = hosting.report(dict(production_config(), INVESTIFY_WEB_ROOT=str(web)), root=tmp_path, online=False)
    assert next(c for c in result['checks'] if c['name'] == 'compiled_frontend')['status'] == 'pass'


def configure_report_root(tmp_path, monkeypatch):
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "frontend/dist/index.html").write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(hosting.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(hosting, "caddy_binary", lambda config: "fixture-caddy")
    monkeypatch.setattr(hosting.platform, "system", lambda: "Windows")


def test_offline_report_hides_credentials_and_never_grants_release(tmp_path, monkeypatch):
    configure_report_root(tmp_path, monkeypatch)
    monkeypatch.setattr(hosting, "local_json", lambda *a: pytest.fail("unexpected HTTP"))
    result = hosting.report(production_config(), root=tmp_path, online=False)
    assert result["routing_ready"] is True
    assert result["multi_user_release_ready"] is False
    assert "private-fixture-secret" not in json.dumps(result)
    assert any(c["name"] == "private_worker_isolation" and c["status"] == "blocked" for c in result["checks"])


def test_model_inventory_does_not_hide_legacy_request_defaults(tmp_path, monkeypatch):
    configure_report_root(tmp_path, monkeypatch)
    config = production_config()
    config.update({name: "qwen3:14b" for name in hosting.MODEL_DEFAULTS})
    monkeypatch.setattr(hosting, "local_json", lambda url: {"models": [{"name": "qwen3:14b"}]})
    checks = {c["name"]: c for c in hosting.report(config, root=tmp_path)["checks"]}
    assert checks["installed_model_routes"]["status"] == "pass"
    assert checks["legacy_default_model"]["status"] == "blocked"


@pytest.mark.parametrize("url", ["http://192.168.1.1/api/tags", "https://127.0.0.1/api/tags",
                                  "http://user:secret@127.0.0.1/api/tags", "http://127.0.0.1/api/tags?x=secret"])
def test_diagnostics_refuse_non_loopback_or_credential_urls(url):
    with pytest.raises(ValueError):
        hosting.local_json(url)


def test_redirect_handler_does_not_follow_redirects():
    assert hosting.NoRedirect().redirect_request(None, None, 302, "", {}, "https://outside.example") is None


def test_serve_env_file_does_not_start_server_on_invalid_config(tmp_path):
    import subprocess
    import sys
    path = tmp_path / "settings"
    path.write_text("INVALID\n", encoding="utf-8")
    result = subprocess.run([sys.executable, "-B", str(hosting.ROOT / "scripts/serve_local.py"),
                             "--env-file", str(path), "--without-worker"],
                            cwd=hosting.ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert "Invalid or unreadable environment file" in result.stderr


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows migration guard is checked on Windows')
def test_serve_env_file_refuses_migrated_windows_database(tmp_path):
    import subprocess
    import sys
    path = tmp_path / 'settings'
    path.write_text('LOCAL_API_RUNTIME=wsl\n', encoding='utf-8')
    result = subprocess.run([sys.executable, '-B', str(hosting.ROOT / 'scripts/serve_local.py'),
                             '--env-file', str(path), '--without-worker'], cwd=hosting.ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and 'API migrated to Investify WSL' in result.stderr
