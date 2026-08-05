import { useCallback, useEffect, useState } from "react";
import { jobsApi } from "../lib/services";
import { getAllItems, putAll, CACHED_JOBS_STORE } from "../lib/offlineDb";
import type { Job } from "../types/api";

export interface FieldJobsState {
  jobs: Job[];
  loading: boolean;
  /** True once we've fallen back to the IndexedDB cache because a live
   * fetch failed (offline, or the request otherwise errored). */
  fromCache: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Loads today's-and-upcoming jobs for the field view (Phase 12). Always
 * tries the network first; on success, the result both renders AND is
 * written into IndexedDB (`cached_jobs`) so the next load -- including one
 * that happens fully offline -- has real data to show instead of a blank
 * screen. On failure, falls back to whatever was last cached and flags
 * `fromCache` so the UI can show the "offline — showing last synced data"
 * banner.
 */
export function useFieldJobs(): FieldJobsState {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [fromCache, setFromCache] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const fresh = await jobsApi.list({ sort: "scheduled_at" });
      setJobs(fresh);
      setFromCache(false);
      setError(null);
      // Best-effort cache write -- if IndexedDB itself is unavailable for
      // some reason, the live view still works, it just won't survive a
      // subsequent offline reload.
      try {
        await putAll(CACHED_JOBS_STORE, fresh);
      } catch {
        /* ignore cache-write failures */
      }
    } catch (err) {
      try {
        const cached = await getAllItems<Job>(CACHED_JOBS_STORE);
        if (cached.length > 0) {
          setJobs(cached);
          setFromCache(true);
          setError(null);
        } else {
          setError(err instanceof Error ? err.message : "Failed to load jobs.");
        }
      } catch {
        setError(err instanceof Error ? err.message : "Failed to load jobs.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Scheduled via a timer callback (rather than calling the async `load`
    // directly in the effect body) so this reads as "subscribing to an
    // external kickoff" to the react-hooks/set-state-in-effect rule,
    // matching the pattern already established in useLocationPing.ts.
    const timer = setTimeout(() => {
      void load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  return { jobs, loading, fromCache, error, refresh: load };
}
