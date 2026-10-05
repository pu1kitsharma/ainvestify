# Setup, configuration and testing


## Quick start

1. Install [Ollama](https://ollama.com/download) and confirm `ollama serve` is running. Pull the models you intend to route to (see **Model configuration** below) — nothing is downloaded automatically.
2. `pip install -r requirements.txt` (add `-r requirements-dev.txt` for `pytest`/`httpx` to run the test suite).
3. Backend: `python3 scripts/serve_local.py` — starts the FastAPI app on `http://localhost:8000` **without auto-reload**. Check active jobs before restarting. For the temporary local account, use the `--local-dev --without-worker` form above.
4. Frontend: `cd frontend && npm install && npm run dev` — Vite dev server on `http://localhost:5173`, with `/api` proxied to the backend.
5. CLI entry point (bypasses the web UI entirely): `python3 main.py "<what you want to do>"` — e.g. `"find promising fintech companies to incubate"` or `"screen this deal, I have the pitch deck ready"`.

## Configuration and sign-in

Preparation now defaults to local inference without hosted fallback. The
[public research setup](deployment/PUBLIC_RESEARCH_SETUP.md) describes a
historical optional adapter, not the target self-hosted KB. No AWS deployment or
live investment-quality acceptance is implied.

For Google login, register a **Web application** OAuth client with Google and set
`OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` in the backend environment, outside source
control. The issuer defaults to `https://accounts.google.com`; only identity scopes
are requested. Never paste the secret into chat or commit it.

Set `APP_ORIGIN` to the exact frontend origin. The registered callback is always
`<APP_ORIGIN>/api/auth/callback`. Prefer trusted local HTTPS. For explicitly isolated
loopback development only, use `APP_ENV=development`, `ALLOW_LOOPBACK_HTTP=1` and
`APP_ORIGIN=http://127.0.0.1:5173` when using `--local-dev`, and register
`http://127.0.0.1:5173/api/auth/callback` with Google. Temporary local login
accepts either `127.0.0.1:5173` or `localhost:5173`; Google login uses the
canonical `127.0.0.1` callback. Non-loopback HTTP and relaxed production settings
are rejected. This is sign-in only, not Google Drive access.

Use the project environment: `source .venv/bin/activate` (or create it first with
`python3 -m venv .venv` and install requirements). `scripts/serve_local.py` now starts
one separate durable room worker; `--without-worker` is available when supervising
`scripts/run_room_worker.py --watch` separately. Access logging is disabled to keep
callback codes out of URL logs. The API remains on loopback without reload.
Do not run a worker against the live DB until ownership and local configuration
are intentional. New authenticated users start with empty sandboxes; no automatic
legacy ownership migration exists.
For the local Vite frontend, start the backend with
`.venv/bin/python scripts/serve_local.py --local-dev --without-worker` while
ownership is unverified. This sets only the explicit loopback development origin;
Google OAuth client credentials still need to be supplied securely in the backend
environment.

The `--local-dev` option also enables a **temporary user ID/password** sign-in
choice on the local login screen. It is restricted to loopback development and
is unavailable in production. Create a fresh isolated sandbox with
`APP_ENV=development ALLOW_LOOPBACK_HTTP=1 LOCAL_DEV_PASSWORD_LOGIN=1 APP_ORIGIN=http://127.0.0.1:5173 .venv/bin/python scripts/create_local_dev_user.py --user-id temporary`.
The script prints a mode-0600 local credential-file path; it never prints the
password to routine server logs. Keep that file private. Passwords are stored
as salted PBKDF2 verifiers and session/CSRF tokens only as hashes in SQLite.
This temporary login does not satisfy the OIDC release requirement or migrate
any legacy data into the new sandbox.

Room activation is exposed at `POST /api/rooms/from-lead/{lead_id}/activate`; direct
entry uses `POST /api/rooms`. The UI activates the room on opening. Unchanged work
reuses its job; changed inputs fence obsolete work. Inspect states with
`GET /api/rooms/{id}`. Artifact previews require authentication. Final downloads
recheck trusted package manifests, actual bytes, current inputs and reviewer grants.

The room UI now shows each durable checkpoint, public KB rights status, local
review findings and release blockers. It lists preview links only for artifacts
matching the latest job's input revision. The older Documents page is explicitly
historical and read-only: retired compilation actions and misleading approval
claims have been removed. The backend still needs a concise package-level
release/reviewer summary and citation-level semantic findings in the room API
before the frontend can show exact accepted-package status or a useful finding
drilldown. No current room draft is represented as ready to send.

Fresh semantic material reviews use a versioned `semantic_v10` request. The
model selects an enumerated slide sentence and quotes the exact proposition it
challenges. Software attaches all offered memo spans sharing that sentence's
cited source IDs, plus finite evidence-scope metadata; the model still decides
whether a defect exists and authors the explanation. Historical requests keep
their recorded contracts and exact replay. A synthetic-only relation probe can
be run with `scripts/evaluate_local_assertion_relation_probe.py`; its scorecard
does not release materials or change the production review route. The opt-in
`semantic_v11` worker implements the same fixed-row shape but is held back by
the failed scale diagnostic. See
[NEXT_AGENT.md](NEXT_AGENT.md) for live failures and the next bounded gate.

Private LibreOffice conversion now uses a short job-local 0700 directory and
Unix IPC socket. Synthetic intro/pitch and revised IM editable/PDF pairs passed
page and text checks, with privacy canaries for sibling files and socket/network
access. Visual parity and complete production Office qualification remain open.
The separate bundled UNO executable failed qualification; do not relax private
isolation to make it pass. See [NEXT_AGENT.md](NEXT_AGENT.md) and the retained
reports under ignored `runtime_qualification/` for exact scope.

## Model configuration

Preparation defaults to local Ollama. Private room workers explicitly use local
inference. Product model selection rejects Claude Pro, Anthropic API and DeepSeek;
historical provider modules remain in the tree but are not approved response routes.
There is no automatic model download. Do not provide private room data to hosted
inference.

| Variable | Purpose | Default |
|---|---|---|
| `SOURCING_MODEL` | Short extraction / classification tasks (lead routing, directive classification) | `phi4-mini` |
| `REASONING_MODEL` | Analytical work, screening, retries, review — thinking enabled | `qwen3:8b` (`qwen3:14b` auto-selected on machines with ≥24GB RAM) |
| `PREPARATION_MODEL` | Fast preparation route for operations drafts | see `agents/inference/local_models.py` |
| `PREPARATION_PROVIDER` | Public reasoning provider; room-private workers always use local | `local` |
| `ELASTICSEARCH_URL` / `ELASTICSEARCH_API_KEY_FILE` / `ELASTICSEARCH_CA_FILE` | Controlled public KB/ES connection and TLS/authentication | unset |
| `REVIEW_MODEL` / `ESCALATION_MODEL` | Alternate thinking models for review/escalation stages | falls back to `REASONING_MODEL` |
| `RESEARCH_AGENT_CONTACT` | Real `"YourOrg contact@email.com"` — SEC EDGAR and Wikipedia both hard-require an identifying User-Agent per their published policies (Wikipedia 403s without one) | placeholder, must be set before relying on either beyond local smoke-testing |
| `PREPARATION_MAX_SECONDS` | Time budget for the preparation path | see `agents/inference/local_models.py` |
| `DISCOVERY_PLAYWRIGHT_MODULE` | Path to an installed Playwright module, for the browser regression scripts only (`scripts/check_discovery_ui.cjs`, `scripts/check_operations_ui.cjs`) | none |

Historical provider configuration remains for compatibility. It is not part of
the local-model product path or an instruction to configure hosted inference.


## Testing

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m pytest -q tests/research tests/delivery tests/api/test_rooms.py tests/api/test_room_financial_phase.py tests/analysis/test_workbook_reconciliation.py tests/analysis/test_private_financial_worker.py tests/discovery/test_kb_candidate.py -p no:cacheprovider
cd frontend && npm run build && npm run lint
```

The focused research and delivery suites most recently passed
1,029 tests with 5 skipped (research and delivery suites). That code result is separate from live model and
investor acceptance. Local model diagnostics require a running Ollama instance;
their raw responses and failure reports are retained under ignored
`runtime_qualification/`. Do not overwrite a failed run to claim success.

Live/manual checks (need Ollama running, hit real networks — not part of the offline suite):

```
python3 scripts/smoke_web_sourcing.py --brief "Agricultural companies making solar dryers" --geography India --max-pages 2
python3 scripts/smoke_operations.py
node scripts/check_discovery_ui.cjs      # needs Playwright; set DISCOVERY_PLAYWRIGHT_MODULE if not on the default path
node scripts/check_operations_ui.cjs
```

