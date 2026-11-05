import {useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {api} from '../api/client';

type BaselineRow = {id: string; meaning: Record<string, string>; value: number | null; source_id: string | null;
 reason: string; conflict: boolean; status: string;
 candidates: {id: string; value: string; document: string; location: string; unsafe: boolean}[]};
type Ledger = {baseline: {rows: BaselineRow[]}; export_review: string;
 exceptions: {kind: string; document?: string; page?: number; detail: string}[];
 occurrences: {document: string; page: number; slot: string; figure: string; status: string; detail?: string;
 expression?: unknown; sources: {id: string; document: string; location: string; observation_sha256: string}[]}[]};

function SourceChoice({row, roomId, enabled}: {row: BaselineRow; roomId: string; enabled: boolean}) {
 const client = useQueryClient();
 const [source, setSource] = useState(row.source_id ?? '');
 const [reason, setReason] = useState('');
 const [editMapping, setEditMapping] = useState(false);
 const [mapping, setMapping] = useState({metric: row.meaning.metric, period: row.meaning.period, unit: row.meaning.unit,
  basis: row.meaning.basis, segment: row.meaning.segment, definition: row.meaning.definition,
  case: row.meaning.case, version: row.meaning.version, perimeter: row.meaning.perimeter,
  financial_role: row.meaning.financial_role ?? '', cost_boundary: row.meaning.cost_boundary ?? ''});
 const choice = useMutation({
  mutationFn: () => api.post(`/api/rooms/${roomId}/deal-documents/baseline-choice`, {row_id: row.id, source_id: source, reason, ...(editMapping ? {mapping} : {})}),
  onSuccess: () => {client.invalidateQueries({queryKey: ['deal-documents', roomId]}); client.invalidateQueries({queryKey: ['source-ledger', roomId]});},
 });
 return <div className="rounded border border-slate-200 p-3 text-sm">
  <p className="font-medium">{row.meaning.metric} · {row.meaning.period} · {row.meaning.basis} · {row.meaning.unit}</p>
  <p className="mt-1 text-xs text-slate-600">{row.meaning.segment} {row.meaning.case} {row.meaning.version}</p>
  <p className="mt-1">{row.source_id ? `${row.value} — ${row.source_id}` : 'Unresolved'}</p>
  <p className="text-xs text-slate-600">{row.reason}</p>
  <ul className="mt-2 text-xs">{row.candidates.map(candidate => <li key={candidate.id}>
   {candidate.value} — {candidate.document}, {candidate.location} [{candidate.id}]{candidate.unsafe && ' — requires verified inputs'}
  </li>)}</ul>
  {enabled && <div className="mt-2 space-y-2">
   <select aria-label={`Source for ${row.meaning.metric} ${row.meaning.period}`} value={source} onChange={event => setSource(event.target.value)} className="w-full rounded border p-1">
    <option value="">Choose a verified source</option>
    {row.candidates.map(candidate => <option key={candidate.id} value={candidate.id} disabled={candidate.unsafe && !editMapping}>{candidate.id}: {candidate.value}</option>)}
   </select>
   <label className="block text-xs"><input type="checkbox" checked={editMapping} onChange={event => setEditMapping(event.target.checked)}/> Review row mapping and definitions</label>
   {editMapping && <div className="grid gap-2 sm:grid-cols-2">{Object.entries(mapping).map(([field, value]) => <label key={field} className="text-xs">{field}
    <input aria-label={`Mapped ${field}`} value={value} onChange={event => setMapping({...mapping, [field]: event.target.value})} className="block w-full rounded border p-1"/>
   </label>)}</div>}
   <input aria-label="Reason for source choice" value={reason} onChange={event => setReason(event.target.value)} placeholder="Why this source should win" className="w-full rounded border p-1"/>
   <button type="button" disabled={!source || reason.trim().length < 10 || choice.isPending} onClick={() => choice.mutate()}
    className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50">Save choice and regenerate memorandum</button>
   {choice.error && <p role="alert" className="text-rose-700">{choice.error.message}</p>}
  </div>}
 </div>;
}

export default function SourceLedger({roomId, canEdit, decks}: {roomId: string; canEdit: boolean; decks: boolean}) {
 const report = useQuery({queryKey: ['source-ledger', roomId, decks], queryFn: () => api.get<Ledger | null>(`/api/rooms/${roomId}/deal-documents/ledger?decks=${decks}`), refetchInterval: 10000});
 if (report.error) return <p role="alert" className="text-sm text-rose-700">{report.error.message}</p>;
 if (!report.data) return null;
 const ledger = report.data;
 return <details className="mt-4 rounded-lg border border-slate-200 p-3">
  <summary className="cursor-pointer text-sm font-medium">Financial baseline and number tie-out · {ledger.occurrences.length} occurrences · {ledger.exceptions.length} exceptions</summary>
  <p className="mt-2 text-xs text-amber-800">{ledger.export_review}</p>
  <a className="mt-2 inline-block text-sm text-indigo-700 underline" href={`/api/rooms/${roomId}/deal-documents/files/${decks ? 'deck_source_ledger.json' : 'source_ledger.json'}`}>Download source ledger</a>
  <div className="mt-3 space-y-2">{ledger.baseline.rows.map(row => <SourceChoice key={row.id} row={row} roomId={roomId} enabled={canEdit}/>)}</div>
  {ledger.exceptions.length > 0 && <ul className="mt-3 list-disc pl-5 text-xs text-rose-800">{ledger.exceptions.map((item, i) => <li key={i}>{item.document} {item.page} · {item.kind}: {item.detail}</li>)}</ul>}
  <div className="mt-3 max-h-96 overflow-auto"><table className="w-full text-left text-xs">
   <thead><tr><th>Document / page</th><th>Occurrence</th><th>Figure</th><th>Source / workings</th></tr></thead>
   <tbody>{ledger.occurrences.map((row, i) => <tr key={i} className="border-t align-top">
    <td className="p-1">{row.document} / {row.page}</td><td className="p-1">{row.slot}</td><td className="p-1">{row.figure} ({row.status})</td>
    <td className="p-1">{row.detail ?? JSON.stringify(row.expression)}{row.sources.map(source => <p key={source.id}>{source.id}: {source.document}, {source.location}<br/>Observation SHA256: {source.observation_sha256}</p>)}</td>
   </tr>)}</tbody>
  </table></div>
 </details>;
}
