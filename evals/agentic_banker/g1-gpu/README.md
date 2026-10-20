# G1: GPU controls (Phase A, offline)

Software and scripts only. No gcloud/aws/terraform command was run, no cloud resource exists, no spend.

- Self-hosted route: `agents/inference/endpoint_policy.py` (`validate_selfhosted_endpoint`, `load_bearer_token`,
  `resolve_selfhosted_route`, `ollama_host`), `model_routing.parse_model_route`.
- Lifecycle: `delivery/gpu_lifecycle.py` (dry-run default, injected runner, event log, preemption re-queue).
- Ledger: `GpuSpendLedger` in `agents/inference/spend_guard.py`; rates in `deploy/gcp/gpu_rates.json` (unverified).
- Bring-up scripts: `deploy/gcp/` (dry-run by default; `APPLY=1` plus an approval variable needed to execute).
- Kill-switch logic: `deploy/gcp/kill_switch/main.py`, tested with synthetic Pub/Sub messages.
- Docs: `deployment/GPU_RUN_PLAN_TEMPLATE.md`, `deployment/GPU_QUOTA_REQUEST.md`.
- Tests: `tests/gpu/`, `tests/inference/test_selfhosted_route.py`. Run: `.venv/bin/python -m pytest tests/gpu tests/inference -q`.

Unverified: scripts were only `bash -n` syntax checked; gcloud flags, SKU names, the DLVM image family and vLLM flags
must be reviewed against current docs before first use. Real preemption/stop behaviour is untested.
