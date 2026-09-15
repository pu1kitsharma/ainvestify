import {useState} from 'react';
import type {ReactNode} from 'react';
import type {ReadableCheck} from './readinessText';

export default function ReadinessCheck({check,index,details}:{check:ReadableCheck;index:number;details:ReactNode}){
 const [copied,setCopied]=useState(false);
 const copy=async()=>{try{await navigator.clipboard.writeText(`Could you share the following records for ${check.service}?\n\n${check.request.map(s=>'- '+s).join('\n')}`);setCopied(true);}catch{setCopied(false);}};
 return <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
  <p className="text-xs font-semibold uppercase tracking-wide text-indigo-600">Check {index+1} · Work to do</p>
  <h3 className="mt-2 text-lg font-semibold">{check.title}</h3>
  <p className="mt-2 text-sm leading-6 text-slate-600">{check.purpose}</p>
  <div className="mt-5 grid gap-6 lg:grid-cols-2">
   <div><h4 className="font-semibold text-sm">Ask the founders for</h4><ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-6 text-slate-700">{check.request.map(s=><li key={s}>{s}</li>)}</ul><button onClick={copy} className="mt-3 text-sm font-semibold text-indigo-600">{copied?'Copied request':'Copy records request'}</button></div>
   <div><h4 className="font-semibold text-sm">What to do with the records</h4><ol className="mt-2 list-decimal space-y-2 pl-5 text-sm leading-6 text-slate-700">{check.steps.map(s=><li key={s}>{s}</li>)}</ol></div>
  </div>
  <div className="mt-5 rounded-lg bg-slate-50 p-4"><h4 className="text-sm font-semibold">What this helps decide</h4><p className="mt-1 text-sm leading-6 text-slate-700">{check.result}</p><p className="mt-2 text-sm leading-6 text-slate-600">{check.limit}</p></div>
  <details className="mt-5"><summary className="cursor-pointer text-sm text-slate-500">Full calculation method and sources</summary><p className="my-4 text-sm text-slate-600">Service being checked: {check.service}</p><div className="grid items-start gap-4 lg:grid-cols-2">{details}</div></details>
 </section>;
}
