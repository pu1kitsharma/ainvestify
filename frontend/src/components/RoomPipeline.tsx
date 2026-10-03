import {useEffect, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../api/client';

type Checkpoint = {
 state?: string; reason?: string; error_count?: number; blockers?: string[];
 recorded_claim_count?: number; identity_state?: string; public_kb?: string; source_rights?: string;
 review?: {findings?: unknown[]};
};
type RoomJob = {
 id: string; state: string; phase?: string; input_revision?: string;
 checkpoint: Record<string, Checkpoint>; error?: string;
};
type RoomArtifact = {id: string; kind: string; format: string; state: string; input_revision: string};
type RoomState = {id: string; jobs: RoomJob[]; artifacts: RoomArtifact[]};

const stages: {key: string; title: string}[] = [
 {key: 'evidence', title: 'Evidence collected'},
 {key: 'financial_model', title: 'Financial reconciliation'},
 {key: 'investment_memo', title: 'Investment memo draft'},
 {key: 'materials', title: 'Deck drafts'},
 {key: 'material_review', title: 'Local semantic review'},
 {key: 'material_repair', title: 'Model authored correction'},
 {key: 'material_re_review', title: 'Frozen re-review'},
 {key: 'validation', title: 'Release validation'},
];
const artifactNames: Record<string, string> = {
 intro_deck: 'Introduction deck', pitch_deck: 'Pitch deck',
 investment_memorandum: 'Investment memorandum', research_brief: 'Research brief',
};
const readable = (value: string) => value.replaceAll('_', ' ');
function stateLabel(stage: string, state?: string) {
 if (!state) return 'Not run';
 if (stage === 'evidence' && state === 'recorded') return 'Recorded; verification pending';
 if (['material_review', 'material_re_review'].includes(stage) && state === 'accepted') return 'Local model check passed';
 if (['investment_memo', 'materials', 'material_repair'].includes(stage) && state === 'accepted') return 'Local draft check passed';
 if (stage === 'materials' && state === 'draft') return 'Draft files generated';
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
 const findings = job?.checkpoint.material_re_review?.review?.findings?.length ??
  job?.checkpoint.material_review?.review?.findings?.length;

 return <section className="mb-5 rounded-xl border border-slate-200 bg-white p-4" aria-label="Deal room workflow">
  <h2 className="font-semibold">Deal room workflow</h2>
  {error || room.error ? <p role="alert" className="mt-2 text-sm text-rose-700">{error || room.error?.message}</p> :
   <p role="status" className="mt-2 text-sm text-slate-700">
    {!roomId || room.isLoading ? 'Opening saved work…' : !job ? 'No room job has been recorded yet.' :
     job.state === 'queued' ? 'Work queued for the local worker.' :
     job.state === 'running' ? `Local worker is processing ${readable(job.phase || 'room work')}.` :
     job.state === 'awaiting_input' ? 'Work paused. Review the gates and missing inputs below.' :
     job.state === 'blocked' ? 'Work blocked. Saved evidence and drafts remain available.' :
     `Room job ${readable(job.state)}. Review release validation below.`}
   </p>}

  {job && <>
   <p className="mt-3 text-xs text-slate-600">Local draft and model checks are separate from independent diligence, financial sign-off, visual review and release approval.</p>
   <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
    {stages.map(({key, title}) => {
     const checkpoint = job.checkpoint[key];
     return <div key={key} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
      <h3 className="font-medium text-slate-800">{title}</h3>
      <p className="mt-1 text-slate-600">{stateLabel(key, checkpoint?.state)}</p>
      {checkpoint?.reason && <p className="mt-1 text-xs text-amber-800">{readable(checkpoint.reason)}</p>}
      {key === 'evidence' && checkpoint?.recorded_claim_count !== undefined &&
       <p className="mt-1 text-xs text-slate-600">{checkpoint.recorded_claim_count} recorded claims · identity {readable(checkpoint.identity_state || 'unresolved')}</p>}
      {key === 'evidence' && checkpoint?.public_kb &&
       <p className="mt-1 text-xs text-slate-600">Public KB: {readable(checkpoint.public_kb)} · rights: {readable(checkpoint.source_rights || 'unknown')}</p>}
      {checkpoint?.error_count ? <p className="mt-1 text-xs text-amber-800">{checkpoint.error_count} findings</p> : null}
     </div>;
    })}
   </div>
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

  {!!currentArtifacts.length && <div className="mt-4 border-t border-slate-200 pt-4">
   <h3 className="font-medium">Current revision draft files</h3>
   <p className="mt-1 text-xs text-slate-600">Preview downloads are private drafts. Final download requires a separately validated and released exact version.</p>
   <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-2 text-sm">
    {currentArtifacts.map(artifact => <li key={artifact.id}><a className="text-indigo-700 underline" href={`/api/rooms/${roomId}/artifacts/${artifact.id}/preview`}>
     Preview draft {artifactNames[artifact.kind] || readable(artifact.kind)} ({artifact.format.toUpperCase()})
    </a></li>)}
   </ul>
  </div>}
  {previousArtifacts > 0 && <p className="mt-3 text-xs text-slate-600">{previousArtifacts} file(s) belong to an earlier room revision and are omitted from the current draft list.</p>}
 </section>;
}
