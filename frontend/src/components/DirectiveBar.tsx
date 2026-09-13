import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useDeal,
  useDirectivePreview,
  useExtractDeal,
  useRunResearch,
  useSignMandate,
  useUploadDocument,
} from "../api/hooks";
import type { PlannerDecision } from "../api/types";

// Actions the review-screen checkpoint's UI can actually execute.
// Everything else (research review, compilation, investors, analytics --
// their own future checkpoints per the plan) still previews correctly, but
// shows a plain "not wired up yet" note instead of a broken control: the
// backend deliberately has no generic execute endpoint (see
// api/routers/prompt.py's module docstring), so this map *is* the execute
// side, built out incrementally same as the rest of the frontend.
const HANDLED_ACTIONS = new Set([
  "sign_mandate",
  "ingest",
  "extract",
  "rerun_extraction",
  "review",
  "research",
  "rerun_research",
]);

/**
 * Persistent per-deal prompt/command bar (plan §5): preview -> inline
 * confirm card -> execute, the direct UI analog of _confirm_with_human --
 * never a blocking modal, and nothing executes until the user acts on the
 * card.
 */
export default function DirectiveBar({ dealId }: { dealId: string }) {
  const [directive, setDirective] = useState("");
  const [decision, setDecision] = useState<PlannerDecision | null>(null);
  const preview = useDirectivePreview(dealId);
  const navigate = useNavigate();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    preview.mutate(directive.trim() || "continue", { onSuccess: setDecision });
  }

  function dismiss() {
    setDecision(null);
    setDirective("");
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={directive}
          onChange={(e) => setDirective(e.target.value)}
          placeholder='Directive, or leave blank + Go to continue -- e.g. "the burn number looks wrong"'
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400"
        />
        <button
          type="submit"
          disabled={preview.isPending}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {preview.isPending ? "Thinking…" : "Go"}
        </button>
      </form>

      {preview.isError && <p className="mt-2 text-sm text-rose-600">{preview.error.message}</p>}

      {decision && (
        <div className="mt-3 rounded-md border border-indigo-100 bg-indigo-50/60 p-3 text-sm">
          <p className="text-slate-700">
            <span className="font-medium">Proposed: {decision.action}</span> — {decision.reasoning}
          </p>
          <ActionForm dealId={dealId} decision={decision} onDone={dismiss} onCancel={dismiss} navigate={navigate} />
        </div>
      )}
    </div>
  );
}

function ActionForm({
  dealId,
  decision,
  onDone,
  onCancel,
  navigate,
}: {
  dealId: string;
  decision: PlannerDecision;
  onDone: () => void;
  onCancel: () => void;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const deal = useDeal(dealId);
  const signMandate = useSignMandate(dealId);
  const upload = useUploadDocument(dealId);
  const extract = useExtractDeal(dealId);
  const runResearch = useRunResearch(dealId);

  const [mandateType, setMandateType] = useState("sell_side_advisory");
  const [terms, setTerms] = useState("");
  // Defaulted, not left blank: the deal already knows its own name, and
  // (for a deal promoted from a sourced lead) Deal.stage carries the
  // lead's sector_tag -- reusing both means research_deal's sector-notes
  // RAG lookup (agents/research_agent.SectorNotesIndex) actually runs
  // instead of silently never firing because sector_query was left empty.
  const [companyName, setCompanyName] = useState(deal.data?.name ?? "");
  const [sectorQuery, setSectorQuery] = useState(deal.data?.stage ?? "");

  if (!HANDLED_ACTIONS.has(decision.action)) {
    return (
      <p className="mt-2 text-xs text-slate-500">
        This action isn&rsquo;t wired up in the UI yet -- use the API directly (
        <code className="rounded bg-slate-100 px-1 py-0.5">{decision.action}</code>).{" "}
        <button onClick={onCancel} className="underline">
          Dismiss
        </button>
      </p>
    );
  }

  if (decision.action === "review") {
    return (
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => {
            navigate(`/deals/${dealId}/review`);
            onDone();
          }}
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
        >
          Go to review
        </button>
        <button onClick={onCancel} className="rounded-md px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100">
          Dismiss
        </button>
      </div>
    );
  }

  if (decision.action === "sign_mandate") {
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          signMandate.mutate({ mandate_type: mandateType, terms_summary: terms }, { onSuccess: onDone });
        }}
        className="mt-2 flex flex-wrap gap-2"
      >
        <select
          value={mandateType}
          onChange={(e) => setMandateType(e.target.value)}
          className="rounded-md border border-slate-300 px-2 py-1.5 text-xs"
        >
          <option value="sell_side_advisory">Sell-side advisory</option>
          <option value="vc_incubation">VC incubation</option>
        </select>
        <input
          value={terms}
          onChange={(e) => setTerms(e.target.value)}
          placeholder="Terms summary (fee %, exclusivity…)"
          className="flex-1 min-w-[180px] rounded-md border border-slate-300 px-2 py-1.5 text-xs"
        />
        <button
          type="submit"
          disabled={signMandate.isPending}
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          Sign mandate
        </button>
        {signMandate.isError && <p className="w-full text-xs text-rose-600">{signMandate.error.message}</p>}
      </form>
    );
  }

  if (decision.action === "ingest") {
    return (
      <div className="mt-2 flex items-center gap-2">
        <input
          type="file"
          accept=".pdf,.xlsx,.xlsm"
          disabled={upload.isPending}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file, { onSuccess: onDone });
          }}
          className="text-xs"
        />
        {upload.isPending && <span className="text-xs text-slate-500">Uploading…</span>}
        {upload.isError && <p className="text-xs text-rose-600">{upload.error.message}</p>}
      </div>
    );
  }

  if (decision.action === "extract" || decision.action === "rerun_extraction") {
    const feedback =
      decision.action === "rerun_extraction"
        ? decision.target_field
          ? `Reviewer directive about '${decision.target_field}': ${decision.reasoning}`
          : `Reviewer directive: ${decision.reasoning}`
        : undefined;
    return (
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => extract.mutate({ reviewer_feedback: feedback }, { onSuccess: onDone })}
          disabled={extract.isPending}
          className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {extract.isPending ? "Extracting… (can take a minute)" : "Run extraction"}
        </button>
        <button onClick={onCancel} className="rounded-md px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100">
          Dismiss
        </button>
        {extract.isError && <p className="text-xs text-rose-600">{extract.error.message}</p>}
      </div>
    );
  }

  if (decision.action === "research" || decision.action === "rerun_research") {
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!companyName.trim()) return;
          runResearch.mutate(
            { company_name: companyName.trim(), sector_query: sectorQuery.trim() || undefined },
            { onSuccess: onDone },
          );
        }}
        className="mt-2 flex flex-col gap-2"
      >
        <div className="flex gap-2">
          <input
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="Company name to research"
            className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-xs"
          />
          <input
            value={sectorQuery}
            onChange={(e) => setSectorQuery(e.target.value)}
            placeholder="Sector to benchmark against (optional, e.g. SaaS Series A burn/runway)"
            className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-xs"
          />
        </div>
        <p className="text-[11px] text-slate-500">
          Live public lookups (GitHub/HN/EDGAR/Wikipedia) are often thin or empty for early-stage private
          companies -- that&rsquo;s an honest gap, not a malfunction. The sector field benchmarks against
          internal sector notes instead, and any signal from the original sourcing lead is included
          automatically.
        </p>
        <button
          type="submit"
          disabled={runResearch.isPending || !companyName.trim()}
          className="w-fit rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {runResearch.isPending ? "Researching…" : "Run research"}
        </button>
        {runResearch.isError && <p className="text-xs text-rose-600">{runResearch.error.message}</p>}
      </form>
    );
  }

  return null;
}
