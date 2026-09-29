# Claude Pro versus local: first-pass diagnostic

24 September 2026. The user authorized using their existing Pro subscription and delegated its role after the distinction between local storage and remote inference was explained. This diagnostic uses public GoCardless source passages only. It does not change live leads or select a production provider.

Authentication was confirmed as `claude.ai` / `pro` through the official CLI outside the filesystem sandbox. The sandboxed check could not access the macOS credential store. No tokens were copied. Normal application inference remains local.

## Inputs and limits

`gocardless-public.json` contains six retained public passages and source metadata. Company records, user instructions, workspace history and previous drafts were excluded. Both fresh isolated workspaces received the same evidence. The first research instruction, input and output schema are exactly equal between reports. The first case was stopped at failure; no broader company sweep was started.

Each provider was allowed at most four application calls and 120 seconds, with no repairs or fallback. Calls were made through the existing production preparation workflow in temporary SQLite stores. The Pro adapter disabled tools, customizations, skills, MCP connections and session persistence, stripped API-key/provider environment overrides, and required Pro authentication. It used one CLI answer per phase, with the output schema in the prompt and local validation. Local used the existing constrained Ollama JSON path. This transport difference and the single company/sample mean these results are diagnostic, not a controlled general model ranking.

## Results

| Provider | Elapsed | Executed application calls | Repairs | Completed pack |
| --- | ---: | ---: | ---: | --- |
| Pro, actual writer `claude-sonnet-5` | 41.084 s | 2 | 0 | No |
| Local `qwen3.5:9b` | 39.369 s | 1 | 0 | No |

Pro retained three research sections pending final review. It failed the next phase because the two work questions were 192 and 199 characters against a 170-character maximum. No final model review was reached. Inspecting its rejected work also found citation and financial-method defects: the annual payment-volume figure is not supported by the selected IDs; it introduces a top-20 customer cutoff; and its comparison of a blended fee rate with published fixed-plus-percentage pricing lacks normalization for transaction mix. These are not cured merely by accepting longer questions.

Local returned literal control characters inside a JSON string and failed parsing despite requesting constrained output. Its raw answer also asks whether payment volume represents gross/net revenue, repeating the earlier category error. Do not conclude that the model size alone caused the malformed output; the schema/decoder interaction needs separate investigation.

The first local launch in `local-gocardless/` failed because Ollama was stopped and never reached inference. It is preserved as an infrastructure failure, not a model-quality result. Ollama was then started on loopback with `OLLAMA_NO_CLOUD=1`; the actual model run is `local-gocardless-service-ready/`. No model was downloaded. The stable application API was not restarted.

The CLI envelopes report auxiliary Haiku usage as well as Sonnet usage. Two application calls therefore must not be described as exactly two underlying model requests. The total CLI-reported API-equivalent estimate is $0.154738; this is not an invoice or proof of an additional charge. Subscription usage was selected; no API key or paid fallback was enabled.

## Audit and engineering follow-up

`audit.json` records source-level inspection by the coding assistant, not independent practitioner acceptance. Original reports, raw outputs and CLI envelopes are retained. No output was manually rewritten or published to a live company.

Original `generation_metrics` counted denied correction attempts as repair calls. The diagnostic never executed those corrections. Counters were fixed to exclude `routing.invoked=false`; corrected counts are in `audit.json`, and original reports remain unchanged. A further validator defect treated ordinary inline `1. ... 2. ...` step labels as unsupported business figures. Consecutive list labels are now ignored for numerical checking only; actual unsupported numbers remain rejected. Neither change turns these failed reports into successful packs.

Verification after the metric correction: 108 focused tests passed. After the additional inline-label fix, 65 affected preparation/analyst tests passed. Both runs had 15 existing dependency warnings. The remaining first-pass research quality requirement is unmet.

Reproduction entry point: `scripts/evaluate_subscription_preparation.py`. It requires an explicit public-only snapshot, a new output directory and an explicit provider. Pro authentication and inference need credential-store/network access. Do not automatically rerun these diagnostics, consume subscription limits or treat them as production generation.
