import {Link} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {api} from '../api/client';
import type {SourcedLead} from '../api/types';
import DealDocuments, {PHASES, Questions, ReadinessMeter, finishText} from './DealDocuments';
import type {Run, Status} from './DealDocuments';
import Diligence from './Diligence';

type Overview = {topics: {title: string; sections: {title: string; paragraphs: string[]}[]}[]};

/** The one thing to do next, in priority order: what only the company can settle comes before anything we can review. */
function nextAction(run: Run) {
 const open = (run.questions ?? []).filter(question => !question.answer);
 const blocking = open.filter(question => question.severity === 'blocker').length;
 const plural = (count: number) => `${count} question${count === 1 ? '' : 's'}`;
 if (blocking) return {title: `Answer the ${plural(blocking)} blocking release`, href: '#questions'};
 if (open.length) return {title: `Answer the ${plural(open.length)} investors will ask`, href: '#questions'};
 const review = PHASES.find(key => run.phases[key].state === 'needs_approval');
 if (review) return {title: `Review and approve the ${run.phases[review].title.toLowerCase()}`, href: '#documents'};
 const failed = PHASES.find(key => run.phases[key].state === 'failed');
 if (failed) return {title: `${run.phases[failed].title} stopped with an error; restart it`, href: '#documents'};
 return null;
}

function WorkStatus({run}: {run: Run}) {
 const key = PHASES.find(phase => ['queued', 'running'].includes(run.phases[phase].state));
 if (!key) return null;
 const phase = run.phases[key];
 const step = phase.steps.find(item => item.state === 'running');
 const percent = phase.steps_total ? Math.round(100 * phase.steps_done / phase.steps_total) : 0;
 return <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4" role="status" aria-live="polite">
  <p className="font-medium text-indigo-900">{phase.title}{step ? `: ${step.label}` : ''}</p>
  <p className="mt-1 text-sm text-indigo-800">{phase.state === 'queued' ? 'Waiting for the worker' : finishText(phase, run)}</p>
  <div className="mt-3 h-2 overflow-hidden rounded-full bg-indigo-100"><div className="h-full rounded-full bg-indigo-600" style={{width: `${percent}%`}}/></div>
 </div>;
}

export default function CompanyDeal({lead, roomId}: {lead: SourcedLead; roomId: string}) {
 const status = useQuery({
  queryKey: ['deal-documents', roomId],
  queryFn: () => api.get<Status>(`/api/rooms/${roomId}/deal-documents`),
  refetchInterval: 15000,
 });
 const overview = useQuery({
  queryKey: ['deal-documents-overview', roomId],
  queryFn: () => api.get<Overview>(`/api/rooms/${roomId}/deal-documents/overview`),
  refetchInterval: 60000,
 });
 const run = status.data?.run;
 if (status.error) return <p role="alert" className="text-sm text-rose-700">{status.error.message}</p>;
 if (!run) return <p role="status">Loading company work…</p>;
 const next = nextAction(run);
 const topics = overview.data?.topics.filter(topic => topic.sections.length) ?? [];
 return <div className="space-y-6">
  <Link to="/" className="text-sm text-slate-500">← My companies</Link>
  <header>
   <h1 className="text-3xl font-semibold tracking-tight">{lead.company_name}</h1>
   {lead.company_profile?.website && <a href={lead.company_profile.website} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm text-indigo-600">Company website ↗</a>}
  </header>
  {next && <a href={next.href} className="block rounded-xl bg-indigo-600 p-5 text-white hover:bg-indigo-700">
   <span className="text-xs font-semibold uppercase tracking-wide text-indigo-100">Your next step</span>
   <span className="mt-1 block text-lg font-semibold">{next.title} →</span>
  </a>}
  <WorkStatus run={run}/>
  {run.readiness && <ReadinessMeter readiness={run.readiness}/>}
  {(run.questions?.length ?? 0) > 0 && <Questions roomId={roomId} run={run} isOwner={!!status.data?.is_owner}/>}
  {topics.length > 0 && <section aria-label="Current draft" className="space-y-3">
   <div>
    <h2 className="text-xl font-semibold">Current draft</h2>
    <p className="mt-1 text-sm text-slate-500">Unapproved working text. Figures come from the company's documents and have not been independently verified.</p>
   </div>
   {topics.map(topic => <details key={topic.title} className="rounded-xl border border-slate-200 bg-white p-5">
    <summary className="cursor-pointer font-semibold">{topic.title}</summary>
    {topic.sections.map(section => <div key={section.title} className="mt-4">
     {topic.sections.length > 1 && <h3 className="text-sm font-semibold text-slate-800">{section.title}</h3>}
     {section.paragraphs.map((paragraph, index) => <p key={index} className="mt-2 text-sm leading-7 text-slate-700">{paragraph}</p>)}
    </div>)}
   </details>)}
  </section>}
  <div id="documents"><DealDocuments roomId={roomId} compact/></div>
  <Diligence roomId={roomId}/>
 </div>;
}
