import {useEffect, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {api} from '../api/client';
import SourceLedger from './SourceLedger';

type Step = {key: string; label: string; kind: string; state: string; started?: number; finished?: number; seconds?: number; cached?: boolean; detail?: string};
type Round = {round: number; kept: string[]; dropped: string[]; scores: Record<string, number | null>; changes?: Record<string, {before_score: number | null; candidate_score: number | null; kept: boolean; diff: string; reason: string}>};
type PageStatus = {key: string; title: string; state: string; problems: string[]};
type PageChanges = {previous: string; changes: {key: string; change: string; diff: string}[]};
type ApprovalRecord = {by: string; at: number; notes?: string; decision?: string; current: boolean; waivers?: {key: string; reason: string}[]};
export type Phase = {
 title: string; state: string; steps: Step[]; started_at?: number; finished_at?: number; queued_at?: number; error?: string;
 approvals: Record<string, ApprovalRecord>; required_approvals: string[]; blocked_reason: string | null; stale?: boolean;
 interruptions?: number; cancel_requested?: boolean; elapsed_seconds: number; remaining_seconds: number; steps_done: number; steps_total: number;
 remaining_low?: number; remaining_high?: number; measured_steps?: number;
 estimate_basis?: string; timings?: Record<string, {samples: number; mean_seconds: number; basis: string}>;
 active_calls?: Record<string, {name: string; profile: string; started: number}>;
 call_timings?: Record<string, {samples: number; mean_seconds: number; min_seconds: number; max_seconds: number}>;
 pages?: PageStatus[]; rounds?: Round[]; page_changes?: PageChanges;
};
type Question = {id: string; text: string; why: string; severity: 'blocker' | 'high' | 'medium'; confidence: number; basis: string; sections: string[];
 answer: {text: string; by: string; at: number} | null};
type Readiness = {score: number; uncapped: number; cap: number; cap_reason: string; phase: string; at: number;
 parts: {key: string; label: string; value: number; weight: number; detail: string}[]};
export type Run = {id: string; company: string; model: string; now: number; worker_alive: boolean; phases: Record<PhaseKey, Phase>; events: {at: number; text: string}[];
 questions?: Question[]; readiness?: Readiness | null; generation_path?: 'page_first' | 'prose'};
type FileInfo = {name: string; phase: string; label: string; size: number; updated: number};
type Earlier = {version: string; updated: number; files: {name: string; phase: string; label: string}[]; rounds?: Round[]};
export type Status = {run: Run | null; files: FileInfo[]; earlier?: Earlier[]; is_owner: boolean; qualified_compliance_reviewer: boolean};
export type PhaseKey = 'facts' | 'memo' | 'decks';
type Check = {key: string; title: string; status: 'pass' | 'fail' | 'counsel'; detail: string; evidence: string[]};
type Issue = {reviewer: string; section?: string; quote?: string; problem?: string; type?: string; area?: string; fix?: string; change?: string; action?: string; quote_verified?: boolean; unverified_number?: boolean};
type MemoView = {
 sections: {section: string; title: string; state: string; problems: string[]; revised_from_review?: boolean;
  removed_sentences: {paragraph: number; sentence: string; reasons: string[]}[];
  paragraphs: {kind: string; text: string; cites: string[]}[]; calculations: {id: string; label: string; text: string; kind: string}[]}[];
 review: {issues: Issue[]; overall: string; compliance_areas: {area: string; status: string; reason: string}[]; failures: string[]} | null;
 compliance: {checks: Check[]; blockers: string[]; assessed_on: string} | null;
};

export const PHASES: PhaseKey[] = ['facts', 'memo', 'decks'];
const stateText: Record<string, string> = {
 not_started: 'Not started', queued: 'Queued — waiting for the local worker', running: 'Generating', needs_approval: 'Ready for your review',
 approved: 'Approved', failed: 'Stopped with an error', cancelled: 'Stopped',
};
const stateTone: Record<string, string> = {
 not_started: 'bg-slate-100 text-slate-600', queued: 'bg-indigo-50 text-indigo-700', running: 'bg-indigo-100 text-indigo-800',
 needs_approval: 'bg-amber-100 text-amber-900', approved: 'bg-emerald-100 text-emerald-800', failed: 'bg-rose-100 text-rose-800',
 cancelled: 'bg-slate-200 text-slate-700',
};
const approvalNames: Record<string, string> = {operator: 'Your approval', compliance: 'Compliance sign-off (qualified reviewer)'};

function duration(seconds: number) {
 const s = Math.max(0, Math.round(seconds));
 const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
 return h ? `${h}h ${String(m).padStart(2, '0')}m` : m ? `${m}m ${String(sec).padStart(2, '0')}s` : `${sec}s`;
}
const TEN_MINUTES = 600;
/** A clock time rounded up to ten minutes, so an estimate never looks more exact than it is. */
function clock(epoch: number) {
 const rounded = new Date(Math.ceil(epoch / TEN_MINUTES) * TEN_MINUTES * 1000);
 return rounded.toLocaleString(undefined, {weekday: 'short', hour: 'numeric', minute: '2-digit'});
}
/** Approximate finish time and the upper end of the estimated range. */
export function finishText(phase: Phase, run: Run) {
 if (!run.worker_alive) return 'Paused: the worker is not running';
 const latest = phase.remaining_high ? `, estimated range to ${clock(run.now + phase.remaining_high)}` : '';
 return `Expected around ${clock(run.now + phase.remaining_seconds)}${latest}`;
}
const when = (epoch: number) => new Date(epoch * 1000).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});

/** Ticks once a second; returns server time so durations match the worker's clock. */
function useServerNow(serverNow?: number) {
 const [offset, setOffset] = useState(0);
 const [, setTick] = useState(0);
 useEffect(() => {if (serverNow) setOffset(serverNow - Date.now() / 1000);}, [serverNow]);
 useEffect(() => {const id = window.setInterval(() => setTick(t => t + 1), 1000); return () => window.clearInterval(id);}, []);
 return Date.now() / 1000 + offset;
}

export default function DealDocuments({roomId, compact}: {roomId: string; compact?: boolean}) {
 const client = useQueryClient();
 const status = useQuery({
  queryKey: ['deal-documents', roomId],
  queryFn: () => api.get<Status>(`/api/rooms/${roomId}/deal-documents`),
  refetchInterval: query => Object.values(query.state.data?.run?.phases ?? {}).some(p => ['queued', 'running'].includes(p.state)) ? 4000 : 60000,
 });
 const run = status.data?.run;
 const now = useServerNow(run?.now);
 const active = PHASES.find(key => ['queued', 'running'].includes(run?.phases[key].state ?? ''));
 const [open, setOpen] = useState<PhaseKey | null>(null);
 const shown: PhaseKey = open ?? active ?? PHASES.slice().reverse().find(key => run && run.phases[key].state !== 'not_started') ?? 'facts';
 const action = useMutation({
  mutationFn: ({phase, verb, body}: {phase: PhaseKey; verb: 'start' | 'cancel' | 'approve'; body?: unknown}) =>
   api.post(`/api/rooms/${roomId}/deal-documents/${phase}/${verb}`, body),
  onSuccess: () => client.invalidateQueries({queryKey: ['deal-documents', roomId]}),
 });
 if (status.isLoading) return <p role="status" className="text-sm text-slate-500">Loading document status…</p>;
 if (status.error) return <p role="alert" className="text-sm text-rose-700">{status.error.message}</p>;
 const phases = run?.phases;
 const live = active && phases ? phases[active] : null;
 const running = live?.steps.find(step => step.state === 'running');
 const percent = live && live.steps_total ? Math.round((live.steps_done / live.steps_total) * 100) : 0;

 return <section className="mb-6 rounded-xl border border-slate-200 bg-white p-5" aria-label="Investor documents">
  <div className="flex flex-wrap items-start justify-between gap-3">
   <div>
    <h2 className="text-lg font-semibold">Investor documents</h2>
    <p className="mt-1 max-w-2xl text-sm text-slate-500">Fact base, investment memorandum and decks, generated in phases on this computer. Each phase waits for your approval. Drafts are visible only to members of this sandbox; nothing is sent to investors.</p>
   </div>
   {run && <p className="text-xs text-slate-500">Model {run.model} · {run.worker_alive ? 'local worker connected' : active ? 'waiting for the worker' : 'worker idle'}</p>}
  </div>

  <LatestDocuments roomId={roomId} files={status.data?.files ?? []}/>

  {live && phases && <div className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50 p-4" role="status" aria-live="polite">
   <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm text-indigo-900">
    <p className="font-medium">{live.title}: {live.state === 'queued' ? 'queued' : running ? running.label : 'working'}</p>
    <p>{live.state === 'running' && run ? finishText(live, run) : 'Waiting for the worker'}</p>
   </div>
   <div className="mt-2 h-2 overflow-hidden rounded-full bg-indigo-100"><div className="h-full rounded-full bg-indigo-600 transition-all" style={{width: `${percent}%`}}/></div>
   <p className="mt-1 text-xs text-indigo-800">{live.steps_done} of {live.steps_total} steps done{live.cancel_requested ? ' · stopping after the current step' : ''}</p>
   {live.estimate_basis && <p className="mt-2 text-xs text-indigo-800">{live.estimate_basis}</p>}
   {Object.entries(live.active_calls ?? {}).map(([id, call]) => {
    const timing = live.call_timings?.[call.profile];
    return <p key={id} className="mt-1 text-xs text-indigo-800">{call.name}: {duration(now - call.started)} elapsed. {timing
     ? `Previous ${call.profile} calls averaged ${duration(timing.mean_seconds)} across ${timing.samples} calls (${duration(timing.min_seconds)}–${duration(timing.max_seconds)}).`
     : 'No completed calls of this kind measured yet.'}</p>;
   })}
  </div>}

  {!compact && run?.readiness && <ReadinessMeter readiness={run.readiness}/>}
  {!compact && run && (run.questions?.length ?? 0) > 0 && <Questions roomId={roomId} run={run} isOwner={!!status.data?.is_owner}/>}

  <ol className="mt-4 grid gap-3 md:grid-cols-3">
   {PHASES.map((key, index) => {
    const phase = phases?.[key];
    const state = phase?.state ?? 'not_started';
    const elapsed = (phase?.elapsed_seconds ?? 0) + (state === 'running' && run?.worker_alive ? Math.max(0, now - run.now) : 0);
    return <li key={key}>
     <button type="button" onClick={() => setOpen(key)} aria-pressed={shown === key}
      className={`h-full w-full rounded-lg border p-3 text-left text-sm ${shown === key ? 'border-indigo-400 ring-1 ring-indigo-300' : 'border-slate-200'}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Phase {index + 1}</p>
      <p className="mt-1 font-medium text-slate-900">{phase?.title ?? ['Verified fact base', 'Investment memorandum', 'Pitch and introductory decks'][index]}</p>
      <span className={`mt-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${stateTone[state]}`}>{stateText[state] ?? state}</span>
      {phase && phase.steps_total > 0 && <p className="mt-2 text-xs text-slate-600">{phase.steps_done}/{phase.steps_total} steps{elapsed ? ` · ${duration(elapsed)}` : ''}</p>}
      {phase?.stale && <p className="mt-1 text-xs text-amber-800">Earlier phase changed; regenerate</p>}
     </button>
    </li>;
   })}
  </ol>

  <PhaseDetail key={shown} roomId={roomId} phaseKey={shown} status={status.data!} now={now}
   act={(verb, body) => action.mutate({phase: shown, verb, body})} busy={action.isPending}/>
  {!compact && run && <SourceLedger roomId={roomId} decks={shown === 'decks'} canEdit={!!status.data?.is_owner && !Object.values(run.phases).some(phase => ['queued', 'running'].includes(phase.state))}/>}
  {action.error && <p role="alert" className="mt-2 text-sm text-rose-700">{action.error.message}</p>}

  {run && run.events.length > 0 && <details className="mt-4 text-sm">
   <summary className="cursor-pointer text-slate-600">Activity ({run.events.length})</summary>
   <ul className="mt-2 space-y-1 text-xs text-slate-600">{run.events.slice().reverse().map((event, i) =>
    <li key={i}><span className="text-slate-400">{when(event.at)}</span> · {event.text}</li>)}</ul>
  </details>}
 </section>;
}

function Meter({value, tone, label}: {value: number; tone: string; label: string}) {
 return <div role="meter" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={100} className="h-2 overflow-hidden rounded-full bg-slate-100">
  <div className={`h-full rounded-full ${tone}`} style={{width: `${value}%`}}/></div>;
}

const scoreTone = (value: number) => value >= 85 ? 'bg-emerald-600' : value >= 70 ? 'bg-amber-500' : 'bg-rose-500';

/** How close the documents are to release: code-computed from checks, never the model's opinion of itself. */
export function ReadinessMeter({readiness}: {readiness: Readiness}) {
 return <div className="mt-4 rounded-lg border border-slate-200 p-4">
  <div className="flex flex-wrap items-baseline justify-between gap-2">
   <h3 className="text-sm font-semibold text-slate-900">Investor readiness</h3>
   <p className="text-2xl font-semibold tabular-nums text-slate-900">{readiness.score}<span className="text-sm font-normal text-slate-500">/100</span></p>
  </div>
  <div className="mt-2"><Meter value={readiness.score} tone={scoreTone(readiness.score)} label="Investor readiness"/></div>
  {readiness.cap_reason && <p className="mt-2 text-sm text-amber-800">Held at {readiness.cap} or below: {readiness.cap_reason.toLowerCase()}.</p>}
  <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{readiness.parts.map(part => <div key={part.key}>
   <dt className="flex justify-between text-xs text-slate-600"><span>{part.label}</span><span className="tabular-nums">{part.value}</span></dt>
   <dd className="mt-1"><Meter value={part.value} tone={scoreTone(part.value)} label={part.label}/><p className="mt-1 text-xs text-slate-500">{part.detail}</p></dd>
  </div>)}</dl>
  <p className="mt-3 text-xs text-slate-500">Calculated from these checks. It measures how complete and checked the documents are, not how an investor will decide.</p>
 </div>;
}

const severityTone: Record<Question['severity'], string> = {blocker: 'bg-rose-100 text-rose-800', high: 'bg-amber-100 text-amber-900', medium: 'bg-slate-100 text-slate-700'};
const severityText: Record<Question['severity'], string> = {blocker: 'Blocks release', high: 'Investors will ask', medium: 'Worth confirming'};

function QuestionCard({roomId, question, isOwner}: {roomId: string; question: Question; isOwner: boolean}) {
 const client = useQueryClient();
 const [text, setText] = useState(question.answer?.text ?? '');
 const save = useMutation({
  mutationFn: (value: string) => api.post(`/api/rooms/${roomId}/deal-documents/questions/${question.id}/answer`, {text: value}),
  onSuccess: () => client.invalidateQueries({queryKey: ['deal-documents', roomId]}),
 });
 return <li className="rounded-lg border border-slate-200 p-3">
  <div className="flex flex-wrap items-center gap-2">
   <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${severityTone[question.severity]}`}>{severityText[question.severity]}</span>
   {question.answer && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">Answered</span>}
  </div>
  <p className="mt-2 text-sm font-medium text-slate-900">{question.text}</p>
  <p className="mt-1 text-sm text-slate-600">{question.why}</p>
  <div className="mt-2 max-w-sm">
   <p className="flex justify-between text-xs text-slate-600"><span>Confidence this needs an answer</span><span className="tabular-nums">{question.confidence}%</span></p>
   <div className="mt-1"><Meter value={question.confidence} tone="bg-indigo-600" label="Confidence this needs an answer"/></div>
   <p className="mt-1 text-xs text-slate-500">{question.basis}</p>
  </div>
  {isOwner && <div className="mt-3">
   <label className="block text-xs text-slate-600" htmlFor={`answer-${question.id}`}>Your answer</label>
   <textarea id={`answer-${question.id}`} value={text} onChange={event => setText(event.target.value)} rows={2} maxLength={4000}
    className="mt-1 w-full rounded-md border border-slate-300 p-2 text-sm"/>
   <button type="button" disabled={save.isPending || text.trim() === (question.answer?.text ?? '')} onClick={() => save.mutate(text)}
    className="mt-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 disabled:opacity-50">{question.answer && !text.trim() ? 'Withdraw answer' : 'Save answer'}</button>
   {save.isError && <p role="alert" className="mt-1 text-sm text-rose-700">The answer was not saved. Try again.</p>}
  </div>}
 </li>;
}

/** What the system needs from the company. Answers become citable company statements in the next run. */
export function Questions({roomId, run, isOwner}: {roomId: string; run: Run; isOwner: boolean}) {
 const questions = run.questions ?? [];
 const open = questions.filter(question => !question.answer).length;
 const rank = {blocker: 0, high: 1, medium: 2};
 const ordered = [...questions].sort((a, b) => Number(!!a.answer) - Number(!!b.answer) || rank[a.severity] - rank[b.severity] || b.confidence - a.confidence);
 return <details id="questions" open={open > 0} className="mt-4 rounded-lg border border-amber-200 bg-amber-50/40 p-4">
  <summary className="cursor-pointer text-sm font-semibold text-slate-900">Questions for you ({open} open of {questions.length})</summary>
  <p className="mt-2 text-sm text-slate-600">The documents cannot settle these on their own. Regenerate the memorandum after answering, and your answers are written in as the company's statements.</p>
  <ul className="mt-3 space-y-3">{ordered.map(question => <QuestionCard key={question.id} roomId={roomId} question={question} isOwner={isOwner}/>)}</ul>
 </details>;
}

/** One-line status for a company card: the active phase with its timer, or what needs review. */
export function DocumentProgress({roomId}: {roomId: string}) {
 const status = useQuery({
  queryKey: ['deal-documents', roomId],
  queryFn: () => api.get<Status>(`/api/rooms/${roomId}/deal-documents`),
  refetchInterval: query => Object.values(query.state.data?.run?.phases ?? {}).some(p => ['queued', 'running'].includes(p.state)) ? 10000 : 120000,
  retry: false,
 });
 const run = status.data?.run;
 if (!run) return null;
 const active = PHASES.find(key => ['queued', 'running'].includes(run.phases[key].state));
 if (active) {
  const phase = run.phases[active];
  const step = phase.steps.find(item => item.state === 'running');
  return <p className="mt-3 text-sm text-indigo-700" role="status">{phase.title}: {phase.state === 'queued' ? 'queued' : step?.label ?? 'generating'} · {finishText(phase, run)}</p>;
 }
 const review = PHASES.find(key => run.phases[key].state === 'needs_approval');
 if (review) return <p className="mt-3 text-sm text-amber-800">{run.phases[review].title} is ready for your review.</p>;
 const failed = PHASES.find(key => run.phases[key].state === 'failed');
 if (failed) return <p className="mt-3 text-sm text-rose-700">{run.phases[failed].title} stopped with an error. Open the room to resume.</p>;
 return null;
}

const MAIN_DOCUMENTS = [
 ['investment_memorandum.pdf', 'Investment memorandum'],
 ['pitch_deck.pdf', 'Pitch deck'],
 ['intro_deck.pdf', 'Introductory deck'],
] as const;

function LatestDocuments({roomId, files}: {roomId: string; files: Status['files']}) {
 const ready = MAIN_DOCUMENTS.flatMap(([name, title]) => {
  const file = files.find(item => item.name === name);
  return file ? [{...file, title}] : [];
 });
 if (ready.length === 0) return null;
 return <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50/50 p-4">
  <h3 className="text-sm font-semibold text-slate-900">Latest documents</h3>
  <p className="mt-1 text-xs text-slate-600">Review drafts, not approved for distribution.</p>
  <ul className="mt-3 grid gap-2 sm:grid-cols-3">{ready.map(file => <li key={file.name}>
   <a href={`/api/rooms/${roomId}/deal-documents/files/${file.name}`} target="_blank" rel="noreferrer"
    className="block rounded-lg border border-slate-200 bg-white p-3 hover:border-indigo-300 hover:bg-indigo-50">
    <span className="block text-sm font-semibold text-indigo-700">{file.title} (PDF)</span>
    <span className="mt-1 block text-xs text-slate-500">Updated {when(file.updated)}</span>
   </a></li>)}</ul>
 </div>;
}

function PhaseDetail({roomId, phaseKey, status, now, act, busy}: {
 roomId: string; phaseKey: PhaseKey; status: Status; now: number; busy: boolean;
 act: (verb: 'start' | 'cancel' | 'approve', body?: unknown) => void;
}) {
 const phase = status.run?.phases[phaseKey];
 const [notes, setNotes] = useState('');
 const [generationPath, setGenerationPath] = useState<'page_first' | 'prose'>(status.run?.generation_path ?? 'page_first');
 const state = phase?.state ?? 'not_started';
 const files = status.files.filter(file => file.phase === phaseKey);
 const earlier = (status.earlier ?? []).filter(version => version.files.some(file => file.phase === phaseKey));
 const startLabel = state === 'not_started' ? 'Start' : 'Regenerate';
 const blocked = phase?.blocked_reason ?? (phaseKey !== 'facts' && !status.run ? 'Approve the earlier phases first' : null);
 return <div className="mt-4 space-y-4">
  <div className="flex flex-wrap items-center gap-3">
   {phaseKey === 'memo' && status.is_owner && !['queued', 'running'].includes(state) && <label className="text-sm text-slate-700">
    Generation <select aria-label="Memorandum generation path" value={generationPath} onChange={event => setGenerationPath(event.target.value as 'page_first' | 'prose')}
     className="ml-2 rounded border border-slate-300 p-2">
     <option value="page_first">Pages first</option><option value="prose">Include full prose review copy</option>
    </select></label>}
   {status.is_owner && !['queued', 'running'].includes(state) &&
    <button type="button" disabled={busy || !!blocked} onClick={() => act('start', phaseKey === 'memo' ? {generation_path: generationPath} : undefined)}
     className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{startLabel} {phase?.title.toLowerCase() ?? ''}</button>}
   {status.is_owner && ['queued', 'running'].includes(state) &&
    <button type="button" disabled={busy || phase?.cancel_requested} onClick={() => act('cancel')}
     className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-50">{phase?.cancel_requested ? 'Stopping after this step…' : 'Stop'}</button>}
   {blocked && !['queued', 'running'].includes(state) && <p className="text-sm text-amber-800">{blocked}</p>}
   {phase?.error && <p role="alert" className="text-sm text-rose-700">{phase.error}</p>}
  </div>

  {phaseKey === 'memo' && (phase?.pages?.length ?? 0) > 0 && <div className="rounded-lg border border-slate-200 p-3">
   <h3 className="text-sm font-medium text-slate-800">Memorandum pages</h3>
   {files.some(file => file.name === 'investment_memorandum.preview.pdf') && <a className="mt-2 inline-block text-sm font-medium text-indigo-700"
    href={`/api/rooms/${roomId}/deal-documents/files/investment_memorandum.preview.pdf`} target="_blank" rel="noreferrer">Open live preview</a>}
   <p className="mt-1 text-xs text-slate-600">The preview updates as pages arrive. Audited pages still require the document compliance gate and human approval.</p>
   <ol className="mt-2 space-y-2 text-sm">{phase?.pages?.map((page, index) => <li key={page.key}>
    <span className="font-medium">{index + 1}. {page.title}</span> <span className="text-xs text-slate-600">{page.state.replaceAll('_', ' ')}</span>
    {page.problems.length > 0 && <p className="text-xs text-amber-800">{page.problems.join('; ')}</p>}
   </li>)}</ol>
  </div>}

  {phase?.rounds && <RoundHistory rounds={phase.rounds}/>}
  {phase?.page_changes && <details className="rounded-lg border border-slate-200 p-3 text-sm">
   <summary className="cursor-pointer font-medium">Changes from version {phase.page_changes.previous} ({phase.page_changes.changes.length} pages)</summary>
   {phase.page_changes.changes.length === 0 && <p className="mt-2 text-slate-600">No page content changed.</p>}
   {phase.page_changes.changes.map(change => <div key={change.key} className="mt-2"><p>{change.key}: {change.change}</p><pre className="overflow-auto whitespace-pre-wrap text-xs">{change.diff}</pre></div>)}
  </details>}

  {files.length > 0 && <div>
   <h3 className="text-sm font-medium text-slate-800">Draft files</h3>
   <ul className="mt-2 flex flex-wrap gap-2">{files.map(file =>
    <li key={file.name}><a className="inline-block rounded-md border border-slate-200 px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-50"
     href={`/api/rooms/${roomId}/deal-documents/files/${file.name}`} target="_blank" rel="noreferrer">{file.label}<span className="ml-2 text-xs text-slate-500">{when(file.updated)}</span></a></li>)}</ul>
  </div>}

  {earlier.length > 0 && <details open={['queued', 'running'].includes(state)} className="rounded-lg border border-slate-200 p-3">
   <summary className="cursor-pointer text-sm font-medium text-slate-800">Earlier versions ({earlier.length})</summary>
   {['queued', 'running'].includes(state) && <p className="mt-2 text-sm text-slate-600">The newest finished version stays here to read while this one is generated.</p>}
   <ul className="mt-2 divide-y divide-slate-100 text-sm">{earlier.map((version, index) => <li key={version.version} className="py-2">
    <p className="text-xs text-slate-600">{when(version.updated)}{index === 0 ? ' · latest finished' : ''}</p>
    {version.rounds && version.rounds.length > 0 && <RoundHistory rounds={version.rounds}/>}
    <ul className="mt-1 flex flex-wrap gap-2">{version.files.filter(file => file.phase === phaseKey).map(file =>
     <li key={file.name}><a className="inline-block rounded-md border border-slate-200 px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-50"
      href={`/api/rooms/${roomId}/deal-documents/files/${file.name}?version=${version.version}`} target="_blank" rel="noreferrer">{file.label}</a></li>)}</ul>
   </li>)}</ul>
  </details>}

  {phase && phase.required_approvals.length > 0 && !['not_started', 'queued', 'running'].includes(state) && <div className="rounded-lg border border-slate-200 p-3">
   <h3 className="text-sm font-medium text-slate-800">Approvals</h3>
   <ul className="mt-2 space-y-2 text-sm">{phase.required_approvals.map(kind => {
    const record = phase.approvals[kind];
    return <li key={kind}>
     <span className="font-medium">{approvalNames[kind] ?? kind}:</span>{' '}
     {record ? <>{record.decision === 'changes_required' ? 'changes required' : 'approved'} by {record.by} on {when(record.at)}
      {!record.current && <span className="text-amber-800"> — the output changed since; approve again</span>}
      {record.notes && <span className="block text-xs text-slate-600">“{record.notes.slice(0, 400)}{record.notes.length > 400 ? '…' : ''}”</span>}</>
      : <span className="text-slate-500">pending</span>}
    </li>;
   })}</ul>
   {status.is_owner && state !== 'failed' && <div className="mt-3">
    <label className="block text-xs text-slate-600" htmlFor={`notes-${phaseKey}`}>Your review notes{phaseKey === 'facts' ? ' (passed to the memo writer as binding instructions)' : ''}</label>
    <textarea id={`notes-${phaseKey}`} value={notes} onChange={event => setNotes(event.target.value)} rows={3}
     className="mt-1 w-full rounded-md border border-slate-300 p-2 text-sm" maxLength={8000}/>
    <button type="button" disabled={busy} onClick={() => act('approve', {notes})}
     className="mt-2 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Approve this exact version</button>
   </div>}
  </div>}

  {phase && phase.steps.length > 0 && <details open={['queued', 'running'].includes(state)} className="rounded-lg border border-slate-200 p-3">
   <summary className="cursor-pointer text-sm font-medium text-slate-800">Steps ({phase.steps_done}/{phase.steps_total}){phase.interruptions ? ` · resumed ${phase.interruptions}×` : ''}</summary>
   <ol className="mt-2 divide-y divide-slate-100 text-sm">{phase.steps.map(step => {
    const seconds = step.state === 'running' && step.started ? now - step.started : step.seconds;
    return <li key={step.key} className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
     <span className={step.state === 'pending' ? 'text-slate-400' : step.state === 'failed' ? 'text-rose-700' : 'text-slate-800'}>
      {step.state === 'done' ? '✓' : step.state === 'running' ? '●' : step.state === 'failed' ? '✕' : '○'} {step.label}
      {step.detail && <span className="ml-2 text-xs text-slate-500">{step.detail}</span>}</span>
     {step.state === 'running' && phase.timings?.[step.kind] && <span className="text-xs text-slate-500">Similar steps: {duration(phase.timings[step.kind].mean_seconds)} ({phase.timings[step.kind].samples} measured; {phase.timings[step.kind].basis})</span>}
     <span className="text-xs tabular-nums text-slate-500">{step.cached ? 'reused' : seconds ? duration(seconds) : ''}</span>
    </li>;
   })}</ol>
  </details>}

  {phaseKey === 'memo' && ['needs_approval', 'approved'].includes(state) && <MemoReview roomId={roomId} qualified={status.qualified_compliance_reviewer}/>}
 </div>;
}

function RoundHistory({rounds}: {rounds: Round[]}) {
 return <details className="rounded-lg border border-slate-200 p-3 text-sm">
  <summary className="cursor-pointer font-medium">Scores and changes by round</summary>
  {rounds.map(round => <div key={round.round} className="mt-3">
   <p className="font-medium">Round {round.round}</p>
   <ul className="mt-1 text-xs text-slate-700">{Object.entries(round.scores).map(([key, score]) => <li key={key}>{key}: {score === null ? 'not scored' : `${score}/100`}{round.dropped.includes(key) ? ' · candidate discarded' : round.round > 0 && round.kept.includes(key) ? ' · improved version kept' : ''}</li>)}</ul>
   {Object.entries(round.changes ?? {}).map(([key, change]) => <details key={key} className="mt-2 text-xs">
    <summary className="cursor-pointer">{key}: {change.before_score ?? 'not scored'} → {change.candidate_score ?? 'failed'} · {change.kept ? 'kept' : 'discarded'}</summary>
    <p>{change.reason}</p><pre className="mt-1 overflow-auto whitespace-pre-wrap">{change.diff || 'No prose changed.'}</pre>
   </details>)}
  </div>)}
 </details>;
}

function MemoReview({roomId, qualified}: {roomId: string; qualified: boolean}) {
 const client = useQueryClient();
 const memo = useQuery({queryKey: ['deal-documents-memo', roomId], queryFn: () => api.get<MemoView>(`/api/rooms/${roomId}/deal-documents/memo`)});
 const [decision, setDecision] = useState<'approved' | 'changes_required'>('changes_required');
 const [notes, setNotes] = useState('');
 const [waivers, setWaivers] = useState<Record<string, string>>({});
 const signoff = useMutation({
  mutationFn: () => api.post(`/api/rooms/${roomId}/deal-documents/memo/compliance-signoff`, {decision, notes,
   waivers: Object.entries(waivers).filter(([, reason]) => reason.trim()).map(([key, reason]) => ({key, reason}))}),
  onSuccess: () => client.invalidateQueries({queryKey: ['deal-documents', roomId]}),
 });
 if (memo.isLoading) return <p className="text-sm text-slate-500">Loading the memorandum…</p>;
 if (memo.error || !memo.data) return <p role="alert" className="text-sm text-rose-700">{memo.error?.message ?? 'Memorandum unavailable'}</p>;
 const {sections, review, compliance} = memo.data;
 const issuesFor = (key: string) => review?.issues.filter(issue => issue.section === key && issue.quote_verified) ?? [];
 return <div className="space-y-4">
  {compliance && <div className="rounded-lg border border-slate-200 p-3">
   <h3 className="text-sm font-medium text-slate-800">Compliance gate</h3>
   <p className="mt-1 text-xs text-slate-600">Code-run checks and questions for counsel, assessed {compliance.assessed_on}. Not legal advice. External release needs a qualified reviewer to resolve or waive every failing item.</p>
   <ul className="mt-2 space-y-1.5 text-sm">{compliance.checks.map(check => <li key={check.key}>
    <span className={`mr-2 inline-block w-20 rounded px-1.5 text-center text-xs font-semibold ${check.status === 'pass' ? 'bg-emerald-100 text-emerald-800' : check.status === 'fail' ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-900'}`}>{check.status === 'counsel' ? 'COUNSEL' : check.status.toUpperCase()}</span>
    <span className="font-medium">{check.title}</span> <span className="text-slate-600">— {check.detail}</span>
    {check.evidence.length > 0 && <ul className="ml-24 mt-1 list-disc text-xs text-slate-600">{check.evidence.map((item, i) => <li key={i}>{item}</li>)}</ul>}
    {qualified && check.status === 'fail' && <input aria-label={`Waiver reason for ${check.title}`} placeholder="Waiver reason (leave empty to require a fix)"
     className="ml-24 mt-1 w-[calc(100%-6rem)] rounded border border-slate-300 p-1 text-xs" value={waivers[check.key] ?? ''}
     onChange={event => setWaivers({...waivers, [check.key]: event.target.value})}/>}
   </li>)}</ul>
   {qualified ? <div className="mt-3 space-y-2">
    <select value={decision} onChange={event => setDecision(event.target.value as 'approved' | 'changes_required')} className="rounded border border-slate-300 p-1 text-sm">
     <option value="changes_required">Changes required</option><option value="approved">Approve for investor distribution</option></select>
    <textarea value={notes} onChange={event => setNotes(event.target.value)} rows={3} placeholder="Sign-off notes (required)"
     className="w-full rounded-md border border-slate-300 p-2 text-sm"/>
    <button type="button" disabled={signoff.isPending || notes.trim().length < 10} onClick={() => signoff.mutate()}
     className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Record compliance sign-off</button>
    {signoff.error && <p role="alert" className="text-sm text-rose-700">{signoff.error.message}</p>}
   </div> : <p className="mt-3 text-xs text-slate-600">Compliance sign-off is recorded by an operator-provisioned qualified compliance reviewer account, not by the sandbox owner or the model.</p>}
  </div>}

  {review && (review.overall || review.failures.length > 0) && <div className="rounded-lg border border-slate-200 p-3 text-sm">
   <h3 className="font-medium text-slate-800">Investment-committee reviewer</h3>
   {review.overall && <p className="mt-1 text-slate-700">{review.overall}</p>}
   {review.failures.length > 0 && <p className="mt-1 text-xs text-rose-700">Reviewer steps that failed: {review.failures.join('; ')}</p>}
  </div>}

  <div className="space-y-3">{sections.map(section => {
   const issues = issuesFor(section.section);
   return <details key={section.section} className="rounded-lg border border-slate-200 p-3">
    <summary className="cursor-pointer text-sm"><span className="font-medium text-slate-900">{section.title}</span>
     <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${section.state === 'valid' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-900'}`}>{section.state === 'valid' ? 'passes code checks' : `${section.problems.length} open problems`}</span>
     {section.revised_from_review && <span className="ml-2 text-xs text-slate-500">revised after review</span>}
     {issues.length > 0 && <span className="ml-2 text-xs text-slate-500">{issues.length} reviewer notes</span>}</summary>
    <div className="mt-3 space-y-3 text-sm leading-6 text-slate-800">
     {section.paragraphs.map((paragraph, i) => <p key={i}>{paragraph.text} <span className="text-xs text-slate-400">[{paragraph.cites.join(', ')}]</span></p>)}
     {section.calculations.length > 0 && <ul className="text-xs text-slate-600">{section.calculations.map(calc =>
      <li key={calc.id}>Computed by code: {calc.label} = <span className="font-medium">{calc.text}</span></li>)}</ul>}
     {section.problems.length > 0 && <ul className="list-disc pl-5 text-xs text-amber-900">{section.problems.map((problem, i) => <li key={i}>{problem}</li>)}</ul>}
     {section.removed_sentences.length > 0 && <details className="text-xs text-slate-600">
      <summary className="cursor-pointer">{section.removed_sentences.length} sentence(s) removed by code checks</summary>
      <ul className="mt-1 list-disc space-y-1 pl-5">{section.removed_sentences.map((item, i) =>
       <li key={i}><span className="line-through">{item.sentence}</span> — {item.reasons.join('; ')}</li>)}</ul>
     </details>}
     {issues.length > 0 && <ul className="list-disc pl-5 text-xs text-slate-600">{issues.map((issue, i) =>
      <li key={i} className={issue.unverified_number ? 'text-slate-400' : ''}>[{issue.reviewer.replace('_', ' ')}] “{issue.quote}” — {issue.problem ?? issue.type ?? issue.area}: {issue.fix ?? issue.change ?? issue.action}{issue.unverified_number && ' (not applied: proposes a figure found in no source or calculation)'}</li>)}</ul>}
    </div>
   </details>;
  })}</div>
 </div>;
}
