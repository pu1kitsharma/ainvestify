import {useEffect, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../api/client';
import Materials from './Materials';

type Checkpoint = {
 state?: string; phase?: string; reason?: string; error_count?: number; blockers?: string[];
 recorded_claim_count?: number; identity_state?: string; public_kb?: string; source_rights?: string;
 review?: {findings?: unknown[]};
 attempt_count?: number; memo_revision?: string;
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

const stages: {key: string; title: string}[] = [
 {key: 'evidence', title: 'Evidence collected'},
 {key: 'financial_model', title: 'Financial reconciliation'},
 {key: 'investment_memo', title: 'Investment memo draft'},
 {key: 'materials', title: 'Deck drafts'},
 {key: 'material_preview', title: 'Private draft previews'},
 {key: 'material_review', title: 'Local semantic review'},
 {key: 'material_repair', title: 'Model authored correction'},
 {key: 'material_re_review', title: 'Frozen re-review'},
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
  active: 'The local model is rewriting one blocked memo field using only the source passages that field cites. The rewritten field is checked again before the memo can move on.'},
 field_v2: {title: 'Second field rewrite',
  active: 'The local model is rewriting another field flagged by final review from its exact cited evidence. The new wording must pass source binding, claim review and final review.'},
 stable_v1: {title: 'Changed sentence review',
  active: 'Earlier local model judgments are reused, exactly as recorded, only where a sentence and its evidence are unchanged. Every changed sentence is reviewed individually.'},
};
const reasonLabels: Record<string, string> = {
 causal_revision_branch_frozen: 'Blocked wording saved; bounded revision queued',
 memo_revision_branch_frozen: 'Blocked wording saved; bounded revision queued',
 bounded_local_memo_attempts_exhausted: 'Pass limit reached; memo not accepted',
 local_memo_review_not_accepted: 'Waiting for the memo to pass its local check',
 local_memo_validation_failed: 'Waiting for the memo to pass its local check',
};
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
 return readable(state);
}

export default function RoomPipeline({leadId}: {leadId: string}) {
 const [roomId, setRoomId] = useState('');
 const [error, setError] = useState('');
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

 const headline = error || room.error ? null : !roomId || room.isLoading ? 'Opening saved work…' : !job ? 'No room job has been recorded yet.' :
  job.state === 'queued' ? 'Work queued for the local worker.' :
  job.state === 'running' ? 'The local worker is generating materials.' :
  job.state === 'awaiting_input' ? 'Paused: needs your input.' :
  job.state === 'blocked' ? 'Blocked: saved drafts remain available.' : `Job ${readable(job.state)}.`;
 return <div>
  {(error || room.error) && <p role="alert" className="mb-3 text-sm text-rose-700">{error || room.error?.message}</p>}
  {roomId && <Materials roomId={roomId} files={currentArtifacts}/>}
  {previousArtifacts > 0 && <p className="mb-3 text-xs text-slate-500">{previousArtifacts} file(s) belong to an earlier revision and are not shown.</p>}
  <details className="mb-6 rounded-xl border border-slate-200 bg-white p-4">
   <summary className="cursor-pointer text-sm font-medium text-slate-700">Pipeline details{headline ? ` · ${headline}` : ''}</summary>
   <div className="mt-3">
  {job && <>
   <p className="mt-3 text-xs text-slate-600">Local draft and model checks are separate from independent diligence, financial sign-off, visual review and release approval.</p>
   <p className="mt-1 text-xs text-slate-600">A passed local model check means the same local model workflow found no issue in its own draft. Independent content, financial and visual approval are not recorded by these checks, and no status here is investor acceptance.</p>
   {memo && ['draft_ready', 'correction_ready', 'ledger_ready'].includes(memo.state || '') &&
    <p className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900">{memoMilestones[memo.state!]} for this room revision. The private PDF and editable file previews appear after the material draft and export phases.</p>}
   {revision && memoPending && <section className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900" aria-label="Investment memo revision">
    <h3 className="font-medium">Memo revision: {revision.title.toLowerCase()}</h3>
    <p className="mt-1">{memoStopped ? `The ${revision.title.toLowerCase()} stopped before the memo passed its local check. Saved drafts and findings remain available.` : revision.active}</p>
    <p className="mt-1 text-xs">{job.phase_attempt !== undefined ? `Pass ${job.phase_attempt} of this phase recorded. ` : ''}{memo?.attempt_count !== undefined ? `${memo.attempt_count} local model responses saved. ` : ''}Passes are capped: the work stops and reports its findings instead of retrying indefinitely.</p>
    <p className="mt-1 text-xs">This revision is a local model step. It does not replace independent review, and the memo is not accepted until it passes.</p>
   </section>}
   {memoPending && <p className="mt-3 text-sm text-slate-700">Deck drafts, previews and material reviews stay pending until the memo passes its local check.</p>}
   <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
    {stages.map(({key, title}) => {
     const checkpoint = job.checkpoint[key];
     return <div key={key} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
      <h3 className="font-medium text-slate-800">{title}</h3>
      <p className="mt-1 text-slate-600">{stateLabel(key, checkpoint?.state, memoPending, revising)}</p>
      {checkpoint?.reason && <p className="mt-1 text-xs text-amber-800">{reasonLabel(checkpoint.reason)}</p>}
      {key === 'evidence' && checkpoint?.recorded_claim_count !== undefined &&
       <p className="mt-1 text-xs text-slate-600">{checkpoint.recorded_claim_count} recorded claims · identity {readable(checkpoint.identity_state || 'unresolved')}</p>}
      {key === 'evidence' && checkpoint?.public_kb &&
       <p className="mt-1 text-xs text-slate-600">Public KB: {readable(checkpoint.public_kb)} · rights: {readable(checkpoint.source_rights || 'unknown')}</p>}
      {checkpoint?.error_count ? <p className="mt-1 text-xs text-amber-800">{checkpoint.error_count} findings</p> : null}
     </div>;
    })}
   </div>
   {causalReview && <section className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950" aria-label="Investment memo claim review">
    <h3 className="font-medium">Investment memo claim review</h3>
    <p className="mt-1">{causalReview.state === 'accepted' ? 'The local model completed this source scoped claim check.' :
     revisionQueued ? 'A source scoped claim check blocked the wording below. A bounded, model authored revision is queued; the flagged wording has not been accepted.' :
     causalReview.state === 'needs_resume' ? 'The local model is checking the saved memo against its cited source passages.' :
     'A source scoped claim check blocked this memo draft. The flagged wording needs model authored correction and another review before investor use.'}</p>
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
   {findings ? <p className="mt-3 text-sm text-amber-800">Local semantic review recorded {findings} {findings === 1 ? 'finding' : 'findings'}. Check the saved review before relying on the drafts.</p> : null}
   {validation?.blockers?.length ? <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
    <h3 className="font-medium">Release blockers</h3>
    <ul className="mt-2 list-inside list-disc">{validation.blockers.map(blocker => <li key={blocker}>{readable(blocker)}</li>)}</ul>
   </div> : <p className="mt-3 text-sm text-slate-600">Release validation has not established an investor ready package.</p>}
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
