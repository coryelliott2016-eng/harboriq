import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { reportsApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Button, Card, ErrorBanner, Spinner, StatCard } from "../components/ui";
import { money } from "../lib/format";
import type { AgingBuckets } from "../types/api";

const BUCKET_COLUMNS: { key: keyof AgingBuckets; label: string }[] = [
  { key: "current", label: "Current" },
  { key: "days_1_30", label: "1-30 days" },
  { key: "days_31_60", label: "31-60 days" },
  { key: "days_61_90", label: "61-90 days" },
  { key: "days_90_plus", label: "90+ days" },
];

// owner/admin/office (mirrors app/api/v1/routes/reports.py::require_operations)
// -- gated at the route level in App.tsx like canManageOperations elsewhere.
export function ArAgingPage() {
  const query = useQuery({
    queryKey: ["reports", "ar-aging"],
    queryFn: () => reportsApi.arAging(),
  });
  const [exporting, setExporting] = useState(false);

  async function handleExport() {
    setExporting(true);
    try {
      await reportsApi.exportArAgingCsv();
    } finally {
      setExporting(false);
    }
  }

  if (query.isLoading) return <Spinner label="Loading AR aging report…" />;
  if (query.isError)
    return (
      <ErrorBanner
        message={
          query.error instanceof ApiError ? query.error.message : "Failed to load AR aging report."
        }
      />
    );

  const report = query.data!;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">AR aging</h1>
          <p className="mt-1 text-sm text-slate-500">
            Outstanding balances as of {new Date(report.as_of).toLocaleString()}, bucketed by days
            overdue. Only invoices with a balance still due are included.
          </p>
        </div>
        <Button onClick={handleExport} disabled={exporting}>
          {exporting ? "Exporting…" : "Export CSV"}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {BUCKET_COLUMNS.map((col) => (
          <StatCard key={col.key} label={col.label} value={money(report.bucket_totals[col.key])} />
        ))}
      </div>

      <Card className="px-4 py-2 text-right text-sm font-semibold text-slate-900">
        Grand total outstanding: {money(report.grand_total)}
      </Card>

      {report.customers.length === 0 ? (
        <Card className="px-4 py-6 text-center text-sm text-slate-500">
          No outstanding balances — everything is paid up.
        </Card>
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
              <tr>
                <th className="px-4 py-2">Customer</th>
                {BUCKET_COLUMNS.map((col) => (
                  <th key={col.key} className="px-4 py-2 text-right">
                    {col.label}
                  </th>
                ))}
                <th className="px-4 py-2 text-right">Total</th>
                <th className="px-4 py-2 text-right">Invoices</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {report.customers.map((c) => (
                <tr key={c.customer_id ?? c.customer_name}>
                  <td className="px-4 py-2">{c.customer_name}</td>
                  {BUCKET_COLUMNS.map((col) => (
                    <td key={col.key} className="px-4 py-2 text-right">
                      {money(c.buckets[col.key])}
                    </td>
                  ))}
                  <td className="px-4 py-2 text-right font-semibold">{money(c.total)}</td>
                  <td className="px-4 py-2 text-right">{c.invoice_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
