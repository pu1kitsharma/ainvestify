# Deal Automation System — Revised Architecture & Design Document

**Status:** Design proposal, supersedes the original executive briefing where noted.
**Scope decisions locked in for this version** (from stakeholder input):
- Target: a product to eventually pitch/sell to funds and boutique IB/PE shops, not a single-user personal tool.
- Infra: fully flexible — local-only is not a hard constraint, but data privacy is still a hard constraint.
- Interaction model: conversational/iterative (user issues follow-up directives against a live deal context), not one-shot batch.
- Human review gate is mandatory before any memo is finalized.
- **Market-research data sourcing has zero budget, full stop.** No paid API, no paid tier, no "free trial that requires a card." §10 is rewritten around this — it also rules out Apollo, which the original brief counted as low-cost but whose free tier turns out to be legally unusable here (see §10.4).
- **Compute must be validated locally, CPU-only, before any AWS spend.** The available hardware is a laptop/desktop with no dedicated GPU, and even free-tier cloud compute is explicitly out of scope for now — Phase 0 (§13, §14) proves the architecture on that hardware first; AWS only enters the picture if that measurement, not an assumption, shows it's actually needed.
- **"Replace the current investment bankers" means eliminating manual grunt work with a human still signing off**, not removing the review gate — reconfirmed directly, see the addendum in §2.

---

## 1. What changed from the original brief, and why

The original brief's *problem statement* is sound: automate first-pass deal analysis (ingest source docs → market research → extraction/analytics → compiled memo) under privacy and cost constraints. That part is approved as-is.

The *implementation* had four issues that would have produced a fragile, slow, single-user prototype rather than something sellable. Each is corrected below, with the research that drove the correction.

| # | Original claim | Problem | Correction |
|---|---|---|---|
| 1 | "Temperature = 0.0 ... eliminate AI hallucinations" | Temperature controls sampling randomness, not factual grounding. A model at temp 0 hallucinates the same wrong number every time, deterministically. | Factuality comes from retrieval grounding, schema-constrained extraction, provenance tracking, and a human review gate — not a decoding parameter. See §7. |
| 2 | FAISS/RAG used to extract "pure parameter matrices" (ARR, cap table %, etc.) from documents | Vector similarity search is built for semantic retrieval of prose, not for pulling exact figures out of tables. Chunking breaks table structure; retrieval can surface an adjacent-but-wrong number with high confidence. Direct full-document-context prompting with a constrained schema outperforms RAG for this class of extraction ([Unstract, 2026](https://unstract.com/blog/comparing-approaches-for-using-llms-for-structured-data-extraction-from-pdfs/)). | RAG is used only where it's a good fit — market/comp research over a corpus (§5.3). Financial figure extraction uses schema-constrained, full-document-context extraction against a Pydantic/JSON schema, with page/table provenance (§5.2). |
| 3 | Single 70B model, hybrid CPU/GPU offload (36/80 layers on a 24GB A10G, 44 layers streamed through system RAM), used for every stage including a claimed 1.5–3 min generation time | Partial CPU offload for a 70B model on a single 24GB GPU realistically lands around **2–8 tok/s**, not the "fast" regime — full GPU placement of a *heavily quantized* 70B on a 4090-class 24GB card benchmarks around 18 tok/s even without any CPU offload ([mustafa.net, 2026](https://mustafa.net/llm-tokens-per-second-benchmarks/)). With over half the layers on CPU, 2–8 tok/s is the realistic range. A multi-page memo (2,000–4,000 output tokens across all agent calls) at that rate is **8–30+ minutes**, not 1.5–3. That's incompatible with the "conversational/iterative" interaction model that was chosen — nobody iterates on a chart at 15 minutes per turn. | Right-size models per stage instead of one 70B for everything (§8). Reserve the largest model for the one step that's naturally a "wait for it" step (final compilation), and use small/fast models for the conversational planner and structured extraction, which need to be responsive. |
| 4 | Cost model and data-source assumptions (Apollo "10,000 free monthly organization lookup records", Similarweb as a cheap/free alternative data source) sized for one user | AWS pricing for g5.4xlarge ($1.624/hr on-demand, [Vantage](https://instances.vantage.sh/aws/ec2/g5.4xlarge)) was actually accurate — that part of the brief holds up. But Apollo's free tier is **email/contact discovery credits tied to one account** (10,000/month only with a verified corporate email domain, 100/month otherwise), not a general "organization lookup" allowance — and, separately from the quota question, **Apollo's API terms of service prohibit embedding the API into a third-party product served to other customers at all**, free tier or paid ([apollo.io/terms/api](https://www.apollo.io/terms/api); see §10.4). Similarweb has **no usable free API tier**; API access requires a Business-tier plan starting around $16,000–35,000+/year ([Tekpon, 2026](https://tekpon.com/software/similarweb/pricing/)) — it was miscast as a cheap alternative-data source. | Apollo dropped entirely, not just deprioritized (§10.4). Similarweb dropped as a default source. Full zero-budget, ToS-checked data stack in §10, and a cost model that distinguishes solo-POC economics from multi-tenant product economics (§11). |

Net effect: the underlying idea is good and worth building. The architecture below keeps what worked (privacy posture, budget discipline as a design constraint, the general 4-phase lifecycle, GitHub as a legitimate free signal) and replaces what didn't (monolithic model, RAG-for-numbers, no review gate, single-user access model, unverified data-source assumptions — including Apollo, which turned out not to hold up on a second, ToS-focused look; see §10.4).

---

## 2. Problem statement (validated) and explicit scope

**Correction to this section (post-Phase-0 clarification):** this was originally written as a fund's *own* buy-side screening tool — deciding whether the shop invests its own capital. The user has since clarified the actual business model explicitly: this supports a boutique-bank-style sourcing/incubation shop that selects promising early-stage companies, incubates them, and helps *them* raise institutional funding — sell-side advisory work, not a buy-side investment decision. The pipeline mechanics below are identical either way (ingest → extract → review → research → compile), but the memo's audience and stakes change: it's external-facing collateral shown to institutional investors to help close a raise, not an internal-only investment-committee document. That's exactly why §7's guardrails and §5.5's human review gate are non-negotiable rather than a nice-to-have — the cost of an uncited or wrong number goes up, not down, once it leaves the building.

**Problem:** Boutique sourcing/incubation shops spend disproportionate time on the same first-pass groundwork needed to package a company for an institutional raise — reading pitch decks and financials, pulling comps, building the same three charts, and drafting the investment case — before a human ever puts it in front of an investor. This is high-volume, semi-structured, low-novelty work that's a good fit for automation, provided the output is treated as a draft for review, not a finished pitch sent without a human looking at it.

**In scope:**
- Sourcing candidate companies from a described theme/sector (§5.8) and letting a human promote a reviewed lead into an actual deal.
- Ingesting founder-provided materials (pitch decks, financial statements, cap tables) in PDF/Excel.
- Structured extraction of standard deal metrics (ARR/MRR, growth rate, burn, cap table structure, headcount, etc.) with source provenance.
- Lightweight external market/comp research from low-cost or free data sources.
- Auto-generated standard charts (ARR growth, cap table breakdown, sector comp table) from *validated* structured data.
- A reviewable draft memo, with every figure traceable to its source.
- A human approval step before any memo is considered final.

**Explicitly out of scope (for this version):**
- Investment recommendations or scoring ("should we invest") — the system produces material for a human's judgment , not a verdict.
- Legal/regulatory due diligence, KYC/AML, or compliance sign-off.
- Full multi-jurisdiction accounting normalization (different startups report differently; the extraction schema flags gaps rather than guessing).
- Fully autonomous operation with no review gate — the stakeholder decision in this round of design explicitly requires a human checkpoint (§6.5, §12).

This scope framing matters for the "product to sell" goal: it's a defensible, honest positioning ("AI-assisted first-pass deal screening co-pilot") rather than an overclaimed one ("automates investment banking"), which also happens to be the safer thing to pitch to a compliance-conscious fund.

**Addendum (reconfirmed this round):** the goal was phrased as a system that could "replace the current investment bankers." Checked against the stakeholder directly — the intent is to eliminate the manual grunt work (extraction, research, first-draft assembly) an analyst does today, with a human still signing off before anything is final, not to remove human judgment from the loop. That's exactly what's already scoped above and enforced architecturally by the mandatory review gate in §5.5/§12 — flagging it here explicitly so this framing doesn't drift back toward "fully autonomous" without a deliberate decision to change the architecture, not just the pitch deck copy.

**Second addendum (this round's business-model clarification):** the "sourcing + incubating + helping a company raise institutional funding" framing at the top of this section is explicitly *what an investment bank's advisory/ECM function does* — the user's own words. That does not reopen the addendum above: this system still doesn't run the raise (contact investors, negotiate terms, close the round) any more than it "replaces the current investment bankers" in the earlier sense — it produces the cited, reviewable material a human analyst uses to do that work faster, for a shop whose business *is* that advisory function rather than a fund investing its own capital. Both addenda point the same direction: automate the grunt work, keep the human doing the judgment and the relationship.

---

## 3. Design principles (revised)

1. **Privacy-by-default, deployment-flexible.** Data residency and encryption requirements are non-negotiable; *where* the compute lives is a per-customer configuration choice, not a hardcoded assumption (§8, §9).
2. **Grounded factuality, not decoding tricks.** Every number in a final memo carries provenance (source doc + page/cell, or source URL) and passes through at least one independent verification pass. Temperature=0 is retained for reproducibility, not claimed as a hallucination fix.
3. **Right-sized models per task.** A conversational router and a table-extraction pass need low latency and don't need 70B-class reasoning. Final synthesis benefits from a larger model. One model size for every step is a latency and cost mismatch.
4. **Human-in-the-loop as a first-class architectural element**, not a bolt-on. The workflow has an explicit interrupt/resume point, not an "email me if something looks wrong."
5. **Multi-tenant from day one**, even if the first deployment is single-customer. Data isolation, auth, and audit trail are part of the architecture, not a v2 add-on — retrofitting tenancy into a single-user SSH-tunnel design is expensive.
6. **Cost-aware, but the unit of cost is "per deal memo," not "per idle GPU-hour."** A budget built around one person's usage pattern doesn't generalize to a product with customers on different schedules.

---

## 4. High-level architecture

```
                          ┌─────────────────────────────────────────┐
                          │            INTERACTION LAYER              │
                          │  Conversational Planner / Supervisor Agent │
                          │  - parses plain-English directives         │
                          │  - maintains per-deal conversation state   │
                          │  - routes to specialist agents              │
                          │  - owns the HITL interrupt/resume loop      │
                          └───────────────┬─────────────────────────┘
                                          │  routes work to
        ┌──────────────┬──────────────────┼──────────────────┬──────────────┐
        ▼              ▼                  ▼                  ▼              ▼
 ┌─────────────┐ ┌──────────────┐ ┌───────────────┐ ┌────────────────┐ ┌───────────┐
 │  INGESTION  │ │  STRUCTURED  │ │    MARKET      │ │   ANALYTICS /   │ │COMPILATION│
 │    AGENT    │ │  EXTRACTION  │ │  RESEARCH (RAG)│ │  VISUALIZATION  │ │   AGENT   │
 │             │ │    AGENT     │ │     AGENT      │ │     AGENT       │ │           │
 └──────┬──────┘ └──────┬───────┘ └───────┬────────┘ └────────┬────────┘ └─────┬─────┘
        │               │                 │                   │                │
        ▼               ▼                 ▼                   ▼                │
 ┌────────────────────────────────────────────────────────────────────┐        │
 │                          DATA LAYER (per-tenant)                     │        │
 │  Object store (raw docs) · Structured store (fields+provenance)      │        │
 │  Vector store (comps corpus only) · Chart spec store · Audit log     │        │
 └────────────────────────────────────────────────────────────────────┘        │
                                          │                                     │
                                          ▼                                     │
                          ┌───────────────────────────────┐                    │
                          │   HUMAN REVIEW CHECKPOINT       │◄───────────────────┘
                          │   (interrupt/resume gate)        │
                          │   analyst approves/edits/rejects │
                          └───────────────┬─────────────────┘
                                          │ approved data only
                                          ▼
                               ┌───────────────────┐
                               │  Final Deal Memo    │
                               │  (versioned, audited)│
                               └───────────────────┘
```

The key structural change from the original brief: the original was a **fixed sequential pipeline** (Ingest → Research → Extract/Chart → Compile). That's replaced with a **supervisor/specialist pattern** — a lightweight planner agent that can call any specialist agent in any order, multiple times, in response to follow-up directives ("pull updated GitHub stars," "redo the ARR chart quarterly," "add a competitor to the comps table") — with the human review checkpoint sitting between "specialists have produced draft content" and "compilation finalizes the memo." This is the standard supervisor/interrupt pattern used in production LangGraph-style agentic systems ([Elastic Search Labs, 2026](https://www.elastic.co/search-labs/blog/human-in-the-loop-hitllanggraph-elasticsearch); [Towards Data Science, 2026](https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows/)), and it's what makes both the conversational interaction model and the mandatory review gate actually work architecturally, rather than being two features bolted onto a linear script.

**A layer above this diagram, not shown in it:** the Deal Sourcing Agent (§5.8) operates *before* a Deal exists at all, so it sits outside the per-deal Planner loop pictured above. Phase 0's `main.py` is a thin top-level router in front of both: it classifies a free-text request into "find candidate companies" (→ Deal Sourcing Agent) or "screen a specific deal" (→ the Planner, entering the diagram above) using the same small/fast-model classification approach as the Planner itself (§8) — deliberately not a general assistant, just a dispatcher between the two real Phase 0 capabilities. It does not claim capabilities that don't exist: a sourcing request that also asks for something out of scope (e.g. "help them raise funds" — a distinct, unbuilt service line, not an extension of finding candidates) gets an explicit note that it wasn't done, not a silent partial answer presented as complete.

---

## 5. Agentic flow — detail per component

### 5.1 Supervisor / Planner Agent

- Owns the conversation. Receives the user's plain-English directive, decides which specialist agent(s) to invoke, in what order, and whether the directive is a *new* task or a *revision* to existing deal state.
- Maintains a **per-deal state object** (§6) that all specialist agents read/write — this is what makes "redo the ARR chart with quarterly granularity" possible without re-running the whole pipeline: the planner sees that only the Analytics agent needs to re-run against already-extracted data.
- Runs on a small/fast model (see §8) — it needs low latency far more than it needs deep reasoning; its job is intent classification and routing, not financial analysis.
- Owns the interrupt/resume mechanics: when specialist agents have produced enough draft content for a review cycle, the planner raises the review checkpoint (§5.5) and pauses; on resume, it routes approved/edited data to the Compilation Agent and routes rejected items back to the relevant specialist with the reviewer's feedback attached.
- **The planner's own routing decision is itself subject to human confirmation before it executes** — not just the specialist agents' outputs. A planner that silently re-routes a deal on its own guess would be the same "review gate doesn't mean anything" failure mode §5.7 already guards against for Compilation, just applied to control flow instead of data.
- Phase 0's implementation (`agents/planner_agent.py`) splits routing into two modes: the happy-path pipeline progression (sign_mandate → ingest → extract → review → research → review_research → compile) is a deterministic state machine (`DealStatus`, §6.1) — routing that through an LLM would be theater, since there's only one sensible next step. The LLM (`llama3.2:3b` — upgraded from `1b` after `1b` was confirmed live to misclassify a directive once the valid-action set grew past ~2 options) classifies a free-text revision directive (e.g. "the burn number looks wrong, recheck it") into one of the *valid* actions for the deal's current state, with a hard fallback to the deterministic default if the model ever proposes an action outside that set. Validated live: a directive after a deal was already compiled was correctly classified into `rerun_extraction` targeting the right field, required human confirmation before executing (tested with a real, non-auto-confirmed run), and correctly forced the deal back through full review before it could be recompiled — and a second, differently-worded directive ("skip research, just compile") was correctly classified into `compile` rather than the deterministic default of `research`, confirming this is real intent classification, not just a lookup table.
- Every state transition is persisted (§6.3) so a deal can be resumed in a genuinely separate process, not just paused mid-`input()` within one still-running interpreter — validated live by driving a deal to `reviewed` in one Python process, exiting, then loading and continuing it from a second, independent process reading the same store.
- **Origination (Stage 2 of the lifecycle mapped in CLAUDE.md's findings): a signed mandate gates ingestion.** A real engagement needs the founder/company to actually agree to work with the shop — a pitch, a "beauty contest," a signed mandate or term sheet — before the shop acts on the company's confidential documents. `DealStatus.NEW` can now only transition to `MANDATE_SIGNED` (via `_run_sign_mandate`, which records `mandate_type`, a human-entered terms summary, and a timestamp — it does not pitch anyone or negotiate anything, it captures what a human already agreed to), and only `MANDATE_SIGNED` can transition to `INGESTED`. This applies uniformly whether the deal came from a promoted `SourcedLead` or was started directly — even a deal the shop already "has in hand" needs an engagement basis recorded before its financials are ingested.

### 5.2 Ingestion Agent

- PDF: layout-aware parsing (table detection + text, not a flat PyPDF text dump — flat text extraction is exactly what breaks table structure and later forces RAG-over-broken-tables, which was issue #2 in §1). Produces per-page structured blocks (text blocks, table blocks with cell coordinates) rather than one long chunked string.
- Excel: parsed with structure preserved (sheet/row/column references retained), not flattened to CSV before any validation — the original brief's mitigation ("normalize into CSV") is a reasonable *fallback* for genuinely messy sheets, but it should be a fallback after structured parsing fails, not the default path, because it discards the cell-reference provenance needed for §7.
- Output: a per-document manifest of typed blocks with page/cell coordinates, stored in the object + structured store, each block get a stable ID other agents cite against.

### 5.3 Structured Extraction Agent

- Takes the Ingestion Agent's typed blocks (not raw chunked text) and extracts against a fixed schema (ARR, MRR, growth rate, burn multiple, runway, cap table rows, headcount, funding history, etc. — see §6.2) using full-document-context prompting with schema-constrained output (Pydantic/JSON schema), which the research consistently shows outperforming vector retrieval for this class of task ([Unstract, 2026](https://unstract.com/blog/comparing-approaches-for-using-llms-for-structured-data-extraction-from-pdfs/)).
- Every extracted field carries: `value`, `source_block_id`, `source_page`, `confidence`, `extraction_method`. Fields the model can't find are marked `null` with `reason: "not_found_in_source"` — never filled with a plausible-looking guess. This is the concrete fix for the temperature=0 myth: the guardrail against hallucination is "no value without a source citation," not a decoding parameter.
- A second pass (same or different model, independent context) re-derives a small set of cross-checkable figures (e.g., does burn multiple recompute consistently from burn and net-new ARR as extracted?) and flags mismatches for the human reviewer rather than silently picking one. Phase 0's implementation (`agents/extraction_agent.py`) runs this as a deterministic, non-LLM recomputation — `runway_months` vs. `cash_on_hand / burn_monthly`, and `growth_rate_yoy` vs. `(arr - arr_prior_year) / arr_prior_year` — rather than a second model pass, since the check itself is pure arithmetic and doesn't need a second inference call. The growth-rate check caught a real failure mode in Phase 0 validation: the extraction model conflated a growth *multiple* stated in prose ("grew ARR 2.3x") with a percentage, producing a plausible-looking but wrong, cited value that the cross-check flagged rather than let through clean.
- Citation enforcement is done in code, not by trusting the model's compliance with the prompt: any value returned without a `source_block_id` that matches a real block in the document is rejected back to `null`/`not_found_in_source`, regardless of what the model claimed. This caught real cases in Phase 0 validation (e.g. cap table rows returned without their required `cap_table_source_block_id`).

### 5.4 Market Research Agent (RAG lives here, correctly)

- This is the one stage where RAG is actually the right tool: retrieving semantically similar comps, sector commentary, and qualitative context from a corpus of prior deals/sector notes is exactly what vector search is good at. FAISS + a mid-size embedding model (bge-large-en-v1.5, as in the original brief — this choice was fine) is appropriate here.
- Pulls from the data sources in §10, tagged by source and retrieval date, feeding the comps table and qualitative context sections of the memo — each finding cites its source URL, same provenance discipline as §5.3.
- Vector index is **scoped per tenant** (§9), never a single shared FAISS index across customers' deals.
- Phase 0's implementation (`agents/research_agent.py`) splits this into two parts, per §10.5's rule that research is corroborating signal, never the same confidence tier as a cited financial figure: (1) live lookups against the §10.1 zero-budget sources (GitHub, HN/Algolia, SEC EDGAR full-text search, Wikipedia — no API key needed for any of them, though SEC EDGAR and Wikipedia both require a descriptive User-Agent identifying the real requester per their own published policies, not a generic library string), and (2) FAISS + `bge-large` (pulled via Ollama, same model choice as above) over `research_corpus/sector_notes.json`, a small hand-authored seed corpus of general SaaS/hardware benchmark notes — Phase 0 has no real multi-deal corpus yet, so this seed proves the retrieval mechanism rather than standing in for real accumulated sector knowledge. That corpus should grow from real prior deals over time, not stay hardcoded.
- Every research finding goes through the same human review gate as extracted fields (§5.5) before it can appear in a memo — approve/reject per finding, shown in its own "External Signals" section clearly separated from the cited financials, exactly per §10.5.

### 5.5 Human Review Checkpoint

- Structurally, this is an `interrupt()`-style pause: the graph/state machine halts after Extraction + Research + Analytics have produced draft content, serializes state, and waits ([Elastic, 2026](https://www.elastic.co/search-labs/blog/human-in-the-loop-hitllanggraph-elasticsearch)).
- The reviewer (analyst) sees every extracted field and research finding next to its source citation and confidence score, can approve, edit, or reject each one individually (not just approve/reject the whole memo), and any manual edit is stored as the new authoritative value with `edited_by` + `edited_at` in the audit log.
- Resume: approved/edited fields flow to Compilation. Rejected or "needs more info" fields route back to the originating specialist agent with the reviewer's note attached, and the planner re-invokes that agent — this loop is bounded (max 2 auto-retries) before it's surfaced back to the reviewer as "couldn't resolve, needs manual input."
- Full detail in §12.

### 5.6 Analytics / Visualization Agent

- Deterministic, not generative: charts are rendered by code (matplotlib/plotly) against the *approved* structured data object, not drawn by having the LLM describe a chart in prose. The LLM's only role here is picking which standard chart template fits the available fields (e.g., skip the cap table pie chart if cap table data wasn't extractable) — the numbers themselves never pass through a free-text generation step.

### 5.7 Compilation Agent

- Assembles the reviewed, approved fields, findings, and chart artifacts into the memo template. Explicitly constrained to only insert data that exists in the approved state object with a citation — no field is "written" by this agent, only *arranged*. This is what makes the review gate actually binding: if compilation could still generate new numbers, the review step upstream wouldn't mean anything.
- Runs on the largest model in the stack (this is the one step where 70B-class reasoning is genuinely useful — narrative coherence, appropriate framing, flagging inconsistencies across sections) and is the one step where a 1–3 minute wait is acceptable, because it's a single "finalize" action, not a conversational back-and-forth.
- Phase 0's implementation (`agents/compilation_agent.py`) extends the "numbers never pass through free-text generation" principle from §5.6 to the memo's narrative paragraph too: the one LLM call in this agent (a short qualitative framing paragraph) is explicitly instructed to contain no digits, and its output is checked post-hoc and **discarded** — not sanitized and kept — if it contains one anyway. Every numeric line in the memo body itself comes from Python string formatting against the approved `ExtractionResult`, never from the model.

**Addendum — the real three-document suite, not one generic memo.** Checked against how IB/VC engagements actually structure outreach (cross-referenced against multiple industry sources, not taken on faith from any single AI-generated proposal — see CLAUDE.md's findings log for the fabricated claims that surfaced along the way): a real engagement produces three distinct documents, not one. Phase 0 now builds all three (`compile_cim`, `compile_teaser`, `generate_proforma_projection`/`compile_proforma_document`):

1. **CIM** (`compile_cim`, formerly `compile_memo`) — the original comprehensive document: full financials, cap table, funding history, external signals. For NDA-gated parties.
2. **Anonymous Teaser** (`compile_teaser`) — the actual first document sent to a prospective investor, *before* any NDA. The real anonymization requirement is about **identity**, not the numbers: cap table, funding history, and external signals are excluded entirely (a specific investor name or a GitHub repo's full name is itself identifying in a small ecosystem, not just the company's own name), and the company name is scrubbed from the rendered document as defense-in-depth. The one-line business description is supplied by the human reviewer, never generated — there's no extracted "what does this company do" field in §6.2's schema, and free-text-generating marketing copy with no grounded input would violate §7's provenance principle. Requires an explicit human sign-off (`MemoVersion.approved_by`) that the document doesn't leak identity before it's treated as safe to send — the concrete implementation of the "NDA/anonymization boundary" that an early proposal correctly flagged as missing, even though several of that same proposal's specific technical suggestions turned out to be fabricated (see CLAUDE.md).
3. **Pro-Forma Model** (`generate_proforma_projection` + `compile_proforma_document`) — a genuinely different kind of document: it computes *projected* numbers rather than arranging *extracted* ones. Same non-negotiable principle either way (pure deterministic arithmetic, never LLM-generated), but projections carry an explicit, human-visible assumptions list (growth rate, burn trajectory, no additional funding modeled) and a `PROJECTED, NOT EXTRACTED` banner — never presented at the same confidence tier as a cited historical figure (§10.5's "supporting signal, not verified fact" principle, applied here to time instead of source type). The reviewer can override the growth-rate assumption directly rather than just approving/rejecting the output after the fact, and the model flags — deterministically, not via LLM judgment — if projected cash on hand goes negative within the horizon.

None of the three is gated behind another: a Teaser or Pro-Forma can be generated as soon as a deal is `REVIEWED` (`is_ready_for_compilation()` true), matching real practice where a teaser goes out well before a full CIM is assembled.

### 5.8 Deal Sourcing Agent (the top of the funnel for the sourcing → incubation → fundraise lifecycle, §2)

- **Distinct job from §5.4.** The Market Research Agent corroborates a deal that already exists in the pipeline (a founder submitted documents). The Deal Sourcing Agent instead surfaces *candidate* companies nobody has submitted yet — pure origination, feeding the top of the funnel rather than supporting a deal already in review.
- **Output is a lead, not a deal.** A sourced candidate becomes a `SourcedLead` (§6.1) — company name, sector tag, a couple of discovery signals, and where it came from. It does **not** enter the `Deal`/`ExtractionResult` pipeline until a human analyst deliberately reviews and promotes it (`agents/planner_agent.promote_lead_to_deal()`) to an actual deal (at which point it goes through Ingestion → Extraction like anything else, once real documents exist for it) — sourcing a lead is not the same claim as screening a deal, and the two must not be blurred. This is the literal on-ramp from "found a candidate" to "incubating it toward a raise."
- **Sourcing is corroborating-signal-only, same discipline as §10.5.** A `SourcedLead`'s discovery signals (e.g. "repo using a payments API, created this month") are a reason to *look at* a company, not a claim about its financials — nothing here ever populates an `ExtractedValue`.
- **Dynamic by design, not hardcoded.** Phase 0 initially hardcoded both a single sector keyword and an India-only owner-location filter; both are now parameters, resolved fresh per request by `main.py`'s router from whatever the user actually asked for (sector keyword always; a geography filter only if one was explicitly named, otherwise the search is global). Discovery also filters by *repo creation date*, not last-updated — a genuinely new repo is a much better "what's happening in this space right now" signal than an old repo that happened to get a commit recently.
- **Sources: see §10.6.** Two live connectors: GitHub (repos created recently matching a theme) and HN/Algolia "Show HN" launches — both already-legitimate sources (§10.1), independent of each other so a closed-source launch with no public repo can still surface via HN. Most of the sources that would give broader coverage (YC's directory, Product Hunt, DuckDuckGo, MCA/registrar scraping, UpForge, campus incubator portals) either fail the same legitimacy bar that excluded Apollo/pytrends/Crunchbase, or need an actual licensing conversation this document can't complete on its own — that doesn't change just because a request asks for broader coverage. Widening this later means widening it through real permission, not by quietly relaxing the bar §10 already set.
- **Clone/spam filtering is required, not optional.** Live testing surfaced the same repo name hosted under many different owner accounts in one result set (a "fintech" search returned 9 accounts all hosting an identical repo) — the signature of a star-farming clone network, not 9 distinct companies. Deduplicating by repo name within one discovery call is now built in; this is a real data-quality risk any code-hosting-search-based discovery connector needs to account for, not a one-off.
- **No LLM needed for discovery itself** — the GitHub/HN connectors are deterministic API calls, same shape as the Market Research Agent's own connectors (§5.4). The one LLM call in the lifecycle (`main.py`'s router) only classifies intent and extracts the search theme/geography from free text — it never invents a discovery signal that didn't come from an actual API response, same principle as §5.6/§5.7.
- **Owned by the Planner, not a separate script.** `agents/planner_agent.py` exposes `source_leads()` and `promote_lead_to_deal()` alongside the per-deal state-machine functions (§5.1) — the whole lifecycle (source → mandate → ingest → extract → review → research → compile) is one module's responsibility, which is what makes "promote this lead and start screening it" a single coherent operation instead of two disconnected tools that happen to share a database.
- **A second, distinct sourcing mode: IB-style (`discover_ib_targets()`).** VC-style sourcing (above) surfaces early-stage candidates via developer/launch activity. IB-style sourcing targets a genuinely different company type — mature, typically public companies signaling an approaching transaction window — and uses a genuinely different, legitimate signal: SEC EDGAR full-text search (already-cleared, §10.1) for standard M&A-process language ("exploring strategic alternatives," "engaged a financial advisor") combined with a sector keyword. This is real analyst practice on a first-party disclosure, not an inference from public activity, and it is deliberately kept as a separate function rather than blended into `discover_leads()` — conflating "early-stage candidate" and "mature M&A target" in one result set would misrepresent what a hit means, the same "don't blend confidence tiers" principle §10.5 already applies to data type, applied here to company type. Validated live against real SEC filings: a "fintech" search surfaced actual public companies (Bakkt Holdings, Green Dot Corp, OneSpan, Everi Holdings) with real, dated 8-K/10-K filings containing the searched phrases.

### 5.9 Roadshow / Investor Tracking (Stage 5 of the lifecycle — demand book)

- **Pure record-keeping for a human-led process, same boundary as sourcing.** `main.py`'s `SOURCING_SCOPE_NOTE` already states explicitly that this system doesn't contact investors or run the raise; investor tracking is the same principle applied to the Roadshow stage. `add_investor()`/`InvestorContact` (§6.1) record that a human already reached out and what the investor said — the system never sends a teaser, requests an NDA, or contacts anyone itself.
- **Lightweight by design.** One record per tracked investor per deal: name, firm, NDA status, interest level, freeform notes. No workflow automation (no automatic follow-up reminders, no status-change triggers) in Phase 0 — this is a demand book a human reads and updates, not a CRM sequencing engine.
- **Available once there's something to show an investor.** Valid from `REVIEWED` onward (same gate as the Teaser), not gated behind a compiled CIM — real practice tracks initial outreach interest well before the full document package exists.

---

## 6. Data model

### 6.1 Core entities

```
Deal
 ├─ id, tenant_id, name, stage, created_at
 ├─ status: new | mandate_signed | ingested | extracted | reviewed | needs_manual_input |
 │          researched | research_reviewed | compiled   # the Planner's state machine, §5.1
 ├─ mandate_type, mandate_terms_summary, mandate_signed_at   # Origination, §5.1 addendum
 ├─ documents: [Document]
 ├─ extracted_fields: [ExtractedField]
 ├─ research_findings: [ResearchFinding]
 ├─ charts: [ChartArtifact]
 ├─ memo_versions: [MemoVersion]
 ├─ investor_contacts: [InvestorContact]   # Roadshow, §5.9
 └─ audit_log: [AuditEvent]
 # Phase 0's store (§6.3) persists documents/extracted_fields/etc. as their
 # own rows keyed by (tenant_id, deal_id) rather than nested arrays on this
 # record -- same entities, a flatter storage shape, not a different design.

Document
 ├─ id, tenant_id, deal_id, filename, type (pdf|xlsx), storage_uri
 └─ blocks: [DocBlock]   # from Ingestion Agent

DocBlock
 ├─ id, document_id, page, block_type (text|table), coordinates, content

ExtractedField
 ├─ id, tenant_id, deal_id, field_name, value, unit
 ├─ source_block_id, source_page, extraction_confidence
 ├─ status: proposed | approved | edited | rejected | not_found
 ├─ reviewer, reviewed_at, edit_note

ResearchFinding
 ├─ id, tenant_id, deal_id, topic, content, source_url, source_type (github|hackernews|sec_edgar|wikipedia|internal_sector_notes|manual)
 ├─ retrieved_at, status: proposed | approved | rejected

ChartArtifact
 ├─ id, tenant_id, deal_id, chart_type, source_field_ids: [ExtractedField.id], storage_uri

MemoVersion
 ├─ id, tenant_id, deal_id, version_number, generated_at, approved_by, content_uri
 └─ document_type: teaser | cim | proforma   # §5.7 addendum's three-document suite

AuditEvent
 ├─ id, tenant_id, deal_id, actor, action, target_id, timestamp, before, after

SourcedLead
 ├─ id, tenant_id, company_name, sector_tag
 ├─ discovery_signals: [{content, source_url, source_type, discovered_at}]
 ├─ status: new | reviewed | promoted_to_deal | dismissed
 ├─ promoted_deal_id (nullable -- set once an analyst promotes this to an actual Deal)

InvestorContact
 ├─ id, tenant_id, deal_id, investor_name, firm
 ├─ teaser_sent_at, nda_status: not_sent | sent | signed, cim_shared_at
 ├─ interest_level: new | cold | warm | hot | passed | committed
 └─ notes, updated_at
```

### 6.2 Standard extraction schema (starting set — extend per deal type)

```json
{
  "arr": {"value": null, "unit": "USD", "source_block_id": null, "confidence": null},
  "arr_prior_year": {"value": null, "unit": "USD", "source_block_id": null, "confidence": null},
  "mrr": {"value": null, "unit": "USD", "source_block_id": null, "confidence": null},
  "growth_rate_yoy": {"value": null, "unit": "%", "source_block_id": null, "confidence": null},
  "burn_monthly": {"value": null, "unit": "USD", "source_block_id": null, "confidence": null},
  "cash_on_hand": {"value": null, "unit": "USD", "source_block_id": null, "confidence": null},
  "runway_months": {"value": null, "source_block_id": null, "confidence": null},
  "headcount": {"value": null, "source_block_id": null, "confidence": null},
  "cap_table": {"rows": [{"holder": null, "pct": null, "share_class": null}], "source_block_id": null},
  "funding_history": {"rounds": [{"round_name": null, "amount": null, "date": null, "lead_investor": null}]}
}
```

Every leaf carries `source_block_id`/`confidence` so nothing in the schema can be filled without traceability — a field with no matching source stays `null`, it is never inferred from "typical" values for a company of this type.

### 6.3 Persistence (Phase 0: SQLite, not deferred)

Originally scoped as "introduce a DB later," this turned out to be a Phase 0 dependency, not a Phase 1+ nice-to-have: the Planner's interrupt/resume mechanics (§5.1, §5.5) aren't real if nothing survives a process restart. Pausing on an `input()` call within one still-running Python process is not the same claim as "serializes state and waits" — an in-memory-only pipeline can't actually be resumed later, in a different process, the way §5.5 describes.

`store.py` implements this with SQLite: one row per entity (`Deal`, `Document`, `ExtractionResult`, `ResearchFinding`, `ChartArtifact`, `MemoVersion`, `AuditEvent`, `SourcedLead`), each stored as a JSON blob of its Pydantic serialization rather than normalized into columns — pragmatic for Phase 0's single-process, low-volume usage, not a permanent architectural commitment. Revisit if this becomes a real concurrent-writer multi-tenant service.

**Every read is tenant-scoped by construction**, not just by caller discipline: each `Store` method takes `tenant_id` and filters on it in the SQL `WHERE` clause itself. A caller that passes the wrong `tenant_id` for a real id gets `None`/an empty list back, not another tenant's data — the same discipline §9 already requires of the FAISS index in §5.4, extended here to the persistence layer itself. Verified live: cross-tenant reads (`get_deal`, `get_extraction_result`) against real data in a running process correctly returned nothing.

---

## 7. Guardrails & factuality (replacing "temperature=0 = no hallucinations")

1. **Provenance is mandatory, not optional.** No numeric field reaches the memo without a `source_block_id` (extracted) or `source_url` (researched). This is enforced at the schema level, not by prompting the model to "be accurate." This applies per-item, not just per-field: each `funding_history` round carries its own `source_block_id`/`source_page` (a Phase 0 fix — rounds were initially extracted without one, which is exactly the kind of uncited number this rule exists to catch), since different rounds can legitimately come from different blocks of the document.
2. **Independent cross-check pass.** A second, separately-scoped pass re-derives any figure that has an algebraic relationship to others (burn multiple, growth rate consistency across periods) and flags disagreement rather than resolving it silently.
3. **Confidence scoring surfaces uncertainty instead of hiding it.** Low-confidence extractions are visually flagged to the reviewer, not silently included at face value.
4. **"Not found" is a valid, expected output.** The extraction schema treats missing data as a first-class state (`not_found_in_source`), removing the incentive for the model to pattern-match a plausible-sounding number.
5. **Human review is the backstop, not the first line of defense.** Everything above exists so the reviewer's job is auditing flagged/low-confidence items quickly, not re-deriving every number from scratch — which is what makes the review gate operationally sustainable rather than a rubber stamp people learn to skip.
6. **Temperature=0 is kept, correctly scoped**: it's used for reproducibility (same input document set → same extraction output, which matters for auditability and for re-running after a correction), not marketed as a factuality guarantee.

---

## 8. Model & infrastructure strategy (tiered — infra is flexible, privacy is not)

### 8.1 Why one 70B model for everything is the wrong shape

Recomputing the brief's own numbers with a realistic throughput: partial CPU offload of a 70B model on a single 24GB GPU (36/80 layers on GPU, the rest streamed through system RAM) lands in the **2–8 tok/s** range in practice — even a *fully GPU-resident*, more aggressively quantized 70B on a 24GB consumer card benchmarks around 18 tok/s ([mustafa.net, 2026](https://mustafa.net/llm-tokens-per-second-benchmarks/)). A deal memo's total generation load across all agent calls (extraction narrative, research synthesis, chart captions, compiled memo prose) easily runs 2,000–4,000+ output tokens. At 2–8 tok/s that's **8–33 minutes**, not the brief's claimed 1.5–3 minutes. That number matters a lot now that the interaction model is conversational/iterative — a 10+ minute round-trip on every follow-up directive kills the UX the stakeholder just asked for.

### 8.2 Right-sized allocation per agent

| Agent | Latency need | Reasoning need | Model class |
|---|---|---|---|
| Supervisor/Planner | Low latency, called every turn | Light (intent classification, routing) | Small (7–8B class), fully GPU-resident, no offload |
| Ingestion | Low latency | None (deterministic parsing + light OCR/layout model) | Non-LLM parser + small vision-language model only if needed for scanned docs |
| Structured Extraction | Medium | Medium (schema-following, needs long context) | Mid-size (8–34B class, quantized to fit fully in VRAM — no CPU offload) |
| Market Research (RAG) | Medium | Medium | Mid-size, same tier as extraction; embedding model bge-large-en-v1.5 (kept from original brief — good choice) |
| Analytics | Low (mostly deterministic code) | Minimal | Small, or no LLM at all for the chart-rendering step itself |
| Compilation | Latency tolerant (single finalize action) | Highest (narrative coherence across sections) | Largest available tier (70B-class if self-hosted; or a frontier API model in tenants where the customer's data-handling terms permit it) |

This is the direct fix for the false economy in the original design: it wasn't that the 70B model was a bad choice, it's that using it for *every* step meant paying 70B latency for steps that never needed 70B reasoning.

### 8.3 Deployment tiers (since infra is flexible but privacy is not)

- **Tier A — "Max Privacy" (self-hosted, customer VPC or on-prem):** All models above run locally, sized to fit the customer's hardware without heavy CPU offload wherever possible. This is the direct descendant of the original brief's approach, corrected per §8.2. Right customer profile: funds with strict data-residency mandates.
- **Tier B — "Hybrid":** Planner/ingestion/extraction stay local (these touch raw deal documents); compilation and/or research may optionally call a private-tenancy cloud API (e.g., a provider offering a signed DPA/no-training-on-data terms) for the steps that benefit most from a larger model, when the customer's data-handling policy permits it. This is the tier likely to be most attractive to a paying customer who wants speed without full self-hosting overhead.
- **Tier C — "Managed" (future):** Fully managed multi-tenant hosting by the vendor, for customers who don't need dedicated infra. Requires the multi-tenancy work in §9 to be solid first — do not offer this tier before that's built.

The point of structuring it this way: the same agent architecture serves all three tiers — only the model-hosting configuration changes, which is what "fully flexible infra, non-negotiable privacy" actually requires architecturally.

---

## 9. Multi-tenancy & security (required now that this is a product, not a personal tool)

The original single-user SSH-tunnel access model (§3 of the brief) is fine for a solo POC and wrong for anything sold to more than one customer. Changes required:

- **Per-tenant data isolation**: separate vector index namespace (or separate index entirely) per tenant, separate structured-store schema/row-level tenant key, separate object storage prefix/bucket per tenant. Never a single shared FAISS index across customers.
- Phase 0 fix: `tenant_id` was inconsistently present in the schema — only `SourcedLead` had it from the start. Added to `Document`, `ExtractionResult`, `ResearchFinding`, `ChartArtifact`, `MemoVersion`, and `AuditEvent` (§6.1), and the SQLite store (§6.3) enforces the row-level tenant key at the query level, not just in application code: every read method takes `tenant_id` and filters on it in the SQL itself, so a caller bug (wrong tenant_id for a real id) returns nothing rather than another tenant's data. Verified live, not just designed: a second tenant's process could not read the first tenant's `Deal` or `ExtractionResult` by id.
- **Application-layer auth** (proper user accounts + role: analyst vs. reviewer/approver) replacing raw SSH port-forwarding as the access model — SSH tunneling is appropriate as a *transport* hardening measure for a single admin, not as the product's access control.
- **Encryption at rest/in transit**: keep the original brief's instincts here (KMS-backed EBS encryption, no public inbound ports) — these were good and should carry forward unchanged, just layered under proper application auth rather than being the only gate.
- **Audit log is a product requirement, not a nice-to-have**, given the target buyer (funds are compliance-sensitive): every approval/edit/rejection in §5.5 is already modeled into `AuditEvent` — this should be exposed to the customer, not just kept internally.
- **Per-customer deployment choice (§8.3) is itself a security/sales feature**: being able to say "your data never leaves your VPC" to a Tier A customer, contractually, is a meaningful differentiator versus a monolithic SaaS-only competitor.

---

## 10. Alternative data sourcing — zero-budget, fully open/free, legitimacy-checked

The constraint for this revision: **no paid API, no paid tier, no free-trial-that-needs-a-card, for the market-research stage.** Everything below was checked against two bars, not one — "is it actually free" (most things claim this) and "does its own terms of service actually allow the use we're putting it to" (most sourcing failures happen here, not on price). The table below replaces §10 in full; where a "free" source failed the legitimacy bar, it's excluded rather than footnoted, because a product pitched to compliance-conscious funds can't ship with a data source whose ToS it's already violating.

### 10.1 What's fully free *and* legitimately usable in a resold, multi-tenant product

| Source | What it actually gives you | Free-tier reality (verified) | Legitimacy |
|---|---|---|---|
| **SEC EDGAR** (full-text search + XBRL structured financial data, `data.sec.gov`) | Public company financials back to 1994/95, structured (XBRL) — the backbone of any "sector comps / valuation multiples" claim; full-text search across all filings can surface a private company's name mentioned in a public company's S-1, 10-K, or litigation filing (customers, competitors, acquirers referencing it) | No API key, **10 requests/second**, unlimited volume otherwise; only requirement is a descriptive `User-Agent` header identifying the requester ([SEC.gov](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)) | Official U.S. government open data. This is as legitimate as a data source gets. |
| **FRED (Federal Reserve Economic Data)** | Macro and sector-level series (interest rates, sector indices, inflation) to contextualize valuation multiples and growth-rate benchmarks | Free registration, generous published rate limits, official St. Louis Fed API ([fred.stlouisfed.org/docs/api](https://fred.stlouisfed.org/docs/api/fred/overview.html)) | Official U.S. government open data. |
| **GitHub REST API** | OSS traction signal (stars, forks, commit velocity, contributor count) for any deal with a public repo | Confirmed free, generous authenticated rate limits — this held up from the original brief unchanged | Fully within GitHub's own ToS — it's the intended use of a public API. |
| **Hacker News (via the Algolia HN Search API)** | Mentions/discussion of the company or founders, an informal but real qualitative signal | Free, no key required, generous limits | Official, sanctioned API for HN's own data. |
| **USPTO Open Data Portal / PatentsView** (PatentsView is migrating into the Open Data Portal but staying free — [USPTO, 2026](https://www.uspto.gov/subscription-center/2026/patentsview-migrating-uspto-open-data-portal-march-20)) | Patent filings/grants as an IP-moat signal — useful for hardware/deep-tech deals specifically | Free, official | Official U.S. government open data. |
| **OpenCorporates** | Legal entity existence, jurisdiction, incorporation status, officers — a legitimacy/KYB-style check, not a funding database | Genuinely free tier exists, but it's modest (community reports of ~200 queries/month on the free key before you need to apply for research/nonprofit access) — treat as "spot-check," not "bulk enrich every deal" | Aggregates official government company registries under an open-data mandate; using it as intended (entity lookups) is clean. |
| **Wikipedia / Wikidata** | Structured facts for the subset of companies notable enough to have an entry — founding date, notable funding events, leadership | Free, open license (CC BY-SA / CC0) | Explicitly licensed for reuse, including commercial. |
| **Damodaran Online** (NYU Stern, `pages.stern.nyu.edu/~adamodar`) | Annually updated sector-level WACC, margins, capex ratios, EV/Sales multiples — global and emerging-market cost-of-capital and valuation benchmarks | Free, static Excel/CSV download, no key, no rate limit (download once, cache locally rather than re-fetch per deal) | Academic data explicitly published by the author for public reuse. |
| **DBIE — Database on Indian Economy** (Reserve Bank of India) | India-specific macro/fiscal series (MCLR, treasury rates, sector credit indicators) for India-market valuation context | Free, static file downloads from the official RBI portal | Official Indian government open data — same class as SEC EDGAR/FRED. |
| **data.gov.in** (Open Government Data Platform India, direct — not via a third-party aggregator) | Official Indian government open datasets, including DPIIT-recognized-startup statistics | Free, published under the Government Open Data License – India, which explicitly permits commercial reuse | Official Indian government open data. Note (unverified as of this writing, site blocks automated fetching): the DPIIT startup dataset here appears from its own description to be **aggregate statistics** (counts by state/sector/year), not a row-level list of individual companies — confirm this by hand before assuming it can source individual deal candidates. |

### 10.2 Usable, but only for the narrow thing they're good for

| Source | Use it for | Caveat |
|---|---|---|
| **Alpha Vantage** | A handful of public-market comps' price/valuation data per deal, as a supplement to EDGAR | Free tier is **25 requests/day, 5/minute** ([macroption.com](https://www.macroption.com/alpha-vantage-api-limits/)) — that's fine for pulling 3–5 comp tickers per deal, not for bulk sector screening. Budget the Market Research Agent's calls accordingly (cache aggressively, don't re-pull comps that haven't changed). |
| **Common Crawl** | The subject company's *own* public website content (product pages, pricing pages, team pages) when you don't want to fetch it live | Common Crawl's own license is fine for reuse, but its terms are explicit that **crawled content stays subject to the original site's own terms** ([commoncrawl.org/terms-of-use](https://commoncrawl.org/terms-of-use)) — safe for a company's own public marketing pages (they intend that to be public and indexed), not a backdoor around a site whose ToS forbids scraping (see §10.3). |
| **Direct fetch of the subject company's own public site** | Same content as above, fresher | This is first-party content the company itself published for public consumption — the cleanest possible source, just fetch it directly rather than via a crawl dataset when latency allows. |

### 10.3 Explicitly excluded — free is not the same as legitimate

| Source | Why it's excluded despite being "free" |
|---|---|
| **Scraping Crunchbase, LinkedIn, or Similarweb profiles** | Crunchbase eliminated its free API tier entirely in 2025 (cheapest plan is now $49/mo — [dev.to, 2026](https://dev.to/agenthustler/crunchbase-api-in-2026-free-tier-gone-what-startup-data-hunters-do-now-1177)); the "free" workaround these sites' own communities discuss is browser-automation scraping of public profile pages, which is a ToS violation on all three platforms and exactly the "not legitimate" outcome this constraint is meant to avoid. Do not build this in, even as an optional toggle. |
| **Unofficial Google Trends wrappers (e.g., pytrends)** | Not an official API — it's reverse-engineering an undocumented endpoint. Fine for a personal side project; not something to embed in a product sold to compliance-sensitive customers. |
| **Apollo.io — for this product specifically** | See §10.4 — this isn't a "free tier is thin" problem like OpenCorporates, it's a flat contractual prohibition. |

### 10.4 Apollo.io: dropped, not just deprioritized

The original brief and even the first revision of this document treated Apollo as a usable low-cost source. On checking Apollo's actual API Terms of Service, that's wrong for this product's shape specifically: Apollo's terms state "*You may not sublicense, sell, or distribute (including but not limited to sharing) the APIs*," bar integrating the API into a third-party product without Apollo's specific written authorization, and license API access "*solely for your internal business purposes*" ([apollo.io/terms/api](https://www.apollo.io/terms/api)). A product that pulls Apollo data through one account and serves it to many paying customers is precisely the "integrate into your product/services" case the terms prohibit — this is true on the free tier and would still be true on a paid tier without a separate commercial agreement. Given the zero-budget constraint and the "legitimate" requirement, Apollo is removed from the architecture entirely rather than kept as a "cheap signal." If a future customer conversation makes headcount/contact-traction data valuable enough to be worth negotiating a real Apollo partnership agreement, that's a Phase 2+ commercial decision, not a default data source.

### 10.5 The honest gap this leaves, and how the architecture compensates

There is no free, ToS-clean equivalent of Crunchbase/PitchBook-grade private-company funding data. That's not a research gap this document can close — it's the actual reason those products charge money: comprehensive private funding-round data is expensive to assemble and is exactly what's being monetized. Pretending a free substitute exists at the same coverage level would be the same overclaiming problem as the original brief's "temperature=0 eliminates hallucinations."

What this means concretely for the Market Research Agent (§5.4):
- **The deal's own submitted documents (pitch deck, financials, cap table) remain the primary source of truth for that company's own numbers** — this was already true in the architecture (§5.3's Structured Extraction Agent), and it matters more now: the Market Research Agent's job is external corroboration and sector context, not filling in gaps in the company's own self-reported data.
- **Public-company comps (EDGAR + Alpha Vantage) stand in for "sector multiples"** where the deal is in a sector with public comparables (fintech, SaaS, biotech) — this is a legitimate and common analyst practice, not a downgrade.
- **Qualitative/traction signals (GitHub, HN, patents, the company's own site) corroborate the story rather than independently verify the financials** — the memo template and the review UX (§12) should present these explicitly as "supporting signal," never blended into the same confidence tier as a cited financial figure from the deal's own documents.
- **If a specific customer later needs Crunchbase-grade funding-round coverage, that becomes an explicit, budgeted, customer-funded add-on (their own Crunchbase/PitchBook seat, queried through their own credentials) — never something silently built into the default zero-budget pipeline.**

### 10.6 Deal Sourcing sources (India focus) — legitimacy-checked for the Deal Sourcing Agent (§5.8)

These are distinct from everything above: §10.1–10.5 are about *researching a deal already in hand*. The sources below are about *finding new companies to consider in the first place* — evaluated against the same two-bar test (actually free, and actually within the source's own ToS for this use), verified via direct ToS lookups, not assumed from a source's popularity.

**Usable:**

| Source | What it gives you | Legitimacy |
|---|---|---|
| **data.gov.in DPIIT dataset** (direct, official) | India-wide startup counts by state/sector/year (§10.1's caveat about aggregate-vs-row-level applies) | Government Open Data License – India, commercial reuse explicitly permitted |
| **GitHub REST API**, `location:india` + sector-keyword queries (e.g. Razorpay/Cashfree integration, regional tax-calc libraries) | New public repos as an early discovery signal for India-based technical founders | Same official, sanctioned API already used in §10.1 — this is just a different query shape against the same legitimate source |
| **SEC EDGAR full-text search** | Indian-subsidiary or competitor mentions inside US public filings (e.g. "acquisition of Indian subsidiary") | Already-established official U.S. government source (§10.1) |

**Explicitly excluded — verified against actual policy text, not assumed:**

| Source | Why |
|---|---|
| **yfinance** | Confirmed: unofficial wrapper against Yahoo's undocumented endpoints. Yahoo's own API terms explicitly prohibit "deriving income... for commercial or monetary gain" from the data. Same category as the already-excluded pytrends. |
| **Y Combinator directory via its "hidden" search endpoint** | Confirmed: no official API, no published terms for this use — it's the undocumented Algolia index the site's own filter UI calls internally. Publicly visible on a webpage is not the same as authorized for automated reuse in a resold product. Same category as pytrends. |
| **Peerlist launch feeds via "network endpoint extraction"** | Same undocumented-endpoint pattern as YC above — no official API exists for this. |
| **Product Hunt API v2** | Confirmed: ToS explicitly states the API "must not be used for commercial purposes" and prohibits redistributing the data to third parties without a separate agreement. Same category as Apollo (§10.4) — a flat prohibition, not a thin-free-tier problem. |
| **DuckDuckGo HTML/Lite scraping** | Confirmed: ToS prohibits automated, non-personal use; actively enforced (403s, throttling on volume). Same category as pytrends/Google Trends. |
| **MCA21 / regional registrar notice-board scraping** | Confirmed: MCA's own terms of use state "unauthorized use of this web site and system... including... misuse of any information posted on this site is strictly prohibited and would attract both penal and punitive action." This is a stronger prohibition than a typical civil ToS violation — treat as a hard exclusion, not a gray area, regardless of how many public scrapers exist on GitHub for it. |

**Needs an actual conversation with the source before use — genuinely ambiguous, not a clean yes or no:**

| Source | Why it's not a default source |
|---|---|
| **UpForge Indian Startup Registry** | Its terms restrict use to "lawful due diligence, research, and professional analysis" (which this product's use case arguably fits) but don't address automated/bulk extraction either way, and UpForge is actively building a paid API tier for "verified investors, researchers, and institutions" — meaning the intended access path for exactly this use case is a future paid product, not today's public pages. Contact them for explicit permission before building a scraper against it. |
| **Elite Indian campus incubator portals** (SINE/IIT Bombay, IITM Research Park, CIIE.CO/IIM Ahmedabad, FITT/IIT Delhi, BITS Pilani Incubator) | No published terms found either way. Lower risk than a commercial ToS violation (these are institutional public-portfolio pages), but unverified per this document's own standard — check each site's terms/robots.txt individually before scraping any of them; don't treat "no terms found" as "cleared." |

**The honest gap this leaves (same shape as §10.5):** there is no free, ToS-clean, row-level "new Indian startups this month" feed. The Deal Sourcing Agent's real Phase 0 coverage is: aggregate DPIIT sector context (not individual leads), GitHub-based technical-founder discovery (a real but narrow signal), and whatever the excluded/ambiguous sources above eventually become if a real licensing conversation happens. Overclaiming broader coverage than this would repeat the exact mistake §10.5 already corrects once.

---

## 11. Cost model — corrected and reframed per deployment tier

**What held up from the original brief:** the g5.4xlarge on-demand price of ~$1.62/hr is accurate ($1.624/hr, [Vantage](https://instances.vantage.sh/aws/ec2/g5.4xlarge)), and the instinct to auto-shutdown idle instances is a good cost control to keep.

**What needs correcting:**

1. **Per-memo compute cost, recalculated.** With right-sized models (§8.2) instead of one 70B model for every step, most conversational turns (planner routing, ingestion, extraction) run on a small model that's fast and cheap even on modest hardware; only the compilation step needs the expensive large-model pass, and it runs once per memo version rather than once per turn. This is a materially better cost profile than the original "everything through 70B" design, even before counting the iteration/conversation turns the stakeholder now wants supported.
2. **"Hours per working day" doesn't map to a multi-tenant product.** The original formula (104.9 compute-hours/month ÷ 22 days ≈ 4.76 hrs/day) assumes one user with one usage pattern. A sellable product needs a per-deal or per-seat cost model instead: estimate compute cost *per deal memo produced* (ingestion + extraction + research + N conversational revision turns + one compilation pass), then multiply by expected deals/month per customer. This is the number that actually determines pricing and margin, and it can't be derived until Tier A vs. Tier B (§8.3) is chosen per customer, since Tier B shifts some compute cost to a metered API instead of fixed instance-hours.
3. **Idle-shutdown guardrail should be kept but reconsidered for multi-tenant.** A hard `shutdown -h now` after 10 minutes of no SSH sessions makes sense for a solo dev box; for a customer-facing deployment it needs to be "scale to zero / scale up on request" at the application layer (e.g., spin up the extraction/compilation model pod on demand, not tied to SSH session presence, which won't exist in a proper multi-user product).

4. **The market-research data layer is now a $0 recurring line item, by design.** With the zero-budget stack in §10, the ₹15,000/month budget is entirely a compute number (GPU instance-hours, storage) — there's no data-API subscription hiding in it. The only "cost" the free-tier data sources impose is a rate-limit constraint on the Market Research Agent (batch and cache calls to Alpha Vantage's 25/day and OpenCorporates' modest free quota, per §10) rather than a dollar figure — worth stating explicitly since the original brief's budget math didn't separate compute cost from data cost at all.

**Recommendation:** treat the original ₹15,000/month figure as the right order of magnitude for a **solo POC / Phase 0 build** (§13), and defer a real per-customer cost model until after Tier A vs. B economics are validated against actual pilot usage.

---

## 12. Human review UX (detail)

- Reviewer sees a single screen per deal: extracted fields grouped by category (financials, cap table, research findings), each row showing value, source citation (clickable — jumps to the highlighted page/cell in the source doc), confidence badge, and three actions: **Approve / Edit / Reject**.
- Cross-check mismatches (§7.2) are visually distinguished (e.g., a warning badge) and cannot be silently approved in bulk — bulk-approve skips only fields with no flags.
- Editing a field records the new value plus `edited_by`/`edited_at`/`edit_note` in the audit log; the edited value becomes the new source of truth for compilation, superseding the model's extraction.
- Rejecting a field routes it back to the originating agent with the reviewer's note, bounded to 2 automatic retries before it's kicked back to the reviewer as "needs manual input" rather than looping indefinitely.
- Only once every required field is in `approved` or `edited` state (or explicitly marked `not_found` and acknowledged by the reviewer) can the Compilation Agent be invoked — this is enforced by the planner, not left as a convention.

---

## 13. Roadmap

**Phase 0 — Local, zero-cloud validation (CPU-only, your own hardware, no AWS spend at all)**
- Full agent set implemented against small open models sized for CPU-only inference (§15) — no GPU, no cloud, no spend of any kind, including free-tier cloud. This now includes the Deal Sourcing Agent (§5.8), added when the product's scope grew from "screen a submitted deal" to "also help find deals worth screening" — its Phase 0 source coverage is intentionally thin (§10.6) since most of the obvious India-specific sources failed the same legitimacy bar that already excluded Apollo/pytrends/Crunchbase.
- Goal: prove the *mechanics* are correct — schema-constrained extraction with provenance, the supervisor/specialist routing, the interrupt/resume human-review loop, the zero-cost data stack (§10) — on real sample deal documents, before spending a rupee on infrastructure.
- Explicitly not trying to prove final output quality or speed at this stage — a 3–8B model on a laptop CPU will produce a rougher memo than the eventual production tier. That's fine; Phase 0's job is "does the pipeline work," not "is the prose publication-grade."
- **Decision gate before Phase 1:** only move off local hardware if Phase 0 measurement (not assumption) shows the CPU-only tier genuinely can't do the job — e.g., extraction accuracy is unacceptably poor even after schema/prompt tuning, or latency makes the conversational loop unusable even for the lighter agents. If Phase 0 holds up, there's no reason to spend anything yet — AWS (or any cloud) is a Phase 1+ decision made from evidence, not a default next step.

**Phase 1 — Solo POC on rented infra (only if Phase 0's decision gate says local isn't enough)**
- Single tenant, Tier A (self-hosted), right-sized models per §8.2 instead of monolithic 70B — this is where AWS (or another provider) first enters the picture, and only for the specific stage(s) Phase 0 showed needed more than a CPU could give.
- Human review UX can be a simple approve/edit form rather than a polished product screen.
- Get real latency numbers per stage on rented hardware to replace the estimates in §8.1.

**Phase 2 — Design-partner pilot (2–3 real funds)**
- Multi-tenancy (§9) built for real, not deferred.
- Offer Tier A and Tier B; let pilot customers' data-handling requirements decide which they're on.
- Replace placeholder data sources with the corrected sourcing in §10; get pilot customers' explicit sign-off on which external sources are acceptable for their deals.
- Start collecting real per-deal compute cost data to build the actual pricing model deferred in §11.
- **Positioning check-in:** confirm with pilot customers that "eliminates the manual grunt work an associate does today, analyst still signs off" (the framing locked in this round — see §2 addendum) is how the product is pitched. "Replaces the investment bankers" is not accurate to what's being built and is a real compliance/credibility risk with this buyer — funds will trust "makes your analysts faster" far more than "replaces your analysts," and the latter overclaims what a system with a mandatory human review gate actually does.

**Phase 3 — Productization**
- Tier C (managed) only after Phase 2's multi-tenancy has held up under real usage.
- Formal audit-log export, role-based access, billing.
- Revisit compliance positioning (§2's explicit scope limits) with actual customer compliance teams before any broader go-to-market claims.

---

## 14. Local-first validation tier (Phase 0 detail) — CPU-only, zero cloud spend

This section exists because the stakeholder decision this round was explicit: **prove it on your own hardware before AWS gets touched at all**, and the hardware in question is a CPU-only laptop/desktop — no dedicated GPU. That changes the model-sizing story in §8.2 again, but in a good direction: the small-model tier that §8.2 already assigned to the Planner and Ingestion agents turns out to run at genuinely usable speed on CPU alone, which is not true of the 70B-class model the original brief assumed everywhere.

### 14.1 What actually runs on CPU alone, with real numbers

Published CPU-only benchmarks (numbers vary by exact CPU — treat as ballpark, then verify on your own machine with §14.3's script) converge on a clear pattern:

| Model class | Example models | Typical CPU-only throughput | RAM needed | Fit for |
|---|---|---|---|---|
| ~1-2B | Llama 3.2 1B, Gemma 4 E2B | 80-120 tok/s ([nextaipulse.com](https://www.nextaipulse.com/ollama-models-for-cpu-only-computers)) | ~2GB | Planner/router agent — needs speed far more than depth |
| ~3-4B | Llama 3.2 3B, Phi-4-mini (3.8B), Gemma 4 E4B | 10-70 tok/s depending on CPU generation ([promptquorum.com](https://www.promptquorum.com/local-llms/best-cpu-only-llm); [nextaipulse.com](https://www.nextaipulse.com/ollama-models-for-cpu-only-computers)) | 2-3GB | Structured extraction — Phi-4-mini and Gemma 4 E4B specifically support native function-calling/JSON-schema output, which is exactly what §5.3's schema-constrained extraction needs ([localaimaster.com, 2026](https://localaimaster.com/blog/small-language-models-guide-2026)) |
| ~7-8B | Qwen2.5 7B, Llama 3.1 8B, Mistral 7B | 20-35 tok/s on a modern laptop i7, less on older CPUs ([localaimaster.com Ollama guide](https://www.nextaipulse.com/ollama-models-for-cpu-only-computers)) | 5GB+ | Market research synthesis and, during Phase 0 only, a stand-in for the compilation step (§14.2) |

The takeaway: this is a completely different regime from the original brief's 70B-hybrid-offload design, where 55% of the model lived in system RAM and throughput realistically landed at 2-8 tok/s (§8.1). A right-sized 1-8B model, fully resident in RAM with no GPU at all, is faster on a laptop than the original 70B design was on the target AWS box. Being CPU-only isn't a downgrade from the corrected architecture in §8.2 — it's the same right-sizing principle, just with the ceiling set lower.

### 14.2 What Phase 0 can't prove on this hardware, and how that's handled

Compilation (§5.7) was deliberately assigned the largest model in §8.2 because narrative coherence across a full memo benefits from more reasoning depth than an 8B model reliably gives. On CPU-only hardware there's no way to test that step at its intended quality — an 8B model is the practical ceiling for a reasonably responsive laptop session. Two honest options, not one glossed-over one:

1. **Run compilation on the same 7-8B model as everything else during Phase 0**, accept that the final memo's prose quality is a lower bar than production, and treat this as explicitly out of scope for what Phase 0 is trying to prove (§13's Phase 0 goal is pipeline mechanics, not prose quality).
2. **Measure whether it's actually a problem before assuming it is.** Compilation only arranges already-approved, already-cited data (§5.7) — it isn't inventing numbers. It's possible an 8B model does a perfectly adequate job of *arranging* pre-approved content into a template, even if it would do a mediocre job of open-ended financial writing. Phase 0 should specifically test this rather than assume the large-model requirement from §8.2 — it may turn out compilation doesn't need to move off local hardware even at Phase 1.

### 14.3 A runnable local benchmark — measure your machine, don't guess it

The published numbers in §14.1 are from other people's CPUs. Sent alongside this document is `local_llm_benchmark.py` — a small, fully free/open-source script (Ollama + Python, no API keys, no cloud) that:
- Pulls a short list of candidate models (1B/3B/8B tier) via Ollama.
- Runs a representative structured-extraction prompt (a small synthetic "financial fact sheet" text) against each, three times.
- Reports tokens/sec, first-token latency, and peak memory for each model on your actual machine.
- Prints a plain recommendation ("routing model," "extraction model," "compilation stand-in") based on what came back fastest for its size class.

Run that once, and §14.1's table stops being a set of citations from other people's hardware and becomes a decision made on yours.

### 14.4 Zero-cost local software stack (everything below is free, open-source, and runs with no GPU)

- **Ollama** — model runtime, CPU-only capable, MIT-licensed, the easiest way to pull and run the models in §14.1 with no separate quantization/build step.
- **llama-cpp-python** — lower-level alternative to Ollama if finer control over quantization/context is needed later.
- **faiss-cpu** — the vector index for the Market Research Agent (§5.4); FAISS has no GPU dependency for index sizes this workload needs.
- **sentence-transformers running `bge-small-en-v1.5`** — a smaller sibling of the `bge-large-en-v1.5` embedding model from the original brief; on CPU-only hardware, dropping from large to small trims embedding latency substantially for a small accuracy cost that's acceptable given §10.5 already treats research findings as corroborating signal, not authoritative data.
- **pdfplumber / PyMuPDF** — free, open-source, non-LLM PDF layout+table extraction for the Ingestion Agent (§5.2) — this is deterministic code, not a model, so it costs nothing to run regardless of hardware tier.

---

## 15. Open risks / questions for further validation

- Real-world extraction accuracy on genuinely messy, non-standard pitch decks and financials — Phase 0's most important deliverable is measuring this, not assuming the schema-constrained approach solves it perfectly on day one.
- Whether any pilot customer's compliance posture will accept Tier B (hybrid cloud API) at all, or whether every realistic customer forces Tier A — this materially changes the model-sizing story in §8.2 if the large-compilation-model step also has to run fully local.
- Actual measured throughput per model tier on real target hardware, to replace the benchmark-derived estimates in §8.1 with first-party numbers.
- Coverage validation on the zero-budget data stack (§10): run it against 10–15 real deals before trusting it in front of a customer, since OpenCorporates' free quota and Alpha Vantage's 25/day limit are tight enough that real usage patterns, not just the documented limits, will determine whether caching/batching is sufficient.
- If a paying customer specifically wants Crunchbase/PitchBook-grade funding coverage, that's a commercial conversation about *their* data subscription (§10.5), not a gap to quietly fill with a scraper — worth deciding in advance how that request gets handled so it doesn't get built in under time pressure.

---

## Sources

- [g5.4xlarge specs and pricing — Vantage](https://instances.vantage.sh/aws/ec2/g5.4xlarge)
- [LLM Tokens/Sec Benchmarks 2026: RTX 4090 vs 3090, 7B–70B Q4 (llama.cpp) — mustafa.net](https://mustafa.net/llm-tokens-per-second-benchmarks/)
- [Apollo Pricing 2026: Plans From $59-$149/mo (Full Breakdown) — Warmly](https://www.warmly.ai/p/blog/apollo-pricing)
- [Apollo API Terms of Service](https://www.apollo.io/terms/api)
- [Similarweb Pricing Review 2026: Plans, Costs & Value — Tekpon](https://tekpon.com/software/similarweb/pricing/)
- [LLMs for Structured Data Extraction from PDFs in 2026 — Unstract](https://unstract.com/blog/comparing-approaches-for-using-llms-for-structured-data-extraction-from-pdfs/)
- [SEC.gov — Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [St. Louis Fed Web Services: FRED API Overview](https://fred.stlouisfed.org/docs/api/fred/overview.html)
- [Alpha Vantage API Request Limits — Macroption](https://www.macroption.com/alpha-vantage-api-limits/)
- [PatentsView migrating to USPTO Open Data Portal — USPTO, 2026](https://www.uspto.gov/subscription-center/2026/patentsview-migrating-uspto-open-data-portal-march-20)
- [OpenCorporates API — Free APIs For You](https://www.freeapisforyou.in/api/opencorporates)
- [Common Crawl — Terms of Use](https://commoncrawl.org/terms-of-use)
- [Crunchbase API in 2026: Free Tier Gone — DEV Community](https://dev.to/agenthustler/crunchbase-api-in-2026-free-tier-gone-what-startup-data-hunters-do-now-1177)
- [CPU-Only LLM 2026: Phi-4 Mini Runs 12 tok/s, No GPU — PromptQuorum](https://www.promptquorum.com/local-llms/best-cpu-only-llm)
- [Ollama Models for CPU Only Computers — NextAIPulse](https://www.nextaipulse.com/ollama-models-for-cpu-only-computers)
- [Best Small Language Models 2026: Top SLMs Ranked (1B-14B) — LocalAIMaster](https://localaimaster.com/blog/small-language-models-guide-2026)
- [Human in the loop (HITL) AI Agents with LangGraph & Elastic — Elastic Search Labs](https://www.elastic.co/search-labs/blog/human-in-the-loop-hitllanggraph-elasticsearch)
- [Building Human-In-The-Loop Agentic Workflows — Towards Data Science](https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows/)
