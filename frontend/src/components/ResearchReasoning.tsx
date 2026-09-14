import type { WebSourcingRun } from "../api/types";

export default function ResearchReasoning({ run }: { run: WebSourcingRun }) {
  const plan = run.research_plan;
  if (!plan?.interpretation) return null;
  const decisions = (run.reasoning_log ?? []).filter(e => e.step !== 'Interpret request');
  return <section className="rounded-xl border border-indigo-100 bg-white p-5" aria-label="AI research">
    <div className="flex flex-wrap justify-between gap-2"><h2 className="font-semibold text-slate-800">AI research brief</h2><span className="text-xs text-slate-500">{plan.status === 'model_interpreted' ? `Interpreted by ${plan.model}` : 'Model interpretation unavailable · original request retained'}</span></div>
    <p className="mt-2 text-sm text-slate-600">{plan.interpretation}</p>
    <div className="mt-4 grid gap-3 sm:grid-cols-3">{plan.criteria.map((c,i) => <div key={i} className="rounded-lg bg-slate-50 p-3"><p className="text-xs font-semibold text-indigo-700">{c.requirement}</p><p className="mt-1 text-xs leading-relaxed text-slate-500">Evidence needed: {c.evidence_needed}</p></div>)}</div>
    <p className="mt-3 text-xs text-slate-500">Candidates are screened against these criteria. Missing growth evidence remains unverified, even when sector and geography fit.</p>
    <details className="mt-4 border-t border-slate-100 pt-3"><summary className="cursor-pointer text-xs font-medium text-indigo-600">AI decisions and research actions · {decisions.length}</summary><ul className="mt-3 max-h-72 space-y-3 overflow-auto">{decisions.map((d,i) => <li key={i} className="border-l-2 border-indigo-100 pl-3 text-xs"><p className="font-medium text-slate-700">{d.company ? `${d.company} · ` : ''}{d.step}{d.decision === 'excluded' ? ' · excluded' : ''}</p><p className="mt-1 text-slate-500">{d.detail}</p></li>)}</ul></details>
  </section>;
}
