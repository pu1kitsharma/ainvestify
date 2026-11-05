import {useEffect, useRef, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {api} from '../api/client';

type Link = {evidence_id: string; evidence_version: string};
type Evidence = Link & {statement: string; document: string; location: string; basis?: string; respondent?: string; approved_for_scope: boolean};
type Request = {id: string; basis?: string; version: number; actor: string; issue: string; required_record: string; rationale: string; origin: string; owner: string; due_date: string | null; priority: string; status: string; blocks: string[]; source_evidence: Evidence[]; accepted_evidence: Link[]; acceptance_note: string; reopened_reason?: string; management_response?: {text: string; by: string}};
type Event = {id: string; version: number; actor: string; counterparty: string; stage: string; state: string; date: string; owner: string; next_action: string; next_date: string | null; evidence: Link[]; artifact: {phase: string; sha256: string} | null; review_note: string; current: boolean; elapsed_days: number};
type Answer = {id: string; version: number; scope: string; status: string; actor: string; at: number; current: boolean; parts: {question: string}[]; claims: {text: string; attribution: string; document: string; location: string; context: Record<string, string>}[]; residual: {question: string; required_record: string}[]; conflicts: Evidence[][]; evidence: Evidence[]; related_evidence: Evidence[]; approval_note?: string; failure?: string};
type Overview = {is_owner: boolean; requests: Request[]; prioritized: Request[]; answers: Answer[]; tracker: {
 mandate: {purpose: string; signed_at: string} | null; production: Record<string, {state: string}>;
 approved_drafts: {phase: string; sha256: string}[];
 counterparties: {id: string; name: string; stage: string; timeline: Event[]; outstanding_answers: string[]}[];
 blockers: Request[]; deadlines: {id: string; kind: string; owner: string; date: string; action: string; overdue: boolean}[];
 weekly_events: Event[]; summary: {events_recorded_this_week: number; open_requests: number; overdue_actions: number}}};
const input = 'max-w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm disabled:opacity-50';
const button = 'rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50';
const labels: Record<string, string> = {
 open: 'Needed', in_progress: 'Being prepared', supplied: 'Ready to review', resolved: 'Complete',
 blocker: 'Blocking progress', requirement: 'Team request', finding: 'Document review', question: 'Investor question',
 company_claim: 'Company statement', projection: 'Company forecast', target: 'Company target', 'source record': 'Source document',
 'counterparty answer': 'Investor answer', 'Unanswered Q&A part': 'A question still needs an answer',
 draft: 'Needs approval', input_needed: 'More information needed', approved: 'Approved', stale: 'Sources changed — review again',
 contact_recorded: 'Contact recorded', nda_executed: 'Confidentiality agreement signed', materials_reviewed: 'Documents reviewed',
 meeting: 'Investor meeting', indicative_offer: 'Initial offer', binding_commitment: 'Binding commitment', closed: 'Raise completed',
 unconfirmed: 'No confirmed stage', planned: 'Planned', occurred: 'Completed', cancelled: 'Cancelled',
 facts: 'Fact base', memo: 'Investment memorandum', decks: 'Pitch decks', needs_approval: 'Needs approval',
};
const label = (text: string) => labels[text] ?? text.replaceAll('_', ' ');
const tones: Record<string, string> = {
 open: 'bg-amber-100 text-amber-900', in_progress: 'bg-indigo-100 text-indigo-800', supplied: 'bg-indigo-100 text-indigo-800',
 resolved: 'bg-emerald-100 text-emerald-800', approved: 'bg-emerald-100 text-emerald-800',
 draft: 'bg-amber-100 text-amber-900', input_needed: 'bg-amber-100 text-amber-900', stale: 'bg-rose-100 text-rose-800',
};
const link = (e: Link): Link => ({evidence_id: e.evidence_id, evidence_version: e.evidence_version});
type Send = (path: string, body: unknown, confirmation: string) => Promise<boolean>;

function Badge({status}: {status: string}) {
 return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tones[status] ?? 'bg-slate-100 text-slate-700'}`}>{label(status)}</span>;
}

function EvidencePicker({evidence, selected, onChange}: {evidence: Evidence[]; selected: Link[]; onChange: (v: Link[]) => void}) {
 return <fieldset className="min-w-0 space-y-2"><legend className="text-sm font-medium">Supporting sources</legend>
  {!evidence.some(e => e.approved_for_scope) && <p className="text-sm text-slate-500">Approve the fact base in Investor documents, or allow a company response under Investor questions → Choose sources for answers.</p>}
  {selected.filter(ref => !evidence.some(e => e.approved_for_scope && e.evidence_id === ref.evidence_id && e.evidence_version === ref.evidence_version)).map(ref => <label key={`${ref.evidence_id}-${ref.evidence_version}`} className="block text-sm text-amber-800"><input type="checkbox" checked onChange={() => onChange(selected.filter(e => e.evidence_id !== ref.evidence_id || e.evidence_version !== ref.evidence_version))}/> A previously selected source changed or is unavailable. Uncheck it and choose a current source.</label>)}
  {evidence.filter(e => e.approved_for_scope).map(e => <label key={e.evidence_id} className="block text-sm">
   <input type="checkbox" checked={selected.some(s => s.evidence_id === e.evidence_id && s.evidence_version === e.evidence_version)} onChange={event => onChange(event.target.checked ? [...selected, link(e)] : selected.filter(s => s.evidence_id !== e.evidence_id))}/>
   {' '}{e.statement} <span className="text-slate-500">({e.document}, {e.location}{e.basis ? `; ${label(e.basis)}` : ''})</span>
  </label>)}
 </fieldset>;
}

function RequestEditor({initial, evidence, send, done}: {initial?: Request; evidence: Evidence[]; send: Send; done: () => void}) {
 const [form, setForm] = useState(initial ?? {issue: '', required_record: '', rationale: '', origin: 'requirement', owner: '', due_date: null as string | null, priority: 'high', status: 'open', blocks: [] as string[], accepted_evidence: [] as Link[], acceptance_note: ''});
 return <form className="space-y-3 rounded-lg border border-indigo-200 bg-indigo-50/30 p-3" onSubmit={async event => {event.preventDefault(); if (await send(initial ? `/requests/${initial.id}` : '/requests', {
  issue: form.issue, required_record: form.required_record, rationale: form.rationale, origin: form.origin, owner: form.owner,
  due_date: form.due_date, priority: form.priority, status: form.status, blocks: form.blocks.filter(v => v.trim()),
  accepted_evidence: form.accepted_evidence, acceptance_note: form.acceptance_note, expected_version: initial?.version ?? 0}, initial ? 'Request updated.' : 'Request added.')) done();}}>
  <label className="block text-sm">What question or concern does this address? <textarea className={`${input} block w-full`} required value={form.issue} onChange={e => setForm({...form, issue: e.target.value})}/></label>
  <label className="block text-sm">What do we need from the company? <textarea className={`${input} block w-full`} required value={form.required_record} onChange={e => setForm({...form, required_record: e.target.value})}/></label>
  <label className="block text-sm">Why it matters <input className={`${input} block w-full`} value={form.rationale} onChange={e => setForm({...form, rationale: e.target.value})}/></label>
  <div className="grid gap-3 sm:grid-cols-2">
   <label className="min-w-0 text-sm">Who is responsible? <input className={`${input} block w-full`} value={form.owner} onChange={e => setForm({...form, owner: e.target.value})}/></label>
   <label className="min-w-0 text-sm">Due date <input className={`${input} block w-full`} type="date" value={form.due_date ?? ''} onChange={e => setForm({...form, due_date: e.target.value || null})}/></label>
   <label className="min-w-0 text-sm">Priority <select className={`${input} block w-full`} value={form.priority} onChange={e => setForm({...form, priority: e.target.value})}>{['blocker', 'high', 'medium', 'low'].map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label>
   <label className="min-w-0 text-sm">Status <select className={`${input} block w-full`} value={form.status} onChange={e => setForm({...form, status: e.target.value})}>{['open', 'in_progress', 'supplied', 'resolved'].map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label>
  </div>
  <label className="block text-sm">What is waiting on this? (one item per line)<textarea className={`${input} block w-full`} value={form.blocks.join('\n')} onChange={e => setForm({...form, blocks: e.target.value.split('\n')})}/></label>
  <p className="text-xs text-slate-500">To mark a request complete, select supporting sources and explain why they satisfy it.</p>
  <EvidencePicker evidence={evidence} selected={form.accepted_evidence} onChange={v => setForm({...form, accepted_evidence: v})}/>
  <label className="block text-sm">Why can this request be marked complete? <textarea required={form.status === 'resolved'} className={`${input} block w-full`} value={form.acceptance_note} onChange={e => setForm({...form, acceptance_note: e.target.value})}/></label>
  <details className="text-sm"><summary className="cursor-pointer">Details</summary><label className="mt-2 block">Where this request came from <select className={`${input} block w-full`} value={form.origin} onChange={e => setForm({...form, origin: e.target.value})}>{['requirement', 'finding', 'question'].map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label></details>
  <div className="flex flex-wrap gap-2"><button className={button}>Save request</button><button type="button" className={input} onClick={done}>Cancel</button></div>
 </form>;
}

function EventEditor({initial, evidence, drafts, investors, send, done}: {initial?: Event; evidence: Evidence[]; drafts: {phase: string; sha256: string}[]; investors: {id: string; name: string}[]; send: Send; done: () => void}) {
 const [form, setForm] = useState(initial ?? {counterparty: '', stage: 'contact_recorded', state: 'planned', date: '', owner: '', next_action: '', next_date: null as string | null, evidence: [] as Link[], review_note: '', artifact: null as {phase: string; sha256: string} | null});
 const knownInvestor = investors.some(i => i.id === form.counterparty);
 return <form className="space-y-3 rounded-lg border border-indigo-200 bg-indigo-50/30 p-3" onSubmit={async e => {e.preventDefault(); if (await send(initial ? `/events/${initial.id}` : '/events', {
  counterparty: form.counterparty, stage: form.stage, state: form.state, date: form.date, owner: form.owner, next_action: form.next_action,
  next_date: form.next_date, evidence: form.evidence, review_note: form.review_note, artifact: form.artifact, expected_version: initial?.version ?? 0}, 'Investor progress saved. Nothing was sent.')) done();}}>
  <div className="grid gap-3 sm:grid-cols-2">
   <label className="min-w-0 text-sm">Investor<select className={`${input} block w-full`} value={knownInvestor ? form.counterparty : ''} onChange={e => setForm({...form, counterparty: e.target.value})}><option value="">Choose an investor or enter a reference below</option>{investors.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}</select></label>
   <label className="min-w-0 text-sm">Stage <select className={`${input} block w-full`} value={form.stage} onChange={e => setForm({...form, stage: e.target.value})}>{['contact_recorded', 'nda_executed', 'materials_reviewed', 'meeting', 'indicative_offer', 'binding_commitment', 'closed'].map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label>
   <label className="min-w-0 text-sm">Has it happened? <select className={`${input} block w-full`} value={form.state} onChange={e => setForm({...form, state: e.target.value})}>{['planned', 'occurred', 'cancelled'].map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label>
   <label className="min-w-0 text-sm">Date <input required type="date" className={`${input} block w-full`} value={form.date} onChange={e => setForm({...form, date: e.target.value})}/></label>
   <label className="min-w-0 text-sm">Who is responsible? <input required className={`${input} block w-full`} value={form.owner} onChange={e => setForm({...form, owner: e.target.value})}/></label>
  </div>
  {!knownInvestor && <label className="block text-sm">Investor reference<input required maxLength={200} className={`${input} block w-full`} value={form.counterparty} onChange={e => setForm({...form, counterparty: e.target.value})}/><span className="text-xs text-slate-500">Enter a unique reference for this investor; use it again when drafting their answers.</span></label>}
  <label className="block text-sm">What happens next? <input className={`${input} block w-full`} value={form.next_action} onChange={e => setForm({...form, next_action: e.target.value})}/></label>
  <label className="block text-sm">Next action due date <input type="date" className={input} value={form.next_date ?? ''} onChange={e => setForm({...form, next_date: e.target.value || null})}/></label>
  <EvidencePicker evidence={evidence} selected={form.evidence} onChange={v => setForm({...form, evidence: v})}/>
  <label className="block text-sm">Approved document reviewed <select className={input} value={form.artifact?.sha256 ?? ''} onChange={e => setForm({...form, artifact: drafts.find(d => d.sha256 === e.target.value) ?? null})}><option value="">No document linked</option>{drafts.map(d => <option key={d.sha256} value={d.sha256}>Approved {label(d.phase)} ({d.sha256.slice(0, 8)})</option>)}</select></label>
  <label className="block text-sm">How do the sources confirm this progress? <textarea required={form.state === 'occurred'} className={`${input} block w-full`} value={form.review_note} onChange={e => setForm({...form, review_note: e.target.value})}/></label>
  <p className="text-xs text-slate-500">Recording progress does not share documents or send a message.</p>
  <div className="flex flex-wrap gap-2"><button className={button}>Save investor progress</button><button className={input} type="button" onClick={done}>Cancel</button></div>
 </form>;
}

function AnswerReview({answer, recipient, canEdit, send}: {answer: Answer; recipient: string; canEdit: boolean; send: Send}) {
 const [note, setNote] = useState('');
 const [ack, setAck] = useState(false);
 return <article className="space-y-3 rounded-lg border border-slate-200 p-3">
  <div className="flex flex-wrap items-start justify-between gap-2"><h4 className="min-w-0 font-medium">{answer.parts.map(p => p.question).join(' / ')}</h4><Badge status={answer.status}/></div>
  <p className="text-xs text-slate-500">For: {recipient}</p>
  {answer.claims.map((claim, i) => <blockquote key={i} className="border-l-2 border-indigo-200 pl-3 text-sm"><p>{claim.text}</p><p className="text-xs text-slate-500">{label(claim.attribution)} — {claim.document}, {claim.location} · {Object.values(claim.context).map(value => label(String(value))).join(' · ')}</p></blockquote>)}
  <details className="text-sm"><summary className="cursor-pointer text-slate-600">Details</summary><div className="mt-2 space-y-2">
   <p className="text-xs text-slate-500">Investor reference: {answer.scope || 'Team review'} · Revision {answer.version} · {answer.actor} · {new Date(answer.at * 1000).toLocaleString()}</p>
   <p className="font-medium">Sources used for this answer</p>{answer.evidence.map(e => <p key={e.evidence_id} className="break-all text-xs">{e.document}, {e.location}: {e.statement} [{e.evidence_id} / {e.evidence_version}]</p>)}
   <p className="font-medium">Other sources to check for disagreements</p>{answer.related_evidence.map(e => <p key={e.evidence_id}>{e.statement} ({e.respondent || (e.basis ? label(e.basis) : '')}; {e.document}, {e.location})</p>)}
  </div></details>
  {answer.residual.map((part, i) => <p key={i} className="text-sm text-amber-800">Still needed: {part.question} Required: {part.required_record}. Added to the company request list above.</p>)}
  {answer.status === 'stale' && <p className="text-sm text-amber-800">Supporting sources changed. Enter the question above and draft a new answer before approving it.</p>}
  {answer.failure && <p className="text-sm text-amber-800">{answer.failure}</p>}
  {answer.conflicts.map((group, i) => <div key={i} className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><strong>Sources disagree — still unresolved</strong>{group.map(e => <p key={e.evidence_id}>{e.statement} ({e.document}, {e.location}; {e.basis})</p>)}</div>)}
  {answer.approval_note && <p className="text-sm">Approval note: {answer.approval_note}</p>}
  {canEdit && answer.status === 'draft' && <form className="space-y-2" onSubmit={async e => {e.preventDefault(); await send(`/answers/${answer.id}/approve`, {expected_version: answer.version, note, acknowledge_conflicts: ack}, 'Answer approved. Nothing was sent.');}}>
   <label className="block text-sm">Your review note: check every answer against its sources <textarea required className={`${input} block w-full`} value={note} onChange={e => setNote(e.target.value)}/></label>
   {!!answer.conflicts.length && <label className="block text-sm"><input type="checkbox" required checked={ack} onChange={e => setAck(e.target.checked)}/> I reviewed every conflicting source; the disagreement remains visible.</label>}
   <button className={button}>Approve answer</button>
  </form>}
 </article>;
}

// Generated request text carries a record-type prefix and table-cell references; the page shows the question itself.
const PREFIX = /^(Reconciliation schedule and underlying source records for|Dated current-period source records for|Reviewed disclosure and supporting records for|Source record or attributed response for):\s*/i;
const CELL_NOTE = /\s*\((?=[^)]*\b[A-Z]{2,}-p\d)[^)]*\)?/g;
const CELL = /\b[A-Z]{2,}-p\d+(?:\.[A-Za-z0-9]+)*|\br\d+c\d+\b/g;

export function plainQuestion(r: Pick<Request, 'issue' | 'basis' | 'blocks'>) {
 if (r.basis === 'requirement') return {title: `${label(r.blocks[0] ?? 'analysis')} page`, detail: `Needs ${r.issue.replace(PREFIX, '')}`};
 const text = r.issue.replace(PREFIX, '').replace(CELL_NOTE, '').replace(CELL, 'a table figure').replace(/\s+/g, ' ').trim();
 const split = text.match(/^([^:]{3,70}):\s+(.+)$/);
 const [title, detail] = split ? [split[1], split[2]] : [text, ''];
 return {title: title.charAt(0).toUpperCase() + title.slice(1), detail};
}

type Group = {key: string; title: string; why: string; match: (r: Request) => boolean};
const GROUPS: Group[] = [
 {key: 'disclosure', title: 'Required before the memorandum can be shared',
  why: 'Private-placement rules (in India, Companies Act s.42 and SEBI) and investors expect these disclosures. The memorandum stays a draft until the company answers them.',
  match: r => r.basis === 'missing_disclosure' || r.priority === 'blocker'},
 {key: 'numbers', title: 'Numbers that don’t reconcile',
  why: 'The company’s own figures disagree with each other. An investor will notice, so the company should explain or correct them.',
  match: r => r.basis === 'calculation' || /fail a calculation/i.test(r.basis ?? '')},
 {key: 'age', title: 'Out-of-date information',
  why: 'The latest figures are old. Investors will ask for current numbers.',
  match: r => r.basis === 'information_age'},
 {key: 'other', title: 'Other open questions',
  why: 'Points found while reviewing the documents that an investor is likely to raise.',
  match: r => r.basis !== 'requirement'},
 {key: 'optional', title: 'Optional: data for extra analysis pages',
  why: 'Not required. With this data the memorandum can add pages such as scenarios and unit economics.',
  match: () => true},
];

function grouped(requests: Request[]) {
 const taken = new Set<string>();
 return GROUPS.map(group => {
  const items = requests.filter(r => !taken.has(r.id) && group.match(r));
  items.forEach(r => taken.add(r.id));
  return {...group, items};
 }).filter(group => group.items.length);
}

function checklist(company: string, groups: ReturnType<typeof grouped>) {
 let n = 0;
 return [`Questions for ${company}`, '',
  ...groups.flatMap(group => [group.title, ...group.items.map(r => {const q = plainQuestion(r); return `${++n}. ${q.title}${q.detail ? ` — ${q.detail}` : ''}`;}), ''])].join('\n');
}

export default function Diligence({roomId}: {roomId: string}) {
 const client = useQueryClient(), root = `/api/rooms/${roomId}/diligence`, key = ['diligence', roomId];
 const overview = useQuery({queryKey: key, queryFn: () => api.get<Overview>(root), refetchInterval: 30000});
 const evidence = useQuery({queryKey: ['diligence-evidence', roomId], queryFn: () => api.get<Evidence[]>(`${root}/evidence?candidates=true`), refetchInterval: 30000});
 const [edit, setEdit] = useState<Request | 'new' | null>(null), [eventEdit, setEventEdit] = useState<Event | 'new' | null>(null);
 const [scope, setScope] = useState(''), [question, setQuestion] = useState('');
 const scopedEvidence = useQuery({queryKey: ['diligence-scope-evidence', roomId, scope], queryFn: () => api.get<Evidence[]>(`${root}/evidence?scope=${encodeURIComponent(scope)}`), enabled: !!scope});
 const [history, setHistory] = useState(false), [onlyOpen, setOnlyOpen] = useState(true);
 const [confirmation, setConfirmation] = useState(''), [copyText, setCopyText] = useState('');
 const synced = useRef(false);
 const revisions = useQuery({queryKey: ['diligence-history', roomId], queryFn: () => api.get<Answer[]>(`${root}/history/answer`), enabled: history});
 const mutation = useMutation({mutationFn: ({path, body}: {path: string; body: unknown}) => api.post<{status?: string}>(root + path, body), onSuccess: async () => {
  await Promise.all([client.invalidateQueries({queryKey: key}), client.invalidateQueries({queryKey: ['diligence-evidence', roomId]}), client.invalidateQueries({queryKey: ['diligence-history', roomId]}), client.invalidateQueries({queryKey: ['diligence-scope-evidence', roomId]})]);
 }});
 const send: Send = async (path, body, message) => {
  setConfirmation('');
  try {
   const result = await mutation.mutateAsync({path, body});
   setConfirmation(path === '/answers' && result?.status === 'input_needed'
    ? 'The documents could not answer this. It was added to the list of questions for the company.' : message);
   return true;
  } catch {return false;}
 };
 // The list is worked out from the documents; an owner should not have to press a button to see it.
 useEffect(() => {
  if (synced.current || !overview.data?.is_owner || overview.data.requests.length) return;
  synced.current = true;
  void send('/sync', undefined, 'Questions worked out from the latest documents.');
 }, [overview.data]);
 if (overview.isLoading) return <p role="status" className="text-sm text-slate-500">Loading investor diligence…</p>;
 if (overview.error) return <p role="alert" className="text-sm text-rose-700">Could not load investor diligence: {overview.error.message}</p>;
 if (!overview.data) return null;
 const data = overview.data, catalog = evidence.data ?? [];
 const open = data.requests.filter(r => r.status !== 'resolved');
 const groups = grouped(data.requests.filter(r => !onlyOpen || r.status !== 'resolved'));
 const count = (k: string) => grouped(open).find(g => g.key === k)?.items.length ?? 0;
 const recipient = (a: Answer) => data.tracker.counterparties.find(c => c.id === a.scope)?.name || a.scope || 'Team review';
 const copy = async () => {
  const text = checklist('the company', grouped(open));
  try {await navigator.clipboard.writeText(text); setCopyText(''); setConfirmation('Checklist copied. Paste it into your message to the founder; nothing was sent.');}
  catch {setCopyText(text);}
 };

 return <section aria-label="Investor diligence" className="mb-6 min-w-0 space-y-5 break-words rounded-xl border border-slate-200 bg-white p-3 sm:p-5">
  <div>
   <h2 className="text-lg font-semibold text-slate-900">Investor diligence</h2>
   <p className="mt-1 max-w-3xl text-sm text-slate-600">What an investor will ask before investing, worked out from the company’s documents. Send the list to the founder, and ask the AI anything about the company. Nothing is sent automatically.</p>
  </div>
  {mutation.error && <p role="alert" className="text-sm text-rose-700">That didn’t work: {mutation.error.message}</p>}
  {confirmation && <p role="status" className="sticky top-2 z-10 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{confirmation}</p>}
  {mutation.isPending && <p role="status" className="text-sm text-indigo-700">Working…</p>}

  <div className="grid gap-2 text-sm sm:grid-cols-3">
   <div className="rounded-lg bg-slate-50 p-3"><p className="text-2xl font-semibold text-slate-900">{open.length}</p><p className="text-slate-600">open questions for the company</p></div>
   <div className="rounded-lg bg-rose-50 p-3"><p className="text-2xl font-semibold text-rose-800">{count('disclosure')}</p><p className="text-rose-800">required disclosures missing</p></div>
   <div className="rounded-lg bg-amber-50 p-3"><p className="text-2xl font-semibold text-amber-900">{count('numbers')}</p><p className="text-amber-900">figures that don’t reconcile</p></div>
  </div>

  <fieldset disabled={mutation.isPending} className="min-w-0 space-y-5">
  <section aria-label="Questions for the company" className="space-y-3">
   <div className="flex flex-wrap items-end justify-between gap-2">
    <div><h3 className="font-semibold">1. Questions for the company</h3><p className="mt-1 text-sm text-slate-500">Most important first. Each group says why investors care.</p></div>
    <div className="flex flex-wrap gap-2">
     {open.length > 0 && <button className={button} onClick={() => void copy()}>Copy checklist for the founder</button>}
     {data.is_owner && <button className={input} onClick={() => void send('/sync', undefined, 'Questions re-checked against the latest documents.')}>Re-check documents</button>}
     {data.is_owner && <button className={input} onClick={() => setEdit('new')}>Add a question</button>}
    </div>
   </div>
   {copyText && <textarea readOnly aria-label="Checklist to copy" className={`${input} block h-40 w-full`} value={copyText}/>}
   {edit && <RequestEditor key={edit === 'new' ? 'new' : `${edit.id}-${edit.version}`} initial={edit === 'new' ? undefined : edit} evidence={catalog} send={send} done={() => setEdit(null)}/>}
   {!groups.length && <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{data.requests.length ? 'Every question has been answered.' : 'No questions yet. They appear once the fact base has been generated in Investor documents.'}</p>}
   {groups.map(group => <details key={group.key} open={!['other', 'optional'].includes(group.key)} className="rounded-lg border border-slate-200 p-3 sm:p-4">
    <summary className="cursor-pointer"><span className="font-medium">{group.title}</span> <span className="text-sm text-slate-500">({group.items.length})</span></summary>
    <p className="mt-2 text-sm text-slate-600">{group.why}</p>
    <ol className="mt-3 space-y-2">{group.items.map(r => {const q = plainQuestion(r); return <li id={`diligence-request-${r.id}`} key={r.id} className="rounded-lg bg-slate-50 p-3 text-sm">
     <div className="flex flex-wrap items-start justify-between gap-2"><p className="min-w-0 font-medium text-slate-900">{q.title}</p><Badge status={r.status}/></div>
     {q.detail && <p className="mt-1 text-slate-700">{q.detail}</p>}
     {r.management_response && <p className="mt-1 text-slate-700">Company’s answer: {r.management_response.text}</p>}
     {r.reopened_reason && <p className="mt-1 text-amber-800">Needs another look: the documents behind the answer changed.</p>}
     <div className="mt-2 flex flex-wrap items-center gap-3">
      {data.is_owner && <button className="text-sm font-medium text-indigo-700 underline" onClick={() => setEdit(r)}>{r.status === 'resolved' ? 'View answer' : 'Record the company’s answer'}</button>}
      <details className="text-xs text-slate-500"><summary className="cursor-pointer">Details</summary><div className="mt-1 space-y-1">
       <p>Asked for: {r.required_record}</p>
       <p>Owner: {r.owner || 'not assigned'} · Due: {r.due_date || 'no date'} · Priority: {label(r.priority)}</p>
       {r.source_evidence.map(e => <p key={e.evidence_id}>Source: {e.document}, {e.location}: {e.statement}</p>)}
       {r.acceptance_note && <p>Why it was closed: {r.acceptance_note}</p>}
      </div></details>
     </div>
    </li>;})}</ol>
   </details>)}
   {data.requests.some(r => r.status === 'resolved') && <label className="block text-sm text-slate-600"><input type="checkbox" checked={!onlyOpen} onChange={e => setOnlyOpen(!e.target.checked)}/> Show answered questions</label>}
  </section>

  <section aria-label="Ask about the company" className="space-y-3 rounded-lg border border-slate-200 p-3 sm:p-4">
   <div><h3 className="font-semibold">2. Ask about the company</h3><p className="mt-1 text-sm text-slate-500">Type an investor’s question. The AI answers only from the company’s documents and cites the page. If the documents can’t answer it, the question is added to the list above for the founder.</p></div>
   {data.is_owner && <form className="space-y-2" onSubmit={async e => {e.preventDefault(); const q = question.trim();
    if (await send('/answers', {scope, parts: [{question: q, required_record: `Records or a company answer for: ${q}`}]}, 'Answer drafted. Check the cited pages, then approve it.')) setQuestion('');}}>
    <textarea required maxLength={2000} aria-label="Investor question" placeholder="e.g. How much of revenue comes from the top three partners?" className={`${input} block w-full`} value={question} onChange={e => setQuestion(e.target.value)}/>
    <div className="flex flex-wrap gap-2"><button className={button}>Answer from the documents</button></div>
    <details className="text-sm"><summary className="cursor-pointer text-slate-600">Answer for a specific investor (optional)</summary>
     <label className="mt-2 block">Investor<select className={`${input} mt-1 block w-full`} value={data.tracker.counterparties.some(c => c.id === scope) ? scope : ''} onChange={e => setScope(e.target.value)}>
      <option value="">Internal team</option>{data.tracker.counterparties.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
     <label className="mt-2 block">Or an investor reference<input maxLength={200} className={`${input} mt-1 block w-full`} value={scope} onChange={e => setScope(e.target.value)}/></label>
     {scope && <p className="mt-2 text-xs text-slate-500">For a specific investor, choose which documents may be used below.</p>}
     {scope && catalog.map(e => {
      const allowed = scopedEvidence.data?.some(ref => ref.evidence_id === e.evidence_id && ref.evidence_version === e.evidence_version);
      return <label key={e.evidence_id} className="mt-1 block text-xs"><input type="checkbox" checked={!!allowed} disabled={scopedEvidence.isFetching}
       onChange={() => void send('/grants', {...link(e), scope, enabled: !allowed}, allowed ? 'Document no longer used for this investor.' : 'Document may be used for this investor. Nothing was shared.')}/> {e.statement} <span className="text-slate-500">({e.document}, {e.location})</span></label>;
     })}
    </details>
   </form>}
   {!data.answers.length && <p className="text-sm text-slate-500">No questions asked yet.</p>}
   {data.answers.map(a => <AnswerReview key={`${a.id}-${a.version}`} answer={a} recipient={recipient(a)} canEdit={data.is_owner} send={send}/>)}
   <details onToggle={e => setHistory(e.currentTarget.open)} className="text-sm"><summary className="cursor-pointer text-slate-600">Earlier answers</summary>
    {history && <div className="mt-3 space-y-2">{revisions.isLoading && <p role="status">Loading…</p>}{revisions.error && <p role="alert" className="text-rose-700">{revisions.error.message}</p>}{revisions.data?.length === 0 && <p className="text-slate-500">None yet.</p>}{revisions.data?.map(a => <AnswerReview key={`${a.id}-${a.version}`} answer={a} recipient={recipient(a)} canEdit={false} send={send}/>)}</div>}
   </details>
  </section>

  <details open={data.tracker.counterparties.length > 0} className="rounded-lg border border-slate-200 p-3 sm:p-4">
   <summary className="cursor-pointer font-semibold">3. Investor conversations <span className="text-sm font-normal text-slate-500">(optional log)</span></summary>
   <p className="mt-2 text-sm text-slate-500">Keep a note of where each investor is: first contact, NDA, meeting, offer, commitment. This is a log only; it doesn’t contact anyone.</p>
   {data.is_owner && <button className={`${button} mt-3`} onClick={() => setEventEdit('new')}>Log an investor update</button>}
   {eventEdit && <div className="mt-3"><EventEditor key={eventEdit === 'new' ? 'new' : `${eventEdit.id}-${eventEdit.version}`} initial={eventEdit === 'new' ? undefined : eventEdit} evidence={catalog} drafts={data.tracker.approved_drafts} investors={data.tracker.counterparties} send={send} done={() => setEventEdit(null)}/></div>}
   {!data.tracker.counterparties.length && <p className="mt-3 text-sm text-slate-500">No investors logged yet.</p>}
   {data.tracker.counterparties.map(c => <article key={c.id} className="mt-3 space-y-2 rounded-lg border border-slate-200 p-3 text-sm">
    <div className="flex flex-wrap items-start justify-between gap-2"><h4 className="min-w-0 font-medium">{c.name}</h4><Badge status={c.stage}/></div>
    {c.timeline.map(e => <div id={`diligence-event-${e.id}`} key={e.id} className="border-t border-slate-100 pt-2">
     <p>{label(e.stage)} · {label(e.state)} · {e.date} · {e.owner}</p>
     {e.next_action && <p className="text-slate-600">Next: {e.next_action}{e.next_date && ` (by ${e.next_date})`}</p>}
     {data.is_owner && <button className="text-sm text-indigo-700 underline" onClick={() => setEventEdit(e)}>Edit</button>}
    </div>)}
   </article>)}
   {data.tracker.deadlines.length > 0 && <div className="mt-3 space-y-1"><h4 className="text-sm font-medium">Upcoming</h4>{data.tracker.deadlines.map((d, i) => <a key={`${d.id}-${i}`} href={`#diligence-${d.kind}-${d.id}`} className={`block text-sm underline ${d.overdue ? 'text-rose-700' : 'text-indigo-700'}`}>{d.date} · {d.owner || 'Not assigned'} · {label(d.action)}{d.overdue ? ' · overdue' : ''}</a>)}</div>}
  </details>
  </fieldset>
 </section>;
}
