# Financial projections: company models and estimated scenarios

30 September 2026. Extension to the [delivery roadmap](LOCAL_TO_CLOUD_RELEASE_PLAN.md).
The user supplied a company projection workbook and explicitly requested that
the product understand company models and also build projections from estimates.
This document plans that capability; it does not create a forecast, recalculate
the supplied file or certify its financial logic.

**3 October scope correction:** financial analysis still starts with a room,
but an investor projection XLSX is conditional. If a company supplies a model,
preserve and assess it before using any figures as validated forecast facts.
Generate a new model only on the user's explicit request and when sufficient
reviewed current assumptions and operating evidence exist. Intro/pitch decks
and the investment memorandum remain required; they may disclose missing or
unvalidated financial inputs without inventing a forecast. No forecast claim,
financial chart or release approval can rely on an unresolved workbook.

**Implementation checkpoint, 1 October 2026:** read-only exported-XLSX inspection
and bounded cell/range lineage are implemented, including cross-sheet and hidden
sheet references, cycle detection and explicit unknown findings. This is only part
of P1/P2 below. `calculation_status` remains `not_run`; the installed private
LibreOffice conversion/UNO path failed qualification. P3–P6 and financial release
review remain open. See handoff §§48–49 and §55 for evidence.

**Release requirement added:** the [local-to-cloud plan](LOCAL_TO_CLOUD_RELEASE_PLAN.md)
requires validation of final exported XLSX/PPTX/DOCX/PDF files before submission.
No unresolved formula errors are permitted anywhere in a delivered workbook,
including hidden sheets. Original source files stay unchanged and separately
archived; a broken source does not become a validated deliverable by hiding cells.
The final download endpoint must enforce a passing exact-file release manifest.

Projection analysis is an automatic stage of the deal-room workflow. It combines
authorized room records with relevant public KB benchmarks locally, without
publishing room-derived facts back into the public KB. Every forecast driver
needs a traceable source, historical calibration or explicitly documented rationale.
Unsupported hypothetical assumptions remain illustrative internal drafts and
cannot be labeled data-backed in a released investor package. New uploads or
assumption revisions update only dependent calculations and artifact sections.

## 1. Product contract

Support three distinct workflows:

1. **Understand a company-supplied model.** Explain its period/units, operating
   drivers, formulas, assumptions, outputs and missing dependencies. Answer
   questions with workbook/sheet/cell citations and calculations.
2. **Challenge and adapt that model.** Keep management's original intact. Create
   separately versioned analyst scenarios, explain changed assumptions, and show
   effects on revenue, earnings, cash and financing requirements where supported.
3. **Build a model when one is absent.** Propose an appropriate operating model,
   collect assumptions and produce an editable formula-driven XLSX. Label it as
   an analyst estimate or illustrative scenario, never management guidance or
   historical fact unless that origin is actually established.

When a projection is requested and supportable, deliver a supporting projection
XLSX, assumptions register, model review report and approved forecast snapshot
for intro/pitch/memo outputs. The projection is an optional fourth supporting
artifact, not merely a financial slide.
Every displayed forecast identifies scenario, model version, forecast date,
currency/scale and actual-versus-estimate status.

“Understand thoroughly” means trace the selected financial outputs back to their
inputs, explain the business meaning, recalculate supported mechanics, identify
uncertainty and demonstrate input sensitivity. Reading all text or producing a
plausible summary does not satisfy this requirement. Coverage must be reported;
unsupported dependencies prevent claims of complete understanding.

## 2. What the supplied sample tells us

A read-only local OOXML inspection found 14 worksheets, five hidden sheets,
3,008 formula cells, five defined names, 1,407 formula cells containing cross-sheet
reference syntax, 104 cached error cells and one formula cell without a stored
value. No external-link parts, VBA project or connection part were observed.
Cross-sheet syntax counts are not a completed dependency graph. Cached errors
are observations about stored results, not a diagnosis of root causes or proof
of current recalculation failure.

No cell values, sheet names, formulas or financial narrative were emitted to the
hosted assistant. The workbook was not modified, executed, recalculated, uploaded
or copied into the repository. Its filename indicates an Oct-22 to Sep-23 model
in INR millions; the implementation must verify dates/units from workbook
evidence, preserve that historical forecast vintage and never treat it as a
current forecast or actual results simply because those dates have passed.

At the initial planning checkpoint, `agents/core/ingestion_agent.py::ingest_excel`
used cached values only. The §48 implementation now retains a separate bounded
OOXML inventory of formulas, caches, hidden sheets, names, stored errors and
unsupported features alongside cached-value citation blocks. It does not yet
construct a complete dependency graph or qualify financial semantics. Official
[openpyxl reader documentation](https://openpyxl.readthedocs.io/en/stable/api/openpyxl.reader.excel.html)
distinguishes cached values from formulas; [openpyxl does not evaluate formulas](https://openpyxl.readthedocs.io/en/stable/simple_formulae.html).
The recalculation gap remains: synthetic LibreOffice CLI round trips recalculated
changed inputs and preserved formulas/hidden sheets, but private sandbox conversion
failed, and the bundled Python/UNO executable failed code-signature verification.
These diagnostics used generated fixtures, not the supplied company workbook.
Explicit UNO `calculateAll`, destination Excel parity and model review remain
release blockers; there is no private-runtime sandbox bypass.

**1 October private Toffee read-only checkpoint:** The original workbook hash
was unchanged. An improved bounded static tracer resolved 3,768 cell-reference
edges, including simple defined names; dependency coverage remains partial
with 23 unresolved reference formulas. The exact source contains 104 stored
formula-error cells, 22 formulas with broken references, two broken defined
names and one missing formula cache. No private recalculation was run. The
ignored local report is `runtime_qualification/toffee_workbook_2026-10-01.json`
and contains counts and a hash, not cell values or formulas. The source
projection is **blocked**, not a validated forecast. Do not convert its
historical Oct-22–Sep-23 periods into actuals based on elapsed dates.

## 3. Architecture

```text
Private workbook / approved operating inputs
  -> immutable original + safe inventory
  -> formula and cached-value representations
  -> cell dependency graph + financial-semantic mapping
  -> locally reviewed assumptions and model specification
  -> isolated spreadsheet recalculation / approved calculation engine
  -> reconciliation + scenario comparisons
  -> local explanation and reviewer approval
  -> editable XLSX + versioned forecast facts for decks/memo
```

### Ingest the workbook as a model, not flattened text

Retain workbook hash, sheet identities/order/visibility, cells and types, formulas,
stored values, number formats, row/column labels, merged ranges, named ranges,
tables, comments, date system, calculation settings and relevant chart bindings.
Hidden sheets remain part of analysis but are not automatically exposed in
investor outputs. Formatting is a clue to meaning, never proof of an input's
origin or approval. Instructions inside cells/comments are untrusted source data.

Build a graph for direct references, ranges, names and supported structured
references. Track formula patterns to find overwritten formulas and inconsistent
period copies. Dynamic references, circular calculations, external dependencies,
array formulas, data tables and unsupported functions need explicit coverage
states. Do not claim an exact dependency graph from a regular-expression scan.
Compute output-specific dependency closure: an unsupported irrelevant area need
not block an unrelated supported output, but every dependency of that output
must be accounted for.

Initial support is bounded `.xlsx` models with ordinary formulas and declared
units/periods. Macros, Power Query, data-model measures, add-ins, external workbook
refresh and intentional circular models are compatibility cases, not promised
MVP support. Inventory without executing them. Never update external links or
run macros, embedded code or instructions from the file. Protected/encrypted or
unsupported inputs produce a specific request for an accessible compatible copy.

### Separate model interpretation from calculation

The local LLM maps labels/ranges into candidate financial concepts, explains
formulas and proposes assumptions/model structure. A reviewer confirms ambiguous
items such as gross versus net revenue, the actual/forecast cutoff and cost bases.
Use retrieved schedule fragments plus dependency context, not a single prompt
containing the whole workbook. Exact formula text remains available locally.

A spreadsheet engine evaluates imported formulas. The initial choice is LibreOffice
headless with explicit UNO recalculation, tested during L0/L1 before L2 depends
on it. Use openpyxl to retain formulas/cached values and author supported XLSX,
not to evaluate formulas. Compare representative results against a trusted
recalculation in the company's intended Excel environment when available. Store
engine/version/settings and recalculation time. Keep the original and original
cached results separate from the recalculated copy. A changed cached result is
not automatically evidence of a company error: engine compatibility, links and
iteration settings can differ.

For generated forecasts, compile a typed model specification into a restricted,
supported set of spreadsheet formulas and deterministic financial calculations.
Do not run model-generated Python, VBA or arbitrary scripts. Calculation results
come from the engine; the LLM cannot substitute its own arithmetic. Verify exported
XLSX recalculation after save/reopen and at least one meaningful input change.

### Private storage and caching

Workbook contents, dependency graphs, assumptions, model questions, scenarios
and narratives are private. Keep them in the private deal store/artifact area,
not in public ES indices, public result caches or hosted API requests. Public
benchmarks can be imported inward after rights/source review. A benchmark request
must not disclose the company's private figures or business plan.

Cache parsing by workbook hash/parser version; dependency analysis by formula
graph/version; calculation by workbook/model hash, scenario, engine/settings and
assumption revisions; explanation by the exact relevant facts/model contract.
An assumption change invalidates downstream forecasts and affected document
sections, not the whole public research corpus. Source/actuals changes invalidate
dependent comparisons and approvals. Protect temporary recalculation files and
restrict renderer/model network access under local milestone L1.

## 4. Financial meaning and assumptions

Add these records to the roadmap's common contracts:

| Record | Required information |
| --- | --- |
| WorkbookRevision | Original hash, private location, vintage, date system, engine/calculation status and compatibility coverage |
| CellEvidence | Workbook/sheet/cell or range, formula, stored/recalculated value, labels, number format, units and origin |
| ModelMap | Schedule roles, period grid, actual/forecast cutoff, business definitions, dependency coverage and reviewer decisions |
| Assumption | Driver, value/range, units, period, source/rationale, supplied/derived/proposed origin, owner, approval and uncertainty |
| Scenario | Base/downside/upside label, active assumption revision, model revision and recalculation record |
| ForecastSnapshot | Metric/entity/period/value/unit, scenario, dependency references, estimate class, calculation and review versions |
| ModelFinding | Affected output/range, formula/accounting/assumption issue, severity, supporting evidence and resolution |

Keep reported actuals, company projections, historical calibrations, external
benchmarks and analyst assumptions distinct. Approval to use an estimate does
not turn it into an actual. An elapsed forecast month becomes actual only when
new actual records are supplied and reconciled. Preserve the old forecast for
forecast-versus-actual analysis.

Interpret units at the relevant range: INR millions, INR, counts and percentages
may coexist. Preserve the original scale and normalize explicitly; do not
double-scale. Honor the stated monthly/quarterly/fiscal calendar rather than
assuming a twelve-month October–September window is an Indian fiscal year.
For aggregates, sum period flows, take appropriate closing stock balances and
recompute ratios from matching components. Missing is not zero.

## 5. Building projections from estimates

Start with the business model and available inputs. Defaults for a newly created
model: 12 monthly forecast periods, an explicit start date and actual cutoff,
base/downside/upside scenarios when inputs support them. Preserve an imported
model's original horizon. Longer horizons and quarterly/annual summaries are
optional extensions; assumptions remain date-specific.

Use a driver-based build, not a flat growth percentage pasted across every row.
Examples to select and verify, not universal company facts:

- Subscription business: starting customers, additions, churn, price/mix and
  billing/recognition timing.
- Transaction platform: transactions or volume, fee basis, take rate, refunds,
  incentives and principal-versus-agent revenue treatment.
- Product business: units, realized prices, returns, variable costs, inventory
  and collection/payment timing.
- Service business: productive capacity, utilization, realized rate and hiring.
- Insurance-related business: first establish whether the company is an insurer,
  broker, distributor or technology provider. Premium flows do not automatically
  equal company revenue; risk, commission, refunds and cash ownership differ.

Build payroll from headcount/hiring dates and compensation assumptions; distinguish
fixed/variable/one-time opex; model capex/depreciation and working capital where
supported. Start with operating drivers, P&L and a cash roll-forward. Add a fully
linked balance sheet only when opening balances and required schedules exist.
Never manufacture opening balances or financing plugs to make statements balance.

Assumption priority: company-provided plan/constraints; calibrated comparable
actuals; relevant cited public benchmarks; then explicit analyst hypotheses.
The local model may propose hypotheses or ranges with explanations. If there is
no defensible basis, show a required input or an explicitly illustrative scenario.
Do not label an arbitrary figure a benchmark or a statistical confidence interval.
Record benchmark differences in stage, geography, product and period.

Require analyst review of material proposed drivers before forecasts are used in
review-ready investor materials. Run draft estimates before review if helpful,
but watermark them and retain unapproved-driver status. Management can approve
or replace assumptions; preserve who supplied each version. Keep “management
case” distinct from analyst base/downside/upside.

Use one authoritative scenario selector and one calculation build for generated
models. Active assumptions feed that build; actuals stay fixed. Scenario comparisons
must contain separately calculated results. If comparing captured snapshots,
label each scenario/run time and mark them stale after assumption changes; never
show three copies of the currently selected case as a scenario comparison.
Keep independent check areas terminal: calculations/assumptions must not depend
on check outputs. Application release policy reads validation results separately.

Estimate cash exhaustion and financing need from the dated cash schedule and a
declared minimum-cash policy, not just average burn. Distinguish funding needed
before financing from assumed funding inflows; an assumed raise cannot hide the
underlying shortfall. Scenarios can vary timing, growth, margins, hiring and
collections coherently. Test supported sensitivities and explain causal changes
without claiming forecast certainty.

## 6. Questions the system must answer with evidence

- Which assumptions explain the projected revenue growth, and where are they set?
- Which inputs were supplied by management, calibrated from actuals or estimated?
- Why does profit differ from cash generation in this period?
- What changes if growth slows, pricing changes or collections take longer?
- Which month falls below the approved cash threshold under each scenario?
- Which output depends on a missing input, stale value or unsupported formula?
- What changed from the prior forecast, and how does it compare with later actuals?

Answers cite the specific workbook revision and ranges, and distinguish traced
facts, deterministic calculation results and model interpretation. “I cannot
determine this from the supplied model” is an acceptable supported answer.

## 7. Projection milestones P1–P6

These are the detailed financial work items within local L2–L5. Deck styling
belongs to L3; transaction/compliance acceptance is part of L4/L5 and final C2.

| ID | Scope and demo | Acceptance gate |
| --- | --- | --- |
| P1 | Safe workbook inventory and formula/value ingestion | Original unchanged; visible/hidden sheets, formulas, names, dates and error states retained; macros/external refresh never executed |
| P2 | Dependency and financial-model interpretation | Selected headline outputs trace to all supported inputs; unit/period/actual-forecast mapping reviewed; unresolved dependencies explicitly block affected claims |
| P3 | Recalculation and model review | Engine parity within declared per-metric tolerances; input-change/save-reopen tests; formula and accounting findings distinguished; no false PASS from cached values |
| P4 | Estimate-driven model generation and scenarios | Editable formula-based XLSX, approved assumptions, genuine case differences, unchanged actuals, reconciled supported P&L/cash schedules |
| P5 | Forecast snapshot into all documents | Exact same approved scenario/metric/period in XLSX, decks and memo; changed assumptions invalidate dependent approvals and snapshots |
| P6 | Held-out workbook/forecast acceptance | Independent reviewer verifies model explanations and scenarios on at least five differently structured workbooks; unsupported cases fail explicitly |

Dependencies: P1 after L0/L1; P2 after P1 and the early local extraction/
reasoning feasibility screen; P3 depends on the L0/L1 engine compatibility test;
P3 after P2; P4 after P3 and a reviewed model specification; P5 after P3 and the L3
artifact interfaces, with generated forecasts requiring P4; P6 after P4/P5.
Include these acceptance cases in L5 and repeat them for the final cloud model at
C1/C2. The early intro-deck slice can omit unsupported forecasts.

Acceptance, supported-feature coverage and independently reviewed outputs determine
readiness. Timeline estimates have been removed at the user’s request. Full support
for macros, external data models or every Excel feature remains a separate scope.

## 8. Acceptance corpus and release gates

Use the supplied workbook as a private compatibility case, never a committed
fixture. Create synthetic structural analogues for automated tests and additional
authorized models for held-out review. Include hidden schedules, stale/missing
cached results, range-unit changes, broken references, hardcoded overrides,
cross-sheet dependencies, different calendars, absent actuals and unsupported
dynamic/circular features. Original failure evidence stays intact.

For each supported output, verify formula lineage, independent arithmetic,
period/scale, scenario identity and business definition. Compare original cached
versus recalculated results without automatically treating either as ground truth.
Use declared absolute/relative tolerances appropriate to the unit; compare IDs,
dates and counts exactly where required. No universal currency tolerance.

Test meaningful driver changes in disposable copies and verify expected direction
where the business equations imply one. A scenario test must exercise later
periods, not only the first month. Distinguish intended one-off adjustments from
accidental formula overrides. Preserve source-workbook layout/features in narrow
edits; generated models should have readable inputs, builds and outputs.

Gate investor publication on: material assumptions reviewed, affected calculations
supported/recalculated, no unresolved material formula/accounting errors in the
selected outputs, citations complete and consistent forecasts across artifacts.
A forecast's successful calculation does not establish commercial plausibility.
Reviewer acceptance and explicit estimate labels remain necessary.

Next implement selected-output dependency closure, including defined names,
structured/3D references and explicit unsupported dynamic cases. Verify units,
periods, actual/estimate status and formula meaning with workbook evidence. Qualify
private recalculation on disposable copies with changed inputs, save/reopen,
independent arithmetic and a held-out corpus before accepting P3. Then build and
validate generated scenarios and consistent exhibits across the exact exported
files. Preserve source workbooks and failed results; cached values alone cannot
make a release check pass. No company-specific assumptions or forecasts have been
fabricated by this planning work.
