import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { portalApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { Badge, Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { PortalLayout, PORTAL_INVALID_LINK_MESSAGE } from "./PortalLayout";
import type { JobStatus } from "../types/api";

const STATUS_TONE: Record<JobStatus, "slate" | "green" | "amber" | "red" | "blue"> = {
  scheduled: "blue",
  in_progress: "amber",
  on_hold: "red",
  completed: "green",
  canceled: "slate",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function PortalJobs() {
  const { token } = useParams<{ token: string }>();

  const query = useQuery({
    queryKey: ["portal", token, "jobs"],
    queryFn: () => portalApi.jobs(token!),
    enabled: !!token,
    retry: false,
  });

  return (
    <PortalLayout>
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Job history</h2>

      {query.isLoading && <Spinner label="Loading your jobs…" />}

      {query.isError && (
        <ErrorBanner
          message={
            query.error instanceof ApiError && query.error.status === 404
              ? PORTAL_INVALID_LINK_MESSAGE
              : "Something went wrong loading your jobs. Please contact the shop."
          }
        />
      )}

      {query.isSuccess && query.data.length === 0 && (
        <EmptyState message="No jobs on file yet." />
      )}

      {query.isSuccess && query.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100">
            {query.data.map((job) => (
              <li key={job.id} className="flex flex-col gap-1 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-medium text-slate-900">{job.title ?? "Untitled job"}</p>
                  <p className="text-slate-500">
                    Scheduled {formatDate(job.scheduled_at)}
                    {job.technician_name ? ` · Tech: ${job.technician_name}` : ""}
                  </p>
                </div>
                <Badge tone={STATUS_TONE[job.status]}>{job.status.replace("_", " ")}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </PortalLayout>
  );
}
