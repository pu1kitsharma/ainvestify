# Checkpoint 2 — local scripted tool session

16 October 2026. This checkpoint covers deterministic tools and their runtime
contracts. It does not qualify a model, financial forecast or investor package.

## Implemented and exercised

- All 21 supported tool names have explicit JSON schemas and fail-closed argument
  validation before effects. PDF/PPTX/XLSX aliases match role tool names.
- Runtime rejects malformed calls, missing or truncated completion markers,
  wrong returned model identities, empty final answers and repeated tool IDs.
  Concrete HTTP transport saves exclusive exact request/response **body** bytes
  plus hash manifests before parsing/effects. Fake sockets test these receipts;
  no real endpoint was invoked. Dict fixtures explicitly lack wire provenance.
- Pack exports publish one complete draft directory with member hashes and a
  manifest. Workbook references can be identity-checked against exact local
  bytes. Changed sources, export bytes and authoring logs fail verification.
- `scripts/qualify_agentic_tool_session.py` runs three roles using explicitly
  scripted fixture envelopes: six synthetic transport calls, zero actual model
  calls. It writes an XLSX with live formulas, two editable slides with native
  embedded chart data, and a DOCX draft. Host code commits the export after the
  role exercise. Replay reads exact files without rerendering or invoking tools.

No content here is company gold or a model-quality claim. Code supplies synthetic
fixture content only for this tool qualification; production company content
must still originate from recorded local-model responses.

## Recorded local exercise

Ignored evidence directory:
`runtime_qualification/agentic_banker/2026-10-16-checkpoint2/session-003/`.

- Session SHA256: `8bfaa3bad069b116739fc1e16ab82eeaa12b4ca3ed98cedd300e499240d0809d`.
- Export manifest SHA256: `1e4baa07d012166b7db14743bead38c11d953302a0213a90d78c7142b949b05c`.
- Replay returned `exact_bytes_verified`, `actual_model_calls: 0`,
  `rerendered: false`, `release: blocked`.
- Earlier session-001 and session-002 remain preserved. Session-001 predates the
  additional root authoring-log bindings and is not the final checkpoint record.

Reproduce in a **new** private output directory with:

```sh
.venv/bin/python scripts/qualify_agentic_tool_session.py --output /private/tmp/new-agentic-tool-session
```

Replay requires the independently recorded `--expected-sha256`; it does not trust
the colocated hash file as an authority. Existing output directories are refused.

## Regression work

Final frozen offline run:
`python -m pytest tests -q -ra --tb=short` — **3,513 passed, 20 skipped**,
16 warnings, 167.23 seconds. Raw local evidence:
`/private/tmp/deal-document-checkpoint2-final-pytest.txt`.
Focused tool/runtime/environment selection: **127 passed** in 0.94 seconds.
`git diff --check` passed. The final read-only room check retained 22 awaiting
input, three blocked, four cancelled, two queued jobs and zero active leases.

The 20 skipped checks comprise 12 explicitly opt-in live model/network/server
checks, one independently capability-blocked private-read isolation check, one
existing native Office canary and six existing native private-runtime checks.
These are unrun checks, not passed checks. Full release/G-READY remains open.

Four stale assertions now match the mandatory content-review phase, unauthenticated
legacy-route constraints and installed-local-model routing. Retired compilation
tests now require 410 with no artifact/memo writes. Authenticated historical
listing, tenant isolation, approval withholding and concurrency checks remain.
No production authentication or validation rule was weakened.

A prior intermittent physical-plan test regenerated PPTX bytes before comparing
an old frozen request; ZIP timestamps made those source versions different.
It now retains the original inventory. A deterministic timestamp regression
preserves exact request equality for original bytes and rejects different bytes.

Default pytest now reports audited live model/network/server checks as opt-in
mandatory unrun. The native isolation probe reports the exact macOS enclosing
sandbox denial as mandatory UNRUN; unexpected policy failures still fail.
The native security gate must pass on a qualified host before release.

## Open gates

General formula evaluation, hidden-cell financial reconciliation, isolated final
LibreOffice recalculation, formula caches, chart/prose numerical agreement,
PDF/Office visual parity, hard cancellation, production role orchestration,
training and investor acceptance remain open. Cloud deployment/spend and model
downloads remain deferred. Claude Code inference has not been started.
