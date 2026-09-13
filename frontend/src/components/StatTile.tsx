import { formatFieldValue } from "../lib/format";
import type { StructuredFinancialField } from "../api/types";

/** Read-only presentation of one financial field inside a compiled document
 * (CIM/Teaser) -- distinct from FieldCard, which is the *editable* review-
 * screen version of the same underlying value. */
export default function StatTile({ field }: { field: StructuredFinancialField }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <p className="text-xs font-medium text-slate-500">{field.label}</p>
      {field.status === "not_found" ? (
        <p className="text-lg font-semibold text-slate-400">Not disclosed</p>
      ) : (
        <>
          <p className="text-lg font-semibold text-slate-900">{formatFieldValue(field.value, field.unit)}</p>
          {field.edited && <p className="text-[11px] text-sky-600">reviewer-edited</p>}
          {field.show_source && field.source_block_id && (
            <p className="mt-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
              source: {field.source_block_id}
              {field.source_page ? `, p.${field.source_page}` : ""}
            </p>
          )}
        </>
      )}
    </div>
  );
}
