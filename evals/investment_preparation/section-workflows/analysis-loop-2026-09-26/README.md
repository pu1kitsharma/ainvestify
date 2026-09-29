# Automatic analysis correction and Sonnet 5 — 26 September 2026

The user requested automatic correction after resetting quota, prohibited Opus,
and explicitly approved Sonnet 5 when the exact Sonnet 5.5 model was unavailable.
The Pro path requests and checks `claude-sonnet-5`. No company prose was written
manually. Public evidence only goes to the provider; private records stay local.
Concurrent API/deployment work is preserved. This is local verification, not
universal first-pass reliability or investment-quality acceptance.

## Final live state

| Company | Current analysis | Final recovery job | Time / calls | Download |
| --- | --- | --- | --- | --- |
| Arable | Published; 8 metrics, 3 conditional outlooks | `automation_bb66c0b1ddb5` | 47.026s / 3 | Analysis 200, founder 200 |
| GoCardless | Published; 1 metric, 3 conditional outlooks | `automation_757bb4fa6f73` | 74.867s / 4 | Analysis 200; historical founder 409 |
| CropX | Existing reviewed analysis; 7 metrics, 3 conditional outlooks | No new call in this loop checkpoint | Prior revalidation 24.051s / 1 | Analysis 200, founder 200 |

Arable and GoCardless reused saved drafts. These times exclude preceding failures;
**they are not first-pass generation times**. Final responses all reported Sonnet 5.
Arable's final three calls were patch, model-declared extra-key removal, and review.
The UI and downloads show reviewed work. HTTP 200 exports contain substantive
content without “not prepared” placeholders. GoCardless's separate older founder
pack remains unreviewed under the current contract and correctly returns 409.

## Retained failures and artifacts

- `arable-navigation-failure.json`: a search response violated the interpretation
  length limit. Shared navigation repair now reuses the observed search transcript
  in tool-free correction calls instead of repeating the search.
- `arable-checkpoint-loss-failure.json`: job `automation_a31f913f920f`, three
  automatic passes, 191.592 seconds / ten calls. An invalid source quotation in a
  reviewer response caused pass two to lose the candidate; pass three then rewrote
  it. Fixed by saving candidate provenance before rejection replay and repairing
  malformed reviews independently. Regression verifies only one writer call.
- `arable-patch-schema-failure.json`: job `automation_4d7e8fa8c1fb`, three automatic
  passes, 76.710 seconds / twelve calls, retaining the candidate. Repeated patch
  outputs added forbidden fields. Shared model-authored format cleanup now removes
  only exact model-selected schema-forbidden keys and replays original raw content.
  The live failure also records contradictory critic suggestions; these remain a
  model-quality limitation, not something retry counts can certify away.
- `arable-complete.json`: final recovery, original response/patch/format chain and
  approving review retained. The repair after the above code fix passed in one
  automatic pass; the successful run did not need a second pass.
- `gocardless-complete.json`: final saved-draft correction and independent review.
- `verification.json`: final read-only API/current metrics/download checks.
- Earlier failures and the successful fresh CropX draft from retained sources are
  retained in `../analysis-recovery-2026-09-26/`. That directory's verification
  predates the corrected export behavior; do not treat it as the final state.

## Limits and tests

Each analysis job has at most three passes of 120 seconds, six task calls and
8 provider requests. Cumulative usage is recorded/displayed. Stop on cancellation,
changed inputs, two unchanged checkpoints, quota/access/model errors or pass cap.
No silent fallback to Opus or API. Validated saved answers survive failed refresh.
The in-process worker is not a durable queue; a server crash may need resume.

155 focused backend tests passed. Frontend build and lint passed. Final shared
budget-message wording was adjusted to avoid falsely saying automatic continuation
was disabled; targeted checks cover that edit. Whitespace checks passed. No live
jobs remained at the final check. See [BLOCKERS.md](BLOCKERS.md) for the complete
known gap inventory, including numeric-candidate starvation that leaves GoCardless
with one metric card despite useful financial data in its prose.
