import { useMemo, useState } from "react";
import { useAuth } from "../context/auth";
import type { DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { customersApi, jobsApi, usersApi } from "../lib/services";
import { ApiError } from "../lib/api";
import { useLocationPing } from "../hooks/useLocationPing";
import { DispatchMap } from "../components/DispatchMap";
import { Badge, Card, ErrorBanner, Spinner } from "../components/ui";
import { JOB_STATUS_LABELS } from "../lib/jobStateMachine";
import type { Job, TeamMember } from "../types/api";

/** Active (not completed/canceled) jobs are the ones worth dispatching. */
function isBoardable(job: Job): boolean {
  return job.status === "scheduled" || job.status === "in_progress" || job.status === "on_hold";
}

const UNASSIGNED_COLUMN = "unassigned";

/**
 * Phase 11 live dispatch board: a drag-and-drop column-per-technician view
 * (native HTML5 DnD, no extra library) sitting on top of the *same*
 * `POST /jobs/{id}/assign` endpoint the Phase 7 ranked-suggestions flow on
 * JobDetailPage already uses -- dragging a job onto a technician's column is
 * just a friendlier way to call the one assignment mechanism the backend
 * has. Below the board, a free OpenStreetMap/Leaflet map plots technician
 * positions (live ping, else static home base) and job/customer locations.
 */
export function DispatchBoardPage() {
  const { user } = useAuth();
  const locationPing = useLocationPing(user);
  const queryClient = useQueryClient();
  const [dragJobId, setDragJobId] = useState<string | null>(null);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);

  const jobsQuery = useQuery({ queryKey: ["jobs", "dispatch-board"], queryFn: () => jobsApi.list() });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: () => usersApi.list() });
  const customersQuery = useQuery({ queryKey: ["customers"], queryFn: () => customersApi.list() });
  const locationsQuery = useQuery({
    queryKey: ["users", "technician-locations"],
    queryFn: () => usersApi.technicianLocations(),
    // Refresh periodically so the map reflects new pings without a manual reload.
    refetchInterval: 60_000,
  });

  const assignMutation = useMutation({
    mutationFn: ({ jobId, technicianId }: { jobId: string; technicianId: string | null }) =>
      jobsApi.assign(jobId, technicianId),
    onSuccess: () => {
      setAssignError(null);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => setAssignError(err instanceof ApiError ? err.message : "Failed to assign job."),
  });

  const technicians = useMemo(
    () => (usersQuery.data ?? []).filter((u): u is TeamMember => u.role === "technician" && u.is_active),
    [usersQuery.data],
  );

  const boardableJobs = useMemo(
    () => (jobsQuery.data ?? []).filter(isBoardable),
    [jobsQuery.data],
  );

  const customersById = useMemo(() => {
    const map = new Map((customersQuery.data ?? []).map((c) => [c.id, c]));
    return map;
  }, [customersQuery.data]);

  function jobsFor(technicianId: string | null): Job[] {
    return boardableJobs.filter((j) => j.technician_id === technicianId);
  }

  function handleDragStart(jobId: string) {
    return (e: DragEvent<HTMLDivElement>) => {
      setDragJobId(jobId);
      e.dataTransfer.setData("text/plain", jobId);
      e.dataTransfer.effectAllowed = "move";
    };
  }

  function handleDrop(technicianId: string | null) {
    return (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOverColumn(null);
      const jobId = e.dataTransfer.getData("text/plain") || dragJobId;
      setDragJobId(null);
      if (!jobId) return;
      const job = boardableJobs.find((j) => j.id === jobId);
      if (!job || job.technician_id === technicianId) return;
      assignMutation.mutate({ jobId, technicianId });
    };
  }

  const isLoading = jobsQuery.isLoading || usersQuery.isLoading || customersQuery.isLoading;
  const isError = jobsQuery.isError || usersQuery.isError || customersQuery.isError;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Dispatch board</h1>
        <p className="mt-1 text-sm text-slate-500">
          Drag a job into a technician's column to assign it. This calls the same
          assignment endpoint as the ranked suggestions on a job's detail page.
        </p>
        {user?.role === "technician" && <LocationPingStatusBanner status={locationPing.status} />}
      </div>

      {assignError && <ErrorBanner message={assignError} />}
      {isLoading && <Spinner label="Loading dispatch board…" />}
      {isError && <ErrorBanner message="Failed to load the dispatch board." />}

      {!isLoading && !isError && (
        <div
          className="grid gap-4"
          style={{ gridTemplateColumns: `repeat(${technicians.length + 1}, minmax(220px, 1fr))` }}
        >
          <BoardColumn
            title="Unassigned"
            jobs={jobsFor(null)}
            isDragOver={dragOverColumn === UNASSIGNED_COLUMN}
            onDragStart={handleDragStart}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOverColumn(UNASSIGNED_COLUMN);
            }}
            onDragLeave={() => setDragOverColumn(null)}
            onDrop={handleDrop(null)}
          />
          {technicians.map((tech) => (
            <BoardColumn
              key={tech.id}
              title={tech.full_name ?? tech.email}
              jobs={jobsFor(tech.id)}
              isDragOver={dragOverColumn === tech.id}
              onDragStart={handleDragStart}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOverColumn(tech.id);
              }}
              onDragLeave={() => setDragOverColumn(null)}
              onDrop={handleDrop(tech.id)}
            />
          ))}
        </div>
      )}

      <div>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">Live map</h2>
        {locationsQuery.isLoading && <Spinner label="Loading technician locations…" />}
        {locationsQuery.isError && (
          <ErrorBanner message="Failed to load technician locations." />
        )}
        {locationsQuery.data && !customersQuery.isLoading && (
          <Card className="overflow-hidden">
            <DispatchMap
              technicianLocations={locationsQuery.data}
              jobs={boardableJobs}
              customersById={customersById}
            />
          </Card>
        )}
      </div>
    </div>
  );
}

function LocationPingStatusBanner({ status }: { status: string }) {
  const text: Record<string, string> = {
    idle: "",
    unsupported: "Your browser doesn't support location sharing.",
    "requesting-permission": "Requesting location permission…",
    denied: "Location permission denied — your position won't appear on the dispatch map.",
    active: "Sharing your live location while this tab is open.",
    error: "Couldn't share your location just now. Will retry automatically.",
  };
  const message = text[status] ?? "";
  if (!message) return null;
  return (
    <p className="mt-2 text-xs text-slate-400" data-testid="location-ping-status">
      {message}{" "}
      {status === "active" && (
        <span title="Best-effort while this tab is open, not true background tracking.">
          (best-effort, tab must stay open)
        </span>
      )}
    </p>
  );
}

function BoardColumn({
  title,
  jobs,
  isDragOver,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  title: string;
  jobs: Job[];
  isDragOver: boolean;
  onDragStart: (jobId: string) => (e: DragEvent<HTMLDivElement>) => void;
  onDragOver: (e: DragEvent<HTMLDivElement>) => void;
  onDragLeave: () => void;
  onDrop: (e: DragEvent<HTMLDivElement>) => void;
}) {
  return (
    <div
      className={`flex min-h-[200px] flex-col gap-2 rounded-lg border-2 p-3 transition-colors ${
        isDragOver ? "border-slate-400 bg-slate-100" : "border-dashed border-slate-200 bg-slate-50"
      }`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      data-testid={`board-column-${title}`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
        <Badge tone="slate">{jobs.length}</Badge>
      </div>
      <div className="flex flex-col gap-2">
        {jobs.map((job) => (
          <div
            key={job.id}
            draggable
            onDragStart={onDragStart(job.id)}
            data-testid={`board-job-${job.id}`}
            className="cursor-grab rounded-md border border-slate-200 bg-white px-3 py-2 shadow-sm active:cursor-grabbing"
          >
            <Link
              to={`/jobs/${job.id}`}
              className="text-sm font-medium text-slate-900 hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {job.title}
            </Link>
            <div className="mt-1 flex items-center gap-2">
              <Badge tone={job.status === "on_hold" ? "amber" : "blue"}>
                {JOB_STATUS_LABELS[job.status]}
              </Badge>
              <span className="text-xs text-slate-400">
                {job.scheduled_at ? new Date(job.scheduled_at).toLocaleDateString() : "Unscheduled"}
              </span>
            </div>
          </div>
        ))}
        {jobs.length === 0 && <p className="text-xs text-slate-400">No jobs.</p>}
      </div>
    </div>
  );
}
