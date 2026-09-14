import { useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { useReview, useLeads, useSourceDocuments, useUploadDocument, useExtractDeal } from "../../api/hooks";
import CapTableCard from "../../components/CapTableCard";
import CitationDrawer from "../../components/CitationDrawer";
import FieldCard from "../../components/FieldCard";
import FundingHistoryCard from "../../components/FundingHistoryCard";
import { SCALAR_FIELDS, SCALAR_FIELD_LABELS } from "../../api/types";
import type { ScalarField } from "../../api/types";

function fieldsTouchedByFlag(flag: string): Set<string> {
  const touched = new Set<string>();
  if (flag.includes("runway_months")) ["runway_months", "cash_on_hand", "burn_monthly"].forEach((f) => touched.add(f));
  if (flag.includes("growth_rate_yoy")) ["growth_rate_yoy", "arr", "arr_prior_year"].forEach((f) => touched.add(f));
  if (flag.includes("cap_table")) touched.add("cap_table");
  return touched;
}

export default function Review() {
  const { dealId } = useOutletContext<{ dealId: string }>();
  const review = useReview(dealId);
  const leads = useLeads();
  const lead = leads.data?.find(l => l.promoted_deal_id === dealId);
  const documents = useSourceDocuments(dealId);
  const upload = useUploadDocument(dealId);
  const extract = useExtractDeal(dealId);
  const [file, setFile] = useState<File | null>(null);
  const companyLink = lead ? `/operations?lead=${lead.id}` : "/operations";
  const [citationBlockId, setCitationBlockId] = useState<string | null>(null);

  if (review.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (review.isError) return <p className="text-sm text-rose-600">{review.error.message}</p>;
  const sourceControls = <section className="rounded-xl border border-slate-200 bg-white p-6"><h2 className="text-lg font-semibold">Check figures from company documents</h2><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">This page checks whether extracted numbers match their source documents before they are used in deal materials. It does not assess whether the company is worth investing in.</p><Link to={companyLink} className="mt-3 inline-block text-sm font-semibold text-indigo-600">Back to company research, metrics & pitch →</Link><div className="mt-5 border-t border-slate-100 pt-4"><p className="text-sm text-slate-600">Use a company financial report or existing deck. A generated company brief is not financial evidence.</p><label className="mt-3 block text-sm">Company document<input type="file" accept=".pdf,.xlsx,.xlsm" onChange={e=>setFile(e.target.files?.[0] || null)} className="mt-2 block max-w-full text-xs" /></label><button disabled={!file || upload.isPending || extract.isPending} onClick={()=>file && upload.mutate(file)} className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{upload.isPending ? "Reading document…" : "Add document"}</button>{!!documents.data?.length && <div className="mt-4"><p className="text-xs text-slate-500">Extraction uses the first source document: {documents.data[0].filename}</p><button disabled={extract.isPending || upload.isPending} onClick={()=>extract.mutate({})} className="mt-2 text-sm font-semibold text-indigo-600 disabled:opacity-50">{extract.isPending ? "Extracting figures…" : "Extract document figures"}</button></div>}{(upload.error || extract.error) && <p role="alert" className="mt-3 text-sm text-rose-700">{(upload.error || extract.error)?.message}</p>}</div></section>;
  if (!review.data?.extraction_result) return sourceControls;

  const result = review.data.extraction_result;
  const flaggedFields = new Set<string>();
  review.data.cross_check_flags.forEach((flag) => fieldsTouchedByFlag(flag).forEach((f) => flaggedFields.add(f)));

  return (
    <div className="flex flex-col gap-4">
      {sourceControls}
      <div
        className={`rounded-lg border p-3 text-sm ${
          review.data.ready_for_compilation
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-slate-200 bg-slate-50 text-slate-600"
        }`}
      >
        {review.data.ready_for_compilation
          ? "Document checks complete. These figures can support draft materials; this does not establish investment readiness."
          : "Some document figures still need review before they can be used in materials."}
      </div>

      {review.data.cross_check_flags.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <p className="mb-1 font-medium">Cross-check flags</p>
          <ul className="list-inside list-disc space-y-0.5">
            {review.data.cross_check_flags.map((flag, i) => (
              <li key={i}>{flag}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {SCALAR_FIELDS.filter(field => result[field].value !== null || flaggedFields.has(field)).map((field: ScalarField) => (
          <FieldCard
            key={field}
            dealId={dealId}
            field={field}
            label={SCALAR_FIELD_LABELS[field]}
            value={result[field]}
            flagged={flaggedFields.has(field)}
            onCiteClick={setCitationBlockId}
          />
        ))}
      </div>

      <details className="rounded-lg border border-slate-200 p-4"><summary className="cursor-pointer text-sm text-slate-600">Fields not found in the document</summary><p className="mt-2 text-xs text-slate-500">Missing means unavailable, not zero. ARR and MRR apply to recurring revenue businesses.</p><div className="mt-3 grid gap-3 sm:grid-cols-2">{SCALAR_FIELDS.filter(field => result[field].value === null && !flaggedFields.has(field)).map(field=><FieldCard key={field} dealId={dealId} field={field} label={SCALAR_FIELD_LABELS[field]} value={result[field]} flagged={false} onCiteClick={setCitationBlockId} />)}</div></details>

      <CapTableCard
        dealId={dealId}
        rows={result.cap_table}
        status={result.cap_table_status}
        sourceBlockId={result.cap_table_source_block_id}
        reviewedAt={result.cap_table_reviewed_at}
      />
      <FundingHistoryCard
        dealId={dealId}
        rounds={result.funding_history}
        status={result.funding_history_status}
        reviewedAt={result.funding_history_reviewed_at}
      />

      <CitationDrawer dealId={dealId} blockId={citationBlockId} onClose={() => setCitationBlockId(null)} />
    </div>
  );
}
