import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import PreparationActivity, { type PreparationEvent, type PreparationRun } from "../components/PreparationActivity";
import type { SourcedLead } from "../api/types";

type Control = { id: string; title: string; status: string; reason: string; authority_urls: string[] };
type Workspace = { id: string; lead_id: string; revision: number; controls: Control[]; model?: string | null; automation?: PreparationRun | null; events: PreparationEvent[]; preparation?: { financials?: { key: string; title: string; status: string; value: string | null; unit: string | null; document_id: string | null; source_page: number | null }[]; calculations?: {name: string; value: string; unit: string; limitation: string}[] } };
const panel = "rounded-xl border border-slate-200 bg-white p-6";
const reviewKinds = ["source_rights_review", "identity_review", "engagement_authority", "regulatory_scope", "privacy_basis", "commercial_validation", "financial_review", "incubation_outcomes", "investor_qualification", "release_approval", "signed_documents", "funds_received"];
const label = (s: string) => s.replaceAll("_", " ");
export default function OperationsRecords() {
  const [params] = useSearchParams();
  const leadId = params.get("lead");
  const lead = useQuery({ queryKey: ["leads", leadId], queryFn: () => api.get<SourcedLead>(`/api/leads/${encodeURIComponent(leadId!)}`), enabled: !!leadId });
  const workspaces = useQuery({ queryKey: ["operations", "records", leadId], queryFn: () => api.get<Workspace[]>(`/api/operations/workspaces?lead_id=${encodeURIComponent(leadId!)}`), enabled: !!leadId, refetchInterval: query => query.state.data?.some(w => w.automation?.status === "queued" || w.automation?.status === "running") ? 3000 : false });
  if (lead.isLoading || workspaces.isLoading) return <p role="status">Loading company records…</p>;
  if (lead.error || workspaces.error) return <p role="alert">{(lead.error || workspaces.error)?.message}</p>;
  return lead.data ? <Records key={lead.data.id} lead={lead.data} w={workspaces.data?.find(w => w.lead_id === lead.data.id)} /> : <Link to="/">Back to companies</Link>;
}
function Records({lead,w}: {lead: SourcedLead; w?: Workspace}) {
  const [kind,setKind] = useState("identity_review");
  const [note,setNote] = useState("");
  const [evidenceIds,setEvidenceIds] = useState<string[]>([]);
  const client = useQueryClient();
  const refresh = () => { client.invalidateQueries({queryKey:["operations"]}); client.invalidateQueries({queryKey:["leads"]}); };
  const documents = useQuery({queryKey:["operations-documents",lead.promoted_deal_id],queryFn:()=>api.get<{id:string;filename:string}[]>(`/api/deals/${lead.promoted_deal_id}/source-documents`),enabled:!!lead.promoted_deal_id});
  const promote = useMutation({mutationFn:()=>api.post(`/api/leads/${lead.id}/promote`,{name:lead.company_name}),onSuccess:refresh});
  const attest = useMutation({mutationFn:()=>api.post(`/api/operations/workspaces/${w!.id}/attestations`,{kind,note,evidence_ids:evidenceIds,expected_revision:w!.revision}),onSuccess:()=>{setNote("");setEvidenceIds([]);refresh();}});
  const facts = lead.company_profile?.evidence || [];
  const financials = w?.preparation?.financials ?? [];
  const calculations = w?.preparation?.calculations ?? [];
  return <div className="space-y-5"><Link className="text-sm text-indigo-600" to={`/operations?lead=${lead.id}`}>← Back to {lead.company_name}'s preparation</Link><header><h1 className="text-2xl font-semibold">Company records & approvals</h1><p className="mt-2 text-sm text-slate-500">Sources, private documents and the reviews required before materials are shared.</p></header>
    <section className={panel}><h2 className="font-semibold">Company documents</h2>{lead.promoted_deal_id ? <><ul className="mt-3 text-sm text-slate-600">{documents.data?.map(d=><li key={d.id}>{d.filename}</li>)}</ul><Link className="mt-3 inline-block text-sm text-indigo-600" to={`/deals/${lead.promoted_deal_id}`}>Open deal room →</Link></> : <button disabled={promote.isPending || lead.status !== "reviewed"} onClick={()=>promote.mutate()} className="mt-4 rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-50">{lead.status === "reviewed" ? "Set up deal room" : "Shortlist company first"}</button>}{w && <a className="ml-4 text-sm text-indigo-600" href={`/api/operations/workspaces/${w.id}/data-request`}>Download data request ↓</a>}{(promote.error || documents.error) && <p role="alert">{(promote.error || documents.error)?.message}</p>}</section>
    <details className={panel}><summary className="cursor-pointer font-semibold">Financial source figures</summary><p className="mt-3 text-xs text-slate-500">Reviewed extracted inputs. ARR applies only to recurring revenue; cash coverage is not a forecast.</p>{!financials.length && !calculations.length && <p className="mt-3 text-sm text-slate-500">No extracted financial figures are saved in this record yet.</p>}<ul className="mt-4 space-y-3">{financials.map(m=><li key={m.key} className="text-sm"><strong>{m.title}: </strong>{m.value === null ? label(m.status) : `${m.value} ${m.unit || ""}`}{m.document_id && <span className="ml-2 text-xs text-slate-400">Document {m.document_id}, page {m.source_page}</span>}</li>)}</ul>{calculations.map(c=><p key={c.name} className="mt-4 text-sm">{c.name}: {c.value} {c.unit}. {c.limitation}</p>)}</details>
    <details className={panel}><summary className="cursor-pointer font-semibold">Public sources · {facts.length} passages</summary><ul className="mt-4 space-y-4">{facts.map(e=><li key={e.id} className="text-sm"><p className="font-medium">{label(e.field)}: {e.value}</p><blockquote className="mt-2 text-slate-500">{e.quote}</blockquote><a className="text-xs text-indigo-600" href={e.source_url} target="_blank" rel="noreferrer">Read source ↗</a></li>)}</ul></details>
    <details className={panel}><summary className="cursor-pointer font-semibold">Approvals and supporting evidence</summary><p className="mt-3 text-xs text-slate-500">Recorded reviews apply to the current evidence. Authority references are guidance, not a compliance certification.</p><ul className="mt-4 divide-y divide-slate-100">{w?.controls.map(c=><li className="py-3" key={c.id}><p className="text-sm font-medium">{c.title} · {label(c.status)}</p><p className="mt-1 text-xs text-slate-500">{c.reason}</p>{c.authority_urls.map((url,i)=><a key={url} className="mr-3 text-xs text-indigo-600" href={url} target="_blank" rel="noreferrer">Reference {i+1} ↗</a>)}</li>)}</ul>
      <form className="mt-6 max-w-xl space-y-3" onSubmit={e=>{e.preventDefault();attest.mutate();}}><h2 className="font-semibold">Record a review</h2><label className="block text-sm">Review type<select className="mt-1 block w-full rounded-lg border border-slate-200 p-2" value={kind} onChange={e=>setKind(e.target.value)}>{reviewKinds.map(k=><option key={k} value={k}>{label(k)}</option>)}</select></label><label className="block text-sm">Findings and basis<textarea className="mt-1 block w-full rounded-lg border border-slate-200 p-2" rows={3} value={note} onChange={e=>setNote(e.target.value)} /></label><fieldset><legend className="text-sm">Supporting evidence</legend><div className="max-h-48 overflow-auto">{[...facts.map(e=>({id:e.id,title:e.value})),...(documents.data || []).map(d=>({id:`doc:${d.id}`,title:d.filename}))].map(e=><label key={e.id} className="flex gap-2 py-2 text-xs"><input type="checkbox" checked={evidenceIds.includes(e.id)} onChange={ev=>setEvidenceIds(ids=>ev.target.checked?[...ids,e.id]:ids.filter(id=>id!==e.id))} />{e.title}</label>)}</div></fieldset><button disabled={!w || attest.isPending || note.trim().length<12 || !evidenceIds.length} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-50">Record review</button>{attest.error && <p role="alert" className="text-sm text-rose-700">{attest.error.message}</p>}{attest.isSuccess && <p role="status" className="text-sm text-emerald-700">Review recorded.</p>}</form>
    </details>
    <PreparationActivity leadId={lead.id} run={w?.automation} events={w?.events} model={w?.model} />
  </div>;
}
