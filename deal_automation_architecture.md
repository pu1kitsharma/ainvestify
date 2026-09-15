# Deal Automation System — Revised Architecture & Design Document

**Current product direction (2026-09-13):** See §16 for the controlling lifecycle and implementation plan: identify companies worth incubation effort → incubate toward market and investment readiness → prepare fundraising materials → support VC fundraising through closing. The user explicitly wants LLM-driven work across this lifecycle. §16 supersedes older scope exclusions for evidence-backed selection, incubation, and fundraising/closing workflow support. Earlier sections still describe the existing prototype; features proposed in §16 are not implemented merely by appearing here.

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

## 16. LLM-driven company selection, incubation, and VC fundraising plan

**Decision date:** 2026-09-13. **Status:** implementation plan; runtime remains the existing prototype.

### 16.1 Product objective and scope

Build a workspace that helps an incubation/advisory firm identify companies worth its effort, improve their market and investment readiness, prepare the right fundraising materials, and support VC financing through closing. This is the primary product path. Broad investment banking, public-company transaction sourcing, buy-side fund management, and exits are secondary extensions.

**User-confirmed targeting:** companies in any sector and ultimately any region; pilot in India. Do not default to software, B2B, ARR-based businesses, or technology-only sources. Company stage is configurable and remains unspecified; the pilot should include a range of readiness levels and document them. A company can be attractive to incubate without being appropriate for VC financing. The system must explain that distinction and allow a different financing recommendation or a hold decision.

**Further user clarification, same session:** The intended operating model combines a YC-style accelerator with VC/IB capabilities, reducing the workforce through end-to-end automation and minimal human intervention. The system should operate the routine workflow, not require an analyst to manually drive every stage. Whether the firm also invests its own capital, and on what terms, remains configurable; do not assume fund size, ownership, or investment terms.

LLM-driven means a conversational supervisor researches, reasons, prioritizes, drafts, executes authorized routine workflows, and revises work as evidence changes. Tools still fetch sources, calculate numbers, enforce access and state rules, and save records. LLM memory is not company evidence, and a second LLM agreeing with the first is not independent corroboration. Use automated validations and an exception queue rather than mandatory manual review of every field or routine step. Reserve human decisions for company acceptance, binding engagement/capital commitments, unresolved material exceptions, final externally shared materials, and legal/financial execution. This request authorizes planning; it does not authorize sending messages, purchasing data, deploying, signing contracts, or moving funds.

The existing local Phase 0 and no-unapproved-paid-services constraints remain. Prototype source access can use analyst-supplied URLs, authorized uploads, and approved public sources. Scalable search/data providers are pluggable dependencies and require a source-specific cost/access decision, not an assumed free entitlement. No model/vendor choice is fixed until measured on representative tasks.

### 16.2 Why current sourcing is vague — code findings

1. `discover_github_leads()` assigns the repository owner's login as `company_name`. An account can be a person, student, clone publisher, or open-source project; company identity is not established.
2. `discover_hn_launches()` uses a launch title as the company name. Product, brand, founder, and legal entity are not reconciled.
3. The default 30-day window finds recent launches/repositories, excluding many operating companies that could benefit from incubation. A repository creation date is not a company founding date.
4. `discover_leads()` concatenates two lists without cross-source entity resolution. Same-name repository deduplication does not establish distinct companies.
5. Geography filtering applies only to GitHub owner profiles; HN receives no geography filter. Missing/ambiguous geography is not represented adequately.
6. Connector exceptions return empty lists, conflating service failures with genuine zero matches.
7. Keyword matching and popularity supply discovery signals, not evidence of demand, team capability, financial health, incubation fit, or VC suitability.
8. `SourcedLead` lacks canonical domain/entity, dated business claims, evidence quality, conflicts, and a selection assessment. Later enrichment therefore has little reliable identity context.

Fixing prompts alone cannot address these structural gaps. Preserve GitHub/HN as optional sector-specific signals; remove their role as the default universe of companies.

### 16.3 Source strategy: discovery, identity, and diligence

| Source family | Intended use | Evidence limits / implementation approach |
|---|---|---|
| Founder applications, referrals, partner incubator submissions | Cross-sector intake, founder consent, objectives, direct documents | Submitted claims remain founder-reported until checked; build structured forms and authorized imports first |
| Company website, product catalog, pricing, team and customer pages | Establish brand/domain, offering, target customers, location claims, current activity | First-party marketing can be incomplete or promotional; preserve exact text and date |
| Accelerator/incubator portfolios, university incubators, industry associations | Discover actual operating businesses across sectors | Directory inclusion establishes only what the publisher asserts; stale entries and selection bias remain |
| Startup India Showcase and relevant public programs | India pilot discovery and program participation | Validate individual profiles; distinguish company-level listings from aggregate statistics |
| Relevant official registries and filings | Legal entity, status, registered jurisdiction, filed financial information when accessible | Registry jurisdiction is not necessarily operating geography; use official permitted access or authorized documents; coverage varies by country |
| Investor portfolio pages and original funding announcements | Corroborate reported investor relationships and historical rounds | Funding announcements do not establish cash balance, current fundraising intent, or willingness to invest again |
| Customer references, invoices, contracts, sales/product exports, financial records supplied with permission | Evaluate demand, revenues, margins, retention, cash, operations, ownership | Reconcile sources and reporting periods; confidential, permission-scoped evidence; references require separately authorized contact |
| Sector-specific sources | Product/regulatory milestones, distribution, manufacturing capacity, trials, patents, tenders, etc. | Select per sector and jurisdiction; applications, grants, awards, sales, and approvals must remain distinct claims |
| News, GitHub, HN and other activity signals | Find candidates or questions worth investigating | Secondary/weak signals; never substitute for commercial validation |
| Licensed company data providers | Optional broader discovery and enrichment | Evaluate coverage, freshness, permitted product use, and incremental selection quality before procurement |

Public-page existence is not verification of an automated API or redistribution license. Maintain a source registry with access method, coverage, allowed use, terms URL/check date, rate limits, cost, refresh policy, and operational status. Earlier §10 blanket source-permission claims are historical and must be revalidated per connector before implementation. Search results are pointers: inspect original pages before accepting claims. Separate `ok`, `no_results`, `blocked`, `rate_limited`, `failed`, and `partial` source outcomes in both API and UI.

Reviewed discovery examples: [YC company directory](https://www.ycombinator.com/companies/), [Techstars portfolio](https://www.techstars.com/portfolio), and [Startup India Showcase](https://www.startupindia.gov.in/content/sih/en/startup_india_showcase.html). These demonstrate candidate source families, not a guarantee of bulk access or comprehensive coverage. [Crunchbase data licensing](https://about.crunchbase.com/products/data-licensing) is a possible future procurement route; no access has been purchased or integration approved.

### 16.4 Company evidence model

Create a persistent `Company` independent of a deal. Keep brands, products, founders, legal entities, and domains linked but distinct. Track registered location, operating markets, and founder location separately. Domain matches are useful but not sufficient: retain ambiguity, rebrands, subsidiaries, and manual merge/split decisions.

Each `EvidenceClaim` stores: tenant/company ID, subject, claim type, value/text, unit/currency, period/as-of date, source ID, exact supporting passage/page/cell, publisher, publication/retrieval dates, extraction/model version, origin category, review status, contradictory claim IDs, and superseded-by ID. Store snapshots/hashes where permitted and apply source-specific retention. Distinguish first-party, independently corroborated, derived, inferred, unknown, and disputed information. Preserve lineage back to a shared original announcement so syndicated articles do not count as independent sources.

Numeric evidence requires the exact period and definition: revenue differs from ARR, GMV, bookings, grants, and funding raised. Missing data remains unknown. Explicitly labeled estimates and forecasts store assumptions and never become observed facts. Refresh policy varies by claim type; stale funding information and current cash are different problems.

Downstream assessments, plans, and documents reference evidence versions. When an input changes, mark affected outputs stale, explain the change, and require relevant re-review. Keep legacy leads and documents intact; migrate incrementally with compatibility adapters and reversible local migration tests.

### 16.5 Stage A — identify companies worth incubation effort

Input: configurable `SelectionThesis` containing regions, sector inclusion/exclusion, stage, business models, support capabilities, effort capacity, expected milestones, and financing objectives. Broad discovery can cover any sector; depth of research and selection criteria depend on the company's business model.

LLM workflow: translate thesis into source/query plan → collect candidates → resolve identity → build evidence dossier → seek disconfirming evidence → identify missing information → assess incubation fit → propose next action. Limit research calls, depth, tokens, and elapsed time; stop with a missing-evidence task when further browsing is unlikely to resolve private information.

Evaluate customer problem and demand; team execution evidence; market/distribution; differentiation; business-model economics; operational feasibility; capital needs; risks; and **whether this firm's support can materially help within its capacity**. Separate evidence completeness from opportunity attractiveness. A sparse public footprint must not automatically mean a weak business.

Output: a cited one-page selection brief with established identity, company description, evidence-backed strengths, concerns, unknowns, proposed incubation intervention, effort estimate, founder questions, and recommendation: `investigate`, `invite_to_discussion`, `nurture`, or `pass`. A later acceptance decision requires founder engagement and stronger evidence. Do not present an LLM score as an investment-success probability. Start with explainable dimension-level judgments; introduce weighted ranking only after calibration against analyst-reviewed examples.

Example, illustrative only: a consumer company has documented repeat orders but weak channel margins. The brief proposes margin verification and channel experiments; it does not reject the company for lacking ARR or public code. A research venture instead needs technical and commercialization milestones appropriate to its stage.

### 16.6 Stage B — founder engagement and incubation

The LLM drafts a founder conversation brief, discovery questions, proposed support plan, engagement proposal, and follow-up drafts. CRM records contacts, meetings, consent, objectives, and outcomes. Actual outreach follows explicit authorization. Allow preliminary public/authorized materials before a mandate; confidential access follows the relevant engagement/permission basis. Replace the universal mandate-before-ingestion assumption with explicit document permissions and engagement types. Recording a signed status is distinct from retaining an executed agreement.

After onboarding, collect a baseline dossier and missing-document requests, then generate a configurable milestone plan (for example, a 30/60/90-day plan where appropriate). Each task has an owner, dependency, baseline, target, due date, required evidence, effort estimate, and acceptance rule. Completion is demonstrated by evidence, not by generated prose.

Workstreams include customer discovery, product/service validation, positioning, pricing, channel strategy, sales/distribution experiments, unit economics, financial reporting, team gaps, operational capacity, ownership cleanup, and relevant specialist reviews. The LLM reviews updates, identifies blockers, drafts deliverables, and proposes plan changes. Human founders/operators perform real-world experiments and supply outcomes; a strategy document alone does not make a company market-ready.

Use separate readiness assessments:

- **Market readiness:** defined customer/problem, appropriate demand evidence, viable offering, feasible delivery, credible pricing/unit economics, and a tested path to customers appropriate to stage.
- **Investment readiness:** explainable business and market, reliable financial/ownership records, risks disclosed, capital ask and use of proceeds, milestone-linked financing plan, investor fit, and diligence materials appropriate to the round.

Criteria are versioned by sector, business model, stage, and jurisdiction. Pre-revenue companies can qualify on appropriate scientific, product, or customer-validation milestones. Do not impose software revenue metrics on manufacturers, services, consumer brands, agriculture, or life sciences. Show blockers and evidence per criterion rather than an unexplained readiness percentage. A reviewer may approve a disclosed exception with rationale; no requirement disappears silently.

### 16.7 Stage C — fundraising materials

The approved company dossier and readiness assessment feed narrative drafting, market analysis, competitor comparisons, financial scenarios, funding strategy, and document generation. Reuse existing citation/review infrastructure, replacing the single-document extraction assumption with multi-document reconciliation and period/currency-aware metrics.

Deliverables are configurable: founder pitch deck, executive summary, investor FAQ, financial model, use-of-funds/milestone plan, organized data-room index, and teaser or CIM when the process calls for them. Internal incubation-selection briefs and external fundraising materials are different templates. Do not require every startup to produce an anonymous teaser and CIM.

Financial models use business drivers: price/volume/margin/capacity for relevant operating businesses, retention/customer acquisition for recurring businesses, development timelines and costs for pre-commercial ventures. Code calculates scenarios, cash runway, dilution, and sensitivities from explicit approved assumptions. LLMs explain and challenge assumptions; they do not supply unsupported actuals. Final review checks claim support, narrative accuracy, omissions, contradictions, projections, and document identity/disclosure before release.

### 16.8 Stage D — investor matching, fundraising, and closing

Create a separate `Fundraise` per round, linked to Company and Engagement. Model investor firms, specific funds, people, relationships, and per-round opportunities separately. Match on stage, sector, geography, check size when evidenced, portfolio conflicts, strategy, and relevant activity. Record why each match fits, what is unknown, evidence date, and whether a warm introduction exists. A portfolio investment is not evidence that the fund currently has deployable capital.

LLM deliverables: tailored investor research briefs, meeting preparation, approved-source outreach drafts, Q&A answers, follow-up drafts, feedback synthesis, and revised targeting. Persist a per-investor pipeline: `identified → qualified → introduction_pending → contacted → meeting → diligence → terms → committed → closed`, with `passed`, `on_hold`, and reasoned reversals. No status changes solely because an email was drafted. No sending or sharing is enabled by this plan; later authorized integrations must record recipient, content/version, approval, outcome, and retries without duplicate sends.

Closing support includes term-sheet extraction/comparison, dilution scenarios, diligence tasks, specialist/legal owners, document versions, required approvals, signatures, conditions, allocations, and evidence of funds received. Distinguish verbal interest, written commitment, executed documents, and received funds. Closing requires recorded completion of the applicable conditions and authorized confirmation; the LLM must not equate a positive response or a generated agreement with a closed round. Support multiple closings/tranches and unsuccessful raises. Drafting and tracking do not replace legal execution or guarantee financing.

After close, track use of proceeds, company milestones, investor updates, and next-round readiness. If VC is a poor fit, explain that finding rather than forcing the company down a VC path.

### 16.9 Technical design and implementation boundaries

Keep the existing React/FastAPI/Pydantic/store architecture initially. Implement specialist capabilities behind one supervisor rather than deploying a microservice per agent. Capabilities: discovery, identity resolution, evidence extraction/verification, selection, incubation/GTM planning, readiness assessment, materials, investor research, and closing coordination. Each returns typed results with evidence IDs, unknowns, proposed actions, and tool/run metadata.

Add entities incrementally: `SelectionThesis`, `Company`, `SourceRecord`, `SourceRun`, `EvidenceClaim`, `SelectionAssessment`, `Engagement`, `IncubationPlan`, `Milestone`, `ReadinessAssessment`, `Fundraise`, `InvestorFirm`, `InvestorOpportunity`, `ClosingChecklist`, and `AgentRun`. Every private entity is tenant-scoped. Keep document-processing status independent from company lifecycle, milestone status, and investor pipeline.

Company lifecycle: `candidate → researching → qualified → engagement_pending → incubating → readiness_review → fundraise_ready`, with `needs_information`, `nurture`, `declined`, and `paused` paths. Fundraising and incubation can overlap; a closed round does not terminate company support. Every transition has typed preconditions and audit history. Reuse current deals as legacy document-workflow records until migrated; do not overwrite the live SQLite database during development.

Add durable background jobs with progress, cancellation, bounded retries, source outcomes, token/call budgets, and resumable checkpoints. Treat fetched pages/documents as untrusted evidence, never instructions. Fetch tools need public-address validation, redirect checks, limits on sizes/types/time, and protection against local/private-network access. Source text cannot authorize tool actions or change policies. Before external collaboration, implement actual authentication, authorization, approved document sharing, and audit attribution; tenant headers alone are insufficient.

### 16.10 Build sequence and acceptance gates

**Milestone 1 — reliable company discovery and selection (first implementation slice).**

- Extend schemas/store with Company, EvidenceClaim, SourceRun, SelectionThesis, and SelectionAssessment; preserve current lead APIs through adapters.
- Refactor `agents/sourcing_agent.py` into source collection → candidate normalization → entity resolution → dossier → selection assessment. Start with founder/analyst intake and supplied company URLs plus individually approved sources. Add source registry and bounded evidence-fetch tools; no invented bulk API.
- Replace lead cards with verified identity, sector/business model, location basis, evidence dates, strengths, concerns, unknowns, source failures, recommendation, and next action. Raw projects stay unverified candidates.
- Add APIs for starting/resuming a sourcing run, reviewing claims/identity, assessing a company, and promoting an approved company to engagement. Preserve existing document pipeline behavior.
- Build an analyst-labeled pilot set of approximately 30 Indian companies across at least five business-model/sector groups, including non-software companies, weak candidates, duplicates, ambiguous entities, and sparse-data cases. This is an evaluation sample, not a representative market census. Separate tuning and held-out cases; repeat model runs to assess instability.
- Proposed release targets: at least 90% correct company/domain identity on held-out resolvable cases, zero unflagged cross-company evidence merges in the sample, at least 95% manually verified support among cited factual claims, and source failures never rendered as true zero-result success. Report denominators, unresolved cases, and errors; small samples are not accuracy guarantees. Set an explicit precision-at-10 and analyst-time baseline before claiming ranking improvement. Test geography, currency/period handling, contradictions, stale claims, tenant isolation, and source-text prompt injection.

**Milestone 2 — engagement, baseline diligence, and incubation.**

- Founder intake, CRM, engagement records, multi-document reconciliation, milestone/task workspace, and evidence-based updates.
- Exit gate: at least one real, authorized non-software company and one company of another business model can move from selection to an owner-assigned plan with measured outcomes. Synthetic fixtures prove software behavior only; actual outcomes require founder participation and time.

**Milestone 3 — readiness and fundraising package.**

- Sector/stage readiness templates, blocker handling, reviewer decisions, business-driver models, deck/summary/FAQ/data-room output, document-level release approval, and stale-output invalidation.
- Exit gate: an authorized company can produce a coherent reviewed package; every factual assertion is supported or explicitly qualified; projections reconcile with model inputs; unresolved material blockers prevent an unqualified ready status.

**Milestone 4 — investor matching and fundraising workspace.**

- Verified investor profiles, fund-level fit assessments, relationship tracking, per-investor opportunities, meeting/feedback/Q&A workflows, and human-reviewed message drafts.
- Exit gate: each proposed investor has evidenced fit or explicit unknowns; stages reflect actual recorded events; no message is sent without authorization. Live outreach is a later separately authorized action, not an acceptance requirement for offline development.

**Milestone 5 — closing and post-close support.**

- Term comparison, conditions/approvals/signature/funding evidence, multi-close handling, allocation records, and milestone/investor updates.
- Exit gate: simulations distinguish interest, commitments, signatures, and funding correctly; real close status requires actual evidence and authorized confirmation. The product supports the process and does not claim to have closed a financing without those events.

Model evaluations are separate from deterministic unit/integration tests. Benchmark task quality, citation support, abstention, latency, and cost on the selected local models before choosing larger or hosted models. Expand infrastructure only when measurements justify it and authorization covers it. Build order follows these gates rather than unsupported calendar estimates.

### 16.11 Product success measures and remaining inputs

Measure verified-company yield by source and sector; false entity matches; supported-claim rate; unknown/conflict rate; freshness; analyst time per accepted candidate; founder acceptance; milestone completion supported by outcomes; readiness progression; investor meeting/diligence progression; and eventual financing outcomes. Attribute funding outcomes to observed events, not document generation. Disaggregate sector results so software-heavy sources cannot hide poor coverage elsewhere.

Confirmed: India pilot, global-capable design, any sector. Still configurable: stage, incubation capacity, engagement economics, exclusions, and readiness thresholds. These do not block the shared evidence model. Founder access is required to validate private business performance; paid data and hosted-model budgets remain unapproved. The first engineering work should be Milestone 1, not another generic CIM template or additional GitHub keyword searches.

### 16.12 Minimal-human operating model

This clarification replaces a per-field/per-action manual approval target with supervision by exception. Existing runtime review gates remain until the replacement validation, approval, and audit system is implemented and tested; do not simply bypass them using `auto_confirm=True`.

| Work | Target autonomous behavior | Human involvement |
|---|---|---|
| Origination | Recurring searches under configured thesis, identity checks, evidence refresh, dossiers, shortlist updates | Review shortlist/accept companies; resolve ambiguous identity or material evidence gaps |
| Initial qualification | Assess fit and support needs, prepare founder questions, analyze submitted answers | Review consequential exceptions and final acceptance; founders provide truthful business inputs |
| Incubation | Generate plans, prioritize work, draft GTM assets, analyze experiment results, monitor milestones, propose changes | Founders/operators execute physical/customer work; supervisor resolves material strategy/resource commitments |
| Financial analysis | Extract/reconcile metrics, run code-based models, analyze scenarios, flag conflicts | Resolve material discrepancies and approve material assumptions where required |
| Materials | Draft and check cross-document consistency, refresh stale sections, generate release package | One accountable final release decision; review exceptions rather than every clean field |
| Fundraising | Research/match investors, prepare meeting briefs, manage pipeline, draft answers and follow-ups | Relationship/negotiation decisions and approved external communications policy |
| Closing | Track conditions, compare terms, assemble checklists, monitor missing evidence | Authorized legal signatories and funds/closing confirmation |

Future sending integrations may execute within an explicitly authorized scope (recipients, channels, templates/content boundaries, cadence, confidentiality, and stop rules) without asking for approval on every routine follow-up. Until that authorization and integration exist, drafts remain drafts. This plan does not grant such authorization. Material new claims, new recipient scopes, confidential disclosures, or commitments escalate outside that scope.

Implement a durable supervisor that wakes on new evidence, founder updates, due tasks, or investor events. It builds a bounded plan, invokes typed tools, verifies results, updates records, schedules follow-up work, and escalates only when a defined condition is met. Long-running actions have idempotency, retry limits, budgets, progress, cancellation, and a full audit trail. Multiple LLM roles are logical responsibilities, not a requirement to spawn independent agents for every task.

Add review states such as `machine_validated`, `needs_review`, `human_approved`, and `rejected`; never attribute machine approval to a human. Automated acceptance requires source/identity/period checks, schema and numerical validation, and calibrated thresholds. Material contradictions, identity ambiguity, unsupported claims, and high-impact judgment calls enter the exception queue. Measure false negatives through sampled human audits of otherwise auto-accepted work and maintain rollback/re-review paths. Readiness checklists can run automatically; material exceptions and external readiness representations need accountable sign-off.

The primary efficiency measures are human minutes per researched company, accepted company, completed incubation milestone, released package, and active raise; also track autonomous task completion, exception rate, rework, and missed material errors. Establish the current baseline before setting reduction targets. Do not promise a particular workforce reduction or fully autonomous company growth/fundraising before pilot evidence exists.

### 16.13 First web sourcing implementation — 2026-09-13

The user authorized implementation, explicitly allowing web scraping beyond GitHub and prioritizing free models now with API pricing/integrations later. Implemented a first bounded slice, not completion of Milestone 1:

- `agents/web_sources.py`: HTTP(S) HTML/text collection; robots checks; per-hop public-address validation; pinned-IP connection with verified TLS hostname; bounded redirects, bytes and time; text/link extraction. Oversized pages can be partially read and explicitly marked incomplete. No login, CAPTCHA, proxy rotation, JavaScript execution, search-engine scraping, or paid source dependency.
- `agents/local_models.py`: injectable structured-model interface, loopback Ollama implementation, `SOURCING_MODEL` configuration (default installed `phi4-mini`), constrained outputs and token limits. No automatic downloads or paid/hosted fallback.
- `agents/company_sourcing.py`: starting URL → observed-link traversal → literal quoted claims → provisional identity → local-model selection assessment → persisted profile and compatible lead. Any sector/geography can be supplied. Company identities and semantic claim attribution remain unverified; cited text proves what the page says, not that the statement is true. Same-host website attribution requires title support; unresolved directory identities retain separate source/name keys. Rebrands and cross-source unresolved identities need fuller resolution later.
- Schemas/Store add company profiles, evidence, assessments, and source runs; additive tables preserve the existing deal pipeline. Duplicate known website/name combinations reuse the profile and lead; mismatched names are surfaced rather than merged. This is not a full evidence-version graph or conflict-resolution engine.
- Web API/UI launch, poll, show outcomes/claims/missing information/incubation actions, and request cancellation. One in-process web worker uses a separate SQLite connection. Restarted work is marked interrupted; full job resumption and distributed workers remain future work. Stopping takes effect between bounded model/network steps.

The initial India portfolio URL is editable; no sector or country is hardcoded into the extraction schema. The older GitHub/HN/SEC APIs remain compatible and are secondary UI options. A keyword alone does not yet initiate an internet-wide search: broader automated discovery and a vetted source registry are next, followed by calibration against a representative analyst-labeled company set. Do not claim fully verified identities, financial diligence, investment ranking accuracy, completed incubation, or autonomous closing from this slice.

Validation includes offline tests for non-software profiles, quoted-evidence rejection, invented destinations, directory/company identity separation, private-address and redirect defenses, source failures, local-model errors, tenant isolation, cancellation, API persistence, and backward-compatible lead use; frontend build/lint and existing deal-workflow regressions. Live smoke scripts use public pages and temporary SQLite databases rather than the user's active deals. A live Startup India page fetch succeeded but yielded no supported company profile; such outcomes remain visible rather than being filled from model memory.

Live testing also caught the local model attributing an incubator's domain to a listed company; the same-host/title check now leaves that website unresolved. An agricultural-company page completed collection, persistence, and local assessment, but produced sparse legal-name evidence rather than a commercially verified dossier. That is a successful plumbing check, not evidence of selection accuracy. Local inference and source coverage still require the planned representative evaluation. Name-only quote repair locates the exact extracted name in real page text; business claims and numerical values never use this repair path.


### 16.14 Brief-driven automatic discovery — 2026-09-13

Supersedes §16.13's URL-required entry point and the supplied-URL-first build order: the user explicitly requires the system to discover companies from a brief. Dashboard, Leads UI, API and CLI now initiate automatic discovery without URLs; supplied URLs remain an optional focused-research override. Full user criteria reach the researcher without keyword reduction.

`agents/web_discovery.py` plans up to three local-model queries, preserves requested geography, searches public destinations, deduplicates/diversifies domains, and then passes them to the bounded original-page collector. DuckDuckGo HTML is best-effort; challenges or outages stop further requests to that provider. Mwmbl's documented unauthenticated v1 search API is an independent fallback, with a smaller index and no API key/billing. Provider contract: https://github.com/mwmbl/mwmbl/blob/main/mwmbl/tinysearchengine/search.py. No challenge solving or proxy rotation. If search yields nothing, geography-matched operator catalog research is labeled limited coverage; unavailable coverage is never a conclusion that no companies exist. Search results are destinations only, never factual company evidence. A provider interface allows later approved search services without changing user input.

Extraction cites exact numbered source passages, checks values against those passages, rejects non-company entities, canonicalizes title-supported company roots, and follows useful observed company pages. Unknown geography/business evidence blocks invitation recommendations. These checks reduce obvious errors; they do not establish truth or calibrated investment suitability. Jobs persist search strategy, discovered destinations, source outcomes, phases and coverage warnings. Tests cover brief-only discovery through persistence, provider failures, citation rejection, manual override and geography checks. End-to-end live availability remains dependent on public sources; production-quality coverage, legal identity resolution and analyst-labeled evaluation remain unfinished.

Live validation of §16.14: a brief-only India solar-dryer run generated queries without supplied URLs. One run reached Mwmbl and discovered a research destination that was inaccessible to collection. A subsequent run encountered DDG HTTP 202 and a Mwmbl timeout, automatically used the India catalog, and persisted Raheja Solar and Gangpur Ventures with name-only evidence, unresolved websites and `investigate` recommendations. This validates autonomous entry and explicit degraded operation, not adequate sourcing coverage or dossier quality. The two-page smoke budget left additional pages unread. Selected sourcing/API/review/concurrency checks passed (85 tests across the suite and targeted reruns); frontend build/lint passed. No browser interaction test was available.


### 16.15 Runtime repair and company enrichment

The reported 405 was reproduced through Vite on port 5173. The process on port 8000 was an older `python -m uvicorn api.main:app --port 8000` instance whose OpenAPI paths contained no web-runs routes. Restarting the confirmed project process with `--reload` restores the endpoint; an empty POST now returns the expected 422 validation response. The client adds a specific compatibility diagnostic for a research-route 405.

Discovery now reserves half the page budget for company enrichment (manual URL overrides retain focused traversal). `SearchSession` aggregates sparse results across independent providers, caches repeated queries, and disables failed providers for that job. Named-company research searches for official/product/customer information, follows observed company links and useful internal pages, and applies the same passage validation. Exact-name matches alone cannot merge identities: same-site provenance, a company-labelled source link, a backlink, or matching offering/team evidence is required. Conflicting websites remain unresolved. This is conservative linkage, not verified legal identity. Earlier stored evidence is retained when refreshing an existing profile.

The public collector follows bounded robots redirects with destination IP validation and reads bounded public PDF text with page markers. Automatic public-document collection removes a local-upload dependency for preliminary company research; PDFs with no selectable text remain explicit gaps. Founder-private data intake and the downstream financial extraction/document workflow still need a unified evidence handoff. No OCR, browser rendering, scheduled refresh, durable distributed jobs or externally sent messages were added in this slice. The desired operating model remains autonomous routine workflows across sourcing, readiness, materials and fundraising support, with measurable quality and exception handling; this implementation does not establish staff-free VC operations.

The live hoteliers check exposed query drift toward accelerators and false business narratives based only on name/location evidence. Query instructions now distinguish the firm's services from the target industry; extraction explicitly excludes programs. Business assessment is withheld deterministically when offering/business-model/traction evidence is absent. Three unrelated program leads created by this diagnostic run were dismissed, retaining their audit history. Short crawl delays are now honored within the request deadline instead of causing automatic rejection. Regression coverage includes identity-only assessment suppression and crawl-delay timing.

Validation: 47 distinct sourcing/enrichment tests passed across the suite and targeted checks; frontend build/lint passed. The real frontend proxy accepted the hotel research request (202), and the API health check passed after the changes. A subsequent temporary-DB run generated appropriate hotel-operator queries, but DDG returned 202 and Mwmbl timed out; catalog fallback did not establish a relevant hotel shortlist. No production sourcing-quality claim is supported by these runs. The assessment-suppression guard was tested separately after that temporary process had loaded the earlier module version.

### 16.16 Dataset provenance and operating workflow — 2026-09-13

The user's Dataful example changes the acquisition strategy: use structured company records to establish a candidate base, then corroborate original websites and private company evidence. Do not ask users for source URLs. The operating workspace now sits beside the legacy deal-document state machine and spans sourcing, diligence preparation, incubation outcomes, readiness, materials, investor qualification and closing evidence. It records work dependencies and review exceptions rather than treating a generated memo as the end of the business process.

**Sources investigated.** Dataful dataset [20873](https://dataful.in/datasets/20873/) lists company/legal names, a reported CIN, website, startup stage, sector and services; its September 2026 metadata reports 236,854 rows, but the public preview is only a sample. Dataset [15737](https://dataful.in/datasets/15737/) contains year/state/industry totals: useful context, never company traction. [Dataful's terms](https://dataful.in/terms-and-conditions/) require subscription access to paywalled data and prohibit downloading datasets for resale; university access is restricted to affiliated academic/research users. No subscription, bulk-download entitlement or redistribution grant is configured. Those connectors remain `metadata_only`, with download/import refused. Their public metadata is catalogued, not represented as a complete imported dataset. The CSV adapter is ready for an explicitly permitted export; it validates schema, duplicate identities and access scope, preserves non-CIN values as reported identifiers, omits personal-contact columns and separates aggregates from company records. There is no UI/API path that silently changes a source's entitlement.

The live free connector uses [Wikidata structured data under CC0](https://www.wikidata.org/wiki/Wikidata:Licensing) and its [documented query service](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service). Queries retain entity URLs, row keys, retrieval times, unknown observation dates, content hashes and bounded-query coverage in tenant-scoped snapshots. An indexed hotel-chain/hotel-group query (classes Q1631129/Q3117865 resolved from Wikidata labels) succeeded for India and returned ITC Hotels Limited, Lemon Tree Hotels and Fortune Hotels with website records. These are established entities, not a representative startup sample or automatically suitable incubation candidates. The broad description query timed out; mappings and coverage outside the tested path remain limited. No inferred company names, websites, legal verification or investment scores are synthesized from aggregate data. Source/licensing failures remain visible and do not disable other research.

**Operating behavior.** New company leads automatically receive a persistent workspace and policy evaluation. API sourcing runs prepare up to two initial draft packs within the run budget when business evidence exists; more work can be triggered from the Company operations screen. One local-model call prepares four internal drafts: diligence questions, incubation/customer/GTM experiments, material/input requirements and investor-fit preparation. Short citation aliases map back to actual evidence IDs; at most one correction attempt is permitted. Output is labeled as an unreviewed proposal, never executed instructions or verified factual/legal conclusions. Draft generation is idempotent for unchanged evidence. Changes to source evidence, documents or extraction results invalidate drafts and prior review attestations. Optimistic revision checks reject concurrent stale writes.

Checks cover source reuse rights, retrieval freshness, identity/ownership review, engagement authority, regulatory/issuer/instrument/investor scope, privacy purpose/retention/sharing, commercial validation, financial review, measured incubation outcomes, release approval, investor qualification, executed documents/conditions and received funds. Review attestations must cite same-company evidence; all except identity review require a company document reference, and financial review additionally requires the existing extraction checks to pass. The record proves an accountable local review was entered, not that software independently authenticated the document. Stages cannot skip unmet dependencies. Sending, signing and money movement remain disabled even if all internal checks are satisfied.

**Authority and applicability.** India pilot references include the [Companies Act record](https://www.indiacode.nic.in/handle/123456789/2114?locale=en), [SEBI Merchant Banker master circular of 14 July 2026](https://www.sebi.gov.in/legal/master-circulars/jul-2026/master-circular-for-merchant-bankers_102815.html), and the [DPDP commencement notification](https://www.meity.gov.in/static/uploads/2025/11/c56ceae6c383460ca69577428d36828b.pdf). DPDP commencement is phased; privacy controls are engineering/readiness requirements and do not assert that all provisions are presently effective. The firm is not automatically classified as a registered merchant banker, investment adviser or AIF manager merely from a VC/IB label; the role, instrument, geography and transaction facts require review. Non-India workspaces do not receive Indian authority links as if Indian rules governed them. Policy review is due 13 October 2026 and overdue references block release. This is a versioned control framework, not legal certification.

The legacy PDF/spreadsheet extraction and final-material review process remains available through linked deals; the new internal workspaces do not bypass its gates. For a deal linked to an operating workspace, the actual teaser safe-to-send confirmation now requires the workspace's release task and its dependencies to be complete. A memo from another deal or a non-teaser document cannot be confirmed through that endpoint. Approval records retain the evidence hash; document-suite reads suppress expired approval status while preserving the historical reviewer record in storage. Legacy deals without an operating workspace retain their existing review behavior.

Validation: the live frontend-proxy run persisted an ITC Hotels workspace and generated all four internal drafts with the local model. It correctly finished as partial because public collection encountered source restrictions; the dataset rows were retained and release/closing stayed blocked. The dataset/local-model smoke also passed against a temporary database. Sourcing, workflow, API and financial-review regression suites passed, including stale approval, cross-deal confirmation, tenant isolation, invalid citations and concurrent-write rejection. Frontend build/lint passed. Browser interaction was unavailable; the live proxy/API check is not a browser test.

Remaining work includes authenticated roles (the pilot still uses local reviewer/tenant context), source-contract configuration, wider dataset coverage, durable scheduling/resumption, stronger semantic fact verification, measured incubation execution, fund-specific investor evidence, governed sharing integrations and real closing validation. No real-world founder/investor messages or transactions were executed.

### 16.17 Query-specific discovery and product repair

The user's “tech startups” search exposed two independent failures. The Leads page rendered the entire historical web-company backlog beneath every search, so a hotel diagnostic appeared to be its result. The search provider also supplied irrelevant archive/news/geography hits, while a narrow dataset mapping did not handle the brief. A name-only McKinsey result was later persisted without enough business evidence. Those outcomes do not constitute successful startup sourcing.

The Discover page now has one brief/geography form, compact company cards, a cross-search shortlist and selectable search history. The separate GitHub/Hacker News/SEC form is removed from the UI; legacy API/CLI interfaces remain. Source errors/queries are available in a collapsed diagnostics panel. New requests clear displayed results immediately; empty and interrupted runs never borrow companies from another run. Run records retain company-profile snapshots; the dedicated `/api/leads/web-runs/{id}/leads` endpoint enforces tenant/run membership and returns the evidence collected in that search. History summaries omit full snapshots to keep polling small. Shortlist decisions remain company-level state.

`agents/public_directories.py` configures public source routes and parses visible directory cards, not embedded private app state or API credentials. The [YC India company directory](https://www.ycombinator.com/companies/location/india) exposes company name, description, location, batch, status and tags. Startup requests filter against the actual brief, prefer recent reported batches and exclude reported public/acquired/inactive entries. Company names are fetched, never compiled into the discovery code. This source is limited to its public portfolio and carries selection bias; it does not prove an active fundraise, current private-company standing or investment suitability. Arbitrary regional routes can be unavailable and fall back to web research. Broader semantic constraints, negation and exhaustive industry/geography coverage remain unvalidated.

Matching directory candidates are persisted before local-model planning starts, so useful results appear while further research runs. Search queries preserve the user's actual brief and geography rather than silently narrowing technology to fintech/ecommerce. Obvious archive, stock-image and geography-conflicting destinations are removed before consuming fetch/model budgets. Automatic name-only discoveries are withheld from result membership until business evidence exists. Named-company research first uses observed profile/website links and shares its budget across candidates. Evidence and source failures remain explicit. Stable observed directory-profile links preserve company identity when an official website is subsequently resolved. Source rights still require review before external reuse.

Discovery creates company workspaces immediately but the UI sets `prepare_workflow: false`; downstream operating drafts are prepared from the company workspace. This separates the user's search latency from a multi-stage drafting workload without adding a second sourcing flow. API/CLI callers retain the optional automatic preparation path. The local service is now launched with `scripts/serve_local.py`, without file auto-reload: an observed reload paused HTTP service while the in-process research task was finishing. Backend edits require an explicit service restart. This is a local runtime repair, not durable distributed job execution.

Validation: offline tests cover run isolation, cross-tenant access, immutable search snapshots, direct-card provenance, stage filtering, relevance filtering, early publication, local-model failure and identity continuity after website resolution. The isolated Playwright regression covers progressive results, shortlist changes, history selection, new-search clearing, empty states, mobile width and browser errors. A real “tech startups” / India submission returned five candidate cards in about 4.5 seconds: Waybill, Ritivel, Cardboard, Ressl AI and Bolna AI. Model enrichment runs afterward; that timing is time to initial cards, not completed diligence or corroboration. No ITC or historical McKinsey result appeared under the new search. Frontend build/lint passed; the live API remained responsive during enrichment on the stable launcher.

### 16.18 Source diversity and visible company work

The YC-only result set exposed a selection bug: the first parsed directory could occupy every candidate slot before other public pages were researched. Startup discovery now attempts the public YC regional directory and Blume portfolio, with Villgro added for the India pilot. Each publisher initially receives at most half the candidate slots (minimum one). Remaining slots are backfilled only after the other sources have had their bounded discovery opportunity, preferring the least represented publisher. Free web search and named-company enrichment remain active. These are source configurations; company names/descriptions are fetched at runtime. Blume geographic conflicts and exited holdings are excluded; its investment-status label is stored as portfolio status, not company legal/operating status. Villgro rows with no location or status retain those gaps. Public portfolio coverage is inherently selective; current funding stage and match quality still need validation.

Each company snapshot records its discovery URL. `source_coverage` derives selected-company contribution, evidence contribution, unique cited claims, readable-card counts, coarse matches and failures from typed outcomes and frozen company evidence. Search links contribute zero company claims. Results distinguish a publisher that found companies from one that supplies supporting evidence; neither count independently verifies a fact. Single-publisher outcomes explicitly disclose the gap. Discover cards name their source, and coverage is grouped into directories, search, datasets and research pages, with individual retrieval logs behind source details. Dataset access/licensing is available within coverage; metadata-only Dataful entries are never presented as fetched company records.

`/operations` is now a shortlist portfolio overview rather than an arbitrary first-company dropdown. Explicit `?lead=` routes open company workspaces with Overview, AI plans, Evidence, Reviews and Activity. The overview presents company evidence, the saved AI assessment, a next action and prioritized evidence gaps. Four plan types separate diligence questions, incubation/GTM experiments, material requirements and investor-fit planning. Evidence links, model identity, missing inputs and stale-state notices accompany the output. Deal-room setup and existing financial-document workflows remain accessible from Evidence; promoted companies still open the same operations workspace from Discover.

`POST /api/operations/leads/{id}/prepare-jobs` starts a saved local background generation job. Its queued/running/completed/failed state, model, timestamps and errors are stored with the workspace; the UI polls while running and recovers progress after navigation/reload. It shares the existing single local-model slot. A process restart reports interrupted work rather than success; there is no distributed queue or automatic restart/resumption. Existing synchronous preparation remains for API compatibility. Current packs are reused; unsupported citations and evidence-version conflicts fail with saved evidence intact. Draft creation never marks incubation experiments, document release, investor outreach or closing as executed.

Validation: 63 targeted backend tests passed, covering independent directory parsing, geographic/status rejection, selection across publishers, blocked-source backfill, honest coverage counts, source/run/tenant isolation, citation validation, saved background results, failure/retry and restart states. Discovery and operations Playwright regressions passed, including shortlist-only landing, explicit company selection, progress across reloads, draft citations, stale plans, reviews, activity, empty states and mobile width. A real UI search (`source_run_e5c069d02126`) returned Waybill and Optifye.ai from YC, Niqo Robotics and Stellapps from Blume, and Navork Innovations from Villgro. This is bounded source diversity, not a comprehensive startup census. Deeper research completed in approximately four minutes with five model-proposed assessments. DuckDuckGo was blocked, while Mwmbl supplied discovery links; this remains a partial-coverage outcome. Official company-site URLs were resolved for some candidates, while missing geographic/business verification remains visible.

Real generation inspection exposed overly generic actions and name-only plan citations. Draft format version 2 now requires structured tasks (action, deliverable, required inputs and proposed success measure) and at least one business-evidence citation per stage. The local prompt requires experiments on the observed offering and does not assume it needs a prototype. Legacy packs become stale for format upgrade without discarding their history. These structural and citation checks improve specificity; they do not establish semantic correctness or completion of the proposed work. Discovery-source metadata is excluded from the company-review basis, while the underlying cited evidence remains included.

Generation and storage use separate contracts: legacy drafts remain readable, while the local model receives a schema requiring task fields and restricting evidence IDs to supplied business facts. This corrected an observed local-model failure where prose instructions alone left tasks/citations incomplete. The saved job exposes validation failures and retries, and stage labels say “Evidence collected” or “Questions prepared” instead of implying completed diligence.

Final live validation: Waybill's version-2 pack completed with `phi4-mini` in about 100 seconds (`automation_569dac1aae61`). Four plans were saved with structured tasks and valid business-evidence references. The incubation proposal names a procurement workflow experiment, elapsed procurement time, errors and customer feedback as proposed measures, while leaving baselines/thresholds unknown. Browser reload during generation retained progress; desktop/mobile inspection showed the saved deliverables, required inputs and evidence. Some wording remains generic and needs editorial judgment; structural validation is not an investment-quality or semantic-accuracy guarantee. Additional tests cover strict generation-schema fields/citation constraints, legacy-pack upgrades and rejection of action-only/name-only drafts. The updated frontend build/lint, browser regressions and focused backend checks passed. The stable API remains running with these changes.

### 16.19 Intent-led research and resumable local plans

The natural-language request “find companies in the fintech space in india which are rapidly growing” exposed three distinct failures: routing to company directories depended on the literal word “startup”; sector aliases broadened financial technology into unrelated technology businesses; and growth was never represented as an evidence requirement. `research_reasoning.py` now interprets the request into sector terms, explicit criteria, discovery queries and research topics before retrieval. Required sector, supplied geography and requested growth criteria survive model omissions. The existing company-directory catalog is available to natural company requests without asking for URLs; the notable-company dataset is only attempted for explicit listed/public-company requests. This is bounded catalog/search coverage, not a universal company registry.

The local model screens one company per bounded call against the criteria using supplied claim IDs, gives a short research-priority reason and proposes supported/unknown/mismatch verdicts. The decoding schema requires candidate and criterion entries and constrains citation IDs. Screening and assessment use isolated citation namespaces; query-specific review references are excluded from the assessment evidence payload to prevent invalid cross-stage citations. Validation excludes explicit geographic conflicts, requires business citations for sector support and requires recent measured operating comparisons for growth support. Funding, forecasts, portfolio membership and absolute customer counts do not establish rapid growth. Explicit source location fields and exact sector labels are checked directly and tagged as source-field checks, so a model omission cannot erase an observed fact. An investor holding’s portfolio status is excluded from the screening payload; an exit does not establish company closure or growth. Screened candidates publish progressively; missing model judgments remain unverified. Named-company research uses the requested evidence topics, follows observed links selected by the model and shares remaining page budget across candidates. When growth is unresolved it issues a short named-company operating-metrics search even if a homepage is already known, and prioritizes those destinations; otherwise a queue of generic profile/about pages can consume the entire budget without investigating growth. A second screening pass evaluates newly collected evidence. The default API research budget is 12 pages for five candidates; source and local-model outages remain partial outcomes. Search snapshots include the research plan, short decisions and criterion reviews; the UI shows this separately from source coverage. These are evidence-bound model judgments, not hidden reasoning traces or verified investment recommendations.

Identical re-read claims reuse their citation IDs and original claim records instead of breaking existing draft references. New source facts still change the workspace evidence basis. Query-specific screening metadata is excluded from that basis. Background company-plan jobs queue behind the current local-model task, deduplicate repeated submissions and reuse current packs without acquiring the model. There is a three-job per-tenant limit and a bounded wait; this remains an in-process local queue, not a distributed scheduler. Each of the four stages generates and saves independently with its evidence basis. A failed stage is retried once; later user retries skip stages already saved against current evidence. Source/revision conflicts still stop saving stale work. Restarted jobs expose interruption; they do not silently resume.

Plan policy version 3 uses a separate instruction for each lifecycle stage. Live inspection of the earlier shared prompt found incubation experiments incorrectly emitted under diligence/documents; policy upgrades invalidate older packs and regenerate all stages, including saved stage bases. The operations UI displays queued work, current-stage progress, how many current plans are saved, stale stage output and retained errors. Activity distinguishes earlier failures superseded by successful generation. Stage outputs remain internal proposed work: planning a diligence investigation, GTM experiment, document or raise does not execute it. Sending, signing and transfers remain disabled. Free Ollama inference and public retrieval remain the only runtime providers; no paid models, datasets or API keys were introduced.

Validation of §16.19: 88 targeted backend tests pass, including natural wording without “startup,” fintech-versus-generic-tech filtering, source diversity, stable claim IDs, citation namespace isolation, required screening references, source-field overrides, measured-growth rules, named growth searches, rejection of generic query hits, stage retry/resumption, queue deduplication, policy upgrades and evidence-version conflicts. Frontend build/lint and the isolated discovery/operations browser checks pass. The browser checks include AI brief/decisions, queued and partial generation, historical failures, saved plans, desktop/mobile layouts and no page errors.

Live query `source_run_e24428775e60` collected Paasa and SureBright from YC, Jai Kisan and Finvolv from Blume, and Agrosperity from Villgro. After correcting screening/assessment constraints, the saved evidence was re-screened and assessed with local `phi4-mini`; the refresh is recorded in the reasoning log and does not claim new retrieval. All five saved assessments have valid company evidence references. Paasa, SureBright and Finvolv have source-supported sector and India criteria; other core-fit gaps remain explicit. None has validated rapid-growth evidence. Source coverage remains partial: free search is sparse, some pages are blocked, and portfolio evidence is not independent commercial verification. A separate live named-growth query returned generic Shopify articles rather than company-specific evidence; the new pre-fetch identity filter rejects that class of result. Do not describe this as verified rapid-growth selection or comprehensive market coverage.

Waybill job `automation_da6382c778be` completed with four current policy-v3 plans at `2026-09-13T19:10:07Z`. Browser inspection verified an operating-evidence diligence task, a procurement workflow experiment, an investor-teaser preparation plan, and an investor-matching brief. The job queued behind discovery, saved each stage and retained output across reloads. These are proposed work products, not executed experiments, completed deal materials or a closed raise. Historical failed attempts and earlier source/model failures remain available for audit.

### 16.20 Substantive business analysis and growth evidence (2026-09-14)

The user rejected task-only plans as meaningless. `agents/business_analysis.py` now gives the local model separate structured contracts for business interpretation/economic risk, customer/buyer/trigger/channel/paid pilot, investor narrative prose, and mandate fit/proof milestones. The stored `OperationDraft` includes a decision and three cited analytical sections, in addition to its next task. Policy version 4 invalidates the old task-only packs. The existing evidence-basis, tenant, revision and partial-stage resumption checks remain. Observed output-failure checks trigger a corrective retry; they are limited pattern checks, not a semantic correctness guarantee. Pilot measurement formulas and contribution/cash-reconciliation methods are supplied by code after the model selects a metric. Proposals and measurement methods are not achieved results.

Background preparation first runs `agents/operating_research.py`: up to four observed company-site pages, following same-domain commercial links, using the SSRF/robots-bounded fetcher. The local model selects exact page-block IDs rather than inventing/paraphrasing quotations. New passages are persisted with source URLs; the research trace records accessible/failed pages and its evidence basis. A completed unchanged pass is reused on retry. Discovery also uses this business-passage extraction on known official sites, avoiding a second generic company-name extraction call. The API discovery page budget is now 24 by default (maximum 30), within the existing time/model limits. Coverage is still bounded and search quality remains a material limitation.

`agents/growth_analysis.py` extracts candidate annual comparisons from collected operating evidence and validates literal values, units, explicit consecutive fiscal/calendar years, company name, recency and source IDs before calculating percentage change in code. Forecasts, customer case studies, incompatible periods, zero baselines and unsupported numbers are rejected. A reported comparison is not an audit and does not automatically satisfy an undefined "rapid" threshold. The current implementation covers explicit recent annual pairs in a single passage; cross-document reconciliation and monthly/quarterly cohorts remain outstanding. Discover shows the measured comparisons or explicit evidence gap and named queries. The saved fintech run was inspected against its existing evidence and labeled accordingly; this was not a new retrieval. All five still lack comparable annual operating figures in that saved run. No claim is made that public figures do not exist elsewhere.

Operations now leads with a decision brief and an Analysis tab: diligence findings, GTM brief, investor narrative and fundraising assessment. Each analytical section exposes its source basis. The next task and missing inputs are secondary. Current analysis can be downloaded from `GET /api/operations/workspaces/{id}/internal-brief` as a Markdown internal brief; wrong-tenant and stale/incomplete exports are blocked. This identified internal artifact does not replace approved/anonymized deal materials or bypass existing financial/release controls. Evidence changes invalidate output as before.

**Live quality finding:** The installed `phi4-mini` repeatedly produced weak or unsupported interpretations despite valid JSON/citations, including treating demos as customer proof, reversing the acquisition channel, assigning an unknown funding stage and producing incomplete sentences under tight schema limits. Smaller, specific contracts, longer string headroom, concise-answer instructions, deterministic metric formulas and corrective retries address observed failures but do not establish reliable autonomous analyst quality. A comparison with the already installed `llama3.2:3b` did not justify switching. No paid inference, remote model or new model download was introduced.

The Waybill brief in `workspace_41fd0152cbe3` was explicitly reviewed and rewritten by Codex during this session. It addresses a critical-component paid pilot for hardware teams, order contribution and cash timing, repeat paid demand, investor mandate hypotheses and financing evidence gaps. Its provenance is `Codex · editorial analysis review`, with a separate `analysis_review` record and history event. This is not represented as unattended phi4-mini output, financial verification, legal approval or an executed pilot. Future regeneration clears that editorial-review marker. UI copy distinguishes unreviewed local-model drafts from this reviewed example. The one-off review is saved company content, not hardcoded runtime company logic.

Validation: 103 focused backend tests pass, including annual positive/negative growth calculations, literal/scope/forecast rejection, exact-passage research persistence, analytical contracts, known bad-answer patterns, source/citation isolation, resumable jobs and tenant/staleness checks on internal exports. Frontend build/lint pass. Live browser verification covered the reviewed Waybill decision brief and GTM sections, internal Markdown download, reload persistence, all mobile tabs and no page errors. The isolated operations regression covers background/retry/stale states and the new analytical sections. These checks establish software behavior, not investment-quality autonomous reasoning. Free broad search and unavailable/private operating metrics remain unresolved coverage constraints; no rapid-growth match or investor commitment was fabricated.

### 16.21 Transaction preparation workpapers and product provenance

Operational process references consulted: [Morgan Stanley, The Anatomy of a Deal](https://advisor.morganstanley.com/the-archer-lang-group/documents/field/a/ar/archer-lang-group/The_Anatomy_of_a_Deal.pdf) (sell-side transaction preparation, objectives, financial diligence and execution) and [YC, A Guide to Seed Fundraising](https://www.ycombinator.com/library/4A-a-guide-to-seed-fundraising) (startup financing). A sale process and an accelerator programme are distinct; the application combines internal preparation workstreams, not a claim to perform every regulated banking function.

`transaction_workpaper.py` derives a financial baseline from tenant/deal-matched document extraction, accepting only approved/edited finite numeric values with matching document block/page citations. Same-unit cash/burn and ARR/prior-ARR pairs support deterministic calculations with explicit limitations; ARR is conditional on recurring revenue, and cash coverage is not a forecast. Missing or proposed figures do not become zero. Workpapers expose engagement, financial/commercial diligence, capitalization, materials, investor process and closing deliverables with owners, exact records needed and completion criteria. Recorded reviews supply statuses; checklists are not executed deliverables. Existing reconciled workspace reads recompute this workpaper without mutating stored data. The local model receives the workpaper alongside public evidence, while private figures remain separate from public-source citations.

Operations exposes Workpapers and a tenant-scoped, read-only `data-request` Markdown download available before AI generation. Main banners and Analysis no longer advertise a model/editor; generation and editorial provenance remain in Activity and stored audit records. Existing company drafts are not silently rewritten. This change does not solve autonomous analyst quality, financial record acquisition, investor outreach, financial forecasting, valuation or closing execution. Validation: 52 focused backend tests, frontend build/lint, isolated operations browser regression including workpaper navigation/download link and mobile tabs.

### 16.22 Research → founder pitch → investment readiness (2026-09-14)

The user rejected exposing internal workflow machinery and generic analysis as the product. `/operations` now opens a shortlist and an explicit company journey with exactly three primary views: Research, Pitch founders, Get investment ready. Research answers what the company does, why to meet, the main commercial risk and a founder question. Pitch founders contains an actual introductory email proposing specific support, with a clipboard action. Readiness presents three ordered priorities with investor questions, actions, deliverables and completion criteria. A company-brief Markdown download contains these outputs and source passages. Public sources are collapsed; company documents, financial workpapers and approvals are secondary records. Raw generation/editor history is preserved under collapsed Technical history, not presented as progress or analyst work.

`agents/company_brief.py` adds separate compact structured contracts for these deliverables. `POST /api/operations/leads/{id}/brief-jobs` reuses the existing local queue and public company research. It does not confuse an existing four-stage legacy pack with a current company brief. Each deliverable saves independently and resumes on retry; tenant, citation, evidence-basis and revision checks still apply. Versioned contracts invalidate incompatible prior outputs; compatible earlier stages can migrate only after validation against current contracts. The model receives company passages and financial inputs/calculations, not the generic seven-workstream checklist. An existing editorial review can inform proposals only if it matches the current evidence version; it is not recast as verified public evidence. Original drafts/provenance remain stored.

Live output exposed invented customer/revenue thresholds, promotional case studies, claims that missing public evidence meant no real-world validation, and confusion between customer cost savings and company profitability. The generator now rejects these observed patterns and retries with the specific error. Short text limits, direct-question checks and per-field descriptions reduce rambling output. These are bounded quality controls, not a semantic correctness guarantee. Readiness remains proposed work: generating a pitch does not send it, and preparing priorities does not execute a paid pilot, prove demand or make the company investment-ready. No paid provider, remote inference or new model was added.

Contract v4 supplies a neutral founder meeting invitation and stable readiness completion/accounting definitions in code. The model supplies business interpretation, proposed pilot work and company-specific actions; it does not redefine contribution as company profit. Validation covers seven new backend cases (resumption, version migration, stale/tenant export rejection, old-pack queue distinction and observed bad outputs), alongside existing operating-workflow tests. The isolated browser regression covers the three-view flow, clipboard, citations, retries, mobile and records/history separation.

Live validation: Waybill's current company brief was generated through the local-model job, then migrated to v4's deterministic meeting invitation and readiness definitions without a manual company-specific rewrite. The live page and Markdown export both show the paid procurement-test offer, customer-demand records, company delivery economics and investor-summary priority. Desktop/mobile checks and clipboard regression pass; the founder email screenshot was visually inspected. This is a usable draft and proposed work programme, not a completed incubation engagement. Existing weak/older model output remains distinguishable through versioning and technical history.

### 16.23 Investment-case evidence, operating metrics and document-review purpose

User rejected the short engagement brief as an investment case and the legacy document-review page as the main product. Primary references revisited: Sequoia, Writing a Business Plan (https://sequoiacap.com/article/writing-a-business-plan), a16z, 16 Startup Metrics (https://a16z.com/16-startup-metrics/), and YC's live company profiles. Product purpose: a research-to-fundraise workspace for an accelerator/advisory firm. Research must establish business, team, customer/market, alternatives, traction, economics and financing questions; a drafted email or checklist is not readiness or transaction progress.

A concrete research bug excluded known directory company profiles whenever an official website existed. Operating research now queues the observed company profile before website subpages and requires the company name plus a link to the known official website for cross-domain profile identity. Explicit founder requests and biographical passages are collected alongside product evidence. Text checks prevent generic product references to a 'team' from becoming founder evidence and require actual request language for founder asks. Prior-employer achievements remain team background, not company traction. Refresh research is available even when an earlier brief is complete. No search provider, paid source or model was added.

`company_metrics.py` validates dated, completed-month company reports: recognized revenue, direct variable costs, cash, net operating burn, paying customers, completed orders and GMV. Missing values remain unknown. Code calculates delivery contribution/margin, consecutive-month same-currency revenue change, constant-burn cash coverage and GMV/order value where supported. It does not annualize growth, substitute GMV for revenue, infer retention from aggregate customer counts or generate a readiness score. Each input carries source/definition notes and a saved record ID; inputs are company-reported, not automatically verified. Corrections retain earlier submissions and supersede a month's active record. Currency and accounting/cohort definitions still require user/source correctness; these aggregate inputs do not establish an audit.

Workspace metric updates use tenant scoping and revision checks; active local jobs block conflicting updates. Evidence hashes include metric updates, invalidating prior generated briefs and reviews. Current workspaces expose calculations and a standalone metrics download; the LLM receives these figures as company-reported context. Company-brief exports include team/founder/market evidence and the metric report, and still refuse stale generation. Private monthly inputs currently have a direct UI/API entry path; automatic accounting integrations and structured multi-document time-series extraction are not implemented.

The deal `/review` page is now labelled Document figures and explains its narrow purpose: compare extracted financial fields with source documents before deal materials use them. It has direct document upload/extraction controls, a return link to the originating company, and collapsed unavailable fields. The command bar and technical document lifecycle are secondary. Existing compilation/financial approval controls remain; reviewed document figures never imply investment readiness. Upload invalidation refreshes source documents and the operating workspace.

Validation for this pass: 62 focused backend tests passed, including monthly calculation edge cases, tenant/revision/correction behavior, profile identity matching and founder-role classification. Frontend build/lint and both isolated browser regressions passed. Live verification covered the real empty document-review page, return to company metrics, updated founder-request pitch, and company-brief download. The refreshed Waybill profile includes source-reported founding year/team size and the request for hardware-procurement introductions; it still supplies no dated revenue or margin observations. No synthetic financial figures were saved to Waybill. Contract v5 uses a source-anchored introduction-request template when the founder explicitly names that target; other drafting remains local-model work. This addresses an observed role reversal, not proof of reliable autonomous business reasoning.

### 16.24 AI-authored outputs and automatic company-update ingestion

The user explicitly requires AI-first responses and AI-generated workflows with minimal operational labor. Contract v6 removes the deterministic founder-request pitch, neutral meeting invitation and overwritten readiness titles/completion definitions from the company product. The model writes the complete email and chooses one to three priorities, each with a reason, required input/dependency, investor question, action, artifact and completion criterion. Existing templates and editorial packs are archived in `company_brief_history`, not silently relabelled as autonomous generation. Per-stage retries, persistence, evidence version checks and validated citation aliases remain.

Input composition now balances evidence categories before taking more passages from one category, carries URLs, origin, retrieval/observation dates and truncation flags, and explicitly supplies founder requests, selection context, evidence gaps, permitted capabilities and financial context. Public passages are bounded to twenty-four of at most nine hundred characters each; operating history is limited to the latest twelve months with omission counts. Earlier editorial prose is no longer fed back as analytical evidence. Each deliverable records the input hash/length, categories, source/evidence counts, generator and attempt count. This is an auditable input change, not a measured accuracy percentage.

`POST /api/operations/workspaces/{id}/metric-imports` accepts a named original company update as text and queues work through the existing local model queue. The model selects monthly observations with exact reporting-period, currency and per-metric quotes and literal numeric tokens. Code checks that the quotes exist, binds values to explicit month sections, rejects forecast/estimate/annual scope, validates metric labels, and normalizes numeric scales without model arithmetic. Unsupported/ambiguous material becomes a retained exception. The original text and model proposals remain in `metric_imports`; accepted figures and their individual source references feed `metrics_report`. Partial monthly corrections replace only explicitly supported fields, preserve other known figures, retain old submissions and refuse automatic currency replacement. The same job then regenerates the research, email and readiness priorities using the updated evidence. No manual per-field approval is required for these internal, labelled company-reported inputs.

The primary metrics UI offers a pasted-update flow with persisted job progress, source quotes and exceptions. Manual numeric entry remains a secondary correction path. Monthly actuals and calculated results are not independent financial verification; the parser deliberately rejects ambiguous table-column layouts, mixed scopes and missing currency instead of guessing. The local in-process queue is still not a durable distributed orchestrator. AI authorship does not imply that customer experiments, introductions, investor outreach or closing have occurred. Those execution integrations remain incomplete and no external communication was enabled.

Live validation exposed two additional defects: free-form numeric/period quotation by the small model was unreliable, and character bounds applied inside constrained decoding produced clipped or padded sentences. The update extractor now asks the model only to select and classify numbered source blocks. Code recovers literal periods, currencies and numeric tokens, retains schema validation, and reports unaccepted metric blocks. Model notes that contradict accepted, validated observations stay in the raw proposals instead of becoming user-facing exceptions. The shared local adapter applies string length constraints after generation; structured shape and citation enums remain in decoding. Company drafting uses narrower context per stage; the founder email gets explicit sender/recipient roles and the exact request excerpt, without the research question or unrelated biography. This reduces context contamination without writing the email in code. Failed draft attempts retain their raw structured output and validation error for diagnosis.

Validation outcome: the default installed model selected all seven values across two explicit historical months from an isolated synthetic update in about nineteen seconds, with exact citations and no unresolved extraction exceptions after input redesign. No synthetic financials were saved to a real company. Browser regressions cover the update submission, persisted progress, exceptions, manual fallback, company views and mobile layout; backend tests cover source/period/currency/value rejection, correction preservation, tenant/revision checks, regeneration and decoding/validation separation. Live tests of phi4-mini and the already-installed llama3.2:3b still exposed weak analyst reasoning, founder/customer role confusion and generic readiness outputs. The successful schema-complete comparison was not promoted to the user's company as investment-quality work. Generic category-only priorities and “records are available” completion criteria are rejected. No claim of an autonomous full lifecycle, measured overall accuracy improvement or workforce replacement is justified by this pass.

### 16.25 Company decision queue and independent investment preparation

The home page now connects shortlisted companies to their engagement decision, current AI work and missing company inputs. Old standalone document records remain accessible in a collapsed section. Document-processing counters are not investment outcome metrics. The investor-materials page explains the purpose of a memorandum, anonymous introduction and financial scenarios, links to the sourced company's investment case, and routes incomplete inputs to source review instead of an empty compilation action.

`agents/investment_case.py` writes a versioned preparation case independently of the legacy company brief. Its first model decision is `proceed`, `clarify` or `do_not_pursue`. The last ends this incubation path; unresolved suitability permits only a screening memo. Supported initial preparation produces an actual decision memo, commercial validation working document and initial investor narrative, with specific missing records and why each matters. It does not mark commercial experiments, engagement authority, investor contact or fundraising execution complete. Public company evidence alone is not proof of financial performance or current intent to raise.

The local model chooses an observed source ID for the business description; code recovers a literal quote instead of allowing an invented category to redirect the engagement. Input context separates search geography from company location and excludes a generic list of missing operating metrics that previously contaminated recommendations. Dated operating figures, calculated measures and source status remain available to the model. Model decisions and narrative remain generated rather than company-specific hand-authored replacements. Validation is a bounded check, not a guarantee of semantic correctness.

Preparation is submitted through `POST /api/operations/leads/{id}/readiness-jobs` and exported through `GET /api/operations/workspaces/{id}/investment-case`. The shared queue, compare-and-swap writes, tenant scope, evidence invalidation, partial stage persistence and history apply. Evidence changes prevent stale exports. Existing drafts remain available in records, not presented as current investment work. The main readiness view renders products, source excerpts and required inputs, with a route back to company updates.

Research policy 5 accepts www normalization on the known domain and asks the local model to choose among observed commercial links, retaining the questions behind the choices. This fixes skipped company subpages and reduces navigation into careers or community content. Link selection and extraction remain bounded; inaccessible sites and small-model reasoning failures remain material limitations.

Process references: [YC's seed fundraising guide](https://www.ycombinator.com/blog/how-to-raise-a-seed-round/) recommends a concise summary/deck supported by business, team, traction and financial information; [Sequoia's business-plan guide](https://sequoiacap.com/article/writing-a-business-plan) organizes the investment argument around customer problem, solution, timing, market, competition, business model and team. These guide document purpose, not prefilled company conclusions or legal eligibility.

Navigation has a single company queue: `/operations` without `lead` redirects to `/`; the company research/pitch/preparation tabs retain their URL state. Suitability input now reuses the balanced business-evidence selector, including explicit founder requests, source dates and prior-career attribution. Validation rejects reversed advisor roles, active-listing readiness rationales, generic record names and negative financial-health inferences from absent data. These checks target observed failures; they do not establish investment-grade accuracy.

Schema v3 adds source-bound maturity and an optional explicit founder-request reference. `proceed` is valid only with early-business evidence or a relevant support request. Established/unknown businesses without that basis require clarification or exclusion. This prevents generic innovation copy from authorizing an incubation program. A do-not-pursue decision must route back to sourcing; it cannot be followed by invented partnership consulting. Source binding and validation constrain the local model, but do not prove all generated reasoning correct.

Maturity classification now runs separately from recommendation. It is persisted before the second model call, whose decision enum excludes `proceed` for established/unknown businesses without a founder-support request. This prevents a small model from combining an established-business classification with a contradictory approval. A failed recommendation retains the classified stage and source evidence for retry. Long-form generation still depends on local-model quality; the Waybill comparisons in this implementation pass were not accepted as investor-grade work or promoted to its live record.

Validation for this pass: 53 focused backend tests passed, plus build/lint and browser checks for the company journey, preparation decisions, financial-source review, document prerequisites and mobile layout. The real DRW record completed the two-step flow with the already-installed `llama3.2:3b` model and returned `do_not_pursue`; its sourced decision exports through HTTP. `phi4-mini` remains the configured default, and earlier live attempts timed out or produced unsupported recommendations. No paid inference or model download was introduced. This establishes a working guarded decision path, not measured overall investor-analysis accuracy or full autonomous fundraising.

### 16.26 Practitioner-grounded preparation and model evaluation (2026-09-14)

The core objective is useful analyst work from company evidence, not generic summaries or a new workflow UI. `research_corpus/practice/methods.json` records primary references from Morgan Stanley, Houlihan Lokey, YC, Sequoia, Techstars, SINE, E-Cell IIT Bombay, NVCA and SEBI. Original methods distinguish mandate selection, underwriting, venture validation, founder outreach, financing design, investor targeting and transaction preparation. Source scope and checked dates are retained. They guide methods, never prove company facts, current legal compliance or relationships our product possesses.

`investment_practice.py` selects methods by stage and supplies a bounded original synthetic teaching example where available. It is integrated into sourcing interpretation/screening, company research/pitch/readiness, legacy stage analysis and investment preparation. Method/source/example fingerprints are persisted with new company deliverables. Company evidence remains separately cited; evaluation cases and validation examples never enter generation context. This is inference-time grounding and example-based prompting, not model-weight training.

Preparation schema v5 adds an AI-authored decision question, next action and completion test to each working document, visible in the existing company page and Markdown export. Reviewed transaction workpaper inputs now accompany public facts and monthly operating figures. Brief schema v7 and preparation v5 run `preparation_quality.py` after generation. Four explicit model judgments cover grounding, usefulness, stage fit and completion; cited draft fields are constrained to actual field paths. Each readiness priority is checked separately. A material issue triggers a bounded rewrite; rejected attempts are retained and previous completed work is preserved. Current-result checks require the review contract and current method fingerprint. These model judgments are fallible critiques, not audited verification or permission for external action.

`scripts/evaluate_preparation.py` compares two installed free models on six synthetic business scenarios using production schemas. Raw responses and errors, plus explicit limitations of the automated checks, live under `evals/investment_preparation/`. `scripts/export_preparation_training.py` exports ten original teaching records (eight train/two validation) in chat format with provenance and split checks; it does not read client records or train weights. The development evaluation is not an investor-quality benchmark. Initial critic failures are retained; an optional empty issue array was inadequate, and a whole-plan critique missed later bad priorities. See the evaluation README for evidence and remaining gaps.

The intended measurable value is less analyst rework per qualified company, supported investment arguments and usable founder/financing materials. Counts of drafts do not establish market readiness, investor engagement, regulatory approval or funds raised. External messaging, signatures and money movements remain unimplemented/unauthorized; there is no new claim of autonomous closing.

Preparation v5 corrects the engagement question: assess whether scoped company-research and preparation work is useful, rather than whether the target needs an accelerator or should receive investment. Existing products or earlier accelerator participation are not automatic exclusions. Maturity conclusions may not contradict cited early-company history. Directory request blocks are reduced to their explicit support span, avoiding sales-offer/recipient inversion; maturity receives founding history and an as-of date separately. `PREPARATION_MODEL` can select a different installed local model from fast sourcing. Qwen3 8B was downloaded for controlled comparison; no weights were fine-tuned.

### 16.27 Consistent evaluation and useful repair feedback

Recorded preparation evaluations use the production document schema and validation helpers. Investment memos and financing narratives leave measurement plans to commercial validation; both production and evaluation supply the rejected final answer and specific feedback on retry. Evaluation reports retain input and schema hashes, practice fingerprints, route details, rejected answers and an explicit success/failure/interruption status. A checked draft still means automated critique only, not independently verified investment analysis.

A real-company replay exposed a short record-label error masking unsupported outcome assertions. The bounded repair now receives all detectable source, number, outcome and record-request defects. If JSON fails a length constraint, structurally usable prose is checked solely to improve feedback; only a subsequent answer passing the full original contract can become a work product. Benefit checks include progressive wording such as “reducing errors.” These finite checks do not resolve all unsupported business-model assumptions or replace semantic evaluation.

Preparation failures report the actual saved draft count. An empty pack retains evidence and the engagement assessment but does not claim saved documents; partially saved drafts retain unresolved review flags. No manually written company analysis replaces model output. The queue and inference routing behavior are unchanged by this follow-up.


### 16.28 Independent analyst deliverables and evidence contracts (2026-09-14)

The primary company workspace now generates four independently checked draft types: research memo, founder proposal, diligence request and investment-readiness actions. `agents/analyst_pack.py` owns a separate versioned protocol (currently v7); legacy briefs and investment cases remain historical records. `POST /api/operations/leads/{id}/preparation-jobs` starts the new path and `GET /api/operations/workspaces/{id}/preparation-pack?document=...` exports current, completed sections. Document availability updates as individual sections finish. No Codex branding or implementation history is shown as the company result.

The collector reads the known company website and an observed commercial-terms link before generation. Retrieval respects the existing public-web access controls. The bounded page coverage is recorded, not represented as comprehensive diligence. AI classifies source passages as offering, customers, pricing, traction, founder history, company/partner structure, marketing or a founder request. Code binds exact quotations, source URLs and retrieval/observation dates. Labels are fallible hints: absent classification is not proof that information or business activity does not exist. Company-reported monthly records and deterministic calculations join this evidence record, preserving their distinct provenance.

Generation consists of nine small sections. Economics has separate revenue-mechanism and unresolved-economics fields; the investment argument separates conditional opportunity, risk and next decision. These fields prevent one product-description paragraph from substituting for every task. Founder outreach is an unsent draft. Diligence names actual company-held records and their scope; readiness links those requests to analysis, an output and a decision admitting adverse findings. Financial calculations remain code-owned; missing figures are not invented, treated as zero or replaced with public tariffs.

Each section has bounded evidence input, its own response schema, review, repair history and input/contract hash. Completed unrelated sections remain saved. Readiness waits for its linked diligence request; changes to a dependency invalidate the dependent section. Code assigns IDs to actual draft sentences. Review objections select a draft sentence ID and an evidence/task basis; code attaches both exact quotations. Models no longer transcribe either side. This guarantees reference binding, not the correctness of the critique. Saved review errors are reused only under the same review contract and model configuration. A malformed review retries the review with its actual binding error; it cannot drive a rewrite of valid prose. Automatic review remains fallible and is not investor certification.

A critical adapter correction supplies response-field descriptions and limits to non-thinking model calls. Previously those calls only received the JSON decoding grammar, which did not communicate field purpose. Both thinking and non-thinking calls now receive the actual output contract; decoding keeps relaxed string limits to avoid cutting prose mid-word. Qwen3 non-thinking defaults follow the model's recommended sampling rather than greedy decoding. Source passages remain untrusted data, and no hidden reasoning is persisted.

`evaluate_analyst_workflows.py` executes the same code in isolated stores with optional public-page collection. The cases include Paasa (India/fintech), Notpla (UK/materials) and SunCulture (Kenya/solar irrigation). Reports retain actual final answers, attempts, latency, completions and corrections. Human-readable content auditing is required in addition to automatic completion before selecting a model. Earlier diagnostics showed why: a repeated business paragraph was accepted as an investment argument, and another model timed out. Redundant historical dumps were removed in the MVP cleanup; the latest baseline and audit remain. Test success and valid JSON do not establish investor-quality preparation or autonomous fundraising. Current real-output acceptance results are recorded separately in `evals/investment_preparation/section-workflows/README.md`.

The explicit local `AnalystModel` profile separates bounded source classification, section writing and critical review. Classification is non-thinking; writing uses the requested mode; supported critical reviewers use thinking. The per-run profile persists across retries. Qwen3.5 9B is installed for evaluation, not promoted as the default. Polling uses a compact, tenant-scoped work view without raw model attempts or rejected candidate text; full records remain stored. Model selection requires the current implementation hash, a consistent configuration and independently audited complete results for every case. These changes are prompting, routing and software validation, not weight training.

The Qwen profile now supports a separate reasoning budget with an answer continuation, following the [Qwen thinking-budget method](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/thinking_budget.md). Intermediate reasoning remains request-local and is never persisted or shown as source evidence. Final JSON still passes schema and reference checks. Explicit runs may select a different installed reviewer through `review_model`; no cloud inference or automatic runtime model installation is enabled. Retrying preserves the selected writer/reviewer configuration. Changed review policies recheck saved prose without blindly inheriting old passes.

Protocol v6 separates literal source claims within mixed page chunks. Code binds each exact span to the original source/date and rejects paraphrases; semantic categorization remains model-selected. Administrative onboarding is retained under operations and excluded from commercial drafting inputs. Missing commercial evidence blocks a section rather than substituting an arbitrary administrative passage. Founder opening is a source-attributed observation plus an unanswered commercial question. Economics explains the charging mechanism without restating numerical tariffs; exact schedules stay attached as source evidence. Diligence targets aggregate/redacted business records rather than customer identity images. Preparation POST responses use the same compact representation as workspace polling.

Stopping preparation is tenant- and job-scoped. Queued work stops before model construction; cancelling running work changes the revision so stale completions cannot overwrite saved sections or a replacement job. An in-flight inference may finish before releasing its slot; this is not immediate GPU cancellation. The current Paasa content audit still fails acceptance despite eight saved sections. See the preserved v6 audit; no cross-company promotion or autonomous fundraising claim is justified.

### 16.29 MVP product contract and cleanup (current priority)

**15 September 2026 amendment:** the user requires model-authored discovery, company information and drafts, and selected worldwide coverage across sectors. They explicitly authorized clearing the old companies after a verified local backup. The active v10 path records raw model answers and publishes exact projections; v9 code-authored templates and the frontend reading guide are retired from the default flow. Existing labels, source extraction/binding, calculations and validation remain code responsibilities. Historical recommendations below to normalize generated prose or delete evaluation dumps do not apply to this checkpoint: preserve original responses and regression fixtures.

**Current result:** reliable fresh generation is not fixed. The latest live GoCardless job failed after 61.186 seconds/two calls, publishing zero sections; no live v10 nine-section pack has completed. The new readiness writer proposes narrative analysis and does not require an executable typed measurement plan. Its presence does not demonstrate economic validation, completed diligence or investment quality. The user requested a thorough state log and push, with no further inference during the checkpoint. Read [handoff §23](SESSION_HANDOFF.md#model-authored-reset) and the [v10 evidence index](evals/investment_preparation/section-workflows/v10-model-authored/README.md) for exact implementation, failures, budgets and tests. Later chronological subsections preserve earlier results, not current release status.

This section controls the next build scope. Earlier lifecycle sections describe the longer-term ambition; they do not imply that current preparation, investor communication or closing capabilities are release-ready.

**MVP promise:** describe an investment thesis, discover relevant companies, shortlist one, and produce a sourced research memo, founder approach and investment-readiness work plan. Sectors and regions remain configurable. India is an optional pilot, not a product restriction. AI authors company analysis and proposed work; code handles retrieval, source binding, arithmetic and state. Public evidence supports research; company-held records support actual financial diligence.

**One company journey, three steps:**

| Step | User question | Useful output | Completion boundary |
| --- | --- | --- | --- |
| Research | Is this company worth pursuing? | Business/revenue explanation, conditional investment argument, material risk and next decision with evidence | A sourced draft is available; investment merit is not certified |
| Pitch founders | What help should we offer? | Source-specific founder approach, a concrete proposed deliverable and an invitation | A draft is available to copy/download; no outreach has occurred |
| Investment readiness | What needs to be resolved? | Each diligence request paired with its required records, proposed analysis, deliverable and decision criterion | Proposed work remains unexecuted until records arrive and work is completed |

The home page is the shortlist and next-decision queue. Discovery is the entry point. Diligence is part of readiness, not a fourth parallel destination. Company records, financial inputs, source details and history are supporting views. No section count, generated document count or AI-review verdict is presented as an investment-readiness score. Unknowns and failed work stay visible. A stale pack cannot appear current. Legacy document routes and saved company data remain accessible.

**Implementation sequence:** first make one complete company pack useful; then evaluate it on unrelated companies across sectors/regions; then address repeatable discovery coverage and execution gaps revealed by that evaluation. Founder proposals must derive from the same commercial uncertainties and requested records as research/readiness. Diligence requests must resolve distinct questions. New UI pages, extra reviewer agents, wider model sweeps and more generated reports are not substitutes for passing this test.

**Proposed release gates:** ten companies across at least three sectors and three regions; every material assertion traceable; no invented financials or claimed verification; useful company-specific proposal and nonduplicative requests; at least nine workflows completing without engineering intervention; practitioner review finding the outputs usable with minor edits. Measure latency and repair effort on the target hardware and agree an acceptable bound before release. These are acceptance targets, not achieved results. Autonomous sending, signing, money movement and closing are outside this first release.

**Repository hygiene:** keep one full-workflow evaluator (`scripts/evaluate_analyst_workflows.py`), reusable source cases, the content rubric, and the latest failed application baseline/audit. Keep regression tests and the single browser journey check (`scripts/check_operations_ui.cjs`). Remove redundant run dumps, obsolete model-comparison outputs and standalone reviewer experiments. Do not remove runtime modules, user documents, live database records or legacy document features as incidental cleanup. The existing content-quality failure remains open after this UI/design cleanup.


MVP implementation update: protocol v7 adds a persisted AI-authored pair of investment questions in distinct decision dimensions. Revenue and cost questions share the unit-economics dimension so they cannot be split into nominally separate agenda items. Diligence question fields are bound to the selected questions; each readiness action receives its corresponding request. The founder proposal is generated after readiness action A and receives the actual request, analysis and investment decision. These dependencies are included in section input hashes; unchanged downstream content stays cached. A changed dependency regenerates only affected work.

Source selection filters navigation-heavy passages and applies explicit per-page and overall budgets. Individual literal claims persist when another claim in their batch fails; retries receive only rejected claims. The audit retains the model's attempted claims. Review inputs distinguish unanswered questions, conditional hypotheses and proposed work from reported descriptions. These changes are under real-company acceptance testing; passing unit tests is not release approval.

Generation reliability follow-up: schema-formatting failures and substantive review objections now have separate bounded retry budgets (at most four section attempts). A formatting correction cannot consume the only content-revision attempt. Citation-only suffixes with selected fact IDs are removed in code before repeating schema validation, including overlong final JSON; unknown IDs or prose following the suffix prevent cleanup. No company claim is rewritten by this normalization. The original normalized response is retained in the attempt audit.

Investment questions now must be answerable from identifiable company-held records; competitor adoption and total-market comparisons require suitable external data rather than company billing ledgers. Agenda instruction/schema changes participate in cache validity, and agenda figures are checked against the selected source facts. Completed internal drafts and source coverage are tracked separately: omitted unsupported excerpts remain an explicit coverage limitation, not an automatic failure of otherwise completed drafts. Content review validity is fingerprinted from its actual prompts, schemas and validators instead of every unrelated pipeline edit. These changes do not waive content review or establish investor-quality output. The live acceptance result is maintained in `evals/investment_preparation/section-workflows/acceptance-latest.json`.

Input-isolation follow-up: navigation/menu labels and repeated document titles are excluded from collected body text, while their destinations remain discoverable; body links receive priority and substantive footer disclosures remain available. Successful page refreshes replace only prior `preparation_public_page` snapshots from the same URL, retaining retired evidence in workspace research history. Failed fetches leave the previous snapshot intact. Planning now supplies only typed questions, dimensions and references to downstream work; unreviewed planner explanations are not promoted into evidence or used as premises for generated advice. Commercial interpretation belongs in the reviewed research deliverable.

The final local profile routes investment arguments, readiness analysis and founder proposals through bounded reasoning on their initial attempt; extraction and simple descriptions remain fast, while reviewer/repair reasoning is independently configured. This behavior is recorded in the generation profile. Draft fields now have enough length headroom for ordinary explanations. Numbered list labels and explicitly proposed cohort windows are treated as document structure and measurement scope, not company-reported metrics; unsupported financial figures remain rejected. AI-review fingerprints cover the critic's actual contract, while current code/schema validation still runs whenever saved work is published. Live model acceptance remains separate from regression-test success.

Final consistent-profile application test (2026-09-14 UTC): the job finished partial, with 7/9 generated sections, 21 model calls and 30.7 minutes elapsed. The development audit accepted only 2/9 sections with minor edits. Outstanding defects include unclear revenue/cost reasoning accepted by the model reviewer, weak founder questioning, and a failed second evidence request that blocked its action. The full report and original outputs are in `acceptance-latest.json`. Regression verification passed 269 tests plus frontend build/lint and browser checks, including the live three-step pages and Markdown export. These are engineering results, not a completed first-company milestone or MVP release. No additional model profile was promoted and no cross-company acceptance run was started after this failure.

### 16.30 Bounded reference comparison and next-session handoff

The user then authorized one reference pack and one bounded capability comparison before further broad development. The separately authored `evals/investment_preparation/section-workflows/paasa-reference.md` contains a research memo, founder proposal and two linked diligence/readiness work packages. It is evaluation material, not a production template, trained output or successful application deliverable. The model received only compact source-checked paraphrases, not the reference answer.

The unchanged v7 pipeline was tested in an isolated Store with Qwen3.5:9b, task-specific reasoning for complex writing, and fast model review. Limits were one correction per stage, 24 model invocations and 20 minutes. This differs from the preceding reasoning-review profile, and the input was curated; the comparison does not isolate one causal configuration change or validate automatic sourcing.

The test was stopped after a material error passed review and propagated: a request recommended a negative finding when fees were below customer assets under management, and its readiness action compared amounts with rates without a defined valid calculation. Extraction had also removed the Apex subject and a pricing qualification. Five sections had completed generation; the four later sections were not assessed. One targeted external audit-directed field correction removed the direct fee/AUM comparator but retained an unclear method and failed the unchanged output validator. Total elapsed time including intervention/correction was 472.34 seconds (7.9 minutes), with 16 model tasks including one interrupted task. The original answers, model reviews, feedback and correction remain in `paasa_reference_test.json`; `paasa-comparison.md` explains the failure. No live company record, production prompt or model default changed, and no further-company run or model promotion followed.

The next proposed engineering work at that time was (1) preserving complete source statements and qualifications through AI selection and (2) validating structured financial analysis before prose publication. The subsequent implementation and its remaining acceptance failure are recorded in §16.31 below; preserve the earlier result as historical evidence.

### 16.31 Source context, semantic plans and a bounded v8 workflow

Protocol v8 implements stable-ID source selection with code-owned complete bounded context, content-aware selection caching and selective downstream reuse. The existing measurement module now validates economic roles, entity/service/population/window/exposure, units, stock/flow basis, revenue presentation, cost deduction and supported decision purposes. The AI proposes the typed plan in its diligence request; code derives the record request, decision and paired readiness action. Missing records leave the decision unresolved. These checks do not verify model-assigned meanings or replace reconciliation of actual records.

The user selected a two-minute maximum for fresh work. Preparation defaults to 120 seconds, 24 logical tasks and 32 raw requests; queue waits and continuations share the deadline. Expiry cancels the local request, saves partial work and requires explicit resume. Cached validated candidates and complete work are reused. Two derived actions remove four model tasks from the no-retry fixture. Initial agenda selection uses the explicit profile thinking setting rather than forcing extended reasoning.

The [v8 report](evals/investment_preparation/section-workflows/v8-interface-update.md) records 301 passing focused tests, frontend/browser checks, a 119.77-second full attempt that saved only two of nine sections, and one subsequent 11.517-second agenda probe that still had ambiguous financial wording. The original evidence-loss regression was prevented, but the full attempt never reached the typed request. Final full-workflow quality and latency remain unproven; **§16.29's MVP release gates remain unmet**. Cached fixture resumes around 20 ms are not evidence of instant fresh analysis. No paid services, model downloads, live company regeneration or model promotion occurred.

`SESSION_HANDOFF.md` is the detailed operational snapshot and resume guide; §16.29 remains the product contract. No investor-quality or autonomous-fundraising acceptance is claimed. Later user instructions control any next implementation or spending decision.

### 16.32 Compact plan capability gate

The user authorized testing a smaller two-plan contract before conditionally replacing the many-stage workflow. `CompactMeasurementPlan` declares shared scope once and expands explicit model-selected operands into the existing canonical validator. The existing evaluator gained a one-case, one-request, 60-second capability mode with no retries or promotion. These experimental schemas are not connected to production orchestration.

The [retained result and audit](evals/investment_preparation/section-workflows/compact-diligence-gate/README.md) record 45.657 seconds, 758 output tokens and 0/2 accepted plans on the five curated Paasa source paraphrases. The model confused contribution amounts with margins, contradicted gross/net cost treatment and compared transaction counts with customer counts. It also selected unconfirmed entities and proposed a problem-resolution measure that its records could not establish. Canonical validation rejected both original plans; no live data changed. The reference answer was not supplied to inference.

The condition for integrating the proposed faster workflow failed, so production remains v8. No further run, model sweep, paid provider or profile promotion followed. A materially different inference approach needs a bounded capability test and any required access/cost/privacy decision; the current evidence does not establish reliable fresh output within two minutes. See handoff §16 for the operational continuation.


### 16.33 Shared initial preparation v9 and live verification

The latest user instruction required continuing the fix after the compact gate failed. The default API now uses one shared source/service/action selection, one AI-written founder proposal and one focused review. Code preserves complete quoted source context and qualifications, binds reported product labels to their supporting passages, carries derived-question citations, and supplies registered contribution/activation quantities, records, formulas and decisions. The founder offer, explicit customer-record request and invitation remain AI-written. Published opening context is quoted exactly; copying the proposal excludes that source context.

The initial customer question is intentionally first-action activation. A durable pump is not required to be purchased repeatedly. Registered event choices exclude satisfaction and causal outcomes. Broader repeat-use/retention helpers remain separate future work. A proposal is reviewed against its intended work contract; missing private records are requests, not invented observations. Optional Qwen3.5 reasoning continuation now preserves its reasoning prefix through raw completion, but the default profile uses three short nonthinking calls.

The shared budget is 120 seconds, at most six logical calls and ten HTTP requests, with explicit partial resume and unchanged-work caching. The final same-implementation checks completed nine sections with three calls/no retries: live Paasa API 51.449 seconds including collection; SunCulture 43.11 seconds; Notpla 41.56 seconds. Cache checks took 21.8–94.3 ms without additional model calls. Validation passed 350 focused tests, frontend build/lint, isolated browser coverage and the actual live pages. [Original outputs and separate audits](evals/investment_preparation/section-workflows/v9-service-binding/README.md) are retained alongside the [failed development runs](evals/investment_preparation/section-workflows/v9-workflow-fix.md).

The stable API was restarted without reload after checking active jobs. Live Paasa is now v9; its original v7 content is preserved in history and a before snapshot. No paid inference, model downloads, weight training or external outreach occurred. These are successful internal **initial-preparation** checks, not §16.29's full release gate, verified company performance or perfect/general reasoning. Source noise and coverage, precise private-data definitions, unseen companies, practitioner review and execution of actual diligence remain open. Handoff §17 is the current operational snapshot.


### 16.34 Source cleanup and confidence after unseen checks

[Handoff §18](SESSION_HANDOFF.md#source-cleanup-latest) and the [result index](evals/investment_preparation/section-workflows/v9-unseen-source-cleanup/README.md) supersede the earlier operational snapshot. Three homepage-only unseen development checks completed in 54–69 seconds, but Resend failed content review despite an automatic pass. Source budgets, pricing-link selection, order-event/cost-input guards, scoped offer repairs and source presentation were corrected without increasing the two-minute limit. A final live Paasa initial draft completed in 45.5 seconds with one targeted repair; 362 tests and frontend/browser checks passed. All original failures remain preserved.

Confidence is moderate for assisted initial preparation and low for autonomous investment judgment or execution. Necessary source/record checks do not establish general reasoning accuracy. Source summaries remain verbose and sometimes select peripheral content; the Resend retest is not full research acceptance. Actual company-record reconciliation, broader unseen/practitioner acceptance and §16.29's release gates remain unmet. No external communication or financial execution occurred.

### 16.35 Research reliability and financial source qualifications

The latest reliability change binds concise research/founder excerpts to complete parent sources, adds source relevance to the combined review, and retains complete commercial qualifications. Shared review evidence is deduplicated. Generic named-plan context checks prevent order execution on a neighboring trading service from being accepted as managed/advisory activation; unsupported order choices are also excluded before inference when no ordering evidence is supplied.

Financial calculation guards now defer explicit double deduction of delivery costs, overhead mixed into variable costs, and cash coverage using restricted/customer funds. Exact financial source passages and unresolved-calculation reasons survive into model evidence and exports. Complete recent financial facts share the bounded evidence budget with public sources. These checks do not establish the truth of company records or constitute a complete semantic/accounting validator.

See [handoff §20](SESSION_HANDOFF.md#research-reliability-latest) and the [verification record](evals/investment_preparation/section-workflows/v9-research-reliability/README.md). Final live Paasa: nine initial sections in 60.55 seconds/four local calls; saved work 57.517 ms; 200 focused tests and browser/build checks passed. The preceding model-approved Paasa result failed content acceptance and remains a regression fixture. This improves initial preparation reliability; it does not establish autonomous investment accuracy, complete research/valuation coverage, independently verified accounts or practitioner acceptance.
