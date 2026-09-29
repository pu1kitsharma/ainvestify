import { useState } from "react";
import { Link } from "react-router-dom";

export type PreparationRun = {
  status: "queued" | "running" | "completed" | "failed" | "interrupted" | "cancelled";
  phase: string;
  model?: string;
  started_at: string;
  completed_at?: string | null;
  error?: string | null;
};
export type PreparationEvent = { at: string; action: string; detail: string };

const statusLabels: Record<PreparationRun["status"], string> = {
  queued: "Waiting to start", running: "In progress", completed: "Completed",
  failed: "Needs attention", interrupted: "Interrupted", cancelled: "Stopped",
};
const eventLabels: Record<string, string> = {
  automation_started: "Preparation started", automation_completed: "Drafts saved",
  automation_failed: "Preparation attempt failed", automation_cancelled: "Preparation stopped",
  automation_interrupted: "Preparation interrupted", evidence_changed: "Source evidence changed",
  draft_pack_prepared: "Drafts saved",
};

export default function PreparationActivity({ leadId, run, events = [], model }: {
  leadId: string; run?: PreparationRun | null; events?: PreparationEvent[]; model?: string | null;
}) {
  const [showAll, setShowAll] = useState(false);
  const ordered = [...events].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  const needsAttention = run && ["failed", "interrupted", "cancelled"].includes(run.status);
  const active = run?.status === "running" || run?.status === "queued";
  const engine = run?.model || model;
  return <section className="rounded-xl border border-slate-200 bg-white p-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="font-semibold text-slate-900">Preparation activity</h2>
      {run && <span className={`rounded-full px-3 py-1 text-xs font-medium ${needsAttention ? "bg-amber-50 text-amber-800" : active ? "bg-indigo-50 text-indigo-700" : "bg-slate-100 text-slate-700"}`}>Latest run · {statusLabels[run.status]}</span>}
    </div>
    {run ? <div className="mt-4 text-sm">
      <p className="font-medium text-slate-800">{run.phase || statusLabels[run.status]}</p>
      <p className="mt-1 text-xs text-slate-500">{run.completed_at ? "Finished" : "Started"} <time dateTime={run.completed_at || run.started_at}>{new Date(run.completed_at || run.started_at).toLocaleString()}</time></p>
      {needsAttention && <p className="mt-3 text-slate-600">Open preparation to review the issue and resume the unfinished work.</p>}
      <Link className="mt-3 inline-block font-medium text-indigo-600" to={`/operations?lead=${leadId}`}>Open preparation & next steps →</Link>
      {run.error && <details className="mt-3 text-sm text-slate-600"><summary className="cursor-pointer">Latest error details</summary><p className="mt-2 whitespace-pre-wrap break-words">{run.error}</p></details>}
    </div> : <p className="mt-3 text-sm text-slate-500">No current generation run is recorded.</p>}
    <details className="mt-5 border-t border-slate-100 pt-4">
      <summary className="cursor-pointer text-sm font-medium text-slate-600">Activity history · {events.length} events</summary>
      <p className="mt-3 text-xs leading-5 text-slate-500">This log preserves earlier attempts, including failures. Each entry describes that attempt; the latest run is shown above.</p>
      {engine && <p className="mt-1 text-xs text-slate-500">Recorded generation engine: {engine}</p>}
      <ol className="mt-4 max-h-96 space-y-4 overflow-y-auto pr-2">
        {(showAll ? ordered : ordered.slice(0, 5)).map((event, i) => <li key={`${event.at}-${i}`} className="border-l-2 border-slate-200 pl-3">
          <p className="text-sm font-medium text-slate-700">{eventLabels[event.action] || event.action.replaceAll("_", " ")}</p>
          <time dateTime={event.at} className="text-xs text-slate-500">{new Date(event.at).toLocaleString()}</time>
          <p className="mt-1 break-words text-xs leading-5 text-slate-600">{event.detail}</p>
        </li>)}
      </ol>
      {ordered.length > 5 && <button onClick={() => setShowAll(!showAll)} className="mt-4 text-sm font-medium text-indigo-600">{showAll ? "Show recent events" : `Show all ${ordered.length} events`}</button>}
    </details>
  </section>;
}
