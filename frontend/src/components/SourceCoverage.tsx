import type { WebSourcingRun } from "../api/types";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export default function SourceCoverage({ run }: { run: WebSourcingRun }) {
  const rows = run.source_coverage ?? [];
  const contributing = rows.filter(r => r.discovered_companies > 0).length;
  const supporting = rows.filter(r => r.supported_companies > 0).length;
  const unavailable = rows.filter(r => r.status === "Unavailable").length;
  const groups = [...new Set(rows.map(r => r.category))];
  return <section className="overflow-hidden rounded-xl border border-slate-200 bg-white" aria-label="Source coverage">
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
      <div><h2 className="font-semibold text-slate-800">Source coverage</h2><p className="mt-1 text-xs text-slate-500">Which sources found companies, and what evidence they supplied.</p></div>
      <div className="flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-indigo-50 px-3 py-1.5 text-indigo-700">{contributing} discovery publishers</span><span className="rounded-full bg-slate-100 px-3 py-1.5 text-slate-600">{supporting} evidence publishers</span>{unavailable > 0 && <span className="rounded-full bg-amber-50 px-3 py-1.5 text-amber-800">{unavailable} unavailable</span>}</div>
    </div>
    {contributing === 1 && <p className="border-t border-amber-100 bg-amber-50 px-5 py-3 text-xs text-amber-800">All selected companies came from one publisher. This search has limited discovery coverage.</p>}
    <details className="border-t border-slate-100 px-5 py-4">
      <summary className="cursor-pointer text-sm font-medium text-indigo-700">Search details and source coverage</summary>
      {!rows.length && <p className="mt-3 text-sm text-slate-500">Source outcomes will appear as this search progresses.</p>}
      {groups.map(group => <section key={group} className="mt-5"><h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">{group}</h3>
        <div className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">{rows.filter(r => r.category === group).map(row => <details key={row.host} className="px-4 py-3">
          <summary className="cursor-pointer text-sm"><span className="font-medium text-slate-800">{row.name}</span><span className={`ml-2 text-xs ${row.status === 'Unavailable' ? 'text-amber-700' : 'text-slate-500'}`}>{row.status}</span>
            <span className="mt-1 block pl-4 text-xs text-slate-500">{row.discovered_companies} selected companies · {row.cited_claims} cited claims{row.records_read > 0 ? ` · ${row.records_read} records read · ${row.matches} retrieval candidates` : ''}{row.issues ? ` · ${row.issues} source issues` : ''}</span>
          </summary>
          <p className="mt-3 text-xs text-slate-500">Evidence from this publisher supports {row.supported_companies} {row.supported_companies === 1 ? 'company' : 'companies'}. Publisher counts do not establish independent verification of each claim.</p>
          <ul className="mt-2 space-y-3">{row.outcomes.map((outcome, i) => <li key={i} className="border-l-2 border-slate-200 pl-3 text-xs text-slate-600"><div className="flex flex-wrap justify-between gap-2"><a className="text-indigo-600 hover:underline" href={outcome.url} target="_blank" rel="noreferrer">Open source ↗</a><span className="text-slate-400">{new Date(outcome.retrieved_at).toLocaleTimeString()} · {outcome.status.replaceAll('_', ' ')}</span></div><p className="mt-1 break-words">{outcome.detail}</p></li>)}</ul>
        </details>)}</div>
      </section>)}
      <div className="mt-5 grid gap-5 border-t border-slate-100 pt-4 sm:grid-cols-2">
        <section><h3 className="text-xs font-semibold text-slate-700">Search queries</h3><ol className="mt-2 list-decimal space-y-2 pl-4 text-xs text-slate-500">{run.search_queries.map((q,i) => <li key={i}>{q}</li>)}</ol>{!run.search_queries.length && <p className="mt-2 text-xs text-slate-500">Direct source collection; search queries have not run yet.</p>}</section>
        <section><h3 className="text-xs font-semibold text-slate-700">Coverage limits</h3><ul className="mt-2 list-disc space-y-2 pl-4 text-xs text-slate-500">{[...new Set([...(run.error ? [run.error] : []), ...run.warnings])].map((w,i) => <li key={i}>{w}</li>)}</ul><p className="mt-2 text-xs text-slate-500">Public portfolios cover their own companies. A company appearing in a portfolio does not establish its current fundraising stage.</p></section>
      </div>
      <SourceAccess />
    </details>
  </section>;
}

function SourceAccess() {
  const [open, setOpen] = useState(false);
  const catalog = useQuery({ queryKey: ["datasets"], enabled: open,
    queryFn: () => api.get<{ sources: { id: string; name: string; url: string; access: string; granularity: string; license_name: string; terms_url: string; limitation: string }[] }>("/api/operations/datasets") });
  return <details className="mt-5 border-t border-slate-100 pt-4" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary className="cursor-pointer text-xs font-medium text-slate-600">Dataset access and licensing</summary>
    <p className="mt-2 text-xs text-slate-500">Catalog access is separate from this search’s results. Metadata-only entries do not supply company records.</p>
    {catalog.isLoading && <p className="mt-2 text-xs text-slate-500">Loading source access…</p>}
    {catalog.error && <p role="alert" className="mt-2 text-xs text-rose-700">{catalog.error.message}</p>}
    <div className="mt-3 grid gap-3 sm:grid-cols-2">{catalog.data?.sources.map(s => <article key={s.id} className="rounded-lg border border-slate-200 p-3"><a href={s.url} target="_blank" rel="noreferrer" className="text-xs font-semibold text-indigo-600">{s.name} ↗</a><p className="mt-2 text-xs text-slate-700">{s.access === 'metadata_only' ? 'Metadata only · records not connected' : s.access === 'open' ? 'Open access' : 'Authorized imports'} · {s.granularity === 'aggregate' ? 'Aggregate statistics' : 'Company records'}</p><p className="mt-1 text-xs leading-relaxed text-slate-500">{s.limitation}</p><a href={s.terms_url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-indigo-600">{s.license_name} · terms ↗</a></article>)}</div>
  </details>;
}
