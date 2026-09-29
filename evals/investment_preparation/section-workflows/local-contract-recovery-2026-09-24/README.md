# Parser, context and review recovery — 24 September 2026

**Reliable fresh preparation remains unresolved. No profile was promoted and no live company answer was replaced.** The user authorized implementation and verification after the earlier Pro comparison. These are six targeted diagnostics of the same retained public GoCardless snapshot, not an unseen-company or multi-sector evaluation.

Each run used an isolated temporary database, a 120-second deadline and a first-pass adapter that denied repair calls. The recorded application calls are not necessarily underlying provider requests. The local reasoning continuation uses another Ollama request; the Claude CLI reports auxiliary Haiku usage. All original reports and raw responses remain unchanged.

| Run | Seconds¹ | Executed calls | Result |
| --- | ---: | ---: | --- |
| `first-pass` | 109.9 | 4 | Local 9B produced nine candidates; review failed its length contract and made incorrect objections. |
| `combined-first-pass` | 106.5 | 2 | Local 9B coordinated draft plus reasoning review; incorrect review objections, real financial defects missed. |
| `compact-reasoning-first-pass` | 80.7 | 1 | Installed local 4B exhausted its response allowance while reasoning; no complete answer. |
| `pro-combined-first-pass` | 35.8 | 2 | Mechanically complete, **independent audit failed**. Wrong section support for Wise; proposed public-price comparison included negotiated plans without requesting their contracts/accounting policy. |
| `pro-section-review-first-pass` | 28.6 | 1 | Model returned fenced JSON; the former parser rejected the wrapper. Original failure retained. |
| `pro-reviewed-parser-first-pass` | 72.4 | 2 | Parser worked; explicit section review rejected an invented FY2025 scope, but also wrongly rejected founder/research alignment. No repairs attempted. |

¹ Saved report timing; console completion differs by milliseconds because export/final validation occurs afterward. See [audit.json](audit.json) for contracts, exact timings and provider metadata. The Pro calls total an API-equivalent estimate of $0.415650; this is **not an invoice** or evidence of separate API billing. Official subscription authentication was used, without API credentials/fallback.

## Implemented engineering changes

- Remove content regex patterns from the local decoding grammar; retain the original patterns, lengths, citation enums and content checks at validation. The previous malformed-control-character failure did not recur in these local writing calls; this does not establish that the grammar was the sole cause.
- Compact only exactly repeated adjacent paragraph sequences for inference. Original source records stay unchanged. The retained case decreases from 12,648 to 9,726 source characters, preserving distinct rates and qualifications.
- Parse a sole JSON Markdown fence as presentation while retaining the original raw response and hash. Surrounding commentary and malformed JSON still fail. No substantive text is inserted, removed or normalized.
- Preserve source/revenue distinctions in instructions and checks; use short word targets rather than relying on character limits to teach the model concision.
- Keep nested schema-failure candidates and model-written patches. A review of projected `required_input` maps back to the original `records_to_request`, so only that field is regenerated. Existing live packs without new optional config keys remain eligible for candidate revalidation.
- Render nested validation failures as readable UI explanations instead of empty panels or raw object dumps.

## Optional coordinated workflow

`combined_draft=True` is an **opt-in diagnostic profile**, not the application's new default. It writes research/work/founder in one response, binds each section to an exact recorded subobject, and runs a separate review. Review now records source and method checks plus a verdict for every section. A conflicting section verdict prevents completion. The legacy default remains local three-phase writing; no Pro production bridge or automatic cloud fallback was installed.

The final reviewer wording explicitly requires two distinct diligence questions while allowing the founder proposal to follow the same investment question. This corrects a false objection in the last run. That final wording and the final projected-field repair mapping have regression tests, **not a subsequent successful live model demonstration**. Later code edits change the contract hash; do not relabel older reports as final-code results or erase their failures.

## Decision and remaining work

AWS hosting alone would not correct the observed model reasoning failures. Keep application storage local and retain the 120-second limit. Do not claim either installed local model or the Pro comparison meets first-pass quality. Pro remains a development/public-evidence comparison tool under the selected local-first direction. Its faster mechanical completion is a candidate for further evaluation, not evidence of reliable investment analysis.

The next quality gate needs source-qualified economics, section-level citation support, valid negotiated-price/revenue reconciliation, and correct critic judgments on unseen businesses. A passing model reviewer is insufficient on its own. Do not import these drafts into the live company workspace or manually repair them. Any future production provider change needs an explicit product decision about remote inference; no paid API or AWS deployment was authorized here.

Current official subscription reference: [Use the Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan). Its June 15 update says the announced billing change is paused and `claude -p` continues drawing from subscription usage limits. This does not make inference local or usage unlimited.
