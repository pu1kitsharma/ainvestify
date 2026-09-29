# Remaining blockers — 26 September 2026

This is a code/live-run inventory, not an investment-quality certification.

1. **Provider access and limits.** The exact Sonnet 5.5 request was rejected by this account. The user approved Sonnet 5, now pinned explicitly. Pro quota, authentication failures and outages stop work and retain drafts; no silent Opus or paid API fallback. A reset does not guarantee uninterrupted capacity.
2. **Variable generation/review latency.** Some source reviews take about a minute. Automatic correction now spans at most three 120-second passes, with cumulative usage visible. This is not an instant-output guarantee; cold retrieval may also fail. Cached validated work needs no new inference.
3. **Model output and reviewer reliability.** Fresh writers/search planners still sometimes violate schemas. Model-authored formatting and field corrections retain exact response provenance. Reviews can miss defects, raise new issues later, or make false objections; one Arable review even included a “no issue actually” objection. Exact quote checks establish binding, not the truth of every financial inference. Final browser inspection also found Arable saying no public disclosures exist when collection was incomplete, and presenting 2020 funding without the 2022 event present in earlier retained research. These are unresolved coverage/scope defects despite model review approval. Human expert evaluation is outstanding.
4. **Source accessibility and completeness.** Official sites, registries and search destinations may be missing, blocked, stale or poorly extracted. Government registration alone does not establish operating quality. Worldwide filing coverage is not demonstrated.
5. **Discovery breadth.** The current subscription workflow selects at most five companies per run and fetches at most six destinations. Search-link counts are not company counts. Continuation can expand the list; this is not exhaustive worldwide discovery. Duplicate company entities also remain in the saved list (AGCO and AGCO Corporation).
6. **Metric selection coverage.** Numeric extraction currently stops at 120 candidates. In GoCardless, a numbers-heavy first source uses the entire budget, so later financial sources appear in prose but cannot supply metric cards. This needs fair source allocation with stable IDs and regression coverage; it is a separate unresolved quality defect. Operational units such as gallons, acres and years also render as “currency/unit unspecified” even when the meaning text explains them; unit extraction/rendering needs improvement.
7. **Missing financial actuals.** Public pages often lack recognized revenue, costs, cash, cash burn and customer economics. The system cannot infer these as facts. Private uploaded accounts/notes stay local; public-evidence model drafts do not use that private context. Local extraction/calculation needs sufficient records.
8. **Future analysis limits.** Outlooks are conditional, not reliable forecasts. Numerical sensitivity requires dated, exact revenue/recurring-revenue data and approved assumptions. No proven probability of success, valuation accuracy or autonomous investment-decision quality exists.
9. **Workflow depth.** Public gaps are assigned to the system and can trigger further source research. The app does not yet run every diligence task to completion without interaction. Founder proposals are reviewed narratives, not an executed financial work plan. Older packs may need independent revalidation even when a separate analysis is complete.
10. **Durable execution.** Checkpoints persist in SQLite, but background workers are process-local. An API restart/crash can require an explicit resume. A durable queue/worker recovery mechanism remains to be implemented before dependable hosted operation.
11. **Evaluation and deployment.** The broader cross-sector/region company benchmark and expert acceptance have not passed. Current checks are local. Concurrent Anthropic API/deployment work is preserved, but AWS production reliability is not verified by these changes.

## Engineering fixes in this checkpoint

- Explicit Sonnet 5 request and returned-model check; quota/access/model errors do not trigger content repair.
- Automatic bounded continuation from saved formatting, draft, patch or review checkpoints; cancellation, no-progress stop and cumulative usage.
- Malformed saved reviews are repaired without discarding or rewriting the saved candidate.
- Search-result schema repair reuses observed links without another web search.
- Schema-forbidden keys can be removed only through a recorded model formatting response, with strict path validation.
- Numeric scale after a plus sign is preserved (for example “5+ billion”); source/metric binding stays checked.
- Last reviewed analysis survives a failed refresh in both UI and downloads. An unreviewed placeholder export is refused.

See README.md in this directory for live outcomes and the distinction between fresh drafting and checkpoint recovery.


Later update: the hidden five-company limit and known duplicate records in item 5
were addressed in [the discovery checkpoint](../discovery-breadth-2026-09-26/README.md).
Targets are configurable; two live runs yielded 18 distinct companies. Source
coverage and bounded execution still limit each run; exhaustive worldwide coverage
is not established. The other analysis-quality blockers above remain.
