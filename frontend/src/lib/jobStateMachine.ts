import type { JobStatus, JobStatusTransitions } from "../types/api";

// Mirrors app/services/state_machines.py::JobSM.transitions exactly. This is
// UI-side gating only (which buttons to offer) — the backend is the real
// enforcement and re-validates every transition under a row lock.
export const JOB_STATUS_TRANSITIONS: JobStatusTransitions = {
  scheduled: ["in_progress", "canceled"],
  in_progress: ["on_hold", "completed", "canceled"],
  on_hold: ["in_progress", "canceled"],
  completed: [],
  canceled: [],
};

export function legalNextStatuses(current: JobStatus): JobStatus[] {
  return JOB_STATUS_TRANSITIONS[current] ?? [];
}

export function canTransition(current: JobStatus, target: JobStatus): boolean {
  return legalNextStatuses(current).includes(target);
}

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  scheduled: "Scheduled",
  in_progress: "In progress",
  on_hold: "On hold",
  completed: "Completed",
  canceled: "Canceled",
};
