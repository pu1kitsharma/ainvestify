# WS-A2 analyst tool layer: evaluate, audit, bind

20 October 2026. Synthetic software qualification only. Nothing here establishes
financial, investor or Office-release acceptance. All tools are observation-only
`tools/v1` calls: they report, never repair a workbook or choose company content.

## What was added (`agents/tools/`)

| Module | Purpose |
| --- | --- |
| `formula_engine.py` | Pure-Python Excel-subset evaluator: `+ - * / ^ & %`, comparisons, cross-sheet/absolute/whole-column refs, defined names, Excel-table structured refs, array arithmetic inside SUMPRODUCT. Functions: SUM AVERAGE MIN MAX MEDIAN COUNT COUNTA PRODUCT SUBTOTAL ABS SIGN INT ROUND/UP/DOWN MOD POWER SQRT EXP LN LOG LOG10 FLOOR CEILING IF IFERROR IFNA CHOOSE AND OR NOT IS* INDEX MATCH VLOOKUP HLOOKUP SUMPRODUCT SUMIF(S) COUNTIF(S) NPV IRR XIRR XNPV PMT DATE EOMONTH EDATE YEAR MONTH DAY TEXT (basic formats) text functions ROW COLUMN. Iterative Tarjan evaluation: exact circular-reference detection (`#CIRC!`, with cell list and a closed path), no recursion limit on long chains, `#REF!/#DIV/0!/#NAME?/#VALUE!/#N/A/#NUM!` propagation. Volatile or unimplemented functions (OFFSET, INDIRECT, TODAY, XLOOKUP, ...) give `#UNSUPPORTED!` and are listed, never guessed. |
| `recalc.py` | Isolated LibreOffice recalculation of a cache-stripped copy (fresh 0700 profile, macros and link updates off, `OOXMLRecalcMode=Always`, Seatbelt no-network via `delivery.isolation.run_private`, timeout, output-size bound, refuses external/network formulas and unsupported package content). Compares every formula cell with the evaluator. Environment missing or isolation unavailable returns `status: UNRUN, mandatory_unrun: true` (tool error code `UNRUN`), never a pass. |
| `audits.py` | (a) hidden sheets/rows/columns/names and visible cells reading them; (b) range-width/stride audit; (c) unit/scale audit; (d) driver-growth double-count candidates; (e) balance-sheet plug candidates, totals check, zero-sum rows, sign patterns; (f) error root/propagation map; (g) hardcodes in formulas, constant-only formulas, literals inside formula rows; (h) monthly = quarterly = FY row-total reconciliation. |
| `claim_binder.py` | `bind_claims` / `bind_document`: every number in text binds to a supplied cell within its displayed rounding and unit/scale, with sign, up/down, CAGR-kind checks and derived growth/CAGR/ratio from series cells; `chart_workbook_agreement`: native PPTX chart series vs evaluated workbook (found, found only after rescaling, pinned range, cache vs embedded chart workbook). |
| `analysis.py` + `registry.py` | `AnalysisTools` and 14 new registry names: `fx.evaluate`, `fx.compare_cache`, `fx.recalc_libreoffice`, `audit.hidden`, `audit.range_width`, `audit.units`, `audit.driver_growth`, `audit.balance_sheet`, `audit.errors`, `audit.hardcodes`, `audit.reconcile_totals`, `claims.bind`, `claims.bind_document`, `chart.agreement`. The earlier 24 registered names and behaviours are unchanged (`analysis=` is an opt-in argument). Sources are sandbox-bound, byte-bounded and SHA-pinned like `DocumentTools`. |

## Tests (`tests/tools/`, synthetic only)

`test_formula_engine.py`, `test_audits.py`, `test_claim_binder.py`, `test_analysis_tools.py`,
`test_recalc.py`, `test_differential.py` (seeded random formulas vs LibreOffice) and
`test_toffee_private.py`. The last file auto-skips when the private workbook is absent and
asserts only structure (addresses, counts, rates); no private value, label or formula is in
the repository. `.venv/bin/python -m pytest tests/tools tests/runtime -q` passes.

## Measured accuracy (this machine)

* Synthetic seeded differential, engine vs isolated LibreOffice: 1,279 of 1,280 formula cells agree
  (8 seeds x 160). The one difference is IRR on a series with several sign changes, where the engine
  finds a root by bisection and LibreOffice returns an error.
* Private reference (`Toffee ...xlsx`, kept outside Git): 2,839 of 2,839 numeric cached cells and
  168 of 168 non-numeric cells reproduced (100 percent, 0 mismatches), 3,008 formulas evaluated in
  about 1.6 s, 104 genuine `#REF!` cells reproduced. The isolated LibreOffice run agreed with the
  evaluator on all 3,008 formula cells.

## Not covered (honest limits)

* A subset of Excel. No dynamic-array spill, XLOOKUP, OFFSET/INDIRECT, LET/LAMBDA, volatile functions, data tables,
  date serials before 1900-03-01 quirks, locale formats, full TEXT format grammar, or iterative-calculation mode.
  Excel itself is not run; LibreOffice agreement is parity evidence, not Excel qualification.
* Audits are heuristics ("candidate"). Unit audit needs readable labels; the range-width audit
  needs at least two sibling aggregation rows; the balance-sheet plug detector is structural and
  label based and can miss plugs routed through several sheets; the double-count detector needs a shared
  growth series and a multiplicative combination; reconciliation needs the caller to name the monthly,
  quarterly and FY column spans (repeated labels are reported ambiguous unless `explicit_rows` pairs them).
* The claim binder shows a number exists in the supplied table at the right scale, not that the prose or
  the source data are right. Years and tokens such as Q3, FY24, 5G are ignored by rule; small unit-less
  integers must be allow-listed or bound. Chart agreement needs native charts with cached values.
* No visual, PDF or PowerPoint rendering parity, no hard process cancellation, no real-model use, no training.
