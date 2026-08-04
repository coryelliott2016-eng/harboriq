import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { customersApi, jobsApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { useAuth, canManageOperations } from "../context/AuthContext";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  Modal,
  Spinner,
  customerName,
  inputClass,
} from "../components/ui";
import { JOB_STATUS_LABELS } from "../lib/jobStateMachine";
import type { JobInput, JobStatus } from "../types/api";

const STATUS_FILTERS: (JobStatus | "all")[] = [
  "all",
  "scheduled",
  "in_progress",
  "on_hold",
  "completed",
  "canceled",
];

function statusTone(status: JobStatus) {
  if (status === "completed") return "green" as const;
  if (status === "canceled") return "red" as const;
  if (status === "on_hold") return "amber" as const;
  return "blue" as const;
}

export function JobsPage() {
  const { user } = useAuth();
  const canWrite = canManageOperations(user?.role);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all");
  const [showCreate, setShowCreate] = useState(false);

  const query = useQuery({
    queryKey: ["jobs", statusFilter],
    queryFn: () => jobsApi.list(statusFilter === "all" ? undefined : { status: statusFilter }),
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Jobs</h1>
          <p className="mt-1 text-sm text-slate-500">Work orders across the shop.</p>
        </div>
        {canWrite && <Button onClick={() => setShowCreate(true)}>New job</Button>}
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
            {s === "all" ? "All" : JOB_STATUS_LABELS[s]}
          </button>
        ))}
      </div>

      {query.isLoading && <Spinner label="Loading jobs…" />}
      {query.isError && (
        <ErrorBanner message={query.error instanceof Error ? query.error.message : "Failed to load jobs."} />
      )}
      {query.isSuccess && query.data.length === 0 && <EmptyState message="No jobs match this filter." />}
      {query.isSuccess && query.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100">
            {query.data.map((job) => (
              <li key={job.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <Link to={`/jobs/${job.id}`} className="text-sm font-medium text-slate-900 hover:underline">
                    {job.title}
                  </Link>
                  <p className="text-xs text-slate-400">
                    {job.scheduled_at ? new Date(job.scheduled_at).toLocaleString() : "Unscheduled"}
                  </p>
                </div>
                <Badge tone={statusTone(job.status)}>{JOB_STATUS_LABELS[job.status]}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {showCreate && <CreateJobModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}

function CreateJobModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [customerId, setCustomerId] = useState("");
  const [vesselId, setVesselId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [error, setError] = useState<string | null>(null);

  const customersQuery = useQuery({ queryKey: ["customers"], queryFn: () => customersApi.list() });
  const vesselsQuery = useQuery({
    queryKey: ["customers", customerId, "vessels"],
    queryFn: () => customersApi.vessels(customerId),
    enabled: !!customerId,
  });

  const mutation = useMutation({
    mutationFn: () => {
      const body: JobInput = {
        customer_id: customerId,
        vessel_id: vesselId || null,
        title,
        description: description || null,
        scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
      };
      return jobsApi.create(body);
    },
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      onClose();
      navigate(`/jobs/${job.id}`);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to create job."),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Modal title="New job" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Customer">
          <select
            required
            className={inputClass}
            value={customerId}
            onChange={(e) => {
              setCustomerId(e.target.value);
              setVesselId("");
            }}
          >
            <option value="" disabled>
              Select a customer…
            </option>
            {(customersQuery.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {customerName(c)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Vessel (optional)">
          <select
            className={inputClass}
            value={vesselId}
            onChange={(e) => setVesselId(e.target.value)}
            disabled={!customerId}
          >
            <option value="">No specific vessel</option>
            {(vesselsQuery.data ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {v.name ?? (`${v.make ?? ""} ${v.model ?? ""}`.trim() || "Unnamed vessel")}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Title">
          <input required className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Description">
          <textarea
            className={inputClass}
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <Field label="Scheduled at (optional)">
          <input
            type="datetime-local"
            className={inputClass}
            value={scheduledAt}
            onChange={(e) => setScheduledAt(e.target.value)}
          />
        </Field>
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending || !customerId || !title}>
            {mutation.isPending ? "Creating…" : "Create job"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
