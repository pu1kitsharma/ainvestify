import { useState } from "react";
import { isReviewConflict, useFundingHistoryDecision } from "../api/hooks";
import type { FieldStatus, FundingRound } from "../api/types";
import StatusBadge from "./StatusBadge";

export default function FundingHistoryCard({
  dealId,
  rounds,
  status,
  reviewedAt,
}: {
  dealId: string;
  rounds: FundingRound[];
  status: FieldStatus;
  reviewedAt: string | null;
}) {
  const [mode, setMode] = useState<"view" | "reject">("view");
  const [note, setNote] = useState("");
  const decision = useFundingHistoryDecision(dealId);
  const conflict = isReviewConflict(decision.error);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Funding History</h3>
        <StatusBadge status={status} />
      </div>

      {rounds.length === 0 ? (
        <>
          <p className="text-sm text-slate-500">No approved funding history for this deal.</p>
          {/* Same reasoning as CapTableCard: an empty table still needs an
              explicit acknowledgement call or is_ready_for_compilation()
              never clears. */}
          {!reviewedAt && (
            <button
              onClick={() => decision.mutate({ decision: "approve" })}
              disabled={decision.isPending}
              className="mt-3 rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              Acknowledge not disclosed
            </button>
          )}
        </>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="pb-1 font-medium">Round</th>
                <th className="pb-1 font-medium">Amount</th>
                <th className="pb-1 font-medium">Date</th>
                <th className="pb-1 font-medium">Lead</th>
              </tr>
            </thead>
            <tbody>
              {rounds.map((r, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="py-1 text-slate-800">{r.round_name ?? "—"}</td>
                  <td className="py-1 text-slate-800">
                    {r.amount !== null ? `$${r.amount.toLocaleString()}` : "—"}
                  </td>
                  <td className="py-1 text-slate-500">{r.date ?? "—"}</td>
                  <td className="py-1 text-slate-500">{r.lead_investor ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {conflict && (
            <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-700">
              This deal changed elsewhere while processing your request -- refresh and try again.
            </p>
          )}
          {decision.data?.outcome.message && !conflict && (
            <p className="mt-2 rounded bg-slate-50 p-2 text-xs text-slate-600">{decision.data.outcome.message}</p>
          )}

          {mode === "view" ? (
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => decision.mutate({ decision: "approve" })}
                className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-500"
              >
                Approve
              </button>
              <button
                onClick={() => setMode("reject")}
                className="rounded-md bg-rose-600 px-3 py-1 text-xs font-medium text-white hover:bg-rose-500"
              >
                Reject
              </button>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                decision.mutate(
                  { decision: "reject", note },
                  { onSuccess: (res) => res.outcome.resolved && setMode("view") },
                );
              }}
              className="mt-3 flex flex-col gap-2"
            >
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What's wrong with the funding history?"
                className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={decision.isPending}
                  className="rounded-md bg-rose-600 px-3 py-1 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
                >
                  {decision.isPending ? "Re-checking…" : "Reject & retry"}
                </button>
                <button
                  type="button"
                  onClick={() => setMode("view")}
                  className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </div>
  );
}
