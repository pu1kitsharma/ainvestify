# Offline regression checkpoint — 16 October 2026

23 passed, 12 skipped in 10.29s using the existing root `.venv/bin/python`.
The skipped tests are explicitly marked mandatory live integrations and remain
unrun; passing offline tests do not establish release or investor acceptance.
No production code, live database, model, network or server was touched.

Evidence-backed stale assertion repairs:
- Legacy brief/readiness queues explicitly route to the shared analyst workflow.
- Default preparation model is local; old migration must not restore hosted Claude.
- Room review advances to mandatory content review before material drafting.
- Retired compilation and confirmation routes return 410, with no memo/artifact
  writes and no changed stored historical approval.
- Historical document filtering/latest reads use real test sessions and check
  unauthenticated and cross-tenant denial. Effective teaser approval remains withheld.
- Offline concurrent review tests use real isolated session/CSRF fixtures. Their
  original race/CAS/audit assertions remain intact.
- Deterministic analytics rerun still produces and persists actual synthetic chart
  files under pytest temporary storage.

Live boundary: `live_integration` marker and `--run-live` opt-in. The three legacy
live API modules and the exact subprocess uvicorn upload test are registered;
ordinary TestClient and mocked transport checks stay in default offline coverage.
Opt-in does not establish environment readiness or authorize external/private work.

The complete physical-plan test module passes with the targeted selection. The
full-suite historical-request mismatch was not reproduced; no production change
or weakened request equality assertion was made. Earlier bare python3 collection
lacked pptx; the recorded result uses the root environment with existing packages.
