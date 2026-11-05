# Local multi-agent execution log

15 October 2026. User explicitly requested multiple agents and local VS Code /
Claude Code work. Coordinator read the external plan and current repository
handoffs. Baseline branch `codex/frontend-release-readiness-2026-10-04`, commit
`c469ff3`; the initial checkout was clean.

| Agent | Isolated worktree / branch | Owned scope |
| --- | --- | --- |
| WS-A | `.worktrees/ws-a`, `ws-a/analyst-workbook` | Workbook/document tools, `tools/v1` envelope, synthetic tests |
| WS-B | `.worktrees/ws-b`, `ws-b/agent-runtime` | Runtime, concrete local HTTP transport, role prompts, task ledger and tests |
| WS-C | `.worktrees/ws-c`, `ws-c/training-environments` | Offline reward/split contracts, scorer, mock expert iteration and tests |
| Coordinator | Original checkout | Endpoint policy, draft pack tools, VS Code and local Claude launcher, integration and documentation |

Tool observations are frozen as `{version:'tools/v1', ok:bool, tool:str,
result:object, errors:list}`. Errors report unsupported/unrun features rather
than replacing agent content. Coordinator integrated owned source files by
copy; no workstream commits or branch merges were performed.

Initial integration exposed missing document-tool copy and a nonfinite-input
log error; both were fixed. Independent WS-B review found redirect handling,
mutable bindings and duplicate tool-call risks. Redirects are rejected, pack
bindings copied, and runtime duplicate IDs reserved before effects. Partial
multi-file export recovery and hard subprocess cancellation remain open.

Live SQLite was queried read-only: 22 awaiting-input, three blocked, four
cancelled and two queued jobs; zero active leases. No service restart, worker,
model download, real training, cloud action, commit or push was performed.
Ollama preflight observed installed models and zero loaded models. VS Code was
opened with the multi-worktree workspace; the Claude extension was already
installed. An explicit inference question was sent because the supplied plan
requires asking before starting Mac inference. No answer is inferred from time.

Focused evidence is under `evals/agentic_banker/ws-{a,b,c}/`; these contain
synthetic software checks only. Private gold, references, trajectories and
adapters remain outside Git. Read the execution document for open gates.

Final focused checks passed 86 tests. Wider regression: 3,450 passed, 27 failed,
seven skipped; the green-suite gate remains open. Four selected failures were
reproduced on unchanged baseline; an additional failure passed in isolated
baseline and integrated reruns. Remaining failures are not all baseline-classified.
See `evals/agentic_banker/LOCAL_CHECKPOINT.md` for exact scope and caveats.

## 16 October — checkpoint 2

User requested the next checkpoint. Existing WS-A/B/C worktrees were reused.
WS-A supplied 21 explicit schema registrations; WS-B added raw HTTP body
receipts, terminal/model/content validation and pre-effect schema checks;
WS-C repaired stale/authenticated test fixtures, isolated audited live tests,
and reproduced the source-byte timestamp regression deterministically.
Coordinator added atomic draft-pack export, source-identity checks, immutable
manifest replay and the scripted role session. Independent review identified
unbounded verification reads and missing root trajectory bindings; both were
corrected before the final session-003 exercise.

The synthetic session uses six scripted responses and zero real model calls.
Its workbook, two-slide deck, embedded chart and memo are diagnostic artifacts
only. Exact byte replay succeeds without rerendering or new tool effects.
All earlier evidence is preserved. Qualified Office recalculation, visual parity,
private native isolation, real-model team behavior and training remain open.
See `evals/agentic_banker/CHECKPOINT_2.md` for artifact hashes and validation.

Final offline suite after all code/test fixes: 3,513 passed, 20 skipped, zero
failures (167.23 seconds). The 20 unrun live/native/Office checks still block
their release gates. Focused checks: 127 passed. No actual model invocation,
training, download, private-reference processing, cloud spend, restart, commit
or push occurred. Final room counts and queued jobs matched baseline.

## 20 October — Phase A completion round

User authorized local Mac inference and asked to complete Phase A. Seven agents ran
in the main checkout with disjoint file ownership (worktrees lack the uncommitted
work): D1 baseline inference, F1/F2 gold sets, D3 training pipeline, C1 public-data
factory, G1 GPU controls, A2 tool-layer gaps, then B2 harness repair. Gold sets
(Toffee, GSI, BlueStone) are git-ignored and unadjudicated. First real inference:
qwen3.5:9b, qwen3:14b, qwen3.5:4b on the fictional North Quay case scored 0/310;
after B2's repair protocol and block ledger, 35–44/310, one of seven blocks done.
One free tiny-model download (Qwen2.5-0.5B-4bit, 290 MB, hash recorded) was used
for the MLX LoRA dry run. No cloud action, spend, commit or push. Coordinator fixed
the workbook rollback defect (deepcopy → serialised snapshot) with a regression test.
Full suite: 3,734 passed, 19 skipped, 0 failed. See `G_READY.md`: gate NOT MET.

## 26 October — Windows self-hosting continuation

The user explicitly requested multiple agents and Claude Code. Work ran in this
shared checkout with coordinated file ownership: `gpu_inference` measured and
activated an opt-in RTX 2060 placement profile; `pdf_export` fixed LibreOffice's
static PDF export, verified native files and reviewed the outbound proxy;
`training_intake` audited the imported private archives and repaired external
private storage support. The coordinator configured the named outbound tunnel,
DNS and public sign-in acceptance host. Source staging checked previous hashes,
archived prior files/manifests and coordinated restarts with zero active jobs.

Native Claude Code 2.1.310 completed two generic architecture reviews using the
existing authenticated subscription, with tools, MCP, skills and project context
disabled. Only sanitized deployment/parser designs were supplied; no private
company inputs or runtime outputs went to Claude. Review requests and responses
remain outside Git under the private hosting directory.

`https://investify.fyi` now serves the frontend and Google sign-in through a named
Cloudflare Tunnel without router access. Public smoke checks passed; two real
Google callbacks provisioned distinct sandboxes and both sessions were revoked
after testing. Private workflow APIs remain closed and the room worker disabled.
Cloudflare terminates public TLS; no private company uploads were exposed.

The 9B real isolated adapter canary completed in 16.88 seconds with 5,786 input
tokens. A larger stress run still failed arithmetic/prose quality. Static Office
exports pass unchanged PDF checks. All 1,552 imported rows are classified, with
zero eligible for weight updates; test-only targets remain held out. No training,
model download, paid compute, data reset, commit or push occurred. See handoff
section 82 and `deployment/LOCAL_MACHINE_HOSTING.md` for exact evidence and
remaining gates. The subsequent upload parser isolation audit is still ongoing.

## 27 October — authenticated public private-workflow hosting

This checkpoint supersedes the 26 October sign-in-only public proxy, disabled
room worker and ongoing-parser-audit statements above. `https://investify.fyi`
now exposes authenticated private workflow APIs through the named Cloudflare
outbound tunnel and `Caddyfile.tunnel`. The active outbound supervisor uses
`-Mode private-workflows`; invocation without `-Mode` still defaults to
`sign-in-acceptance`. Cloudflare terminates public TLS, while the backend,
database, uploaded files, artifact processing and model inference remain local.
Router forwarding was not needed. A cached old ISP delegation was bridged with
the former Porkbun zone's apex A records `104.21.31.42` and `172.67.174.243`,
TTL 600; all mail records were preserved.

Coordinated workstreams completed upload/legacy extraction and review isolation,
bounded API text classification, exact-byte artifact registration/validation
inspection, and confined public PDF parsing. The coordinator preserved identity
for discovery's automatic durable preparation and retired the unsafe standalone
legacy chart-generation HTTP route. Parsers receive fresh scoped jobs, with no
database/session credentials or network/model capability. Inference workers use
the existing bounded model socket. Exact-file mandatory investor release checks
remain unchanged. Source staging compared previous manifest/file hashes and
retained backups; existing users/sessions and labelled synthetic fixtures remain.

Measured acceptance: **513 integrated backend tests**, **47 loopback HTTP
checks**, **35 authenticated public HTTP checks**, **10 anonymous public routing
checks**, and **15 frontend tests plus build/lint** passed. The authenticated
public checks used factory sessions for the existing Google-verified identities,
not new OAuth callbacks. Their receipt is
`/home/investify/runtime/public-http-isolation-20261026T192851Z-67184ee2dc/report.json`.
A separate fresh real Chrome Google callback on the final bundle opened My
companies and completed logout; private receipt
`hosting/network/final-browser-auth-smoke.json`. Backend integration evidence is
`/home/investify/runtime/backend-integration-ce408f1ebdad/report.json`.

The real isolated 9B extraction completed in **20.111 seconds**. A bounded durable
worker pass completed in **2.181 seconds**, reaching `source_selection` with zero
model calls and zero network bytes observed through IP accounting. Financial
processing correctly blocks missing cached workbook results. Both
`investify-api.service` and `investify-room-worker.service` are enabled and active;
the durable worker retains the full API service restrictions. The outbound Startup
shortcut was backed up and verified in explicit private-workflows mode. Next-login
execution and reboot recovery remain untested.

Training intake remains **1,552 rows, zero eligible weight-update rows**. No
training, financial diligence, complete investor materials, semantic model-quality
acceptance or final investor release is claimed. Private references, test-only
gold, scorer keys and unqualified adapters remain outside Git and unpromoted.

## 27 October — private reference and local quality repair checkpoint

The user supplied seven financial/reference files and renewed authorization to use
them as local quality/training sources. The `pdf_export` workstream imported and
inspected byte-exact private copies without changing originals; private data and
model responses were excluded from Claude/hosted processing. The coordinator uses
Claude Code only for sanitized generic code/task review. Material and discovery
changes remain separate from the accepted hosting/isolation slice above.

`training_intake` audited exact archived hashes and historical source declarations
instead of declaring the entire new bundle held out by default. Five originals
are byte-identical to archived sources; all seven belong to three previously
reserved acceptance families, with two declaration-only source versions unresolved.
Current source-use authorization is recorded independently. The immutable private
family ledger and seven pending source/version review requests are under
`/home/investify/private/training_preparation/2026-10-27-seven-v1/`.
They contain no approved targets or weight updates. New unmatched sources remain
unassigned/unadjudicated; existing scorer/evaluation families and their derivatives
stay excluded from training. Training/storage/runtime checks passed 62 tests.

Measured capacity remains 6 GiB RTX 2060 VRAM, approximately 24 GiB Windows RAM and
7.76 GiB visible to WSL training. No 32B model is installed. A coordinated synthetic
two-call pass spent 113.2 seconds; installed 14B and 27.3B thinking diagnostics
timed out at their 40.028/73.005-second allocations without accepted answers.
Raw failures remain at `/home/investify/private/model_capacity/20261026T200106Z/`.
Header-only MLX inspection estimated 0.988/18.819 GB expanded BF16 weights before
training overhead. No blind dequantization, package installation, model download,
weight update or production-route promotion was performed by this workstream.
The prepared CUDA trainer now handles unsupported BF16, requires local files and
rejects unconverted packed MLX bases. Compatible runtime/base and independently
reviewed non-held-out training targets remain necessary.

The coordinator implemented confined Linux OCR and corrected six independent
review findings: projection/native runtime pins, PNG geometry/CRC/aspect binding,
32 MiB source limits, strict TSV page/hierarchy replay, streamed bounded engine
outputs and shared parent timing. The authoritative corrected-profile 37-page
reference transcription completed in 22.686 seconds at
`/home/investify/private/ocr_qualification/2026-10-27-b5d4d05441`;
21 native OCR/manifest checks passed. Earlier 19.443-second raw output remains
historical and is not adopted under the new pins. Literal OCR stays unreviewed,
with financial validation not established. No final materials/financial/model
quality or successful public discovery repair is claimed at this checkpoint;
final runtime adoption and positive public evidence remain to be recorded.

Actual supplied-workbook evidence was subsequently checked before Office under
the unchanged converter gate. The isolated audit took 0.378 seconds: 14 sheets,
five hidden, 3,008 formula cells; 104 stored errors, one missing cache, 22 broken
formula references, two broken defined names and 23 unsupported/unknown references.
It returned `blocked_before_office` for unknown references. No actual
recalculation, model call or live database write occurred; the original source
hash remains unchanged. Metadata is retained at
`/home/investify/private/workbook_qualification/2026-10-27-7db511acce/report.json`;
raw formula reports stay private and are not committed. No forecast validity or
invented explanation of lost formulas is asserted.

One IM section completed the local author step, but same-model non-independent
review returned `REVISE` for entity/metric distinctions and insufficient depth.
Patch decoding remains in repair; no complete or accepted investor-material
package exists. Discovery's focused software selection passed 144 tests, while
positive public product acceptance remains outstanding.

## 27 October — V3 public preliminary discovery and material limits

This supersedes the pending public-discovery observations in the preceding
checkpoint. Actual Chrome owner Google sign-in and Retry search on the original
unmodified brief produced new run `source_run_ead46f340149` from
`source_run_d148153f58fe`. The public UI displayed CRED, Lentra and Paytm as three
preliminary source matches. The request for 20 was not met: the run is explicitly
partial at 120.033 seconds/six calls, with its sixth additional-page call cancelled
at the remaining 20.987-second allocation. The original raw database row hash is
unchanged; no failed financial-assessment response was rescued or relabelled.

The live audit checked exact literal spans and parent hashes, each company's own
evidence, company-bound title/country support, evidence roles and publication
dates. Historical 2023/2022/2021 vintages remain visible. Financial assessment is
absent/not performed and current operation is not verified. Evidence is
`/home/investify/runtime/public-discovery-evidence-audit-20261026T224357Z-9b03d28e/report.json`.
V3 `OWN_GEOGRAPHY` passed 164 native tests; the final V3 integration passed 361
tests with one explicit Office skip in 40.803 seconds. Earlier V2's 359 passes/
one skip remain historical and do not substitute for this V3 result.

The coordinator staged 31 repair files with checked prior hashes/backups into a
1,183-file snapshot. Before final documentation staging, the manifest was
`469468772c64ec5c468883799d495bf2622a384df2649ee3704f9d191610b28b`;
receipt `/home/investify/runtime/repair-code-stage-20261026T223911Z-6cfd4797/receipt.json`.
The later documentation stage must supply its own receipt/hash. Frontend
build/lint passed and live asset `index-CkV2puP3.js` was observed. Both services
are active; the coordinated restart followed a checked 24-table online backup,
successful SQLite quick-check and zero active jobs. Eight anonymous public
routing checks passed. The separate three-file 8B branch
(`agents/research/document_generation.py`, new
`agents/research/bounded_material_review.py` and
`tests/research/test_bounded_material_review.py`) remains outside the deployed
31-file snapshot. It passed 140 native regressions with zero skips, including 16
new tests. Its only authorized actual probe failed at the shared 105.01-second
budget, 107.115 seconds total, with one logical call/two requests. The first
reasoning phase retained all 6,628 prompt tokens and generated its bounded 256
tokens; a length stop was permitted for this phase. The second phase's 900-token
allocation produced no terminal/count/body before the deadline. No valid review,
`REVISE` or patch was adopted. The full 78 units/four pages and exact
1,185-character draft remain unchanged, as do 27 API security properties and 11
live file hashes. Observed VRAM was 4,746,641,407 bytes with context 8,192,
28 GPU layers/batch 128. The model was unloaded. Private evidence remains in
`review8b-thinking-b195bdaa3e`; there are no further probes or expert/financial/
full-package acceptance claims from this branch.

Final material hardening passed 111 tests with one skip. One 1,185-character IM
section completed its author step, but non-independent same-model review returned
`REVISE`, and a contradicted-support check failed. No full investor-material
package or exact-file release was accepted. An actual full-context 14B review
produced no response in 105.113 seconds, with measured GPU utilization of 96% and
5.274 GB in use; this supplies capacity evidence, not a semantic verdict.

The corrected 37-page OCR diagnostic remains 22.686 seconds with 21 native
OCR/manifest passes and unreviewed transcription status. The actual workbook
remains blocked before Office with 104 stored errors, 22 broken formula references
and two broken defined names, among the retained findings. There is no actual
recalculation or validated forecast. Training remains zero eligible rows/no weight
updates; current source-use permission does not erase the three existing reserved
families. Two completed Claude Code reviews used only sanitized code/task designs.
The public finder evidence qualifies this bounded preliminary matching slice;
it does not complete the 20-company request, current-status verification,
financial diligence, investor materials, training or exact-file release gates.
