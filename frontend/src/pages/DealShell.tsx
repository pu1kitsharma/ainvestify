import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { useDeal } from "../api/hooks";
import DirectiveBar from "../components/DirectiveBar";
import Stepper from "../components/Stepper";
import StatusBadge from "../components/StatusBadge";

const TABS = [
  { to: "review", label: "Document figures" },
  { to: "research", label: "Source checks" },
  { to: "documents", label: "Documents" },
  { to: "investors", label: "Investors" },
  { to: "audit-log", label: "Audit Log" },
];

export default function DealShell() {
  const { dealId } = useParams<{ dealId: string }>();
  const deal = useDeal(dealId);

  if (deal.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (deal.isError) return <p className="text-sm text-rose-600">{deal.error.message}</p>;
  if (!deal.data || !dealId) return null;

  return (
    <div className="flex flex-col gap-4">
      <Link to="/" className="text-sm text-indigo-600 hover:underline">
        ← Back to companies
      </Link>

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">{deal.data.name}</h1>
            {deal.data.stage && <p className="text-xs text-slate-500">{deal.data.stage}</p>}
          </div>
          <StatusBadge status={deal.data.status} />
        </div>
        <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer">Document preparation status</summary><Stepper status={deal.data.status} /></details>
      </div>

      <details className="text-xs text-slate-500"><summary className="cursor-pointer">Advanced document actions</summary><div className="mt-3"><DirectiveBar dealId={dealId} /></div></details>

      <div>
        <nav className="flex gap-1 overflow-x-auto border-b border-slate-200">
          {TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) =>
                `border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "border-indigo-600 text-indigo-700"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>
        <div className="pt-4">
          <Outlet context={{ dealId, deal: deal.data }} />
        </div>
      </div>
    </div>
  );
}
