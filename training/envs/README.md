# Offline modelling reward contracts

This initial slice supplies E1–E7 deterministic scoring plumbing. It neither
collects filings nor creates an answer key, company answer, financial model,
training trajectory or adapter. Every reward applies only to observations supplied
by the caller. A declared `live_formulas: true` is not verified workbook inspection.
Artifact-bound extraction and independent financial/semantic adjudication are
required before these rewards may select real training examples.

The prediction and answer-key files are JSON arrays. For example, an entirely
synthetic E4 key is:

```json
[{"case_id":"synthetic-reconciliation","environment":"E4","checks":{
  "flags":{"status":"available","kind":"set","expected":["units","comparator"]}
}}]
```

A corresponding prediction is:

```json
[{"case_id":"synthetic-reconciliation","environment":"E4","observations":{
  "flags":{"status":"observed","value":["units"]}
}}]
```

Run locally with `python3 scripts/evaluate_agentic_banker.py --predictions
predictions.json --answer-key keys.json --output new-report.json`. It writes a new
mode-0600 report and refuses to overwrite existing evidence. Keep private keys,
predictions and derivatives under approved ignored private storage. No reference
findings or private financial numbers are shipped here.

`CONTRACTS` lists mandatory dimensions per environment. Each key dimension must
have `status: available` and one of:

- `kind: numeric`, finite `expected`, optional nonnegative `absolute_tolerance`;
  units and periods must be normalized by the independently reviewed key author.
- `kind: exact`, a scalar `expected` (types must agree).
- `kind: set`, unique expected string IDs; reports precision, recall and F1.

A key can instead declare `status: unsupported`. A prediction observation uses
`status: observed` plus `value`, or explicit `missing` / `unsupported`. Missing
cases remain in the denominator. Missing keys, unsupported checks and unobserved
checks receive zero reward; they cannot silently pass or disappear. Checks within
an environment and cases within a report receive equal weight. Forecast reward is
a binary tolerance check, not a calibrated forecasting loss. The E6 banker critic
is always unsupported; comparison-direction declarations are not semantic review.
No score is investor acceptance, financial approval or release qualification.

`validate_splits` requires explicit public-training rights approval and `private:
false`. All train/valid/test splits must be populated; company, sector, underlying
evidence family and source SHA256 must be disjoint across them. Optional explicit
private holdout company IDs are excluded from the entire public corpus. Caller IDs
are normalized for case/whitespace only; independent entity resolution must catch
aliases. Caller hashes are checked structurally, not recomputed from originals.
The manifest reports the existing 20-company / 50-family / 3-sector coverage gate;
a synthetic fixture does not meet it. It does not certify adjudication or source
rights. Public source candidates remain disabled pending individual rights review.

The injectable `training.expert_iteration.run_iteration` now exercises bounded
sample → score → filter → trainer declaration → held-out evaluator plumbing. It
requires `dry_run=True`; real training is unsupported. Callbacks are trusted caller
code, not sandboxed. Samplers and held-out evaluators see only task input objects,
not answer keys; private/unapproved/leaking rows fail before any callback. Training
callbacks receive train-split selections only. Raw malformed predictions and all
rejections survive in a new immutable output directory. Trainer claims are stored
as unverified declarations and never set `weights_trained` or `adapter_verified`.

The iteration preflight additionally rejects identical canonical task input across
splits even when top-level `case_id`, `company_key` or `split` labels change.
Canonical JSON sorts object keys; repeated tasks within a single split remain
allowed. This catches exact content duplication; it does not detect paraphrases,
source overlap, nested relabeling or differently formatted equivalent documents.
