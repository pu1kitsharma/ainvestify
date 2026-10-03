# AInvestify frontend

React, TypeScript and Vite UI for the local deal workspace. The backend owns sessions,
private room state, job checkpoints and artifact release decisions; the UI displays
those states and does not turn a draft into an accepted investor document.

## Run locally

From the repository root, prepare the Python environment and start the backend
without reload. For the temporary loopback development account, use:

```sh
.venv/bin/python scripts/serve_local.py --local-dev --without-worker
```

In a second terminal:

```sh
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the loopback backend.
Google OIDC requires a separately registered Web OAuth client; the temporary
user ID/password option is limited to local development. See the root
[README](../README.md#setup) for setup and sandbox details. Do not use a live
room worker against unverified legacy data ownership.

## Current UI surface

- Signed-in dashboard, leads, company operations and existing deal pages.
- Opening a lead's deal room activates a durable local job. The UI polls the
  room for evidence, financial, material and validation checkpoints and can
  cancel queued/running work.
- Draft artifacts use authenticated preview routes. Final downloads require
  the backend's exact-version package validation and reviewer grants.

The current local-model material diagnostic produced editable/PDF pairs for a
synthetic case, but semantic review and independent visual/content acceptance
remain open. The UI must preserve those blocked and pending states. A lead,
room draft or historical funding observation is not an investment recommendation.

## Checks

```sh
cd frontend
npm run build
npm run lint
```

Backend tests and live qualification are separate; see [NEXT_AGENT.md](../NEXT_AGENT.md)
for the latest exact status. The root [README](../README.md) lists repository checks.
