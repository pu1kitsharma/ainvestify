# Gold-set schema (generic, no company data)

Gold sets live in `evals/agentic_banker/gold/<deal>/` (git-ignored; confidential). Every deal directory uses the same files and JSON shapes so evaluators can be written once.

```
gold/<deal>/
  facts.json            normalised facts extracted from the raw source files
  expected_findings.json  defects/claims/traps an agent should (or should not) report
  sections.json         ordered section list a banker IM for this deal must contain
  corrected_model/      (financial-model deals only) corrected_model.xlsx + corrected_summary.json
  README.md             method, limits, unverified items
```

## facts.json
```json
{"deal": "string", "schema_version": 1,
 "sources": {"<source_key>": {"file": "name.pdf", "kind": "pdf|xlsx|pptx"}},
 "facts": [{
   "id": "string, unique, stable",
   "label": "what the number is",
   "value": 0.0,              // number, string, or boolean; null if not stated
   "unit": "usd|inr|pct|count|x|text|...",
   "scale": "units|thousand|lakh|mn|crore|bn|trillion",   // scale of `value` as printed
   "currency": "USD|INR|null",
   "period": "FY23|Q2 FY23|Dec-22|as_of_2022-03-31|...",
   "period_kind": "fy|quarter|month|point_in_time|cumulative|none",
   "provenance": "actual|company_projection|derived",
   "source": "<source_key>",
   "locator": "p3 | slide 4 | Sheet!A1:B2",
   "verbatim": "optional exact printed text"
 }]}
```
`provenance`: `actual` = historical as stated by the company; `company_projection` = forward-looking figure from the company; `derived` = computed by the gold author (state formula in `derivation`).

## expected_findings.json
```json
{"deal": "string", "schema_version": 1,
 "findings": [{
   "id": "F-001",
   "severity": "critical|high|medium|low",
   "category": "units|fx|formula|logic|cross_doc|claim|missing_data",
   "description": "string",
   "evidence": [{"source": "<source_key>", "locator": "..."}],
   "recomputed_values": {"name": 0.0},
   "expected_agent_action": "flag|correct|ask_user|disclose_assumption|ignore",   // traps may also use do_not_flag | flag_low_at_most
   "verification": "recomputed|read_only|unverified"
 }],
 "traps": [{
   "id": "T-001",
   "description": "statement that looks wrong but is right",
   "evidence": [{"source": "...", "locator": "..."}],
   "why_correct": "string",
   "expected_agent_action": "do_not_flag"
 }]}
```
Scoring: a finding is *matched* if the agent output names the same evidence locator (or equivalent fact) and the same direction of error; a trap is a *false positive* if the agent flags it as an error.

## sections.json
```json
{"deal": "string", "schema_version": 1, "document_type": "banker_im",
 "sections": [{"order": 1, "id": "string", "title": "string",
   "purpose": "string", "required_content": ["..."],
   "source_facts": ["fact ids or source keys"], "required": true}]}
```

## corrected_model/corrected_summary.json (financial-model deals)
```json
{"deal": "string", "currency": "INR", "scale": "mn",
 "as_modelled": {"<metric>": {"<period>": 0.0}},
 "corrected":   {"<metric>": {"<period>": 0.0}},
 "scenarios": {"<name>": {"<metric>": {"<period>": 0.0}}},
 "assumptions": ["explicit text"], "balance_check_max_abs_diff": 0.0}
```

## Notes added after first implementation (additive, backwards compatible)
- `facts[].period_kind` may also be `cumulative`; `value` may be text for qualitative claims (`unit: "text"`).
- A fact's `id` is stable and dotted (`<source>.<locator-ish>.<period>`); `sections[].source_facts` and findings may reference fact ids or finding ids.
- `facts.json` may carry an optional `verbatim` (exact printed text) and, for `derived` facts, an optional `derivation`.
- `recomputed_values` is free-form per finding but every number must be reproducible from the facts plus the stated arithmetic.
- `verification`: `recomputed` (gold author recalculated), `read_only` (read from a source, not recomputable) or `unverified`.
- The gold author is a single automated agent; there is no independent human adjudication.
- Toffee's `corrected_summary.json` uses arrays aligned with a top-level `periods` list instead of `{period: value}` maps (`{"metric": [v1, v2, ...]}`), plus `balance_sheet_quarter_ends`, `cash_need` and per-scenario `ebitda_12m` / `peak_cash_need_ex_opening_cash`; evaluators should accept both layouts.
