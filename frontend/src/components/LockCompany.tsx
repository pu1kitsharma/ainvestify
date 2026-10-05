import {useState, type FormEvent} from 'react';
import {useMutation, useQueryClient} from '@tanstack/react-query';
import {api} from '../api/client';
import {mandateTypes} from './mandate';

export default function LockCompany({leadId, company}: {leadId: string; company: string}) {
 const client = useQueryClient();
 const [type, setType] = useState(mandateTypes[0].value);
 const [terms, setTerms] = useState('');
 const lock = useMutation({
  mutationFn: () => api.post(`/api/leads/${encodeURIComponent(leadId)}/lock`, {mandate_type: type, terms_summary: terms.trim()}),
  onSuccess: () => Promise.all([client.invalidateQueries({queryKey: ['leads']}), client.invalidateQueries({queryKey: ['deal']})]),
 });
 const submit = (event: FormEvent) => {event.preventDefault(); lock.mutate();};
 const hint = mandateTypes.find(item => item.value === type)?.hint;

 return <section aria-label="Lock company" className="rounded-xl border border-slate-200 bg-white p-6">
  <p className="text-xs font-semibold uppercase tracking-wide text-indigo-600">Step 4 · Locked until you decide</p>
  <h2 className="mt-1 text-xl font-semibold tracking-tight">Lock {company} to prepare investor materials</h2>
  <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
   Research and the founder pitch come first. Locking is your decision to engage this company: it records the engagement and opens a private
   deal room, where the intro deck, pitch deck and investment memo are prepared. Nothing is prepared before you lock.</p>
  <form onSubmit={submit} className="mt-5 max-w-2xl space-y-4">
   <fieldset>
    <legend className="text-sm font-medium text-slate-800">Engagement</legend>
    <div className="mt-2 grid gap-2 sm:grid-cols-3">
     {mandateTypes.map(item => <label key={item.value} className={`cursor-pointer rounded-lg border p-3 text-sm transition ${type === item.value ? 'border-indigo-400 bg-indigo-50' : 'border-slate-200 hover:bg-slate-50'}`}>
      <input type="radio" name="mandate" className="sr-only" checked={type === item.value} onChange={() => setType(item.value)}/>
      <span className="font-medium">{item.label}</span></label>)}
    </div>
    <p className="mt-2 text-xs text-slate-500">{hint}</p>
   </fieldset>
   <label className="block text-sm font-medium text-slate-800">What was agreed
    <textarea value={terms} onChange={event => setTerms(event.target.value)} required minLength={10} maxLength={1000} rows={3}
     placeholder="Scope, term and fee basis in a sentence or two"
     className="mt-1.5 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"/></label>
   {lock.error && <p role="alert" className="text-sm text-rose-700">{lock.error.message}</p>}
   <div className="flex flex-wrap items-center gap-4">
    <button type="submit" disabled={lock.isPending || terms.trim().length < 10}
     className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300">
     {lock.isPending ? 'Locking…' : 'Lock company'}</button>
    <p className="text-xs text-slate-500">This records your decision. It sends nothing to the company or to investors.</p>
   </div>
  </form>
 </section>;
}
