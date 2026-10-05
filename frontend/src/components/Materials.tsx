import {useState} from 'react';

export type MaterialFile = {id: string; kind: string; format: string; input_revision: string};

const docs = [
 {key: 'intro_deck', title: 'Intro deck', note: 'Short first look for investors', editable: 'PPTX'},
 {key: 'pitch_deck', title: 'Pitch deck', note: 'Full story, market and ask', editable: 'PPTX'},
 {key: 'investment_memorandum', title: 'Investment memo', note: 'Cited analysis and open questions', editable: 'DOCX'},
];

const baseKind = (kind: string) => kind.replace(/_preview$/, '');

export default function Materials({roomId, files}: {roomId: string; files: MaterialFile[]}) {
 const available = docs.map(doc => {
  const mine = files.filter(file => baseKind(file.kind) === doc.key);
  return {...doc, pdf: mine.find(file => file.format === 'pdf'), editableFile: mine.find(file => file.format !== 'pdf')};
 });
 const [selected, setSelected] = useState<string | null>(null);
 const active = available.find(doc => doc.key === selected && doc.pdf) ?? available.find(doc => doc.pdf);
 const url = (id: string, inline: boolean) => `/api/rooms/${roomId}/artifacts/${id}/preview${inline ? '?inline=1' : ''}`;

 return <section aria-label="Investor materials" className="mb-6">
  <div className="flex flex-wrap items-end justify-between gap-2">
   <div><h2 className="text-xl font-semibold tracking-tight">Investor materials</h2>
    <p className="mt-1 text-sm text-slate-500">Each document as a PDF and an editable file.</p></div>
   <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-900">Drafts · not reviewed or approved</span>
  </div>

  <div className="mt-4 grid gap-3 md:grid-cols-3">
   {available.map(doc => {
    const ready = !!doc.pdf;
    const isActive = active?.key === doc.key;
    return <article key={doc.key} className={`rounded-xl border bg-white p-4 transition ${isActive ? 'border-indigo-400 ring-2 ring-indigo-100' : 'border-slate-200'}`}>
     <div className="flex items-start justify-between gap-2">
      <h3 className="font-semibold">{doc.title}</h3>
      <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${ready ? 'bg-emerald-50 text-emerald-800' : 'bg-slate-100 text-slate-500'}`}>{ready ? 'Draft ready' : 'Not generated'}</span>
     </div>
     <p className="mt-1 text-sm text-slate-500">{doc.note}</p>
     <div className="mt-4 flex flex-wrap gap-2">
      <button type="button" disabled={!ready} onClick={() => setSelected(doc.key)}
       className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500">
       {isActive && ready ? 'Viewing' : 'View PDF'}</button>
      {doc.editableFile && <a href={url(doc.editableFile.id, false)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50">Download {doc.editable}</a>}
      {doc.pdf && <a href={url(doc.pdf.id, true)} target="_blank" rel="noreferrer" className="rounded-lg px-2 py-1.5 text-sm text-indigo-700 hover:underline">Open in tab ↗</a>}
     </div>
    </article>;
   })}
  </div>

  {active?.pdf ? <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
   <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm">
    <span className="font-medium">{active.title} · PDF preview</span>
    <span className="text-xs text-slate-500">Private draft</span>
   </div>
   <iframe key={active.pdf.id} title={`${active.title} PDF preview`} src={url(active.pdf.id, true)} className="h-[78vh] w-full bg-slate-100"/>
  </div> : <p className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">No materials have been generated for this company yet.</p>}
 </section>;
}
