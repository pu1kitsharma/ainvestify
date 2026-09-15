import { useState } from "react";

export default function WebSourcing({ initialThesis = "", initialGeography = "", busy, starting, stopping, onSearch, onCancel, error }: {
  initialThesis?: string; initialGeography?: string; busy: boolean; starting: boolean; stopping: boolean;
  onSearch: (brief: string, geography: string) => void; onCancel: () => void; error?: string;
}) {
  const [thesis, setThesis] = useState(initialThesis);
  const [geography, setGeography] = useState(initialGeography);
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
    <form onSubmit={e => { e.preventDefault(); onSearch(thesis.trim(), geography.trim()); }}>
      <label htmlFor="company-brief" className="block text-sm font-semibold text-slate-800">What companies are you looking for?</label>
      <textarea id="company-brief" value={thesis} onChange={e => setThesis(e.target.value)} rows={2} maxLength={2000}
        placeholder="Describe the sector, stage or problem they solve…" required
        className="mt-2 block w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-3 text-base outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <label htmlFor="company-geography" className="block text-xs font-medium text-slate-500">Geography
          <input id="company-geography" value={geography} onChange={e => setGeography(e.target.value)} maxLength={120} placeholder="Worldwide"
            className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-800 outline-none focus:border-indigo-500 sm:w-56" />
        </label>
        <div className="flex items-center gap-3">
          {busy && <button type="button" disabled={stopping} onClick={onCancel} className="rounded-lg px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50">{stopping ? "Stopping…" : "Stop search"}</button>}
          <button type="submit" disabled={busy || starting || thesis.trim().length < 3}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:opacity-50">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>
            {starting ? "Starting search…" : busy ? "Searching…" : "Find companies"}
          </button>
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500">AI searches public sources and assesses the results. Preparation starts automatically for the first company found.</p>
      {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
    </form>
  </section>;
}
