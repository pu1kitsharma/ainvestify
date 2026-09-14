import { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useLeads } from "../api/hooks";
import type { SourcedLead } from "../api/types";
import CompanyMetrics from "../components/CompanyMetrics";
import type { Metrics, MetricImport } from "../components/CompanyMetrics";
import InvestmentCase from "../components/InvestmentCase";
import type { InvestmentCaseData } from "../components/InvestmentCase";
import OperationsRecords from "./OperationsRecords";

type Citation = { evidence_ids: string[]; quality_review?: {issues:{correction:string}[]} };
type Research = Citation & { business: string; reason_to_meet: string; main_risk: string; first_question: string };
type Pitch = Citation & { subject: string; observation: string; proposed_help: string; meeting_ask: string };
type Priority = { why_now: string; required_input: string; title: string; investor_question: string; action: string; output: string; done_when: string };
type Brief = { status?:string; version?: number; basis_hash?: string; updated_at?: string; research?: Research; pitch?: Pitch; readiness?: Citation & { priorities: Priority[] } };
type Workspace = { investment_case?:InvestmentCaseData; metric_imports?: MetricImport[]; revision: number; metrics?: Metrics; id: string; lead_id: string; basis_hash: string; company_brief?: Brief; automation?: { status: string; phase: string; error?: string } };
const evidenceText = (e: {field:string;value:string}) => {
  if (e.field === "founder_ask") {
    const target = e.value.match(/(?:intros? to|introductions to)\s+([^.!?\n]+)/i)?.[1];
    if (target) return `The founders request introductions to ${target}.`;
  }
  const value = e.value.replace(/^.*?Active Founders\s+/, "");
  if (e.field === "team") {
    const sentences = value.split("The problem")[0].split(/(?<=[.!?])\s+/).filter(s=>/[.!?]$/.test(s));
    return [...new Set(sentences)].join(" ") || value;
  }
  return value;
};
const panel = "rounded-2xl border border-slate-200 bg-white p-6 sm:p-8";
const primary = "rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50";
const busy = (w?: Workspace) => ["queued", "running"].includes(w?.automation?.status || "");
const current = (w?: Workspace) => w?.company_brief?.version === 9 && w.company_brief.basis_hash === w.basis_hash;
const complete = (w?: Workspace) => current(w) && !!w?.company_brief?.research && !!w.company_brief.pitch && !!w.company_brief.readiness;

export default function Operations() {
  const [params] = useSearchParams();
  const leads = useLeads();
  const workspaces = useQuery({ queryKey: ["operations"], queryFn: () => api.get<Workspace[]>("/api/operations/workspaces"), refetchInterval: q => q.state.data?.some(busy) ? 2000 : false });
  if (params.get("view") === "records") return <OperationsRecords />;
  if (leads.isLoading || workspaces.isLoading) return <p role="status" className={panel}>Loading companies…</p>;
  const error = leads.error || workspaces.error;
  if (error) return <p role="alert" className={panel}>{error.message}</p>;
  const leadId = params.get("lead");
  const lead = leads.data?.find(l => l.id === leadId && l.company_profile && l.status !== "dismissed");
  if (leadId) return lead ? <Company key={lead.id} lead={lead} workspace={workspaces.data?.find(w => w.lead_id === lead.id)} /> : <div className={panel}>Company unavailable. <Link to="/operations" className="text-indigo-600">Back to companies</Link></div>;
  return <Navigate to="/" replace />;
}

function Company({ lead, workspace: w }: { lead: SourcedLead; workspace?: Workspace }) {
  const [companyParams, setCompanyParams] = useSearchParams();
  const [tab, setTab] = useState(["research","pitch","readiness"].includes(companyParams.get("tab") || "") ? companyParams.get("tab")! : "research");
  const chooseTab = (value:string) => {setTab(value);const next=new URLSearchParams(companyParams);next.set("tab",value);setCompanyParams(next,{replace:true});};
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const client = useQueryClient();
  const prepare = useMutation<Workspace, Error, boolean>({ mutationFn: (refresh = false) => api.post<Workspace>(`/api/operations/leads/${lead.id}/brief-jobs${refresh ? "?refresh=true" : ""}`), onSuccess: value => {
    client.setQueryData<Workspace[]>(["operations"], old => [...(old || []).filter(x => x.lead_id !== lead.id), value]);
    client.invalidateQueries({queryKey:["operations"]}); client.invalidateQueries({queryKey:["leads"]});
  }});
  useEffect(() => { if (w?.company_brief?.basis_hash || ["completed", "failed"].includes(w?.automation?.status || "")) client.invalidateQueries({queryKey:["leads"]}); }, [w?.automation?.status, w?.company_brief?.basis_hash, client]);
  const pack = w?.company_brief;
  const available = current(w);
  const excluded = w?.investment_case?.version === 8 && w?.investment_case?.basis_hash === w?.basis_hash && !!w?.investment_case?.fit && w.investment_case.fit.decision !== "proceed";
  const research = excluded ? undefined : pack?.research, pitch = excluded ? undefined : pack?.pitch, readiness = pack?.readiness;
  const running = busy(w) || prepare.isPending;
  const facts = lead.company_profile?.evidence || [];
  const text = pitch ? `Subject: ${pitch.subject}\n\nHi ${lead.company_name} team,\n\n${pitch.observation}\n\n${pitch.proposed_help}\n\n${pitch.meeting_ask || ""}` : "";
  const copy = async () => {try {await navigator.clipboard.writeText(text);setCopied(true);setCopyError("");} catch {setCopyError("Copy unavailable. Select the email text below to copy it.");}};
  const selected = tab === "research" ? research : tab === "pitch" ? pitch : readiness;
  return <div className="space-y-6">
    <Link className="text-sm text-slate-500" to="/operations">← Your companies</Link>
    <header className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-3xl font-semibold tracking-tight">{lead.company_name}</h1><p className="mt-2 text-sm text-slate-500">{facts.find(e => e.field === "location")?.value || "Location not established"}{lead.company_profile?.website && <> · <a className="text-indigo-600" href={lead.company_profile.website} target="_blank" rel="noreferrer">Website ↗</a></>}</p></div>{tab === "readiness" ? null : excluded ? <button className={primary} onClick={()=>chooseTab("readiness")}>View engagement decision</button> : complete(w) ? <a className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700" href={`/api/operations/workspaces/${w!.id}/company-brief`}>Download brief ↓</a> : <button disabled={running} className={primary} onClick={() => prepare.mutate(false)}>{running ? "Preparing…" : pack?.research ? "Update / finish brief" : "Prepare company brief"}</button>}</header>
    <nav role="tablist" aria-label="Company journey" className="grid grid-cols-3 gap-2 rounded-xl bg-slate-100 p-1.5">{[["research","1. Research"],["pitch","2. Pitch founders"],["readiness","3. Get investment ready"]].map(([key,name]) => <button role="tab" aria-selected={tab === key} onClick={() => chooseTab(key)} key={key} className={`rounded-lg px-2 py-3 text-sm font-semibold ${tab === key ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>{name}</button>)}</nav>
    {running && <p role="status" className="rounded-lg bg-indigo-50 px-4 py-3 text-sm text-indigo-800">{w?.automation?.phase || "Starting company research…"} You can leave this page; completed drafts are saved.</p>}
    {tab !== "readiness" && current(w) && pack?.status === "needs_review" && <section className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900"><p>Working draft · automated review questions remain unresolved. Check the source evidence before using this externally.</p><button className="mt-2 font-semibold underline" disabled={running} onClick={()=>prepare.mutate(false)}>Revise flagged drafts</button><details className="mt-3"><summary className="cursor-pointer">Review questions · AI proposed, not confirmed findings</summary>{[pack.research,pack.pitch,pack.readiness].flatMap(s=>s?.quality_review?.issues||[]).map((issue,i)=><p className="mt-3 leading-6" key={i}>{issue.correction}</p>)}</details></section>}
    {prepare.error && <p role="alert" className="text-sm text-rose-700">{prepare.error.message}</p>}
    {!running && w?.automation?.status === "failed" && <p role="alert" className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">Company work needs attention. Saved figures and drafts are retained. Check the details below before retrying.<details className="mt-2"><summary>Failure details</summary>{w.automation.error}</details></p>}
    {tab !== "readiness" && selected && !available && <p className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">{pack?.basis_hash !== w?.basis_hash ? "Company evidence has changed. This is the previous draft; update it before using it." : "This draft uses the previous analysis format. Update it to generate the complete pitch and company-specific priorities."}</p>}
    {excluded && tab !== "readiness" && <div className="rounded-xl border border-amber-200 bg-amber-50 p-6"><h2 className="font-semibold">{w?.investment_case?.fit?.decision === "clarify" ? "Confirm the engagement before preparing a raise" : "This company does not fit the incubation engagement"}</h2><p className="mt-3 text-sm leading-6">{w?.investment_case?.fit?.rationale}</p><button className="mt-4 text-sm font-semibold text-indigo-600" onClick={()=>chooseTab("readiness")}>Read the decision and next action →</button></div>}
    {tab === "research" && !excluded && (research ? <div className="space-y-5"><section className={panel}><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Company brief · source-based analysis</p><h2 className="mt-3 text-xl font-semibold">What does this company do?</h2><p className="mt-3 max-w-3xl text-base leading-7 text-slate-700">{research.business}</p><div className="mt-7 grid gap-7 md:grid-cols-2"><div><h3 className="font-semibold">Why spend time on it?</h3><p className="mt-2 text-sm leading-7 text-slate-600">{research.reason_to_meet}</p></div><div><h3 className="font-semibold">What could change your mind?</h3><p className="mt-2 text-sm leading-7 text-slate-600">{research.main_risk}</p></div></div></section><section className="rounded-xl border border-indigo-100 bg-indigo-50 p-6"><h2 className="text-sm font-semibold text-indigo-800">Start the founder conversation here</h2><p className="mt-2 text-lg leading-7 text-indigo-950">{research.first_question}</p><button className="mt-4 text-sm font-semibold text-indigo-700" onClick={() => chooseTab("pitch")}>Read your founder pitch →</button></section></div> : <section className={panel}><h2 className="text-xl font-semibold">Start with the business</h2><p className="mt-3 text-slate-600">{facts.find(e => e.field === "offering")?.value || "The company description needs research."}</p><p className="mt-5 max-w-2xl text-sm leading-6 text-slate-500">Prepare a short brief explaining the opportunity, the main risk and the first question to ask. We'll also draft your founder pitch and investment-readiness priorities.</p></section>)}
    {tab === "pitch" && !excluded && (pitch ? <section className={panel}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-semibold">Your introduction to the founders</h2><p className="mt-2 text-sm text-slate-500">Proposed support, ready to personalize. Nothing has been sent.</p></div><button disabled={!available} className={primary} onClick={copy}>{copied ? "Copied" : "Copy email"}</button></div>{copyError && <p role="alert" className="mt-3 text-sm text-amber-800">{copyError}</p>}<div className="mt-6 rounded-xl border border-slate-200 p-5 sm:p-7"><p className="border-b border-slate-100 pb-4 text-sm font-semibold">Subject: {pitch.subject}</p><div className="mt-5 space-y-5 text-sm leading-7 text-slate-700"><p>Hi {lead.company_name} team,</p><p>{pitch.observation}</p><p>{pitch.proposed_help}</p><p>{pitch.meeting_ask}</p></div></div><button onClick={() => chooseTab("readiness")} className="mt-5 text-sm font-semibold text-indigo-600">See the work you'd propose →</button></section> : <Empty title="A pitch to win the founder conversation" description="The brief will include a company-specific email: what caught your attention, how you could help, and a clear invitation to talk." />)}
    {tab === "readiness" && <InvestmentCase leadId={lead.id} workspaceId={w?.id} basis={w?.basis_hash} data={w?.investment_case} busy={running} facts={facts} metrics={w?.metrics} onAddInputs={()=>chooseTab("research")} />}

    {tab !== "readiness" && <details className="rounded-xl border border-slate-200 bg-white px-5 py-4"><summary className="cursor-pointer text-sm font-medium text-slate-600">Sources behind this {tab === "pitch" ? "pitch" : "brief"}</summary><p className="mt-3 text-xs text-slate-500">Company statements are source-reported. The pitch and priorities are proposals.</p><ul className="mt-4 space-y-4">{facts.filter(e => selected?.evidence_ids.includes(e.id) || (!selected && e.field === "offering")).map(e => <li key={e.id} className="text-sm text-slate-600"><blockquote className="border-l-2 border-indigo-100 pl-3 leading-6">{e.quote}</blockquote><a className="mt-1 inline-block text-xs text-indigo-600" target="_blank" rel="noreferrer" href={e.source_url}>Read source ↗</a></li>)}</ul>{w?.metrics?.months.filter(row=>selected?.evidence_ids.includes(row.id)).map(row=><div key={row.id} className="mt-4 text-sm text-slate-600"><p className="font-medium">Company-reported figures · {row.month} · {row.currency}</p><p className="mt-1">{row.source_note}</p><button className="mt-2 text-indigo-600" onClick={()=>chooseTab("research")}>See figures, quotes and calculations →</button></div>)}</details>}
    {tab === "research" && !excluded && w && <><CompanyMetrics workspaceId={w.id} revision={w.revision} metrics={w.metrics} imports={w.metric_imports} busy={running} /><section className={panel}><h2 className="text-xl font-semibold">Evidence for the investment case</h2><div className="mt-3 flex flex-wrap gap-4">{facts.filter(e=>["founded","team_size"].includes(e.field)).map(e=><p key={e.id} className="text-sm text-slate-600">{e.field === "founded" ? "Founded" : "Reported team size"}: <strong>{e.value}</strong> <a href={e.source_url} target="_blank" rel="noreferrer" className="text-indigo-600">Source ↗</a></p>)}</div><div className="mt-4 space-y-5">{[["Team",["team"]],["What the founders need",["founder_ask"]],["Market and alternatives",["market","competition"]]].map(([title,fields])=>{const matching=facts.filter(e=>(fields as string[]).includes(e.field)).slice(0,2);return <div key={title as string}><h3 className="text-sm font-semibold">{title as string}</h3>{matching.length ? matching.map(e=><p key={e.id} className="mt-2 text-sm leading-6 text-slate-600">{evidenceText(e).slice(0,700)} <a href={e.source_url} target="_blank" rel="noreferrer" className="text-indigo-600">Source ↗</a></p>) : <p className="mt-2 text-sm text-slate-500">Not established in the collected evidence.</p>}</div>})}</div><button disabled={running} className="mt-5 text-sm font-semibold text-indigo-600 disabled:opacity-50" onClick={()=>prepare.mutate(true)}>Refresh company research</button></section></>}
    <footer className="flex flex-wrap justify-between gap-3 text-xs text-slate-400"><p>{pack?.updated_at ? `Draft updated ${new Date(pack.updated_at).toLocaleDateString()}` : "Company research feeds all three steps."}</p><Link className="hover:text-indigo-600" to={`/operations?lead=${lead.id}&view=records`}>Company records & approvals →</Link></footer>
  </div>;
}

function Empty({title, description}: {title: string; description: string}) {return <section className={panel}><h2 className="text-xl font-semibold">{title}</h2><p className="mt-3 max-w-2xl text-sm leading-7 text-slate-500">{description}</p></section>}
