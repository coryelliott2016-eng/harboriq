import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { invoicesApi } from "../lib/services";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { money } from "../lib/format";
import { INVOICE_STATUS_LABELS } from "../lib/invoiceStateMachine";
import type { InvoiceStatus } from "../types/api";

const STATUS_FILTERS: (InvoiceStatus | "all")[] = [
  "all",
  "draft",
  "sent",
  "partial",
  "paid",
  "void",
  "uncollectible",
];

function statusTone(status: InvoiceStatus) {
  if (status === "paid") return "green" as const;
  if (status === "void" || status === "uncollectible") return "red" as const;
  if (status === "partial") return "amber" as const;
  return "slate" as const;
}

export function InvoicesPage() {
  const [statusFilter, setStatusFilter] = useState<InvoiceStatus | "all">("all");

  const query = useQuery({
    queryKey: ["invoices", statusFilter],
    queryFn: () => invoicesApi.list(statusFilter === "all" ? undefined : { status: statusFilter }),
  });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Invoices</h1>
        <p className="mt-1 text-sm text-slate-500">Bills sent to customers.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              statusFilter === s ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {s === "all" ? "All" : INVOICE_STATUS_LABELS[s]}
          </button>
        ))}
      </div>

      {query.isLoading && <Spinner label="Loading invoices…" />}
      {query.isError && (
        <ErrorBanner message={query.error instanceof Error ? query.error.message : "Failed to load invoices."} />
      )}
      {query.isSuccess && query.data.length === 0 && <EmptyState message="No invoices match this filter." />}
      {query.isSuccess && query.data.length > 0 && (
        <Card>
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
              <tr>
                <th className="px-4 py-2">Invoice</th>
                <th className="px-4 py-2 text-right">Total</th>
                <th className="px-4 py-2 text-right">Balance due</th>
                <th className="px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {query.data.map((inv) => (
                <tr key={inv.id}>
                  <td className="px-4 py-2">
                    <Link to={`/invoices/${inv.id}`} className="font-medium text-slate-900 hover:underline">
                      {inv.id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-right">{money(inv.total)}</td>
                  <td className="px-4 py-2 text-right">{money(inv.balance_due)}</td>
                  <td className="px-4 py-2">
                    <Badge tone={statusTone(inv.status)}>{INVOICE_STATUS_LABELS[inv.status]}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
