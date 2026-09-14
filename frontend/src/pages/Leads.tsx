import SourceCoverage from "../components/SourceCoverage";
import ResearchReasoning from "../components/ResearchReasoning";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useCancelWebRun, useLeadDecision, useLeads, useStartWebRun, useWebRuns } from "../api/hooks";
import WebSourcing from "../components/WebSourcing";
import type { SourcedLead, WebSourcingRun } from "../api/types";

const running = (run?: WebSourcingRun) => !!run && ["running", "cancel_requested"].includes(run.status);
const label = (value: string) => value.replaceAll("_", " ");
const host = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "Source"; } };
const recommendationStyle: Record<string, string> = {
  invite_to_discussion: "bg-emerald-50 text-emerald-800", investigate: "bg-indigo-50 text-indigo-700",
  nurture: "bg-amber-50 text-amber-800", pass: "bg-slate-100 text-slate-600",
};
// Multiple sources often independently confirm the same fact (e.g. a
// company's name or location) -- rendering one block per evidence item
// duplicates that fact once per source instead of showing it once with
// every source that backs it.
type Evidence = { id: string; field: string; value: string; quote: string; source_url: string; retrieved_at: string };
function groupEvidence(facts: Evidence[]) {
  const groups = new Map<string, { field: string; value: string; items: Evidence[] }>();
  for (const e of facts) {
    const key = `${e.field}::${e.value}`;
    const g = groups.get(key) ?? { field: e.field, value: e.value, items: [] };
    g.items.push(e);
    groups.set(key, g);
  }
  return [...groups.values()];
}
const phaseLabel: Record<string, string> = {
  interpreting_request: "AI is interpreting your requirements", screening_candidates: "AI is screening candidates against your criteria",
  starting: "Starting your search", querying_datasets: "Looking through company records", planning_search: "Preparing your search",
  searching_web: "Finding relevant sources", researching_companies: "Reading company evidence", enriching_companies: "Researching the candidates",
  assessing_companies: "Assessing fit and evidence gaps", preparing_operating_workflow: "Preparing company workspaces",
};

export default function Leads() {
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"results" | "shortlist" | "history">("results");
  const runs = useWebRuns();
  const allLeads = useLeads();
  const start = useStartWebRun();
  const cancel = useCancelWebRun();
  const decision = useLeadDecision();
  const selectedId = params.get("run");
  const requestedBrief = params.get("keyword");
  const selected = selectedId ? runs.data?.find(r => r.id === selectedId) : requestedBrief
    ? runs.data?.find(r => r.thesis.toLowerCase() === requestedBrief.toLowerCase() && (!params.get("location") || r.geography?.toLowerCase() === params.get("location")!.toLowerCase()))
    : runs.data?.[0];
  const active = runs.data?.find(running);
  // A new request clears visible results immediately. No global lead backlog
  // may be substituted while that request has zero companies or is loading.
  const visibleRun = start.isPending ? undefined : selected;
  const results = useQuery({ queryKey: ["run-leads", visibleRun?.id],
    queryFn: () => api.get<SourcedLead[]>(`/api/leads/web-runs/${visibleRun!.id}/leads`), enabled: !!visibleRun,
    refetchInterval: running(visibleRun) ? 2000 : false });
  useEffect(() => {
    if (visibleRun?.completed_at) void queryClient.invalidateQueries({ queryKey: ["run-leads", visibleRun.id] });
  }, [visibleRun?.id, visibleRun?.completed_at, queryClient]);
  const shortlist = (allLeads.data ?? []).filter(l => l.status === "reviewed" || l.status === "promoted_to_deal");
  const statuses = new Map((allLeads.data ?? []).map(l => [l.id, l.status]));
  const current = (results.data ?? []).map(l => ({ ...l, status: statuses.get(l.id) ?? l.status })).filter(l => l.status !== "dismissed" &&
    l.company_profile?.evidence.some(e => ["offering", "business_model", "traction"].includes(e.field)));
  const companies = tab === "shortlist" ? shortlist : visibleRun ? current : [];
  const selectRun = (id: string) => { setParams({ run: id }); setTab("results"); };
  const search = (thesis: string, geography: string) => {
    setTab("results");
    start.mutate({ thesis, geography: geography || undefined, prepare_workflow: false }, { onSuccess: run => selectRun(run.id) });
  };
  const error = start.error ?? cancel.error ?? decision.error ?? runs.error ?? results.error ?? allLeads.error;
  return <div className="space-y-6">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">Company discovery</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">Find your next opportunity</h1>
        <p className="mt-2 text-sm text-slate-500">Research a market. Compare companies. Build your shortlist.</p></div>
      <button onClick={() => setTab("shortlist")} className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:border-indigo-300">Shortlist <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs">{shortlist.length}</span></button>
    </header>
    <WebSourcing key={selected?.id ?? "new"}
      initialThesis={params.get("keyword") ?? selected?.thesis ?? ""} initialGeography={params.get("location") ?? selected?.geography ?? ""}
      busy={!!active} starting={start.isPending} stopping={cancel.isPending || active?.status === "cancel_requested"}
      onSearch={search} onCancel={() => active && cancel.mutate(active.id)} error={error?.message} />
    {active && visibleRun?.id !== active.id && !start.isPending && <button onClick={() => selectRun(active.id)} className="text-sm text-indigo-600 underline">View the search currently running: {active.thesis}</button>}
    <div className="flex gap-6 border-b border-slate-200" role="tablist" aria-label="Discovery views">
      {([['results', 'Search results'], ['shortlist', 'Shortlist'], ['history', 'Search history']] as const).map(([value, title]) =>
        <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className={`border-b-2 pb-3 text-sm font-medium ${tab === value ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{title}</button>)}
    </div>
    {tab === "history" ? <section aria-label="Search history" className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      {!runs.data?.length && <p className="p-6 text-sm text-slate-500">Your searches will appear here.</p>}
      {runs.data?.map(run => <button key={run.id} onClick={() => selectRun(run.id)} className="flex w-full items-center justify-between gap-4 border-b border-slate-100 p-4 text-left last:border-0 hover:bg-slate-50">
        <div><p className="text-sm font-semibold text-slate-800">{run.thesis}</p><p className="mt-1 text-xs text-slate-500">{run.geography || "Worldwide"} · {new Date(run.started_at).toLocaleString()}</p></div>
        <div className="shrink-0 text-right"><p className="text-sm text-slate-700">{run.lead_ids.length} companies</p><p className="mt-1 text-xs text-slate-500">{label(run.status)} →</p></div>
      </button>)}
    </section> : <>
      {tab === "results" && visibleRun && <SearchProgress run={visibleRun} count={current.length} />}
      {tab === "results" && visibleRun && <ResearchReasoning run={visibleRun} />}
      {tab === "shortlist" && <div><h2 className="font-semibold">Companies you’ve shortlisted</h2><p className="mt-1 text-sm text-slate-500">Saved across searches, ready for further diligence and company work.</p></div>}
      {(start.isPending || runs.isLoading || (results.isLoading && !!visibleRun && tab === "results")) ? <p role="status" className="rounded-xl bg-white p-6 text-sm text-slate-500">{start.isPending ? "Starting a new search…" : "Loading your results…"}</p>
        : companies.length ? <div className="grid items-start gap-4 md:grid-cols-2">{companies.map(lead => <CompanyCard key={lead.id} lead={lead} pending={decision.isPending} researching={tab === "results" && running(visibleRun)}
          onKeep={() => decision.mutate({ leadId: lead.id, decision: "keep" })} onDismiss={() => decision.mutate({ leadId: lead.id, decision: "dismiss" })} />)}</div>
        : <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
          <h2 className="text-base font-semibold text-slate-700">{tab === "shortlist" ? "Your shortlist starts here" : running(visibleRun) ? "Looking for companies that match your brief" : visibleRun ? "No matching companies were established in this search" : "Start with the companies you want to find"}</h2>
          <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">{tab === "shortlist" ? "Shortlist a company from your search results to keep working on it." : running(visibleRun) ? "Candidates will appear here as evidence is collected." : visibleRun ? "The available sources did not provide enough relevant evidence. You can retry the search; this does not mean the market has no companies." : "Enter a brief and geography above. Each search has its own results."}</p>
        </div>}
      {tab === "results" && visibleRun && <SourceCoverage run={visibleRun} />}
    </>}
  </div>;
}

function SearchProgress({ run, count }: { run: WebSourcingRun; count: number }) {
  return <section aria-live="polite" className="flex flex-wrap items-center justify-between gap-3">
    <div><h2 className="text-base font-semibold text-slate-800">{run.thesis} <span className="ml-2 text-sm font-normal text-slate-500">{run.geography || "Worldwide"}</span></h2>
      <p className="mt-1 flex items-center gap-2 text-sm text-slate-500">{running(run) && <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500"/>}
        {running(run) ? phaseLabel[run.phase] ?? "Research in progress" : run.status === "partial" ? "Search finished with limited source coverage" : run.status === "completed" ? "Search complete" : run.status === "cancelled" ? "Search stopped · collected results retained" : "Search interrupted · collected results retained"}</p></div>
    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-600">{count} {count === 1 ? "company" : "companies"}</span>
  </section>;
}


function CompanyCard({ lead, pending, researching, onKeep, onDismiss }: { lead: SourcedLead; pending: boolean; researching: boolean; onKeep: () => void; onDismiss: () => void }) {
  const profile = lead.company_profile;
  const facts = profile?.evidence ?? [];
  const fact = (field: string) => facts.find(e => e.field === field)?.value;
  const assessment = profile?.assessment;
  const saved = lead.status === "reviewed" || lead.status === "promoted_to_deal";
  const sourceCount = new Set(facts.map(e => host(e.source_url))).size;
  const origin = profile?.discovery_source_url || facts.find(e => e.field === "directory_profile")?.source_url;
  const publisher = origin ? ({ "ycombinator.com": "Y Combinator", "blume.vc": "Blume Ventures", "villgro.org": "Villgro" }[host(origin)] || host(origin)) : null;
  return <article className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
    <div className="p-5">
      <div className="flex items-start gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-sm font-semibold text-indigo-600" aria-hidden="true">{lead.company_name.slice(0,2).toUpperCase()}</span>
        <div className="min-w-0 flex-1"><h3 className="text-base font-semibold text-slate-900">{lead.company_name}</h3><p className="mt-0.5 text-xs text-slate-500">{fact("location") || "Location to verify"}{fact("accelerator_batch") ? ` · YC ${fact("accelerator_batch")}` : ""}</p></div>
        {saved && <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">Shortlisted</span>}
      </div>
      <p className="mt-4 line-clamp-3 text-sm leading-relaxed text-slate-600">{fact("offering") || fact("business_model") || "Business activity needs further research."}</p>
      {origin && publisher && <a href={origin} target="_blank" rel="noreferrer" className="mt-3 inline-block text-xs text-indigo-600 hover:underline">Found through {publisher} ↗</a>}
      {profile?.growth_analysis?.status && <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"><h4 className="text-xs font-semibold text-slate-700">Operating growth evidence</h4>{profile.growth_analysis.comparisons.map((c,i) => <p key={i} className="mt-2 text-sm text-slate-700">{c.metric}: {c.before} → {c.after} {c.unit} · {c.change_pct > 0 ? '+' : ''}{c.change_pct}% <span className="text-xs text-slate-500">({c.period_before}–{c.period_after})</span> <a href={c.source_url} target="_blank" rel="noreferrer" className="text-xs text-indigo-600">Reported source ↗</a></p>)}<p className="mt-2 text-xs leading-relaxed text-slate-600">{profile.growth_analysis.explanation}</p><details className="mt-2 text-xs text-slate-500"><summary className="cursor-pointer">Evidence needed and searches attempted</summary><p className="mt-2">{profile.growth_analysis.required}</p><ul className="mt-2 space-y-1">{profile.growth_analysis.research_queries?.map(q => <li key={q}>{q}</li>)}</ul></details></div>}
      {!!profile?.criteria_review?.length && <div className="mt-3 flex flex-wrap gap-2">{profile.criteria_review.map((c,i) => <span key={i} title={c.reason} className={`rounded px-2 py-1 text-xs ${c.status === 'supported' ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'}`}>{label(c.dimension)}: {c.status === 'supported' ? 'source supported' : 'unverified'}</span>)}</div>}
      <p className="mt-3 text-xs text-slate-400">{facts.length} cited claims · {sourceCount} {sourceCount === 1 ? "source" : "sources"} · {assessment ? assessment.status === "needs_review" ? "Assessment needs review" : "Initial assessment available" : researching ? "Assessment pending" : "Further research needed"}</p>
      <details className="mt-4 border-t border-slate-100 pt-3 text-sm">
        <summary className="cursor-pointer font-medium text-indigo-600">Review evidence and fit</summary>
        {profile?.criteria_review?.map((c,i) => <div key={i} className="mt-3 text-xs text-slate-600"><p className="font-semibold">{c.requirement} · {c.status}</p><p className="mt-1">{c.reason}</p>{c.evidence_ids.map(id => { const fact = facts.find(e => e.id === id); return fact && <a key={id} className="mr-2 text-indigo-600" href={fact.source_url} target="_blank" rel="noreferrer">{host(fact.source_url)} ↗</a>; })}</div>)}
        {assessment && <div className="mt-3 text-sm text-slate-600">
          <span className={`inline-block rounded px-2 py-1 text-xs font-semibold ${recommendationStyle[assessment.recommendation] ?? "bg-slate-100 text-slate-600"}`}>{label(assessment.recommendation)}</span>
          <p className="mt-2">{assessment.rationale}</p>
          {!!assessment.missing_information.length && <><p className="mt-3 text-xs font-semibold text-slate-700">Questions to resolve</p><ul className="mt-1 list-disc space-y-1 pl-4 text-xs">{assessment.missing_information.map((item,i) => <li key={i}>{label(item)}</li>)}</ul></>}
        </div>}
        <p className="mt-3 text-xs text-slate-500">Source-reported claims; current stage, investment fit and financials still need verification.</p>
        <ul className="mt-3 divide-y divide-slate-100">{groupEvidence(facts.filter(e => e.field !== "directory_profile" && e.field !== "name")).map(g => <li key={`${g.field}::${g.value}`} className="py-2 text-xs text-slate-600 first:pt-0">
          <p><span className="font-semibold">{label(g.field)}:</span> {g.value}</p>
          <p className="mt-1 text-slate-400">{g.items.map((e,i) => <span key={e.id}>{i > 0 && ", "}<a href={e.source_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">{host(e.source_url)}</a></span>)} · {new Date(g.items[0].retrieved_at).toLocaleDateString()}</p>
        </li>)}</ul>
        {profile?.website && <a className="mt-3 block text-xs font-medium text-indigo-600" href={profile.website} target="_blank" rel="noreferrer">Visit {host(profile.website)} ↗</a>}
      </details>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 bg-slate-50/60 px-5 py-3">
      {saved ? <Link to={`/operations?lead=${lead.id}`} className="text-sm font-medium text-indigo-600">Open company workspace →</Link>
        : <button disabled={pending} onClick={onKeep} className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50">Shortlist company</button>}
      {!saved && <button disabled={pending} onClick={onDismiss} className="px-2 py-1 text-xs text-slate-500 hover:text-slate-800 disabled:opacity-50">Dismiss</button>}
    </div>
  </article>;
}
