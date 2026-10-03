# Local implementation, production artifact validation, then private cloud

3 October 2026. Current execution plan following the user's request to build
locally first, migrate later, and validate every deck, memorandum and spreadsheet
before delivery. Section 0 is the fresh controlling end-to-end sequence; older
milestone text below supplies technical detail only where it agrees with Section 0.
No timelines: milestones end when their acceptance gates pass.

This is the single controlling product, architecture and release plan. Focused
specifications: [financial projections](FINANCIAL_PROJECTIONS_PLAN.md),
[public knowledge base](deployment/PUBLIC_KNOWLEDGE_BASE_PLAN.md), and
[local model quality](deployment/LOCAL_MODEL_QUALITY_EXECUTION.md). Start with
[AGENTS.md](AGENTS.md); use [SESSION_HANDOFF.md](SESSION_HANDOFF.md) for historical
implementation evidence. Earlier overlapping roadmaps have been consolidated here.

Scope: worldwide startup research and due diligence before evidence-backed
investment suggestions, plus preparation of investor materials for company
fundraising. The user's brief controls geography, sector and stage. India
pre-seed/seed is a bounded pilot/regression case, not a product restriction.
Historical runs keep their original policy. The memorandum is for startup
transaction review, not an AIF fundraising PPM.

**Core workflow:** activating a deal room starts its evidence, financial-model,
document and validation workflow automatically. The public knowledge base serves
both lead discovery and deal-room research; it is not a discovery-only feature.

## 0. Fresh end-to-end execution contract — 3 October 2026

**Scope correction:** Sections below mentioning India or seed describe the
observed pilot source/fixture, an India-specific compliance branch, or a pilot
acceptance case. They do not restrict the product. Before any investment
suggestion, require a diligence dossier with resolved company identity; dated
funding, ownership and operating history; product and customer evidence;
market/competition; team and governance; financial evidence and assumptions;
legal/compliance and material risks; source conflicts; unknowns; and an
investment thesis with falsifiable counterarguments. Bind the local model's
conclusion to that dossier and its exact source versions. Missing critical
evidence or unresolved material conflict blocks a positive suggestion while
remaining visible as a research question. A shortlist is only a lead queue.

### A. What has actually failed

The source collector fetches one registered URL per source. It does not yet
traverse a directory company entry through the company profile, official site,
investor and company announcements. The indexed public KB contains searchable
source observations, not a reconciled, dated company/claim/event history.
Product discovery can assess a candidate using a small selected-page batch,
so a later announcement outside that batch may not affect eligibility.
The worker has one six-hour `last_checked` threshold for every source; no
per-source 12-hour cadence, durable due-item queue, failed-job backoff or
stale-current reconciliation exists. Its prepared hourly launchd timer is
not active after a macOS execution denial. These are code/runtime gaps,
not missing instructions to the previous agent.

The current India category on
[startups.gallery](https://startups.gallery/categories/locations/countries/india)
illustrates the failure. It displays Airbound as Seed, while an
[Airbound-issued 25 August 2026 announcement](https://rss.globenewswire.com/news-release/2026/08/25/3350182/0/en/airbound-scales-new-class-of-aircraft-to-change-the-economics-of-flight.html)
reports a $37 million Series A. A source-specific freshness clock must not
turn the old Seed label into current eligibility. The directory also shows
Ultrahuman as Series B; neither displayed entry passes the current seed
stage gate. This is a two-entry observed page, not a census of Indian startups.
Another directory profile describes a $20 million Series A for Default,
while its linked founder announcement describes $20 million raised in total;
round proceeds and cumulative funding must be separate claim types.

Saved complete public-only memo trials still failed before independent review
under the bounded local-model budget, and the room worker has no distinct pitch
content/renderer, complete IM contract, matching six-file export or qualified
exact-file release. Code tests and an isolated repair probe do not count as
accepted live discovery, memo or investor materials.

### B. Non-negotiable phase-by-phase source journey

Each phase writes a durable event before the next phase can start. Every URL
is a lead until that publisher's automated access, retention, local inference
processing and investor-document reuse rights are recorded. The collector
never receives private room text, uploads, notes or derived private queries.

| Phase | Work | Durable output and stop condition |
| --- | --- | --- |
| S0 source admission | Review publisher terms, robots/access mechanics, path scope, rate limit and four separate rights. Register permitted seed pages, APIs and feeds with cadence. | Rights decision, reviewer, effective date and URL pattern. Denied/unknown rights block automated fetch and remain visible. |
| S1 directory page | On its due tick fetch a permitted directory/category page within page, byte, time and rate limits; retain original response/hash and navigation links. | Immutable source version, fetch/status event, observed listing IDs and pagination cursor. Failure does not advance cursor. |
| S2 company entry | Follow each observed company link through an approved profile path; bind the listing entry to the profile by source/version and identity evidence. | Profile snapshot and link-edge event. Ambiguous/cross-company entries stop for resolution. |
| S3 official identity | Resolve observed official domain and legal/operating entity, with aliases supported by evidence. Fetch only separately rights-approved official pages. | Identity candidate, confidence basis, website/source versions, unmatched links and explicit unknowns. No name-only merge. |
| S4 announcement expansion | Stage company, investor, accelerator and permitted press/board links from the profile and official site. Review each publisher/path before fetch; then collect bounded targeted announcements. LinkedIn links are manual or authorized-API leads because its current crawling terms prohibit unapproved automated scraping. | Every discovered URL records parent URL/version, link text/context, decision, queued/fetched/blocked outcome, HTTP status, response hash and any failure/retry. No silent skipped link. |
| S5 source extraction | Extract identity, offering, dated funding/status/operating statements from each retained version with exact text span, event/publication/observation dates, amount semantics, currency and publisher class. | Source-reported claim/event proposals. A directory claim cannot become verified by being indexed. |
| S6 reconciliation | Group by evidenced entity; compare all current and historical event proposals, not just selected pages. Preserve contrary evidence, corrections and retractions. Derive one time-qualified current projection with unknown/conflicted status when needed. | Append-only claim/event history plus versioned eligibility decision and all supporting/opposing source IDs. A later Series A demotes an old Seed lead. |
| S7 retrieval and discovery | Search a company/claim bundle first, apply the user's explicit geography/stage mandate and operating-status checks, then have the installed local model author a cited candidate shortlist and gaps. Review exclusions and exact response. | Candidates are preliminary leads only; unresolved identity, status or source coverage stays visible with a specific reason. |
| S7a investment diligence | Build the versioned dossier described above from reconciled permitted public claims and tenant-private material, with conflict/unknown registers and independent review. Have the installed local model author a thesis, alternatives and risks against the exact bundle. | An investment suggestion is eligible for review only when mandatory diligence fields, source coverage, contradiction handling and exact-version validation pass. Otherwise return a research plan, not a positive investment suggestion. |
| S8 room and materials | Activation joins permitted public bundle privately with room evidence; local model authors distinct intro, pitch and IM specifications. Projection XLSX is conditional on supplied or explicitly requested/reviewed data. | Frozen material revision and raw model responses; three editable core artifacts and matching PDFs as reviewable drafts. No fabricated finance. |
| S9 validation and release | Inspect exact exported bytes, citations, figures, charts, layout, file pair consistency, source rights, financial status and reviewer decisions. | All six core files pass every applicable mandatory check against the same manifest hash. Failed/unrun checks block investor release. |

The startups.gallery directory is currently **not enabled for scheduled
collection**: its automated and reuse rights could not be verified using
available research tools. Its company listings can guide a public read-only
source assessment. Site admission S0 must be completed before S1-S4 run in
the product. Free viewing, a robots allowance or an outbound link is not a
commercial reuse licence. Its small India listing is supplemental; add other
rights-cleared Indian company, investor and accelerator publishers for breadth.

### C. Scheduler, stale pruning and reconciliation contract

An external durable timer checks due jobs hourly; it does not perform all
fetches at once. A class-specific policy schedules permitted funding/news and
investor announcement feeds every **6 hours**, and permitted directory,
company-profile and official-status pages every **12 hours**. Source-specific
terms may require slower intervals. Active shortlisted companies may receive
an explicitly recorded narrower permitted cadence. A sleeping laptop cannot
meet these service levels; local qualification must demonstrate an always-on
runner or show `overdue`, and private cloud is considered only after measured
local limits and a user-approved spend decision.

Due items are durable leased jobs keyed by source ID, URL, requested window and
content revision. Record enqueue/start/fetch/parse/reconcile/index/notify/end
events, worker ID, attempts, deadline, bytes, HTTP status, ETag/Last-Modified,
content hash, source rights revision, error and next retry. Respect
Retry-After, per-domain pacing and bounded backoff. A failed fetch, bad
archive, extractor failure or ES outage cannot advance a successful cursor.
HTTP 304 is accepted only when the referenced archived bytes still exist and
match their hash; otherwise refetch or report a blocked integrity failure.
Two workers must not duplicate work, and a restart must resume leased jobs
without repeating unchanged extraction or model calls.

"Prune stale data" means **remove stale facts from the current searchable
eligibility projection**, not erase historical source versions, old claims,
raw responses or failed reports. Keep `observed_at`, `published_at`,
`effective_at`, `superseded_at`, `last_checked_at` and source validity separate.
When a later round/acquisition/closure is found, append an event, recompute
the current decision, demote an ineligible lead, and invalidate dependent
room bundles/material revisions. A missing update, 304 or recently refetched
old page cannot prove that an old stage remains current. A source correction
or retraction is recorded as a new version; its old claim remains inspectable.
Overdue/failed sources mark current eligibility `unknown` when the freshness
policy requires new evidence. No silent promotion or deletion.

### D. Minimal data and log contracts

Store `SourcePolicy`, `SourceVersion`, `ObservedLink`, `FetchJob`,
`CollectionEvent`, `EntityIdentity`, `Claim`, `FundingEvent`, `Conflict`,
`EligibilityDecision`, `EvidenceBundle`, `MaterialRevision` and
`ReleaseManifest` with stable IDs. A collection event includes timestamp,
source/parent URL and version, phase, actor/worker, rights decision, input
revision, outcome/reason, next state, attempt and trace ID. Public links are
untrusted text; normalize/validate host, redirects, MIME, size and public IP
at every approved fetch. Do not log credentials or private payloads. Private
room logs remain tenant/deal scoped. Every generated figure and substantive
sentence binds to source version + span or reviewed calculation lineage.

### E. Dependency-ordered implementation and acceptance

1. **Freeze baseline.** Inspect uncommitted work, service/job leases and saved
   failures. Preserve originals, SQLite, archives, raw model attempts and
   rejected reports. Measure the current six-hour worker and last live result.
2. **S0-S4 intake.** Add rights policy and 6/12-hour due queue, bounded
   listing→profile→official→announcement traversal and complete event logging.
   The existing `public_kb/source_candidates.py` is an unwired, tested
   pending-review link queue from indexed StartupDB records; extend its
   provenance and worker integration without treating its targets as approved.
3. **S5-S6 history.** Add entity/claim/event persistence and an idempotent
   reconciler. Seed-before-Series-A, amount-type, same-name/different-entity,
   retraction and source-outage fixtures must keep history and derive correct
   current status. The Airbound example is a mandatory independent live
   inspection case after relevant publishers pass rights review.
4. **S7 discovery.** Replace page-only eligibility with complete company
   bundle eligibility before model assessment. Run live multi-market searches,
   including Indian seed as one regression case;
   audit all accepted and excluded candidates, exact citations and status.
   Coverage and quality, not a target count, determine acceptance.
4a. **S7a due diligence and suggestions.** Define a versioned dossier schema
   and coverage policy per user mandate. Reconcile source-reported timelines
   before local-model thesis generation; independently check supporting and
   opposing evidence, unresolved conflicts, missing financials and exact
   citations. Persist draft, reviewer decision and input digest. Test a
   materially contradicted company, an evidence-thin company and a supported
   company across multiple markets. Only the last may receive a positive
   investment suggestion after review; the other two yield explicit research
   questions and no positive recommendation. A discovery shortlist never
   passes this gate by itself.
5. **S8 materials.** Add room-scoped requested-material state and conditional
   projection branch. Freeze one claim ledger/revision; record separate local
   model specs for intro, pitch and full IM. Render editable PPTX/PPTX/DOCX
   and matching PDFs. Missing financials are explicitly disclosed; a broken
   source workbook is never presented as a validated forecast.
6. **S9 release.** Validate every exported file and pair, hidden spreadsheet
   formulas when applicable, citations, amounts/dates/units, charts, layout,
   rights and cross-file parity. Capture independent source-exclusion,
   financial and compliance review on the exact manifest digest. OIDC and
   verified legacy ownership remain gates before multi-user release.
7. **Live integrated acceptance.** Two identical ticks produce no duplicate
   extraction; a newer stage updates lead status and flags two subscribed
   rooms; one source outage leaves history intact and status visible; private
   canary data never enters public KB; room reopen makes zero unchanged model
   calls; an accepted evidence bundle yields six distinct exact files and
   complete review. Failed/unrun/unsupported gates stay blocked.

The next agent should implement **steps 2 and 3 as one vertical slice** before
another complete memo trial. Use synthetic rights-approved directory/profile,
official-site and announcement fixtures first, then one rights-approved live
publisher. Codex and Claude Code CLI may collaborate on sanitized generic
code/tests; installed local models alone author company conclusions. Do not
send private company inputs or runtime outputs to Claude, download models,
use hosted product inference, reset data, commit, or incur cloud spend without
the separate authorization required by `AGENTS.md`.

### F. Current status and proof labels

| Area | Status at this checkpoint |
| --- | --- |
| Source rights | StartupDB limited fact-only projection approved locally; startups.gallery and LinkedIn automated collection are not approved. |
| Collection | One-URL collector and manually enabled StartupDB records exist; 6/12-hour linked traversal and active unattended timer do not. |
| History | Retained source versions/passages exist; reconciled cross-publisher company/funding/status history does not. |
| Discovery | KB-first local-model route exists; complete-bundle current-stage acceptance is not established. |
| Memo/models | Narrow correction and tests passed; complete public-only local memo trials remain unaccepted before review. |
| Materials | Intro/memo/research previews exist; distinct pitch/full IM/six-file validation and approval do not. |

Software tests prove code behavior on fixtures. A live collected source, a
reconciled current decision, an independently reviewed local-model result and
exact exported-file inspection are separate acceptance results. Do not merge
them into one `passed` label.

### G. Copy-ready next-agent instruction

> Read `AGENTS.md` and Section 0 of `LOCAL_TO_CLOUD_RELEASE_PLAN.md`, then the
> focused public KB, local model and financial specifications and latest
> `SESSION_HANDOFF.md`. Inventory uncommitted changes, active services/jobs and
> retained failed reports before editing. Preserve SQLite, archives, originals,
> raw responses and failed artifacts. Implement S0-S6 as a vertical slice:
> rights-reviewed per-publisher source policies; durable hourly due queue with
> 6-hour announcement and 12-hour directory/profile/official-status cadence;
> directory entry → profile → official identity → separately approved company,
> investor and announcement links, with every transition logged; immutable
> source versions and dated claim/event reconciliation. Do not scrape LinkedIn
> without express permission or enable startups.gallery until automated access
> and reuse rights are documented. Make an old Seed label lose current
> eligibility after a later company-issued Series A. Preserve both records and
> expose the decision's supporting/opposing source IDs. Use synthetic fixtures
> first, then one rights-approved live source. Prove idempotence, restart,
> 6/12-hour due timing, source failure, ES outage, private/public isolation and
> exact Airbound-style stale-stage behavior. Continue to S7-S9 only when this
> evidence bundle is complete; local models alone author company conclusions.
> Keep the intro, pitch and IM plus matching PDFs mandatory; projections are
> conditional. Report code tests, live collection, accepted model output and
> exact-file validation separately. Do not commit, reset, download a model,
> use hosted product inference or incur cloud spend.

### Execution snapshot — 1 October 2026

This snapshot updates implementation status; the milestones and release gates below
still control acceptance. Google OIDC, private sandboxes, durable room jobs, draft
PPTX/DOCX rendering and exact-file download gating exist in code. A loopback-only
temporary ID/password account permits local UI work while the Google OAuth Web
client is uncreated; it is **not OIDC acceptance**. The current UI shows the signed-in
account in the header and keeps sign-out there. At this checkpoint the API and Vite
are serving locally without a room worker; verify live processes and job leases
before any restart rather than relying on this transient status.

The user's revised **execution priorities** are: **P1** build the durable public
KB for discovery and deal-room research; **P2** remove Claude and other hosted LLM
dependencies from product response paths so all model-generated answers use
installed local models, with no hosted fallback; **P3** finish private
LibreOffice/UNO and financial/artifact validation; **P4** qualify the integrated
local workflow; **P5** complete live Google OIDC and legacy ownership acceptance.
P5 is an execution priority, not permission to release a multi-user service
without verified identity and isolation. The existing OIDC code and local login
may remain available for development. No milestone is accepted from offline tests
or draft renderers. See handoff §56 for the superseding next-agent order.
The company-agnostic path from local model drafts to an evaluated investment
package is sequenced in [the local model quality execution plan](deployment/LOCAL_MODEL_QUALITY_EXECUTION.md).

### Toffee sample and model-confidence direction — 1 October 2026

The user supplied a historical company workbook and two PDF decks as private
reference and acceptance inputs, not a product template. Do not hardcode that
company's figures, formulas, names or assumptions into runtime behavior. Treat
their content as evidence, not instructions. On room
activation, preserve the originals, inventory all sheets/pages, extract with
cell/page lineage, and run independent formula, financial and cross-artifact
checks before any model-authored conclusion. Company-supplied projections are
inputs, not automatically validated forecasts or actuals. A model may explain,
challenge and draft from recorded evidence; it must abstain or flag missing
inputs when reconciliation fails. Require exact exported XLSX/PPTX/DOCX/PDF
validation before release, including hidden cells and consistent figures.

The requested “1000% confidence” is an assurance goal, not a measurable model
probability or a guarantee of zero errors. Acceptance means zero unresolved
mandatory validation errors in the specific released artifact versions,
documented coverage and limitations, and reviewer approval. Model agreement
alone cannot establish arithmetic correctness. Prefer rights-cleared free
public data in the shared ES KB, with source versions and attribution; keep
private uploads, extracted figures and derived room data in private storage.
Use installed local inference first and avoid hosted consumer-model calls for
company material. Private self-hosted cloud compute is a capacity option only
after local bottlenecks are measured and a concrete budget, region, isolation
design and cost are reviewed. On 2 October the user supplied a ₹15,000/month
ceiling and Mumbai/Hyderabad preference. A bounded public-only GPU evaluation
is costed in [the private GPU evaluation plan](deployment/PRIVATE_GPU_EVALUATION_PLAN.md);
no cloud resource has been created or qualified.

## 1. Deliverables and the production contract

One approved evidence/model revision produces the requested material set:

**3 October scope correction:** intro deck, pitch deck, and investment
memorandum are the required investor materials. A projection workbook is
conditional: analyze a company-supplied model when present, or generate a new
forecast only after an explicit user request and enough reviewed current inputs.
An absent or defective projection does not by itself prevent drafting supported
nonfinancial material. Financial claims, charts and exhibits still require
their own evidence and calculation gates; missing finance stays visibly
missing. The production worker and validators have not yet implemented this
complete conditional flow.

| Artifact | Editable deliverable | Matching distribution version |
| --- | --- | --- |
| Intro deck | PPTX with editable text, tables and supported native charts | PDF from that deck revision |
| Pitch deck | PPTX with editable text, tables and supported native charts | PDF from that deck revision |
| Investment memorandum | DOCX with cited narrative, tables, assumptions and review appendix | PDF from that memo revision |
| Financial projection, when requested and supported | XLSX with real formulas, editable assumptions, case selection and charts | Selected validated financial exhibits in the other documents; PDF summary when requested |

An attractive file is not sufficient. Production readiness requires supported
calculations, source accuracy, readable layout, coherent charts, file compatibility,
privacy controls and an auditable release decision. The user receives a package
only after mandatory validation of the actual exported files.

“Zero formula errors” is a **release rule**: no unresolved spreadsheet errors,
unsupported/unexecuted calculations or failed financial reconciliations in the
delivered workbook. It is not a mathematical guarantee against every undiscovered
business mistake. Known failures block submission; missing test coverage cannot
be represented as a pass. Forecast correctness and forecast realism remain
separate questions.

Keep broken source workbooks intact as evidence. A corrected/rebuilt deliverable
is a separate version with explicit changes; do not silently rewrite the original
or conceal errors by replacing formulas with cached numbers or zero defaults.

### Deal room as the product entry point

Creating/activating a deal room for a selected or directly entered company queues
one durable `DealRoomActivated` workflow, subject to existing access/engagement
requirements. Resolving the company's identity comes first; uncertain matches do
not inherit another company's facts. Reopening the page displays saved work and
resumes eligible unfinished tasks, not a new full model run on every page visit.

The room orchestrates:

1. Retrieve relevant permitted public KB evidence: company/founder identity,
   funding, investors, market context, competitors and applicable reference sources.
2. Reuse fresh evidence; request targeted refreshes only for missing/stale public
   facts, without transmitting private notes or inferred confidential questions.
3. Inventory authorized room uploads and extract private facts/formula dependencies.
   Reconcile them against public claims without assuming either source is always true.
4. Build an evidence coverage map, identify material contradictions and collect
   missing inputs into one prioritized, actionable request.
5. Interpret supplied projections or propose evidence-based estimated drivers;
   calculate supported scenarios with explicit assumptions and provenance.
6. Generate the common material revision, intro/pitch decks, IM and supporting
   workbook. Prepare independent supported sections while other inputs are pending.
7. Run the full pre-delivery suite and required reviews; expose final downloads
   only for the validated approved package.

The user sees one room with Evidence, Financial model, Materials and Validation
views and a clear next action. Do not require separate prompts to initiate each
agent. Automate eligible work within recorded budgets and cancellation controls;
room activation is not permission for unlimited crawling, paid inference or outreach.
Missing data changes the relevant task to `awaiting_input`, never fabricated success.

Uploads, approved assumptions and new source revisions emit durable change events.
Track which room claims, calculations, sections and artifacts depend on them;
recompute only affected work and invalidate corresponding reviews. Keep prior
versions inspectable. Store room subscriptions, user activity and private evidence
in tenant/deal-scoped transactional storage, not the shared public KB.

### Reconcile the existing entities: no third silo

**Decision:** DealRoom is the product/API facade over an evolved
`OperatingWorkspace`, with an explicit optional association to `Deal`. It is not
a third independent store of company facts, approvals or document copies.
Preserve workspace IDs, revisions and histories.

| Existing record | Responsibility |
| --- | --- |
| Company profile / sourced lead | Identity, discovery evidence, eligibility and promotion link |
| OperatingWorkspace | Stable room ID, research/analysis, material references, jobs and events |
| Deal | Engagement/mandate lifecycle, deal-owned documents, extraction/review records and legacy artifacts |

Add a tenant-checked workspace `deal_id` association. Backfill only from an
unambiguous `SourcedLead.promoted_deal_id`; `workspace_basis` already consults this
relation. Flag conflicts and retain unlinked records instead of merging histories
or guessing. Do not duplicate the Deal's authoritative mandate state in the room.
Prospect rooms may research public facts without a mandate; existing deal-document
ingestion still honors its mandate/access gates. Opening a room never signs a
mandate or clears an approval.

For direct entry, establish a profile and explicitly manual-origin lead, then
reuse workspace creation. Do not forge AI discovery provenance. For a legacy Deal
without a lead/workspace, provide an explicit linking migration preserving its
records. MVP cardinality is one active workspace per tenant/lead and at most one
linked Deal per workspace; reconcile any conflicting existing relationships in L0.
Multiple future engagements require a deliberate cardinality change.

L0 mapping tests cover unpromoted lead, promoted lead with workspace, legacy Deal
only, direct entry, ambiguous duplicates and cross-tenant rejection. L1 adds the
association and facade through additive migrations. Keep legacy routes as adapters
until migration is verified, rather than maintaining another source of truth.

### Everything substantive has a data basis

Every factual statement, number, financial assumption, chart series and material
analytical conclusion must map to its supporting evidence or calculation record.
Headings and layout labels need no artificial citations. Evidence must support the
actual claim, entity, scope and period; attaching an unrelated URL is insufficient.

| Content class | Required basis and presentation |
| --- | --- |
| Reported fact | Exact public passage or authorized document/cell; source, date, entity and reported/audited status |
| Calculated result | Reviewed inputs, formula/calculation version, units/period and successful execution |
| Forecast or estimate | Named drivers, source/calibration/rationale, uncertainty, scenario and assumption approval; explicitly estimated |
| Analytical conclusion | Supporting facts/calculations, stated reasoning basis and qualifications; distinguished from an observed fact |
| Missing or contradicted item | Specific missing evidence or competing source claims; no confident replacement from model memory |

Company-supplied and media-reported are provenance categories, not independent
verification. A benchmark must have a relevant source and comparable definition.
Unsupported hypothetical drivers may be explored in an explicitly illustrative
internal draft; they cannot be presented as data-backed assumptions in the released
investor package. Human approval does not convert an unsupported claim into evidence.

Add a coverage gate before final delivery: every material claim has a resolvable,
permitted source or calculation lineage, and every material contradiction is
resolved or explicitly disclosed under the artifact's review policy. Required
unresolved evidence blocks finalization. Never use fluent prose or a self-reported
confidence percentage as a substitute for evidence.

## 2. Build the same application locally and in AWS

### User sandbox and OAuth registration

**Required before multi-user/team release (execution priority P5):** users register/sign in through an approved OAuth 2.0
provider using **OpenID Connect (OIDC)** for verified identity. Create a private
personal sandbox on first successful sign-in. “Sandbox” means enforced user/data
authorization plus isolated job resources, not merely separate UI views or folders.
No user sees another user's rooms, uploads, prompts, findings, jobs, review history
or artifacts by default. The shared public KB is the explicit, rights-controlled
exception; private user activity and room evidence are never shared through it.

Use a configurable standard OIDC adapter rather than tying business logic to an
AWS-specific login SDK. Google/Microsoft or an organization-approved issuer can
be configured; actual provider/client registration is an implementation dependency,
not completed by this plan. Use Authorization Code with PKCE, state and nonce;
allowlist issuer/redirect URIs; validate signature, issuer, audience, expiry and
nonce using a maintained library. Reject replay and untrusted dynamic issuers.
[OIDC defines identity over OAuth](https://openid.net/developers/how-connect-works/);
follow [OAuth security BCP](https://www.rfc-editor.org/rfc/rfc9700.html).

Keep token exchange server-side. Browser sessions use opaque revocable server
session IDs in HttpOnly, Secure, appropriately SameSite cookies, with CSRF/origin
checks for state-changing requests. Rotate the session on login/privilege changes,
enforce idle/absolute expiry and revoke on logout/account suspension. Do not store
provider tokens in browser localStorage, URLs or application logs. Request only
identity scopes needed (`openid`, minimal profile/email); no Drive, mailbox or
contact access is implied by sign-in. Do not send deal information to the IdP.
Use locally trusted HTTPS or an explicitly isolated development-only callback
configuration; never carry relaxed development settings into deployment.

Identify accounts by stable `(issuer, subject)` mapped to internal user IDs,
not email addresses. Verified email is a contact attribute; it does not grant
organization access or automatically link accounts from different issuers. Any
future account linking requires authenticated proof. Create user, external identity,
personal sandbox and owner membership transactionally, with uniqueness constraints
to prevent duplicate signup callbacks from provisioning multiple sandboxes.

**Authorization and ownership:** represent the personal sandbox as a tenant with
an authenticated owner membership. Derive active tenant/user/reviewer server-side
from the session and checked membership; remove caller-controlled `X-Tenant-ID`
and `X-Reviewer` as authority. Check membership plus resource ownership/permission
on every list/read/write/upload/job/stream/export/download operation. Random IDs,
CORS and frontend controls are not authorization. No global `default_tenant` or
anonymous fallback after migration. Signing up grants no compliance-reviewer role.

Default is private single-owner work. If financial/compliance reviewers must access
a room, require an explicit owner grant/invitation with a scoped role and audit
trail; do not enable organization-wide sharing merely because email domains match.
Owner, analyst, reviewer and administrator permissions are distinct. Administrative
metadata access does not automatically permit document-body access; privileged
support access must be explicitly controlled and audited.

**Files and workers:** replace the current unauthenticated `/memo_output`
StaticFiles mount in `api/main.py` with an authorized artifact gateway. Serve only
server-resolved artifact IDs and checked release/draft-preview states, never
client-provided paths. Local directories/object keys include sandbox and deal
scope, with path traversal/symlink checks and no directory listing. Keep private
buckets nonpublic; an authenticated streaming gateway is the default for revocable
access. Any later short-lived signed URLs need a documented expiry/revocation risk.

Jobs carry trusted sandbox, actor and room references from enqueue; workers
recheck current access before reading private data, finalizing or serving outputs.
Revoked users cannot keep accessing a running job or its results. Use job-scoped
temporary mounts/directories and bounded CPU/GPU/storage quotas. Shared GPU weights
are acceptable, but sessions, prompts, conversation memory, embeddings, private
response/prefix caches and logs must not expose one user's data to another. Include
authorization scope in private cache keys; never reuse another user's private
result because its company name or input hash looks similar.

**Existing data migration:** current default-tenant data is not assigned to the
first person who logs in. Back up and explicitly bind it to a verified owner through
a controlled administrator migration, reconciling linked leads, Deal/workspace
records, documents, jobs, approvals and paths. Preserve original approval actors as
historical identities; do not falsely turn them into authenticated new users.
Quarantine unassigned records from new accounts until ownership is established.

**Acceptance:** two real isolated test users cannot access each other's records,
previews, original files, job events, cache outputs or final downloads, even using
guessed IDs, spoofed headers or stale URLs. Test invalid/replayed callbacks,
same-email/different-issuer accounts, concurrent signup, CSRF, logout/revocation,
membership changes mid-job, path traversal, direct static URLs and legacy-record
ownership. Anonymous requests fail closed. A development identity fixture is
isolated from real data and cannot be enabled in production. Repeat the same suite
after cloud migration. OAuth authenticates identity; these sandbox controls enforce
authorization and confidentiality.

Use a portable modular application and isolated workers. The execution logic,
schemas, prompts, templates and validation suite stay the same across environments.
Only infrastructure adapters and configuration change.

| Component | Local implementation | Later private AWS deployment |
| --- | --- | --- |
| App and access | Existing FastAPI/React, authenticated user/deal scope; loopback pilot | Private authenticated ingress; same API and authorization |
| Model inference | Local installed self-hosted model behind a typed adapter | Evaluated self-hosted model on private GPU compute; no consumer/API fallback |
| Calculation | Isolated local spreadsheet engine | Same pinned engine/container on private CPU workers |
| Rendering | Local PPTX/DOCX/XLSX render/export adapters and fonts | Same versions, fonts and templates on CPU workers |
| Public search/KB | Rights-cleared collector and local Elasticsearch | Separate public collector; controlled private Elasticsearch service |
| Private originals and artifacts | Restricted local content-addressed storage | Encrypted private object storage, explicit access policies |
| Job/review authority | SQLite on one host, durable leases/checkpoints | Transactional shared store such as PostgreSQL for multi-host workers |
| Scheduling | External local timer invoking a bounded worker | AWS scheduler/worker adapter, with equivalent idempotency and budgets |
| Validation/release | Local automated suite and immutable artifact manifest | Identical suite plus cloud isolation, restore and concurrency checks |

Define `InferenceProvider`, `ArtifactStore`, `JobStore`, `KnowledgeStore`,
`CalculationEngine`, `Renderer` and `ReleaseValidator` interfaces. They are
specific service boundaries, not a general plugin framework. Do not couple
financial logic to S3 paths, cloud queues or a particular GPU.

Pin engine/model/runtime/template/font versions. Keep a model digest and precision
profile where available. A model change requires model-quality acceptance; a
renderer or calculation-engine change requires compatibility regression tests.
Identical model output across environments is not assumed. Compare evaluated
behavior and normalized financial outputs, not only file bytes.

The current product model selection rejects Claude Pro, Anthropic API and
DeepSeek routes; historical provider modules and raw outputs remain. Complete an
exhaustive route audit across discovery, public KB enrichment, room research and
drafting, then verify installed-model inference fails clearly when unavailable.
Route every model-generated answer through installed local models without hosted
fallback. External LLM credentials are unnecessary. Local inference
does not eliminate external traffic from deliberately public web collection;
keep that worker isolated from private records and queries.

### Selected initial calculation and rendering stack

Evaluate **LibreOffice headless**, controlled through UNO calculation/document
APIs, as the local recalculation and PDF-conversion engine. Use `python-pptx` for
PPTX construction, `python-docx` for DOCX, and `openpyxl` for workbook reading/writing,
formulas and supported native XLSX charts. openpyxl does not execute formulas.
These are concrete initial choices, subject to the L0/L1 compatibility test.

PPTX/XLSX charts should be native editable objects for supported chart types.
DOCX initially contains editable text/tables and data-bound chart images. Do not
claim python-docx offers native Word-chart authoring; its documented
[shape support](https://python-docx.readthedocs.io/en/latest/user/shapes.html)
centers on inline pictures. Native Word charts require a separately qualified
adapter. Images still derive from the common validated ChartSpec.

Run LibreOffice with per-job isolated profiles, blocked egress, disabled macros
and external refresh, timeouts and cleanup. Explicitly recalculate, save, reopen
and inspect results. A successful headless process or conversion alone is not
calculation proof. Preserve required workbook features on a round trip or create
a separately identified reviewed derivative; never silently discard them.

L0 records tested versions, fonts, OS and consumer-application coverage. Add
runtime/dependency manifests after successful qualification. LibreOffice,
python-pptx and python-docx are not in the current declared dependencies and were
not installed by this plan. No licence fee does not mean zero infrastructure cost.
LibreOffice acceptance does not establish Excel/PowerPoint parity; test declared
destination versions and explicitly block unsupported features.

## 3. Milestones, in execution order

### L0 — Freeze contracts and the acceptance corpus

Implementation started 30 September 2026: `delivery/contracts.py` now defines the
four artifact contracts, exact-revision manifests and fail-closed assessment of
trusted validation/review results. `delivery/room_mapping.py` provides a read-only
tenant-scoped mapping planner; `delivery/workflow_contracts.py` defines activation
idempotency/budgets and distinct public KB consumer contracts. Export policy and
JSON schemas with `python3 scripts/export_delivery_contracts.py`. Synthetic
negative tests are in `tests/delivery/`. See handoff §47 for verification.

This is an initial L0 implementation, not L0 acceptance or the L4 release gateway.
Section lists are initial engineering contracts pending acceptance-owner review;
mandatory checks have no N/A exemptions in v1. Real file validators, transactional
release, authorized downloads, migration execution, workbook/model acceptance
fixtures and engine qualification remain outstanding. Existing runtime routes
do not use these contracts yet. A synthetic passing assessment is not a released
artifact and cannot establish financial/compliance approval.

Define the four artifact formats, section requirements, private/public boundaries,
source rights, forecast classifications and supported workbook feature set.
Specify the intended spreadsheet and presentation applications and versions for
compatibility acceptance. Preserve the existing DB, workbooks and failed runs.

Create public/synthetic fixtures covering common company types and malformed
workbooks. Keep the real Toffee workbook as a private compatibility case. Do not
commit it or send its content to hosted inference. Identify independent expected
calculations and material-error labels before tuning prompts.

Exit: machine-readable artifact contracts, validation policy and labeled expected
results. Every proposed pass condition has a test or a named reviewer decision.
Include the deal-room activation/event contract and both KB consumer contracts
(discovery eligibility versus room evidence/context) in these fixtures.

### Early feasibility gate — alongside L0/L1

Do not wait until L5 to discover local-model limitations. Run a small labeled
development check with public/synthetic inputs: approximately ten extraction and
reasoning cases plus two synthetic multi-sheet financial models. Include wrong
entity, unit conversion, subset/whole metrics, missing assumptions, unsupported
claims and cash/profit distinctions. Use the installed profile, deterministic
expected calculations and a fixed total call/time budget, with no unbounded
retries. Private samples wait for verified L1 isolation.

Record raw outputs, task failures, latency/memory and task-level go/no-go. This
screen is not the final held-out qualification. If reasoning fails, continue
local deterministic parsing/rendering/validation with clearly labeled fixtures
and limit model tasks to what passed. Prepare a stronger self-hosted cloud
benchmark specification, but actual cloud evaluation still waits for the cloud
gate and explicit spending authorization. This preserves local-first execution;
L5/C1 remain the broader unseen-case acceptance gates.

Also evaluate the named engine stack during L0/L1: change an input in a synthetic
workbook, recalculate/save/reopen; construct a native-chart PPTX and a table/chart-
image DOCX; convert them to PDF and inspect results. Resolve compatibility failure
before dependent L2/L3 implementation. L0 additionally resolves the entity mapping
above and names financial/compliance acceptance owners.

### L1 — Implement local private execution and resumable jobs

Make self-hosted inference the explicit default, implement restricted worker
resources/egress and durable job/checkpoint state, and add trusted reviewer/deal
authorization before team use. Separate public fetching, private inference,
calculation, rendering and validation. Preserve completed sections on retry.

Exit: private canary values cannot reach outgoing HTTP requests, public indices,
other deals or routine logs; workers cannot read unauthorized files. Restart,
cancel and duplicate-job tests pass. An unavailable model does not invoke a
hosted API. Network isolation is tested, not inferred from prompt text.
Concurrent activation/reopen events for one room must not duplicate jobs, paid
requests or artifacts. Room identity and permissions come from trusted server state.

### L2 — Interpret and validate workbooks locally

Implement formula-plus-cached-value ingestion, hidden-sheet/named-range inventory,
dependency coverage, units/period mapping and isolated recalculation. Add reviewed
assumptions, supported driver schedules and real scenario calculations. Keep
management forecasts, analyst estimates and actuals distinct.

Exit: selected financial outputs trace to inputs, reconcile independently and
respond correctly to representative input changes after export/reopen. Unsupported
features block affected computations. The system can identify the exact missing
input or source range instead of repeatedly regenerating the whole answer.

### L3 — Produce the complete artifact set locally

Use a common `MaterialRevision` and approved `ForecastSnapshot` to populate all
artifacts. Implement editable templates, native charts where supported, local
fonts/assets, citations and explicit actual/forecast/scenario labels. Render
PPTX and DOCX to their distribution PDFs with pinned tools. Add source/assumption
links for financial exhibits. Founder proposals remain optional.

Build an early intro-deck slice, then pitch/memo/XLSX using the same contracts.
Synthetic content proves renderer behavior only; it is not evidence of successful
model-authored company analysis. Runtime drafts must retain recorded model-output
or separately attributed human-edit provenance.

Exit: all requested formats open correctly and remain editable as specified;
every slide/page/used sheet view renders cleanly; all formats agree on material
figures. This is an artifact-generation milestone, not yet a user-release gate.

### L4 — Install the mandatory pre-delivery validation gate

Implement the suite in §4 against final exported files, aggregate every required
check, bind results to file hashes and make the delivery endpoint enforce them.
Add mutation tests that deliberately introduce errors and prove they block release.
No file can be marked production-ready just because generation returned success.

Exit: a healthy fixture releases; each injected formula, chart, citation, layout,
privacy or version error prevents delivery and returns a precise internal finding.
Fixing one failure reruns its dependent checks and package-wide consistency.
No stale validation can authorize changed bytes or a changed evidence revision.

### L5 — Validate local end-to-end quality and scheduled ingestion

Run the existing held-out model/workbook acceptance stages, plus all artifact
release checks. Add permitted incremental collection and KB-first retrieval once
the artifact path works. Exercise unchanged reuse, later-stage exclusions,
changed-source invalidation and recovery from ES/model/engine failures.

Exit: supported cases produce validated packages without developer intervention;
measure draft acceptance, false acceptance, abstention, correction loops and
analyst minutes. Any unresolved model-quality gap is recorded separately from
working software and rendering. The local machine may be too small for the final
reasoning profile; that does not authorize claiming local quality has passed.
Demonstrate activation of a room from a discovered lead and from a directly entered
company, reuse of the same public KB facts, ingestion of new private records,
targeted updates and final validation. Private room facts must never flow back
into shared public discovery results or another room's evidence bundle.

### C0 — Prepare private cloud infrastructure and migrate adapters

After local implementation/validator acceptance, produce reviewed infrastructure
configuration, region/model/GPU choices and a bounded evaluation budget. Deploy
isolated private inference/calculation/rendering and separate public collectors.
Migrate storage/job adapters without rewriting business logic or the validation
suite. Preserve record IDs, original files, audit history and content hashes.

Exit: cloud resources satisfy the same isolation tests; credentials never enter
files/logs; migration reconciles object hashes and record counts; tested backup,
restore and rollback procedures exist. If multiple hosts are used, transactional
coordination and spending limits are shared rather than local SQLite copies.

### C1 — Qualify stronger models and cloud operation

Evaluate stronger self-hosted models on the exact held-out tasks and workbook
cases, with an additional unseen set after tuning. Run exported-file validation
and consumer-application compatibility again in the production environment.
Load-test real concurrency, GPU memory, job leases, queues and cancellation.

Exit: the selected profile passes the model and artifact gates, private egress
checks pass, and supported cases meet measured latency/quality targets. Cloud
compute can close a local capacity gap; it cannot waive a financial-quality gate.

### C2 — Controlled production release

Shadow-run representative jobs before switching the active deployment. Confirm
active jobs are drained/checkpointed, preserve local rollback and point delivery
only at validated cloud manifests. Monitor blocked releases, review exceptions,
source freshness, usage, storage and failures without logging private content.

Exit: the full production package passes the suite and necessary sign-offs;
the user receives only those exact validated files. No external investor delivery
or fundraising action is automatically performed.

## 4. Mandatory pre-delivery validation suite

All mandatory checks have `pass`, `fail`, `not_run` or an explicitly justified
`not_applicable` state. `not_run`, unknown coverage and unapproved exceptions block
release. A not-applicable decision is permitted only by the artifact contract,
not as a way to bypass a failing check. Cosmetic warnings may remain only when
they do not violate acceptance criteria; no formula error is downgraded to one.

| Layer | Required checks | Blocking examples |
| --- | --- | --- |
| Input and provenance | Valid file/schema; exact evidence/cell references; approved material inputs; scope, vintage and actual/forecast labels | Untraceable metric, stale required evidence, wrong company or private data in public context |
| Formula execution | Recalculate in supported engine; inspect every delivered sheet including hidden sheets/names; scan errors and broken references; test unsupported/circular/external dependencies | `#REF!`, unexpected `#DIV/0!`, `#VALUE!`, `#NAME?`, `#NUM!`, `#SPILL!`, `#CALC!`, unresolved `#N/A`, unexecuted output |
| Financial semantics | Independent totals/bridges; proper stocks/flows, periods, currency and scale; no double counting; actual-versus-forecast separation | Premium/GMV misreported as revenue, profit confused with cash, duplicate funding, invented balance-sheet plug |
| Scenarios | One active case; actuals unchanged; each compared case independently calculated; captured comparisons labeled and fresh | All cases point to the same active output; changed assumptions leave stale numbers/charts |
| Cross-artifact facts | Compare normalized metric IDs/entity/period/scenario values across workbook, chart data, decks and memo | Different revenue, raise amount, cash need or cap table for the same context |
| Chart data and presentation | Source binding, complete series, units, period, title, legend, scale and data labels; correct native chart payload | Chart uses old case, wrong denominator, clipped legend, unexplained truncated axis or misleading composition |
| Narrative and compliance | Material factual statements supported; hypotheses/forecasts labeled; applicability and review recorded | Unsupported ownership, fabricated certainty, missing required transaction evidence |
| Visual rendering | Render every page/slide and relevant populated sheet/print region; overflow, clipping, contrast, font, alignment and chart completeness checks | Off-slide content, unreadable labels, `####`, missing fonts, blank chart, cut-off table or citation |
| File compatibility | Open/export/reopen in declared supported engines; formula and native-chart behavior; PDF page count, searchable text where expected, no broken embedded assets | File repairs on open, missing chart cache, PDF differs from approved editable content |
| Confidentiality and release | Audience/deal permissions; document metadata/hidden content/embedded chart workbook inspection; approvals and validation match exact hashes | Private appendix embedded in an unintended audience's deck; changed file served under old approval |

Supplement automated layout heuristics with rendered-image acceptance examples
and targeted visual review while the checker is being qualified. A second LLM's
“looks good” response is not enough to validate typography or financial truth.
Define a supported template set so repeatable automatic layout checks are feasible.
If visual correctness cannot be established for a generated page, do not auto-release
it. Do not silently add an unlimited human slide-by-slide workflow as the product
scales; improve templates/checkers or narrow supported layouts.

Zero-error policy applies to the delivered workbook, including hidden material.
It does not require silently deleting faulty original-source sheets. Keep original
evidence separately and deliver a reconciled reviewed derivative where necessary.
Do not hide errors with `IFERROR(...,0)`, flatten calculations, or treat a blank
cache as zero. An unsupported unrelated source sheet may remain archived, but it
cannot be included as a functioning part of a released model without verification.

Use per-metric absolute/relative tolerances declared by units and precision;
compare identities, dates and exact quantities appropriately. Display rounding
does not authorize inconsistent underlying values. Validate unrounded facts, then
check that rounded displays and chart labels faithfully represent them.

## 5. Charts, including pie charts

Support charts as data-bound objects, not illustrations whose numbers the model
invented. Store a `ChartSpec` with metric IDs, source revision, scenario, periods,
unit/scale, categories, series, chart type and displayed rounding. Native PPTX/XLSX
charts and PDF renderings derive from that same specification. Embedded chart
workbooks must contain only the audience-approved data, not the full private model.

Use pie/donut charts for a valid composition such as a reviewed allocation or
cap table with a defined ownership basis. Require nonnegative parts, a positive
total, mutually exclusive categories and a complete stated denominator. Check
sum-to-total and percentage reconciliation before rounding. Any “Other” category
must be calculated from known source categories; do not invent the missing remainder.
Handle label rounding explicitly rather than silently changing values to make
rounded labels sum to 100. Avoid 3D/exploded distortions and overcrowded slices.

Use line/column charts for growth, grouped bars for comparisons and supported
waterfall charts for reconciled changes. A pie chart is not suitable for negative
cash flows, overlapping categories or a time trend. Each visual must display the
correct period, units and actual/forecast/scenario context. A chart-type decision
must follow the data's meaning, not a requirement to put pies on every page.

## 6. Release states, artifacts and validation report

```text
Evidence approved -> Content drafted -> Calculated -> Rendered
-> Validating -> Ready for required review -> Approved -> Released
                  | failure
                  -> Blocked with specific findings -> Targeted repair -> Revalidate
```

Internal draft previews can be visibly marked and accessible to authorized
reviewers; they are not submitted as production files. The normal final download
action is enabled only for `Released`. Required financial/compliance approvals
are checked in addition to automated validation. Different artifact types may
have different approval requirements. For a requested full package, release is
atomic: do not silently omit a failed member and label the set complete.

Persist an `ArtifactManifest` listing evidence/model/assumption/material revisions,
requested outputs, file hashes, renderer/calculation/model versions, validation
policy/results and reviewer decisions. Publish immutable files only after a
transactional release decision. The download endpoint checks trusted release
state and artifact identity; checking a UI badge is insufficient. Keep temporary
generation files inaccessible through final-download paths.

The validation report records check IDs, coverage, counts, failing locations,
expected/observed results, tolerances and engine versions. The user sees a concise
summary and can open permitted details. Do not publish private source dumps or
chain-of-thought in the report. A content/formula/chart/template change invalidates
affected checks and exact-version approvals; run package-wide consistency again.
Time-sensitive source/rule freshness is checked at the applicable release gate.

## 7. Tests that prove the gate works

Before claiming production readiness, deliberately inject and catch:

- A shifted spreadsheet reference, wrong INR scale and missing formula cache.
- An error on a hidden sheet and an unsupported formula feeding a headline output.
- A cash schedule that does not reconcile and an unjustified funding plug.
- A stale scenario chart and a pie with overlapping/negative categories.
- A deck figure inconsistent with the workbook's approved forecast.
- An unsupported memo statement or out-of-date required compliance rule.
- Clipped slide text, a blank chart and a broken PDF conversion.
- Private data hidden inside chart attachments, notes or document metadata.
- A modified export with an old passing manifest and an unauthorized download.
- Engine/model outage, process interruption and duplicate finalization attempts.

Maintain known-good fixtures and independent arithmetic expectations as well as
negative cases. Measure false passes, false blocks, first-pass completion and
human correction effort on unseen examples. Tests must cover the actual exported
files, not just the in-memory JSON or mocked renderer responses.

## 8. Definition of done

Local implementation is complete when the full workflow and mandatory gate work
locally on the supported corpus and all limitations are explicit. Model capability
may still require cloud GPU qualification, which must be recorded honestly.
Production release is complete only when the deployed model, calculation engine,
artifact formats and privacy boundary all meet their acceptance gates.

This plan defines the acceptance gates; the execution snapshot and table below
record partial code implementation. Mandatory exported-file and reviewer gates
remain open. Updating this document generated no workbook/deck/memo, altered no
original and provisioned no cloud resource.


## 9. Implementation baseline and contracts

| Capability | Evidence today | Remaining work |
| --- | --- | --- |
| India/pre-seed/seed filters | Offline code and tests; dated quote requirements and historical-run separation | Live precision, coverage and later-stage contradiction checks |
| Public generation routing | Product model selection rejects Claude Pro/Anthropic API/DeepSeek; historical modules remain; mocked route tests pass | Exhaustive route audit, live local-model acceptance and fail-closed network verification |
| Durable public KB | Rights-gated registry, bounded collector, passage sink, KB-first retrieval and bounded worker tested with synthetic sources | Qualify a real publisher and ES, structured claims/events, later-stage invalidation and external timer |
| Public caching | Exact ES source/search/result caches, leases, spending reservations; mocked tests | Local ES installation, real integration tests, lifecycle/restore operations |
| Private inference | Local adapter and payload-origin checks | OS/network isolation and end-to-end leakage tests; local quality acceptance |
| PDF/Excel input and calculations | Real-file inventory retains formulas, cached results and hidden sheets; bounded cross-sheet cell/range lineage reports cycles and unknowns | Named/structured/dynamic dependency coverage, financial semantics, isolated recalculation and independent arithmetic |
| UI / jobs | Deal-room view, durable SQLite room leases/checkpoints and scoped worker exist; account UI shows the signed-in user and sign-out | Qualified end-to-end room run, worker recovery and complete materials; legacy discovery BackgroundTasks remain separate |
| Tenant/reviewer identity | Google OIDC and server-side sessions/private sandboxes replace header identity; temporary loopback password login exists for development | Priority P5: create Google Web client and pass live OIDC/scope acceptance before multi-user release; verify legacy ownership, assign reviewers and test role grants |
| Document compilation | Draft PPTX/DOCX renderers and private preview/final-file gateway exist alongside legacy Markdown output | Four complete artifacts, qualified PDF conversion, exported-file layout/chart/evidence validation and exact-version reviews |
| Scheduled KB | Disabled rights-gated source registry, immutable content-hash staging and leased SQLite outbox pass synthetic tests | Approved source, safe HTTP collector, extraction, ES sink/retrieval, durable cursor and external timer |
| Quality | §38 selection passed 213 offline tests; later targeted auth, lineage and KB checks passed; failed private LibreOffice report retained | Complete mandatory suite, live Google acceptance, private renderer/UNO qualification, held-out model and artifact review |

Do not describe the existing generic “preparation complete” state as a completed
investor deck. Preserve the failed Kaleidofin draft and historical failures.

### Shared data contracts

Define these typed records before adding many connectors:

| Record | Required concepts |
| --- | --- |
| SourcePolicy | Publisher/domain, connector, permitted operations, rights evidence, check/expiry dates, cadence, rate limits, retention and export attribution |
| User / ExternalIdentity / Session | Internal user ID, unique issuer/subject, verified identity attributes, revocable server session; no client-selected reviewer identity |
| Sandbox / Membership | Personal tenant, owner and explicit scoped grants; no default cross-user access or first-login claim over legacy data |
| SourceRevision | Canonical URL, publisher, content hash, published/fetched/checked dates, ETag, parser version, permitted original location, page/block spans |
| CompanyIdentity | Stable internal ID, legal names/CIN where supported, domains, alias evidence, resolution state; never merge solely on fuzzy name |
| Claim | Company/entity, metric/value/unit/currency, reporting period/as-of, scope/population, actual/forecast/audit status, exact citation, origin, validation state |
| FundingEvent | Announcement/close dates, round/stage, amount/currency, equity/debt/secondary distinctions, investor claims, duplicate-event links |
| EligibilityDecision | India evidence, latest known stage/status, contradictory evidence, mandate version, eligible/excluded/unresolved with reasons |
| EvidenceBundle | Immutable selected claim/source revision IDs, freshness/conflicts, audience and classification; private bundles never enter public ES |
| DealRoom view | Facade over OperatingWorkspace with a tenant-checked optional Deal link; no third evidence/approval store |
| RoomDependency | Room-private mapping from source/assumption revisions to affected claims, calculations, sections, reviews and artifacts |
| MaterialRevision | Artifact kind, source bundle, model response/patch IDs, numeric calculation IDs, section states, template and provenance |
| ReviewDecision | Authenticated reviewer, role, exact revision hash, findings, decision, timestamp and ruleset version where applicable |
| Job | Task, scope, input/version hash, state, attempt, lease owner/expiry, checkpoints, usage and sanitized error |

Use Decimal-based calculations and explicit Indian lakh/crore/unit conversion.
Distinguish consolidated from standalone, period flows from point-in-time stocks,
and monthly run rates from annual totals. Missing means missing, never zero.
Preserve competing claims until their scope/period differences are resolved.

Use the KB index names in the KB plan (`ainvestify-kb-*-v1`) for durable public
records and the current `ainvestify-public-*-v1` names for disposable caches.
Record durable manifests and job transactions locally; index claims and company
views in ES. Start with exact filters plus keyword retrieval. Vector retrieval
is deferred until a measured benchmark shows a need; any embeddings remain local.

### Concrete implementation boundaries

Reuse FastAPI/React, existing PDF/Excel parsers, inference interfaces, eligibility
checks and financial validators. Add focused knowledge, job, material and compliance
modules rather than replacing the application. Keep original public source manifests
and an indexing outbox transactionally durable; ES indexing failures retry safely.
Use immutable content-addressed original/artifact storage. Private-derived data
stays outside public ES. See the KB supplement for index names and refresh policies.

Migrations must preserve identities, source revisions, raw model responses, saved
company work and historical approvals. Legacy Markdown artifacts remain readable
and explicitly identified as legacy; never relabel them as new deck outputs.

Runtime checkpoint, 1 October (§§48–55): server-side Google OIDC sessions replace
header identity; new users receive empty private sandboxes. Authenticated room
preparation uses durable SQLite leases/checkpoints and scoped private workers.
Excel ingestion retains formula/cache/hidden-sheet inventory and bounded cell
lineage. Private previews and final downloads enforce scope and actual bytes;
the release gateway blocks missing mandatory checks. A temporary local password
account supports loopback development only. None of this establishes full L1
acceptance or Google sign-in without a registered Web client.

Current blockers include live Google client setup, verified legacy ownership
migration, deployed public KB/discovery, private LibreOffice conversion/explicit UNO,
complete financial dependency and semantic analysis, all-artifact renderers and
mandatory validation, and unverified model quality. Offline tests are not proof
of live acceptance. The failed Kaleidofin run and its generic metric-comparability/
missing-input errors remain recorded in handoff §38; never replace its answer by
hand to claim recovery.

## 10. Model, discovery and compliance acceptance

### Model evaluation

The early L0/L1 feasibility screen comes first. The larger corpus below is the
L5/C1 qualification gate, not the first test of the installed model.

Work: establish a development set and untouched acceptance set; compare the
installed local profile, one stronger feasible local candidate, and a stronger self-hosted cloud candidate when the cloud evaluation gate is reached. No downloads/hardware commitment assumed.
Measure extraction, unsupported-claim detection and short narratives separately.
Prepare the harness offline; do not report a mocked comparison as live.

Proposed minimum acceptance set: 50 source documents across at least 20 company
identities and three sectors, including missing fields, Indian units, tables,
duplicate press releases, stale seed announcements and conflicting scopes. Add
synthetic private cases and 10 short investor-narrative tasks. Split by company
and underlying announcement so duplicate news cannot leak into both sets.

Acceptance targets: at least 98% field precision and 90% recall on labeled
extractable fields; at least 95% abstention on labeled unsupported questions;
100% resolvable citations on accepted claims; zero critical errors in accepted
outputs on this set. Critical means wrong entity, materially wrong amount/unit/
period, invented ownership or ungrounded compliance conclusion. Report counts
and uncertainty, failures, raw output and human corrections—not only percentages.
These are proposed pilot gates, not proven model scores or general guarantees.

Decision: choose the cheapest *accepted* route per task. If private narrative
fails, keep assisted drafting/human review and assess stronger local hardware;
do not loosen truthfulness checks or send private data to a hosted API. A second
model's approval alone is not ground truth. Keep a new held-out set after tuning.

Demo: scored examples with elapsed time, memory, retries, provider cost and analyst
editing minutes, plus an explicit go/no-go for each task.

### Discovery quality

Use at least 30 independently labeled mixed candidates. No known later-stage,
listed or acquired company may enter eligible seed leads. Target at least 90%
recall of labeled eligible companies present in the test sources, reporting
unknowns and source coverage separately. This is not market-wide recall. Later
funding/status evidence invalidates earlier eligibility; never infer pre-seed
from absent news or rank incumbents into the list to fill a target count. Keep
ambiguous identities unresolved without company-specific aliases.

### Compliance scope

A qualified Indian reviewer owns the applicability matrix: company/issuance route,
instrument, investor residency, sector and regulated activities. Requirements need
an official source, effective/verification dates, evidence and responsible reviewer.
Assess Companies Act, FEMA/RBI and applicable SEBI requirements for the specific
transaction; do not assume every startup memo is governed by an AIF PPM template.

Primary implementation research sources: [Companies Act](https://www.indiacode.nic.in/indiacode/handle/123456789/2114?view_type=browse),
[private-placement rules](https://e-book.icsi.edu/Actpagedisplay.aspx?PAGENAME=28411),
[RBI foreign-investment direction](https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=11200).
These are research pointers, not a certified current ruleset. Test domestic,
foreign-investor and unsupported transactions against reviewer-labeled requirements.
Missing evidence, changed transaction details or stale rules invalidate the relevant
release approval. The memo does not replace statutory forms or executed documents.

**Staffing dependency: unassigned.** The organization must name a qualified Indian
legal/compliance professional and a financial/investment acceptance owner, recording
authority, supported transaction scope and review responsibilities. Ownership is
an L0 decision; accepting L4 compliance rules requires that reviewer. Engineering
can implement schemas and synthetic checks meanwhile, but neither a developer nor
an LLM can self-appoint as the qualified signatory. Without the reviewer, compliance
materials remain unapproved drafts, not final releases.

## 11. Private AWS migration details

AWS is the later compute environment, not a requirement for local implementation.
Data would leave the laptop for the organization's AWS account; AWS is part of the
infrastructure trust boundary. Confirm region, residency, capacity and spend before
provisioning. No resources or private uploads have been authorized by this plan.

Use self-hosted weights on private GPU EC2 or appropriately network-isolated
SageMaker. Evaluate a pinned efficient model and a stronger model on the same
held-out set. Initial candidates are [Qwen3.5-35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B)
and [Qwen3.5-122B-A10B](https://huggingface.co/Qwen/Qwen3.5-122B-A10B), not accepted
winners. GPU sizing includes full weight storage, precision, runtime overhead,
context and concurrency; sparse active parameters alone are insufficient.
[AWS P5](https://aws.amazon.com/ec2/instance-types/p5/) is a candidate family,
not a regional availability or cost commitment.

Protect ingress with authenticated organization/deal access. Use scoped roles,
KMS-backed encrypted storage, restricted security groups and private service
endpoints. Block internet egress from confidential inference/calculation/rendering;
stage reviewed weights/images before private jobs. Isolate public collection.
Disable content telemetry, diagnostic data capture and prompt/body logging.
[Private SageMaker access](https://docs.aws.amazon.com/sagemaker/latest/dg/interface-vpc-endpoint.html)
and [container network isolation](https://docs.aws.amazon.com/sagemaker/latest/dg/mkt-algo-model-internet-free.html)
are distinct controls that require verification, not consequences of using a VPC.

Current loopback-only model/ES adapters need authenticated, allowlisted private
endpoint adapters for migration, not unrestricted URLs. Keep ES compatibility;
Amazon OpenSearch is not presumed a drop-in replacement. Multi-host workers need
shared transactional coordination and cost controls, not network-mounted SQLite.
Measure cost per accepted package including GPU idle time, repeated calls and
analyst correction. Batch background work, reuse validated results and cap resource
usage. Do not assume a cloud budget or silently escalate models.

Responses contain a direct conclusion, metric/entity/period/scenario, citations,
assumptions, validation status and a specific required action when blocked. Use
supported/calculated/estimated/needs-input states. Self-reported model confidence
is not measured accuracy. Automate routine work; preserve human review for material
assumptions, unresolved exceptions and final transaction/compliance approval.
