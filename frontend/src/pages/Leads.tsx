import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  useLeadDecision,
  useLeads,
  usePromoteLead,
  useSourceIbTargets,
  useSourceLeads,
} from "../api/hooks";
import StatusBadge from "../components/StatusBadge";
import type { SourcedLead } from "../api/types";

export default function Leads() {
  const [searchParams] = useSearchParams();
  const [keyword, setKeyword] = useState(searchParams.get("keyword") ?? "");
  const [location, setLocation] = useState(searchParams.get("location") ?? "");
  // What the most recently completed search actually asked for -- shown in
  // the empty-state message so "found nothing" is distinguishable from "the
  // search never ran." Without this, a legitimate zero-result search (e.g.
  // a narrow keyword+geography combo with no recent GitHub/HN matches) looks
  // identical to a broken search: the unfiltered historical backlog below
  // stays exactly as it was, with no feedback that anything happened.
  const [lastSearch, setLastSearch] = useState<{ keyword: string; location?: string; mode: "vc" | "ib" } | null>(
    null,
  );

  const leads = useLeads();
  const sourceLeads = useSourceLeads();
  const sourceIb = useSourceIbTargets();
  const decision = useLeadDecision();
  const promote = usePromoteLead();

  // Arrived from the dashboard prompt bar with a pre-classified keyword --
  // run the search immediately rather than making the user click again.
  useEffect(() => {
    const k = searchParams.get("keyword");
    if (k) {
      const loc = searchParams.get("location") ?? undefined;
      sourceLeads.mutate({ sector_keyword: k, location_filter: loc });
      setLastSearch({ keyword: k, location: loc, mode: "vc" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function runSource(mode: "vc" | "ib") {
    if (!keyword.trim()) return;
    const k = keyword.trim();
    const loc = location.trim() || undefined;
    if (mode === "vc") {
      sourceLeads.mutate({ sector_keyword: k, location_filter: loc });
    } else {
      sourceIb.mutate({ sector_keyword: k });
    }
    setLastSearch({ keyword: k, location: mode === "vc" ? loc : undefined, mode });
  }

  const isSourcing = sourceLeads.isPending || sourceIb.isPending;

  // Leads returned by the most recently completed search -- kept separate
  // from the full historical backlog (117+ leads can pile up across a
  // session's worth of unrelated test searches) so a fresh, relevant result
  // is never buried among leads from a completely different query.
  const freshIds = new Set([...(sourceLeads.data ?? []), ...(sourceIb.data ?? [])].map((l) => l.id));

  const allNewLeads = (leads.data ?? []).filter((l) => l.status === "new");
  const freshLeads = allNewLeads.filter((l) => freshIds.has(l.id));
  const backlogLeads = allNewLeads.filter((l) => !freshIds.has(l.id));
  const reviewedLeads = (leads.data ?? []).filter((l) => l.status === "reviewed");
  const otherLeads = (leads.data ?? []).filter(
    (l) => l.status === "dismissed" || l.status === "promoted_to_deal",
  );

  const searchFoundNothing =
    !isSourcing && lastSearch !== null && freshLeads.length === 0 &&
    (lastSearch.mode === "vc" ? sourceLeads.isSuccess : sourceIb.isSuccess);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Sourcing &amp; Leads</h1>
        <p className="mt-1 text-sm text-slate-500">
          Finds candidate companies with a citable, recent discovery signal -- not a comprehensive market
          map, and not fundraising execution. Promoting a lead starts the real deal pipeline; it never
          contacts investors or runs a raise itself.
        </p>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap gap-2">
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="Sector keyword, e.g. fintech"
            className="flex-1 min-w-[180px] rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400"
          />
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="Geography (optional)"
            className="w-48 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400"
          />
          <button
            onClick={() => runSource("vc")}
            disabled={isSourcing || !keyword.trim()}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {sourceLeads.isPending ? "Searching…" : "Source (early-stage)"}
          </button>
          <button
            onClick={() => runSource("ib")}
            disabled={isSourcing || !keyword.trim()}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {sourceIb.isPending ? "Searching…" : "Source (mature/public)"}
          </button>
        </div>
        {(sourceLeads.isError || sourceIb.isError) && (
          <p className="mt-2 text-sm text-rose-600">
            {(sourceLeads.error ?? sourceIb.error)?.message}
          </p>
        )}
      </div>

      {leads.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {leads.isError && <p className="text-sm text-rose-600">{leads.error.message}</p>}

      {searchFoundNothing && (
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
          Search ran, but found no new candidates for &quot;{lastSearch!.keyword}&quot;
          {lastSearch!.location ? ` in ${lastSearch!.location}` : ""} in the current lookback window --
          try a broader keyword or drop the geography filter. This is separate from the {backlogLeads.length}{" "}
          lead{backlogLeads.length === 1 ? "" : "s"} below from earlier searches.
        </p>
      )}

      {freshLeads.length > 0 && (
        <LeadSection
          title={`Just found for "${lastSearch?.keyword}"`}
          leads={freshLeads}
          onKeep={(id) => decision.mutate({ leadId: id, decision: "keep" })}
          onDismiss={(id) => decision.mutate({ leadId: id, decision: "dismiss" })}
          decisionPending={decision.isPending}
        />
      )}

      {backlogLeads.length > 0 && (
        <LeadSection
          title="Awaiting review (earlier searches)"
          leads={backlogLeads}
          onKeep={(id) => decision.mutate({ leadId: id, decision: "keep" })}
          onDismiss={(id) => decision.mutate({ leadId: id, decision: "dismiss" })}
          decisionPending={decision.isPending}
        />
      )}

      {reviewedLeads.length > 0 && (
        <LeadSection
          title="Kept for follow-up"
          leads={reviewedLeads}
          onPromote={(id) => promote.mutate({ leadId: id })}
          promotePending={promote.isPending}
        />
      )}

      {otherLeads.length > 0 && (
        <LeadSection title="Dismissed / promoted" leads={otherLeads} muted />
      )}

      {leads.data?.length === 0 && !isSourcing && (
        <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
          No leads sourced yet. Enter a sector keyword above to find candidates.
        </p>
      )}
    </div>
  );
}

function LeadSection({
  title,
  leads,
  onKeep,
  onDismiss,
  onPromote,
  decisionPending,
  promotePending,
  muted,
}: {
  title: string;
  leads: SourcedLead[];
  onKeep?: (id: string) => void;
  onDismiss?: (id: string) => void;
  onPromote?: (id: string) => void;
  decisionPending?: boolean;
  promotePending?: boolean;
  muted?: boolean;
}) {
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">{title}</h2>
      <div className="flex flex-col gap-2">
        {leads.map((lead) => (
          <div
            key={lead.id}
            className={`rounded-lg border border-slate-200 bg-white p-3 shadow-sm ${muted ? "opacity-60" : ""}`}
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium text-slate-900">{lead.company_name}</p>
                {lead.sector_tag && <p className="text-xs text-slate-500">{lead.sector_tag}</p>}
              </div>
              <StatusBadge status={lead.status} />
            </div>
            <ul className="mt-2 space-y-1">
              {lead.discovery_signals.map((sig, i) => (
                <li key={i} className="text-xs text-slate-600">
                  <span className="font-medium text-slate-500">[{sig.source_type}]</span> {sig.content}
                  {sig.source_url && (
                    <a
                      href={sig.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-1 text-indigo-600 hover:underline"
                    >
                      source
                    </a>
                  )}
                </li>
              ))}
            </ul>
            {(onKeep || onDismiss || onPromote) && (
              <div className="mt-3 flex gap-2">
                {onKeep && (
                  <button
                    onClick={() => onKeep(lead.id)}
                    disabled={decisionPending}
                    className="rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                  >
                    Keep for follow-up
                  </button>
                )}
                {onDismiss && (
                  <button
                    onClick={() => onDismiss(lead.id)}
                    disabled={decisionPending}
                    className="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                  >
                    Dismiss
                  </button>
                )}
                {onPromote && (
                  <button
                    onClick={() => onPromote(lead.id)}
                    disabled={promotePending}
                    className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                  >
                    Promote to deal
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
