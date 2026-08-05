import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useFieldJobs } from "../hooks/useFieldJobs";
import { useOnlineStatus } from "../hooks/useOnlineStatus";
import { useOfflineQueue } from "../hooks/useOfflineQueue";
import { InstallAppBanner } from "../components/InstallAppBanner";
import { SignaturePad } from "../components/SignaturePad";
import { Badge, Card, ErrorBanner, Spinner } from "../components/ui";
import { JOB_STATUS_LABELS } from "../lib/jobStateMachine";
import type { Job } from "../types/api";

/**
 * Dedicated technician field view (Phase 12), deliberately NOT a responsive
 * reflow of the admin job board: single column, today-forward jobs only,
 * tap straight into a job for the handful of actions a tech needs in a
 * boatyard with no signal (clock in/out, photo, signature). Everything on
 * this route reads from the IndexedDB job cache when offline and writes
 * field actions through the offline queue -- see useFieldJobs.ts and
 * useOfflineQueue.ts.
 */
export function FieldPage() {
  const { id } = useParams<{ id: string }>();
  if (id) return <FieldJobDetail jobId={id} />;
  return <FieldJobList />;
}

function OfflineStatusBanner({ fromCache, pendingCount, syncing }: { fromCache: boolean; pendingCount: number; syncing: boolean }) {
  const online = useOnlineStatus();
  if (!online || fromCache) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
        Offline — showing last synced data.
        {pendingCount > 0 && ` ${pendingCount} action${pendingCount === 1 ? "" : "s"} will sync when back online.`}
      </div>
    );
  }
  if (pendingCount > 0) {
    return (
      <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800">
        {syncing
          ? `Syncing ${pendingCount} pending action${pendingCount === 1 ? "" : "s"}…`
          : `${pendingCount} action${pendingCount === 1 ? "" : "s"} waiting to sync.`}
      </div>
    );
  }
  return null;
}

function todayOrLater(job: Job): boolean {
  if (!job.scheduled_at) return true;
  const scheduled = new Date(job.scheduled_at);
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  return scheduled >= startOfToday;
}

function FieldJobList() {
  const { user } = useAuth();
  const { jobs, loading, fromCache, error, refresh } = useFieldJobs();
  const { pendingCount, syncing } = useOfflineQueue();

  const myJobs = jobs
    .filter((j) => j.technician_id === user?.id)
    .filter((j) => j.status !== "completed" && j.status !== "canceled")
    .filter(todayOrLater)
    .sort((a, b) => (a.scheduled_at ?? "").localeCompare(b.scheduled_at ?? ""));

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 py-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">My jobs</h1>
        <button
          onClick={() => void refresh()}
          className="text-sm text-slate-500 hover:underline"
        >
          Refresh
        </button>
      </div>

      <InstallAppBanner />
      <OfflineStatusBanner fromCache={fromCache} pendingCount={pendingCount} syncing={syncing} />

      {loading && myJobs.length === 0 && <Spinner label="Loading your jobs…" />}
      {error && <ErrorBanner message={error} />}
      {!loading && myJobs.length === 0 && !error && (
        <p className="rounded-md border border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
          No jobs assigned to you right now.
        </p>
      )}

      <ul className="flex flex-col gap-3">
        {myJobs.map((job) => (
          <li key={job.id}>
            <Link
              to={`/field/${job.id}`}
              className="block rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm active:bg-slate-50"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-slate-900">{job.title}</span>
                <Badge tone={job.status === "in_progress" ? "blue" : "slate"}>
                  {JOB_STATUS_LABELS[job.status]}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-slate-500">
                {job.scheduled_at ? new Date(job.scheduled_at).toLocaleString() : "Unscheduled"}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FieldJobDetail({ jobId }: { jobId: string }) {
  const { jobs, loading, fromCache, error } = useFieldJobs();
  const { pendingCount, syncing, enqueue } = useOfflineQueue();
  const [showSignature, setShowSignature] = useState(false);
  const [clockState, setClockState] = useState<"idle" | "in" | "out">("idle");
  const [flash, setFlash] = useState<string | null>(null);

  const job = jobs.find((j) => j.id === jobId);

  async function handleClockIn() {
    if (!job) return;
    await enqueue("clock_in", job.id, {});
    setClockState("in");
    setFlash("Clock-in recorded — will sync when back online if needed.");
  }

  async function handleClockOut() {
    if (!job) return;
    await enqueue("clock_out", job.id, {});
    setClockState("out");
    setFlash("Clock-out recorded — will sync when back online if needed.");
  }

  async function handlePhotoSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !job) return;
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
    await enqueue("attachment", job.id, {
      kind: "photo",
      data: dataUrl,
      content_type: file.type || "image/jpeg",
    });
    setFlash("Photo queued — will sync when back online if needed.");
    e.target.value = "";
  }

  async function handleSignatureSave(dataUrl: string) {
    if (!job) return;
    await enqueue("attachment", job.id, {
      kind: "signature",
      data: dataUrl,
      content_type: "image/png",
    });
    setShowSignature(false);
    setFlash("Signature queued — will sync when back online if needed.");
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 py-6">
      <Link to="/field" className="text-sm text-slate-500 hover:underline">
        ← My jobs
      </Link>

      <InstallAppBanner />
      <OfflineStatusBanner fromCache={fromCache} pendingCount={pendingCount} syncing={syncing} />

      {loading && !job && <Spinner label="Loading job…" />}
      {error && !job && <ErrorBanner message={error} />}

      {job && (
        <>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">{job.title}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {job.scheduled_at ? new Date(job.scheduled_at).toLocaleString() : "Unscheduled"}
            </p>
            {job.description && <p className="mt-2 text-sm text-slate-700">{job.description}</p>}
          </div>

          {flash && (
            <div className="rounded-md border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-800">
              {flash}
            </div>
          )}

          <Card className="flex flex-col gap-3 p-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Time clock
            </h2>
            <div className="flex gap-2">
              <button
                onClick={() => void handleClockIn()}
                disabled={clockState === "in"}
                className="flex-1 rounded-md bg-slate-900 px-3 py-3 text-sm font-medium text-white disabled:bg-slate-300"
              >
                Clock in
              </button>
              <button
                onClick={() => void handleClockOut()}
                disabled={clockState !== "in"}
                className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-3 text-sm font-medium text-slate-900 disabled:text-slate-300"
              >
                Clock out
              </button>
            </div>
          </Card>

          <Card className="flex flex-col gap-3 p-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Photo</h2>
            <label className="flex cursor-pointer items-center justify-center rounded-md border border-dashed border-slate-300 px-3 py-6 text-sm text-slate-500">
              Tap to take or choose a photo
              <input
                type="file"
                accept="image/*"
                capture="environment"
                className="hidden"
                onChange={(e) => void handlePhotoSelected(e)}
              />
            </label>
          </Card>

          <Card className="flex flex-col gap-3 p-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
              Customer signature
            </h2>
            {showSignature ? (
              <SignaturePad
                onSave={(dataUrl) => void handleSignatureSave(dataUrl)}
                onCancel={() => setShowSignature(false)}
              />
            ) : (
              <button
                onClick={() => setShowSignature(true)}
                className="rounded-md border border-slate-300 bg-white px-3 py-3 text-sm font-medium text-slate-900"
              >
                Capture signature
              </button>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
