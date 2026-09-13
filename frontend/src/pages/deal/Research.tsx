import { useOutletContext } from "react-router-dom";
import {
  useFindingDecision,
  useMarkResearchReviewed,
  useResearchFindings,
} from "../../api/hooks";
import StatusBadge from "../../components/StatusBadge";
import type { ResearchFinding } from "../../api/types";

export default function Research() {
  const { dealId } = useOutletContext<{ dealId: string }>();
  const findings = useResearchFindings(dealId);
  const decision = useFindingDecision(dealId);
  const markReviewed = useMarkResearchReviewed(dealId);

  if (findings.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (findings.isError) return <p className="text-sm text-rose-600">{findings.error.message}</p>;

  const data = findings.data ?? [];
  if (data.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        No research yet -- use the directive bar above ("research" or "rerun_research") to run it.
      </p>
    );
  }

  const sourcingSignals = data.filter((f) => f.topic === "sourcing_signal");
  const liveFindings = data.filter((f) => f.topic !== "sourcing_signal");
  const allDecided = data.every((f) => f.status !== "proposed");

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          External corroborating signal -- supporting context, never blended with the deal's own cited
          financials.
        </p>
        <button
          onClick={() => markReviewed.mutate()}
          disabled={!allDecided || markReviewed.isPending}
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          title={allDecided ? undefined : "Decide on every finding first"}
        >
          Mark research reviewed
        </button>
      </div>

      {sourcingSignals.length > 0 && (
        <FindingSection
          title="From the original sourcing signal"
          findings={sourcingSignals}
          onDecide={(findingId, d) => decision.mutate({ findingId, decision: d })}
          pending={decision.isPending}
        />
      )}
      {liveFindings.length > 0 && (
        <FindingSection
          title="Live lookups"
          findings={liveFindings}
          onDecide={(findingId, d) => decision.mutate({ findingId, decision: d })}
          pending={decision.isPending}
        />
      )}
    </div>
  );
}

function FindingSection({
  title,
  findings,
  onDecide,
  pending,
}: {
  title: string;
  findings: ResearchFinding[];
  onDecide: (findingId: string, decision: "approve" | "reject") => void;
  pending: boolean;
}) {
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">{title}</h2>
      <div className="flex flex-col gap-2">
        {findings.map((f) => (
          <div key={f.id} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex items-start justify-between gap-2">
              <p className="text-xs font-medium text-slate-500">
                [{f.source_type}] {f.topic}
              </p>
              <StatusBadge status={f.status} />
            </div>
            <p className="mt-1 text-sm text-slate-800">{f.content}</p>
            {f.source_url && (
              <a
                href={f.source_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-xs text-indigo-600 hover:underline"
              >
                source
              </a>
            )}
            {f.status === "proposed" && (
              <div className="mt-2 flex gap-2">
                <button
                  onClick={() => onDecide(f.id, "approve")}
                  disabled={pending}
                  className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  onClick={() => onDecide(f.id, "reject")}
                  disabled={pending}
                  className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
