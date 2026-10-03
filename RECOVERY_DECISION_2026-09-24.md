# Recovery decision — 24 September 2026

> Historical context: current instructions are in [AGENTS.md](AGENTS.md) and the [local-to-cloud plan](LOCAL_TO_CLOUD_RELEASE_PLAN.md). Older scope/provider/deployment statements below are superseded where they conflict. Preserve the historical evidence.


> **Latest decision:** The user explicitly approved **“Use Claude Pro for public-evidence drafts.”** The app now uses the official signed-in CLI for that limited scope. Private records/context and storage remain local; no API-key fallback or AWS service was configured. See [handoff §29](SESSION_HANDOFF.md#public-pro-working-path) and the [complete run history](evals/investment_preparation/section-workflows/generation-quality-2026-09-24/README.md). Earlier proposals and local-only statements below preserve history and do not override this approval.

> **Later user clarification:** the intended product keeps company context and inference local to avoid recurring API billing. The user has Claude Pro and wants to use that where possible. The paid-model/search proposal below is retained as researched history, not an approved implementation direction. See the amendment at the end. No provider was enabled.

> **Subsequent authorized comparison:** Pro sign-in was verified and one public-evidence first-pass diagnostic was run against the local model. Both failed to complete. [Results and limitations](evals/investment_preparation/section-workflows/pro-subscription-diagnostic-2026-09-24/README.md). The app's production provider remains local.

Research and implementation proposal, not a deployment or a successful evaluation. No new inference, paid API calls, account subscriptions, service restarts or company-data changes were performed for this review. Public documentation was consulted on 24 September 2026. Prices are USD and require rechecking before purchase.

## Decision

Keep the existing application and provenance storage. Test a stronger hosted model and a supported search API after correcting the failure-recovery boundary. Do not move the whole application to AWS or rent a GPU as the first fix. The next deliverable is one complete, readable, source-supported company journey, followed by an unseen-case acceptance test.

Primary model candidate: Claude Sonnet 5 through the native Claude API. Primary discovery provider candidate: Brave Search API. These are candidates for a bounded evaluation, not proven winners for this product. If AWS billing is required, investigate Claude Platform on AWS separately from Amazon Bedrock; they have different feature surfaces. Retain a provider interface so the application can change models without rewriting business logic.

## Verified local baseline

Read-only SQLite inspection found two companies and two operating workspaces. Neither has a complete preparation pack. The latest saved jobs remain from 16 September IST, not new September 24 runs.

| Company | Last saved preparation | Saved sections | Result |
| --- | --- | ---: | --- |
| GoCardless | automation_10c031a8d61c | 0 | Failed after approximately 30 seconds: economics.unknown_economics exceeded 350 characters |
| CropX | automation_eb590e208dd8 | 3 | Failed: a numbered action label was treated as an unsupported figure |

CropX discovery previously produced one candidate in 83.028 seconds, with partial source coverage. Its primary website and location were unresolved. That result demonstrates a genuine model-driven discovery path, not reliable global sourcing.

The last commit is b3945b6. Later discovery, preparation, UI, tests and documentation changes are still in the working tree. Historical tests and UI checks do not establish financial accuracy. Handoff section 23's 61-second GoCardless run is superseded by the later failure above.

The product has reusable retrieval, storage, job and provenance infrastructure, but has not demonstrated its core promise. No investment-quality percentage is justified.

## Failure analysis from code and retained evidence

1. **Retrieval fails before analysis starts.** DuckDuckGo was blocked; Mwmbl timed out or returned weak results. A more capable model cannot analyze evidence the application never obtained. Directory pages can also mix unrelated companies.
2. **Meaning errors survive formatting repairs.** Retained GoCardless responses confuse bank payments with card processing and processed-payment volume with revenue. Retained CropX work includes irrelevant commercial concepts. These require evidence and reasoning evaluation.
3. **Schema failure is too destructive.** `agents/model_authorship.py` preserves the raw response on exception but does not expose it as a usable candidate. `response_answer` rejects errored rows. `agents/authored_preparation.py` primarily repairs whole top-level objects; a nested length error can lose otherwise useful work from the active candidate path.
4. **The provider is not interchangeable yet.** `agents/local_models.py:generate_authored_task` directly constructs `LocalModel`, with Ollama-specific sampling and token settings. Adding an API key or replacing a model name will not migrate this path.
5. **Schemas vary with evidence and repair scope.** `bound_schema` embeds fact-ID enums; correction schemas vary with failing sections. This can create new compiled grammars in hosted structured-output services. Cache behavior must be measured, not assumed.
6. **Readiness is a proposal, not executed diligence.** Public evidence can support an initial memo and a request for company records. It cannot establish margins, retention, reconciliation or investment readiness when those records are missing.

## What current documentation changes about the recommendation

Bedrock supports constrained JSON on supported models, but excludes string-length and numerical constraints. Its documentation also says first-time grammar compilation can take minutes and cached grammars last 24 hours. Therefore our 350-character failure is not solved simply by choosing Bedrock structured outputs. Use stable generation schemas and retain application validation. [AWS structured-output documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html)

AWS currently lists structured outputs as unsupported for Sonnet 5, while its Sonnet 4.6 model card lists support. This is a model-and-endpoint compatibility issue, not evidence that one model reasons better. Do not assume feature parity from a shared model family. [Sonnet 5 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5.html), [Sonnet 4.6 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html)

The native Sonnet 5 documentation directs developers to structured outputs. It also specifies adaptive thinking by default, rejects non-default sampling parameters and removes manual thinking budgets. The current local temperature-zero configuration must not be copied into that API. Configure reasoning explicitly and measure total billed tokens. [Sonnet 5 migration behavior](https://platform.claude.com/docs/en/models/sonnet-5/whats-new-sonnet-5)

Claude's native structured-output path also has grammar compilation and schema limitations. SDK helpers may remove unsupported constraints before generation and enforce them afterward. Preserve the raw response before SDK/application parsing; otherwise we can reproduce the current failure under a different provider. [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

Claude Platform on AWS is Anthropic-operated and billed through AWS Marketplace; Bedrock is a separate AWS-operated offering. Use the direct API for the first proof unless an existing AWS requirement makes the additional setup worthwhile. This is not a recommendation to create both accounts. [Platform comparison](https://platform.claude.com/docs/en/build-with-claude/claude-platform-on-aws)

## Proposed implementation sequence

### 1. Repair the generation contract without weakening evidence requirements

- Separate the provider response, parsed candidate, application validation and published section. Persist each boundary with model, input, schema and response hashes.
- Preserve schema-invalid JSON as an unaccepted candidate, with explicit field-level defects. Never mark it validated merely because it parses.
- Use a fixed schema per generation phase and a fixed repair envelope. Pass available evidence IDs as input; check membership and source support in code. This relocates the same check rather than removing it.
- Repair the smallest failing field or dependent section with another recorded model response. Reconstruct accepted output exactly from the response chain. Recheck changed claims and all affected downstream sections.
- Keep the current length and evidence contracts initially. If presentation limits are later redesigned, version that decision and re-evaluate; do not silently accept failed historical outputs.
- Treat provider timeout, refusal, truncation, unsupported schema, invalid citation and unsupported business claim as different outcomes. No unlimited retries. Existing six-call/120-second preparation ceiling remains the maximum.
- Preserve valid sections and display accurate per-section state. A failed founder draft must not erase validated research. Unreviewed text must not appear accepted.

Regression proof: replay the actual GoCardless overlong response, missing/invalid IDs, CropX step labels, real unsupported numbers, truncation, resume and stale-evidence cases. Verify source and authorship checks still reject unsafe output. This engineering work does not require another expensive model run.

### 2. Replace fragile search as the default

Use Brave's search endpoint for observed URLs and descriptions, with model-authored queries and company selection. Fetch and retain the actual relevant passages, publisher, source URL, retrieval time and entity association before generating claims. Use its context endpoint only after checking that the retained passages and provenance meet our requirements; a search snippet is not sufficient evidence for an investment claim. [Brave Search API](https://brave.com/search/api/)

Keep retrieval parallel only where independent, with bounded connections, deadlines and one bounded refinement round. A blocked provider should not consume the whole job in retries. No manually selected company catalogue or code-written company descriptions.

Check company identity before merging records: a directory listing, similarly named legal entity or another firm's pricing is not interchangeable evidence. Multiple copied press releases are not independent corroboration. Preserve missing and contradictory evidence explicitly. Worldwide coverage requires non-US and non-English test cases, not merely a query containing “global.”

Tavily is a documented alternative with search and extraction; use it only if the discovery evaluation identifies coverage or extraction failures that justify a second integration. Its pay-as-you-go price is $0.008/credit; basic and advanced searches consume one and two credits respectively. Price alone does not establish which provider retrieves the right companies. [Tavily pricing](https://docs.tavily.com/documentation/api-credits)

### 3. Demonstrate model capability using fixed evidence

Start with GoCardless, CropX and one unseen company. Freeze evidence snapshots so retrieval differences do not confound the model comparison. For a controlled comparison, run the current local model and Sonnet 5 through the same corrected contract; do not compare differently configured historical jobs as if they were an experiment.

Use the existing three writing phases and a focused review initially. Do not add autonomous research loops or extra reviewer agents without a measured benefit. Smaller predefined workflows make latency and failure attribution easier. This follows the general engineering recommendation to add agent complexity only when simpler workflows are insufficient. [Anthropic workflow guidance](https://www.anthropic.com/engineering/building-effective-agents)

A model reviewer can identify defects but cannot certify itself. Inspect the actual claims and proposed work against the evidence. If Sonnet cannot pass these cases, stop before full application migration. Distinguish contract failures from evidence failures and reasoning failures. One bounded stronger-model diagnostic can test whether capability is limiting; do not start another broad model sweep by default.

Gemini 3.8 Flash is a possible later cost challenger with documented structured outputs and search grounding. No comparative quality claim is established here. Introducing it now would increase the evaluation surface before a baseline exists. [Google model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)

### 4. Prove the complete journey on unseen cases

Freeze an acceptance set before tuning: ten evidence-sufficient companies across at least three sectors and three regions, separate from the diagnostic cases. Repeat each fresh preparation three times. Also maintain separate negative cases for no evidence, wrong entity, stale or conflicting sources and provider failure. Do not count a correct abstention on an evidence-sufficient case as a complete pack; do not require fabricated completion on an evidence-missing case.

Proposed pilot gate, not an accuracy estimate:

- At least 27 of 30 evidence-sufficient runs produce the full nine-section pack without manual answer edits, with no company systematically failing all repeats.
- Every published material factual claim has a source that actually supports its meaning and entity. No invented financials, revenue/volume confusion or falsely claimed diligence completion in the reviewed set.
- An investment practitioner judges the research, founder draft and two distinct diligence plans usable with minor edits. Record disagreements; model self-review alone does not pass this gate.
- Each quantitative plan identifies necessary records, entity, period, currency and meaningful comparison. Actual numerical outputs require deterministic calculations over supplied records. Initial narrative plans remain explicitly unexecuted.
- Record full latency distributions, failures, retries, tokens and cost. Preparation must respect its 120-second deadline. Discovery has a separately reported deadline; do not combine these into a false two-minute end-to-end promise.
- Measure fresh live discovery separately: on ten predefined diverse thesis queries with known accessible candidates, at least nine return three distinct, evidence-supported eligible companies within the discovery budget. Report relevance and identity errors alongside yield. This is a proposed discovery gate, not present performance or exhaustive coverage.

Thirty runs are a useful pilot gate, not statistical evidence of universal accuracy. The evaluation should combine code checks, calibrated model review and human judgment. [Agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

Research on financial question answering separately measures finding the right document and finding the actual supporting page or passage. That distinction matters here: a working search API alone does not prove adequate evidence retrieval. Its benchmark results are not a score for our application or current chosen model. [Kobeissi and Langlais, PMLR 2026](https://proceedings.mlr.press/v318/kobeissi26a.html)

## Latency and cost boundaries

Desired UX targets to test: retained validated work in under one second locally; a first validated research section within 30 seconds of preparation starting when sufficient evidence is already present; a complete prepared pack within the existing 120-second preparation budget. These are acceptance targets, not measured promises. Schema cold starts, queueing, page fetches and repairs belong in the measurements. Streaming shows progress but does not make the completed answer arrive faster or make unvalidated text trustworthy.

Use stable schemas, reuse unchanged evidence, cache by evidence/model/prompt/contract versions and avoid regenerating unaffected sections. Warm known schemas during deployment only with authorized usage; report cold and warm performance separately. A cache is not evidence that fresh generation is fast.

Current native Sonnet 5 prices are $2 per million input tokens and $10 per million output tokens. Brave Search is $5 per 1,000 requests. These published prices do not establish the tokens our application will consume. [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Brave pricing](https://api-dashboard.search.brave.com/documentation/pricing)

Illustration only: 40,000 total billed input tokens across all workflow calls plus 6,000 total billed output tokens costs $0.14; six Brave requests add $0.03, giving $0.17. Include reasoning tokens in output, repeated contexts in input, and repairs/reviews in both. Taxes, hosting and optional extraction services are excluded. This is arithmetic, not a measured per-company quote or an AWS price guarantee.

Propose an initial $20 external-API experiment envelope, subject to explicit authorization before use. Enforce request/token limits and conservative reservations in the application before dispatch, reconcile actual usage, and stop if the remaining allowance cannot cover the next request. Track all concurrent jobs. Budget alerts alone are insufficient: AWS documents delayed billing notifications. [AWS Budgets limitations](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)

## What happens after the gate

Select the passing provider based on observed quality, latency and cost, then consider cloud deployment for availability and shared access. Do not choose a GPU instance before measuring a reason to self-host. App hosting, model hosting and model capability are three separate decisions.

Preserve existing data, provenance and regression fixtures. No hardcoded company prose, manual repair of generated answers, fabricated completion or automatic investment execution. The deliverable to show the user is the actual unedited output plus its evidence and measurements, not another UI screenshot or a passing unit-test count.

Confidence is high that the identified recovery and retrieval defects need correction. Confidence that a particular hosted model will satisfy this workload remains unmeasured until the bounded tests run. That distinction is the basis for the proposed spending and acceptance gates.

## Amendment — local context, Claude Pro and repeatability

The user clarified that local operation, use-case-specific responses, fixed format and avoiding API charges are core requirements. Do not treat the earlier $20 experiment proposal as authorized spending or automatically replace local inference with cloud generation.

Anthropic's current June 15 update says personal Agent SDK, `claude -p` and third-party app usage still draw from subscription limits; the announced separate SDK credit was paused. Ordinary Claude API billing remains separate. Personal subscription use must not be represented as an unlimited shared production backend. [Current subscription guidance](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [authentication boundaries](https://code.claude.com/docs/en/legal-and-compliance)

Claude Code 2.1.203 is installed locally. Its `auth status --json` check reported `loggedIn: false` in this execution environment. No authentication tokens were read or copied and no inference was started. Claude inference still occurs remotely; keeping SQLite local does not keep the prompt local. The user delegated the choice after this distinction was explained. The selected approach keeps normal generation local and uses Pro only for development and a bounded comparison using public evidence after authentication. No automatic cloud fallback or recurring API billing was enabled.

The current authored local writer already requests structured JSON and temperature zero. Thus recommending those two settings as new fixes would be misleading. Ollama documents constrained schemas and lower temperature as tools for stable output, not truth guarantees. [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)

Separate four requirements: stable document layout (schema plus renderer); identical reopening of accepted work (versioned caching); domain-specific reasoning (relevant local evidence, explicit business rules and reviewed examples); first-attempt quality (measured on fresh runs with zero repairs). The earlier 27/30 completion target allows bounded repairs and therefore does not prove the user's first-iteration requirement. Add an explicit first-attempt acceptance metric, tracking schema, source support and reasoning failures separately. Never count cached responses as fresh successes.

Keep the local default and the existing no-cloud-fallback boundary. Improve field-level recovery, evidence selection and the domain contract before selecting another model. Freeze model artifact, prompt, schema, source snapshot and supported generation settings for reproducible comparisons. Exact fresh wording and factual correctness are not guaranteed by low temperature or a seed. Reuse unchanged accepted model output rather than regenerating it on page visits. No hardcoded company conclusions or hand-edited application answers.

Historical hardware notes report 16 GB unified memory; the current sandbox denied the hardware query. Model upgrades must be chosen against verified available memory and measured latency, not an untested recommendation to load a much larger model. Fine-tuning is not an immediate remedy without a reviewed training set and held-out evidence of improvement.

Implementation following this clarification: schema-invalid JSON is retained as an explicitly unaccepted candidate; nested corrections are exact recorded model patches, with full schema, citation, semantic and raw-response checks before acceptance. Missing fields require a new model replacement, not defaults. First-attempt contract completion is recorded separately from repaired completion. Verification: 107 focused tests passed (15 existing dependency warnings). This is engineering recovery and measurement, not proof of first-pass research quality. No live model run or stable service restart occurred.
