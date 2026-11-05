"""Read-only hosting inventory and an explicit loopback-only routing preview.

No model generation, workers, public listener, DNS/firewall edits or release grant.
The preview backs up SQLite before starting the API, which can migrate its schema.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "deployment/.env"
MODULES = ("fastapi", "uvicorn", "authlib", "ollama", "httpx", "multipart",
           "pdfplumber", "openpyxl", "pptx", "docx", "reportlab", "pypdf",
           "numpy", "faiss", "matplotlib", "bs4", "defusedxml")
MODEL_DEFAULTS = {
    "SOURCING_MODEL": "phi4-mini", "REASONING_MODEL": "qwen3:8b",
    "PREPARATION_MODEL": "qwen3.5:9b", "LOCAL_MEMO_DRAFT_MODEL": "qwen3.5:9b",
    "LOCAL_MEMO_AUTHOR_MODEL": "qwen3:14b",
}
LEGACY_TABLES = ("deals", "documents", "sourced_leads", "company_profiles", "operating_workspaces")


def read_env_file(path):
    """Read literal KEY=VALUE, without executing shell code or expanding variables."""
    values = {}
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ValueError(f"Invalid or duplicate environment key on line {number}")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed environment value on line {number}")
            value = value[1:-1]
        if "\x00" in value:
            raise ValueError(f"Invalid environment value on line {number}")
        values[key] = value
    return values


def environment(path, *, environ=None):
    result = dict(os.environ if environ is None else environ)
    if Path(path).is_file():
        result.update(read_env_file(path))
    return result


def database_inventory(path):
    """SELECT-only metadata. Never instantiate Store or initialize a missing database."""
    path = Path(path)
    if not path.is_file():
        return {"exists": False, "running_jobs": 0, "active_leases": 0, "unowned_records": 0}
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        connection.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result = {"exists": True, "running_jobs": 0, "active_leases": 0, "unowned_records": 0}
        if "room_jobs" in tables:
            result["jobs"] = dict(connection.execute("SELECT state,count(*) FROM room_jobs GROUP BY state"))
            result["running_jobs"] = result["jobs"].get("running", 0)
            result["active_leases"] = connection.execute(
                "SELECT count(*) FROM room_jobs WHERE lease_until>?", (time.time(),)).fetchone()[0]
        for table in LEGACY_TABLES:
            if table not in tables:
                continue
            if "auth_sandboxes" in tables:
                count = connection.execute(
                    f"SELECT count(*) FROM {table} x WHERE NOT EXISTS "
                    "(SELECT 1 FROM auth_sandboxes s WHERE s.id=x.tenant_id)").fetchone()[0]
            else:
                count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            result["unowned_records"] += count
        return result
    finally:
        connection.close()


def database_path(config, *, root=ROOT):
    return Path(config.get('INVESTIFY_DB_PATH') or Path(root) / 'deal_automation.db')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def local_json(url):
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Only literal loopback HTTP diagnostics are supported")
    if not ipaddress.ip_address(parts.hostname or "").is_loopback:
        raise ValueError("Only literal loopback HTTP diagnostics are supported")
    request = Request(url, headers={"Accept": "application/json"})
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=3) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Diagnostic response exceeds its limit")
    return json.loads(data)


def caddy_binary(config):
    configured = config.get("CADDY_BINARY")
    if configured:
        return str(Path(configured).resolve()) if Path(configured).is_file() else None
    portable = ROOT / "deployment/.secrets/caddy" / ("caddy.exe" if os.name == "nt" else "caddy")
    return str(portable) if portable.is_file() else shutil.which("caddy")


def report(config, *, root=ROOT, online=True):
    root = Path(root)
    checks = []
    facts = {"platform": platform.system(), "python": platform.python_version()}
    def add(name, status, detail, scope="full"):
        checks.append({"name": name, "status": status, "scope": scope, "detail": detail})

    missing = [name for name in MODULES if importlib.util.find_spec(name) is None]
    add("python_dependencies", "blocked" if missing else "pass",
        "Missing: " + ", ".join(missing) if missing else "Required import targets are installed; imports are checked separately.",
        "routing")
    web_root = Path(config.get('INVESTIFY_WEB_ROOT') or root / 'frontend/dist')
    add("compiled_frontend", "pass" if (web_root / "index.html").is_file() else "blocked",
        "Build with npm run build in frontend.", "routing")
    add("caddy", "pass" if caddy_binary(config) else "blocked",
        "Caddy executable is available." if caddy_binary(config) else "Install Caddy or set CADDY_BINARY.", "routing")
    migrated = config.get('LOCAL_API_RUNTIME') == 'wsl' and platform.system() == 'Windows'
    try:
        if migrated:
            raise RuntimeError('active_database_is_in_wsl')
        facts["database"] = database_inventory(database_path(config, root=root))
        busy = facts["database"]["running_jobs"] or facts["database"]["active_leases"]
        add("active_room_jobs", "blocked" if busy else "pass",
            "Active work must finish before starting or restarting services." if busy else "No running room job or active lease observed.",
            "routing")
        unowned = facts["database"]["unowned_records"]
        add("legacy_ownership", "blocked" if unowned else "pass",
            f"{unowned} records lack an existing sandbox association; verified ownership migration is required."
            if unowned else "No unassigned legacy records observed; live ownership acceptance is separate.")
    except (sqlite3.Error, OSError):
        add("database_inventory", "blocked", "Database metadata could not be read safely.", "routing")
    except RuntimeError:
        add('active_runtime_inventory', 'unknown',
            'The active database/API are in Investify WSL; the Windows database is preserved history. Run the Linux check with its private server.env.', 'routing')
    secure = (config.get("APP_ENV") == "production"
              and config.get("APP_ORIGIN") == "https://investify.fyi"
              and config.get("ALLOW_LOOPBACK_HTTP", "0") == "0"
              and config.get("LOCAL_DEV_PASSWORD_LOGIN", "0") == "0")
    add("production_origin", "pass" if secure else "blocked",
        "Require APP_ENV=production, APP_ORIGIN=https://investify.fyi and development login/HTTP disabled.")
    oidc = (config.get("OIDC_ISSUER", "https://accounts.google.com") == "https://accounts.google.com"
            and all(config.get(key, "").strip() for key in ("OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")))
    add("google_oidc_config", "pass" if oidc else "blocked",
        "Credentials are present; live login is still unqualified." if oidc else "Create a Google Web OAuth client and store credentials in deployment/.env.")
    local = config.get("PREPARATION_PROVIDER", "local") == "local"
    add("local_inference_policy", "pass" if local else "blocked", "PREPARATION_PROVIDER must remain local.")
    hosts = [config.get(key, "http://127.0.0.1:11434") for key in ("OLLAMA_HOST", "LOCAL_OLLAMA_HOST")]
    local_hosts = True
    for host in hosts:
        try:
            parts = urlsplit(host)
            local_hosts &= (parts.scheme == "http" and ipaddress.ip_address(parts.hostname or "").is_loopback
                            and not parts.username and not parts.password and not parts.query
                            and not parts.fragment and parts.path in ("", "/") and parts.port == 11434)
        except ValueError:
            local_hosts = False
    add("model_endpoint", "pass" if local_hosts else "blocked", "Both model clients must use literal loopback HTTP port 11434.")
    if online and local_hosts:
        try:
            names = {item["name"] for item in local_json(hosts[0].rstrip("/") + "/api/tags").get("models", [])}
            facts["installed_models"] = sorted(names)
            required = {config.get(key) or default for key, default in MODEL_DEFAULTS.items()}
            required.update(config[key] for key in ("REVIEW_MODEL", "ESCALATION_MODEL", "LOCAL_MEMO_PART_B_MODEL",
                "LOCAL_MEMO_REVIEW_MODEL", "LOCAL_MEMO_CHALLENGE_MODEL", "LOCAL_MATERIAL_DRAFT_MODEL") if config.get(key))
            missing_models = sorted(name for name in required if name not in names and name + ":latest" not in names)
            add("installed_model_routes", "blocked" if missing_models else "pass",
                "Missing configured models: " + ", ".join(missing_models) if missing_models else "Configured role identifiers are installed; no generation was run.")
            add("legacy_default_model", "pass" if "phi4-mini" in names or "phi4-mini:latest" in names else "blocked",
                "Several legacy API/CLI defaults explicitly request phi4-mini; environment role settings do not rewrite those request defaults.")
        except (URLError, OSError, ValueError, KeyError, TypeError):
            add("ollama_inventory", "blocked", "Could not read the local model inventory; no model call was attempted.")
    else:
        add("ollama_inventory", "unknown", "Local HTTP inventory was not run.")
    add("private_storage", "blocked" if platform.system() == "Windows" else "unknown",
        "Private storage requires POSIX no-follow directory/file descriptors; a Windows equivalent and native acceptance are not implemented.")
    system = platform.system()
    if system == "Windows":
        add("private_worker_isolation", "blocked", "delivery/isolation.py has no Windows backend; private room processing refuses execution.")
    elif system == "Linux":
        enabled = config.get('PRIVATE_MODEL_IPC') == 'unix-ollama-v1'
        add("private_worker_isolation", "unknown" if enabled else "blocked",
            "Unix model IPC is explicitly enabled; native process, file, network and full-room acceptance remain required."
            if enabled else "Linux local inference requires the explicit PRIVATE_MODEL_IPC=unix-ollama-v1 socket boundary and native qualification; host networking must remain unshared.")
    else:
        add("private_worker_isolation", "unknown", "Native private filesystem/network and Office qualification must pass on this host.")
    add("public_kb", "unknown" if (root / "runtime_public_kb/kb.db").is_file() else "blocked",
        "Restore/qualify the rights-reviewed local registry, archive and loopback Elasticsearch; no sources are enabled by this check.")
    add("internet_routing", "unknown", "This local inventory does not qualify public ingress. Verify the chosen named outbound tunnel or direct inbound route, DNS, certificate and external HTTPS; router access is unnecessary for an outbound tunnel. See the current hosting runbook and retained public smoke evidence.")
    add("live_multi_user_acceptance", "unknown", "Two real Google users, private files/jobs/caches, revocation and legacy ownership require acceptance before release.")
    add("investor_artifact_release", "unknown", "All mandatory financial, Office, model and exact-file human review gates remain in force.")
    return {"routing_ready": not any(c["scope"] == "routing" and c["status"] != "pass" for c in checks),
            "multi_user_release_ready": all(c["status"] == "pass" for c in checks),
            "facts": facts, "checks": checks}


def backup_database(path, backup_root):
    path = Path(path)
    if not path.is_file():
        return None
    if (state := database_inventory(path))["running_jobs"] or state["active_leases"]:
        raise RuntimeError("Active room jobs or leases block startup")
    directory = Path(backup_root) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / path.name
    source = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite backup integrity check failed")
    finally:
        destination.close()
        source.close()
    return target


def port_free(port):
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def preview(config, *, seconds=0):
    if config.get('LOCAL_API_RUNTIME') == 'wsl':
        raise RuntimeError('API migrated to WSL; use deployment/local/start_local_host.ps1 instead of starting a second Windows database')
    if not all(port_free(port) for port in (8000, 8080)):
        raise RuntimeError("Ports 8000/8080 must be free; existing services are never stopped automatically")
    result = report(config)
    if not result["routing_ready"]:
        raise RuntimeError("Routing prerequisites are blocked; run the check command")
    child_env = dict(config, APP_ENV="production", APP_ORIGIN="https://investify.fyi",
                     ALLOW_LOOPBACK_HTTP="0", LOCAL_DEV_PASSWORD_LOGIN="0",
                     PYTHONDONTWRITEBYTECODE="1", INVESTIFY_WEB_ROOT=(ROOT / "frontend/dist").as_posix())
    binary = caddy_binary(config)
    caddyfile = str(ROOT / "deployment/local/Caddyfile.preview")
    subprocess.run([binary, "validate", "--config", caddyfile, "--adapter", "caddyfile"],
                   cwd=ROOT, env=child_env, check=True)
    saved = backup_database(database_path(config), ROOT / "runtime_backups/local-hosting")
    if saved:
        print("Verified SQLite backup: " + str(saved), flush=True)
    children = []
    try:
        children.append(subprocess.Popen([sys.executable, "-B", str(ROOT / "scripts/serve_local.py"),
                                         "--without-worker"], cwd=ROOT, env=child_env))
        deadline = time.monotonic() + 30
        while True:
            if children[0].poll() is not None:
                raise RuntimeError("API exited during startup")
            try:
                if local_json("http://127.0.0.1:8000/api/health").get("status") == "ok":
                    break
            except (URLError, OSError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("API startup health deadline expired")
            time.sleep(.25)
        children.append(subprocess.Popen([binary, "run", "--config", caddyfile, "--adapter", "caddyfile"],
                                         cwd=ROOT, env=child_env))
        print("Loopback routing preview: http://127.0.0.1:8080 (no room worker or public listener)", flush=True)
        deadline = time.monotonic() + seconds if seconds else None
        while deadline is None or time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A preview service exited; stopping the preview")
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "preview"))
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    parser.add_argument("--offline", action="store_true", help="No local HTTP inventory (check only)")
    parser.add_argument("--json", action="store_true", help="Print metadata with secrets omitted")
    parser.add_argument("--seconds", type=int, default=0, help="Stop an explicit preview after this many seconds; zero means Ctrl+C")
    args = parser.parse_args()
    if args.seconds < 0 or args.command == "preview" and args.offline:
        parser.error("Invalid preview options")
    try:
        config = environment(args.env_file)
        if args.command == "preview":
            preview(config, seconds=args.seconds)
            return 0
        result = report(config, online=not args.offline)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            for check in result["checks"]:
                print(f"{check['status'].upper():7} {check['name']}: {check['detail']}")
            print("Routing ready: " + str(result["routing_ready"]))
            print("Multi-user release ready: " + str(result["multi_user_release_ready"]))
        return 0 if result["multi_user_release_ready"] else 2
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # Do not echo arbitrary exception strings, config values, HTTP bodies or credentials.
        print("Hosting operation failed (" + type(error).__name__ + "). Run check and inspect local service diagnostics.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
