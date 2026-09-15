import {Link} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {useDeals,useLeads} from '../api/hooks';
import {api} from '../api/client';
import {preparationRefresh} from '../api/preparationRefresh';
import {PREPARATION_VERSION,PreparationSteps,NextPreparationLink} from '../components/PreparationWorkspace';
import type {AnalystPack} from '../components/PreparationWorkspace';
type Work={id:string;lead_id:string;basis_hash:string;analyst_pack?:AnalystPack;automation?:{status:string;phase:string}};

export default function Dashboard(){
 const leads=useLeads();const deals=useDeals();
 const work=useQuery({queryKey:['operations','summary'],queryFn:()=>api.get<Work[]>('/api/operations/workspaces?summary=true'),...preparationRefresh});
 const companies=leads.data?.filter(l=>l.company_profile&&['reviewed','promoted_to_deal'].includes(l.status))||[];
 const linked=new Set(leads.data?.map(l=>l.promoted_deal_id).filter(Boolean));
 const standalone=deals.data?.filter(d=>!linked.has(d.deal.id))||[];
 if(leads.isLoading||work.isLoading)return <p role="status">Loading your companies…</p>;
 if(leads.error||work.error)return <p role="alert">{(leads.error||work.error)?.message}</p>;
 return <div className="space-y-7">
  <header className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-3xl font-semibold tracking-tight">My companies</h1><p className="mt-3 text-slate-500">Your shortlist, next decisions and preparation work in one place.</p></div><Link className="rounded-lg bg-indigo-600 px-5 py-3 text-sm font-semibold text-white" to="/leads">Find companies →</Link></header>
  {!companies.length&&<section className="rounded-xl border border-dashed border-slate-300 bg-white p-8"><h2 className="text-xl font-semibold">Start with a company worth researching</h2><p className="mt-3 max-w-xl text-sm leading-6 text-slate-500">Describe the companies you want to find. Shortlist a result, then prepare its research memo, founder approach and investment-readiness work.</p><Link className="mt-5 inline-block text-sm font-semibold text-indigo-600" to="/leads">Discover companies →</Link></section>}
  <div className="space-y-4">{companies.map(lead=>{
   const w=work.data?.find(w=>w.lead_id===lead.id);
   const pack=w?.analyst_pack?.version===PREPARATION_VERSION&&w.analyst_pack.basis_hash===w.basis_hash?w.analyst_pack:undefined;
   const business=pack?.sections['research.business'];const assessment=pack?.sections['research.decision'];
   const description=business?.status==='complete'?business.content?.text:lead.company_profile?.evidence.find(e=>e.field==='offering')?.value;
   const decision=assessment?.status==='complete'?assessment.content?.next_decision:undefined;
   const risk=assessment?.status==='complete'?assessment.content?.unresolved_risk:undefined;
   const busy=['queued','running'].includes(w?.automation?.status||'');
   return <article key={lead.id} className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0 flex-1"><Link className="text-xl font-semibold hover:text-indigo-600" to={`/operations?lead=${lead.id}`}>{lead.company_name}</Link><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{description||'Prepare research to establish the business and its investment case.'}</p></div><NextPreparationLink pack={pack} leadId={lead.id}/></div>
    {busy&&<p className="mt-3 text-sm text-indigo-700">Preparation in progress · saved work is available inside.</p>}
    {(decision||risk)&&<div className="mt-5 grid gap-4 border-t border-slate-100 pt-4 md:grid-cols-2">{decision&&<div><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Next decision</h3><p className="mt-2 text-sm leading-6">{decision}</p></div>}{risk&&<div><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Unresolved risk</h3><p className="mt-2 text-sm leading-6 text-slate-600">{risk}</p></div>}</div>}
    <div className="mt-5"><PreparationSteps pack={pack} leadId={lead.id}/></div>
   </article>;
  })}</div>
  <details className="rounded-xl border border-slate-200 bg-white p-5"><summary className="cursor-pointer text-sm font-medium text-slate-500">Other document records ({standalone.length})</summary><p className="mt-3 text-sm text-slate-500">Existing documents outside your company shortlist.</p>{deals.error&&<p role="alert">{deals.error.message}</p>}<ul className="mt-4 space-y-3">{standalone.map(d=><li key={d.deal.id}><Link className="text-sm text-indigo-600" to={`/deals/${d.deal.id}/documents`}>{d.deal.name} →</Link></li>)}</ul></details>
 </div>;
}
