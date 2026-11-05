# Deal documents v2 plan

Status: proposed 30 October 2026. Contains no deal data, so it can be shared with any reviewing agent.
Evidence: measured from the recorded calls of the live run, the code, and a read of the actual draft.

## What is wrong

1. **The draft is not an IM.** It reads as a diligence report. Figures are recited in semicolon chains, there is
   no investment thesis, sections repeat each other, and most paragraphs say what the materials lack.
2. **The order is backwards.** Questions come after about 7.5 hours although nearly all of the work behind them
   is code. Answers cannot reach a running job. So a person waits a full run to have any effect.
3. **The work is unconditional.** Every section is rewritten and rechecked whether or not it needs it.
4. **The page shows the wrong system.** The company page reads the old public-research records. The document
   pipeline feeds none of those panels.
5. **The laptop is too slow** (1.39 tokens/s for the writer), which multiplies 2 and 3.

Measured on the current attempt: 72% decoding, 12% prefill, 17% thinking-cap calls. First drafts account for about
15% of the output tokens. Projection for this design: 11.5 hours for the memo without hill climbing, up to 19 with
it, decks after that.

## Prototype result, 30 October 2026

One thesis and one exhibit-led section, on the laptop with the existing writer and a topic-scoped prompt: 679 and 401
seconds. Reading: the shape is far better (a finding as headline, 60 to 70 word paragraphs, no recited tables), and at
that pace 12 sections would take about 80 minutes on the laptop. This is two calls, not a measured full run.

The numbers were not safe. Without the evidence contract the writer mislabelled a twelve-month projection as a
financial year, compared unlike periods, stated a loss figure found in no source, called a smaller loss a wider one,
and offered a merit its own evidence contradicted. So free-written figures are rejected. Milestone 2 must also give
the writer code-computed readings on comparable periods, and validate every number and period in prose against them.

## Decisions

- **Model.** No stronger open model that fits was found, and parameter count did not track analytical scores.
  Qwen3.8-27B stays the writer candidate; the gain available is precision (FP8 rather than Q4) and speed. A
  bake-off decides. The writing contract below is the main quality fix, and more compute will not replace it.
- **Questions come first.** Fact base, then questions, then writing. A draft with open blockers is labelled as such.
- **Exhibits carry numbers, prose carries meaning.** Code draws every table. Prose never recites a table.
- **One thesis.** A thesis step sets three or four merits, each with its proof. Every section serves one of them.
- **Limits sit where they matter.** A material caveat stays beside the exhibit it changes, once. A "Basis of
  preparation" page sets out dates and sources, and a separate open-items list goes to the company. The body presents
  the business and does not run a commentary on what is missing.
- **The thesis carries its opposition.** Every merit lists the contrary evidence. A thesis that omits a known
  contradiction fails, however well it reads.
- **A transaction brief is mandatory before release.** Raise, instrument, valuation, uses and runway come from the
  company. Reconciled actuals and forecast assumptions are required too.
- **Length.** 1,800 to 2,500 words plus 8 to 10 exhibits, down from about 4,700 words and no exhibits.
- **Hill climbing stays off** until it has measured value. It has never run on the real model.
- **Honest limit.** Writing cannot repair 52-month-old data, an unstated raise or missing disclosures. Those need
  answers. A good draft of unanswered material is "ready for a banker to review", not ready for investors.

## Milestones

Each has a measurable acceptance test. The company page, plain finish time and read-only overview are already done.

| # | Work | Files | Acceptance test |
|---|---|---|---|
| 1 | Stop the bleeding: failed calls never cached, live answers with stable ids, questions straight after facts, rewrite only flagged sections, climb off. **Code done; timing not yet measured** | pipeline.py, runs.py, questions.py, climb.py, llm.py | Questions appear within 5 minutes of fact approval. Killing a host caches 0 failures |
| 2 | IM contract: thesis step, exhibits by code, one-limit rule, length budget, cross-section repetition check | memo.py, render, new thesis step | One real section passes a blind read against the current draft; 0 semicolon chains of figures; 0 "the materials do not" in body text |
| 3 | Public bake-off (stage A below). Prerequisite for 5 and 6 and for any timing promise | scripts, deployment notes | End-to-end benchmark at the real context size and concurrency, not only tokens/s |
| 4 | Dependency graph from facts and answers through thesis, calculations, reviews and files to paragraphs and slides | new graph.py | Replay rebuilds 100% of links. Every paragraph resting on a changed fact goes stale, and every other paragraph is untouched, however many that is |
| 5 | Task queue across model servers: leases, three attempts, priority answer > first version > refinement | new tasks.py, llm.py, worker | Host killed mid-call: run completes, 0 duplicates, requeue under 3 minutes |
| 6 | Fast first version | memo.py, pipeline.py | 12 sections in under 30 minutes on the cloud GPU |
| 7 | Answer patching | memo.py, questions.py, decks.py | Answer visible in the draft in under 5 minutes; unlinked paragraphs byte-identical |
| 8 | Paragraph-level streaming and stage-based status | deal_documents.py, DealDocuments.tsx, runs.py | New section visible in under 10 seconds; estimate within 25% |
| 9 | Decks from the same thesis and exhibits | decks.py | Every slide inspected as an image; intro deck is a true subset |
| 10 | Banker review pack: claim-level sources in exports, owned blockers, removed claims, changes since last version, explicit acceptance of company answers | render, review | Whole document scored by a person against a written rubric |

## Compute

Recorded limits, verified in `deployment/PRIVATE_GPU_EVALUATION_PLAN.md`: the Mumbai quota request told AWS at most
one `g6e.2xlarge`, public data only, no Spot, capped at 32 GPU hours and ₹15,000 a month. Existing notes also say GCP
replaced AWS, and the saved rule says private documents stay local. The owner has since said to use AWS.

Target: **one on-demand `g6e.2xlarge`** (8 vCPU, 44 GiB L40S, about US$2.69/hour, approximate). It fits the 8 vCPU
quota, matches the recorded request, and has room for FP8 (about 28.5 GiB). Two `g5.xlarge` at about US$2.42/hour are
the fallback; a 22 GiB card cannot hold FP8. A single model cannot usefully span two instances, so splitting means
writer on one and reviewer on the other. `g7e.2xlarge` (96 GiB, about US$5.49/hour) is the upgrade if the bake-off
justifies it.

Expected full run: 40 to 70 minutes. This is an estimate that assumes 25 tokens/s and must be measured before anyone
relies on it.

Controls: encrypted disk, no inbound rules (SSM or a single-address SSH tunnel), model server bound to loopback,
prompt logging off, boot-time forced shutdown, idle alarm, terminate after the run.

### Provisioned, 31 October 2026

`deploy/aws/` holds the scripts. One `g5.xlarge` (A10G, 22 GiB, 16 GiB RAM, US$1.21/hour) runs in `ap-south-1a`, tagged
`Project=deal-gpu`. It was the only type with capacity: `g6e.xlarge`, `g6e.2xlarge`, `g7e.2xlarge`, `g6.xlarge`,
`g6.2xlarge` and `g5.2xlarge` all returned `InsufficientInstanceCapacity` that night. The disk is 100 GB encrypted
gp3, inbound is SSH from one address, IMDSv2 is required and the model server is bound to loopback.

Spending limits, in the order they act:
- `deal-gpu-guard` in AWS Lambda runs every five minutes, counts instance hours and stops the machine at 20 hours a
  month or 6 hours a session. It alerts at 50%, 80% and 100%, and an alarm fires if the guard itself fails.
- Each boot schedules a stop after 345 minutes, in case the guard fails.
- Budget `DealGpuMonthlyCap` (US$150, ₹15,000 at the planning rate of ₹100/$) sends alerts. Billing data lags, so
  this is a warning and not the control.

The 20-hour limit was set for the dearest type tried, and each instance's hours count, so a second machine uses it
twice as fast. Before a higher-priced type runs, or the limit is raised, work out the monthly worst case again.

### Stage A: public bake-off (within the recorded request)

About one hour and under US$10. Public or synthetic data only: same fact pack and prompt for current Q4, FP8 with and
without thinking, Qwen3.6-27B FP8 and Gemma 4 31B, three seeds each. Record valid-JSON rate and tokens/s at 1, 8 and 16
concurrent. Read blind, scoring unsupported claims, padding and figures per 100 words. Promote only with 0 unsupported
figures, 100% valid JSON and a clear win. If FP8 does not beat Q4, the fix is the contract, not more compute.

### Stage B: private documents on the owner's AWS account

Approved by the owner on 30 October 2026: private documents may be processed in a private sandbox in their own AWS
account. Source files and the database stay on the local machine. Hosted model APIs remain excluded. This differs from
the original quota request, which said public data only, and the egress and retention checks in the evaluation plan
must pass before the first private run. Prompts and outputs on the instance are destroyed when it is terminated.

## Out of scope for this plan

Compliance sign-off stays with a qualified human. Nothing is sent to investors. Nothing here claims an investor
outcome.
