import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useClassifyPrompt, useCreateDeal, useStartWebRun } from "../api/hooks";
import type { RouterDecision } from "../api/types";

/** Classify the brief; sourcing starts immediately using the full user criteria. */
export default function PromptBar() {
  const [prompt, setPrompt] = useState("");
  const [decision, setDecision] = useState<RouterDecision | null>(null);
  const [dealName, setDealName] = useState("");
  const classify = useClassifyPrompt();
  const createDeal = useCreateDeal();
  const startResearch = useStartWebRun();
  const navigate = useNavigate();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim()) return;
    classify.mutate(prompt, {
      onSuccess: (result) => {
        setDecision(result);
        setDealName("");
        if (result.action === "source_leads") {
          startResearch.mutate({ thesis: prompt.trim(), geography: result.location_filter || undefined },
            { onSuccess: () => navigate("/leads") });
        }
      },
    });
  }

  function handleCreateDeal() {
    if (!dealName.trim()) return;
    createDeal.mutate(
      { name: dealName.trim() },
      { onSuccess: (deal) => navigate(`/deals/${deal.id}`) },
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder='What would you like to do? e.g. "find companies in fintech worth incubating"'
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400"
        />
        <button
          type="submit"
          disabled={classify.isPending || startResearch.isPending || !prompt.trim()}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {classify.isPending ? "Thinking…" : startResearch.isPending ? "Starting research…" : "Go"}
        </button>
      </form>

      {classify.isError && (
        <p className="mt-2 text-sm text-rose-600">{classify.error.message}</p>
      )}
      {startResearch.isError && <p className="mt-2 text-sm text-rose-600">{startResearch.error.message}</p>}

      {decision && (
        <div className="mt-3 rounded-md border border-indigo-100 bg-indigo-50/60 p-3 text-sm">
          <p className="text-slate-700">{decision.reasoning}</p>
          {decision.action === "source_leads" && startResearch.isPending && <p className="mt-2 text-xs text-slate-600">Discovering sources for your full brief…</p>}
          {decision.action === "screen_deal" && (
            <div className="mt-2 flex gap-2">
              <input
                value={dealName}
                onChange={(e) => setDealName(e.target.value)}
                placeholder="Company name"
                className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm outline-none focus:border-indigo-400"
              />
              <button
                onClick={handleCreateDeal}
                disabled={!dealName.trim() || createDeal.isPending}
                className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                Create deal
              </button>
            </div>
          )}
          {decision.action === "unknown" && (
            <p className="mt-1 text-xs text-slate-500">
              Try something like &ldquo;find companies in fintech&rdquo; or &ldquo;screen this deal for Acme
              Robotics&rdquo;.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
