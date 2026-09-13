const STATUS_STYLES: Record<string, string> = {
  new: "bg-slate-100 text-slate-700",
  mandate_signed: "bg-sky-100 text-sky-700",
  ingested: "bg-sky-100 text-sky-700",
  extracted: "bg-amber-100 text-amber-700",
  reviewed: "bg-emerald-100 text-emerald-700",
  needs_manual_input: "bg-rose-100 text-rose-700",
  researched: "bg-amber-100 text-amber-700",
  research_reviewed: "bg-emerald-100 text-emerald-700",
  compiled: "bg-indigo-100 text-indigo-700",
  // Lead statuses
  reviewed_lead: "bg-emerald-100 text-emerald-700",
  promoted_to_deal: "bg-indigo-100 text-indigo-700",
  dismissed: "bg-slate-100 text-slate-500",
  // Field statuses
  proposed: "bg-slate-100 text-slate-700",
  approved: "bg-emerald-100 text-emerald-700",
  edited: "bg-sky-100 text-sky-700",
  rejected: "bg-rose-100 text-rose-700",
  not_found: "bg-slate-100 text-slate-500",
};

export default function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
