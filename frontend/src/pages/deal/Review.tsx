import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useReview } from "../../api/hooks";
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
  const [citationBlockId, setCitationBlockId] = useState<string | null>(null);

  if (review.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (review.isError) return <p className="text-sm text-rose-600">{review.error.message}</p>;
  if (!review.data?.extraction_result) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        No extraction result yet -- ingest a document and run extraction from the directive bar above.
      </p>
    );
  }

  const result = review.data.extraction_result;
  const flaggedFields = new Set<string>();
  review.data.cross_check_flags.forEach((flag) => fieldsTouchedByFlag(flag).forEach((f) => flaggedFields.add(f)));

  return (
    <div className="flex flex-col gap-4">
      <div
        className={`rounded-lg border p-3 text-sm ${
          review.data.ready_for_compilation
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-slate-200 bg-slate-50 text-slate-600"
        }`}
      >
        {review.data.ready_for_compilation
          ? "Ready for compilation -- every required field has been resolved."
          : "Not yet ready for compilation -- resolve every flagged field below."}
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
        {SCALAR_FIELDS.map((field: ScalarField) => (
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
