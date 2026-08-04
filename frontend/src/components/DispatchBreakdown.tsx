import { Badge } from "./ui";
import type { DispatchScore } from "../types/api";

/**
 * Human-friendly labels for the rule-based dispatch scorer's factors
 * (see app/services/dispatch.py). Kept in sync manually since the backend
 * intentionally returns the raw factor keys, not display labels — this is
 * the one place in the frontend that needs to know their names.
 */
const FACTOR_LABELS: Record<string, string> = {
  urgency: "Urgency",
  revenue: "Revenue",
  customer_value: "Customer value",
  distance: "Distance",
  parts_availability: "Parts availability",
  technician_fit: "Skill fit",
  workload: "Workload",
};

function factorLabel(key: string): string {
  return FACTOR_LABELS[key] ?? key;
}

/**
 * Renders a dispatch score's total plus an explainable per-factor breakdown.
 * Used both on the job-detail dispatch-suggestions panel (per candidate) and
 * could be reused anywhere else a `DispatchScore` needs to be shown.
 */
export function DispatchBreakdown({ score }: { score: DispatchScore }) {
  const entries = Object.entries(score.breakdown);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <Badge tone="blue">Score {Number(score.total).toFixed(2)}</Badge>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-slate-500 sm:grid-cols-3">
        {entries.map(([key, value]) => {
          const numeric = Number(value);
          return (
            <div key={key} className="flex justify-between gap-2">
              <dt>{factorLabel(key)}</dt>
              <dd className={numeric < 0 ? "text-red-600" : "text-slate-700"}>
                {numeric > 0 ? "+" : ""}
                {numeric.toFixed(2)}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
