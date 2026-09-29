# Discovery breadth and duplicate identity repair — 26 September 2026

The user requested immediate removal of discovery limits/duplicate results and
confirmation that company information was not hardcoded.

## Changes

- Removed the hidden five-company clamp. The search form has a 1–50 company target
  (default 20); the API records the requested count. This is a bounded target, not
  an invented quota of successful results.
- Model-driven navigation may select twelve observed search URLs for discovery;
  named-company research retains its six-link schema. Fetching honors the explicit
  discovery page limit instead of silently reading only six.
- Extraction works in compact groups of at most three pages / eight companies.
  Each accepted company is source-bound and saved immediately. Full groups can be
  revisited after other sources while excluding all already selected names. Empty
  or wholly duplicate batches are not retried indefinitely. Eight task calls,
  ten provider requests and 120 seconds bound the complete discovery run.
- Source corrections remain model-authored, with original raw responses retained.
  Unsupported company facts/names/websites are never filled by a code fallback.
- Shared identity matching recognizes legal suffix variants and www/http/path
  variants of official hosts, but requires the same normalized company name plus
  compatible official hosts, or a shared exact identity-evidence page when a site
  is unresolved. Different official hosts, different names or tenants do not merge.
  An unresolved entry cannot bridge two conflicting namesakes.
- New discovery reuses existing company/lead IDs on confirmed identity matches.
  Historical result lists, continuation chains and the company list return one
  card per confirmed identity. Original database profiles, source-run snapshots,
  workspaces, notes and drafts remain accessible via related record links.
- The existing AGCO / AGCO Corporation pair was grouped by these generic rules:
  a legal-name variant on the same source page, with one unresolved website. There
  is no AGCO-specific branch or alias table.

## Hardcoding audit

No company names, company-specific answer templates or result catalogue were found
in the active discovery/preparation modules checked. Saved company discoveries have
recorded extraction/assessment response references. Code handles validation,
source binding, identity comparison, budgets and display labels. Names, facts,
selection and substantive assessments continue to come from model responses and
retrieved source passages. This does not certify the factual quality of all model
answers; the analysis limitations in the preceding checkpoint remain.

## Verification and limits

136 related backend tests passed before an additional API duplicate-view regression.
The twelve-company fixture demonstrates that the first eight are persisted before
the next extraction and that repeating a search reuses company/lead IDs. Identity
regressions cover legal variants, conflicting websites, different tenants, unknown
identity bridges and preservation of historical records. Frontend build/lint pass.
Live-run details are appended below after the bounded Sonnet 5 search completes.

Known limits: source access and model latency can prevent reaching the requested
count in one run; Find more extends the search. Two WebSearch calls do not establish
exhaustive global coverage. Ambiguous aliases without shared identity evidence are
kept separate; the app does not guess mergers from similar names alone. Private
records remain local and no automatic company-preparation run is part of this
live discovery verification.

## Final live outcome

- Initial agrotech run `source_run_e37be4a4a80d`: 12 model-selected source URLs;
  eight distinct, source-bound companies saved. Four task calls / six requests,
  120.578 seconds. It reached the deadline during the next extraction; the first
  eight remained available. See `agrotech-initial.json`.
- Continuation `source_run_043e78b1ab2f`: reused the prior failed batch's recorded
  public page payload, with zero new search or fetch calls. Ten additional distinct
  companies saved in four calls / four requests, 120.640 seconds. The combined
  result list contains **18 distinct companies**. It too is partial at the deadline;
  18 is not a single-pass or exhaustive-worldwide claim. See `agrotech-continuation.json`.
- The new checkpoint stores retained public page blocks and pending page groups;
  Find more resumes fresh checkpoints before repeating retrieval. A compatibility
  path replays a failed extraction's original page payload from older runs.
- Both old and newly exposed duplicates were addressed: the original legal-name
  variant via shared identity evidence, and a same-name entry on separate source
  pages via a recorded Sonnet 5 identity decision citing non-name evidence on both
  sides. The latter took one call / 3.638 seconds. No company-specific alias was
  authored in code. `identity-reconciliation.json` preserves the exact response.
- `scripts/reconcile_company_identities.py` provides generic read-only detection
  and an explicit `--apply` bounded public-evidence reconciliation. New discovery
  invokes the same model comparison before creating ambiguous same-name records.
  A null/unsupported decision does not merge entities. Private-origin evidence is
  excluded and tampered raw responses invalidate model-supported grouping.
- Before the continuation, the provenance audit found original recorded extraction
  responses and valid raw hashes for all 19 stored company profiles at that time.
  It includes the older v1 response-id naming convention. See `provenance-audit.json`.
- Final catalogue: 29 stored lead records, 27 distinct displayed company identities;
  no repeated normalized names in that checked catalogue. Both linked records and
  their workspaces are retained. Read-only API verification is in `verification.json`.

Verification: 136 related backend tests passed before the final continuation and
model-identity additions, followed by 58 affected tests. Frontend build/lint passed.
Those tests include public-only identity evidence, exact model response provenance,
no repeated search/fetch on continuation, cross-run ID reuse, incremental saves,
tenant isolation, legal suffixes, and keeping namesakes separate. No active job
remained before loading the final backend. No investment execution or outreach.
