import { useState } from "react";
import { Link } from "react-router-dom";
import { useDeals, useLeads } from "../api/hooks";
import PromptBar from "../components/PromptBar";
import StatusBadge from "../components/StatusBadge";
import type { DealStatus } from "../api/types";

const STATUS_FILTERS: { label: string; value: DealStatus | undefined }[] = [
  { label: "All", value: undefined },
  { label: "New", value: "new" },
  { label: "In progress", value: "extracted" },
  { label: "Reviewed", value: "reviewed" },
  { label: "Compiled", value: "compiled" },
];

export default function Dashboard() {
  const [statusFilter, setStatusFilter] = useState<DealStatus | undefined>(undefined);
  const deals = useDeals(statusFilter);
  const newLeads = useLeads("new");

  return (
    <div className="flex flex-col gap-6">
      <PromptBar />

      {!!newLeads.data?.length && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <Link to="/leads" className="font-medium underline underline-offset-2">
            {newLeads.data.length} sourced lead{newLeads.data.length === 1 ? "" : "s"} awaiting review
          </Link>
        </div>
      )}

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h1 className="text-lg font-semibold text-slate-900">Deals</h1>
          <div className="flex gap-1">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.label}
                onClick={() => setStatusFilter(f.value)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  statusFilter === f.value
                    ? "bg-indigo-600 text-white"
                    : "bg-white text-slate-600 hover:bg-slate-100"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {deals.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
        {deals.isError && <p className="text-sm text-rose-600">{deals.error.message}</p>}

        {deals.data && deals.data.length === 0 && (
          <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
            No deals yet. Source some leads, or ask the prompt bar above to screen a specific deal.
          </p>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {deals.data?.map((summary) => (
            <Link
              key={summary.deal.id}
              to={`/deals/${summary.deal.id}`}
              className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md"
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                <h2 className="font-medium text-slate-900">{summary.deal.name}</h2>
                <StatusBadge status={summary.deal.status} />
              </div>
              {summary.deal.stage && <p className="text-xs text-slate-500">{summary.deal.stage}</p>}
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500">
                <div className="flex justify-between">
                  <dt>Documents</dt>
                  <dd className="font-medium text-slate-700">{summary.document_count}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Findings</dt>
                  <dd className="font-medium text-slate-700">{summary.research_finding_count}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Documents built</dt>
                  <dd className="font-medium text-slate-700">{summary.memo_version_count}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Investors</dt>
                  <dd className="font-medium text-slate-700">{summary.investor_count}</dd>
                </div>
              </dl>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
