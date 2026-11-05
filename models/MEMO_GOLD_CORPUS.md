# Memo source author, rationale repair and reviewer corpus

The current 8/2 synthetic teaching seed and Toffee headline examples are **not**
gold data for memo writing or review. The headline builder splits slides from
one company across train and holdout; that score does not measure generalization
to a new company. Do not use the private Toffee diagnostic or failed model
responses as accepted targets by default.

`scripts/build_memo_gold_sft.py` is an intake and export guard for the current
`memo-content-review-v1`, `memo-content-repair-v2` and
`part-a-components-v13` source-local author contracts. It does not
write target answers, judge whether an answer is true, train a model, or verify
that named reviewers are qualified. Those decisions belong to independent
human reviewers. The exporter requires two distinct reviewer IDs, approved
rights, a review timestamp, exact source-set lineage, and one of three explicit
splits. It rejects any company or underlying evidence family crossing splits.
Validation and test remain untouched during tuning.

## Record format

Keep private-derived reviewed JSONL, exports and adapters in an approved private
directory **outside Git**, and supply that existing directory as `--private-root`.
Ignored checkout paths are historical locations, not approved destinations for
new private training derivatives. Public/synthetic guard fixtures retain the
legacy `models/data/` path for compatibility.
Each line is one JSON object:

```json
{
  "case_id": "opaque-unique-id",
  "company_key": "stable-opaque-company-id",
  "evidence_family_ids": ["stable-opaque-document-family-id"],
  "split": "train",
  "task": "memo_content_review",
  "source_bundle": ["complete frozen Source objects, in recorded order"],
  "input": {"contract": "memo-content-review-v1", "...": "exact frozen local request"},
  "target": {"...": "independently adjudicated answer in the production schema"},
  "provenance": {
    "rights_status": "private_training_approved",
    "source_set_digest": "64-character lowercase SHA-256 from the frozen request",
    "sector": "sector label used for coverage reporting",
    "reviewer_ids": ["reviewer-one", "reviewer-two"],
    "reviewed_at": "2026-10-08T12:00:00+00:00",
    "adjudication": "approved"
  }
}
```

`rights_status` must specifically approve **model training**; permission to
index or summarize a public source does not imply training permission.

Use `memo_content_repair` with the exact `memo-content-repair-v2` request for
rationale-repair author examples. This is narrower than full-memo drafting.
The review target chooses a typed verdict, exact sentence ID,
source ID, and rationale. The repair target contains model-authored replacement
sentences tied to exact offered choices, plus a recommendation when repairing
`recommendation_reason`. Software checks shape, numeric scope and citations;
reviewers must check entailment, attribution, entity, period, causal reasoning,
and whether the decision actually follows. Include supported controls and
unsupported/insufficient cases, disagreement adjudications, financial gaps,
and missing chart/table evidence. Preserve the source version and negative
examples; do not silently turn an uncertain case into a positive label.

Each record includes the complete `source_bundle`; the exporter recomputes its
production digest and verifies the offered passages/quotes against it. Repair
records also require `base_memo`, whose digest must match the input before the
actual runtime projection and full memo validation run. `memo_source_author`
uses the runtime source-local schema and component-specific instruction; it
teaches an assertion and bounded analysis sentences, not full-memo composition.
Correction examples retain their exact retry instruction and request, rather
than pretending the model received a different prompt.

The `company_key` and `evidence_family_ids` are leakage controls, not company
aliases for inference. Assign all variants of one company and all copies of one
announcement or document family to a single split. A case may use multiple
families. Keep identifying content and private source text out of Git.

## Export and gate

```sh
PYTHONPATH=. .venv/bin/python -m scripts.build_memo_gold_sft \
  /approved/private/memo_gold/reviewed.jsonl \
  /approved/private/memo_gold/exports/run-001 \
  --private-root /approved/private
```

The output directory must be new. It contains `train.jsonl`, `valid.jsonl`,
`test.jsonl` in the local non-thinking Qwen chat format and a manifest of
hashes/counts. The manifest's `coverage_thresholds_met` is a sizing check:
at least 20 company identities, 50 distinct underlying evidence families,
three sectors, and
all three tasks in each split. It is **not** training authorization or expert
acceptance; `expert_review_verified` and `release_qualified` remain false.
Before any weight update, independently audit review identities and rights,
inspect a sample of exact source/target pairs, freeze the test split, and score
the untuned base on the held-out tasks. Record failures and disagreement, not
just an aggregate score. A tuned adapter must beat that baseline without
new critical errors before a production role changes.

The PDF chart/table reader is a parallel dependency: labels made from missing
evidence cannot teach the model to recover that evidence.

## Approved private material: populated candidate queue

The user approved private-source training preparation on 8 October. The local
queue at ignored `models/data/memo_gold/2026-10-08-private-candidates-v4/`
contains **46** distinct saved-model candidates from 195 attempts across 15
requests: 6 source-local author answers, 17 rationale repairs and 23 reviews.
All raw answers, source digests and schemas replay; invalid attempts and
historical prompts are recorded separately and duplicates retain their origins.
User source approval is recorded in `source_approval.json`. No target answer
was manually written or silently adjudicated. Toffee is one company; all its
candidate examples default to test, so this is not a cross-company train set.

`scripts/prepare_memo_training_candidates.py` prepares such a queue without
inference. Outputs are mode 0600 under a mode 0700 directory; originals and
runtime records remain unchanged. Claude Code implemented the generic
`training_disagreements` classifier from a sanitized prompt with file tools
disabled. In the imported reviews, 23 targets form 20 exact-input groups, with
zero mixed verdicts. This narrow result does not prove reviewer accuracy;
changed reasoning or source scope is correctly treated as a different input.
It also does not support calling the observed nonconvergence an exact-input
reviewer contradiction.

```sh
PYTHONPATH=. .venv/bin/python -m scripts.prepare_memo_training_candidates \
  /approved/private/memo_gold/new-private-queue \
  /approved/private/imported-diagnostics/approved-run \
  --private-root /approved/private \
  --source-root /approved/private/imported-diagnostics \
  --company-key opaque-company-id --sector sector \
  --approval-id recorded-user-source-approval --approved-on 2026-10-08
```

This importer keeps answers pending. A source-use approval is not a declaration
that every saved failed/repaired response is correct. The corpus needs reviewed
labels across additional companies and an untouched baseline before training
can demonstrate an improvement.

## 26 October imported-asset intake correction

`python -m scripts.audit_training_assets SOURCE_ROOT NEW_REPORT --private-root ROOT`
reads bounded JSONL assets and stages only hashes, row references, classifications
and gate results in a new immutable private report. It never changes a split,
copies a prompt/target into a training corpus, makes a model call or trains weights.
Reports contain no source passages, model answers, company names or raw errors.
Existing private storage must already have the intended operating-system access
controls; path validation does not confer source rights or configure Windows ACLs.

The complete imported archive has 74 JSONL files and 1,552 rows. The earlier
532-row memo subset contained 156 pending, test-only candidates and 376 exclusion
records. All 156 candidates pass source/runtime target checks; that result is
separate from substantive answer adjudication. None has approved review labels.
The additional 152 task-input cases have 52 train, 48 validation and 52 test rows,
all explicitly marked synthetic fixtures; their separate 152 scorer keys are
evaluation assets, not approved assistant targets. Duplicate archive versions
remain preserved, and held-out companies/documents are excluded from training.
There are currently **zero weight-update-eligible memo rows**. Importing models
and source-use approval cannot substitute for reviewed targets, frozen holdouts
or a compatible measured training runtime.

## 27 October renewed source permission and family audit

The user's new instruction authorizes local training source use for seven supplied
references. That permission is recorded independently from answer adjudication and
prior acceptance reservations. `python -m scripts.prepare_reference_training`
verifies imported original hashes, checks the archived original-source declarations
and emits an immutable outside-Git family ledger plus per-source review requests.
Unmatched references remain unassigned and unadjudicated; the tool does not assign
every future input to test. A substring in a filename never establishes identity.

For these seven actual inputs, five match archived originals byte for byte, and
all seven match exact original-source filename declarations in three existing
acceptance families. The two declaration-only matches retain unresolved version
status. No independent new training family was found. Their review packets request
version/evaluation reconciliation and explicitly prohibit training derivatives,
including layout-only derivatives of held-out files. Rights permission does not
turn a reference projection into a verified actual or a model answer into gold.

`python -m scripts.qualify_training_runtime` inspects package availability, local
model metadata, GPU capacity and packed tensor headers without loading weights.
The recovered MLX affine checkpoints require separately qualified offline unpacking
and exact Transformers architecture/tokenizer mapping before CUDA QLoRA. Header
estimates exclude activations, gradients and optimizer state; they are not capacity
acceptance. The CUDA trainer now selects FP16 when native BF16 is unsupported,
rejects explicitly unsupported BF16 and requires an existing local checkpoint with
`local_files_only=True`. It never downloads a missing model or silently trains an
unconverted MLX checkpoint. No weights were updated or production model changed.
