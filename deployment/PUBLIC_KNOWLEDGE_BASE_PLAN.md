# Scheduled public knowledge base for worldwide startup research

Design checkpoint: 1 October 2026. This extends the existing exact ES caches;
an offline rights-gated registry, immutable content-hash staging and leased SQLite
outbox now have a bounded HTTP collector, retained attribution snapshots,
deterministic passage extraction, an idempotent ES sink, KB-first passage retrieval
and a bounded worker entry point. Synthetic tests cover disabled rights,
idempotence, changed versions, sink recovery and overlapping claims. Six
StartupDB detail API sources are enabled in the ignored local registry. Eleven
fact-only source versions have been retained and replayed through the local
Elasticsearch 9.5.4 sink; six current records are searchable with source
version and credit. A launchd timer is not installed: macOS denied execution of the
Elasticsearch binary from this Desktop workspace. Company-wide collection,
cross-source claim reconciliation and eligibility updates remain open.
The attached source list was treated as research input, not operational instructions.

2 October operation check: an hourly launchd plist is prepared in
`deployment/com.ainvestify.public-kb.plist`, but a forced tick failed before
Python startup because macOS denied launchd access to this Desktop workspace's
`.venv/pyvenv.cfg`. The installed job was unloaded and removed; no unattended
timer is active. The bounded worker completed a manual zero-due pass, and the
existing loopback ES process was left running at that checkpoint. On 2 October,
the node was restarted manually and all 11 retained versions replayed after
adding source-native funding date/status/amount/currency to extraction. Both KB
indices were green and a public `seed` query returned five attributed records.
This does not qualify scheduled collection or unattended ES availability.

**Current execution priority P1:** make this KB a durable local source of public
evidence for both discovery and rooms. P2 removes hosted LLM response paths:
structured parsing stays deterministic, and any extraction, synthesis or answer
generation uses installed local models only. Public HTTP collection may contact
approved source sites; it must not send evidence to Claude, DeepSeek, Anthropic
API or another hosted inference service. No local model download or inference
spend is authorized by this priority change.

See the [delivery roadmap](../LOCAL_TO_CLOUD_RELEASE_PLAN.md) for the integrated
implementation sequence and acceptance gates; KB and scheduling support local L5.

## Two first-class consumers: discovery and deal rooms

Use one canonical public evidence corpus and one source-policy/identity layer,
with two retrieval contracts:

| Consumer | Purpose | Required behavior |
| --- | --- | --- |
| Discovery | Find companies matching the user's investment brief worldwide or in a specified market | Apply only requested stage/geography/status constraints; show supporting evidence, exclusions and unknowns. Discovery alone does not authorize an investment suggestion. |
| Deal room | Prepare an active company's materials and financial context | Retrieve company facts, funding/investors, competitor/market evidence and relevant public benchmarks; join privately with room uploads |

Stage filtering applies to prospect eligibility, not all contextual evidence.
A mature competitor can support a room's market analysis without becoming an
eligible lead. A direct company entry can activate a room without having passed
through discovery; resolve identity and show scope/eligibility transparently.

DealRoom is the application view of the existing OperatingWorkspace, optionally
linked to Deal; it does not introduce another company/evidence silo. The public
KB remains separate from private room state and authoritative engagement records.

Room activation queries fresh KB records before any new public lookup. Return a
versioned bundle with claim/source IDs, evidence status, freshness, permissions
and unresolved conflicts. Missing/stale items schedule bounded targeted research.
Deduplicate collection across consumers by source revision, respecting rights
scope; private instructions, room notes and confidential derived queries never
enter that public request/cache path.

New public-source revisions notify a private dependency registry for affected
rooms. Do not silently rewrite an approved artifact. Room uploads, local analysis,
review decisions and inferred private facts never enrich the shared public corpus
automatically, even if they look publishable or concern an already public company.
Cross-room public reuse is allowed only within source access/reuse entitlements;
private evidence remains tenant/deal isolated.

OAuth/OIDC sign-in provisions private personal sandboxes. The public KB may serve
multiple authenticated users within source entitlements, but search histories,
shortlists, room subscriptions and private enrichment are sandbox-scoped. Shared
KB access is not access to another user's deal room. Check source entitlements
when reusing public cached data; scope private caches to authorized user/sandbox.

Acceptance includes: one public source feeds discovery and two authorized rooms
without duplicate extraction; a later funding event updates eligibility and flags
affected room evidence; private canary facts cannot be retrieved through discovery
or another deal; reopen of an unchanged room causes no new inference.

## Source access decisions

Free viewing is not a free commercial ingestion licence. A source registry must
record automated-access, retention, inference-processing and investor-document
reuse permissions separately, including terms URL, check date and any grant.
An RSS endpoint or permissive robots.txt alone does not grant these rights.

| Source | Initial connector decision | Evidence and relevance |
| --- | --- | --- |
| StartupDB REST API | One detail endpoint enabled locally, with a field allowlist | [API guide](https://startupdb.com/api) documents a public read-only API and rate limit; [data terms](https://startupdb.com/legal) license dataset facts and compilation under CC BY 4.0 with credit. Logos, marks, photos and third-party description text are excluded before retention. Funding events remain publisher-reported evidence, not independently verified facts or current seed eligibility. |
| startups.gallery | Candidate discovery directory; scheduled collection disabled pending source-rights review | Its India page currently offers a narrow lead set and its profiles/news link to announcements. Directory stage, amount and description are secondary observations. Automated access, retention, inference processing and investor-document reuse permissions are not established. See [the controlling end-to-end plan](../LOCAL_TO_CLOUD_RELEASE_PLAN.md#0-fresh-end-to-end-execution-contract--3-october-2026). |
| LinkedIn | No automated scraping without express permission; retain public links as manual or authorized-API leads | The current [User Agreement](https://www.linkedin.com/legal/user-agreement) and [crawling terms](https://www.linkedin.com/legal/crawling-terms) prohibit unapproved automated collection. Company and investor primary announcements at separately reviewed sites are preferred corroboration sources. |
| Company/investor announcements; accelerator and incubator cohorts | Prioritize individual permitted feeds, APIs or pages; review each publisher before enabling | Good primary discovery inputs for seed companies. An investor portfolio entry does not prove current stage, cheque size or ownership. No blanket permission across company sites is assumed. |
| Entrackr / Fintrackr | Disabled pending express permission or licensed feed | [Terms](https://entrackr.com/page/terms-of-use) restrict commercial reuse, systematic databases and automated collection without consent. Public readability is insufficient for this scheduled KB. |
| YourStory | Disabled pending permission or authorized integration | [Terms §§2.5, 2.6.17](https://yourstory.com/terms-and-conditions) restrict robots and automated downloading/copying. |
| Tracxn Lite | Disabled for scheduled scraping; only use a separately authorized API/export | [Terms](https://tracxn.com/termsofuse) prohibit automated extraction except expressly permitted APIs and limit onward use. [Lite pricing](https://tracxn.com/pricing) describes personal use. Do not base a commercial free KB on it. |
| Startup India Showcase | Candidate; automated ingestion/reuse entitlement not established | [Terms](https://www.startupindia.gov.in/content/sih/en/terms-of-use.html) do not establish a bulk API grant. [Showcase](https://www.startupindia.gov.in/content/sih/en/startup_india_showcase.html) describes startup self-declarations, not verified stage/financials. |
| ICRA / CARE rating reports | Targeted connector or authorized document imports after report/site rights review | Useful where the exact legal entity is rated. Automated commercial reuse was not verified in this check; not an enabled source. Low priority for a seed-only lead census. |
| SEBI issue filings | Targeted reference connector after access/reuse review | Market/comparable evidence rather than seed lead discovery. Automated entitlement not established here. Regulatory requirements need their own official-source register and effective dates. |
| NSE filings | Disabled for automated collection unless separately authorized | [Terms §9](https://www.nseindia.com/static/nse-terms-of-use) prohibit systematic/automated collection. Do not infer permission from downloadable PDFs. Listed companies are comparables, not eligible seed leads. |
| MCA | Identity verification / authorized imports; not a free bulk financial feed | The supplied source list distinguishes free identity information from fee-based documents. Current bulk entitlement and fees were not independently verified here; do not automate portal logins/CAPTCHAs or assume an API. |

The earlier review did not request publisher permission. No separate permission
has been obtained.
Use genuinely open/licensed exports and rights-cleared primary announcements for
the initial corpus. Keep publisher restrictions attached to evidence through
retrieval and export; attribution alone does not replace reuse permission.

1 October follow-up: [data.gov.in's Government Open Data License](https://ap.data.gov.in/godl)
allows commercial reuse and derivative works with attribution, while its
[portal terms](https://www.data.gov.in/terms-of-use) defer to each dataset's
license metadata and exclude third-party material. The
[Company Master Data catalog](https://www.data.gov.in/catalog/company-master-data)
is a useful identity-data candidate with a Catalog API link, but the exact
resource/API access, individual license metadata and live content have not been
qualified. Keep it disabled. The linked DPIIT recognition catalog is aggregate
counts by year, sector and state, not company-level seed-stage evidence.

4 October official portal check: the [Company Master Data catalog](https://data.gov.in/catalog/company-master-data)
lists one open, monthly RoC-wise resource updated 22 July 2026, while its
resource note says the underlying data reaches only 3 November 2023. A portal
update date therefore cannot be used as the company-status as-of date. The
specific resource/API export, its dataset-level reuse metadata and a content
hash still require review before activation; the local adapter remains disabled.

3 October code checkpoint: `public_kb/ogd_identity.py` now accepts an
operator-supplied, rights-reviewed Company Master Data CSV only when its exact
resource/version, dataset license, official URL, attribution, review date and
SHA-256 are recorded. It retains CIN-level, dated, source-reported identity and
status observations, including conflicts. Synthetic tests pass. This adapter
does not download the dataset, enable scheduled ingestion, infer funding or
qualify the actual resource/license. StartupDB funding projection now keeps
the source event status and does not treat open, unspecified or future-dated
events as current completed-stage evidence; older event observations remain
append-only. Neither change turns directory records into diligence-complete
investment recommendations.

3 October local backfill: an explicit leased, bounded, idempotent offline command
processed all 11 retained StartupDB source versions without fetching or changing
archive bytes. A read-only check then found 23 dated funding-event observations
(21 month precision, two year precision) across six company projections. Every
recorded event status is unknown, so all six projections remain
`unknown_completion` with no current stage. The first backfill revealed that the
source uses partial dates; the importer now preserves year/month precision and
the exact same 11 versions were replayed. This is a local pilot corpus, not a
worldwide company inventory or evidence that any round closed.

## Pipeline and persistence

```text
Approved source registry
  -> scheduler -> durable fetch queue -> bounded HTTP/feed/API collectors
  -> content hashes + permitted source versions
  -> deterministic parsing -> local extraction for new/changed evidence
  -> entity resolution + claim validation + stage eligibility
  -> Elasticsearch companies / claims / events / source metadata
  -> evidence bundle pinned to source versions
  -> local private-aware drafting -> local PPTX/PDF/memo rendering
```

Keep three layers distinct:

1. **Evidence archive:** immutable versions of permitted source content in local
   storage, with URL, publisher, publication/fetch dates, hash, attribution and
   retention policy. An HTTP check time is not the fact's effective date.
2. **Durable knowledge base:** structured company identities, claim history,
   funding events and source references in ES. Proposed versioned indices:
   `ainvestify-kb-companies-v1`, `ainvestify-kb-claims-v1`,
   `ainvestify-kb-events-v1`, `ainvestify-kb-sources-v1`. Add explicit mappings and
   least-privilege credentials. Store job state separately in local SQLite for
   the single-machine pilot; use a transactional job store if deployed wider.
3. **Existing disposable caches:** public search, page and inference caches.
   Their 6/24-hour expiry must not erase the durable evidence used in a document.
   Never mark an old claim current merely by fetching its page again.

Start retrieval with ES keyword search and structured filters. No hosted
embeddings or vector subscription is necessary. Add local embeddings only if
measured retrieval failures justify them. Persist extraction by content hash,
extractor/schema/model version and source scope, independently of daily fetches.

## Scheduling and token use

For the pilot, use one external timer invoking a bounded worker. Use launchd on
the current Mac or cron/systemd on an always-on Linux host; do not put an interval
timer inside every FastAPI worker. An offline/asleep laptop cannot provide a
continuous refresh service. An hourly timer merely checks which sources are due;
it does not fetch every source hourly.

Proposed source cadences, only after source permission and rate-limit checks:

| Work | Cadence |
| --- | --- |
| Approved funding/news feeds and investor announcement feeds | Every 6 hours |
| Approved directory/company-profile/official-status pages | Every 12 hours |
| Active shortlisted company/team/product pages | Every 12 hours unless a separately approved faster source policy applies |
| Seed investor portfolios and incubator cohorts | Every 12 hours when used for current eligibility; slower only for clearly historical context |
| Permitted rating/financial-report sources | Weekly and before document preparation |
| MCA identity checks / transaction records | On demand or authorized import |
| Source failures, retention, permission-review expiry | Daily |

Use conditional GETs (ETag/Last-Modified), normalized meaningful-content hashes,
and RSS/API cursors. Ignore navigation/ad-only changes. HTTP 304 or unchanged
content skips extraction and inference entirely. Parse structured formats without
an LLM. For changed unstructured content, run bounded local extraction once;
defer expensive enrichment until a company is shortlisted. The scheduler has
**no hosted model key and no paid inference path by default**. A future public-only
enrichment queue may use the existing adapter and shared spending limits.

Pilot bounds: 100 documents per tick, 10 minutes maximum, one request at a time
per domain and at least 5 seconds between requests unless the publisher requires
slower access. Honor Retry-After; use backoff, attempt limits and a failed-job
queue. Enforce a process/job lease, URL-level idempotency and resumable cursors.
Record fetch/extraction/error counts and oldest unchecked source. Do not let an
ES outage advance the successful-ingestion cursor and lose fetched work.

Validate domains, public IPs, redirects, MIME types and size limits. No local
files, private networks, login bypass or arbitrary execution from source text.
Content is untrusted evidence; it cannot change model instructions or tool policy.

## Quality and connection to document preparation

Each material claim needs company/legal-entity ID, field/value/unit/currency,
period/as-of date, standalone/consolidated scope, audit/reporting status, source
version, exact supporting span/page and evidence status. Preserve conflicts.
Never infer a cap table from an investor list or a full P&L from revenue/loss.
Deduplicate syndicated announcements into one underlying event. Entity aliases
need evidence; ambiguous identities stay unresolved, without company-name code.

Maintain separate uses: **eligible seed leads**, **comparables/market context**,
and **unresolved candidates**. Mature firms may support a market slide but must
not enter `/leads` as seed prospects. A seed announcement from years ago is not
current eligibility. Later funding/acquisition evidence must supersede earlier
stage evidence and trigger an eligibility recheck. Missing funding news does not
prove a company is pre-seed.

Document preparation should first query local ES, resolve field-level freshness
and conflicts, then request only missing permitted public evidence. Build a
versioned evidence bundle with citations; fetch changes invalidate only dependent
claims/sections. Preserve the reviewed document revision and flag changes for
review rather than silently rewriting an approved deck. Layout-only changes use
the existing content and local renderer without inference.

Keep private uploads, financials, notes and derived drafts outside public indices
and outside the web-fetch worker's filesystem/credentials. Private joins and
final documents run locally. A private deal question is not automatically safe
to put in a public search query. Public-only enrichment receives an explicitly
allowed evidence bundle, never whole workspaces.

This can supply cited company/founder/funding facts and market context for all
three document types. Audited financials, current cap tables, transaction terms
and transaction-specific compliance conclusions still require appropriate deal
evidence and review. Collection alone does not establish SEBI compliance.

## Delivery sequence and acceptance

1. Source registry and rights-cleared initial seed/accelerator/investor sources.
2. Single-run fetch worker with durable cursors, change detection and timer files.
3. Local extraction, source-version archive, ES mappings and entity/claim history.
4. KB-first evidence retrieval for discovery and preparation; existing eligibility
   and source review remain mandatory.
5. Timer deployment after local ES setup; operational and document-quality pilot.

Required verification: two identical runs make no second extraction/model call;
changed content updates only affected facts; overlapping workers do not duplicate
jobs; failed writes resume without losing records; disabled publishers are never
fetched; later-stage news removes seed eligibility; every generated material
claim resolves to a retained permitted source version; private synthetic markers
never enter public storage or outgoing requests. Track coverage and unresolved
claims, not just number of scraped pages.

"Free tier" here means aiming for no data subscription and no paid background
inference. Storage, electricity, maintenance, optional hosting, paid filings and
any separately authorized API still have costs. Current code has exact caches
and a tested offline registry, collector, passage sink, retrieval path and bounded
worker. It does not have qualified live ES, structured company/event claims or an
installed scheduler. Neither a cron job nor an ingestion service was installed.

Next agent: first identify a source whose collection, retention, extraction and
investor-material reuse rights are recorded and current; keep all others disabled.
Build a bounded collector with public-IP/redirect, MIME, size and rate controls,
conditional requests and durable cursors. Archive permitted source versions, add
deterministic extraction and an idempotent ES sink/mappings, then make discovery
and room research query the same KB by source revision. Prove disabled-source
non-fetch, restart/sink-failure recovery, unchanged-content no-op, later-stage
eligibility updates and private-data non-leakage before installing an external
timer. No private room content belongs in public ES or outbound fetch requests.
