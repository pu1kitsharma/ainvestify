import { useState } from "react";
import { isReviewConflict, useFieldDecision } from "../api/hooks";
import type { ExtractedValue } from "../api/types";
import { formatFieldValue } from "../lib/format";
import StatusBadge from "./StatusBadge";

function formatValue(ev: ExtractedValue): string {
  return formatFieldValue(ev.value, ev.unit);
}

export default function FieldCard({
  dealId,
  field,
  label,
  value,
  flagged,
  onCiteClick,
}: {
  dealId: string;
  field: string;
  label: string;
  value: ExtractedValue;
  flagged?: boolean;
  onCiteClick?: (blockId: string) => void;
}) {
  const [mode, setMode] = useState<"view" | "edit" | "reject">("view");
  const [newValue, setNewValue] = useState(value.value?.toString() ?? "");
  const [note, setNote] = useState("");
  const decision = useFieldDecision(dealId);

  const notFound = value.status === "not_found";
  const outcome = decision.data?.outcome;
  const conflict = isReviewConflict(decision.error);

  function reset() {
    setMode("view");
    setNote("");
    decision.reset();
  }

  function submitDecision(d: "approve" | "edit" | "reject" | "acknowledge") {
    decision.mutate(
      { field, decision: d, newValue: d === "edit" ? newValue : undefined, note: note || undefined },
      {
        onSuccess: (res) => {
          if (res.outcome.resolved) reset();
          // resolved=false (bad edit value, or a reject that triggered a
          // retry) -- stay in the current mode so the outcome.message
          // renders and the user can act on it (fix the value, or just
          // look at the freshly retried field before deciding again).
        },
      },
    );
  }

  return (
    <div
      className={`rounded-lg border bg-white p-3 shadow-sm ${
        flagged ? "border-amber-300 ring-1 ring-amber-200" : "border-slate-200"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className="text-lg font-semibold text-slate-900">{formatValue(value)}</p>
        </div>
        <StatusBadge status={value.status} />
      </div>

      {flagged && <p className="mt-1 text-xs text-amber-700">Cross-check mismatch -- review individually.</p>}
      {value.edit_note && <p className="mt-1 text-xs text-slate-500">Note: {value.edit_note}</p>}

      {value.source_block_id && (
        <button
          onClick={() => onCiteClick?.(value.source_block_id!)}
          className="mt-2 inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 hover:bg-slate-200"
        >
          source: {value.source_block_id}
          {value.source_page ? `, p.${value.source_page}` : ""}
        </button>
      )}

      {conflict && (
        <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-700">
          This deal changed elsewhere while processing your request -- refresh and try again.
        </p>
      )}
      {outcome?.message && !conflict && (
        <p className="mt-2 rounded bg-slate-50 p-2 text-xs text-slate-600">{outcome.message}</p>
      )}

      {mode === "view" && (
        <div className="mt-3 flex gap-2">
          {notFound ? (
            <>
              <button onClick={() => submitDecision("acknowledge")} className={btnPrimary}>
                Acknowledge
              </button>
              <button onClick={() => setMode("edit")} className={btnSecondary}>
                Supply manually
              </button>
            </>
          ) : (
            <>
              <button onClick={() => submitDecision("approve")} className={btnPrimary}>
                Approve
              </button>
              <button onClick={() => setMode("edit")} className={btnSecondary}>
                Edit
              </button>
              <button onClick={() => setMode("reject")} className={btnDanger}>
                Reject
              </button>
            </>
          )}
        </div>
      )}

      {mode === "edit" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submitDecision("edit");
          }}
          className="mt-3 flex flex-col gap-2"
        >
          <input
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder="New value"
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            autoFocus
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Edit note (optional)"
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
          <div className="flex gap-2">
            <button type="submit" disabled={decision.isPending} className={btnPrimary}>
              Save
            </button>
            <button type="button" onClick={reset} className={btnSecondary}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {mode === "reject" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submitDecision("reject");
          }}
          className="mt-3 flex flex-col gap-2"
        >
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What's wrong with this value?"
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            autoFocus
          />
          <div className="flex gap-2">
            <button type="submit" disabled={decision.isPending} className={btnDanger}>
              {decision.isPending ? "Re-checking…" : "Reject & retry"}
            </button>
            <button type="button" onClick={reset} className={btnSecondary}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

const btnPrimary =
  "rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50";
const btnSecondary =
  "rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50";
const btnDanger =
  "rounded-md bg-rose-600 px-3 py-1 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50";
