import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import {
  useCompileCim,
  useCompileProforma,
  useConfirmTeaser,
  useDocuments,
  useTeaserDraft,
} from "../../api/hooks";
import CitationDrawer from "../../components/CitationDrawer";
import StatTile from "../../components/StatTile";
import { formatFieldValue } from "../../lib/format";
import type {
  CimStructuredData,
  DocumentType,
  MemoVersion,
  ProformaStructuredData,
  TeaserStructuredData,
} from "../../api/types";

const TABS: { key: DocumentType; label: string }[] = [
  { key: "cim", label: "CIM" },
  { key: "teaser", label: "Teaser" },
  { key: "proforma", label: "Pro-forma" },
];

export default function Documents() {
  const { dealId } = useOutletContext<{ dealId: string }>();
  const [activeTab, setActiveTab] = useState<DocumentType>("cim");
  const documents = useDocuments(dealId);
  const [citationBlockId, setCitationBlockId] = useState<string | null>(null);

  if (documents.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (documents.isError) return <p className="text-sm text-rose-600">{documents.error.message}</p>;

  function latestOf(type: DocumentType): MemoVersion | undefined {
    return documents.data
      ?.filter((d) => d.document_type === type)
      .sort((a, b) => b.version_number - a.version_number)[0];
  }

  return (
    <div className="flex flex-col gap-4">
      <nav className="flex gap-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === tab.key ? "bg-indigo-600 text-white" : "bg-white text-slate-600 hover:bg-slate-100"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === "cim" && <CimView dealId={dealId} memo={latestOf("cim")} onCite={setCitationBlockId} />}
      {activeTab === "teaser" && <TeaserView dealId={dealId} memo={latestOf("teaser")} />}
      {activeTab === "proforma" && <ProformaView dealId={dealId} memo={latestOf("proforma")} />}

      <CitationDrawer dealId={dealId} blockId={citationBlockId} onClose={() => setCitationBlockId(null)} />
    </div>
  );
}

// --- CIM --------------------------------------------------------------

function CimView({
  dealId,
  memo,
  onCite,
}: {
  dealId: string;
  memo: MemoVersion | undefined;
  onCite: (blockId: string) => void;
}) {
  const compile = useCompileCim(dealId);

  if (!memo) {
    return (
      <EmptyState
        message="No CIM compiled yet."
        action="Compile CIM"
        onAction={() => compile.mutate()}
        pending={compile.isPending}
        error={compile.error?.message}
      />
    );
  }

  const data = memo.structured_data as unknown as CimStructuredData;

  return (
    <div className="flex flex-col gap-4">
      <DocHeader memo={memo} onRecompile={() => compile.mutate()} recompiling={compile.isPending} />

      {data.narrative && (
        <p className="rounded-lg border border-slate-200 bg-white p-4 text-sm italic text-slate-700 shadow-sm">
          {data.narrative}
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Object.values(data.financials).map((field) => (
          <div key={field.label} onClick={() => field.source_block_id && onCite(field.source_block_id)}>
            <StatTile field={field} />
          </div>
        ))}
      </div>

      {data.cross_check_flags.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <p className="mb-1 font-medium">Reviewer notes / cross-check flags</p>
          <ul className="list-inside list-disc space-y-0.5">
            {data.cross_check_flags.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">Cap Table</h3>
        {data.cap_table.available ? (
          <table className="w-full text-sm">
            <tbody>
              {data.cap_table.rows.map((row, i) => (
                <tr key={i} className="border-t border-slate-100 first:border-t-0">
                  <td className="py-1 text-slate-800">{row.holder ?? "—"}</td>
                  <td className="py-1 text-slate-800">{row.pct !== null ? `${row.pct}%` : "—"}</td>
                  <td className="py-1 text-slate-500">{row.share_class ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-slate-500">Not available or not disclosed for this deal.</p>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">Funding History</h3>
        {data.funding_history.available ? (
          <table className="w-full text-sm">
            <tbody>
              {data.funding_history.rounds.map((r, i) => (
                <tr key={i} className="border-t border-slate-100 first:border-t-0">
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
        ) : (
          <p className="text-sm text-slate-500">No approved funding history for this deal.</p>
        )}
      </div>

      {data.external_signals.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 text-sm font-semibold text-slate-800">External Signals</h3>
          <p className="mb-2 text-xs text-slate-500">
            Supporting context, not independent verification of the figures above.
          </p>
          <ul className="space-y-1 text-sm text-slate-700">
            {data.external_signals.map((sig, i) => (
              <li key={i}>
                <span className="font-medium">[{sig.topic}]</span> {sig.content}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.charts.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data.charts.map((chart, i) => (
            <img
              key={i}
              src={`/${chart.storage_uri}`}
              alt={chart.chart_type}
              className="rounded-lg border border-slate-200 bg-white p-2 shadow-sm"
            />
          ))}
        </div>
      )}
    </div>
  );
}

// --- Teaser --------------------------------------------------------------

function TeaserView({ dealId, memo }: { dealId: string; memo: MemoVersion | undefined }) {
  const draft = useTeaserDraft(dealId);
  const confirm = useConfirmTeaser(dealId);
  const [description, setDescription] = useState("");

  if (!memo) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <p className="mb-2 text-sm text-slate-600">
          No teaser drafted yet. The business description is supplied by you, not generated -- it's never
          inferred from ungrounded prose.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (description.trim()) draft.mutate(description.trim());
          }}
          className="flex gap-2"
        >
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="One-line anonymized business description (no company name)"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={!description.trim() || draft.isPending}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            Draft teaser
          </button>
        </form>
        {draft.isError && <p className="mt-2 text-xs text-rose-600">{draft.error.message}</p>}
      </div>
    );
  }

  const data = memo.structured_data as unknown as TeaserStructuredData;

  return (
    <div className="flex flex-col gap-4">
      <DocHeader memo={memo} />

      <div
        className={`rounded-lg border p-3 text-sm ${
          memo.approved_by
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-amber-200 bg-amber-50 text-amber-800"
        }`}
      >
        {memo.approved_by ? (
          <>Confirmed safe to send externally by <span className="font-medium">{memo.approved_by}</span>.</>
        ) : (
          <>
            <p className="mb-2 font-medium">
              Confirm this does NOT leak the company's identity -- safe to send externally?
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => confirm.mutate({ memoId: memo.id, confirmed: true })}
                disabled={confirm.isPending}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              >
                Yes, safe to send
              </button>
              <button
                onClick={() => confirm.mutate({ memoId: memo.id, confirmed: false })}
                disabled={confirm.isPending}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              >
                No, revise
              </button>
            </div>
          </>
        )}
      </div>

      <p className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-800 shadow-sm">
        {data.business_description}
      </p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {Object.values(data.financials).map((field) => (
          <StatTile key={field.label} field={field} />
        ))}
      </div>

      {data.charts.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {data.charts.map((chart, i) => (
            <img
              key={i}
              src={`/${chart.storage_uri}`}
              alt={chart.chart_type}
              className="rounded-lg border border-slate-200 bg-white p-2 shadow-sm"
            />
          ))}
        </div>
      )}

      <p className="text-xs text-slate-500">
        Full financials, cap table, and company identity are available under NDA.
      </p>
    </div>
  );
}

// --- Pro-forma ---------------------------------------------------------

function ProformaView({ dealId, memo }: { dealId: string; memo: MemoVersion | undefined }) {
  const compile = useCompileProforma(dealId);
  const [override, setOverride] = useState("");

  if (!memo) {
    return (
      <EmptyState
        message="No pro-forma model compiled yet."
        action="Compile pro-forma"
        onAction={() => compile.mutate(override.trim() ? Number(override) : undefined)}
        pending={compile.isPending}
        error={compile.error?.message}
        extra={
          <input
            value={override}
            onChange={(e) => setOverride(e.target.value)}
            placeholder="Override ARR growth rate % (optional)"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        }
      />
    );
  }

  const data = memo.structured_data as unknown as ProformaStructuredData;

  return (
    <div className="flex flex-col gap-4">
      <DocHeader memo={memo} />

      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
        <p className="font-medium">PROJECTED, NOT EXTRACTED</p>
        <p className="mt-1 text-xs">
          Every number below is computed from the stated assumptions, not sourced from a document. Never
          treat it at the same confidence tier as the CIM's cited figures.
        </p>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">Assumptions</h3>
        <ul className="list-inside list-disc space-y-1 text-sm text-slate-700">
          {data.assumptions.map((a, i) => (
            <li key={i} className={a.startsWith("WARNING") ? "text-rose-700" : undefined}>
              {a}
            </li>
          ))}
        </ul>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th className="px-3 py-2 font-medium">Year</th>
              <th className="px-3 py-2 font-medium">Projected ARR</th>
              <th className="px-3 py-2 font-medium">Projected Cash on Hand</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.year} className="border-t border-slate-100">
                <td className="px-3 py-2 text-slate-800">Year {row.year}</td>
                <td className="px-3 py-2 text-slate-800">{formatFieldValue(row.arr, "USD")}</td>
                <td className="px-3 py-2 text-slate-800">
                  {row.cash_on_hand !== null ? formatFieldValue(row.cash_on_hand, "USD") : "not projected"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --- Shared --------------------------------------------------------------

function DocHeader({
  memo,
  onRecompile,
  recompiling,
}: {
  memo: MemoVersion;
  onRecompile?: () => void;
  recompiling?: boolean;
}) {
  return (
    <div className="flex items-center justify-between text-xs text-slate-500">
      <span>
        v{memo.version_number} · generated {new Date(memo.generated_at).toLocaleString()}
      </span>
      {onRecompile && (
        <button onClick={onRecompile} disabled={recompiling} className="text-indigo-600 hover:underline disabled:opacity-50">
          {recompiling ? "Recompiling…" : "Recompile"}
        </button>
      )}
    </div>
  );
}

function EmptyState({
  message,
  action,
  onAction,
  pending,
  error,
  extra,
}: {
  message: string;
  action: string;
  onAction: () => void;
  pending: boolean;
  error?: string;
  extra?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center">
      <p className="mb-3 text-sm text-slate-500">{message}</p>
      <div className="flex items-center justify-center gap-2">
        {extra}
        <button
          onClick={onAction}
          disabled={pending}
          className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {pending ? "Compiling…" : action}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-rose-600">{error}</p>}
    </div>
  );
}
