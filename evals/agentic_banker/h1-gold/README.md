# H1: gold set x scorer validation (G-READY criterion 3)

Run: `.venv/bin/python scripts/validate_gold_scorer.py` (writes a new private,
git-ignored report to `evals/agentic_banker/gold/_scorer_validation/report.json`;
stdout is counts only, deals labelled deal_a..deal_c in alphabetical directory order).
Adapter: `training/gold_adapter.py`. Tests: `tests/gold` (fictional fixture + an
auto-skipping private-gold structural test). No inference, no adjudication added.

## What is demonstrated (counts only)
Three gold sets (16/15, 27/12, 35/14 findings/traps). For each: 5 cases (E1, E2,
E4, E5, E6), 6 supported and 7 unsupported dimensions. Oracle (derived from the same
gold) scores 1.0 on every supported dimension; unsupported dimensions score 0 and
are reported `unsupported`, so the case mean is below 1 by design. Six degradations
(miss findings, flag traps, wrong scale, wrong period, extra unsupported claims,
wrong cash scale): each applicable one scores strictly lower and its specific
penalty fires (trap flag lowers precision only; miss lowers recall only; scale/period
errors zero the affected check). 14, 14 and 15 checks pass, 0 fail.
Caveat: this proves scorer/adapter consistency with gold that has no human
adjudication. It says nothing about model quality or gold correctness.

## Mapping
- E4 `flags`: ids of findings whose action is flag/correct/ask_user; traps with
  `do_not_flag` are forbidden ids (any hit lowers precision).
- E1 `historical_cells`/`citations`, E2 `reported_totals`: set tokens
  id|value|unit|scale|currency|period (and id|source|locator) for numeric
  `actual` facts; E2 is a heuristic (label contains "total").
- E5 `cash_need`: numeric, only where the summary states a peak cash-need figure
  (1 of 3 deals); abs tolerance 0.5 in the summary's scale.
- E6 `text_cell_agreement`: section|fact bindings; `sections`: order|id tokens.

## Gaps (cannot be expressed in the current scorer schema)
| Category | deal_a | deal_b | deal_c |
| --- | --- | --- | --- |
| Findings with non-flag action (disclose_assumption), unscored | 1 | 0 | 7 |
| Findings with recomputed values (only id match is scored, values/direction of error not) | 13 | 24 | 32 |
| Trap allowing low-severity flag (`flag_low_at_most`), not expressible | 0 | 0 | 1 |
| Trap with other action (disclose_assumption), unscored | 0 | 0 | 1 |
| Company-projection facts (no gold-backed E3 key) | 23 | 176 | 654 |
| Derived facts / non-numeric facts unscored | 0 / 0 | 6 / 1 | 5 / 13 |
| Section source refs not resolving to fact ids (finding ids / source keys) | 1 of 7 | 4 of 15 | 39 of 76 |
| E2 totals found by heuristic | 3 | 4 | 0 (E2 unsupported) |
| E5 cash_need key available | no | no | yes |

Structural gaps: the scorer has no per-item severity, no direction-of-error or
value matching for findings (ids only); E3 and E7 have no gold content; `live_formulas`,
`no_calculation_hardcodes`, `maximum_draw`, `funding_buffer`, `recalc_clean` and
`comparison_direction` have no gold source; section required_content text is not
scored; most corrected-summary groups (scenarios, LBO, balance sheet) are unconsumed.
Findings are matched by gold id, which is a closed-world assumption: a model must
emit gold ids, so a real run needs a (not yet built) mapper from free-text findings
to ids.
