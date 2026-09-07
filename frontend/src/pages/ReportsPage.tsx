import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { reportsApi, type ReportDateRange } from "../lib/services";
import { ApiError } from "../lib/api";
import { Button, Card, ErrorBanner, Field, Spinner, StatCard, inputClass } from "../components/ui";
import { money } from "../lib/format";
import type { CashFlowMonth, PnlMonth } from "../types/api";

type Tab = "pnl" | "cash-flow";

/** Defaults to the trailing 12 months so the page shows something useful
 * without requiring the user to pick dates first. */
function defaultRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - 11);
  start.setDate(1);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function useReportRange() {
  const [range, setRange] = useState(defaultRange());
  const asQuery: ReportDateRange = useMemo(
    () => ({
      start_date: range.start ? `${range.start}T00:00:00Z` : undefined,
      end_date: range.end ? `${range.end}T23:59:59Z` : undefined,
    }),
    [range],
  );
  return { range, setRange, asQuery };
}

function DateRangeControls({
  range,
  setRange,
}: {
  range: { start: string; end: string };
  setRange: (r: { start: string; end: string }) => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <Field label="Start date">
        <input
          type="date"
          className={inputClass}
          value={range.start}
          onChange={(e) => setRange({ ...range, start: e.target.value })}
        />
      </Field>
      <Field label="End date">
        <input
          type="date"
          className={inputClass}
          value={range.end}
          onChange={(e) => setRange({ ...range, end: e.target.value })}
        />
      </Field>
    </div>
  );
}

function UnratedTechniciansNotice({ month }: { month: PnlMonth }) {
  if (!month.labor_cost_unavailable) return null;
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
      Labor cost for {month.month} is incomplete: no hourly rate is set for{" "}
      {month.unrated_technicians.join(", ")}. Set an hourly rate on the Team page for an accurate
      figure.
    </div>
  );
}

function PnlTab() {
  const { range, setRange, asQuery } = useReportRange();
  const query = useQuery({
    queryKey: ["reports", "pnl", asQuery],
    queryFn: () => reportsApi.pnl(asQuery),
  });
  const [exporting, setExporting] = useState(false);

  async function handleExport() {
    setExporting(true);
    try {
      await reportsApi.exportPnlCsv(asQuery);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <DateRangeControls range={range} setRange={setRange} />
        <Button onClick={handleExport} disabled={exporting}>
          {exporting ? "Exporting…" : "Export CSV"}
        </Button>
      </div>

      {query.isLoading && <Spinner label="Loading P&L…" />}
      {query.isError && (
        <ErrorBanner
          message={query.error instanceof ApiError ? query.error.message : "Failed to load P&L report."}
        />
      )}

      {query.data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Revenue" value={money(query.data.totals.revenue)} />
            <StatCard label="Refunds" value={money(query.data.totals.refunds)} />
            <StatCard label="Parts cost" value={money(query.data.totals.parts_cost)} />
            <StatCard label="Net" value={money(query.data.totals.net)} />
          </div>

          {query.data.totals.labor_cost_unavailable && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Labor cost is incomplete for this range: no hourly rate is set for{" "}
              {query.data.totals.unrated_technicians.join(", ")}. This total does NOT count their
              hours as $0 -- it is a known undercount. Set an hourly rate on the Team page to
              include them.
            </div>
          )}

          {query.data.months.length > 0 && (
            <Card className="p-4">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={query.data.months}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="net_revenue" name="Net revenue" fill="#0f172a" />
                  <Bar dataKey="parts_cost" name="Parts cost" fill="#f59e0b" />
                  <Bar dataKey="labor_cost" name="Labor cost" fill="#3b82f6" />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}

          <Card>
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
                <tr>
                  <th className="px-4 py-2">Month</th>
                  <th className="px-4 py-2 text-right">Revenue</th>
                  <th className="px-4 py-2 text-right">Refunds</th>
                  <th className="px-4 py-2 text-right">Net revenue</th>
                  <th className="px-4 py-2 text-right">Parts cost</th>
                  <th className="px-4 py-2 text-right">Labor cost</th>
                  <th className="px-4 py-2 text-right">Net</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {query.data.months.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                      No activity in this range.
                    </td>
                  </tr>
                ) : (
                  query.data.months.map((m) => (
                    <tr key={m.month}>
                      <td className="px-4 py-2">
                        {m.month}
                        {m.labor_cost_unavailable && (
                          <span className="ml-1 text-amber-600" title="Labor cost incomplete">
                            *
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right">{money(m.revenue)}</td>
                      <td className="px-4 py-2 text-right">{money(m.refunds)}</td>
                      <td className="px-4 py-2 text-right">{money(m.net_revenue)}</td>
                      <td className="px-4 py-2 text-right">{money(m.parts_cost)}</td>
                      <td className="px-4 py-2 text-right">{money(m.labor_cost)}</td>
                      <td className="px-4 py-2 text-right font-semibold">{money(m.net)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </Card>

          {query.data.months
            .filter((m) => m.labor_cost_unavailable)
            .map((m) => (
              <UnratedTechniciansNotice key={m.month} month={m} />
            ))}
        </>
      )}
    </div>
  );
}

function CashFlowTab() {
  const { range, setRange, asQuery } = useReportRange();
  const query = useQuery({
    queryKey: ["reports", "cash-flow", asQuery],
    queryFn: () => reportsApi.cashFlow(asQuery),
  });
  const [exporting, setExporting] = useState(false);

  async function handleExport() {
    setExporting(true);
    try {
      await reportsApi.exportCashFlowCsv(asQuery);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <DateRangeControls range={range} setRange={setRange} />
        <Button onClick={handleExport} disabled={exporting}>
          {exporting ? "Exporting…" : "Export CSV"}
        </Button>
      </div>

      {query.isLoading && <Spinner label="Loading cash flow…" />}
      {query.isError && (
        <ErrorBanner
          message={
            query.error instanceof ApiError ? query.error.message : "Failed to load cash flow report."
          }
        />
      )}

      {query.data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Cash in" value={money(query.data.totals.cash_in)} />
            <StatCard label="Refunds out" value={money(query.data.totals.refunds_out)} />
            <StatCard label="Cost incurred" value={money(query.data.totals.cost_incurred)} />
            <StatCard label="Net cash" value={money(query.data.totals.net_cash)} />
          </div>

          <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
            {query.data.cost_incurred_caveat}
          </div>

          {query.data.months.length > 0 && (
            <Card className="p-4">
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={query.data.months}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="month" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="cash_in" name="Cash in" stroke="#0f172a" />
                  <Line type="monotone" dataKey="cost_incurred" name="Cost incurred" stroke="#f59e0b" />
                  <Line type="monotone" dataKey="net_cash" name="Net cash" stroke="#22c55e" />
                </LineChart>
              </ResponsiveContainer>
            </Card>
          )}

          <Card>
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">
                <tr>
                  <th className="px-4 py-2">Month</th>
                  <th className="px-4 py-2 text-right">Cash in</th>
                  <th className="px-4 py-2 text-right">Refunds out</th>
                  <th className="px-4 py-2 text-right">Cost incurred</th>
                  <th className="px-4 py-2 text-right">Net cash</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {query.data.months.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                      No activity in this range.
                    </td>
                  </tr>
                ) : (
                  query.data.months.map((m: CashFlowMonth) => (
                    <tr key={m.month}>
                      <td className="px-4 py-2">{m.month}</td>
                      <td className="px-4 py-2 text-right">{money(m.cash_in)}</td>
                      <td className="px-4 py-2 text-right">{money(m.refunds_out)}</td>
                      <td className="px-4 py-2 text-right">{money(m.cost_incurred)}</td>
                      <td className="px-4 py-2 text-right font-semibold">{money(m.net_cash)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}

// owner/admin/office (mirrors app/api/v1/routes/reports.py::require_operations)
// -- gated at the route level in App.tsx like AR aging.
export function ReportsPage() {
  const [tab, setTab] = useState<Tab>("pnl");
  const [exportingQbo, setExportingQbo] = useState(false);
  const { asQuery } = useReportRange();

  async function handleQboExport() {
    setExportingQbo(true);
    try {
      await reportsApi.exportTransactionsCsv(asQuery);
    } finally {
      setExportingQbo(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Reports</h1>
          <p className="mt-1 text-sm text-slate-500">
            A simple cash-basis P&amp;L and cash flow view computed from your invoices, refunds,
            purchase orders, and technician time entries.
          </p>
        </div>
        <Button onClick={handleQboExport} disabled={exportingQbo}>
          {exportingQbo ? "Exporting…" : "Export QuickBooks CSV"}
        </Button>
      </div>

      <div className="flex gap-2 border-b border-slate-200">
        <button
          className={`px-3 py-2 text-sm font-medium ${
            tab === "pnl"
              ? "border-b-2 border-slate-900 text-slate-900"
              : "text-slate-500 hover:text-slate-800"
          }`}
          onClick={() => setTab("pnl")}
        >
          Profit &amp; loss
        </button>
        <button
          className={`px-3 py-2 text-sm font-medium ${
            tab === "cash-flow"
              ? "border-b-2 border-slate-900 text-slate-900"
              : "text-slate-500 hover:text-slate-800"
          }`}
          onClick={() => setTab("cash-flow")}
        >
          Cash flow
        </button>
      </div>

      {tab === "pnl" ? <PnlTab /> : <CashFlowTab />}
    </div>
  );
}
