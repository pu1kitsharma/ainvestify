# Optional existing public API and local Elasticsearch setup

> This runbook documents existing code, not the target inference architecture.
> For self-hosted local-first implementation, follow the [current plan](../LOCAL_TO_CLOUD_RELEASE_PLAN.md). No hosted key is required by that target design.

This is the offline setup guide for the India pre-seed/seed workflow. No service
was installed or live provider switched during the implementation. DeepSeek Flash
is the default public adapter; its real output quality has not been benchmarked.
Private documents/financials and their derivatives stay on the local inference path.

## 1. Prepare Elasticsearch

Use an organization-controlled local Elasticsearch instance bound to loopback.
The current adapter deliberately accepts only localhost/127.0.0.1/::1. A remote
organization cluster needs an explicit deployment/security change before use.

For a local pilot, follow Elastic's authenticated
[single-node Docker instructions](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-basic).
Docker is not installed on the inspected machine. The official documentation
currently uses Elasticsearch 9.5.4; pin and review the chosen release. Use a
persistent volume, expose only the loopback interface, retain TLS/authentication,
and keep certificates and credentials outside Git. Do not expose port 9200 publicly.
No Kibana, embedding service or hosted ES account is required for the cache.

Create an application API key limited to these indices, with the permissions
needed for document read/write/create/delete and initial index creation:

- `ainvestify-public-results-v1`
- `ainvestify-public-search-v1`
- `ainvestify-public-sources-v1`
- `ainvestify-public-leases-v1`

Provision indices centrally and remove creation privilege after initial setup if
that matches your deployment policy. Use one shard for this small local pilot;
configure replicas according to the actual cluster. These are exact caches, not
yet a full searchable company master or semantic/vector retrieval service.

Save the encoded ES API key through the hidden prompt:

```bash
python3 scripts/configure_api_key.py --provider elasticsearch
```

This saves `deployment/.secrets/elasticsearch_api_key` with mode 0600. That
directory is ignored by Git. Existing files are never overwritten by the helper.

## 2. Configure public inference

Use a direct API key, not a consumer chat subscription or Claude credentials:

```bash
python3 scripts/configure_api_key.py --provider deepseek
```

The helper makes no network requests. In the shell that will run the API:

```bash
export PREPARATION_PROVIDER=deepseek_public
export DEEPSEEK_API_KEY_FILE="$PWD/deployment/.secrets/deepseek_api_key"
export ELASTICSEARCH_URL=https://localhost:9200
export ELASTICSEARCH_API_KEY_FILE="$PWD/deployment/.secrets/elasticsearch_api_key"
export ELASTICSEARCH_CA_FILE=/absolute/path/to/http_ca.crt
export PUBLIC_REASONING_MONTHLY_USD=5
python3 scripts/check_public_runtime.py
```

Use the actual local URL and CA path. `configured: true` only means configuration
is present; it is not an authenticated connectivity or model-quality check. Never
paste API keys into chat, URLs, repository files, screenshots or logs.

If all inference must be local, explicitly select `PREPARATION_PROVIDER=local` and
use the installed Ollama models. This has no hosted reasoning fallback. Local
model quality/latency limits from the historical evaluations remain unresolved.
External web searches still send deliberately public search queries.

## 3. Start only after checking active jobs

Inspect existing discovery and preparation jobs before replacing the stable API.
Use `python3 scripts/serve_local.py` without reload. Loading new code requires a
restart; editing files or setting variables in another terminal does not change
an already-running server. Keep the current database and artifact directories.

Start with a small public-only India seed search and one synthetic company pack.
Verify results and API billing before using real deals. Legacy broad search
results stay in history and cannot be continued as a new scoped search. Do not
use Kaleidofin's existing shortlist status as proof of seed-stage eligibility.

## Cache and budget behavior

- Public search result TTL: 6 hours; source snapshots: 24 hours; model results:
  24 hours. Expired entries are rejected even before physical cleanup.
- Fingerprints include exact evidence, task/instructions, schema, model contract
  and settings. Source changes, audience/prompt changes and schema changes miss
  the old result. The contract version must be bumped on a model-policy change.
- Cached raw output is hash-checked and schema-checked. Current downstream source
  binding and semantic validation still apply; a cache hit is not expert approval.
- A hit makes no paid provider request. `cache_hits`, `requests`, token usage and
  reserved cost are recorded separately; historical `calls` counts logical task
  attempts, including cache lookups.
- ES failures stop paid generation. An absent ES endpoint also blocks paid calls.
- ES create-only leases prevent duplicate generation for identical requests.
  Expired leases use sequence/primary-term fencing. A failed submitted request
  retains its lease for up to 180 seconds because it may still have been billed.
- Per-pass reservation ceiling: $0.25. The existing maximum three-pass analysis
  loop can reserve up to $0.75 across its passes. Default monthly reservation
  ceiling: $5, shared across jobs through `.cache/public-spend.sqlite3`.
- Reservations use conservative byte-based input and maximum-output estimates
  at the recorded peak prices, not a billing reconciliation. Failed requests
  retain reservations. These are application safeguards; review provider prices
  and set a provider-account credit/spend limit as well. The ledger is local to
  this deployment, not a distributed multi-server billing service.
- Cache-hit savings do not eliminate source-refresh/search-provider costs.
  The current independent search adapters are free best-effort DDG/Mwmbl routes;
  blocked/empty search coverage remains a live validation risk. No bypass or
  automatic paid search fallback is enabled.

Expired source/result documents and audit data still occupy disk until an
operator retention job removes them. Set index retention and backup retention
before sustained use. Do not share these cache credentials with private-document
storage. Private data is not supported in these ES indices.

## Remaining product work

The intro/pitch PPTX/PDF renderers, transaction-specific compliance requirements
registry, qualified final approval, live provider evaluation and a successful
Kaleidofin recovery are not established by these infrastructure changes. The
current founder/research preparation is not a finished investor deck. See
[the current plan](../LOCAL_TO_CLOUD_RELEASE_PLAN.md) for the product scope and sequence.
