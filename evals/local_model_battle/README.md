# Local-model battle test

A bounded, resumable harness that measures installed local-model roles using
synthetic fixtures only. It produces diagnostic evidence.
It never renders or promotes an investor artifact, and a good score is not
investment quality or human acceptance.

## Suites

| Suite | Role under test | Prompt and schema | Calls per case |
| --- | --- | --- | --- |
| `challenge` | Whole-memo challenge call (earlier design, kept for comparison) | `CHALLENGE`, `Challenge`, `validate_challenge` | 1 |
| `ledger_flow` | Production challenge step and review: evidence ledger, claim mapping, field revision, re-comparison, review | Production `challenge_revision` and `review_request` | up to 5 per pass, 3 passes |
| `memo_flow` | Production memo stage from an injected synthetic draft: reconciliation, timeline or field repair, review and re-review | Production `run_stage` and `renderable_sections` | up to 5 per pass, 3 passes |
| `reconciliation` | Evidence reconciliation / candidate stage | Defined in `suites.py` (see limits) | 1 |
| `claim_coverage` | Investor-material claim coverage | Defined in `suites.py` (see limits) | 1 |

The challenge suites test the roles on a fixed source-bound memo, so they work
even when a full draft run exhausts its passes.

In `ledger_flow`, software extracts typed facts with exact spans from each
structured source record and compares them with cited prose and reader-visible
claim assertions.
The local model does three separate things: it labels each cited assertion
with a field and a polarity (without seeing the record), it rewrites a field
that has a direct conflict, and it reviews the corrected memo with the ledger.
The suite fails closed like production: a memo whose structured-cited
assertions are not all validly labelled, or whose conflict survives the
rewrite, is `blocked` and never scored as a pass.

`memo_flow` uses the fixture memo as an injected draft stimulus. It does not
measure model draft generation. Later responses come from the installed local
model and are replayed through the production stage and renderer. Each case
keeps separate raw attempts under `attempts/<case-id>.json`, and the scorecard
marks the draft as `fixture_injected_stimulus_not_model_generated`.

## Fixtures

Files in `fixtures/*.synthetic.json`, loaded and checked by `fixtures.py`:

- every source URL is `https://example.invalid/...`; the company names are invented;
- every case belongs to a counterfactual pair with a `defect` and a `control`
  variant: reported vs verified amount, reported amount called absent, reversed
  stage chronology, stale listing vs newer announcement, distinct legal
  entities, missing finances, contradictory source;
- labels are decision properties, never expected prose: a verdict and the exact
  memo span and source span of the planted defect (challenge), allowed statuses
  and selections (reconciliation), allowed labels (claim coverage);
- challenge stimulus memos must already pass `validate_memo`, because the
  challenge role runs after source binding;
- no label is sent to a model.

## What is scored

- **challenge**: exact defect detection (right field, right source, phrase and
  excerpt overlapping the planted spans, allowed kind), whether every issue is
  exactly bound and therefore routable to the field-patch path, issues other
  than the planted defect, and false-positive challenges on control memos.
- **ledger_flow**: whether the planted conflict was located exactly (field,
  cited source, assertion and record span), whether that field was rewritten
  and no conflict remained, conflicts or rewrites on a control memo, rows left
  unresolved for the reviewer, and the reviewer's recorded verdict.
- **memo_flow**: whether the bounded production stage completed, the exact
  saved responses can render, the planted defect is absent from reader-visible
  text, and the control memo was not changed.
- **reconciliation**: false-positive suggestions (an `investigate` status or a
  selection the reconciled evidence does not allow) and wrongful exclusions.
- **claim_coverage**: unsupported or contradicted statements labelled
  `supported`, false alarms on supported statements, and inexact excerpts.

A pair passes only when both its variants pass.

## Running

```sh
python3 -m evals.local_model_battle.runner challenge \
    runtime_qualification/local_model_battle/<run-name> --model qwen3.5:9b
```

- Models are called only through `agents.inference.local_models.LocalModel`
  (loopback Ollama, no download, no hosted fallback) and `recorded_call`.
- The model name and digest are pinned in `profile.json`; a changed digest or a
  different fixture, case set or model in the same directory is refused.
- Bounds: at most 24 model-calling cases per invocation (`--max-cases`), at
  most 105 seconds per pass. Single-call suites treat a model answer as final,
  valid or not, and request again only a call that produced no answer, once.
  The production-path suites keep the production bounds instead.
- `--only <case ids>` restricts a run, for example to one defect/control pair.
- Saved responses that the current run does not use (for example answers to an
  earlier prompt contract) stay in `scorecard.json` under `prior_responses`;
  one that called a planted defect supported is labelled
  `missed_planted_defect`.
- Re-running the same command resumes and replays saved responses.
- Output goes to ignored `runtime_qualification/local_model_battle/`:
  `profile.json`, raw hashed responses in `attempts.json` (or per-case
  `attempts/*.json` for `memo_flow`), and `scorecard.json`.

## Limits

- The reconciliation and claim-coverage prompts and schemas live in this
  package. The production candidate prompt is built inline inside
  `agents/discovery/kb_candidate.py` together with its database reads, and
  there is no production claim-coverage model role yet. Those two suites
  therefore measure the model on an equivalent contract, not the production
  prompt. Sharing one prompt needs a change in that file.
- Fixtures are small and hand-built. A scorecard describes these cases only.
- Thresholds for acting on a scorecard (prompt change, model change, weight
  adaptation) are not set here.
