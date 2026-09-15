# Preparation error recovery — 15 September 2026

The reported screen showed `Local generation failed (AttributeError)` although the live Paasa workspace already contained nine complete sections from job `automation_d00ca4a2fb2b`. No new model run was needed.

Two defects were addressed:

- Operations and Dashboard stopped polling after failure, while global focus refresh was disabled. Both now refresh saved work on focus/reconnect and poll visible failed/interrupted work every five seconds, active jobs every two seconds, and other states every thirty seconds. These are read-only requests; they do not retry generation.
- `preparation_contexts` assumed every fetched page had the recently introduced `content_blocks` attribute. A collector regression reproduced the `AttributeError`. Older page objects now fall back to their complete text, preserving qualifications; existing bounds still explicitly omit oversized unsplittable text.

Unexpected worker failures now record exception type and stack locations in local logs and the saved failure event. Source text, model payloads and exception values are excluded. A regression verifies that failed refreshes retain evidence and the existing pack without extra model calls.

The historical exception's precise origin cannot be established: its worker discarded the traceback. The missing-field exception and stale-screen behavior are reproduced defects, not a recovered historical stack trace.

Verification:

- The legacy-page regression failed with `AttributeError` before the compatibility fix and passed afterward.
- 135 focused backend tests passed; frontend production build and lint passed.
- The isolated browser regression verifies failed → completed synchronization on Operations and Dashboard without page reload or another preparation POST, along with the existing journey checks.
- After an idle, graceful API restart, a separate browser verified the actual Paasa draft: all three stages available, nine completed sections, founder/readiness content visible, no failure banner, and a successful export.
- The saved-work API read took 70.991 ms. This measures retrieval, not fresh generation.
- No new inference calls. All 31 workspace rows remained byte-identical, including revision 1204 and the original completed job.

Exact results and implementation hashes: [verification.json](verification.json). This fixes runtime compatibility and display synchronization; it does not change the earlier content-quality acceptance findings.
