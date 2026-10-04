# Private local attachment acceptance

`scripts/evaluate_private_acceptance.py` handles three user-supplied local inputs
(two PDFs and one XLSX) outside the deal, account, mandate, public KB and release
stores. It does not create a company profile or investor package. The operator
chooses a new output directory under ignored
`runtime_qualification/private_acceptance/` for each diagnostic.

## Phases

1. `prepare <intro.pdf> <pitch.pdf> <workbook.xlsx> <new-output-dir>` verifies
   regular files and size bounds, then parses them in a network-denied macOS
   sandbox. It retains original page passages in the private output, groups
   adjacent short pages without rewriting text, and records hashes/counts.
2. `run-one-pass memo_draft <output-dir>` freezes the complete PDF source bundle,
   local model profile and clock, then runs one 105-second local draft pass in
   the private sandbox. The filename-derived company label is explicitly
   unverified. Incomplete source coverage blocks inference.
3. `run-one-pass financial <output-dir>` verifies the original workbook hash,
   copies unchanged bytes into the isolated job, and runs one bounded local
   reconciliation pass. Cached values or a worker result never validate
   historical financials or a forecast.

Each pass preserves raw responses and returns only status, generic reason,
counts and private paths. A result always remains diagnostic and unreleased.
`resume memo_draft <output-dir>` continues the exact frozen memo request for at
most six total 105-second draft passes on historical profiles or eight on
frozen `memo-cards-v1` through `v7` profiles, or thirty on the source-local
`memo-cards-v8` through `v13` profiles, matching the production draft-phase cap; it never
changes an earlier response. The financial diagnostic cannot
resume through this command. Private passages, workbook
cells, formulas and model output must not be copied into logs, Git, hosted
models or the shared public KB. Failed runs remain evidence and are not reset.

## 4 October 2026 private checkpoint

The supplied three originals were parsed read-only in the isolated worker:
25 PDF page passages became 22 complete memo source units, with no oversized
passage. The workbook inventory found structural formula/cache/reference issues;
its one local financial pass blocked before inference. The local 9B memo draft
used all six production-aligned draft passes: two no-response time limits and
four answered component calls, with no schema error. The worker still reported
`needs_resume`, so the external six-pass cap blocks further continuation on
that exact version. No accepted memo, deck, financial forecast or investor
package resulted. All raw local responses remain in the ignored diagnostic.

The separate frozen memo-cards-v2 packet diagnostic retained the same 22
complete sources. Its local 9B bound two batches on exact replay. A third
batch stated a number/date absent from the source span selected by the model;
its one bounded correction repeated that gap. The two-attempt batch cap is
exhausted after four calls in two passes. The worker is blocked, with five
batches untouched. Earlier diagnostic roots and raw responses remain intact.

Packet-v3 later bound all 22 private source cards through eight local calls.
Source-local v9 and v10 memo authoring each exhausted one saved correction on
unsupported numeric text. V11 exhausted its correction on a spelled quantity
that was present in the selected exact quote, so its absolute numeric-free gate
blocked a source-supported statement. One installed, digest-pinned local 14B
comparison reused the exact v9 second-author task: numeric and process gates
passed, but the frozen 240-character reason limit rejected its 258-character
sentence. All results remain ignored private diagnostics, with no accepted
memo or investor package.
