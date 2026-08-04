import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { jobsApi, invoicesApi } from "../lib/services";
import { Card, EmptyState, ErrorBanner, Spinner, StatCard, Badge } from "../components/ui";
import { JOB_STATUS_LABELS } from "../lib/jobStateMachine";
import { INVOICE_STATUS_LABELS } from "../lib/invoiceStateMachine";
import type { InvoiceStatus, JobStatus } from "../types/api";

const JOB_STATUSES: JobStatus[] = ["scheduled", "in_progress", "on_hold", "completed", "canceled"];
const INVOICE_STATUSES: InvoiceStatus[] = ["draft", "sent", "partial", "paid", "void"];

export function DashboardPage() {
  const jobsQuery = useQuery({ queryKey: ["jobs", "dashboard"], queryFn: () => jobsApi.list() });
  const invoicesQuery = useQuery({
    queryKey: ["invoices", "dashboard"],
    queryFn: () => invoicesApi.list(),
  });

  if (jobsQuery.isLoading || invoicesQuery.isLoading) return <Spinner label="Loading dashboard…" />;
  if (jobsQuery.isError)
    return <ErrorBanner message={jobsQuery.error instanceof Error ? jobsQuery.error.message : "Failed to load jobs."} />;
  if (invoicesQuery.isError)
    return (
      <ErrorBanner
        message={invoicesQuery.error instanceof Error ? invoicesQuery.error.message : "Failed to load invoices."}
      />
    );

  const jobs = jobsQuery.data ?? [];
  const invoices = invoicesQuery.data ?? [];

  const jobCounts = JOB_STATUSES.map((status) => ({
    status,
    count: jobs.filter((j) => j.status === status).length,
  }));
  const invoiceCounts = INVOICE_STATUSES.map((status) => ({
    status,
    count: invoices.filter((i) => i.status === status).length,
  }));

  const recentJobs = [...jobs]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 8);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">At a glance across jobs and invoices.</p>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Jobs by status
        </h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {jobCounts.map(({ status, count }) => (
            <StatCard key={status} label={JOB_STATUS_LABELS[status]} value={count} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Invoices by status
        </h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {invoiceCounts.map(({ status, count }) => (
            <StatCard key={status} label={INVOICE_STATUS_LABELS[status]} value={count} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Recent jobs
        </h2>
        <Card>
          {recentJobs.length === 0 ? (
            <EmptyState message="No jobs yet. Create one from the Jobs page." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {recentJobs.map((job) => (
                <li key={job.id} className="flex items-center justify-between px-4 py-3">
                  <Link to={`/jobs/${job.id}`} className="text-sm font-medium text-slate-900 hover:underline">
                    {job.title}
                  </Link>
                  <Badge tone={job.status === "completed" ? "green" : job.status === "canceled" ? "red" : "blue"}>
                    {JOB_STATUS_LABELS[job.status]}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>
    </div>
  );
}
