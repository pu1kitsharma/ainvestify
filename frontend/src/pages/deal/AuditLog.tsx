import { useOutletContext } from "react-router-dom";
import { useAuditLog } from "../../api/hooks";

const ACTION_LABELS: Record<string, string> = {
  approve: "approved",
  edit: "edited",
  reject: "rejected",
  acknowledge_not_found: "acknowledged not found",
};

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export default function AuditLog() {
  const { dealId } = useOutletContext<{ dealId: string }>();
  const audit = useAuditLog(dealId);

  if (audit.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (audit.isError) return <p className="text-sm text-rose-600">{audit.error.message}</p>;

  const events = [...(audit.data ?? [])].reverse(); // newest first

  if (events.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        No audit events yet -- every review decision is logged here as it happens.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {events.map((e) => (
        <div key={e.id} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-sm text-slate-800">
              <span className="font-medium">{e.actor}</span> {ACTION_LABELS[e.action] ?? e.action}{" "}
              <span className="font-mono text-xs text-slate-500">{e.target_id}</span>
            </p>
            <p className="whitespace-nowrap text-xs text-slate-400">{new Date(e.timestamp).toLocaleString()}</p>
          </div>
          {(e.before !== null || e.after !== null) && e.action === "edit" && (
            <p className="mt-1 text-xs text-slate-500">
              {formatValue(e.before)} → {formatValue(e.after)}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
