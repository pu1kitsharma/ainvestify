import type { DealStatus } from "../api/types";

const HAPPY_PATH: { status: DealStatus; label: string }[] = [
  { status: "new", label: "New" },
  { status: "mandate_signed", label: "Mandate" },
  { status: "ingested", label: "Ingested" },
  { status: "extracted", label: "Extracted" },
  { status: "reviewed", label: "Reviewed" },
  { status: "researched", label: "Researched" },
  { status: "research_reviewed", label: "Research reviewed" },
  { status: "compiled", label: "Compiled" },
];

export default function Stepper({ status }: { status: DealStatus }) {
  const isStuck = status === "needs_manual_input";
  // needs_manual_input branches off after extraction -- show progress up to
  // "Extracted" as done, and flag the Reviewed step instead of pretending
  // the deal is further along than it is.
  const effectiveIndex = isStuck
    ? HAPPY_PATH.findIndex((s) => s.status === "extracted")
    : HAPPY_PATH.findIndex((s) => s.status === status);

  return (
    <div className="flex items-center overflow-x-auto py-1">
      {HAPPY_PATH.map((step, i) => {
        const done = i < effectiveIndex || (i === effectiveIndex && !isStuck);
        const isCurrent = i === effectiveIndex;
        const flagged = isStuck && step.status === "reviewed";
        return (
          <div key={step.status} className="flex items-center">
            <div className="flex flex-col items-center gap-1">
              <div
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-medium ${
                  flagged
                    ? "bg-rose-500 text-white"
                    : done
                      ? "bg-indigo-600 text-white"
                      : isCurrent
                        ? "border-2 border-indigo-600 text-indigo-600"
                        : "border border-slate-300 text-slate-400"
                }`}
              >
                {i + 1}
              </div>
              <span
                className={`whitespace-nowrap text-[11px] ${
                  flagged ? "font-medium text-rose-600" : done || isCurrent ? "text-slate-700" : "text-slate-400"
                }`}
              >
                {flagged ? "Needs input" : step.label}
              </span>
            </div>
            {i < HAPPY_PATH.length - 1 && (
              <div className={`mx-1 h-px w-8 shrink-0 ${i < effectiveIndex ? "bg-indigo-600" : "bg-slate-200"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}
