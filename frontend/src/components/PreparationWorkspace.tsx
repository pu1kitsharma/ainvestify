import {useState} from 'react';
import {Link, useSearchParams} from 'react-router-dom';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {api} from '../api/client';
import type {SourcedLead} from '../api/types';
import CompanyMetrics from './CompanyMetrics';
import type {Metrics, MetricImport} from './CompanyMetrics';

export type Fact={id:string;category:string;subject?:string;quote:string;source_url:string;retrieved_at:string;observed_at?:string;status:string};
type SectionContent={fact_ids:string[];source_quotes?:boolean;source_excerpt?:{id:string;fact_id:string;quote:string};text?:string;revenue_mechanism?:string;unknown_economics?:string;reason_to_engage?:string;unresolved_risk?:string;next_decision?:string;reported_observation?:string;question_to_explore?:string;proposed_work?:string;invitation?:string;question?:string;records_to_request?:string;required_input?:string;action?:string;output?:string;decision?:string;analysis_plan?:Record<string,unknown>};
export type Section={document:string;title:string;status:string;evidence_status?:string;dependency?:string;content?:SectionContent;error?:string;review?:{objections:{passage:string;correction:string}[]}};
export type AnalystPack={version:number;basis_hash:string;status:string;record:{facts:Fact[];unknowns?:string[];coverage?:string};sections:Record<string,Section>;documents?:Record<string,{title:string;status:string}>};
export type AnalystWorkspace={id:string;lead_id:string;revision:number;basis_hash:string;analyst_pack?:AnalystPack;metrics?:Metrics;metric_imports?:MetricImport[];automation?:{id?:string;status:string;phase:string;error?:string}};
export const PREPARATION_VERSION=10;
const preparationStages=[
 {id:'research',title:'Research',question:'Is this company worth pursuing?',description:'Understand the business, how it earns revenue, and the evidence that would change your decision.',sections:['research.business','research.economics','research.decision']},
 {id:'founder',title:'Pitch founders',question:'What help should we offer?',description:'A founder approach explaining why we want to engage and the specific assistance we propose.',sections:['founder.observation','founder.proposal']},
 {id:'readiness',title:'Investment readiness',question:'What should we check before investor conversations?',description:'Ask the founders for these records, check the numbers, then decide what needs fixing.',sections:['diligence.request_a','readiness.action_a','diligence.request_b','readiness.action_b']},
];
function stageStatus(pack:AnalystPack|undefined,keys:string[]){
 const rows=keys.map(key=>pack?.sections[key]);
 if(rows.every(s=>s?.status==='complete'))return 'Draft available';
 if(rows.some(s=>s&&['failed','needs_revision','review_failed','review_pending','blocked'].includes(s.status)))return 'Needs attention';
 return rows.some(s=>s?.status==='complete')?'Partial draft':'Not prepared';
}
export function PreparationSteps({pack,leadId,activeStage,onSelect}:{pack?:AnalystPack;leadId?:string;activeStage?:string;onSelect?:(id:string)=>void}){
 return <nav aria-label="Company preparation" className={`grid gap-3 ${onSelect?'md:grid-cols-3':'sm:grid-cols-3'}`}>{preparationStages.map((stage,index)=>{
  const body=<>{onSelect&&<span className="text-xs font-semibold text-indigo-600">STEP {index+1}</span>}<span className="mt-1 block font-semibold">{stage.title}</span><span className="mt-1 block text-xs text-slate-500">{stageStatus(pack,stage.sections)}</span></>;
  return onSelect?<button key={stage.id} onClick={()=>onSelect(stage.id)} aria-current={activeStage===stage.id?'step':undefined} className={`rounded-xl border p-4 text-left transition-colors ${activeStage===stage.id?'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-400':'border-slate-200 bg-white hover:border-indigo-200'}`}>{body}</button>:<Link key={stage.id} to={`/operations?lead=${leadId}&tab=${stage.id}`} className="rounded-lg bg-slate-50 p-3 text-sm hover:bg-indigo-50">{body}</Link>;
 })}</nav>;
}
export function NextPreparationLink({pack,leadId}:{pack?:AnalystPack;leadId:string}){
 const next=preparationStages.find(s=>stageStatus(pack,s.sections)!=='Draft available')||preparationStages[0];
 return <Link className="rounded-lg border border-indigo-200 px-4 py-2.5 text-sm font-semibold text-indigo-600" to={`/operations?lead=${leadId}&tab=${next.id}`}>{pack?'Continue preparation →':'Prepare company work →'}</Link>;
}
const labels:Record<string,string>={revenue_mechanism:'How the company earns money',unknown_economics:'What we still need to establish',reason_to_engage:'Why pursue this company',unresolved_risk:'What could weaken the case',next_decision:'The decision to make next',reported_observation:'Published context',question_to_explore:'What we want to explore',proposed_work:'The help we propose',invitation:'Suggested invitation',question:'Ask the founders',records_to_request:'Records needed',required_input:'Use these records',action:'Work to perform',output:'Deliverable',decision:'Decision this supports'};
const sectionTitles:Record<string,string>={'research.business':'The business','research.economics':'Revenue and economics','research.decision':'Investment case to investigate','founder.observation':'Context for the conversation','founder.proposal':'Proposed engagement'};
const panel='rounded-xl border border-slate-200 bg-white p-5 sm:p-6';

function WorkSection({section:s,sectionKey,pack,title}:{section?:Section;sectionKey:string;pack?:AnalystPack;title?:string}){
 const complete=s?.status==='complete';
 const name=title||sectionTitles[sectionKey]||s?.title||'Work to prepare';
 return <section className={panel}>
  <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{name}</h3><span className="text-xs text-slate-500">{complete?'AI draft':s?'Needs attention':'Not prepared'}</span></div>
  {complete?<>
   {s.evidence_status==='source_reported'&&<p className="mt-3 text-xs text-slate-500">Based on reported sources · not independently verified</p>}
   {Object.entries(s.content||{}).filter(([field,value])=>typeof value==='string'&&field!=='opening_source_id').map(([field,value])=>{
    const quoted=s.content?.source_quotes&&['text','revenue_mechanism'].includes(field);
    // Legacy quoted economics stays available in source details; the main
    // section is for the checked plain-language explanation, never a page dump.
    if(quoted&&field==='revenue_mechanism')return <p key={field} className="mt-4 text-sm text-slate-500">Published pricing and terms are in the source details below.</p>;
    return <div key={field} className="mt-4">{field!=='text'&&<h4 className="text-sm font-semibold">{quoted?'Published commercial terms':labels[field]||field.replaceAll('_',' ')}</h4>}{quoted?<><p className="mt-1 text-xs text-slate-500">Published source context · claims have not been independently verified</p>{s.content?.fact_ids.map(id=>pack?.record.facts.find(f=>f.id===id)).filter((f):f is Fact=>!!f).map(f=><blockquote key={f.id} className="mt-3 border-l-2 border-indigo-100 pl-3"><p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{s.content?.source_excerpt?.fact_id===f.id?s.content.source_excerpt.quote:f.quote}</p>{f.source_url&&<a href={f.source_url} target="_blank" rel="noreferrer" className="text-xs text-indigo-600">Read original source ↗</a>}</blockquote>)}</>:<p className="mt-1 whitespace-pre-wrap text-sm leading-7 text-slate-700">{String(value)}</p>}</div>;
   })}
   <details className="mt-5 text-sm text-slate-500"><summary className="cursor-pointer">Source passages and reported figures</summary>{pack?.record.facts.filter(f=>(s.content?.fact_ids||[]).includes(f.id)).map(f=><blockquote key={f.id} className="mt-4 border-l-2 border-indigo-100 pl-3"><p>{f.quote}</p><p className="mt-2 text-xs">{f.status==='calculated_from_supplied_inputs'?'Calculated from supplied figures':'Source-reported claim'} · retrieved {new Date(f.retrieved_at).toLocaleDateString()}{f.observed_at?` · observed ${new Date(f.observed_at).toLocaleDateString()}`:''}</p>{f.source_url?<a href={f.source_url} target="_blank" rel="noreferrer" className="text-indigo-600">Read original source ↗</a>:<p className="text-xs">Underlying records are available in Company figures.</p>}</blockquote>)}</details>
  </>:<><p className="mt-3 text-sm leading-6 text-slate-500">{!s?'This work has not been prepared yet.':s.status==='blocked'?'Required evidence or related work is still missing.':s.status==='review_pending'?'Saved work needs another review before it can be used.':'This draft needs correction before it can be used.'}</p>{s&&(s.error||s.review?.objections.length)?<details className="mt-3 text-sm text-slate-500"><summary className="cursor-pointer">See the issue</summary><p className="mt-2">{s.error}</p>{s.review?.objections.map((o,i)=><p key={i} className="mt-3">{o.correction}</p>)}</details>:null}</>}
 </section>;
}

export default function PreparationWorkspace({lead,workspace:w}:{lead:SourcedLead;workspace?:AnalystWorkspace}){
 const [params,setParams]=useSearchParams();const client=useQueryClient();const [copyState,setCopyState]=useState('');
 const requested=params.get('tab');const alias=requested==='pitch'?'founder':requested==='diligence'?'readiness':requested;
 const stage=preparationStages.find(s=>s.id===alias)||preparationStages[0];
 const current=w?.analyst_pack?.version===PREPARATION_VERSION&&w.analyst_pack.basis_hash===w.basis_hash;
 const pack=current?w?.analyst_pack:undefined;
 const busy=['queued','running'].includes(w?.automation?.status||'');
 const completeCount=Object.values(pack?.sections||{}).filter(s=>s.status==='complete').length;
 const allDrafts=pack?.status==='complete'&&preparationStages.every(s=>stageStatus(pack,s.sections)==='Draft available');
 const prepare=useMutation({mutationFn:(refresh:boolean)=>api.post(`/api/operations/leads/${lead.id}/preparation-jobs${refresh?'?refresh=true':''}`),onSuccess:()=>client.invalidateQueries({queryKey:['operations']})});
 const stop=useMutation({mutationFn:()=>api.post(`/api/operations/workspaces/${w?.id}/preparation-jobs/${w?.automation?.id}/stop`),onSuccess:()=>client.invalidateQueries({queryKey:['operations']})});
 const changeStage=(id:string)=>{const next=new URLSearchParams(params);next.set('tab',id);setParams(next,{replace:true});setCopyState('');};
 const copy=async()=>{try{await navigator.clipboard.writeText([pack?.sections['founder.proposal']?.content?.proposed_work,pack?.sections['founder.proposal']?.content?.invitation].filter(Boolean).join('\n\n'));setCopyState('Copied');}catch{setCopyState('Select the text below to copy it.');}};
 const downloads=stage.id==='readiness'?[['diligence','Records request'],['readiness','Proposed analysis']]:[[stage.id,stage.id==='research'?'Research memo':'Founder proposal']];
 return <div className="space-y-6">
  <Link to="/" className="text-sm text-slate-500">← My companies</Link>
  <header className="flex flex-wrap items-start justify-between gap-5"><div><h1 className="text-3xl font-semibold tracking-tight">{lead.company_name}</h1><p className="mt-2 text-slate-500">Research the opportunity. Propose your help. Prepare for investor conversations.</p>{lead.company_profile?.website&&<a href={lead.company_profile.website} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm text-indigo-600">Company website ↗</a>}</div><button disabled={busy||prepare.isPending||allDrafts} onClick={()=>prepare.mutate(false)} className="rounded-lg bg-indigo-600 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50">{busy?'Preparing company work…':allDrafts?'Drafts prepared':pack?'Resume preparation':'Prepare company work'}</button></header>
  {busy&&<div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-indigo-50 p-4"><p role="status" className="text-sm text-indigo-800">{w?.automation?.phase||'Starting preparation'} · {completeCount} sections saved</p>{w?.automation?.id&&<button disabled={stop.isPending} onClick={()=>stop.mutate()} className="text-sm font-semibold text-indigo-800">Stop preparation</button>}</div>}
  {w?.automation?.status==='cancelled'&&<p role="status" className="text-sm text-slate-600">Preparation stopped. Saved sections remain available. Resume when you are ready.</p>}
  {(prepare.error||stop.error)&&<p role="alert" className="text-sm text-rose-700">{prepare.error?.message||stop.error?.message}</p>}
  {!busy&&w?.automation?.status==='failed'&&<div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><p>Preparation is incomplete. Resume to correct unfinished work; saved drafts are retained.</p><details className="mt-2"><summary className="cursor-pointer">What needs attention</summary><p className="mt-2">{w.automation.error}</p></details></div>}
  {w?.analyst_pack&&!current&&<p className="rounded-xl bg-amber-50 p-4 text-sm">Company inputs changed, or the preparation method was updated. Prepare current work; previous drafts remain in company records.</p>}
  {pack?.record.coverage==='partial'&&<p className="text-sm text-slate-600">Source coverage is incomplete. Some content could not be collected or included; drafts use the retained source claims.</p>}
  <PreparationSteps pack={pack} activeStage={stage.id} onSelect={changeStage}/>
  <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-xl font-semibold">{stage.question}</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{stage.description}</p></div><div className="flex flex-wrap gap-3 text-sm font-semibold text-indigo-600">{stage.id==='founder'&&stageStatus(pack,stage.sections)==='Draft available'&&<button onClick={copy}>{copyState||'Copy proposal'}</button>}{downloads.filter(([doc])=>Object.values(pack?.sections||{}).some(s=>s.document===doc&&s.status==='complete')).map(([doc,label])=><a key={doc} href={`/api/operations/workspaces/${w?.id}/preparation-pack?document=${doc}`}>{label} ↓</a>)}</div></div>
  {stage.id==='founder'&&<p className="text-sm text-slate-500">Draft approach to the founders. No message has been sent.</p>}
  {stage.id==='readiness'?<>
   {['a','b'].map(suffix=><div key={suffix} className="grid items-start gap-4 lg:grid-cols-2"><WorkSection section={pack?.sections['diligence.request_'+suffix]} sectionKey={'diligence.request_'+suffix} pack={pack} title="Records to request"/><WorkSection section={pack?.sections['readiness.action_'+suffix]} sectionKey={'readiness.action_'+suffix} pack={pack} title="Proposed analysis"/></div>)}
   {w&&<details className={panel}><summary className="cursor-pointer font-semibold">Company figures</summary><p className="my-3 text-sm text-slate-500">Add company records to support revenue, cost and growth calculations.</p><CompanyMetrics workspaceId={w.id} revision={w.revision} metrics={w.metrics} imports={w.metric_imports} busy={busy}/></details>}
  </>:stage.sections.map(key=><WorkSection key={key} section={pack?.sections[key]} sectionKey={key} pack={pack}/>)}
  {pack&&<details className={panel}><summary className="cursor-pointer font-semibold">Company evidence · {pack.record.facts.length} source claims</summary><p className="mt-3 text-sm text-slate-500">Published claims may need corroboration. Missing public information is not proof of missing business activity.</p>{[...new Set(pack.record.facts.map(f=>f.category))].map(category=><div key={category} className="mt-5"><h3 className="text-sm font-semibold capitalize">{category.replaceAll('_',' ')}</h3>{pack.record.facts.filter(f=>f.category===category).map(f=><p key={f.id} className="mt-2 text-sm leading-6">{f.quote} {f.source_url&&<a className="text-indigo-600" href={f.source_url} target="_blank" rel="noreferrer">Source ↗</a>}</p>)}</div>)}</details>}
  <footer className="flex flex-wrap justify-between gap-3 border-t border-slate-200 pt-5 text-sm"><button disabled={busy||prepare.isPending} onClick={()=>prepare.mutate(true)} className="text-indigo-600 disabled:opacity-50">Refresh source research</button><Link to={`/operations?lead=${lead.id}&view=records`} className="text-slate-500">Company records & history →</Link></footer>
 </div>;
}
