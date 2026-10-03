# AWS deployment assessment — 26 September 2026

> Historical context: current instructions are in [AGENTS.md](../AGENTS.md) and the [local-to-cloud plan](../LOCAL_TO_CLOUD_RELEASE_PLAN.md). Older scope/provider/deployment statements below are superseded where they conflict. Preserve the historical evidence.


Status: not deployed. No AWS resources created, credentials copied, database uploaded, or model requests started by this assessment.

## Follow-up: supported API integration

The user signed into AWS and authorized a supported API/provider. VS Code's browser showed the AWS dashboard, but CloudShell reported: “Your account verification is in progress. This may take up to two days for new accounts.” Lightsail navigation was opened, but provisioning availability was not established. Do not treat a successful console login as proof that resources can be created.

The user needs to create an API account and requested Chrome for Claude Console. The Chrome tab is at https://platform.claude.com/ awaiting user sign-up, which accepts Commercial Terms. The user has not supplied an API key or approved a concrete hosting/inference spending amount. No paid calls or resources have been created.

`agents/anthropic_api.py` now implements the official Messages API for public discovery, preparation and the new public company analysis workflow. Select explicitly with `PREPARATION_PROVIDER=anthropic_api_public`. The model defaults to `claude-sonnet-5`, configurable with `ANTHROPIC_MODEL`. The local service default remains unchanged while another session edits and runs it. No service restart was performed for this integration.

The API transport preserves raw response text, API envelope and usage; validates exact model-authored objects; accepts navigation destinations only from structured web-search results; limits search to two uses; reserves search requests against the existing budget; and terminates its HTTP child process on cancellation/deadline. It never uses subscription credentials or retries/falls back automatically. Private-input manifests remain enforced. Private Ollama functionality has not been migrated.

After creating the account and key, run this yourself in the repository terminal:

```sh
python3 scripts/configure_api_key.py
```

The hidden prompt saves the key to ignored `deployment/.secrets/anthropic_api_key` with owner-only permissions. Never paste it into chat or a command argument. The script makes no API calls and does not change the running app. The deployed service will need `ANTHROPIC_API_KEY_FILE` pointing to a securely mounted copy; do not bake the key into an image/source archive. A controlled local check can use the absolute local path, but only after checking active jobs and agreeing the bounded live API spend.

Validation uses mocked API responses and makes no network/model requests. Live authentication, model availability, inference quality, deployment packaging, cloud access protection, persistent paths and the public URL are still outstanding.

## Verified

- VS Code's integrated browser opens the AWS console sign-in flow. It has a separate session from Chrome. The observed flow reached email verification; the user must finish sign-in.
- Frontend is React/Vite; production build is `npm ci && npm run build` in `frontend/`. Browser API requests use relative routes.
- Backend is FastAPI (`api.main:app`). Run one worker because discovery/preparation queues and concurrency guards are process-local.
- SQLite defaults to `deal_automation.db` beside `store.py`. Generated charts/documents use `memo_output/`. Deployment needs persistent storage and backups, not ephemeral application storage.
- Current API has no authentication. Tenant/reviewer headers are caller-controlled, not authenticated identity. A shared deployment needs access protection across API, documents and frontend; hiding UI controls is insufficient.
- Public discovery/preparation invokes the installed Claude CLI and checks personal Pro sign-in. Private analysis paths also depend on local Ollama. Neither dependency moves automatically with frontend/backend files.
- AWS CLI and Docker were not found on the current shell PATH.
- Another active session is modifying this workspace. Capture a deliberate deployment snapshot after its changes settle; preserve all existing changes and local records.

## Proposed first deployment

Use one Linux AWS instance with persistent disk, one API worker, a production frontend build, and a TLS reverse proxy. Begin with an empty cloud workspace and invited-user access unless the user chooses otherwise. Do not upload local databases, backups, credentials, notes, uploads or financial records as part of a source archive.

Lightsail is a candidate for simple persistent single-instance hosting. AWS lists a 2 GB Linux/public IPv4 bundle at $12/month; this is a web/API sizing candidate, not adequate sizing for the existing local language models. Region, actual console availability, transfer, snapshots, taxes, inference costs and final sizing remain to be checked before provisioning. No expenditure is authorized by this document.

For a product used by others, replace the personal Pro route with an explicitly configured supported API/provider. Preserve source binding, recorded exact model responses, privacy scopes, request/time budgets and validation. Discovery's WebSearch dependency and private Ollama paths need separate compatibility checks. Do not silently fall back to a paid provider or transmit private records.

## Outstanding

1. Complete AWS sign-in in the integrated browser.
2. Resolve invited access versus anonymous public use, and empty workspace versus selected public drafts.
3. Select cloud inference credentials/provider and an operating budget; do not ask for secret values in chat.
4. Prepare deployment packaging, persistent paths, TLS/access protection, process supervision and backup/restore procedure against the settled code snapshot.
5. Review the concrete AWS resource/cost configuration before committing recurring expenditure.
6. Deploy and verify the public URL, authentication, persistence through restart, and one explicitly authorized bounded discovery/preparation journey. A health endpoint alone does not establish working AI features.

## Sources checked

- AWS instance bundles: https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html
- AWS pricing: https://aws.amazon.com/lightsail/pricing/
- AWS browser SSH and static IP overview: https://aws.amazon.com/lightsail/faq/
- Anthropic product authentication guidance: https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account

Historical handoff “deployed” results refer to the local running application, not an AWS deployment.
