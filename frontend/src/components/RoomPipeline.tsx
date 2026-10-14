import {useEffect, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../api/client';
import Materials from './Materials';

type Checkpoint = {
 state?: string; phase?: string; reason?: string; error_count?: number; blockers?: string[];
 recorded_claim_count?: number; identity_state?: string; public_kb?: string; source_rights?: string;
 review?: {findings?: unknown[]};
 batches_recorded?: number; batches_total?: number;
 workbook_count?: number; retained_cell_count?: number; packet_count?: number;
 semantic_coverage?: string; financial_validation?: string;
 attempt_count?: number; memo_revision?: string; content_flow_contract?: string; content_phase?: string;
 content_diligence_coverage?: {
  state?: string; coverage_complete?: boolean; judgments?: Record<string, unknown>;
  unassessed_sources?: string[]; unresolved_sources?: string[]; missing_categories?: string[];
 };
 content_review?: {state?: string; repair_rounds?: number; independent_review?: string};
 causal_review?: {
  state?: string; reason?: string; batches_recorded?: number; batches_total?: number;
  review?: {findings?: {
   field?: string; sentence_id?: string; relation?: string; challenged_clause?: string | null;
   reason?: string; premise_source_ids?: string[];
  }[]};
 };
};
type RoomJob = {
 id: string; state: string; phase?: string; phase_attempt?: number; input_revision?: string;
 checkpoint: Record<string, Checkpoint>; error?: string;
};
type RoomArtifact = {id: string; kind: string; format: string; state: string; input_revision: string};
type RoomState = {id: string; jobs: RoomJob[]; artifacts: RoomArtifact[]};
type PackageAssessment = {package_id: string; eligible_for_release: boolean; manifest_digest: string; blockers: string[]};

const stages: {key: string; title: string}[] = [
 {key: 'evidence', title: 'Evidence collected'},
 {key: 'financial_evidence', title: 'Workbook evidence'},
 {key: 'financial_model', title: 'Financial reconciliation'},
 {key: 'investment_memo', title: 'Investment memo draft'},
 {key: 'materials', title: 'Deck drafts'},
 {key: 'material_preview', title: 'Private draft previews'},
 {key: 'material_review', title: 'Claim review'},
 {key: 'material_repair', title: 'Model correction'},
 {key: 'material_re_review', title: 'Re-review'},
 {key: 'validation', title: 'Release validation'},
];
const readable = (value: string) => value.replaceAll('_', ' ');
const memoMilestones: Record<string, string> = {
 draft_ready: 'Model draft saved · correction next',
 correction_ready: 'Model correction saved · evidence ledger next',
 ledger_ready: 'Evidence ledger bound · local review next',
};
// Durable memo revision markers. Anything else keeps the generic review wording.
const memoRevisions: Record<string, {title: string; active: string}> = {
 field_v1: {title: 'Field rewrite',
  active: 'The local model is rewriting a blocked field from its cited evidence.'},
 field_v2: {title: 'Second field rewrite',
  active: 'The local model is rewriting another field flagged by review.'},
 stable_v1: {title: 'Changed sentence review',
  active: 'Changed sentences are reviewed again. Unchanged checks are replayed.'},
};
const reasonLabels: Record<string, string> = {
 causal_revision_branch_frozen: 'Blocked wording saved; bounded revision queued',
 memo_revision_branch_frozen: 'Blocked wording saved; bounded revision queued',
 bounded_local_memo_attempts_exhausted: 'Pass limit reached; memo not accepted',
 local_memo_review_not_accepted: 'Waiting for the memo to pass its local check',
 local_memo_validation_failed: 'Waiting for the memo to pass its local check',
 source_characterization_complete: 'Source history and forecast scope recorded; generation queued',
 source_unit_author_complete: 'The local model wrote source-bound fields; final review queued',
 source_unit_content_not_supported: 'Draft failed its evidence or field-purpose check; release blocked',
 source_unit_review_inference_failed: 'Local review could not complete; release blocked',
 source_unit_phase_time_limit: 'This bounded model phase reached its time limit; release blocked',
 source_unit_phase_failed: 'Source-bound drafting or review failed; release blocked',
 source_unit_phase_incomplete: 'Drafting did not finish within its bounded pass; release blocked',
 next_isolated_source_unit_author: 'Writing each field against its selected evidence',
 next_grouped_source_unit_review: 'Checking source attribution, financial labels and open questions',
 next_core_section_author: 'Writing the full memo sections from retained source evidence',
 next_core_section_review: 'Reviewing every full memo section against its source evidence',
 source_unit_review_shape_exhausted: 'Local review could not return a complete judgment; release blocked',
 next_bounded_source_characterization: 'Checking source dates, history and forecast scope',
 source_characterization_terminal: 'Source interpretation could not pass its checks; release blocked',
 next_bounded_content_review: 'Reviewing rationale against its evidence',
 next_bounded_content_rereview: 'Checking the model’s revised rationale',
 next_bounded_content_repair: 'The local model is correcting unsupported wording',
 revised_content_not_supported: 'Revised rationale still needs evidence; release blocked',
 bounded_memo_content_passes_exhausted: 'Rationale review reached its pass limit; release blocked',
 material_relation_review_next_batch: 'Reviewing the next saved group of deck statements',
 material_relation_review_no_answer: 'The deck review did not return an answer; release blocked',
 material_relation_review_malformed: 'The deck review could not bind its judgment; release blocked',
 model_relation_review_blocked: 'The local review found a deck statement that needs correction',
 model_narrative_review_blocked: 'A deck statement failed its evidence, scope or slide purpose check',
 narrative_review_no_valid_answer: 'The deck review did not complete; release blocked',
 narrative_review_malformed: 'The deck review could not bind its judgment; release blocked',
 no_distinct_memo_sentences_left: 'The memo has no unused supported content for this slide',
 complete_diligence_inventory_exceeds_local_capacity: 'Complete source inventory exceeds the current local capacity',
 diligence_coverage_binding_failed: 'Source coverage failed its evidence check',
 diligence_coverage_inference_failed: 'Local source assessment could not finish',
 unassessed_retained_sources: 'Assessing retained source text',
 model_field_scope_selection_required: 'Selecting evidence for memo sections',
 next_diligence_coverage_batch: 'Assessing the next source batch',
 next_diligence_source_adjudication: 'Checking source judgments',
 next_diligence_field_selection: 'Selecting evidence for memo sections',
 diligence_coverage_complete: 'Source text assessed; drafting next',
 financial_evidence_index_failed: 'Workbook indexing failed; the original is preserved',
 financial_evidence_index_binding_failed: 'Workbook evidence does not match this room revision',
 financial_evidence_workbook_capacity_exceeded: 'More than three workbooks need a separate bounded pass',
 workbook_outside_room_scope: 'Workbook does not belong to this room',
 financial_index_request_changed: 'Workbook index inputs changed; a new revision is required',
};
const fieldLabels: Record<string, string> = {
 investment_thesis: 'Investment case', business_and_market: 'Business and market',
 differentiation_and_execution: 'Positioning and execution', risks_and_countercase: 'Risks',
 diligence_plan: 'Open diligence',
};
const coverageLabels: Record<string, string> = {
 identity: 'Company identity', funding_and_ownership: 'Funding and ownership',
 product_and_customers: 'Product and customers', market_and_competition: 'Market and competition',
 team_and_governance: 'Team and governance', financial_evidence: 'Financial evidence',
 legal_and_compliance: 'Legal and regulatory evidence', risks: 'Risks',
 opposing_evidence: 'Conflicting evidence', material_unknowns: 'Material unknowns',
};
const memoFieldKeys = Object.keys(fieldLabels);
const flow4Steps = ['source_characterization', 'source_unit_author',
 'source_unit_review_recommendation', 'source_unit_review_u0', 'source_unit_review_u1',
 ...memoFieldKeys.map(field => `memo_section_author_${field}`),
 ...memoFieldKeys.map(field => `memo_section_review_${field}`)];
const flow5Steps = [...Array.from({length: 5}, (_, index) => `diligence_coverage_${index + 1}`),
 'diligence_field_selection', ...flow4Steps];
const flow6Steps = [...flow5Steps.slice(0, 5), 'diligence_source_adjudication',
 'diligence_field_selection', ...flow4Steps];
const flow7Steps = [...flow5Steps.slice(0, 5),
 ...Array.from({length: 5}, (_, index) => `diligence_source_adjudication_${index + 1}`),
 'diligence_field_selection', ...flow4Steps];
const flow10Steps = [
 ...Array.from({ length: 5 }, (_, i) => `diligence_source_adjudication_${i + 1}`),
 'diligence_field_selection', ...flow4Steps];
const flow12Steps = [
 ...Array.from({length: 25}, (_, i) => `diligence_source_pair_${i + 1}`),
 'diligence_field_selection', ...flow4Steps];
function contentPhaseLabel(phase: string) {
 if (phase.startsWith('diligence_source_pair_')) return `Extract evidence and classify source ${phase.split('_').at(-1)}`;
 if (phase.startsWith('diligence_source_adjudication_')) return `Check source group ${phase.split('_').at(-1)}`;
 if (phase.startsWith('diligence_coverage_')) return `Assess source batch ${phase.split('_').at(-1)}`;
 if (phase === 'diligence_source_adjudication') return 'Check source judgments';
 if (phase === 'diligence_field_selection') return 'Select evidence for each section';
 if (phase === 'source_characterization') return 'Check source dates and financial scope';
 if (phase === 'source_unit_author') return 'Write source-bound findings';
 if (phase === 'source_unit_review_recommendation') return 'Review the recommendation';
 if (phase.startsWith('source_unit_review_u')) return 'Review open questions';
 for (const prefix of ['memo_section_author_', 'memo_section_review_']) {
  if (phase.startsWith(prefix)) return `${prefix.includes('author') ? 'Write' : 'Review'}: ${fieldLabels[phase.slice(prefix.length)] || readable(phase.slice(prefix.length))}`;
 }
 return readable(phase);
}
const releaseLabels: Record<string, string> = {
 compliance_scope_missing: 'Regulatory scope is missing',
 compliance_scope_stale: 'Regulatory scope needs an updated review',
 compliance_scope_unresolved: 'Transaction scope has unresolved details',
 compliance_matrix_missing: 'Regulatory applicability matrix is missing',
 compliance_matrix_stale: 'Regulatory applicability needs an updated review',
 compliance_rule_coverage_incomplete: 'Regulatory rule coverage is incomplete',
 compliance_qualified_signoff_missing: 'Qualified compliance signoff is missing',
 compliance_signoff_stale: 'Compliance signoff is for another version',
 compliance_signoff_rejected: 'Compliance review was rejected',
 compliance_signoff_future_dated: 'Compliance review date is invalid',
 compliance_signoff_predates_rule_verification: 'Compliance signoff predates the rule check',
 compliance_owner_unqualified: 'A qualified compliance reviewer is required',
 compliance_owner_scope_or_authority_mismatch: 'Reviewer authority does not cover this scope',
 compliance_content_revision_changed: 'Regulatory scope or rules changed; revalidate',
 compliance_evidence_inventory_unavailable: 'Regulatory evidence has not been verified',
 compliance_scope_evidence_unresolved: 'Transaction details lack verified source evidence',
 financial_owner_unqualified_for_scope: 'A qualified financial reviewer is required for this scope',
 financial_review_date_missing_or_invalid: 'Financial signoff needs a valid recorded review date',
 financial_model_not_validated: 'Financial validation is incomplete',
 complete_formats_calculation_layout_and_exact_version_reviews_required: 'File validation and exact-version reviews are incomplete',
 independent_evidence_required_for_release: 'Independent evidence is required',
 source_coverage_incomplete: 'Source coverage is incomplete',
 independent_diligence_review_required: 'Independent diligence review is required',
 mandatory_diligence_categories_missing: 'Required diligence topics lack evidence',
 unresolved_retained_sources: 'Some source interpretations remain unresolved',
 policy_version_mismatch: 'Validation policy changed; revalidate',
 observed_file_set_mismatch: 'Delivered files differ from the reviewed set',
};
const checkLabels: Record<string, string> = {
 input_provenance: 'Evidence provenance', financial_semantics: 'Financial checks', chart_binding: 'Chart evidence',
 narrative_support: 'Claim evidence', visual_rendering: 'Layout inspection', file_compatibility: 'File compatibility',
 confidentiality: 'Privacy checks', compliance_applicability: 'Regulatory applicability',
 formula_execution_all_sheets: 'Workbook calculation', scenario_execution: 'Scenario checks',
 cross_artifact_consistency: 'Cross-document figures', source_rights_freshness: 'Source rights and freshness',
};
function blockerLabel(blocker: string) {
 const parts = blocker.split(':');
 const code = parts[0];
 if (releaseLabels[code]) return releaseLabels[code];
 if (code === 'missing_file') {
  const kinds: Record<string, string> = {intro_deck: 'Intro deck', pitch_deck: 'Pitch deck',
   investment_memorandum: 'Investment memo', financial_projection: 'Projection workbook'};
  return `${kinds[parts[1]] || readable(parts[1] || 'file')} ${(parts[2] || '').toUpperCase()} is missing`;
 }
 if (['missing_or_ambiguous_review', 'invalid_review'].includes(code)) {
  return `${parts[1] === 'financial' ? 'Financial' : 'Compliance'} signoff ${code === 'invalid_review' ? 'is invalid for this version' : 'is missing or ambiguous'}`;
 }
 if (['blocking_check', 'missing_check', 'stale_check'].includes(code)) {
  const check = parts[code === 'blocking_check' ? parts.length - 2 : parts.length - 1];
  const label = checkLabels[check] || readable(check);
  if (code === 'stale_check') return `Updated review required: ${label.toLowerCase()}`;
  return `${parts.at(-1) === 'fail' ? 'Failed' : 'Incomplete'}: ${label.toLowerCase()}`;
 }
 const regulatoryLabels: Record<string, string> = {
  compliance_rule_review_missing_or_unexpected: 'A regulatory rule review is missing or unmatched',
  compliance_source_unverified: 'A rule source is not admitted for review',
  compliance_source_bytes_unavailable: 'A retained official rule source is missing',
  compliance_source_bytes_mismatch: 'A retained official rule source has changed',
  compliance_rule_evidence_unresolved: 'A regulatory rule lacks verified transaction evidence',
  compliance_rule_stale: 'A regulatory rule needs a fresh source check',
  compliance_rule_outside_effective_period: 'A rule is outside its reviewed effective period',
  compliance_rule_version_mismatch: 'Rule versions differ; revalidate',
  compliance_rule_source_mismatch: 'Rule source snapshots differ; revalidate',
  compliance_applicability_unresolved: 'A rule’s applicability is unresolved',
  compliance_rule_jurisdiction_mismatch: 'A rule does not match the declared jurisdiction',
  compliance_evidence_missing: 'Required regulatory evidence is missing',
  compliance_evidence_contradicted: 'Regulatory evidence contains a conflict',
  compliance_evidence_not_run: 'Regulatory evidence review has not run',
  compliance_evidence_not_applicable: 'Required regulatory evidence was excluded',
  compliance_invalid_exclusion: 'A rule exclusion needs review',
  compliance_evidence_incomplete: 'Regulatory evidence coverage is incomplete',
 };
 return regulatoryLabels[code] || readable(code);
}
const materialStages = ['materials', 'material_preview', 'material_review', 'material_repair', 'material_re_review'];
const reasonLabel = (reason: string) => reasonLabels[reason] || readable(reason);
function stateLabel(stage: string, state?: string, memoPending = false, revising = false) {
 if (!state) return memoPending && materialStages.includes(stage) ? 'Pending memo acceptance' : 'Not run';
 if (stage === 'investment_memo' && revising && state === 'needs_resume') return 'Revision in progress';
 if (stage === 'investment_memo' && memoMilestones[state]) return memoMilestones[state];
 if (stage === 'evidence' && state === 'recorded') return 'Recorded; verification pending';
 if (['material_review', 'material_re_review'].includes(stage) && state === 'accepted') return 'Local model check passed';
 if (['investment_memo', 'materials', 'material_repair'].includes(stage) && state === 'accepted') return 'Local draft check passed';
 if (stage === 'materials' && state === 'draft') return 'Draft files generated';
 if (stage === 'material_preview' && state === 'accepted') return 'Private previews available; review pending';
 if (stage === 'financial_model' && state === 'partial_evidence') return 'Partial evidence; review required';
 if (stage === 'financial_evidence' && state === 'indexed_source_only') return 'Original cells retained; interpretation pending';
 return readable(state);
}

export default function RoomPipeline({leadId}: {leadId: string}) {
 return <RoomPipelineState key={leadId} leadId={leadId} />;
}

function RoomPipelineState({leadId}: {leadId: string}) {
 const [roomId, setRoomId] = useState('');
 const [error, setError] = useState('');
 const [releaseCheck, setReleaseCheck] = useState<{roomId: string; revision?: string; result: PackageAssessment} | null>(null);
 const [checkingRelease, setCheckingRelease] = useState(false);
 const [releaseError, setReleaseError] = useState('');
 useEffect(() => {
  let current = true;
  api.post<{workspace_id: string}>(`/api/rooms/from-lead/${encodeURIComponent(leadId)}/activate`)
   .then(result => {if (current) setRoomId(result.workspace_id);})
   .catch(cause => {if (current) setError(cause instanceof Error ? cause.message : 'Room activation failed');});
  return () => {current = false;};
 }, [leadId]);
 const room = useQuery({
  queryKey: ['room', roomId],
  queryFn: () => api.get<RoomState>(`/api/rooms/${roomId}`),
  enabled: !!roomId,
  refetchInterval: query => query.state.data?.jobs.some(job => ['queued', 'running'].includes(job.state)) ? 2000 : false,
 });
 const job = room.data?.jobs[0];
 const currentArtifacts = room.data?.artifacts.filter(artifact =>
  job?.input_revision && artifact.input_revision === job.input_revision) ?? [];
 const previousArtifacts = (room.data?.artifacts.length ?? 0) - currentArtifacts.length;
 const validation = job?.checkpoint.validation;
 const memo = job?.checkpoint.investment_memo;
 const causalReview = memo?.causal_review;
 const causalFindings = causalReview?.review?.findings ?? [];
 const savedRevision = (job?.checkpoint as Record<string, unknown> | undefined)?.memo_revision;
 const revisionKey = memo?.memo_revision || (typeof savedRevision === 'string' ? savedRevision : '');
 const revision = memoRevisions[revisionKey];
 const memoPending = !!memo && memo.state !== 'accepted';
 const memoStopped = ['blocked', 'awaiting_input'].includes(memo?.state || '');
 const revising = !!revision && memoPending && !memoStopped;
 const revisionQueued = ['causal_revision_branch_frozen',
  'memo_revision_branch_frozen'].includes(memo?.reason || '');
 const findings = job?.checkpoint.material_re_review?.review?.findings?.length ??
  job?.checkpoint.material_review?.review?.findings?.length;
 const coverage = memo?.content_diligence_coverage;
 const assessedSources = Object.keys(coverage?.judgments ?? {});
 const retainedSources = new Set([...assessedSources, ...(coverage?.unassessed_sources ?? [])]);
 const contentSteps = memo?.content_flow_contract === 'memo-source-unit-flow-v12' ? flow12Steps :
 ['memo-source-unit-flow-v10', 'memo-source-unit-flow-v11'].includes(memo?.content_flow_contract || '') ? flow10Steps :
  ['memo-source-unit-flow-v7', 'memo-source-unit-flow-v8', 'memo-source-unit-flow-v9'].includes(memo?.content_flow_contract || '') ? flow7Steps :
 memo?.content_flow_contract === 'memo-source-unit-flow-v6' ? flow6Steps :
 memo?.content_flow_contract === 'memo-source-unit-flow-v5' ? flow5Steps :
  memo?.content_flow_contract === 'memo-source-unit-flow-v4' ? flow4Steps : [];
 const pendingIndex = contentSteps.indexOf(memo?.content_phase ?? '');
 const completedSteps = memo?.content_review?.state === 'accepted' ? contentSteps.length : pendingIndex;
 const checkedRelease = releaseCheck?.roomId === roomId && releaseCheck.revision === job?.input_revision ? releaseCheck.result : null;
 const blockers = checkedRelease?.blockers ?? validation?.blockers ?? [];
 const blockerGroups = Array.from(new Set(blockers.map(blockerLabel)));
 const jobActive = !!job && ['queued', 'running'].includes(job.state);

 const headline = error || room.error ? null : !roomId || room.isLoading ? 'Opening saved work…' : !job ? 'No room job has been recorded yet.' :
  job.state === 'queued' ? 'Work queued for the local worker.' :
  job.state === 'running' ? 'The local worker is generating materials.' :
  job.state === 'awaiting_input' ? 'Paused: needs your input.' :
  job.state === 'blocked' ? 'Blocked: saved drafts remain available.' : `Job ${readable(job.state)}.`;
 return <div>
  {(error || room.error) && <p role="alert" className="mb-3 text-sm text-rose-700">{error || room.error?.message}</p>}
  {roomId && <Materials roomId={roomId} files={currentArtifacts}/>}
  <details className="mb-6 rounded-xl border border-slate-200 bg-white p-4">
   <summary className="cursor-pointer text-sm font-medium text-slate-700">Pipeline details{headline ? ` · ${headline}` : ''}</summary>
   <div className="mt-3">
    {previousArtifacts > 0 && <p className="mb-3 text-xs text-slate-500">{previousArtifacts} file(s) belong to an earlier revision and are not shown.</p>}
  {job && <>
   <p className="mt-3 text-xs text-slate-600">Drafts remain private until required evidence, financial, compliance and file reviews are approved.</p>
   {memo && ['draft_ready', 'correction_ready', 'ledger_ready'].includes(memo.state || '') &&
    <p className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900">{memoMilestones[memo.state!]}.</p>}
   {revision && memoPending && <section className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900" aria-label="Investment memo revision">
    <h3 className="font-medium">Memo revision: {revision.title.toLowerCase()}</h3>
    <p className="mt-1">{memoStopped ? 'Revision stopped. Saved drafts and findings remain available.' : revision.active}</p>
    <p className="mt-1 text-xs">{job.phase_attempt !== undefined ? `Phase passes: ${job.phase_attempt}. ` : ''}{memo?.attempt_count !== undefined ? `Saved model responses: ${memo.attempt_count}.` : ''}</p>
   </section>}
   {(job.phase === 'content_review' || memo?.phase === 'memo_content_review_pending' || memo?.content_review) &&
    <section className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900" aria-label="Memo content review">
     <h3 className="font-medium">Memo content review</h3>
     <p className="mt-1">{memo?.content_review?.state === 'accepted'
      ? 'Local evidence checks passed. Independent approval is pending.'
      : memoStopped ? 'Review stopped. The draft is not approved.'
      : 'The local model is drafting and checking each evidence-bound section.'}</p>
     {contentSteps.length > 0 && completedSteps >= 0 && <p className="mt-2 text-xs">{completedSteps} of {contentSteps.length} steps complete</p>}
     {memo?.content_phase && <p className="mt-1 text-xs">{memoStopped ? 'Stopped at' : 'Next step'}: {contentPhaseLabel(memo.content_phase)}</p>}
    </section>}
   {coverage && <section className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700" aria-label="Evidence coverage">
    <h3 className="font-medium">Evidence coverage</h3>
    {retainedSources.size > 0 && <p className="mt-1">{assessedSources.length} of {retainedSources.size} retained sources assessed</p>}
    {coverage.unresolved_sources?.length ? <p className="mt-1 text-amber-800">{coverage.unresolved_sources.length} source interpretations remain unresolved.</p> : null}
    {coverage.missing_categories?.length ? <p className="mt-1 text-amber-800">Evidence gaps: {coverage.missing_categories.map(category => coverageLabels[category] || readable(category)).join(', ')}.</p> : null}
    <p className="mt-1 text-xs">Coverage records source text; it does not verify company facts.</p>
   </section>}
   {memoPending && <p className="mt-3 text-sm text-slate-700">Deck drafts, previews and material reviews stay pending until the memo passes its local check.</p>}
   <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
    {stages.filter(({key}) => key !== 'financial_evidence' || job.checkpoint.financial_evidence).map(({key, title}) => {
     const checkpoint = job.checkpoint[key];
     return <div key={key} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
      <h3 className="font-medium text-slate-800">{title}</h3>
      <p className="mt-1 text-slate-600">{stateLabel(key, checkpoint?.state, memoPending, revising)}</p>
      {checkpoint?.reason && <p className="mt-1 text-xs text-amber-800">{reasonLabel(checkpoint.reason)}</p>}
      {['material_review', 'material_re_review'].includes(key) && checkpoint?.batches_total !== undefined &&
       <p className="mt-1 text-xs text-slate-600">{checkpoint.batches_recorded ?? 0} of {checkpoint.batches_total} statement groups reviewed</p>}
      {key === 'evidence' && checkpoint?.recorded_claim_count !== undefined &&
       <p className="mt-1 text-xs text-slate-600">{checkpoint.recorded_claim_count} recorded claims · identity {readable(checkpoint.identity_state || 'unresolved')}</p>}
      {key === 'evidence' && checkpoint?.public_kb &&
       <p className="mt-1 text-xs text-slate-600">Public KB: {readable(checkpoint.public_kb)} · rights: {readable(checkpoint.source_rights || 'unknown')}</p>}
      {key === 'financial_evidence' && checkpoint?.retained_cell_count !== undefined &&
       <p className="mt-1 text-xs text-slate-600">{checkpoint.workbook_count ?? 0} workbook(s) · {checkpoint.retained_cell_count} original cells retained</p>}
      {key === 'financial_evidence' && checkpoint?.state === 'indexed_source_only' &&
       <p className="mt-1 text-xs text-amber-800">Financial meaning, calculation and review are pending.</p>}
      {checkpoint?.error_count ? <p className="mt-1 text-xs text-amber-800">{checkpoint.error_count} findings</p> : null}
     </div>;
    })}
   </div>
   {causalReview && <section className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950" aria-label="Investment memo claim review">
    <h3 className="font-medium">Investment memo claim review</h3>
    <p className="mt-1">{causalReview.state === 'accepted' ? 'Local claim checks passed.' :
     revisionQueued ? 'Flagged wording is awaiting a model correction.' :
     causalReview.state === 'needs_resume' ? 'Checking claims against cited evidence.' :
     'Claim review blocked this draft. Correction and re-review are required.'}</p>
    {causalReview.batches_total !== undefined && <p className="mt-1 text-xs">{causalReview.batches_recorded ?? 0} of {causalReview.batches_total} review batches recorded</p>}
    {!!causalFindings.length && <ul className="mt-2 space-y-2">
     {causalFindings.map((finding, index) => <li key={`${finding.sentence_id || 'finding'}-${index}`} className="rounded border border-amber-200 bg-white p-2">
      <p className="font-medium">{finding.field ? readable(finding.field) : 'Memo claim'}{finding.sentence_id ? ` · ${readable(finding.sentence_id)}` : ''}</p>
      {finding.relation && <p className="mt-1 text-xs">Local model finding: {readable(finding.relation)}</p>}
      {finding.challenged_clause && <p className="mt-1">Flagged wording: “{finding.challenged_clause}”</p>}
      {finding.reason && <p className="mt-1">Review reason: {finding.reason}</p>}
      {!!finding.premise_source_ids?.length && <p className="mt-1 text-xs">Cited source IDs: {finding.premise_source_ids.join(', ')}</p>}
     </li>)}
    </ul>}
    {causalReview.state === 'blocked' && !causalFindings.length && causalReview.reason &&
     <p className="mt-2">Review could not be completed: {reasonLabel(causalReview.reason)}.</p>}
   </section>}
   {findings ? <p className="mt-3 text-sm text-amber-800">Claim review: {findings} {findings === 1 ? 'finding' : 'findings'}.</p> : null}
   <section className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" aria-label="Release requirements">
    <h3 className="font-medium">Release requirements</h3>
    {blockerGroups.length ? <ul className="mt-2 list-inside list-disc">{blockerGroups.map(label => <li key={label}>{label}</li>)}</ul> :
     <p className="mt-1">{checkedRelease?.eligible_for_release ? 'Recorded checks allow a release request. These files have not been released.' : 'Required reviews have not been established.'}</p>}
    {blockers.length > 0 && <details className="mt-2 text-xs">
     <summary className="cursor-pointer">Check details ({blockers.length})</summary>
     <ul className="mt-2 space-y-1">{blockers.map((blocker, index) => <li key={`${blocker}-${index}`} className="break-all font-mono">{blocker}</li>)}</ul>
    </details>}
    <button type="button" disabled={jobActive || checkingRelease} className="mt-3 text-sm text-indigo-700 underline disabled:cursor-not-allowed disabled:text-slate-500" onClick={async () => {
     setCheckingRelease(true); setReleaseError('');
     const revision = job.input_revision;
     try {
      const result = await api.post<PackageAssessment>(`/api/rooms/${roomId}/validate`);
      setReleaseCheck({roomId, revision, result});
     } catch (cause) {setReleaseError(cause instanceof Error ? cause.message : 'Release check failed');}
     finally {setCheckingRelease(false);}
    }}>{checkingRelease ? 'Checking requirements…' : 'Check release requirements'}</button>
    {checkedRelease && <p className="mt-1 text-xs">Recorded check for this input revision. Later edits require a new check.</p>}
    {releaseError && <p role="alert" className="mt-2 text-rose-700">{releaseError}</p>}
   </section>
   {job.error && <p role="alert" className="mt-3 text-sm text-rose-700">Worker error: {readable(job.error)}</p>}
   {['queued', 'running'].includes(job.state) && <button className="mt-3 text-sm text-indigo-700 underline" onClick={async () => {
    try {await api.post(`/api/rooms/${roomId}/jobs/${job.id}/cancel`); await room.refetch();}
    catch (cause) {setError(cause instanceof Error ? cause.message : 'Cancellation failed');}
   }}>Cancel work</button>}
  </>}

   </div>
  </details>
 </div>;
}
