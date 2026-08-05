import { useCallback, useEffect, useState } from "react";
import {
  enqueueAction,
  listQueuedActions,
  newIdempotencyKey,
  replayQueue,
  type PendingAction,
  type PendingActionKind,
} from "../lib/offlineQueue";
import { sendFieldAction } from "../lib/fieldSync";

export interface UseOfflineQueueResult {
  /** Number of actions still waiting to sync. */
  pendingCount: number;
  /** True while a replay attempt is in flight. */
  syncing: boolean;
  /** Queue a field action (clock in/out, attachment). Returns immediately;
   * the action is written to IndexedDB and a replay is attempted right
   * away in case we're actually online (the common case -- most actions
   * succeed on the first try and never sit in the queue at all). */
  enqueue: (kind: PendingActionKind, jobId: string, payload: Record<string, unknown>) => Promise<void>;
  /** Manually trigger a replay (also happens automatically on `online` and
   * on mount, i.e. "next app open"). */
  syncNow: () => Promise<void>;
}

/**
 * The offline action queue's React binding (Phase 12): wraps
 * src/lib/offlineQueue.ts + src/lib/fieldSync.ts with automatic replay on
 * the browser's `online` event and once on mount (covering "app was closed
 * while offline, reopened later with connectivity already restored" --
 * the `online` event alone wouldn't fire in that case since the app starts
 * already online).
 */
export function useOfflineQueue(): UseOfflineQueueResult {
  const [pendingCount, setPendingCount] = useState(0);
  const [syncing, setSyncing] = useState(false);

  const refreshCount = useCallback(async () => {
    const queued = await listQueuedActions();
    setPendingCount(queued.length);
  }, []);

  const syncNow = useCallback(async () => {
    setSyncing(true);
    try {
      // Loop until nothing succeeds anymore, so a queue of N items doesn't
      // require N separate "online" events to fully drain -- replayQueue
      // stops at the first failure, so keep calling it while progress is
      // being made.
      for (;;) {
        const before = (await listQueuedActions()).length;
        if (before === 0) break;
        const result = await replayQueue(sendFieldAction);
        await refreshCount();
        if (result.succeeded.length === 0) break;
        const after = (await listQueuedActions()).length;
        if (after === 0 || after === before) break;
      }
    } finally {
      setSyncing(false);
    }
  }, [refreshCount]);

  useEffect(() => {
    // Scheduled via a timer callback rather than calling the async
    // functions directly in the effect body -- see useFieldJobs.ts for why.
    const timer = setTimeout(() => {
      void refreshCount();
      void syncNow();
    }, 0);
    const onOnline = () => void syncNow();
    window.addEventListener("online", onOnline);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("online", onOnline);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const enqueue = useCallback(
    async (kind: PendingActionKind, jobId: string, payload: Record<string, unknown>) => {
      const action: PendingAction = {
        idempotencyKey: newIdempotencyKey(),
        kind,
        jobId,
        payload,
        createdAt: new Date().toISOString(),
        attempts: 0,
      };
      await enqueueAction(action);
      await refreshCount();
      // Try to send immediately -- if we're online this resolves instantly
      // and the item never visibly sits in "pending sync" state.
      void syncNow();
    },
    [refreshCount, syncNow],
  );

  return { pendingCount, syncing, enqueue, syncNow };
}
