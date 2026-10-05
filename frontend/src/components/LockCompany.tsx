import {useMutation, useQueryClient} from '@tanstack/react-query';
import {api} from '../api/client';

export default function LockCompany({leadId, company}: {leadId: string; company: string}) {
 const client = useQueryClient();
 const lock = useMutation({
  mutationFn: () => api.post(`/api/leads/${encodeURIComponent(leadId)}/lock`, {}),
  onSuccess: () => Promise.all([client.invalidateQueries({queryKey: ['leads']}), client.invalidateQueries({queryKey: ['deal']})]),
 });
 return <section aria-label="Lock company" className="rounded-xl border border-slate-200 bg-white p-6">
  <h2 className="text-xl font-semibold tracking-tight">Ready to engage {company}?</h2>
  <p className="mt-2 max-w-xl text-sm leading-6 text-slate-600">
   Lock the company once research and the founder pitch have convinced you. This opens its private deal room and starts the
   intro deck, pitch deck and investment memo. Nothing is sent to the company or to investors.</p>
  {lock.error && <p role="alert" className="mt-3 text-sm text-rose-700">{lock.error.message}</p>}
  <button type="button" disabled={lock.isPending} onClick={() => lock.mutate()}
   className="mt-5 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60">
   {lock.isPending ? 'Locking…' : 'Lock company'}</button>
 </section>;
}
