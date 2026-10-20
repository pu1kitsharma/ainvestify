# Local Phase A software checkpoint

Started 15 October 2026. Synthetic tooling only; not investment acceptance.

- Final focused selection: **86 passed in 0.54 seconds** (`tests/tools`,
  `tests/runtime`, `tests/envs`, `tests/inference/test_endpoint_policy.py`).
- Full `tests` run before final independent hardening: **3,450 passed,
  27 failed, seven skipped**, 180.26 seconds. Raw local log:
  `/private/tmp/deal-document-phase-a-pytest.txt`. The full suite was not repeated
  after the final workbook/logging and split-guard changes; their focused tests
  passed. Green full-suite and no-new-failure gates remain unproven.
- Unchanged `c469ff3` WS-B worktree reproduced four selected failures: room memo
  phase expectation; company-brief background argument; readiness background
  argument; historical model-route expectation. An indexed physical-plan test
  failed in the full run but passed both baseline and isolated integrated reruns;
  this is consistent with suite-order/shared-state behavior, not a proven cause.
- The remaining failures include legacy retired-route assertions, auth/server
  harness failures and sandbox-blocked live Ollama connection attempts. They
  have not all been independently baseline-classified. No validation was weakened.
- `git diff --check` passed. Final read-only room counts match initial counts:
  22 awaiting input, three blocked, four cancelled, two queued; zero active leases.
- Final loopback preflight: `ready_not_run`; zero loaded Ollama models.

The full suite includes live API/model tests. Their requests were blocked in the
restricted test environment; this is not a live qualification run. Future default
offline selection needs explicit live-test separation before any unrestricted run.

No actual model sampling, weights training, model download, private-gold creation,
cloud deployment/spend, production service restart, Git commit or push occurred.
Claude Code is configured for a bounded loopback reviewer task in VS Code, but the
task was not invoked: permission to start Mac inference was requested under the
external plan and has not been received. Preflight is not Claude contribution.

Unqualified areas include source rights, adjudicated gold, full team orchestration,
exact raw-response receipts, hard cancellation, complete formula evaluation,
LibreOffice recalculation, artifact/prose binding, matching PDFs, visual review,
real training, financial/compliance review and human investor release.
