/**
 * Offline action queue ("outbox") for the technician field app (Phase 12).
 *
 * IDEMPOTENCY APPROACH (documented per the Phase 12 spec):
 * Every queued action is stamped with a client-generated `idempotencyKey`
 * (a UUID, minted at the moment the technician performs the action -- not
 * at replay time). That same key is sent to the backend on every attempt,
 * in the JSON body for POST /jobs/{id}/attachments and the clock-in/out
 * routes (see app/services/field_app.py), which persists it in a unique
 * partial index per (company_id, idempotency_key) and returns the
 * already-created row instead of erroring or duplicating if it sees the
 * same key twice. This makes it safe to:
 *   - retry a request that failed for a network reason but may have
 *     actually succeeded server-side,
 *   - replay the entire queue again if the app is closed mid-sync and
 *     reopened before all items finished, and
 *   - accidentally double-fire a replay (e.g. both the `online` event and
 *     an app-open check firing back to back).
 * The queue itself also removes an action from IndexedDB as soon as its
 * request succeeds, so under normal conditions nothing is ever resent --
 * the idempotency key is a safety net for the abnormal cases above, not
 * the primary de-duplication mechanism.
 *
 * ORDERING: actions are replayed strictly in the order they were enqueued
 * (oldest `createdAt` first), one at a time -- important because, e.g., a
 * clock-in must reach the server before its corresponding clock-out.
 */
import { getAllItems, deleteItem, put, PENDING_ACTIONS_STORE } from "./offlineDb";

/** Max age for a queued offline action before it is purged client-side
 * (marine threat model Scenario 1 #3 / Scenario 3 #1). Server also rejects
 * replays whose client_queued_at exceeds offline_queue_max_age_seconds. */
export const MAX_QUEUE_AGE_MS = 7 * 24 * 60 * 60 * 1000;

export type PendingActionKind =
  | "clock_in"
  | "clock_out"
  | "attachment";

export interface PendingAction {
  idempotencyKey: string;
  kind: PendingActionKind;
  jobId: string;
  /** Arbitrary JSON payload appropriate to `kind`; sent as-is (plus the
   * idempotency key) to the corresponding endpoint. */
  payload: Record<string, unknown>;
  createdAt: string;
  /** Number of failed replay attempts so far, for surfacing "stuck" items. */
  attempts: number;
  lastError?: string;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Fallback for environments without crypto.randomUUID (older Safari/jsdom
  // without the polyfill) -- not cryptographically strong, but uniqueness
  // (not unguessability) is all that's required here.
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function enqueueAction(
  action: Omit<PendingAction, "attempts" | "createdAt"> & { createdAt?: string },
): Promise<PendingAction> {
  const full: PendingAction = {
    ...action,
    attempts: 0,
    createdAt: action.createdAt ?? new Date().toISOString(),
  };
  await put(PENDING_ACTIONS_STORE, full);
  return full;
}

export async function listQueuedActions(): Promise<PendingAction[]> {
  const items = await getAllItems<PendingAction>(PENDING_ACTIONS_STORE);
  return items.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export function isQueuedActionStale(
  action: PendingAction,
  nowMs: number = Date.now(),
): boolean {
  const created = Date.parse(action.createdAt);
  if (Number.isNaN(created)) return true;
  return nowMs - created > MAX_QUEUE_AGE_MS;
}

/** Drop actions older than MAX_QUEUE_AGE_MS. Returns how many were removed.
 * Called opportunistically on replay so a device that sat offline for weeks
 * does not forever retain (and eventually push) ancient customer payloads. */
export async function purgeStaleQueuedActions(
  nowMs: number = Date.now(),
): Promise<number> {
  const queued = await listQueuedActions();
  let removed = 0;
  for (const action of queued) {
    if (isQueuedActionStale(action, nowMs)) {
      await removeQueuedAction(action.idempotencyKey);
      removed += 1;
    }
  }
  return removed;
}

export async function removeQueuedAction(idempotencyKey: string): Promise<void> {
  await deleteItem(PENDING_ACTIONS_STORE, idempotencyKey);
}

/** A sender executes exactly one action against the backend and either
 * resolves (success -> the item is removed from the queue) or throws
 * (failure -> the item stays queued, attempts is incremented). Injected
 * rather than hard-coded so this module has no direct dependency on the
 * API client and is trivially unit-testable. */
export type ActionSender = (action: PendingAction) => Promise<void>;

export interface ReplayResult {
  succeeded: string[];
  failed: string[];
}

/**
 * Replays every queued action in order, stopping at the first failure so a
 * later action never jumps ahead of an earlier one that is still failing
 * (preserves in-order delivery, e.g. clock-in before clock-out on the same
 * job). Returns which idempotency keys succeeded vs. the one (if any) that
 * failed and halted the run.
 */
export async function replayQueue(send: ActionSender): Promise<ReplayResult> {
  // Drop hopelessly old items before attempting network I/O.
  await purgeStaleQueuedActions();
  const queued = await listQueuedActions();
  const succeeded: string[] = [];
  const failed: string[] = [];

  for (const action of queued) {
    try {
      await send(action);
      await removeQueuedAction(action.idempotencyKey);
      succeeded.push(action.idempotencyKey);
    } catch (err) {
      failed.push(action.idempotencyKey);
      await put(PENDING_ACTIONS_STORE, {
        ...action,
        attempts: action.attempts + 1,
        lastError: err instanceof Error ? err.message : String(err),
      });
      break;
    }
  }

  return { succeeded, failed };
}
