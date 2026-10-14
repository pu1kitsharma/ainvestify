# Private financial evidence index

The financial index keeps complete workbook retention separate from the small
text-document diligence context. A workbook with hundreds of packets does not
become hundreds of flattened memo sources. This separation does not establish
financial understanding or permit forecasts to be released.

## Records and retrieval

`agents/research/financial_evidence_manifest.py` provides:

- `build_financial_manifest`: binds tenant, deal, document and original SHA-256;
  retains every nonempty cell, formulas, caches, number formats, ISO dates and
  hidden sheet/row/column flags. Its inventory also retains raw workbook
  date-system attributes, merged ranges and typed date observations, defined names,
  formula attributes, calculation settings, dependency edges and unresolved
  findings. No recalculation runs.
- Deterministic per-sheet packets and a cell-to-packet index. Every nonempty cell
  appears in one packet. An oversized cell remains retained; its packet reports
  incompatibility with the bounded source contract.
- `retrieve_financial_evidence`: resolves exact cell IDs, A1 ranges or packet IDs
  selected by the caller/local model. It includes supported dependency closure,
  explicit blank coordinates, missing dependency coordinates and unresolved
  findings. Bounds reject the whole retrieval instead of clipping evidence.
  Selected and excluded packet IDs stay visible.
- `financial_semantic_payload` and `financial_semantics_schema`: freeze an exact
  retrieved subset and local-model pin. Proposed financial concepts reference
  value cell IDs and literal label spans; the model cannot author new values.
- `bind_financial_annotations`: replays retrieval against the manifest and binds
  one unique recorded local-model response to its exact input, schema, raw hash
  and server-resolved installed model pin. Proposed reported/projected statuses
  require their own exact source-status label. Their meaning still requires
  independent review.

The server must obtain `expected_binding` and `installed_model_pin` from checked
private storage and local model inventory. These are trusted server arguments,
not fields accepted from a model or browser as proof of authorization. Existing
room association and original-byte checks remain required before construction.
All manifest files and their derivatives stay in tenant/deal private storage.
They must never be indexed into the shared public KB or sent to hosted inference.

## Meaning of status

Inventory completeness means all nonempty cells were retained. It does not mean
all financial concepts were understood or that the dependency parser supports
every formula. The initial financial status is `unreconciled`; actual-results
origin, currency/unit/period semantics and independent review remain unestablished.
Formula caches are observations from saved files. A missing cache is not zero.
Elapsed historical projection periods do not become actual results.

Model-declared `reported`, `projected`, `unreconciled` and `missing` are proposed
source interpretations. A missing field in a selected subset is an evidence
request, not proof of workbook-wide absence. Labels and values remain traceable
to original cells. No annotation grants reconciliation, actuals, professional
review, forecast approval or investor release.

## Room integration

`delivery/financial_evidence_stage.py` and the network-denied isolated
`scripts/private_financial_manifest_worker.py` now provide the private indexing
bridge. The stage reads only an original resolved from the canonical tenant/deal
upload subtree. It freezes adapter/job revision, request and original bytes,
then retains a manifest and exact-byte receipt. Ancestor/file symlinks, arbitrary
stage paths, foreign room bindings and changed derivatives fail closed.

The opt-in `room-v63-source-quotes` contract retains the stage record in the room
checkpoint before text-document source selection. The production default remains
`room-v62-explicit-topic-status`; the opt-in contract's local-model quality has
failed qualification, and no real room was activated under it this turn.
On an unchanged reopen,
`load_financial_evidence` checks original SHA, current workspace/job/revision,
request, source copy, adapter, receipt and manifest hashes without reparsing.
The room worker must resolve these arguments server-side and check access and
current originals. Text-document diligence consumes
the text-document inventory. Financial inference consumes exact workbook
retrievals separately; it must report unreviewed and excluded financial evidence.
Historical requests and failures must not be rewritten under this new structure.

The bridge supports up to three supplied workbooks per bounded indexing pass;
excess, missing, foreign or stale indexes block explicitly. Its source fingerprint
and model profile include the complete workbook inventory digest even when the
text selector chooses no financial passage. Later source coverage/core stages
receive the unassessed financial scope. Initial memo-cards-v13 remains
narrative-only: this bridge does not add financial semantic inference to those
frozen initial authoring payloads. Internal index paths stay out of public job
serialization; the frontend receives only safe retention/status counts.

Core documents can disclose incomplete financial inputs; supported financial
tables/charts require a reviewed, version-bound financial dossier and the
existing exact-file release checks. Existing arithmetic, spreadsheet-engine
qualification, financial-owner and compliance gates remain applicable.

The focused synthetic checks cover complete inventories above 25 packets,
formula-cache and hidden-cell retention, exact dependency retrieval, scoped
integrity, oversized evidence, unsupported dynamic references and recorded
annotation provenance. These checks do not establish live local-model semantics,
Toffee-level content, financial qualification or regulatory approval.

## Read-only qualification checkpoint — 13 October 2026

The combined stage/manifest suite passed 20 checks: 11 stage checks and nine
manifest checks, with 15 existing dependency warnings. A separate original-file
run through the isolated parser retained 3,596 cells exactly once in 786 richer
packets, including 3,008 formulas, 97 date observations, 14 sheets (five hidden),
five defined names, 3,768 dependency edges, two merged ranges and one missing
formula cache. The earlier 314-packet intake archive remains unchanged.

The original and its private source copy were byte-identical before/after the
1.726-second parser check. Exact range retrieval passed. The ignored report is
`runtime_qualification/private_acceptance/2026-10-13-workbook-manifest-v1-ubpvzprf/parser_check_report.json`.
Dependency coverage remains partial, financial status unreconciled, semantic
coverage unassessed and financial validation unestablished. No model call,
recalculation, financial interpretation or investor release occurred.
