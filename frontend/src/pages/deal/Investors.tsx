import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useAddInvestor, useInvestors } from "../../api/hooks";

const INTEREST_LEVELS = ["new", "cold", "warm", "hot", "passed", "committed"] as const;
const NDA_STATUSES = ["not_sent", "sent", "signed"] as const;

/**
 * Demand book (plan §5 Roadshow stage): pure record-keeping. Deliberately
 * no outreach affordance here -- matches InvestorContact's own docstring
 * boundary ("this system tracks who was approached... it does not contact
 * anyone or send anything itself"), still locked for this pass per the
 * plan's scope decision even though the user is open to revisiting it later.
 */
export default function Investors() {
  const { dealId } = useOutletContext<{ dealId: string }>();
  const investors = useInvestors(dealId);
  const addInvestor = useAddInvestor(dealId);

  const [name, setName] = useState("");
  const [firm, setFirm] = useState("");
  const [ndaStatus, setNdaStatus] = useState<(typeof NDA_STATUSES)[number]>("not_sent");
  const [interestLevel, setInterestLevel] = useState<(typeof INTEREST_LEVELS)[number]>("new");
  const [notes, setNotes] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    addInvestor.mutate(
      {
        investor_name: name.trim(),
        firm: firm.trim() || undefined,
        nda_status: ndaStatus,
        interest_level: interestLevel,
        notes: notes.trim() || undefined,
      },
      {
        onSuccess: () => {
          setName("");
          setFirm("");
          setNdaStatus("not_sent");
          setInterestLevel("new");
          setNotes("");
        },
      },
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <form onSubmit={handleSubmit} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <p className="mb-3 text-xs text-slate-500">
          Pure record-keeping -- tracks who a human already reached out to. Never sends anything itself.
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Investor name"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            value={firm}
            onChange={(e) => setFirm(e.target.value)}
            placeholder="Firm"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <select
            value={ndaStatus}
            onChange={(e) => setNdaStatus(e.target.value as typeof ndaStatus)}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            {NDA_STATUSES.map((s) => (
              <option key={s} value={s}>
                NDA: {s.replace("_", " ")}
              </option>
            ))}
          </select>
          <select
            value={interestLevel}
            onChange={(e) => setInterestLevel(e.target.value as typeof interestLevel)}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            {INTEREST_LEVELS.map((l) => (
              <option key={l} value={l}>
                Interest: {l}
              </option>
            ))}
          </select>
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notes (optional)"
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={!name.trim() || addInvestor.isPending}
          className="mt-3 rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          Add investor
        </button>
        {addInvestor.isError && <p className="mt-2 text-xs text-rose-600">{addInvestor.error.message}</p>}
      </form>

      {investors.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {investors.isError && <p className="text-sm text-rose-600">{investors.error.message}</p>}

      {investors.data && investors.data.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
          No investors tracked yet.
        </p>
      )}

      {investors.data && investors.data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="px-3 py-2 font-medium">Investor</th>
                <th className="px-3 py-2 font-medium">Firm</th>
                <th className="px-3 py-2 font-medium">NDA</th>
                <th className="px-3 py-2 font-medium">Interest</th>
                <th className="px-3 py-2 font-medium">Notes</th>
                <th className="px-3 py-2 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {investors.data.map((inv) => (
                <tr key={inv.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium text-slate-900">{inv.investor_name}</td>
                  <td className="px-3 py-2 text-slate-600">{inv.firm ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-600">{inv.nda_status.replace("_", " ")}</td>
                  <td className="px-3 py-2 text-slate-600">{inv.interest_level}</td>
                  <td className="px-3 py-2 text-slate-500">{inv.notes ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-400">{new Date(inv.updated_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
