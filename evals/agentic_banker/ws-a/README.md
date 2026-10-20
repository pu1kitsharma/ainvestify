# WS-A local workbook tools checkpoint

15 October 2026. Synthetic software qualification only; no financial or investor acceptance.

Implemented `tools/v1` observations with exactly `version`, `ok`, `tool`, `result`,
`errors`. Error entries carry `code` and `message`. `WorkbookTools` exposes
add_sheet/write/name/style/comment/read/trace/recalc. Call trajectories retain
`call` (tool, args, kwargs) and `observation` in sandbox-local JSONL.

Files and trajectory paths resolve inside a caller-provisioned private sandbox;
path traversal and escaping symlinks fail. Existing workbooks require explicit
resume, and a source is copied to a distinct new destination. Original files stay
unchanged. Saves use same-directory atomic replacement. Input matrices must match
bounded ranges, retain literal agent-authored formulas, and do not supply any
financial structure or defaults. Source comments, styling and defined names are
explicit agent actions. Tenant authorization belongs to the caller.

The bounded evaluator handles arithmetic, A1/cross-sheet references and SUM.
It detects cycles, stored errors, division errors and unsupported formulas, including
hidden sheets. Results are diagnostic observations only; it never writes formula
caches or claims Office qualification. Trace coverage is syntactic A1 only.
No Python formula package is installed locally. The LibreOffice backend explicitly
fails unavailable; no process is started. Full formula coverage, named/structured
references, qualified final recalculation and financial acceptance remain open.

Verification: root `.venv/bin/python -m pytest tests/tools/test_workbook_tools.py -q`
passed **4 tests**. Cases cover a scripted synthetic workbook, saved-file formulas,
comments and style, two-cell arithmetic dependencies, cross-sheet SUM, hidden-sheet
errors/cycles, source-byte preservation, trajectory shape, sandbox paths/symlinks,
existing-file protection and bounded ranges. No model invocation, downloads,
private reference access, runtime restart, cloud operation or spend occurred.

## Read-only document tools

`DocumentTools(root, tenant_id=..., deal_id=...)` exposes pages/text/tables/
chart_series/xlsx_read/page_image. PDF/PPTX observations reuse the existing native
manifest parser, including source SHA256, exact native unit hashes and page/slide/
cell locators. XLSX retains formulas, stored unverified caches, hidden state and
cell-value/source hashes. Empty cells retain their requested coordinates.

Files are session-pinned on first access and can additionally be bound with
expected_sha256. Changed bytes fail even when a caller supplies the new hash.
Byte, expanded package, page/slide, cell and serialized output budgets fail
explicitly; there is no fabricated truncation or inference. Native PDF tables
and chart caches remain unverified observations. External dependencies are never
fetched. page_image explicitly reports its unqualified backend rather than
fabricating a render. Document tools append local call/observation trajectories.

Combined synthetic verification: root `.venv/bin/python -m pytest
 tests/tools/test_workbook_tools.py tests/tools/test_document_tools.py -q`
passed **8 tests** in 0.28 seconds. Synthetic PDF, native PPTX table/chart,
XLSX formulas/blanks/caches, changed-file hash rejection and budget errors are
covered. This is bounded software-tool coverage, not semantic financial quality,
complete document understanding or final artifact release qualification.

## Independent hardening review

16 October 2026. Found and fixed nonfinite-input logging escapes, partial
in-memory mutations after illegal cell content/save errors, missing source-XLSX
allocation bounds and uncaught audit-write failures. Mutation calls now snapshot
and restore workbook state on exceptions and fail before mutation when audit
storage cannot be opened. Audit failures are structured errors. Rejected NaN and
Infinity inputs remain explicit tagged diagnostics in strict JSONL.

Source and saved XLSX packages now have compressed-byte, expanded-byte, package
entry and actual-cell-count gates before loading/replacement. External formulas
in copied source files are rejected by the evaluator before dependency traversal.
Final saved-file replacement stays atomic. Document log failures also return
structured observations.

Focused verification now passes **13 tests** in 0.31 seconds. New tests exercise
illegal second-cell content rollback, nonfinite JSONL, audit-storage failure,
source bytes/cells bounds, external copied formulas and failed-save rollback.
PDF/PPTX parsing still runs in-process; source and output bounds do not establish
a hard OS memory/time limit for arbitrary malicious parser inputs. Process-level
resource isolation remains a production qualification requirement.
